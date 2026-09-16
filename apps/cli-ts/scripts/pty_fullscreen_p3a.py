#!/usr/bin/env python3
"""P3a full-screen evidence: read-only agents/task tree panel + --no-agents.

Reproducible pty capture against the hermetic dev daemon (no provider key, no
network). Run from apps/cli-ts:

    uv run python scripts/pty_fullscreen_p3a.py
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
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
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
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="p3a-"))
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
        pid, fd = spawn(descriptor, [])
        print("===== BOOT (120x40, panels + agents) =====")
        boot = read(fd, 4)
        frames.append(boot)
        print(boot)
        os.write(fd, b"hi")
        time.sleep(0.4)
        os.write(fd, b"\r")
        print("===== TURN (creates task + session) =====")
        turn = read(fd, 6)
        frames.append(turn)
        print(turn)

        # Sidebar order is transcript, agents, files, diff -> one Tab selects agents.
        os.write(fd, b"\t")
        time.sleep(1.5)
        agents = read(fd, 2.5)
        frames.append(agents)
        print("===== TAB -> agents panel =====")
        print(agents)
        # The renderer diffs cells, so after a Tab only changed cells are
        # re-emitted: the panel *title* can be split across frames and a
        # substring check would be flaky (R2 finding F1). Assert instead on
        # facts that are deterministically observable:
        #   - the panel exists in the FIRST full paint (boot frame),
        #   - the tree content is rendered,
        #   - --no-agents removes the panel (second spawn below).
        # Selection itself is covered by the renderer-independent unit tests for
        # nextPanel/visiblePanels (test/opentui-panels.test.ts), not from frames.
        print("AGENTS_PANEL_PRESENT:", "─agents" in boot)
        print(
            "TREE_ROWS_RENDERED:",
            any(g in "\n".join(frames) for g in ("▸", "•", "◆", "(unlinked task)", "(no mandates)")),
        )
        # Regression guard: selecting a panel must not steal composer focus.
        os.write(fd, b"zzz")
        time.sleep(0.4)
        typed = read(fd, 1.2)
        print("TYPABLE_WITH_AGENTS_PANEL:", "zzz" in typed)
        os.write(fd, b"\x03")
        time.sleep(0.5)
        kill(pid)

        pid, fd = spawn(descriptor, ["--no-agents"])
        print("===== BOOT --no-agents (expect NO agents panel) =====")
        frame = read(fd, 4)
        print(frame)
        print("HAS_AGENTS_TITLE:", "─agents" in frame)
        os.write(fd, b"\x03")
        time.sleep(0.4)
        kill(pid)
    finally:
        daemon.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
