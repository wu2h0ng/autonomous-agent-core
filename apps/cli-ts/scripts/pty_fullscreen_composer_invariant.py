#!/usr/bin/env python3
"""Composer invariant (must hold on ANY composer implementation).

Anti-regression anchor for the trap found in the self-owned-composer WIP: an
overlay layer swallowed printable keys, so "/stat" only ever entered "/" and
Enter ran the palette's default item (/exit) - the app exited cleanly and the
next pty write failed with EIO.

Invariants asserted here:
  1. typing "/stat" opens the command palette (bordered, titled "commands")
  2. Enter on that palette runs /status (the session-status panel appears)
  3. the process SURVIVES the submit (no EIO on the next write)
  4. printable keys are never swallowed by an open overlay (implied by 1-2)

Run from apps/cli-ts:

    uv run python scripts/pty_fullscreen_composer_invariant.py
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


def flat(text: str) -> str:
    """Letters/digits/slash only, digits removed: style resets can inject a
    stray digit between styled cells, so tokens are matched without them."""
    return re.sub(r"[^a-z/._@-]", "", text.lower())


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
    tmp = Path(tempfile.mkdtemp(prefix="composer-inv-"))
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

        for ch in b"/stat":
            os.write(fd, bytes([ch]))
            time.sleep(0.06)
        time.sleep(1.0)
        palette = read(fd, 2.5)
        frames.append(palette)
        print("===== PALETTE =====")
        print(palette)
        # The renderer diffs cells: assert over the accumulated frames (the box
        # title can be painted while the composer is still being updated).
        palette_text = "".join(frames)
        palette_ok = ("commands" in palette_text) and ("status" in flat(palette_text))
        print("PALETTE_OPEN_WITH_TYPED_COMMAND:", palette_ok)

        os.write(fd, b"\r")
        time.sleep(1.0)
        ran = read(fd, 3)
        frames.append(ran)
        allflat = flat("".join(frames))
        ran_status = ("sessionstatus" in allflat) or (
            "turns" in allflat and "statusidle" in allflat
        )
        print("PALETTE_ENTER_RAN_STATUS:", ran_status)

        # The trap: /exit would have terminated the app, so this write fails.
        alive = True
        try:
            os.write(fd, b"x")
            time.sleep(0.4)
        except OSError:
            alive = False
        print("PROCESS_ALIVE_AFTER_ENTER:", alive)

        os.write(fd, b"\x03")
        time.sleep(0.4)
        kill(pid)
        print("INVARIANT_OK:", palette_ok and ran_status and alive)
    finally:
        daemon.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
