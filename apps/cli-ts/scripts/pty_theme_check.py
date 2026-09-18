#!/usr/bin/env python3
"""Theme verification: `/theme` must change the RENDERED colours (#17).

Uses frame_reader.Screen, which reconstructs rows AND SGR attributes from the raw
pty bytes, so the assertion is on what the terminal actually shows (a stripped
capture cannot see this).

The keys are located BY ROW. `Screen.token_style` returns the first span
anywhere that contains the token, and the top status line (app.tsx) renders
`◆ noem v… · ASK · …` as ONE accent-coloured span — so asking it for "noem" and
for "ASK" returned the SAME span twice and the run reported
`THEME_KEYS_CHANGED ['header','footer']` from a single token. The footer is
located on its own row (the `❯ mode · …` line) and reported as measured: that
`<text>` carries no fg token, so it is NOT counted as theme evidence.

Run from apps/cli-ts:

    uv run python scripts/pty_theme_check.py
"""
from __future__ import annotations

import fcntl
import os
import pty
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from frame_reader import Screen  # noqa: E402

ROOT = HERE.parents[2]
CLI = ROOT / "apps" / "cli-ts"

# The header token is a real themed span, so its colour is pinned to the
# resolved values (src/theme.ts accent cyan/white -> src/opentui/theme-colors.ts
# INK_HEX). Asserting "something changed" alone would pass on a wrong theme
# being rendered; asserting the concrete pair does not.
HEADER_DEFAULT_FG = (17, 168, 205)   # #11a8cd, default.accent = cyan
HEADER_MONO_FG = (255, 255, 255)     # #ffffff, mono.accent = white
LOCATE_TIMEOUT = 20.0


def spawn(descriptor: Path) -> tuple[int, int]:
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    env = dict(os.environ)
    env["PATH"] = os.path.expanduser("~/.bun/bin") + ":" + env.get("PATH", "")
    env["TERM"] = "xterm-256color"
    env["AGENT_OS_RUNTIME_DESCRIPTOR"] = str(descriptor)
    env["AGENT_OS_RUNTIME_DATABASE"] = str(descriptor.parent / "a.sqlite3")
    pid = os.fork()
    if pid == 0:
        os.setsid()
        os.dup2(slave, 0)
        os.dup2(slave, 1)
        os.dup2(slave, 2)
        os.chdir(str(CLI))
        os.execvpe(
            "bun",
            ["bun", "run", "src/opentui/main.tsx", "--descriptor", str(descriptor)],
            env,
        )
    os.close(slave)
    return pid, master


def pump(fd: int, screen: Screen, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            try:
                screen.feed(os.read(fd, 65536))
            except OSError:
                break


def locate_row(fd: int, screen: Screen, token: str, what: str) -> int:
    """Pump until a row containing `token` exists; fail loudly if it never does.

    A fixed pump is a first-frame race: the same trap as asserting a streaming
    reply's tail from the frame that carries its head.
    """
    deadline = time.time() + LOCATE_TIMEOUT
    while time.time() < deadline:
        index = screen.find_row(token)
        if index >= 0:
            return index
        pump(fd, screen, 0.5)
    raise AssertionError(f"{what} row ({token!r}) never rendered")


def style_in_row(screen: Screen, index: int, token: str):
    """SGR of the first span IN ROW `index` containing `token` (None if absent).

    Row-scoped: see the module docstring for the same-span collision this
    avoids.
    """
    if index < 0:
        return None
    for text, fg, bg, bold in screen.spans(index):
        if token in text:
            return (fg, bg, bold)
    return None


def locate(fd: int, screen: Screen) -> dict[str, tuple[int, tuple | None, tuple | None, bool] | None]:
    """(row, style) for each key, each key on ITS OWN row."""
    header_row = locate_row(fd, screen, "◆ noem", "header/top status line")
    footer_row = locate_row(fd, screen, "❯ ", "footer")
    return {
        "header": (header_row, style_in_row(screen, header_row, "noem")),
        "footer": (footer_row, style_in_row(screen, footer_row, "ASK")),
    }


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="theme-"))
    descriptor = tmp / "r.json"
    workspace = tmp / "ws"
    workspace.mkdir()
    daemon = subprocess.Popen(
        [
            sys.executable, "apps/cli-ts/scripts/dev_daemon.py",
            "--descriptor", str(descriptor),
            "--database", str(tmp / "a.sqlite3"),
            "--workspace", str(workspace),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        if descriptor.exists():
            break
        time.sleep(0.5)
    time.sleep(1.5)

    screen = Screen(40, 120)
    pid: int | None = None
    try:
        pid, fd = spawn(descriptor)
        pump(fd, screen, 6)
        before = locate(fd, screen)
        print("THEME default:", before)

        # Anti-impersonation: two keys on one row are one piece of evidence.
        assert before["header"][0] != before["footer"][0], (
            "header and footer resolved to the SAME row "
            f"({before['header'][0]}): the two keys are not independent evidence"
        )

        for ch in b"/theme mono":
            os.write(fd, bytes([ch]))
            time.sleep(0.06)
        os.write(fd, b"\r")
        pump(fd, screen, 3)

        after = locate(fd, screen)
        print("THEME mono   :", after)
        assert after["header"][0] == before["header"][0], (
            "the header row moved between the two captures; the two styles are not comparable"
        )

        changed = [key for key in before if before[key][1] != after[key][1]]
        print("THEME_KEYS_CHANGED:", changed)
        print("THEME_APPLIED:", "header" in changed)
        # The footer is reported as measured, never claimed. Its `<text>`
        # (app.tsx: the `❯ ${mode} · …` line) carries no fg, and src/theme.ts's
        # `footer` token has no consumer, so an identical SGR before/after is
        # the honest result here - not a theme failure, and not header evidence.
        print(
            "FOOTER_THEMED:", "footer" in changed,
            f"| footer row {before['footer'][0]} SGR {before['footer'][1]} -> {after['footer'][1]}"
            " | the footer <text> renders with no fg token, so it is not counted as theme evidence",
        )

        # Concrete colours, not just "they differ": the resolved tokens are
        # src/theme.ts accent (default cyan / mono white) through
        # src/opentui/theme-colors.ts INK_HEX.
        header_before = before["header"][1]
        header_after = after["header"][1]
        assert header_before is not None, "header span carries no SGR at all"
        assert header_before[0] == HEADER_DEFAULT_FG, (
            f"header accent under the default theme is {header_before[0]}, expected {HEADER_DEFAULT_FG}"
        )
        assert header_after is not None and header_after[0] == HEADER_MONO_FG, (
            f"header accent under mono is {header_after[0] if header_after else None}, "
            f"expected {HEADER_MONO_FG}"
        )

        os.write(fd, b"\x03")
        time.sleep(0.4)
    finally:
        # Cleanup must not depend on reaching the end of the try body: an
        # assertion (or a Ctrl-C) used to leave the bun child running.
        if pid is not None:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        daemon.terminate()
        shutil.rmtree(tmp, ignore_errors=True)

    print("THEME_CHECK PASS: /theme mono repainted the located header span "
          f"{before['header'][1][0]} -> {after['header'][1][0]} on row {before['header'][0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
