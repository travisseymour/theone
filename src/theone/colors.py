"""Colour palettes, colour modes and colour-file parsing (mirrors neo's cloud.cpp/neo.cpp)."""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from pathlib import Path

from theone import NeoError


class ColorMode(enum.Enum):
    MONO = 0
    COLOR16 = 16
    COLOR256 = 256
    TRUECOLOR = 32


class Color(enum.Enum):
    USER = "user"
    GREEN = "green"
    GREEN2 = "green2"
    GREEN3 = "green3"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"
    BLUE = "blue"
    CYAN = "cyan"
    GOLD = "gold"
    RAINBOW = "rainbow"
    PURPLE = "purple"
    PINK = "pink"
    PINK2 = "pink2"
    VAPORWAVE = "vaporwave"
    GRAY = "gray"


@dataclass(frozen=True)
class Palette:
    c16: tuple[int, ...]  # foreground colour codes in 16-colour mode (pairs 1..N)
    c256: tuple[int, ...]  # foreground colour codes in 256/truecolor mode (pairs 1..N)
    # init_color() overrides applied in truecolor mode: index -> (r, g, b) on a 0..1000 scale
    truecolor: dict[int, tuple[int, int, int]]


# Values copied verbatim from neo's Cloud::SetColor().
PALETTES: dict[Color, Palette] = {
    Color.GREEN: Palette(
        (10, 15),
        (234, 22, 28, 35, 78, 84, 159),
        {
            234: (71, 141, 83),
            22: (149, 243, 161),
            28: (188, 596, 318),
            35: (188, 714, 397),
            78: (227, 925, 561),
            84: (271, 973, 667),
            159: (667, 1000, 941),
        },
    ),
    Color.GOLD: Palette(
        (8, 3, 11, 15),
        (58, 94, 172, 178, 228, 230, 231),
        {
            58: (839, 545, 216),
            94: (905, 694, 447),
            172: (945, 831, 635),
            178: (1000, 922, 565),
            228: (1000, 953, 796),
            230: (976, 976, 968),
        },
    ),
    Color.GREEN2: Palette(
        (8, 2, 10, 15),
        (28, 34, 76, 84, 120, 157, 231),
        {
            28: (16, 180, 59),
            34: (59, 246, 117),
            76: (46, 512, 172),
            84: (262, 749, 332),
            120: (520, 945, 578),
            157: (676, 969, 758),
            231: (906, 1000, 898),
        },
    ),
    Color.GREEN3: Palette(
        (2, 15),
        (22, 28, 34, 70, 76, 82, 157),
        {
            22: (0, 373, 0),
            28: (0, 529, 0),
            34: (0, 686, 0),
            70: (373, 686, 0),
            76: (373, 843, 0),
            82: (373, 1000, 0),
            157: (686, 1000, 686),
        },
    ),
    Color.YELLOW: Palette((8, 11, 15), (100, 142, 184, 226, 227, 229, 230), {}),
    Color.RAINBOW: Palette(
        (9, 1, 11, 10, 12, 13), (196, 208, 226, 46, 21, 93, 201), {}
    ),
    Color.RED: Palette((1, 9, 15), (234, 52, 88, 124, 160, 196, 217), {}),
    # neo sets pair 4 twice (19 then 20); the second call wins.
    Color.BLUE: Palette((4, 12, 15), (234, 17, 18, 20, 21, 75, 159), {}),
    Color.CYAN: Palette((6, 14, 15), (24, 25, 31, 32, 38, 45, 159), {}),
    Color.ORANGE: Palette((1, 7), (52, 94, 130, 166, 202, 208, 231), {}),
    Color.PURPLE: Palette((5, 7), (60, 61, 62, 63, 69, 111, 225), {}),
    Color.PINK: Palette((13, 15), (133, 139, 176, 212, 218, 224, 231), {}),
    Color.PINK2: Palette((5, 13, 15), (145, 181, 217, 218, 224, 225, 231), {}),
    Color.VAPORWAVE: Palette(
        (5, 13, 11, 14, 15),
        (53, 54, 55, 134, 177, 219, 214, 220, 227, 229, 87, 123, 159, 195, 231),
        {},
    ),
    Color.GRAY: Palette((8, 7, 15), (234, 237, 240, 243, 246, 249, 251, 252, 231), {}),
}

# Key bindings for colours, from neo's HandleInput().
COLOR_KEYS: dict[str, Color] = {
    "1": Color.GREEN,
    "2": Color.GREEN2,
    "3": Color.GREEN3,
    "4": Color.GOLD,
    "5": Color.PINK2,
    "6": Color.RED,
    "7": Color.BLUE,
    "8": Color.CYAN,
    "9": Color.PURPLE,
    "0": Color.GRAY,
    "!": Color.RAINBOW,
    "@": Color.YELLOW,
    "#": Color.ORANGE,
    "$": Color.PINK,
    "%": Color.VAPORWAVE,
}

