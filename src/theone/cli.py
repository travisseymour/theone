"""Command-line interface (cyclopts) and the main loop."""

from __future__ import annotations

import locale
import os
import sys
import time
from pathlib import Path
from typing import Annotated, Literal

from cyclopts import App, Parameter

from theone import NeoError, __version__
from theone.cloud import CHARSET_NAMES, BoldMode, Cloud, ShadingMode
from theone.colors import COLOR_KEYS, Color, ColorMode, parse_color_file
from theone.terminal import (
    CLOCK,
    KEY_DOWN,
    KEY_ESC,
    KEY_LEFT,
    KEY_RESIZE,
    KEY_RIGHT,
    KEY_UP,
    Screen,
    Terminal,
)

ColorName = Literal[
    "green", "green2", "green3", "yellow", "orange", "red", "blue", "cyan", "gold",
    "rainbow", "purple", "pink", "pink2", "vaporwave", "gray",
]  # fmt: skip
CharsetName = Literal[
    "ascii", "extended", "english", "dec", "decimal", "digits", "punc", "bin", "binary",
    "hex", "hexadecimal", "katakana", "greek", "cyrillic", "arabic", "hebrew",
    "devanagari", "braille", "runic",
]  # fmt: skip

VERSION_TEXT = f"""\
neo {__version__} (theone - Python port)
Original neo: Copyright (C) 2021 Stewart Reive
License GPLv3+: GNU GPL version 3 or later <https://gnu.org/licenses/gpl.html>.
This is free software: you are free to change and redistribute it.
There is NO WARRANTY, to the extent permitted by law.
This program is not affiliated with "The Matrix",
Warner Bros. Entertainment Inc., Village Roadshow Pictures, Silver Pictures,
nor any of their parent companies, subsidiaries, partners, or affiliates."""

KEYS_HELP = """\
Keys while running:
  SPACE clear screen | UP/DOWN speed | LEFT/RIGHT glitchiness | TAB shading mode
  +/- density | a async | p pause | q/ESC quit
  1 green  2 green2  3 green3  4 gold  5 pink2  6 red  7 blue  8 cyan
  9 purple  0 gray  ! rainbow  @ yellow  # orange  $ pink  % vaporwave"""

app = App(
    name="neo",
    help='Simulate the digital rain from "The Matrix".',
    help_epilogue=KEYS_HELP,
    help_format="plaintext",
    version=VERSION_TEXT,
    version_format="plaintext",
    version_flags=["--version", "-V"],
    help_flags=["--help", "-h"],
    default_parameter=Parameter(negative=""),
)


def _parse_ms_pair(value: str, opt: str) -> tuple[int, int]:
    try:
        lo_s, hi_s = value.split(",")
        lo, hi = int(lo_s), int(hi_s)
    except ValueError:
        raise NeoError(f"Invalid {opt} option") from None
    if lo <= 0 or hi <= 0 or lo > hi or hi > 0xFFFF:
        raise NeoError(f"Invalid {opt} option")
    return lo, hi


def _parse_user_chars(value: str) -> list[int]:
    out: list[int] = []
    for index, tok in enumerate(value.split(","), start=1):
        try:
            cp = int(tok.strip(), 16)
        except ValueError:
            cp = 0
        if not 0 < cp <= 0x10FFFF:
            raise NeoError(f"Invalid unicode char at index {index}")
        out.append(cp)
    return out


def _term_caps() -> tuple[int, bool, int]:
    """(number of colours, can_change_color, number of colour pairs) from terminfo."""
    colors, ccc, pairs = -1, False, 0
    try:
        import curses
    except ImportError:
        curses = None
    if curses is not None:
        try:
            curses.setupterm()
            colors = curses.tigetnum("colors")
            ccc = curses.tigetflag("ccc") > 0
            pairs = curses.tigetnum("pairs")
        except curses.error:
            colors, ccc, pairs = -1, False, 0
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        colors = max(colors, 256)
        ccc = True
    return colors, ccc, max(pairs, 0)


