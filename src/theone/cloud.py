from __future__ import annotations

import enum
import math
import random
import time

from theone import NeoError
from theone.colors import PALETTES, Color, ColorContent, ColorMode, ColorState
from theone.terminal import BLANK, Screen

"""
The digital rain simulation: a faithful port of neo's Cloud and Droplet classes.
"""


NONE = -1  # "unset" line marker (neo uses 0xFFFF)
CHAR_POOL_SIZE = 2048
GLITCH_POOL_SIZE = 1024

# CharLoc
MIDDLE, TAIL, HEAD = 0, 1, 2


def c_round(x: float) -> int:
    """C's round(): halves away from zero."""
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)


class ShadingMode(enum.IntEnum):
    RANDOM = 0
    DISTANCE_FROM_HEAD = 1


class BoldMode(enum.IntEnum):
    OFF = 0
    RANDOM = 1
    ALL = 2


class Charset(enum.IntFlag):
    NONE = 0x0
    ENGLISH_LETTERS = 0x1
    ENGLISH_DIGITS = 0x2
    ENGLISH_PUNCTUATION = 0x4
    KATAKANA = 0x8
    GREEK = 0x10
    CYRILLIC = 0x20
    ARABIC = 0x40
    HEBREW = 0x80
    BINARY = 0x100
    HEX = 0x200
    DEVANAGARI = 0x400
    BRAILLE = 0x800
    RUNIC = 0x1000
    DEFAULT = 0x7
    EXTENDED_DEFAULT = 0xE


CHARSET_NAMES: dict[str, Charset] = {
    "ascii": Charset.DEFAULT,
    "extended": Charset.EXTENDED_DEFAULT,
    "english": Charset.ENGLISH_LETTERS,
    "digits": Charset.ENGLISH_DIGITS,
    "dec": Charset.ENGLISH_DIGITS,
    "decimal": Charset.ENGLISH_DIGITS,
    "punc": Charset.ENGLISH_PUNCTUATION,
    "bin": Charset.BINARY,
    "binary": Charset.BINARY,
    "hex": Charset.HEX,
    "hexadecimal": Charset.HEX,
    "katakana": Charset.KATAKANA,
    "greek": Charset.GREEK,
    "cyrillic": Charset.CYRILLIC,
    "arabic": Charset.ARABIC,
    "hebrew": Charset.HEBREW,
    "devanagari": Charset.DEVANAGARI,
    "braille": Charset.BRAILLE,
    "runic": Charset.RUNIC,
}

UNICODE_RANGES: list[tuple[Charset, list[tuple[int, int]]]] = [
    (Charset.BINARY, [(48, 49)]),
    (Charset.HEX, [(48, 57), (65, 70)]),
    (Charset.ENGLISH_LETTERS, [(65, 90), (97, 122)]),
    (Charset.ENGLISH_DIGITS, [(48, 57)]),
    (Charset.ENGLISH_PUNCTUATION, [(33, 47), (58, 64), (91, 96), (123, 126)]),
    (Charset.KATAKANA, [(0xFF64, 0xFF9F)]),
    (Charset.GREEK, [(0x0370, 0x03FF)]),
    (Charset.CYRILLIC, [(0x0410, 0x044F)]),
    (Charset.ARABIC, [(0x0627, 0x0649)]),
    (Charset.HEBREW, [(0x0590, 0x05FF), (0xFB1D, 0xFB4F)]),
    (Charset.DEVANAGARI, [(0x0900, 0x097F)]),
    (Charset.BRAILLE, [(0x2800, 0x28FF)]),
    (Charset.RUNIC, [(0x16A0, 0x16FF)]),
]


