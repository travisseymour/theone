"""Minimal, fast terminal layer: a double-buffered screen that only emits changed cells,
plus raw keyboard input. Replaces the subset of ncurses that neo uses."""

from __future__ import annotations

import os
import shutil
import signal
import sys
import termios
import unicodedata
from collections import deque
from collections.abc import Callable

from theone import NeoError

BLANK = -1  # style of an erased cell (background colour only)
CLOCK = -2  # style of the date/time overlay (fixed, independent of the rain palette)

# Key tokens returned by Terminal.getch() besides plain characters
KEY_UP = "KEY_UP"
KEY_DOWN = "KEY_DOWN"
KEY_LEFT = "KEY_LEFT"
KEY_RIGHT = "KEY_RIGHT"
KEY_RESIZE = "KEY_RESIZE"
KEY_ESC = "\x1b"
KEY_OTHER = "KEY_OTHER"

_ARROWS = {"A": KEY_UP, "B": KEY_DOWN, "C": KEY_RIGHT, "D": KEY_LEFT}

_ENTER = "\x1b[?1049h\x1b[?25l\x1b[?7l"  # alt screen, hide cursor, no autowrap
_LEAVE = "\x1b[0m\x1b[2J\x1b[?7h\x1b[?25h\x1b[?1049l"
_SYNC_BEGIN = "\x1b[?2026h"  # synchronized output (kitty & others); ignored elsewhere
_SYNC_END = "\x1b[?2026l"

_width_cache: dict[str, int] = {}


def char_width(ch: str) -> int:
    w = _width_cache.get(ch)
    if w is None:
        if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
            w = 0
        elif unicodedata.east_asian_width(ch) in ("W", "F"):
            w = 2
        else:
            w = 1
        _width_cache[ch] = w
    return w


class Screen:
    """Back buffer (what neo draws) and front buffer (what the terminal shows)."""

    def __init__(self, out_fd: int) -> None:
        self.out_fd = out_fd
        self.lines = 0
        self.cols = 0
        self.chars: list[str] = []
        self.styles: list[int] = []
        self._front_chars: list[str] = []
        self._front_styles: list[int] = []
        self._dirty: list[int] = []
        self._needs_clear = True
        self._sgr_cache: dict[int, str] = {}
        self.sgr_builder: Callable[[int, bool], str] = lambda pair, bold: "\x1b[0m"
        self.clock_sgr = "\x1b[0;7m"
        self.resize()

    def resize(self) -> None:
        try:
            size = os.get_terminal_size(self.out_fd)
        except OSError:
            size = shutil.get_terminal_size((80, 25))
        self.lines = max(size.lines, 1)
        self.cols = max(size.columns, 1)
        self.clear()

    def set_palette(self, builder: Callable[[int, bool], str]) -> None:
        self.sgr_builder = builder
        self._sgr_cache.clear()

    def sgr(self, style: int) -> str:
        s = self._sgr_cache.get(style)
        if s is None:
            if style == BLANK:
                s = self.sgr_builder(0, False)
            elif style == CLOCK:
                s = self.clock_sgr
            else:
                s = self.sgr_builder(style >> 1, bool(style & 1))
            self._sgr_cache[style] = s
        return s

    def clear(self) -> None:
        n = self.lines * self.cols
        self.chars = [" "] * n
        self.styles = [BLANK] * n
        self._front_chars = [" "] * n
        self._front_styles = [BLANK] * n
        self._dirty = []
        self._needs_clear = True

    def put(self, line: int, col: int, ch: str, style: int) -> None:
        if 0 <= line < self.lines and 0 <= col < self.cols:
            idx = line * self.cols + col
            if self.chars[idx] != ch or self.styles[idx] != style:
                self.chars[idx] = ch
                self.styles[idx] = style
                self._dirty.append(idx)

    def char_at(self, line: int, col: int) -> str:
        if 0 <= line < self.lines and 0 <= col < self.cols:
            return self.chars[line * self.cols + col]
        return ""

    def flush(self) -> None:
        if not self._dirty and not self._needs_clear:
            return
        out: list[str] = [_SYNC_BEGIN]
        cur_style: int | None = None
        if self._needs_clear:
            out.append(self.sgr(BLANK))
            out.append("\x1b[2J")
            cur_style = BLANK
            self._needs_clear = False

        chars, styles = self.chars, self.styles
        fchars, fstyles = self._front_chars, self._front_styles
        cols = self.cols
        sgr = self.sgr
        cur_idx = -1  # buffer index where the cursor currently sits (-1 = unknown)
        for idx in sorted(set(self._dirty)):
            ch = chars[idx]
            st = styles[idx]
            if fchars[idx] == ch and fstyles[idx] == st:
                continue
            fchars[idx] = ch
            fstyles[idx] = st
            if idx != cur_idx:
                row, col = divmod(idx, cols)
                out.append(f"\x1b[{row + 1};{col + 1}H")
            if st != cur_style:
                out.append(sgr(st))
                cur_style = st
            out.append(ch)
            # Only trust the cursor position after a plain single-width char that
            # didn't land on the last column.
            if (ch < "̀" or char_width(ch) == 1) and (idx + 1) % cols:
                cur_idx = idx + 1
            else:
                cur_idx = -1
        self._dirty = []
        out.append(_SYNC_END)
        data = "".join(out).encode("utf-8", "replace")
        view = memoryview(data)
        while view:
            try:
                n = os.write(self.out_fd, view)
            except InterruptedError:
                continue
            except BlockingIOError:
                continue
            view = view[n:]