def _pick_color_mode(user: ColorMode | None, colors: int, ccc: bool) -> ColorMode:
    if user is not None:
        return user
    if colors < 8:
        return ColorMode.MONO
    if colors >= 256:
        return ColorMode.TRUECOLOR if ccc else ColorMode.COLOR256
    return ColorMode.COLOR16


@app.default
def neo(
    *,
    async_: Annotated[bool, Parameter(name=["--async", "-a"])] = False,
    bold: Annotated[Literal[0, 1, 2], Parameter(name=["--bold", "-b"])] = 1,
    colorfile: Annotated[Path | None, Parameter(name=["--colorfile", "-C"])] = None,
    color: Annotated[ColorName | None, Parameter(name=["--color", "-c"])] = None,
    defaultbg: Annotated[bool, Parameter(name=["--defaultbg", "-D"])] = False,
    density: Annotated[float, Parameter(name=["--density", "-d"])] = 1.0,
    fullwidth: Annotated[bool, Parameter(name=["--fullwidth", "-F"])] = False,
    fps: Annotated[float, Parameter(name=["--fps", "-f"])] = 60.0,
    glitchpct: Annotated[float, Parameter(name=["--glitchpct", "-G"])] = 10.0,
    glitchms: Annotated[str, Parameter(name=["--glitchms", "-g"])] = "300,400",
    lingerms: Annotated[str, Parameter(name=["--lingerms", "-l"])] = "1,3000",
    shadingmode: Annotated[Literal[0, 1], Parameter(name=["--shadingmode", "-M"])] = 0,
    message: Annotated[str | None, Parameter(name=["--message", "-m"])] = None,
    profile: Annotated[bool, Parameter(name=["--profile", "-p"])] = False,
    rippct: Annotated[float, Parameter(name=["--rippct", "-r"])] = 33.33333,
    speed: Annotated[float, Parameter(name=["--speed", "-S"])] = 8.0,
    screensaver: Annotated[bool, Parameter(name=["--screensaver", "-s"])] = False,
    chars: Annotated[list[str] | None, Parameter(name="--chars")] = None,
    charset: Annotated[CharsetName | None, Parameter(name="--charset")] = None,
    colormode: Annotated[
        Literal[0, 16, 32, 256] | None, Parameter(name="--colormode")
    ] = None,
    maxdpc: Annotated[Literal[1, 2, 3], Parameter(name="--maxdpc")] = 3,
    noglitch: Annotated[bool, Parameter(name="--noglitch")] = False,
    shortpct: Annotated[float, Parameter(name="--shortpct")] = 50.0,
    notime: Annotated[bool, Parameter(name="--notime")] = False,
) -> None:
    """Simulate the digital rain from "The Matrix".

    Parameters
    ----------
    async_
        Asynchronous scroll speed: each column scrolls at an independent speed (bounded by --speed).
    bold
        Control character boldness: 0=off, 1=random, 2=all.
    colorfile
        Read the colors from a file (see examples/colorfile*.txt in the neo repo).
    color
        Select the foreground text color.
    defaultbg
        Use the default terminal background color.
    density
        Density of droplets, greater than 0 and less than 100. Values in [0.25, 4.0] look best.
    fullwidth
        Use two columns per character (for Greek, full-width katakana, ...).
    fps
        Frames per second target/limit.
    glitchpct
        Percentage of screen chars that glitch (0-100).
    glitchms
        NUM1,NUM2: random delay in milliseconds between glitches.
    lingerms
        NUM1,NUM2: how long (ms) characters linger after scrolling.
    shadingmode
        Shading mode: 0=random, 1=gradient (distance from head).
    message
        Display a message in the center of the screen, revealed by the rain.
    profile
        Profiling mode: write per-frame timings to ./time_profile.txt.
    rippct
        Percentage of droplets that die before reaching the bottom (0-100).
    speed
        Scroll speed in characters per second.
    screensaver
        Exit on the first key press.
    chars
        NUM1,NUM2: also use the Unicode code points NUM1..NUM2 (hex, e.g. 0x1F030,0x1F093). Repeatable.
    charset
        Character set to draw with.
    colormode
        Color mode: 0=mono, 16, 256 or 32 (24-bit truecolor). Auto-detected by default.
    maxdpc
        Maximum droplets per column.
    noglitch
        Disable character glitching.
    shortpct
        Percentage of shortened droplets (0-100).
    notime
        Don't show the date and time in the bottom right corner.
    """
    # ---- validate everything before touching the terminal -----------------
    if not 0.0 < density < 100.0:
        raise NeoError("-d/--density must be greater than 0 and less than 100.0")
    if fps <= 0.0:
        raise NeoError("-f/--fps option must be greater than 0")
    if not 0.0 <= glitchpct <= 100.0:
        raise NeoError("-G/--glitchpct must be between 0 and 100.0 inclusive")
    glitch_lo, glitch_hi = _parse_ms_pair(glitchms, "-g/--glitchms")
    linger_lo, linger_hi = _parse_ms_pair(lingerms, "-l/--lingerms")
    if not 0.0 <= rippct <= 100.0:
        raise NeoError("-r/--rippct must be between 0 and 100.0 inclusive")
    if not 0.0 < speed <= 1000000.0:
        raise NeoError("-S/--speed must be greater than 0 and less than 1000000")
    if not 0.0 <= shortpct <= 100.0:
        raise NeoError("--shortpct must be between 0 and 100.0 inclusive")
    char_ranges: list[tuple[int, int]] = []
    for spec in chars or []:
        cps = _parse_user_chars(spec)
        if len(cps) % 2:
            raise NeoError("--chars: odd number of unicode chars given (must be even)")
        char_ranges.extend(zip(cps[::2], cps[1::2]))

    user_mode = None if colormode is None else ColorMode(colormode)
    num_colors, ccc, num_pairs = _term_caps()
    color_mode = _pick_color_mode(user_mode, num_colors, ccc)
    user_colors = None
    if colorfile is not None:
        user_colors = parse_color_file(
            colorfile, max_colors=max(num_colors, 16), max_pairs=num_pairs or 256
        )

    # Determine whether to use UTF-8 or ASCII based on the locale
    try:
        loc = locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        loc = ""
    ascii_only = "utf" not in (loc or "").lower()

    term = Terminal()
    term.start()
    try:
        screen = Screen(term.out_fd)
        screen.clock_sgr = CLOCK_SGR[color_mode]
        cloud = Cloud(screen, color_mode, ascii_only)
        cloud.show_time = not notime
        term.on_resume = lambda: setattr(cloud, "force_draw_everything", True)

        # Apply settings (in neo's option order where it matters)
        if charset is not None:
            cloud.charset = CHARSET_NAMES[charset]
        if async_:
            cloud.async_ = True
        cloud.bold_mode = BoldMode(bold)
        if color is not None:
            cloud.set_color(Color(color))
        if user_colors is not None:
            cloud.user_colors = user_colors
            cloud.set_color(Color.USER)
        if defaultbg:
            cloud.default_background = True
            cloud.set_color(cloud.color)
        cloud.set_droplet_density(density)
        if fullwidth:
            cloud.full_width = True
        cloud.glitch_low_ms, cloud.glitch_high_ms = glitch_lo, glitch_hi
        cloud.set_glitch_pct(glitchpct / 100.0)
        cloud.linger_low_ms, cloud.linger_high_ms = linger_lo, linger_hi
        cloud.set_shading_mode(ShadingMode(shadingmode))
        if message:
            cloud.set_message(message)
        cloud.die_early_pct = rippct / 100.0
        cloud.set_chars_per_sec(speed)
        for lo, hi in char_ranges:
            cloud.add_chars(lo, hi)
        cloud.max_droplets_per_column = maxdpc
        if noglitch:
            cloud.glitchy = False
            cloud.set_glitch_pct(0.0)
            cloud.glitch_low_ms = cloud.glitch_high_ms = 0xFFFF
        cloud.short_pct = shortpct / 100.0

        cloud.init_chars()
        cloud.reset()

        if profile:
            _profiler(cloud, term, screensaver)
        else:
            _main_loop(cloud, term, fps, screensaver)
    finally:
        term.stop()


