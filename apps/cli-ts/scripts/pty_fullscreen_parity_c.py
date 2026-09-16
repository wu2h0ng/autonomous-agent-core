#!/usr/bin/env python3
"""Key-delivery probe + Ctrl-G external-editor round trip (slice C evidence).

Slice C (multiline composer, external editor, vim) needs to know exactly which
keys reach the view's key handler while the composer is focused, so no binding is
shipped as dead code.

Measured (2026-09-16, this build, ONE FRESH APP PER CANDIDATE):
  DELIVERED: return, tab, escape, up, down, ctrl-n, ctrl-p, ctrl-j
             (name="linefeed"), ctrl-g (name="g"), ctrl-o, f2, alt-g.
  Caveats: (a) opentui does NOT set the `ctrl` flag for a control byte - it
  arrives with the plain key name (Ctrl-G => name="g", Ctrl-J => name="linefeed"),
  so bindings must match the NAME, not `ctrl`; (b) a single app instance
  confounds the matrix, because Tab/Enter can move the renderer's focus away from
  the input (an earlier version of this probe reported a false "all delivered").

BLOCKER for the REST of slice C is therefore NOT key delivery but the composer
itself: the view uses opentui's native single-line <input>, so ctrl+J newlines
cannot be DISPLAYED and vim's modal editing cannot replace the input's native
editing. Multiline + vim need a composer this view owns (or a textarea), which is
a larger change than this slice.

Run from apps/cli-ts:

    uv run python scripts/pty_fullscreen_parity_c.py
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


def spawn(descriptor: Path, extra_env: dict[str, str] | None = None) -> tuple[int, int]:
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    env = dict(os.environ)
    env["PATH"] = os.path.expanduser("~/.bun/bin") + ":" + env.get("PATH", "")
    env["TERM"] = "xterm-256color"
    env["AGENT_OS_RUNTIME_DESCRIPTOR"] = str(descriptor)
    env["AGENT_OS_RUNTIME_DATABASE"] = str(descriptor.parent / "a.sqlite3")
    # The probe only works with the instrumentation enabled in the build; without
    # it the app prints nothing and the probe reports no observed keys.
    if extra_env:
        env.update(extra_env)
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


CANDIDATES = [
    ("return", b"\r"),
    ("tab", b"\t"),
    ("escape", b"\x1b"),
    ("up", b"\x1b[A"),
    ("down", b"\x1b[B"),
    ("ctrl-n", b"\x0e"),
    ("ctrl-p", b"\x10"),
    ("ctrl-j", b"\n"),
    ("ctrl-g", b"\x07"),
    ("ctrl-o", b"\x0f"),
    ("f2", b"\x1bOQ"),
    ("alt-g", b"\x1bg"),
    ("plain-a", b"a"),
    ("plain-g", b"g"),
    ("word-abc", b"abc"),
]


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="keyprobe-"))
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
    # 2) Ctrl-G external-editor round trip: a deterministic $EDITOR appends a
    #    marker; the draft is then submitted so the result is observable as NEW
    #    transcript content (composer lines are not reliably repainted).
    editor = tmp / "editor.sh"
    editor.write_text('#!/bin/sh\nprintf "edited-by-editor\\n" >> "$1"\n', encoding="utf-8")
    editor.chmod(0o755)
    try:
        pid, fd = spawn(descriptor, {"EDITOR": str(editor)})
        read(fd, 3)
        os.write(fd, b"draft")
        time.sleep(0.4)
        os.write(fd, b"\x07")  # Ctrl-G
        time.sleep(1.2)
        read(fd, 1.0)
        os.write(fd, b"\r")
        time.sleep(1.0)
        submitted = read(fd, 5)
        kill(pid)
        ok = "editedbyeditor" in re.sub(r"[^a-z]", "", submitted.lower())
        print("EDITOR_ROUNDTRIP:", ok)
    finally:
        pass

    try:
        observed: list[str] = []
        # A FRESH app per candidate: pressing Tab (or Return) can move the
        # renderer's focus away from the input, which would confound the next
        # candidate (that is exactly how the first version of this probe got a
        # false "everything is delivered" result).
        for label, seq in CANDIDATES:
            pid, fd = spawn(descriptor)
            read(fd, 3)
            os.write(fd, seq)
            time.sleep(0.4)
            out = read(fd, 0.6)
            if "DBGKEY" in out:
                observed.append(label)
                line = [row for row in out.splitlines() if "DBGKEY" in row]
                print(f"  {label}: {line[-1][:70] if line else ''}")
            os.write(fd, b"\x03")
            time.sleep(0.3)
            kill(pid)
        if observed:
            print("DELIVERED_KEYS (composer focused):", observed)
            print(
                "NOT_DELIVERED:",
                [label for label, _ in CANDIDATES if label not in observed],
            )
        else:
            # The matrix needs the env-gated instrumentation (NOEM_KEY_DEBUG) to
            # be present in the build; the editor round trip above does not.
            print(
                "DELIVERY_MATRIX_SKIPPED: build has no NOEM_KEY_DEBUG instrumentation\n"
                "(add it temporarily to re-measure the matrix; the measured result\n"
                "is recorded in this file's docstring and in the parity checklist)."
            )
    finally:
        daemon.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
