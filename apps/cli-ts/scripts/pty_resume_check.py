#!/usr/bin/env python3
"""pty-level proof that an operator stop is not a dead end in the TUI.

PR #77's stop is real and PR #83 gave it a key (Ctrl-X), but the stop leaves the
Run PAUSED by kernel design and the kernel then refuses every new turn
(`run_turn requires a runnable Run`). The TUI's `/resume <session-id>` attached
(GET snapshot) without ever sending the resume command, so the printed guidance
("resume with `noem session resume <session-id>`") could only be obeyed by
leaving the app: an operator dead end.

This check drives the SHIPPED entry (`src/cli.tsx` under Bun) in a real pty
against a hermetic daemon (`scripts/resume_daemon.py`) whose first provider call
is HELD OPEN, and asserts on the RECONSTRUCTED SCREEN (`scripts/frame_reader.py`):

  1. Ctrl-X stops the turn, and the durable terminal line names an actionable
     in-terminal way out (`/resume <session-id>`), not only a shell command;
  2. typing that command sends the REAL resume control command and renders the
     kernel's own read-back status — not an optimistic guess;
  3. the resume is not cosmetic: the status the daemon reports afterwards is
     ACTIVE, `RUN_RESUMED` is durably recorded, and a NEW turn actually runs
     (the daemon's second provider call is reached);
  4. the capability the stopped turn's held provider call proposed is never
     dispatched, before or after the resume.

Usage: uv run python apps/cli-ts/scripts/pty_resume_check.py
"""

from __future__ import annotations

import fcntl
import json
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
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from frame_reader import Screen  # noqa: E402

REPO_ROOT = HERE.parents[2]
# Derived from this file's own location, never hardcoded: a copy of the client
# used for a mutation check must be the one that actually runs.
CLI_DIR = HERE.parent
CLI_ENTRY = CLI_DIR / "src" / "cli.tsx"
BUN = os.path.expanduser("~/.bun/bin/bun")

BOOT_TIMEOUT = float(os.environ.get("CLI_TS_PTY_BOOT_TIMEOUT", "30"))
TURN_TIMEOUT = float(os.environ.get("CLI_TS_PTY_TURN_TIMEOUT", "90"))
ROWS, COLS = 46, 160
HOLD_MS = int(os.environ.get("CLI_TS_PTY_RESUME_HOLD_MS", "12000"))

CTRL_X = b"\x18"
STOP_TERMINAL = "turn stopped by the operator"
RESUME_APPLIED = "resume applied: session status ACTIVE"
RESUMED_TURN = "the resumed turn ran"
NOT_DISPATCHED = "workspace.read"


def flat(text: str) -> str:
    """Collapse row padding, so a phrase that wrapped across rows still matches."""
    return re.sub(r"\s+", " ", text)


class Tui:
    """A pty running the CLI, plus the reconstructed screen for assertions."""

    def __init__(self, master: int, rows: int, cols: int) -> None:
        self.master = master
        self.screen = Screen(rows, cols)

    def text(self) -> str:
        return "\n".join(self.screen.text_rows())

    def pump(self, seconds: float, until: str | None = None) -> str:
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([self.master], [], [], 0.2)
            if self.master in ready:
                try:
                    self.screen.feed(os.read(self.master, 65536))
                except OSError:
                    break
            if until is not None and until in self.text():
                break
        return self.text()

    def wait_until(self, predicate, seconds: float, what: str) -> tuple[str, float]:
        started = time.time()
        deadline = started + seconds
        text = self.text()
        while True:
            if predicate(text):
                return text, time.time() - started
            if time.time() >= deadline:
                raise AssertionError(f"{what} did not reach the screen within {seconds:.0f}s")
            self.pump(0.2)
            text = self.text()

    def type(self, text: str) -> None:
        for ch in text:
            os.write(self.master, ch.encode())
            self.pump(0.12)

    def press(self, data: bytes) -> None:
        os.write(self.master, data)