# Black text on green ("reverse video" of green-on-black) for the date/time overlay
CLOCK_SGR = {
    ColorMode.MONO: "\x1b[0;7m",
    ColorMode.COLOR16: "\x1b[0;30;42m",
    ColorMode.COLOR256: "\x1b[0;38;5;16;48;5;28m",
    ColorMode.TRUECOLOR: "\x1b[0;38;2;0;0;0;48;2;0;135;45m",
}


def _draw_clock(cloud: Cloud) -> None:
    """Overlay the date and time in the bottom-right corner, on top of the rain."""
    if not cloud.show_time:
        return
    screen = cloud.screen
    text = time.strftime(" %Y-%m-%d %H:%M:%S ")
    line = screen.lines - 1
    start = screen.cols - len(text)
    put = screen.put
    for i, ch in enumerate(text):
        put(
            line, start + i, ch, CLOCK
        )  # off-screen cells are ignored on tiny terminals


def _handle_input(cloud: Cloud, term: Terminal, screensaver: bool) -> None:
    ch = term.getch()
    if ch is None:
        return
    if screensaver and ch != KEY_RESIZE:
        cloud.raining = False
        return
    if ch in (KEY_RESIZE, " "):
        cloud.reset()
        cloud.force_draw_everything = True
    elif ch == "a":
        cloud.async_ = not cloud.async_
        cloud.set_column_speeds()
        cloud.update_droplet_speeds()
    elif ch == "p":
        cloud.toggle_pause()
    elif ch == KEY_UP:
        cps = cloud.chars_per_sec
        cps = cps * 2.0 if cps <= 0.5 else cps + 1.0
        cloud.set_chars_per_sec(min(cps, 1000.0))
    elif ch == KEY_DOWN:
        cps = cloud.chars_per_sec
        cps = cps / 2.0 if cps <= 1.0 else cps - 1.0
        cloud.set_chars_per_sec(cps)
    elif ch == KEY_LEFT:
        if cloud.glitchy:
            cloud.set_glitch_pct(max(cloud.glitch_pct - 0.05, 0.0))
    elif ch == KEY_RIGHT:
        if cloud.glitchy:
            cloud.set_glitch_pct(min(cloud.glitch_pct + 0.05, 1.0))
    elif ch == "\t":
        if cloud.shading_mode == ShadingMode.RANDOM:
            cloud.set_shading_mode(ShadingMode.DISTANCE_FROM_HEAD)
        else:
            cloud.set_shading_mode(ShadingMode.RANDOM)
    elif ch in ("q", KEY_ESC):
        cloud.raining = False
    elif ch in COLOR_KEYS:
        cloud.set_color(COLOR_KEYS[ch])
    elif ch == "-":
        cloud.set_droplet_density(max(cloud.droplet_density - 0.25, 0.01))
    elif ch == "+":
        cloud.set_droplet_density(min(cloud.droplet_density + 0.25, 5.0))