class Droplet:
    """A single vertical string of characters."""

    __slots__ = (
        "alive",
        "col",
        "cp_idx",
        "cps",
        "end_line",
        "head_crawling",
        "head_cur",
        "head_put",
        "head_stop_time",
        "last_time",
        "length",
        "linger",
        "tail_crawling",
        "tail_cur",
        "tail_put",
    )  # fmt: skip

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.alive = False
        self.head_crawling = False
        self.tail_crawling = False
        self.col = NONE
        self.head_put = 0  # where we are advancing the head
        self.head_cur = 0  # where the head currently is (drawn)
        self.tail_put = NONE  # where we are advancing the tail
        self.tail_cur = 0  # the last empty line in this column
        self.end_line = NONE  # the head will not advance past this line
        self.cp_idx = 0  # index into the char pool
        self.length = 0
        self.cps = 0.0
        self.last_time = 0.0
        self.head_stop_time: float | None = None
        self.linger = 0.0  # seconds

    def fill(
        self,
        col: int,
        end_line: int,
        cp_idx: int,
        length: int,
        cps: float,
        linger: float,
    ):
        self.reset()
        self.col = col
        self.end_line = end_line
        self.cp_idx = cp_idx
        self.length = length
        self.cps = cps
        self.linger = linger

    def activate(self, t: float) -> None:
        self.alive = True
        self.head_crawling = True
        self.tail_crawling = True
        self.last_time = t

    def advance(self, t: float, cloud: Cloud) -> None:
        n = c_round(self.cps * (t - self.last_time))
        if n <= 0:
            return

        if self.head_crawling:
            self.head_put = min(self.head_put + n, self.end_line)
            # If the head reaches the end line, stop it and maybe the tail too
            if self.head_put == self.end_line:
                self.head_crawling = False
                if self.head_stop_time is None:
                    self.head_stop_time = t
                    if self.linger > 0:
                        self.tail_crawling = False

        if self.tail_crawling and (
            self.head_put >= self.length or self.head_put >= self.end_line
        ):
            self.tail_put = self.tail_put + n if self.tail_put != NONE else n
            self.tail_put = min(self.tail_put, self.end_line)
            # If the tail advances far enough down the screen, allow other droplets to spawn
            thresh = cloud.lines // 4
            if self.tail_cur <= thresh < self.tail_put:
                cloud.col_can_spawn[self.col] = True

        # Restart the tail after lingering
        if (
            not self.tail_crawling
            and self.head_stop_time is not None
            and t - self.head_stop_time >= self.linger
        ):
            self.tail_crawling = True
        # Once the tail reaches the head, kill this droplet
        if self.tail_put == self.head_put:
            self.alive = False
        self.last_time = t

    def is_head_bright(self, t: float) -> bool:
        if self.head_crawling:
            return True
        return self.head_stop_time is not None and t - self.head_stop_time <= 0.1

    def increment_time(self, dt: float) -> None:
        self.last_time += dt
        if self.head_stop_time is not None:
            self.head_stop_time += dt


class MsgChr:
    __slots__ = ("col", "draw", "line", "val")

    def __init__(self, val: str) -> None:
        self.line = NONE
        self.col = NONE
        self.val = val
        self.draw = False


