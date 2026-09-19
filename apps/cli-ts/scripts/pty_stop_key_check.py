#!/usr/bin/env python3
"""pty-level proof that the operator can STOP a running turn from the TUI.

PR #77 made a single-session stop real (a durable pause endpoint, a cooperative
mid-turn stop, `stop_reason=stopped_by_operator`, `noem session pause <id>`
exiting 0) and its honest-limits section says the entry point is CLI/HTTP only —
there is no TUI stop key. This check drives the SHIPPED entry (`src/cli.tsx`
under Bun) in a real pty against a hermetic daemon whose first provider call is
HELD OPEN (`scripts/stop_daemon.py --hold-ms`), presses the stop key mid-turn,
and asserts on the RECONSTRUCTED SCREEN (`scripts/frame_reader.py`):

  1. the keypress reaches the real path: the frame names the request
     ("stop requested") and the durable status the kernel answered with
     ("stop applied: session status PAUSED") — the status is read back from the
     kernel, never inferred by the client;
  2. the client does NOT claim the turn stopped while it is still running: the
     frame shows its own "stopping…" state, and the durable terminal line
     ("turn stopped by the operator") is absent until the durable turn record
     arrives. This is the premature-success failure mode the UI must not have;
  3. the stop is not cosmetic: the capability the held provider call was about to
     propose is never dispatched (no card, no receipt) and the second provider
     call never runs — checked on the frame AND on the task's durable event log;
  4. the composer is untouched by the key (no control byte lands in the draft).

Usage: uv run python apps/cli-ts/scripts/pty_stop_key_check.py
"""

from __future__ import annotations

import fcntl
import json
import os
import pty
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
# The shipped runtime. Under Bun the entry mounts the full-screen view; under
# node it deliberately refuses with actionable advice (it has no native FFI).
BUN = os.path.expanduser("~/.bun/bin/bun")

BOOT_TIMEOUT = float(os.environ.get("CLI_TS_PTY_BOOT_TIMEOUT", "30"))
TURN_TIMEOUT = float(os.environ.get("CLI_TS_PTY_TURN_TIMEOUT", "60"))
ROWS, COLS = 46, 160
# Long enough that the keypress cannot race the end of the held provider call.
HOLD_MS = int(os.environ.get("CLI_TS_PTY_STOP_HOLD_MS", "12000"))

CTRL_X = b"\x18"
PLACEHOLDER = "Tell Noem what to do"
# Keyed into the composer while the turn runs: Ctrl-X must not touch it.
DRAFT = "draft survives the stop"
NOT_DISPATCHED = "workspace.read"
SECOND_CALL_TEXT = "the second provider call must never be reached"
STOP_TERMINAL = "turn stopped by the operator"


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
        """Poll the screen until `predicate(text)` holds; return (frame, elapsed)."""
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
            self.pump(0.15)

    def press(self, data: bytes) -> None:
        os.write(self.master, data)


def start_daemon(tmp: Path) -> tuple[subprocess.Popen, Path, dict]:
    desc = tmp / "stop-runtime.json"
    log = open(tmp / "stop_daemon.log", "wb")  # noqa: SIM115 - closed by the caller
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
            str(HERE / "stop_daemon.py"),
            "--descriptor", str(desc),
            "--database", str(tmp / "stop.sqlite3"),
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
            "stop daemon never wrote a descriptor; log:\n"
            + (tmp / "stop_daemon.log").read_text(errors="replace")[-2000:]
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
        raise AssertionError(f"stop daemon did not become reachable at {base_url}")
    return proc, desc, data


def stop_daemon(proc: subprocess.Popen, desc: Path) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    subprocess.run(
        ["pkill", "-f", f"stop_daemon.py --descriptor {desc}"],
        check=False, capture_output=True,
    )