def _main_loop(
    cloud: Cloud, term: Terminal, target_fps: float, screensaver: bool
) -> None:
    target_period = 1.0 / target_fps
    prev_time = time.monotonic()
    prev_delay = 5e-9
    while cloud.raining:
        _handle_input(cloud, term, screensaver)
        cloud.rain()
        _draw_clock(cloud)
        cloud.screen.flush()

        cur_time = time.monotonic()
        elapsed = cur_time - prev_time
        calc_delay = 0.0 if elapsed >= target_period else target_period - elapsed
        cur_delay = (7 * prev_delay + calc_delay) / 8
        time.sleep(cur_delay)
        prev_time = cur_time
        prev_delay = cur_delay


def _profiler(cloud: Cloud, term: Terminal, screensaver: bool) -> None:
    """Rudimentary profiler: times the app logic and the screen refresh each frame."""
    with open("time_profile.txt", "w") as fp:
        prev = time.perf_counter_ns()
        while cloud.raining:
            _handle_input(cloud, term, screensaver)
            cloud.rain()
            _draw_clock(cloud)
            t2 = time.perf_counter_ns()
            fp.write(f"app_ns={t2 - prev}\n")
            cloud.screen.flush()
            cur = time.perf_counter_ns()
            fp.write(f"refresh_ns={cur - t2}\n")
            prev = cur


def run() -> None:
    try:
        app()
    except NeoError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
