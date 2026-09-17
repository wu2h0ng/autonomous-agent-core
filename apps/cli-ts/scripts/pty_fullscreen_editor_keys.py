#!/usr/bin/env python3
"""Full-screen editor key delivery - the three coverage gaps recorded when Ink
was retired (backspace 0x7f, ctrl-d forward delete, CR/CRLF paste).

The Ink suite had sixteen integration tests; the retirement note listed exactly
three behaviours with no equivalent assertion on the shipping view, on the
assumption that the opentui textarea now handles them natively:

  * 0x7f deletes the character BEFORE the cursor
  * ctrl-d deletes the character AT the cursor (forward delete)
  * a paste containing CR / CRLF becomes ONE newline

MEASURED 2026-09-17 on this tree (bun src/opentui/main.tsx over a pty, hermetic
daemon): all three are NOT_MET - the assumption does not hold. Typing "qwe" +
0x7f + "r" leaves "qwer"; "asd" + Left + ctrl-d leaves "asd"; a bracketed paste
of "p\\r\\nq" lands as one line "pq". Leading hypothesis: the view router claims
printable keys and writes the draft through its own mirror (`setComposerText`),
so the textarea never receives the editing keys it would otherwise handle.

This script is the assertion harness for that gap: it must print
EDITOR_KEYS_OK: True once the behaviours are implemented. It is NOT wrapped as
a passing test, precisely so the deficit stays visible.

Scope, stated honestly: each case runs in its OWN process and is asserted on a
forced full repaint (TIOCSWINSZ jiggle), so a stale frame cannot satisfy it. A
raw CR is Enter, so case 3 uses bracketed paste framing; sending bare
"p\\r\\nq" was measured to submit a turn instead (asserts nothing about paste).

Run from apps/cli-ts:

    uv run python scripts/pty_fullscreen_editor_keys.py
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
    """Letters/slash/dot only: style resets can inject stray digits between
    styled cells, so tokens are compared without them."""
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


def full_repaint(fd: int, master: int, rows: int = 40, cols: int = 120) -> str:
    """Jiggle the window size so the renderer paints every cell again; the read
    buffer then holds a complete frame instead of the last diff."""
    for height in (rows + 1, rows):
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", height, cols, 0, 0))
        time.sleep(0.3)
    return read(fd, 1.5)


def type_chars(fd: int, text: bytes, delay: float = 0.06) -> None:
    for ch in text:
        os.write(fd, bytes([ch]))
        time.sleep(delay)


def case(name: str, descriptor: Path, body) -> bool:
    pid, fd, master = 0, 0, 0
    try:
        pid, fd = spawn(descriptor)
        master = fd
        read(fd, 4)
        ok = bool(body(fd, master))
    except Exception as exc:  # a dead pty surfaces here, never as a false pass
        print(f"CASE {name} ERROR:", exc)
        ok = False
    finally:
        kill(pid)
    print(f"{name}:", ok)
    return ok


def backspace_case(fd: int, master: int) -> bool:
    """qwe + 0x7f + r -> qwr (qwer would mean the backspace was dropped)."""
    type_chars(fd, b"qwe")
    time.sleep(0.5)
    os.write(fd, b"\x7f")
    time.sleep(0.4)
    type_chars(fd, b"r", delay=0.1)
    text = flat(full_repaint(fd, master))
    print("  backspace frame:", text[-80:])
    return "qwr" in text and "qwer" not in text


def ctrl_d_case(fd: int, master: int) -> bool:
    """asd + Left + ctrl-d -> ad (forward delete at the cursor)."""
    type_chars(fd, b"asd")
    time.sleep(0.5)
    os.write(fd, b"\x1b[D")
    time.sleep(0.3)
    os.write(fd, b"\x04")
    time.sleep(0.6)
    try:
        text = flat(full_repaint(fd, master))
    except OSError:
        print("  ctrl-d killed the pty (treated as NOT_MET)")
        return False
    print("  ctrl-d frame:", text[-80:])
    return "ad" in text and "asd" not in text


def crlf_case(fd: int, master: int) -> bool:
    """A pasted CRLF must become one line break: both lines stay visible.

    A raw CR is Enter in a terminal, so a real paste must be bracketed
    (ESC[200~ .. ESC[201~); sending bare "p\\r\\nq" submits a turn instead and
    asserts nothing about paste handling (measured: it submitted).
    """
    os.write(fd, b"\x1b[200~p\r\nq\x1b[201~")
    time.sleep(0.9)
    raw = full_repaint(fd, master)
    text = flat(raw)
    print("  crlf frame:", text[-60:])
    # Both pasted letters must be present and the CR must not have overwritten
    # "p"; "pq" (everything on one line) would mean the break was dropped.
    return "pq" not in text and "p" in text and "q" in text


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="editor-keys-"))
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
        results = [
            case("BACKSPACE_DELETES_PREVIOUS", descriptor, backspace_case),
            case("CTRL_D_DELETES_FORWARD", descriptor, ctrl_d_case),
            case("PASTE_CRLF_IS_ONE_BREAK", descriptor, crlf_case),
        ]
        print("EDITOR_KEYS_OK:", all(results))
    finally:
        daemon.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