class Cloud:
    def __init__(
        self, screen: Screen, color_mode: ColorMode, default_to_ascii: bool
    ) -> None:
        self.screen = screen
        self.color_mode = color_mode
        self.colors = ColorState(color_mode)
        self.default_to_ascii = default_to_ascii
        self.rng = random.Random(0x1234567)

        self.lines = screen.lines
        self.cols = screen.cols
        self.droplets: list[Droplet] = []
        self.num_droplets = 0
        self.charset = Charset.NONE
        self.user_chars: list[str] = []
        self.char_pool: list[str] = []
        self.glitch_pool: list[str] = []
        self.glitch_pool_idx = 0
        self.glitch_map = bytearray()
        self.color_pair_map: list[int] = []
        self.droplet_density = 1.0
        self.droplets_per_sec = 5.0
        self.col_speed: list[float] = []
        self.col_num_droplets: list[int] = []
        self.col_can_spawn: list[bool] = []
        self.last_glitch_time = 0.0
        self.next_glitch_time = 0.0
        self.pause_time = 0.0
        self.last_spawn_time = 0.0
        self.chars_per_sec = 8.0
        self.shading_mode = ShadingMode.RANDOM
        self.force_draw_everything = False
        self.paused = False
        self.full_width = False
        self.color = Color.GREEN
        self.default_background = False
        self.async_ = False
        self.raining = True
        self.show_time = True  # date/time overlay (drawn by the CLI)
        self.bold_mode = BoldMode.RANDOM
        self.glitch_pct = 0.1
        self.glitch_low_ms = 300
        self.glitch_high_ms = 400
        self.glitchy = True
        self.short_pct = 0.5
        self.die_early_pct = 0.3333333
        self.linger_low_ms = 1
        self.linger_high_ms = 3000
        self.max_droplets_per_column = 3
        self.message: list[MsgChr] = []
        self.num_color_pairs = 7
        self.pair_lo = 2
        self.pair_hi = 5
        self.user_colors: list[ColorContent] = []
        # per-frame glitch flicker state
        self._bright = False
        self._dim = False

        if color_mode is not ColorMode.MONO:
            self.set_color(Color.GREEN)
        else:
            self.screen.set_palette(self.colors.sgr)

    # ------------------------------------------------------------------
    # main per-frame work
    # ------------------------------------------------------------------
    def rain(self) -> None:
        if self.paused:
            return
        t = time.monotonic()
        self.spawn_droplets(t)

        force = self.force_draw_everything
        if force:
            self.screen.clear()

        time_for_glitch = self.glitchy and t >= self.next_glitch_time
        self._bright = self._is_bright(t)
        self._dim = self._is_dim(t)
        quarter = self.lines // 4
        for d in self.droplets:
            if not d.alive:
                continue
            d.advance(t, self)
            if time_for_glitch:
                self._do_glitch(d)
            self._draw_droplet(d, t, force)
            if not d.alive:
                col = d.col
                self.col_num_droplets[col] -= 1
                # If the droplet dies very early, then mark the column as free
                if d.tail_put <= quarter:
                    self.col_can_spawn[col] = True

        if self.message:
            self._calc_message()
            self._draw_message()

        if time_for_glitch:
            self.last_glitch_time = t
            self.next_glitch_time = t + self._rand_glitch_ms() / 1000.0
        self.force_draw_everything = False

    def _draw_droplet(self, d: Droplet, t: float, draw_everything: bool) -> None:
        put = self.screen.put
        col = d.col
        start = 0
        if d.tail_put != NONE:
            # Delete the very end of the tail
            for line in range(d.tail_cur, d.tail_put + 1):
                put(line, col, " ", BLANK)
            d.tail_cur = d.tail_put
            start = d.tail_put + 1

        lines = self.lines
        char_pool = self.char_pool
        color_map = self.color_pair_map
        glitchy = self.glitchy
        glitch_map = self.glitch_map
        bold_mode = self.bold_mode
        gradient = self.shading_mode == ShadingMode.DISTANCE_FROM_HEAD
        n_pairs = self.num_color_pairs
        bright, dim = self._bright, self._dim
        head_put, head_cur, tail_put = d.head_put, d.head_cur, d.tail_put
        end_line, cp_idx, length = d.end_line, d.cp_idx, d.length
        head_bright = d.is_head_bright(t)
        tail_line = tail_put + 1 if tail_put != NONE else NONE
        # In gradient mode neo redraws every cell each frame; a cell's colour only
        # depends on the head position, so it's only necessary when the head moved.
        skip_ok = not draw_everything and (not gradient or head_put == head_cur)
        base = col * lines

        for line in range(start, head_put + 1):
            idx = base + line
            glitched = glitchy and glitch_map[idx]
            if line == head_put and head_bright:
                cl = HEAD
            elif line == tail_line:
                cl = TAIL
            else:
                cl = MIDDLE
            # No need to redraw non-glitched chars between the tail and the drawn head
            if (
                cl == MIDDLE
                and skip_ok
                and line < head_cur
                and not glitched
                and line != end_line
            ):
                continue

            val = char_pool[(cp_idx + line) % CHAR_POOL_SIZE]
            if cl == TAIL:
                pair, bold = 1, False
            elif cl == HEAD:
                pair, bold = n_pairs, True
            else:
                bold = bold_mode == BoldMode.RANDOM and ((line ^ ord(val)) & 1) == 1
                if gradient:
                    pair = n_pairs - c_round((head_put - line) / length * (n_pairs - 1))
                else:
                    pair = color_map[idx]
                if glitched:
                    if bright:
                        pair += 1
                        bold = True
                    elif dim:
                        pair -= 1
                        bold = False
                pair = max(min(pair, n_pairs - 1), 1)
            if bold_mode == BoldMode.OFF:
                bold = False
            elif bold_mode == BoldMode.ALL:
                bold = True
            put(line, col, val, (pair << 1) | bold)
        d.head_cur = head_put

    # ------------------------------------------------------------------
    # spawning
    # ------------------------------------------------------------------
    def spawn_droplets(self, t: float) -> None:
        to_spawn = min(
            int((t - self.last_spawn_time) * self.droplets_per_sec), self.num_droplets
        )
        if to_spawn <= 0:
            return
        rng = self.rng
        droplets = self.droplets
        idx = 0
        spawned = 0
        last_col = self.cols - 1
        for _ in range(to_spawn):
            col = rng.randint(0, last_col)
            if self.full_width:
                col &= ~1
            if (
                not self.col_can_spawn[col]
                or self.col_num_droplets[col] >= self.max_droplets_per_column
            ):
                continue
            while idx < self.num_droplets and droplets[idx].alive:
                idx += 1
            if idx >= self.num_droplets:
                break
            d = droplets[idx]
            self._fill_droplet(d, col)
            d.activate(t)
            self.col_can_spawn[col] = False
            self.col_num_droplets[col] += 1
            spawned += 1
        if spawned:
            self.last_spawn_time = t

    def _fill_droplet(self, d: Droplet, col: int) -> None:
        rng = self.rng
        end_line = self.lines - 1
        if rng.random() <= self.die_early_pct:
            end_line = rng.randint(0, max(self.lines - 2, 0))
        cp_idx = rng.randint(0, CHAR_POOL_SIZE - 1)
        length = self.lines
        if rng.random() <= self.short_pct:
            length = rng.randint(1, max(self.lines - 2, 1))
        linger = 0.001
        if end_line <= length:
            linger = rng.randint(self.linger_low_ms, self.linger_high_ms) / 1000.0
        speed = self.col_speed[col] * self.chars_per_sec
        d.fill(col, end_line, cp_idx, length, speed, linger)

    # ------------------------------------------------------------------
    # glitching
    # ------------------------------------------------------------------
    def _rand_glitch_ms(self) -> int:
        return self.rng.randint(self.glitch_low_ms, self.glitch_high_ms)

    def _do_glitch(self, d: Droplet) -> None:
        start = d.tail_put + 1 if d.tail_put != NONE else 0
        base = d.col * self.lines
        gmap = self.glitch_map
        pool, gpool = self.char_pool, self.glitch_pool
        for line in range(start, d.head_put + 1):
            if gmap[base + line]:
                pool[(d.cp_idx + line) % CHAR_POOL_SIZE] = gpool[self.glitch_pool_idx]
                self.glitch_pool_idx = (self.glitch_pool_idx + 1) % GLITCH_POOL_SIZE

    def _is_bright(self, t: float) -> bool:
        if t < self.last_glitch_time:
            return False
        span = self.next_glitch_time - self.last_glitch_time
        if span <= 0:
            return False
        return (t - self.last_glitch_time) / span <= 0.25

    def _is_dim(self, t: float) -> bool:
        if t > self.next_glitch_time:
            return True
        span = self.next_glitch_time - self.last_glitch_time
        if span <= 0:
            return True
        return (t - self.last_glitch_time) / span >= 0.75

    def _fill_glitch_map(self) -> None:
        if not self.glitchy:
            return
        rnd = self.rng.random
        pct = self.glitch_pct
        self.glitch_map = bytearray(rnd() <= pct for _ in range(self.lines * self.cols))

    def _fill_color_map(self) -> None:
        lo, hi = self.pair_lo, self.pair_hi
        randint = self.rng.randint
        self.color_pair_map = [randint(lo, hi) for _ in range(self.lines * self.cols)]

    # ------------------------------------------------------------------
    # state changes
    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.screen.resize()
        self.lines = self.screen.lines
        self.cols = self.screen.cols

        self.num_droplets = c_round(1.5 * self.cols)
        self.droplets = [Droplet() for _ in range(self.num_droplets)]

        self.rng.seed(0x1234567)
        self._update_pair_range()
        self._fill_glitch_map()
        self._fill_color_map()

        self._update_droplets_per_sec()
        self.col_speed = [1.0] * self.cols
        self.col_num_droplets = [0] * self.cols
        self.col_can_spawn = [True] * self.cols
        self.set_column_speeds()
        self.update_droplet_speeds()

        if self.message:
            self._reset_message()

        now = time.monotonic()
        self.last_glitch_time = now
        self.next_glitch_time = now + self._rand_glitch_ms() / 1000.0
        self.last_spawn_time = now

    def init_chars(self) -> None:
        self.glitch_pool_idx = 0
        if self.charset == Charset.NONE and not self.user_chars:
            self.charset = (
                Charset.DEFAULT if self.default_to_ascii else Charset.EXTENDED_DEFAULT
            )
        chars: list[str] = []
        for cs, segments in UNICODE_RANGES:
            if self.charset & cs:
                for lo, hi in segments:
                    chars.extend(chr(c) for c in range(lo, hi + 1))
        chars.extend(self.user_chars)
        choice = self.rng.choice
        self.char_pool = [choice(chars) for _ in range(CHAR_POOL_SIZE)]
        self.glitch_pool = [choice(chars) for _ in range(GLITCH_POOL_SIZE)]

    def add_chars(self, begin: int, end: int) -> None:
        if begin > end:
            raise NeoError("--chars: characters given in wrong order")
        self.user_chars.extend(chr(c) for c in range(begin, end + 1))

    def _update_droplets_per_sec(self) -> None:
        droplet_seconds = self.lines / self.chars_per_sec
        self.droplets_per_sec = self.cols * self.droplet_density / droplet_seconds

    def set_chars_per_sec(self, cps: float) -> None:
        self.chars_per_sec = cps
        self._update_droplets_per_sec()
        self.set_column_speeds()
        self.update_droplet_speeds()

    def set_droplet_density(self, density: float) -> None:
        self.droplet_density = density
        self._update_droplets_per_sec()

    def set_column_speeds(self) -> None:
        if self.async_:
            uniform = self.rng.uniform
            self.col_speed = [uniform(0.3333333, 1.0) for _ in self.col_speed]
        else:
            self.col_speed = [1.0] * len(self.col_speed)

    def update_droplet_speeds(self) -> None:
        for d in self.droplets:
            if d.alive:
                d.cps = self.col_speed[d.col] * self.chars_per_sec

    def set_glitch_pct(self, pct: float) -> None:
        self.glitch_pct = pct
        self._fill_glitch_map()

    def set_shading_mode(self, mode: ShadingMode) -> None:
        self.shading_mode = mode
        self.force_draw_everything = True

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        if self.paused:
            self.pause_time = time.monotonic()
        else:
            elapsed = time.monotonic() - self.pause_time
            self.last_spawn_time += elapsed
            for d in self.droplets:
                if d.alive:
                    d.increment_time(elapsed)

    def set_message(self, msg: str) -> None:
        self.message = [MsgChr(c) for c in msg]

    def _update_pair_range(self) -> None:
        n = self.num_color_pairs
        if n < 3:
            self.pair_lo, self.pair_hi = 1, 1
        elif n == 3:
            self.pair_lo, self.pair_hi = 2, 2
        else:
            self.pair_lo, self.pair_hi = 2, n - 2

    def set_color(self, color: Color) -> None:
        self.color = color
        cs = self.colors
        mode = self.color_mode
        bg = 0 if mode is ColorMode.COLOR16 else 16
        if self.default_background:
            bg = -1

        if color is Color.USER:
            if mode is ColorMode.TRUECOLOR:
                for cc in self.user_colors:
                    if cc.has_rgb:
                        cs.init_color(cc.color, cc.r, cc.g, cc.b)
            bg = self.user_colors[0].color
            fgs = [cc.color for cc in self.user_colors[1:]]
        else:
            pal = PALETTES[color]
            if mode is ColorMode.TRUECOLOR:
                for idx, (r, g, b) in pal.truecolor.items():
                    cs.init_color(idx, r, g, b)
            fgs = list(pal.c16 if mode is ColorMode.COLOR16 else pal.c256)

        cs.bg = bg
        cs.pairs = {i + 1: fg for i, fg in enumerate(fgs)}
        self.num_color_pairs = len(fgs)
        self.screen.set_palette(cs.sgr)

        self._update_pair_range()
        self._fill_color_map()
        self.force_draw_everything = True

    # ------------------------------------------------------------------
    # message
    # ------------------------------------------------------------------
    def _reset_message(self) -> None:
        """Position message chars centred between the first and last quarter of the screen."""
        first_col = self.cols // 4
        last_col = 3 * self.cols // 4
        chars_per_col = last_col - first_col + 1
        msg_lines = len(self.message) // chars_per_col + 1
        first_line = self.lines // 2 - msg_lines // 2

        remaining = len(self.message)
        line = first_line
        col = first_col
        if remaining < chars_per_col:
            col += (chars_per_col - remaining) // 2
        for m in self.message:
            m.draw = False
            if 0 <= line < self.lines:
                m.line, m.col = line, col
            else:
                m.line, m.col = NONE, NONE
            if col == last_col:
                line += 1
                col = first_col
                if remaining < chars_per_col:
                    col += (chars_per_col - remaining) // 2
            else:
                col += 1
            remaining -= 1

    def _calc_message(self) -> None:
        """Reveal message chars once rain has passed over their position."""
        char_at = self.screen.char_at
        for m in self.message:
            if m.line == NONE or m.col == NONE:
                break
            ch = char_at(m.line, m.col)
            if ch and ch != " ":
                m.draw = True

    def _draw_message(self) -> None:
        bold = self.bold_mode != BoldMode.OFF
        style = (self.num_color_pairs << 1) | bold
        put = self.screen.put
        for m in self.message:
            if m.draw:
                put(m.line, m.col, m.val, style)
