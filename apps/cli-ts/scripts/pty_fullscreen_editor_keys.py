#!/usr/bin/env python3
"""Full-screen editor key delivery - the three coverage gaps recorded when Ink
was retired (backspace 0x7f, ctrl-d forward delete, CR/CRLF paste).

The Ink suite had sixteen integration tests; the retirement note listed exactly
three behaviours with no equivalent assertion on the shipping view, on the
assumption that the opentui textarea now handles them natively:

  * 0x7f deletes the character BEFORE the cursor
  * ctrl-d deletes the character AT the cursor (forward delete)
  * a paste containing CR / CRLF becomes ONE newline

Read-back is row-level via `frame_reader.Screen` (deterministic terminal
emulation), NOT a whole-buffer regex and NOT a forced repaint. An earlier
version of this harness used those two and was itself the defect: it reported
all three behaviours NOT_MET (`qwe`+0x7f+`r` -> `qwer`) when the textarea
handles them correctly. Cause: a forced repaint read right after a key returns
an empty/partial frame, and its ctrl-d expectation was wrong (`asd`+Left+ctrl-d
yields `as`, not `ad`, so that assertion could never pass). Every byte the
child writes is now fed to one Screen per case, and only the composer interior
rows are asserted.

MEASURED 2026-09-17 with this version: EDITOR_KEYS_OK: True - composer goes
`qwe` -> `qw` -> `qwr` with 0x7f, `jkl` -> `jk` with Left+ctrl-d, and a
bracketed paste of `p\\r\\nq` lands as two rows `p` / `q`. The Ink-retirement
assumption (native textarea handling) holds.

Run from apps/cli-ts:

    uv run python scripts/pty_fullscreen_editor_keys.py
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
import tempfile
import termios
import time
from pathlib import Path

from frame_reader import Screen

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "apps" / "cli-ts"


def pump(screen: Screen, fd: int, seconds: float) -> None:
    """Feed every byte the child writes into the screen emulator."""
    end = time.time() + seconds
    while time.time() < end:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if not ready:
            continue
        try:
            data = os.read(fd, 65536)
        except OSError:
            return
        screen.feed(data)


def rows(screen: Screen) -> list[str]:
    return [row.rstrip() for row in screen.text_rows()]


def holds(screen: Screen, token: str) -> bool:
    return any(token in row for row in rows(screen))


def composer(screen: Screen) -> list[str]:
    """The three interior rows of the "message" box (rows 35..37 at 40x120)."""
    return [row.strip("│ ").rstrip() for row in rows(screen)[35:38]]


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


def type_chars(fd: int, text: bytes, delay: float = 0.08) -> None:
    for ch in text:
        os.write(fd, bytes([ch]))
        time.sleep(delay)


def case(name: str, descriptor: Path, body) -> bool:
    pid = 0
    try:
        pid, fd = spawn(descriptor)
        screen = Screen(rows=40, cols=120)
        pump(screen, fd, 4.0)
        ok = bool(body(fd, screen))
    except Exception as exc:  # a dead pty surfaces here, never as a false pass
        print(f"CASE {name} ERROR:", exc)
        ok = False
    finally:
        kill(pid)
    print(f"{name}:", ok)
    return ok


def backspace_case(fd: int, screen: Screen) -> bool:
    """qwe + 0x7f + r -> qwr (qwer would mean the 0x7f was dropped)."""
    type_chars(fd, b"qwe")
    pump(screen, fd, 0.6)
    print("  composer after qwe:", composer(screen))
    os.write(fd, b"\x7f")
    pump(screen, fd, 0.5)
    print("  composer after 0x7f:", composer(screen))
    type_chars(fd, b"r")
    pump(screen, fd, 0.6)
    print("  composer after r:", composer(screen))
    return "qwr" in composer(screen) and "qwer" not in composer(screen)


def ctrl_d_case(fd: int, screen: Screen) -> bool:
    """jkl + Left + ctrl-d -> jk: forward delete removes the char AT the cursor
    (one Left from the end puts the cursor on 'l')."""
    type_chars(fd, b"jkl")
    pump(screen, fd, 0.6)
    print("  composer after jkl:", composer(screen))
    os.write(fd, b"\x1b[D")
    pump(screen, fd, 0.3)
    os.write(fd, b"\x04")
    pump(screen, fd, 0.7)
    print("  composer after Left + ctrl-d:", composer(screen))
    line = "".join(composer(screen))
    return "jk" in line and "jkl" not in line


def crlf_case(fd: int, screen: Screen) -> bool:
    """Bracketed paste of "p\\r\\nq" must land as TWO rows (p above q).

    A raw CR is Enter in a terminal, so bare "p\\r\\nq" submits a turn instead
    of pasting; bracketed paste framing is what a real terminal sends.
    """
    os.write(fd, b"\x1b[200~p\r\nq\x1b[201~")
    pump(screen, fd, 1.0)
    print("  composer after paste:", composer(screen))
    inside = composer(screen)
    return inside[0] == "p" and inside[1] == "q"


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