class Terminal:
    """Puts the tty into a cbreak/no-echo, non-blocking mode and restores it on exit."""

    def __init__(self) -> None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise NeoError("neo must be run in a terminal")
        self.in_fd = sys.stdin.fileno()
        self.out_fd = sys.stdout.fileno()
        self._saved = termios.tcgetattr(self.in_fd)
        self._active = False
        self._keys: deque[str] = deque()
        self._resized = False
        self.on_resume: Callable[[], None] | None = None

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        attrs = termios.tcgetattr(self.in_fd)
        attrs[3] &= ~(termios.ICANON | termios.ECHO)  # lflag
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(self.in_fd, termios.TCSANOW, attrs)
        os.write(self.out_fd, _ENTER.encode())
        self._active = True
        signal.signal(signal.SIGWINCH, self._on_winch)
        signal.signal(signal.SIGTSTP, self._on_tstp)
        signal.signal(signal.SIGTERM, self._on_term)

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        try:
            os.write(self.out_fd, _LEAVE.encode())
        finally:
            termios.tcsetattr(self.in_fd, termios.TCSAFLUSH, self._saved)

    # -- signals ----------------------------------------------------------
    def _on_winch(self, signum, frame) -> None:
        self._resized = True

    def _on_term(self, signum, frame) -> None:
        raise SystemExit(0)

    def _on_tstp(self, signum, frame) -> None:
        # Ctrl-Z: restore the terminal, suspend, then take it back over on resume.
        self.stop()
        signal.signal(signal.SIGTSTP, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTSTP)
        # ... execution continues here after SIGCONT
        self.start()
        self._resized = True
        if self.on_resume:
            self.on_resume()

    # -- input ------------------------------------------------------------
    def _read_pending(self) -> None:
        try:
            data = os.read(self.in_fd, 4096)
        except (BlockingIOError, InterruptedError):
            return
        if not data:
            return
        text = data.decode("utf-8", "replace")
        i, n = 0, len(text)
        keys = self._keys
        while i < n:
            ch = text[i]
            if ch != "\x1b":
                keys.append(ch)
                i += 1
                continue
            # Escape sequence or a lone ESC
            if i + 2 < n and text[i + 1] in "[O" and text[i + 2] in _ARROWS:
                keys.append(_ARROWS[text[i + 2]])
                i += 3
            elif i + 1 < n and text[i + 1] == "[":
                j = i + 2
                while j < n and not ("\x40" <= text[j] <= "\x7e"):
                    j += 1
                final = text[j] if j < n else ""
                # Modified arrows (e.g. ESC[1;2A) still map to arrows
                keys.append(_ARROWS.get(final, KEY_OTHER))
                i = j + 1
            elif i + 1 < n and text[i + 1] == "O":
                keys.append(KEY_OTHER)
                i += 3
            elif i + 1 < n:
                keys.append(KEY_OTHER)  # Alt+key
                i += 2
            else:
                keys.append(KEY_ESC)
                i += 1

    def getch(self) -> str | None:
        """Return one pending key (like ncurses getch() in nodelay mode) or None."""
        if self._resized:
            self._resized = False
            return KEY_RESIZE
        if not self._keys:
            self._read_pending()
        return self._keys.popleft() if self._keys else None
