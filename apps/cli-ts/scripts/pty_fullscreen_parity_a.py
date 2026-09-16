#!/usr/bin/env python3
"""Parity slice A evidence: command palette + selector overlay in the full-screen view.

Reproducible pty capture against the hermetic dev daemon (no provider key, no
network). Run from apps/cli-ts:

    uv run python scripts/pty_fullscreen_parity_a.py
"""
from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "apps" / "cli-ts"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip(buf: bytes) -> str:
    return ANSI.sub("", buf.decode(errors="replace")).replace("\x1b", "")


def read(fd: int, seconds: float) -> str:
    end = time.time() + seconds
    buf = b""
    while time.time() < end:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            try:
                buf += os.read(fd, 65536)
            except OSError:
                break
    return strip(buf)


def flat(text: str) -> str:
    """Lower-case and drop everything but letters/digits: the renderer splits
    words across styled cells, so substrings must be matched on a normal form."""
    return re.sub(r"[^a-z0-9/]", "", text.lower())


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


def kill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="parity-a-"))
    descriptor = tmp / "r.json"
    workspace = tmp / "ws"
    workspace.mkdir()
    daemon = subprocess.Popen(
        [
            "uv", "run", "python", "apps/cli-ts/scripts/dev_daemon.py",
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

    frames: list[str] = []
    try:
        pid, fd = spawn(descriptor)
        frames.append(read(fd, 4))

        # 1) Command palette: typing "/stat" must open the titled, bordered
        #    palette (asserted on its border+title, which only the palette has).
        for ch in b"/stat":
            os.write(fd, bytes([ch]))
            time.sleep(0.05)
        time.sleep(0.8)
        palette = read(fd, 2)
        frames.append(palette)
        print("===== PALETTE (after typing '/stat') =====")
        print(palette)
        print("PALETTE_SHOWN:", "─commands" in palette)

        # 2) Enter on the palette must RUN the highlighted command. /status emits
        #    a "session status" panel, so its presence proves the palette routed
        #    Enter to the command instead of submitting raw text.
        os.write(fd, b"\r")
        time.sleep(0.8)
        ran = read(fd, 2.5)
        frames.append(ran)
        print("===== ENTER ON PALETTE =====")
        print(ran)
        # The status panel is appended to the transcript; the renderer diffs
        # cells, so evaluate over the accumulated frames.
        allflat_ran = flat("".join(frames))
        print("PALETTE_ENTER_RAN_STATUS:", "sessionstatus" in allflat_ran and "turns" in allflat_ran)

        # 3) Clear the composer, then /theme opens the selector overlay.
        for _ in range(12):
            os.write(fd, b"\x7f")
            time.sleep(0.05)
        time.sleep(0.3)
        read(fd, 0.4)
        for ch in b"/theme":
            os.write(fd, bytes([ch]))
            time.sleep(0.05)
        time.sleep(0.4)
        os.write(fd, b"\r")
        time.sleep(0.6)
        overlay = read(fd, 2.5)
        frames.append(overlay)
        print("===== SELECTOR OVERLAY (/theme) =====")
        print(overlay)
        # Selector-specific tokens (the hint line), so the home help text's
        # "Esc during a turn" cannot produce a false positive.
        allflat_sel = flat("".join(frames))
        print("SELECTOR_SHOWN:", "19pick" in allflat_sel and "esccancel" in allflat_sel)

        # 4) Esc cancels the selector (and must not reach the global handler).
        os.write(fd, b"\x1b")
        time.sleep(0.6)
        cancelled = read(fd, 2)
        frames.append(cancelled)
        print("===== AFTER ESC =====")
        print(cancelled)
        print("SELECTOR_CANCELLED:", "19pick" not in flat(cancelled))

        os.write(fd, b"\x03")
        time.sleep(0.5)
        kill(pid)
        print("===== ALL FRAMES (debug) =====")
        print(flat("".join(frames))[:1500])
        allflat = flat("".join(frames))
        print("SUMMARY:", {
            "palette_title": "commands" in allflat,
            "selector": "select" in allflat,
        })
    finally:
        daemon.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
