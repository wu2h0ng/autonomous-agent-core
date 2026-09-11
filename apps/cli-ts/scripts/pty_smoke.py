#!/usr/bin/env python3
"""pty smoke for the cli-ts Ink client — drives the REAL TUI in a real pty.

Why this exists (iteration-16): unit tests and the headless path cannot catch
terminal-handling regressions (raw mode, per-key input parsing, Ink redraw).
This script boots the hermetic dev_daemon, runs the real CLI under a pty,
types keystrokes ONE BYTE AT A TIME (like a human), and asserts:

  1. initial render shows the status line ("/help")
  2. echo of typed input renders
  3. submitting with Enter streams the deterministic reply end to end
  4. Ctrl-C exits the process

Lesson encoded: never write multi-byte input in a single pty write — the
kernel coalesces it into one read, Ink's input-parser emits it as one event,
and a trailing \\r is then parsed as paste text, not Return (false alarm in
iteration-16). Per-key writes are required for a faithful probe.

Usage: uv run python apps/cli-ts/scripts/pty_smoke.py
"""

from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_DIR = REPO_ROOT / "apps" / "cli-ts"
CLI_ENTRY = CLI_DIR / "src" / "cli.tsx"
TSX = CLI_DIR / "node_modules" / ".bin" / "tsx"

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z]")


def drain(master: int, seconds: float, until: str | None = None) -> bytes:
    """Read pty output for up to `seconds`, early-exit once `until` appears."""
    end = time.time() + seconds
    buf = b""
    while time.time() < end:
        r, _, _ = select.select([master], [], [], 0.2)
        if master in r:
            try:
                buf += os.read(master, 65536)
            except OSError:
                break
            if until and until in ANSI_RE.sub("", buf.decode(errors="replace")):
                break
    return buf


def type_keys(master: int, text: str) -> bytes:
    """Type like a human: one key per write with a small gap."""
    buf = b""
    for ch in text:
        os.write(master, ch.encode())
        buf += drain(master, 0.15)
    return buf


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cli-ts-pty-") as tmp:
        desc = Path(tmp) / "runtime.json"
        db = Path(tmp) / "agent-os.sqlite3"
        ws = Path(tmp) / "ws"
        ws.mkdir()

        daemon = subprocess.Popen(
            [
                "uv", "run", "python",
                str(REPO_ROOT / "apps" / "cli-ts" / "scripts" / "dev_daemon.py"),
                "--descriptor", str(desc),
                "--database", str(db),
                "--workspace", str(ws),
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(60):
                if desc.exists():
                    break
                time.sleep(0.5)
            if not desc.exists():
                print("[pty-smoke] FAIL: daemon never wrote descriptor")
                return 1
            time.sleep(2)

            master, slave = pty.openpty()
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
            proc = subprocess.Popen(
                [str(TSX), str(CLI_ENTRY), "--descriptor", str(desc)],
                stdin=slave, stdout=slave, stderr=slave, close_fds=True,
            )
            os.close(slave)
            try:
                out = drain(master, 10, until="/help")
                text = ANSI_RE.sub("", out.decode(errors="replace"))
                assert "/help" in text, "initial render missing status line"

                out = type_keys(master, "hello pty")
                text = ANSI_RE.sub("", out.decode(errors="replace"))
                assert "hello pty" in text, "typed input did not echo"

                os.write(master, b"\r")
                out = drain(master, 20, until="deterministic")
                text = ANSI_RE.sub("", out.decode(errors="replace"))
                assert "deterministic" in text, (
                    "Enter did not submit / no streamed reply within 20s"
                )

                os.write(master, b"\x03")  # Ctrl-C
                out = drain(master, 3)
                proc.wait(timeout=5)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)
        finally:
            daemon.terminate()
            daemon.wait(timeout=10)

    print("[pty-smoke] PASS: render / typing echo / Enter submit+stream / Ctrl-C exit")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"[pty-smoke] FAIL: {exc}")
        sys.exit(1)