def start_daemon(tmp: Path) -> tuple[subprocess.Popen, Path, dict]:
    desc = tmp / "resume-runtime.json"
    log = open(tmp / "resume_daemon.log", "wb")  # noqa: SIM115 - closed by the caller
    env = {
        **os.environ,
        # Keep the operator's ~/.agent-os out of the loop entirely.
        "AGENT_OS_PROVIDER_CONFIG": str(tmp / "provider.json"),
    }
    proc = subprocess.Popen(
        [
            # sys.executable, not "uv run python": the cli-ts CI job has no uv
            # (it pip-installs the daemon pins); the interpreter running this
            # check is the one the daemon must share (same conversion pty_smoke made).
            sys.executable,
            str(HERE / "resume_daemon.py"),
            "--descriptor", str(desc),
            "--database", str(tmp / "resume.sqlite3"),
            "--workspace", str(tmp / "workspace"),
            "--hold-ms", str(HOLD_MS),
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    for _ in range(60):
        if desc.exists():
            break
        time.sleep(0.5)
    if not desc.exists():
        proc.terminate()
        raise AssertionError(
            "resume daemon never wrote a descriptor; log:\n"
            + (tmp / "resume_daemon.log").read_text(errors="replace")[-2000:]
        )
    data = json.loads(desc.read_text("utf-8"))
    base_url = f"http://{data['host']}:{data['port']}"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base_url, timeout=1)
            break
        except Exception:  # noqa: BLE001 - any answer means "up"; keep polling otherwise
            time.sleep(0.3)
    else:
        proc.terminate()
        raise AssertionError(f"resume daemon did not become reachable at {base_url}")
    return proc, desc, data


def stop_daemon(proc: subprocess.Popen, desc: Path) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    subprocess.run(
        ["pkill", "-f", f"resume_daemon.py --descriptor {desc}"],
        check=False, capture_output=True,
    )


def fetch_json(base_url: str, token: str, path: str) -> object:
    request = urllib.request.Request(base_url + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def session_state(desc_data: dict) -> tuple[str, dict, list[dict]]:
    """The kernel's own view of the session and its durable event log."""
    base_url = f"http://{desc_data['host']}:{desc_data['port']}"
    token = desc_data["bearer_token"]
    listing = fetch_json(base_url, token, "/v1/surface/sessions?limit=10")
    sessions = listing["sessions"]  # type: ignore[index]
    assert sessions, "the daemon recorded no session for the pty turn"
    session_id = sessions[0]["session_id"]
    session = fetch_json(base_url, token, f"/v1/surface/sessions/{session_id}")
    request = urllib.request.Request(
        base_url
        + f"/v1/surface/tasks/{session['session']['task_id']}/events?after=0&wait_ms=0",  # type: ignore[index]
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        body = response.read().decode("utf-8")
    return session_id, session, [  # type: ignore[return-value]
        json.loads(line[len("data: "):])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cli-ts-resume-pty-") as tmp_str:
        tmp = Path(tmp_str)
        proc, desc, desc_data = start_daemon(tmp)
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        env = {
            **os.environ,
            "PATH": os.path.dirname(BUN) + ":" + os.environ.get("PATH", ""),
            "TERM": os.environ.get("TERM", "xterm-256color"),
            # Hermetic: never read/write the developer's ~/.agent-os state, and
            # never let the entry autostart a daemon of its own.
            "AGENT_OS_CLI_STATE": str(tmp / "cli-ts-state.json"),
            "AGENT_OS_PROVIDER_CONFIG": str(tmp / "provider.json"),
            "AGENT_OS_NO_AUTOSTART": "1",
        }
        cli = subprocess.Popen(
            [BUN, "run", str(CLI_ENTRY), "--descriptor", str(desc)],
            stdin=slave, stdout=slave, stderr=slave, close_fds=True,
            cwd=str(CLI_DIR), env=env,
        )
        os.close(slave)
        tui = Tui(master, ROWS, COLS)
        try:
            try:
                tui.wait_until(lambda text: "Quick start" in text, BOOT_TIMEOUT, "the home panel")

                tui.type("read the fixture")
                tui.press(b"\r")
                tui.wait_until(
                    lambda text: "streaming…" in text, BOOT_TIMEOUT, "the in-flight streaming state"
                )

                # --- 1. The stop, and the way out it prints ----------------
                os.write(tui.master, CTRL_X)
                settled, _ = tui.wait_until(
                    lambda text: STOP_TERMINAL in text, TURN_TIMEOUT, "the durable stop record"
                )
                session_id, session, events = session_state(desc_data)
                assert session["status"] == "PAUSED", session  # type: ignore[index]
                assert "RUN_PAUSED" in [event.get("event_type") for event in events], events
                # The guidance must be obeyable WITHOUT leaving the app.
                guidance = flat(settled)
                assert f"`/resume {session_id}`" in guidance, (
                    f"the post-stop line must name the in-terminal resume command; got: {guidance!r}"
                )
                assert "noem session resume" in guidance, (
                    "the shell equivalent must still be named"
                )
                assert RESUME_APPLIED not in settled, "nothing has been resumed yet"

                # --- 2. The operator types what the guidance names ---------
                tui.type(f"/resume {session_id}")
                tui.press(b"\r")
                resumed, _ = tui.wait_until(
                    lambda text: RESUME_APPLIED in text,
                    TURN_TIMEOUT,
                    "the kernel's post-resume status read back into the screen",
                )
                assert "resume FAILED" not in resumed, f"the resume was rejected: {resumed!r}"
                # Not a local flag: the daemon must now agree.
                _, session_after, events_after = session_state(desc_data)
                types_after = [event.get("event_type") for event in events_after]
                assert session_after["status"] == "ACTIVE", session_after  # type: ignore[index]
                assert "RUN_RESUMED" in types_after, (
                    f"the resume left no durable RUN_RESUMED event: {types_after}"
                )

                # --- 3. The session really runs again ----------------------
                tui.type("carry on, then")
                tui.press(b"\r")
                finished, _ = tui.wait_until(
                    lambda text: RESUMED_TURN in text,
                    TURN_TIMEOUT,
                    "a NEW turn running after the resume (the daemon's second provider call)",
                )
                assert NOT_DISPATCHED not in finished, (
                    f"the stopped turn's suppressed capability was dispatched: {finished!r}"
                )
                _, _, events_final = session_state(desc_data)
                completions = [
                    json.loads(event["payload_json"])
                    for event in events_final
                    if event.get("event_type") == "SESSION_TURN_COMPLETED"
                ]
                assert completions, "no durable turn completion at all"
                assert completions[0]["stop_reason"] == "stopped_by_operator", completions[0]
                assert len(completions) >= 2, (
                    f"the resumed turn never completed durably: {completions}"
                )
                assert not any(
                    event.get("event_type") == "ACTION_RECEIPT_RECORDED"
                    for event in events_final
                ), "workspace.read was dispatched despite the stop"
                print(
                    f"[pty-resume] session {session_id}: PAUSED + RUN_PAUSED after ctrl-x, "
                    "ACTIVE + RUN_RESUMED after `/resume`, second turn ran, "
                    "suppressed capability never dispatched"
                )

                tui.press(b"\x03")  # Ctrl-C
                tui.pump(3)
                try:
                    cli.wait(timeout=10)
                except subprocess.TimeoutExpired as exc:
                    raise AssertionError("Ctrl-C did not exit the TUI within 10s") from exc
                assert cli.returncode == 0, f"Ctrl-C exit code was {cli.returncode}, expected 0"
            except AssertionError:
                sys.stderr.write("\n[pty-resume] TUI screen at failure:\n" + tui.pump(0.5) + "\n")
                raise
        finally:
            if cli.poll() is None:
                cli.terminate()
                try:
                    cli.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    cli.kill()
                    cli.wait(timeout=5)
            stop_daemon(proc, desc)

    print(
        "[pty-resume] PASS: ctrl-x mid-turn → durable PAUSED with an actionable in-terminal "
        "way out → `/resume <id>` sends the real resume → kernel read-back says ACTIVE → "
        "RUN_RESUMED durable → a new turn runs → nothing was dispatched while stopped"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"[pty-resume] FAIL: {exc}")
        sys.exit(1)
