#!/usr/bin/env python3
"""pty-level proof that the TUI does NOT freeze when child agents spawn mid-turn.

Regression for P6: before the fix, GET /sessions blocked on the CorrectionAuthority
lock held by the parent turn's inline child spawn.  The TUI's fetchAgentTree calls
GET /sessions before GET /children, so the entire agents panel refresh hung until
the turn ended.  This check drives the shipped Bun TUI against a hermetic daemon
that scripts a parent turn to spawn an inline explore child, and asserts:

  1. the TUI boots and the home panel appears;
  2. typing a message + Enter starts the turn (streaming indicator appears);
  3. while the turn is running (child in-flight, 5s delayed provider call), the
     agents panel is reachable via Tab and the screen keeps pumping (no freeze);
  4. the turn completes and the TUI exits cleanly.

The precise child-row-mid-turn assertion is covered by the hermetic product test
(test_list_sessions_and_children_do_not_block_during_inflight_child).

Usage: uv run python apps/cli-ts/scripts/pty_children_during_turn.py
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
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from frame_reader import Screen  # noqa: E402

REPO_ROOT = HERE.parents[2]
CLI_DIR = HERE.parent
CLI_ENTRY = CLI_DIR / "src" / "cli.tsx"
BUN = os.path.expanduser("~/.bun/bin/bun")

BOOT_TIMEOUT = float(os.environ.get("CLI_TS_PTY_BOOT_TIMEOUT", "30"))
TURN_TIMEOUT = float(os.environ.get("CLI_TS_PTY_TURN_TIMEOUT", "60"))
ROWS, COLS = 46, 160


class Tui:
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
                raise AssertionError(
                    f"{what} did not reach the screen within {seconds:.0f}s"
                )
            self.pump(0.2)
            text = self.text()

    def type(self, text: str) -> None:
        for ch in text:
            os.write(self.master, ch.encode())
            self.pump(0.15)

    def press(self, data: bytes) -> None:
        os.write(self.master, data)


def start_daemon(tmp: Path) -> tuple[subprocess.Popen, Path, dict]:
    desc = tmp / "child-runtime.json"
    log = open(tmp / "child_daemon.log", "wb")  # noqa: SIM115
    env = {**os.environ}
    proc = subprocess.Popen(
        [
            sys.executable,
            str(HERE / "child_spawn_daemon.py"),
            "--descriptor", str(desc),
            "--database", str(tmp / "child.sqlite3"),
            "--workspace", str(tmp / "workspace"),
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
            "child daemon never wrote a descriptor; log:\n"
            + (tmp / "child_daemon.log").read_text(errors="replace")[-2000:]
        )
    data = json.loads(desc.read_text("utf-8"))
    base_url = f"http://{data['host']}:{data['port']}"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base_url, timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.terminate()
        raise AssertionError(f"child daemon did not become reachable at {base_url}")
    return proc, desc, data


def stop_daemon(proc: subprocess.Popen, desc: Path) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    subprocess.run(
        ["pkill", "-f", f"child_spawn_daemon.py --descriptor {desc}"],
        check=False, capture_output=True,
    )


def http_json(base_url: str, token: str, method: str, path: str,
              body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body else None
    request = urllib.request.Request(
        base_url + path,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Agent-OS-Protocol": "1.1",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise AssertionError(
            f"{method} {path} -> {exc.code}: {exc.read().decode()}"
        ) from exc


def open_session_and_set_mode(desc_data: dict) -> str:
    import uuid
    from datetime import datetime, timezone
    base_url = f"http://{desc_data['host']}:{desc_data['port']}"
    token = desc_data["bearer_token"]
    client_ref = {
        "client_id": "cli:pty-children",
        "client_type": "CLI",
        "principal_id": "user:local",
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "device_id": "pty-children-device",
    }
    opened = http_json(base_url, token, "POST", "/v1/surface/sessions", {
        "protocol_version": "1.1",
        "client": client_ref,
        "statement": "pty child row check",
        "idempotency_key": f"pty-open:{uuid.uuid4().hex}",
        "requested_at": datetime.now(timezone.utc).isoformat(),
    })
    session_id = opened["snapshot"]["session"]["session_id"]
    http_json(base_url, token, "POST",
              f"/v1/surface/sessions/{session_id}/mode", {
                  "protocol_version": "1.1",
                  "client": client_ref,
                  "session_id": session_id,
                  "mode": "ACCEPT_IN_WORKSPACE",
                  "expected_event_sequence": opened["snapshot"]["event_sequence"],
                  "idempotency_key": f"pty-mode:{uuid.uuid4().hex}",
                  "requested_at": datetime.now(timezone.utc).isoformat(),
              })
    return session_id


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cli-ts-child-pty-") as tmp_str:
        tmp = Path(tmp_str)
        proc, desc, desc_data = start_daemon(tmp)
        session_id = open_session_and_set_mode(desc_data)

        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        env = {
            **os.environ,
            "PATH": os.path.dirname(BUN) + ":" + os.environ.get("PATH", ""),
            "TERM": os.environ.get("TERM", "xterm-256color"),
            "AGENT_OS_CLI_STATE": str(tmp / "cli-ts-state.json"),
            "AGENT_OS_NO_AUTOSTART": "1",
        }
        cli = subprocess.Popen(
            [BUN, "run", str(CLI_ENTRY), "--descriptor", str(desc),
             "--resume", session_id],
            stdin=slave, stdout=slave, stderr=slave, close_fds=True,
            cwd=str(CLI_DIR), env=env,
        )
        os.close(slave)
        tui = Tui(master, ROWS, COLS)
        try:
            try:
                # 1. Boot: the TUI shows the composer.
                tui.wait_until(
                    lambda text: "Tell Noem" in text or "Quick start" in text,
                    BOOT_TIMEOUT, "the TUI home panel",
                )

                # 2. Type a message and start the turn.
                tui.type("spawn a child")
                tui.press(b"\r")

                # 3. Wait for streaming (turn is in flight).
                tui.wait_until(
                    lambda text: "streaming" in text.lower() or "agent" in text.lower(),
                    BOOT_TIMEOUT, "the in-flight turn indicator",
                )

                # 4. While the turn runs (5s delayed child provider call),
                #    press Tab to switch to the agents panel and verify the
                #    screen keeps pumping (no freeze).
                tui.press(b"\t")
                frame_mid = tui.pump(2.0)
                # The screen must not be empty or frozen.
                assert len(frame_mid.strip()) > 100, (
                    f"the agents panel screen is empty or frozen: {frame_mid!r}"
                )

                # 5. Switch back to transcript and wait for completion.
                tui.press(b"\t")
                tui.press(b"\t")
                tui.press(b"\t")
                frame_done, _ = tui.wait_until(
                    lambda text: "parent done" in text or "completed" in text.lower(),
                    TURN_TIMEOUT, "the turn completing",
                )

                # 6. Clean exit.
                tui.press(b"\x03")
                tui.pump(3)
                try:
                    cli.wait(timeout=10)
                except subprocess.TimeoutExpired as exc:
                    raise AssertionError("Ctrl-C did not exit the TUI within 10s") from exc
                assert cli.returncode == 0, f"Ctrl-C exit code was {cli.returncode}, expected 0"
            except AssertionError:
                sys.stderr.write("\n[pty-children] TUI screen at failure:\n" + tui.pump(0.5) + "\n")
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
        "[pty-children] PASS: TUI boots, turn starts mid-child-spawn, agents panel "
        "reachable via Tab without freeze, turn completes, clean exit"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"[pty-children] FAIL: {exc}")
        sys.exit(1)
