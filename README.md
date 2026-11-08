# theone

A Python port of [neo](https://github.com/st3w/neo) by Stewart Reive: the digital rain
from "The Matrix" in your terminal. It has the same behaviour, options, key bindings,
colour palettes and colour-file format as the original C++ neo. It also adds one
feature of its own: a date and time display (see below).

**Why the port?** I wanted to be able to install it using `uv tool install`, and I wanted the date/time displayed.

>WARNING: neo may cause discomfort and seizures in people with photosensitive epilepsy.

## Install

```sh
uv tool install git+https://github.com/travisseymour/theone
```

This installs two identical commands: `neo` and `theone`.

## Run

```sh
neo
neo -h
neo --color=gold --charset=greek -F
neo -m "neo is AWESOME" --color=green2 --shortpct=100 --speed=12 --async -d 1.5 --lingerms=1,1 --rippct=0 --maxdpc=1
neo --colorfile=examples/colorfile2.txt
```

Keys: SPACE clear, UP/DOWN speed, LEFT/RIGHT glitchiness, TAB shading mode, `+`/`-` density,
`a` async, `p` pause, `q`/ESC quit, `1`-`0` and `!@#$%` change colour.

## Date and time

By default the current local date and time are shown in the bottom right corner,
as black text on a dark green bar:

```
 2026-11-07 22:45:22 
```

- The rain falls behind the clock, which is always drawn on top.
- It updates every second and keeps running while the rain is paused (`p`).
- Its colour is fixed: it doesn't change with `--color`, `--colorfile` or the colour keys.
  In 16-colour mode it uses your terminal theme's green. With `--colormode=0` it is
  shown in reverse video.
- Use `--notime` to hide it:

```sh
neo --notime
```

To change the colour, edit `CLOCK_SGR` in `src/theone/cli.py`. To change the format,
edit the `strftime` string in `_draw_clock` in the same file.

## Implementation notes

- No ncurses. A small double-buffered renderer writes only the cells that changed each
  frame, as one write wrapped in synchronized-output escapes. That keeps tearing away on
  kitty and other modern terminals.
- Colour mode is auto-detected from terminfo, the same way neo does. On kitty that gives
  24-bit colour. Override it with `--colormode=0|16|256|32`.
- Unlike the original, `--message` accepts Unicode.
- The date/time display and `--notime` are additions that the original doesn't have.

## License

GPL-3.0-or-later, the same as the original neo (see `LICENSE`).
