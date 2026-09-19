#!/usr/bin/env python3
"""pty-level frame proof that a permission DENY reaches the operator's screen.

What this exists for (PR #75's own honest limit): the DENY card's evidence was a
real daemon + real controller + `renderTranscript`/`toolState` + unit tests — no
pty-level frame assertion. A card that only exists in a unit projection is not
the same claim as a card the operator can see, and the whole defect was that a
refused action left NOTHING on screen while the model reported success.

This check therefore drives the SHIPPED entry (`src/cli.tsx` under Bun — the real
runtime) in a real pty against a hermetic daemon (`scripts/deny_daemon.py`) that
seeds a durable operator DENY rule before the session opens, and asserts on the
RECONSTRUCTED SCREEN (`scripts/frame_reader.py`), i.e. on what a human sees:

  1. the refusal renders as its own card: the `✗` marker, the capability, the
     RULE id and the operator's own reason (`denied by rule … — deploy freeze`);
  2. it is distinguishable from an ORDINARY tool failure, which in the same
     transcript carries the same `✗` marker: only the denial names a rule, and
     only the ordinary failure carries its own error text. The two rows are
     compared against each other, so a change that made them indistinguishable
     fails here;
  3. the model's final claim ("done - I updated fixture.txt") is on screen at the
     same time — the card is the only thing contradicting it;
  4. the frame agrees with DURABLE truth: the task's own event log carries
     `POLICY_VERDICT_RECORDED(DENY, basis=rule, rule_id=…)` for that capability
     and NO receipt for it (the action was never dispatched), and the workspace
     file is byte-identical — the refusal really did prevent the edit. Without
     this the frame could be a rendering-only artifact.

Usage: uv run python apps/cli-ts/scripts/pty_deny_frame_check.py
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

RULE_ID = "rule-deploy-freeze"
RULE_REASON = "deploy freeze"
DENIED_CAPABILITY = "workspace.edit"
MISSING_PATH = "missing-file.txt"
FINAL_CLAIM = "done - I updated fixture.txt"


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

    def wait_until(self, predicate, seconds: float, what: str) -> str:
        """Poll the screen until `predicate(text)` holds, else fail.

        `wait_for`-style early exit on a single needle is not enough for a
        transcript that is still being written: the frame that first shows the
        card can still be missing the row it settles on.
        """
        deadline = time.time() + seconds
        text = self.text()
        while True:
            if predicate(text):
                return text
            if time.time() >= deadline:
                raise AssertionError(f"{what} did not reach the screen within {seconds:.0f}s")
            self.pump(0.2)
            text = self.text()

    def type(self, text: str) -> None:
        """Type like a human: one key per write with a small gap."""
        for ch in text:
            os.write(self.master, ch.encode())
            self.pump(0.15)

    def press(self, data: bytes) -> None:
        os.write(self.master, data)


def rows_containing(text: str, needle: str) -> list[str]:
    return [row.strip() for row in text.split("\n") if needle in row]


def start_daemon(tmp: Path) -> tuple[subprocess.Popen, Path, dict]:
    desc = tmp / "deny-runtime.json"
    workspace = tmp / "workspace"
    log_path = tmp / "deny_daemon.log"
    log = open(log_path, "wb")  # noqa: SIM115 - closed by the caller
    env = {
        **os.environ,
        # Keep the operator's ~/.agent-os out of the loop entirely: the provider
        # config path is redirected into this run's temp dir (the daemon would
        # otherwise read ~/.agent-os/provider.json for its redacted status).
        "AGENT_OS_PROVIDER_CONFIG": str(tmp / "provider.json"),
    }
    proc = subprocess.Popen(
        [
            # sys.executable, not "uv run python": the cli-ts CI job has no uv
            # (it pip-installs the daemon pins); the interpreter running this
            # check is the one the daemon must share (same conversion pty_smoke made).
            sys.executable,
            str(HERE / "deny_daemon.py"),
            "--descriptor", str(desc),
            "--database", str(tmp / "deny.sqlite3"),
            "--workspace", str(workspace),
            "--rule-id", RULE_ID,
            "--rule-reason", RULE_REASON,
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
        raise AssertionError(f"deny daemon never wrote a descriptor; log:\n{log_path.read_text(errors='replace')[-2000:]}")
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
        raise AssertionError(f"deny daemon did not become reachable at {base_url}")
    return proc, desc, data


def stop_daemon(proc: subprocess.Popen, desc: Path) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    # The Popen handle is the `uv run` wrapper; sweep the python child by its
    # exact descriptor path so no daemon outlives the check.
    subprocess.run(
        ["pkill", "-f", f"deny_daemon.py --descriptor {desc}"],
        check=False, capture_output=True,
    )


def fetch_json(base_url: str, token: str, path: str) -> object:
    request = urllib.request.Request(base_url + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_task_events(base_url: str, token: str, task_id: str) -> str:
    request = urllib.request.Request(
        base_url + f"/v1/surface/tasks/{task_id}/events?after=0&wait_ms=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8")


def check_frame(tui: Tui) -> None:
    tui.wait_until(lambda text: "Quick start" in text, BOOT_TIMEOUT, "the home panel")

    tui.type("please update fixture.txt")
    tui.press(b"\r")

    # 1. The refusal card, with the rule the operator wrote and their own reason.
    text = tui.wait_until(
        lambda frame: f"denied by rule {RULE_ID}" in frame,
        TURN_TIMEOUT,
        "the DENY card",
    )
    denial_rows = rows_containing(text, f"denied by rule {RULE_ID}")
    assert len(denial_rows) == 1, f"expected exactly one denial row, got {denial_rows}"
    denial_row = denial_rows[0]
    assert DENIED_CAPABILITY in denial_row, f"denial row names no capability: {denial_row!r}"
    assert "✗" in denial_row, f"the denial must render as a failed (✗) card: {denial_row!r}"
    assert RULE_REASON in denial_row, f"the operator's reason is missing: {denial_row!r}"
    assert "⏵" not in denial_row, "a refusal is not a pending proposal"
    assert "☑" not in denial_row, "a refusal is not a success"

    # 2. An ORDINARY tool failure in the same transcript renders the same ✗
    #    marker, so the marker alone cannot separate them — and one of them
    #    names a rule. That difference is the operator's only signal, so assert
    #    it as a relation between the two rows rather than as two spellings.
    settled = tui.wait_until(
        lambda frame: FINAL_CLAIM in frame and MISSING_PATH in frame,
        TURN_TIMEOUT,
        "the ordinary failure card and the model's closing claim",
    )
    failure_rows = [
        row for row in rows_containing(settled, "workspace.read") if MISSING_PATH in row
    ]
    assert failure_rows, f"no ordinary failure card for workspace.read: {settled!r}"
    failure_row = failure_rows[0]
    assert "✗" in failure_row, f"an ordinary dispatch failure renders ✗ too: {failure_row!r}"
    assert "error" in failure_row.lower(), f"ordinary failure carries no error text: {failure_row!r}"
    assert "denied by rule" not in failure_row, (
        f"an ordinary failure must not look like a policy refusal: {failure_row!r}"
    )
    assert denial_row != failure_row
    assert "denied by rule" not in settled.replace(denial_row, ""), (
        "exactly one row may carry the denial marker"
    )

    # 3. The model's own (false) claim is on screen next to the card: the card is
    #    the only thing contradicting it, which is why it has to be visible.
    assert FINAL_CLAIM in settled, "the scripted model claim never rendered"

    if "✗ workspace.edit" not in settled:
        raise AssertionError(f"the denial card row is malformed: {denial_row!r}")


def check_durable_truth(desc_data: dict, workspace: Path) -> None:
    base_url = f"http://{desc_data['host']}:{desc_data['port']}"
    token = desc_data["bearer_token"]
    listing = fetch_json(base_url, token, "/v1/surface/sessions?limit=10")
    sessions = listing["sessions"]  # type: ignore[index]
    assert sessions, "the daemon recorded no session for the pty turn"
    session_id = sessions[0]["session_id"]
    snapshot = fetch_json(base_url, token, f"/v1/surface/sessions/{session_id}")
    task_id = snapshot["session"]["task_id"]  # type: ignore[index]

    body = fetch_task_events(base_url, token, task_id)
    events = [
        json.loads(line[len("data: "):])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]

    def payloads(event_type: str) -> list[dict]:
        decoded = []
        for event in events:
            if event.get("event_type") != event_type:
                continue
            decoded.append(json.loads(event["payload_json"]))
        return decoded

    denials = [
        payload
        for payload in payloads("POLICY_VERDICT_RECORDED")
        if payload.get("verdict") == "DENY"
        and payload.get("capability_id") == DENIED_CAPABILITY
    ]
    assert len(denials) == 1, (
        f"expected exactly one durable rule denial for {DENIED_CAPABILITY}, got {denials}; "
        f"event types seen: {[event.get('event_type') for event in events]}"
    )
    denial = denials[0]
    assert denial["basis"] == "rule", denial
    assert denial["rule_id"] == RULE_ID, denial
    assert denial["rule_reason"] == RULE_REASON, denial
    assert denial["action_id"], "the durable denial must identify the refused action"
    assert denial["action_digest"], "the durable denial must carry the action digest"
    # The refused action was never proposed and never dispatched: the verdict is
    # its only record, and no receipt may exist for it.
    refused_action = denial["action_id"]
    assert all(
        payload.get("action_id") != refused_action
        for payload in payloads("ACTION_RECEIPT_RECORDED")
    ), "a refused action must never be dispatched — no receipt may exist for it"
    assert all(
        (payload.get("action") or {}).get("action_id") != refused_action
        for payload in payloads("ACTION_PROPOSED")
    ), "a refused action is not a proposal"
    fixture = (workspace / "fixture.txt").read_text(encoding="utf-8")
    assert fixture == "cli-ts spike fixture\n", f"the refused edit reached the file: {fixture!r}"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cli-ts-deny-pty-") as tmp_str:
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
                check_frame(tui)
            except AssertionError:
                sys.stderr.write("\n[pty-deny] TUI screen at failure:\n" + tui.pump(0.5) + "\n")
                raise
            check_durable_truth(desc_data, tmp / "workspace")
            tui.press(b"\x03")  # Ctrl-C
            tui.pump(3)
            try:
                cli.wait(timeout=10)
            except subprocess.TimeoutExpired as exc:
                raise AssertionError("Ctrl-C did not exit the TUI within 10s") from exc
            assert cli.returncode == 0, f"Ctrl-C exit code was {cli.returncode}, expected 0"
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
        "[pty-deny] PASS: a rule DENY renders in a real frame as its own failed "
        f"card ({DENIED_CAPABILITY} · denied by rule {RULE_ID} — {RULE_REASON}), "
        "distinguishable from an ordinary ✗ failure in the same transcript, "
        "next to the model's false 'done' claim; the durable log carries the "
        "DENY with no receipt for it and the workspace file is unchanged"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"[pty-deny] FAIL: {exc}")
        sys.exit(1)
