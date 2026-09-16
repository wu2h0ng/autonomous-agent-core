#!/usr/bin/env python3
"""Theme verification: `/theme` must change the RENDERED colours (#17).

Uses frame_reader.Screen, which reconstructs rows AND SGR attributes from the raw
pty bytes, so the assertion is on what the terminal actually shows (a stripped
capture cannot see this).

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


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="theme-"))
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

    screen = Screen(40, 120)
    try:
        pid, fd = spawn(descriptor)
        pump(fd, screen, 6)
        before = {
            "header": screen.token_style("noem"),
            "footer": screen.token_style("ASK"),
        }
        print("THEME default:", before)

        for ch in b"/theme mono":
            os.write(fd, bytes([ch]))
            time.sleep(0.06)
        os.write(fd, b"\r")
        pump(fd, screen, 3)

        after = {
            "header": screen.token_style("noem"),
            "footer": screen.token_style("ASK"),
        }
        print("THEME mono   :", after)

        changed = [key for key in before if before[key] != after[key]]
        print("THEME_KEYS_CHANGED:", changed)
        print("THEME_APPLIED:", len(changed) > 0)
        os.write(fd, b"\x03")
        time.sleep(0.4)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    finally:
        daemon.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