UNSET = 0x7FFF  # marks an RGB component that was not given in a colour file


@dataclass
class ColorContent:
    color: int
    r: int = UNSET
    g: int = UNSET
    b: int = UNSET

    @property
    def has_rgb(self) -> bool:
        return UNSET not in (self.r, self.g, self.b)


_INT_RE = re.compile(r"\s*([+-]?\d+)")
_COMMENT_STARTS = (";", "#", "/", "*", "@")


def _strtol(text: str) -> int:
    """Lenient integer parse like C's strtol(): leading int or 0."""
    m = _INT_RE.match(text)
    return int(m.group(1)) if m else 0


def _is_skippable(line: str) -> bool:
    return line in ("", "\n") or line.startswith(_COMMENT_STARTS)


def _parse_color_line(line: str, line_num: int, max_colors: int) -> ColorContent:
    cc = ColorContent(_strtol(line))
    if cc.color >= max_colors:
        raise NeoError(
            f"Bad color value ({cc.color}) on line {line_num} (max {max_colors - 1})"
        )
    if "," not in line:
        return cc  # a single 16/256 colour value
    tokens = line.split(",")
    rgb: list[int] = []
    for i in range(1, 4):
        if i >= len(tokens) or tokens[i] in ("", "\n"):
            raise NeoError(f"Color file line {line_num} does not have four components")
        val = _strtol(tokens[i])
        if not 0 <= val <= 1000:
            raise NeoError(f"Bad RGB component value ({val}) on line {line_num}")
        rgb.append(val)
    cc.r, cc.g, cc.b = rgb
    return cc


def parse_color_file(path: Path, max_colors: int, max_pairs: int) -> list[ColorContent]:
    latest_version = 1
    try:
        lines = path.read_text(errors="replace").splitlines(keepends=True)
    except OSError:
        raise NeoError(f"Could not read colorfile: {path}") from None

    idx = 0
    # Skip leading comments/blank lines, then look for the optional version string.
    while idx < len(lines) and _is_skippable(lines[idx]):
        idx += 1
    if idx >= len(lines):
        raise NeoError("Invalid color file")
    if "neo_color_version" in lines[idx]:
        parts = lines[idx].split()
        if len(parts) < 2:
            raise NeoError("Invalid color file version")
        version = _strtol(parts[1])
        if version <= 0:
            raise NeoError("Invalid color file version")
        if version > latest_version:
            raise NeoError(
                f"Color file version ({version}) is newer than supported ({latest_version})"
            )
        idx += 1
    else:
        idx = 0

    colors: list[ColorContent] = []
    for line_num, line in enumerate(lines[idx:], start=idx + 1):
        if _is_skippable(line):
            continue
        if len(colors) + 1 > max_pairs:
            raise NeoError(f"Color file has too many lines (max {max_pairs})")
        colors.append(_parse_color_line(line, line_num, max_colors))
    if len(colors) < 2:
        raise NeoError("Color file must have at least two colors")
    return colors


def _ncurses_to_rgb(v: int) -> int:
    return (v * 255 + 500) // 1000


class ColorState:
    """Emulates the ncurses colour state that neo manipulates: colour pairs and the
    (truecolor-mode) redefined palette entries, which persist across colour changes
    exactly as they do under ncurses."""

    def __init__(self, mode: ColorMode) -> None:
        self.mode = mode
        self.pairs: dict[int, int] = {}  # pair number -> foreground colour code
        self.bg = 16
        self.overrides: dict[int, tuple[int, int, int]] = {}  # colour code -> 8-bit RGB

    def init_color(self, idx: int, r: int, g: int, b: int) -> None:
        if self.mode is ColorMode.TRUECOLOR:
            self.overrides[idx] = (
                _ncurses_to_rgb(r),
                _ncurses_to_rgb(g),
                _ncurses_to_rgb(b),
            )

    def _spec(self, code: int, fg: bool) -> str:
        if code < 0:
            return "39" if fg else "49"
        rgb = self.overrides.get(code)
        if rgb is not None:
            return f"{38 if fg else 48};2;{rgb[0]};{rgb[1]};{rgb[2]}"
        if self.mode is ColorMode.COLOR16 and code < 16:
            if code < 8:
                return str((30 if fg else 40) + code)
            return str((90 if fg else 100) + code - 8)
        return f"{38 if fg else 48};5;{code}"

    def sgr(self, pair: int, bold: bool) -> str:
        """SGR escape for a colour pair (0 = background only) with optional bold."""
        attrs = "0;1" if bold else "0"
        if self.mode is ColorMode.MONO:
            return f"\x1b[{attrs}m"
        fg = self.pairs.get(pair, -1) if pair > 0 else -1
        return f"\x1b[{attrs};{self._spec(fg, True)};{self._spec(self.bg, False)}m"