def fetch_json(base_url: str, token: str, path: str) -> object:
    request = urllib.request.Request(base_url + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def task_events(desc_data: dict) -> tuple[dict, list[dict]]:
    base_url = f"http://{desc_data['host']}:{desc_data['port']}"
    token = desc_data["bearer_token"]
    listing = fetch_json(base_url, token, "/v1/surface/sessions?limit=10")
    sessions = listing["sessions"]  # type: ignore[index]
    assert sessions, "the daemon recorded no session for the pty turn"
    session = fetch_json(base_url, token, f"/v1/surface/sessions/{sessions[0]['session_id']}")
    request = urllib.request.Request(
        base_url + f"/v1/surface/tasks/{session['session']['task_id']}/events?after=0&wait_ms=0",  # type: ignore[index]
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        body = response.read().decode("utf-8")
    return session, [  # type: ignore[return-value]
        json.loads(line[len("data: "):])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cli-ts-stop-pty-") as tmp_str:
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
                _, _ = tui.wait_until(lambda text: "Quick start" in text, BOOT_TIMEOUT, "the home panel")

                tui.type("read the fixture")
                tui.press(b"\r")
                # The turn is in flight: `streaming…` is the controller's own
                # state, so this is the exact window the stop key targets.
                tui.wait_until(
                    lambda text: "streaming…" in text,
                    BOOT_TIMEOUT,
                    "the in-flight streaming state",
                )

                # A draft in the composer while the turn runs: Ctrl-X must be a
                # global stop, not the textarea's key. (A cut/insert here would
                # silently eat the operator's next message.)
                tui.type(DRAFT)
                tui.wait_until(lambda text: DRAFT in text, BOOT_TIMEOUT, "the composer draft")

                os.write(tui.master, CTRL_X)
                stopped_ack = time.time()
                # 1. requested → applied, with the kernel's own status verbatim.
                frame, _ = tui.wait_until(
                    lambda text: "stop requested" in text
                    and "stop applied: session status PAUSED" in text,
                    TURN_TIMEOUT,
                    "the stop request and the kernel's PAUSED status",
                )
                pause_latency_s = time.time() - stopped_ack
                # 2. Not yet stopped, and the client says so: its own "stopping…"
                #    state is up and the durable terminal line is NOT.
                assert "stopping…" in frame, f"the UI must show it is still stopping: {frame!r}"
                assert STOP_TERMINAL not in frame, (
                    "the frame claims the turn stopped before the durable turn record"
                )
                assert "stop FAILED" not in frame, f"the pause was rejected: {frame!r}"

                # 3. The durable terminal state. Condition-driven, not a fixed
                #    sleep: wait until BOTH the durable stopped record is on
                #    screen AND the client's own "stopping…" indicator has
                #    cleared (the finally block that clears it runs one render
                #    after the record is pushed, so polling for the record alone
                #    can catch a frame that still shows "stopping…").
                settled, elapsed = tui.wait_until(
                    lambda text: STOP_TERMINAL in text and "stopping…" not in text,
                    TURN_TIMEOUT,
                    "the durable stopped_by_operator turn record with the stopping indicator cleared",
                )
                assert "the session is PAUSED" in settled, settled
                assert "noem session resume" in settled, (
                    "the terminal state must name how to continue the paused session"
                )
                assert "stopping…" not in settled, "the stopping state must clear when the turn ends"
                # The refused work never happened: no card, and the second
                # provider call's text was never produced.
                assert NOT_DISPATCHED not in settled, (
                    f"the held turn dispatched {NOT_DISPATCHED} after the stop: {settled!r}"
                )
                assert SECOND_CALL_TEXT not in settled, "a stopped turn must not call the provider again"
                # 4. The key did not reach the composer: the draft is byte-for-byte
                #    what the operator typed, and no control byte was inserted.
                assert DRAFT in settled, (
                    "the stop key ate (or altered) the composer draft: "
                    + repr([row for row in settled.split("\n") if "draft" in row])
                )
                assert PLACEHOLDER not in settled, (
                    "the composer was emptied — the stop key reached the textarea"
                )

                session, events = task_events(desc_data)
                assert session["status"] == "PAUSED", session  # type: ignore[index]
                types = [event.get("event_type") for event in events]
                assert "RUN_PAUSED" in types, f"the durable pause is missing: {types}"
                assert "ACTION_RECEIPT_RECORDED" not in types, (
                    f"a stopped turn dispatched a capability: {types}"
                )
                assert "NODE_COMPLETED" not in types, f"a stopped turn completed a node: {types}"
                completions = [
                    json.loads(event["payload_json"])
                    for event in events
                    if event.get("event_type") == "SESSION_TURN_COMPLETED"
                ]
                assert completions, f"the turn never completed durably: {types}"
                assert completions[-1]["stop_reason"] == "stopped_by_operator", completions[-1]
                print(
                    f"[pty-stop] pause acknowledged in {pause_latency_s:.2f}s; "
                    f"durable stop recorded {elapsed:.2f}s after the keypress"
                )

                tui.press(b"\x03")  # Ctrl-C
                tui.pump(3)
                try:
                    cli.wait(timeout=10)
                except subprocess.TimeoutExpired as exc:
                    raise AssertionError("Ctrl-C did not exit the TUI within 10s") from exc
                assert cli.returncode == 0, f"Ctrl-C exit code was {cli.returncode}, expected 0"
            except AssertionError:
                sys.stderr.write("\n[pty-stop] TUI screen at failure:\n" + tui.pump(0.5) + "\n")
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
        "[pty-stop] PASS: ctrl-x mid-turn → real pause (durable status PAUSED read back "
        "from the kernel) → honest 'stopping…' (no premature 'stopped') → durable "
        "turn record stopped_by_operator with the session left PAUSED, no dispatch, "
        "no second provider call, composer untouched"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"[pty-stop] FAIL: {exc}")
        sys.exit(1)
