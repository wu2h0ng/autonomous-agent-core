#!/usr/bin/env python3
"""P2 full-screen evidence: multi-panel boot, Tab focus cycle, flags.

Reproducible pty capture against the hermetic dev daemon (no provider key, no
network). Prints stripped frames so the panel layout / focus / flags can be
checked without a human at the terminal. Run from apps/cli-ts:

    uv run python scripts/pty_fullscreen_p2.py
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


def spawn(descriptor: Path, args: list[str]) -> tuple[int, int]:
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
    env = dict(os.environ)
    env["PATH"] = os.path.expanduser("~/.bun/bin") + ":" + env.get("PATH", "")
    env["TERM"] = "xterm-256color"
    pid = os.fork()
    if pid == 0:
        os.setsid()
        os.dup2(slave, 0)
        os.dup2(slave, 1)
        os.dup2(slave, 2)
        os.chdir(str(CLI))
        os.execvpe(
            "bun",
            ["bun", "run", "src/opentui/main.tsx", "--descriptor", str(descriptor), *args],
            env,
        )
    os.close(slave)
    return pid, master


def kill(pid: int) -> None:
    try:
        os.write(-1, b"")
    except OSError:
        pass
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="p2-"))
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

    try:
        pid, fd = spawn(descriptor, [])
        print("===== BOOT (120 cols, panels) =====")
        print(read(fd, 4))
        os.write(fd, b"hi")
        time.sleep(0.4)
        os.write(fd, b"\r")
        print("===== TURN =====")
        print(read(fd, 6))
        os.write(fd, b"\t")
        print("===== TAB -> files =====")
        print(read(fd, 1.5))
        os.write(fd, b"\t")
        print("===== TAB -> diff =====")
        print(read(fd, 1.5))
        os.write(fd, b"\x03")
        time.sleep(0.5)
        kill(pid)

        for args in (["--no-panels"], ["--no-animation"]):
            pid, fd = spawn(descriptor, args)
            print(f"===== BOOT {args} =====")
            print(read(fd, 4))
            before = time.time()
            idle = read(fd, 3)
            print(
                f"===== IDLE {args}: {len(idle)} chars in "
                f"{time.time() - before:.1f}s ====="
            )
            os.write(fd, b"\x03")
            time.sleep(0.4)
            kill(pid)
    finally:
        daemon.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
