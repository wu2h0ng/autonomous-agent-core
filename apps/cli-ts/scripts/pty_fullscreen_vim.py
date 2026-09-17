#!/usr/bin/env python3
"""Vim modal-layer evidence: normal-mode editing + submit.

Flow (hermetic dev daemon, no keys):
  1. toggle vim with `/vim`
  2. insert mode: type "qqwwzz"
  3. Esc -> normal mode (the textarea is blurred there, so letters cannot insert)
  4. `0` then `x` -> the draft becomes "qwwzz"
  5. Enter in normal mode submits; the submitted user message (NEW transcript
     content, the reliable channel) must read "qwwzz", never "qqwwzz".

WHY A SELF-MADE MARKER: the step-5 check used to type "hello" and assert
`"ello" in window and "hello" not in window`, but the scripted fixture reply
(`scripts/dev_daemon.py` TURN1_TEXT) contains `return "hello " + name`, so
"hello" is in the submitted window no matter what the vim layer did — the
signal was pinned False and could not fail on a real regression. "qqwwzz"
cannot collide with any fixture text.

This script GATES: it exits non-zero when a signal is False. It used to print
the signals and exit 0, so a False signal could be quoted as evidence.

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

# Typed in insert mode, then edited by `0` + `x` in normal mode. Deliberately
# not "hello": see the module docstring.
MARKER = b"qqwwzz"
MARKER_EDITED = "qwwzz"


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


def main() -> int:
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
        for ch in MARKER:
            os.write(fd, bytes([ch]))
            time.sleep(0.05)
        time.sleep(0.5)
        frames.append(read(fd, 1.0))

        # 3/4) Esc -> normal mode, 0 -> line start, x -> delete the first char
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
        # contain the marker from the insert-mode composer echo.
        submitted_flat = flat(submitted)
        signals: dict[str, bool] = {}
        signals["VIM_NORMAL_EDIT_SUBMITTED"] = (
            MARKER_EDITED in submitted_flat and MARKER.decode() not in submitted_flat
        )
        print("VIM_NORMAL_EDIT_SUBMITTED:", signals["VIM_NORMAL_EDIT_SUBMITTED"])

        os.write(fd, b"\x03")
        time.sleep(0.5)
        kill(pid)

        # --- shift+I / shift+A / Ctrl-C, each in a FRESH app -------------
        # (a second submission in the same app parks on an approval, which blurs
        # the composer and would swallow the next scenario's keys.)
        def wait_ready(fd_: int) -> None:
            """The UI must be on screen before typing, otherwise keys are lost
            (which silently left vim disabled and produced e.g. "helloip")."""
            deadline = time.time() + 25
            while time.time() < deadline:
                if "message" in read(fd_, 0.6):
                    return

        def fresh_scenario(keys: bytes) -> str:
            pid2, fd2 = spawn(descriptor)
            frames2: list[str] = [read(fd2, 4)]
            wait_ready(fd2)
            for ch in b"/vim":
                os.write(fd2, bytes([ch]))
                time.sleep(0.06)
            os.write(fd2, b"\r")
            time.sleep(1.0)
            frames2.append(read(fd2, 1.2))
            for ch in b"hello":
                os.write(fd2, bytes([ch]))
                time.sleep(0.06)
            time.sleep(0.4)
            frames2.append(read(fd2, 0.8))
            os.write(fd2, b"\x1b")                      # normal mode
            time.sleep(0.7)
            os.write(fd2, b"\x1b")                      # no-op in normal mode; drains the race
            time.sleep(0.7)
            read(fd2, 0.3)
            for byte in keys:
                os.write(fd2, bytes([byte]))
                time.sleep(0.3)
            frames2.append(read(fd2, 1.2))
            # Submit: the user message is NEW transcript content and therefore
            # reliably painted (a repainted composer line is not).
            os.write(fd2, b"\r")
            time.sleep(1.0)
            frames2.append(read(fd2, 4.5))
            kill(pid2)
            return "".join(frames2)

        # shift+A goes to line end: "hello" + A + "c" -> "helloc" (visible in the
        # composer echo, which is enough to prove the caret placement).
        shift_a = flat(fresh_scenario(b"Ac"))
        signals["VIM_SHIFT_A_AT_LINE_END"] = "helloc" in shift_a
        print("VIM_SHIFT_A_AT_LINE_END:", signals["VIM_SHIFT_A_AT_LINE_END"])

        # shift+I goes to line start: "hello" + I + "p" -> "phello".
        shift_i = flat(fresh_scenario(b"Ip"))
        signals["VIM_SHIFT_I_AT_LINE_START"] = "phello" in shift_i
        print("VIM_SHIFT_I_AT_LINE_START:", signals["VIM_SHIFT_I_AT_LINE_START"])

        # Ctrl-C in normal mode must still exit the process.
        pid3, fd3 = spawn(descriptor)
        read(fd3, 4)
        wait_ready(fd3)
        for ch in b"/vim":
            os.write(fd3, bytes([ch]))
            time.sleep(0.06)
        os.write(fd3, b"\r")
        time.sleep(1.0)
        read(fd3, 1.0)
        os.write(fd3, b"\x1b")        # normal mode
        time.sleep(0.8)
        read(fd3, 0.5)
        exited = False
        try:
            os.write(fd3, b"\x03")
            time.sleep(1.5)
            os.write(fd3, b"x")        # EIO once the process is gone
            time.sleep(0.4)
            os.write(fd3, b"y")
        except OSError:
            exited = True
        signals["CTRL_C_EXITS_IN_NORMAL_MODE"] = exited
        print("CTRL_C_EXITS_IN_NORMAL_MODE:", exited)
        kill(pid3)
    finally:
        daemon.terminate()
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [name for name, ok in signals.items() if not ok]
    for name in failed:
        print(f"VIM_SIGNAL_FAILED: {name} = False")
    print("VIM_SIGNALS_FAILED:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
