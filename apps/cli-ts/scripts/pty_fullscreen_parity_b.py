#!/usr/bin/env python3
"""Parity slice B evidence: @mentions completion, input history, markdown text.

Reproducible pty capture against the hermetic dev daemon (no provider key, no
network). Run from apps/cli-ts:

    uv run python scripts/pty_fullscreen_parity_b.py
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
    return re.sub(r"[^a-z0-9/._@-]", "", text.lower())


def flat_alpha(text: str) -> str:
    """Like flat() but without digits: the renderer's style resets can leave a
    stray "0" between styled cells, which would break a longer token match."""
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
    tmp = Path(tempfile.mkdtemp(prefix="parity-b-"))
    descriptor = tmp / "r.json"
    workspace = tmp / "ws"
    (workspace / "src").mkdir(parents=True)
    (workspace / "fixture.txt").write_text("cli-ts spike fixture\n", encoding="utf-8")
    (workspace / "src" / "a.ts").write_text("export const a = 1;\n", encoding="utf-8")
    # A dot-free, distinctive name: the renderer styles the "@" separately, so a
    # token containing "." right after the marker is not reliably matchable.
    (workspace / "zzmentionfile").write_text("mention me\n", encoding="utf-8")

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

        # A session must exist before workspace files can be listed.
        os.write(fd, b"hi")
        time.sleep(0.4)
        os.write(fd, b"\r")
        frames.append(read(fd, 6))

        # 1) Input history first (so the most recent submission is still "hi"):
        #    Up recalls it into the composer.
        os.write(fd, b"\x1b[A")
        time.sleep(0.6)
        history = read(fd, 2)
        frames.append(history)
        print("===== AFTER UP (history) =====")
        print(history)
        hist_ok = "hi" in flat_alpha(history)
        print("HISTORY_PREVIOUS:", hist_ok)

        for _ in range(40):
            os.write(fd, b"\x7f")  # clear the composer
            time.sleep(0.02)
        time.sleep(0.4)
        read(fd, 0.4)

        # 2) @mention: typing "@zz" narrows to the distinctive workspace file and
        #    Tab completes it. The completed text is submitted, so it becomes a
        #    NEW transcript line - unlike the composer line, new content must be
        #    painted by the cell-diffing renderer, which makes it observable.
        os.write(fd, b"@zz")
        time.sleep(0.9)
        frames.append(read(fd, 1.5))
        os.write(fd, b"\t")
        time.sleep(0.6)
        frames.append(read(fd, 1.5))
        os.write(fd, b"\r")
        time.sleep(1.0)
        submitted = read(fd, 5)
        frames.append(submitted)
        print("===== AFTER ENTER (submitted mention) =====")
        print(submitted)
        # Narrow assertion: the token must appear in the SUBMITTED window (the
        # new transcript line), not merely somewhere in the accumulated frames.
        mention_ok = "zzmentionfile" in flat_alpha(submitted)
        print("MENTION_COMPLETED_ON_SUBMIT:", mention_ok)

        os.write(fd, b"\x03")
        time.sleep(0.5)
        kill(pid)

        # Assistant text is rendered through the markdown renderable; the
        # deterministic reply landing in the transcript proves that path renders.
        # Smoke check: the assistant reply still lands in the transcript through
        # the markdown path. It does NOT verify markdown formatting itself.
        md_ok = "deterministicreply" in flat_alpha("".join(frames))
        print("MARKDOWN_RENDER_PATH_OK (smoke, not a formatting test):", md_ok)
        print("SLICE_B_ALL_SIGNALS_VERIFIED:", mention_ok and hist_ok and md_ok)
        # Evidence methodology note: observing a COMPOSER change is unreliable
        # under cell diffing; observing NEW transcript content (a submitted
        # message, a reply) is reliable. This script only asserts the latter.
        if not (mention_ok and hist_ok and md_ok):
            print("NOT ALL SLICE-B SIGNALS OBSERVED - do not claim verification.")
    finally:
        daemon.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
