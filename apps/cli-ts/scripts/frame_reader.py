#!/usr/bin/env python3
"""Readable row frames: reconstruct the real screen from raw pty bytes.

The pty capture used elsewhere in this directory strips escape sequences, so it
cannot answer two questions that parity work needs:

  * row structure - does a two-line draft occupy two ROWS? (the `<text>` folding
    bug was invisible to the stripped captures);
  * colour - which SGR attributes does a token carry? (theme colours and syntax
    highlighting can only be asserted from attributes).

This module keeps a cell grid: CUP (`ESC[r;cH`) positions the cursor, SGR (`m`)
tracking gives every cell a (fg, bg, bold) style, and text/CR/LF/erase are
applied like a terminal. `Screen.text_rows()` and `Screen.spans(row)` then expose
the result.

Usage (visual check):
    uv run python scripts/frame_reader.py --demo
    uv run python scripts/frame_reader.py --self-test
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass

CSI = re.compile(rb"\x1b\[([0-9;]*)([A-Za-z])")

DEFAULT_FG = (255, 255, 255)
DEFAULT_BG = (0, 0, 0)


@dataclass
class Style:
    fg: tuple[int, int, int] | None = None
    bg: tuple[int, int, int] | None = None
    bold: bool = False

    def key(self) -> tuple[object, object, bool]:
        return (self.fg, self.bg, self.bold)


class Screen:
    def __init__(self, rows: int = 40, cols: int = 120) -> None:
        self.rows = rows
        self.cols = cols
        self.grid: list[list[tuple[str, Style]]] = [
            [(" ", Style()) for _ in range(cols)] for _ in range(rows)
        ]
        self.cursor_row = 0
        self.cursor_col = 0
        self.style = Style()
        self._tail = b""

    # ---- terminal emulation -------------------------------------------------
    def feed(self, data: bytes) -> None:
        buf = self._tail + data
        self._tail = b""
        i = 0
        while i < len(buf):
            byte = buf[i : i + 1]
            if byte == b"\x1b":
                match = CSI.match(buf, i)
                if match is None:
                    # Not a CSI we understand (OSC, alt-screen, ...): skip it.
                    nxt = buf.find(b"\x1b", i + 1)
                    if nxt == -1:
                        self._tail = buf[i:]
                        return
                    i = nxt
                    continue
                self._csi(match.group(1).decode(), match.group(2).decode())
                i = match.end()
                continue
            if byte == b"\r":
                self.cursor_col = 0
            elif byte == b"\n":
                self.cursor_row = min(self.cursor_row + 1, self.rows - 1)
            elif byte == b"\b":
                self.cursor_col = max(self.cursor_col - 1, 0)
            elif byte == b"\t":
                self.cursor_col = min(((self.cursor_col // 8) + 1) * 8, self.cols - 1)
            elif byte >= b"\x80":
                # Multi-byte UTF-8 (box drawing, CJK, ...): decode the whole
                # sequence, otherwise every glyph becomes a replacement char.
                length = 2 if byte[0] < 0xE0 else 3 if byte[0] < 0xF0 else 4
                chunk = buf[i : i + length]
                self._put(chunk.decode("utf-8", errors="replace"))
                i += length
                continue
            elif byte > b" ":
                self._put(byte.decode("utf-8", errors="replace"))
            i += 1

    def _put(self, text: str) -> None:
        if self.cursor_col >= self.cols:
            self.cursor_col = 0
            self.cursor_row = min(self.cursor_row + 1, self.rows - 1)
        self.grid[self.cursor_row][self.cursor_col] = (text, Style(self.style.fg, self.style.bg, self.style.bold))
        self.cursor_col += 1

    def _csi(self, params: str, final: str) -> None:
        args = [int(p) if p else 0 for p in params.split(";")] if params else []
        if final in ("H", "f"):
            row = (args[0] if args and args[0] else 1) - 1
            col = (args[1] if len(args) > 1 and args[1] else 1) - 1
            self.cursor_row = min(max(row, 0), self.rows - 1)
            self.cursor_col = min(max(col, 0), self.cols - 1)
        elif final == "A":
            self.cursor_row = max(self.cursor_row - (args[0] if args and args[0] else 1), 0)
        elif final == "B":
            self.cursor_row = min(self.cursor_row + (args[0] if args and args[0] else 1), self.rows - 1)
        elif final == "C":
            self.cursor_col = min(self.cursor_col + (args[0] if args and args[0] else 1), self.cols - 1)
        elif final == "D":
            self.cursor_col = max(self.cursor_col - (args[0] if args and args[0] else 1), 0)
        elif final == "K":
            mode = args[0] if args else 0
            if mode == 0:
                for c in range(self.cursor_col, self.cols):
                    self.grid[self.cursor_row][c] = (" ", Style())
            elif mode == 2:
                for c in range(self.cols):
                    self.grid[self.cursor_row][c] = (" ", Style())
        elif final == "J":
            mode = args[0] if args else 0
            if mode in (2, 3):
                for r in range(self.rows):
                    for c in range(self.cols):
                        self.grid[r][c] = (" ", Style())
                self.cursor_row = 0
                self.cursor_col = 0
        elif final == "m":
            self._sgr(args)

    def _sgr(self, args: list[int]) -> None:
        if not args or args == [0]:
            self.style = Style()
            return
        idx = 0
        while idx < len(args):
            code = args[idx]
            if code == 0:
                self.style = Style()
            elif code == 1:
                self.style.bold = True
            elif code == 22:
                self.style.bold = False
            elif code == 39:
                self.style.fg = None
            elif code == 49:
                self.style.bg = None
            elif 30 <= code <= 37 or 90 <= code <= 97:
                self.style.fg = _ansi16(code)
            elif 40 <= code <= 47 or 100 <= code <= 107:
                self.style.bg = _ansi16(code, background=True)
            elif code in (38, 48) and idx + 4 < len(args) and args[idx + 1] == 2:
                colour = (args[idx + 2], args[idx + 3], args[idx + 4])
                if code == 38:
                    self.style.fg = colour
                else:
                    self.style.bg = colour
                idx += 4
            idx += 1

    # ---- queries -----------------------------------------------------------
    def text_rows(self) -> list[str]:
        return ["".join(cell for cell, _ in row).rstrip() for row in self.grid]

    def row_text(self, index: int) -> str:
        return self.text_rows()[index]

    def spans(self, index: int) -> list[tuple[str, tuple | None, tuple | None, bool]]:
        """Merge adjacent cells with the same style into (text, fg, bg, bold)."""
        out: list[tuple[str, tuple | None, tuple | None, bool]] = []
        for cell, style in self.grid[index]:
            if out and out[-1][1:] == (style.fg, style.bg, style.bold):
                out[-1] = (out[-1][0] + cell, style.fg, style.bg, style.bold)
            else:
                out.append((cell, style.fg, style.bg, style.bold))
        return [span for span in out if span[0].strip() != ""]

    def find_row(self, needle: str) -> int:
        for index, text in enumerate(self.text_rows()):
            if needle in text:
                return index
        return -1

    def token_style(self, token: str) -> tuple[tuple | None, tuple | None, bool] | None:
        for index in range(self.rows):
            for text, fg, bg, bold in self.spans(index):
                if token in text:
                    return (fg, bg, bold)
        return None


def _ansi16(code: int, background: bool = False) -> tuple[int, int, int]:
    table = {
        0: (0, 0, 0),
        1: (205, 49, 49),
        2: (13, 188, 121),
        3: (229, 229, 16),
        4: (36, 114, 200),
        5: (188, 63, 188),
        6: (17, 168, 205),
        7: (229, 229, 229),
    }
    index = (code - 30) if not background else (code - 40)
    if 90 <= code <= 97:
        index = code - 90
    if 100 <= code <= 107:
        index = code - 100
    base = table.get(index % 8, (229, 229, 229))
    if index >= 8:
        return tuple(min(255, channel + 60) for channel in base)
    return base


def self_test() -> int:
    failures = 0

    # Row structure: two CUP-addressed rows must stay two rows.
    screen = Screen(rows=4, cols=20)
    screen.feed(b"\x1b[1;1HA\x1b[2;1HB")
    rows = screen.text_rows()
    if rows[0] != "A" or rows[1] != "B":
        print("FAIL rows:", rows[:2])
        failures += 1

    # Truecolor SGR must be attributed to the right token only.
    screen = Screen(rows=2, cols=20)
    screen.feed(b"\x1b[38;2;10;20;30mred\x1b[0m plain")
    span = screen.spans(0)
    if span[0][:2] != ("red", (10, 20, 30)) or span[1][0].strip() != "plain":
        print("FAIL sgr:", span)
        failures += 1

    # Overwriting and erase-to-end-of-line must clear stale cells.
    screen = Screen(rows=2, cols=20)
    screen.feed(b"abcdef\r\x1b[Kxy")
    if screen.row_text(0) != "xy":
        print("FAIL erase:", repr(screen.row_text(0)))
        failures += 1

    print("SELF_TEST_FAILURES:", failures)
    return 1 if failures else 0


def demo() -> None:
    screen = Screen(rows=6, cols=40)
    screen.feed(
        b"\x1b[1;1H\x1b[1mNoem\x1b[0m demo"
        b"\x1b[2;1H\x1b[38;2;97;175;239mdef hello():\x1b[0m"
        b"\x1b[3;3Hreturn 1"
    )
    for index, text in enumerate(screen.text_rows()):
        if text.strip():
            print(f"{index:02d}| {text}")
            for span_text, fg, _bg, bold in screen.spans(index):
                if span_text.strip():
                    print(f"    span {span_text!r} fg={fg} bold={bold}")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    demo()
