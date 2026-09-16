#!/usr/bin/env python3
"""Vim modal-layer evidence: normal-mode editing + submit.

Flow (hermetic dev daemon, no keys):
  1. toggle vim with `/vim`
  2. insert mode: type "hello"
  3. Esc -> normal mode (the textarea is blurred there, so letters cannot insert)
  4. `0` then `x` -> the draft becomes "ello"
  5. Enter in normal mode submits; the submitted user message (NEW transcript
     content, the reliable channel) must read "ello", never "hello".

Run from apps/cli-ts:

    uv run python scripts/pty_fullscreen_vim.py
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
    tmp = Path(tempfile.mkdtemp(prefix="vim-"))
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

        # 1) enable vim (insert mode is the default after toggling)
        for ch in b"/vim":
            os.write(fd, bytes([ch]))
            time.sleep(0.05)
        os.write(fd, b"\r")
        time.sleep(0.8)
        frames.append(read(fd, 1.5))

        # 2) insert-mode typing
        for ch in b"hello":
            os.write(fd, bytes([ch]))
            time.sleep(0.05)
        time.sleep(0.5)
        frames.append(read(fd, 1.0))

        # 3/4) Esc -> normal mode, 0 -> line start, x -> delete "h"
        os.write(fd, b"\x1b")
        time.sleep(0.4)
        os.write(fd, b"0")
        time.sleep(0.3)
        os.write(fd, b"x")
        time.sleep(0.4)
        frames.append(read(fd, 1.0))
        print("===== AFTER Esc/0/x =====")
        print(frames[-1][-200:].replace("\n", " "))

        # 5) Enter in normal mode submits the edited draft
        os.write(fd, b"\r")
        time.sleep(1.0)
        submitted = read(fd, 5)
        frames.append(submitted)
        print("===== AFTER ENTER (normal mode) =====")
        print(submitted[-300:].replace("\n", " "))
        # Assert on the SUBMITTED window only: earlier frames legitimately
        # contain "hello" from the insert-mode composer echo.
        submitted_flat = flat(submitted)
        print(
            "VIM_NORMAL_EDIT_SUBMITTED:",
            "ello" in submitted_flat and "hello" not in submitted_flat,
        )

        os.write(fd, b"\x03")
        time.sleep(0.5)
        kill(pid)
    finally:
        daemon.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
