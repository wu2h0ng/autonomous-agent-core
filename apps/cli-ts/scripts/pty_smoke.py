#!/usr/bin/env python3
"""pty smoke for the cli-ts Ink client — drives the REAL TUI in a real pty.

Why this exists (iteration-16): unit tests and the headless path cannot catch
terminal-handling regressions (raw mode, per-key input parsing, Ink redraw).
This script boots the hermetic dev_daemon, runs the real CLI under a pty,
types keystrokes ONE BYTE AT A TIME (like a human), and asserts:

  phase 1 (24x80): initial render shows the status line, typed input echoes,
                   Enter submits and the deterministic reply streams in,
                   Ctrl-C exits the process.
  phase 2 (12x40): same flow under a tiny terminal (wrapping/scroll stress,
                   CJK intact), then a mid-session resize to 30x100 must
                   relayout and keep the TUI responsive (iteration-17).

Lessons encoded:
  - Never write multi-byte input in a single pty write — the kernel coalesces
    it into one read, Ink's input-parser emits it as one event, and a trailing
    \\r is then parsed as paste text, not Return (false alarm in iteration-16).
    Per-key writes are required for a faithful probe.
  - Each phase needs its OWN daemon: dev_daemon's scripted provider advances
    one turn per submit (turn 1 = streaming text, turn 2 = edit proposal), so
    reusing a daemon across phases silently changes the expected reply.

Usage: uv run python apps/cli-ts/scripts/pty_smoke.py
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
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_DIR = REPO_ROOT / "apps" / "cli-ts"
CLI_ENTRY = CLI_DIR / "src" / "cli.tsx"
TSX = CLI_DIR / "node_modules" / ".bin" / "tsx"

# Generous, env-overridable timeouts: under a loaded `e2e` chain (multiple uv
# daemons + tsx startup) a fixed 2s readiness sleep and 10s/20s drains raced.
BOOT_TIMEOUT = float(os.environ.get("CLI_TS_PTY_BOOT_TIMEOUT", "30"))
TURN_TIMEOUT = float(os.environ.get("CLI_TS_PTY_TURN_TIMEOUT", "60"))

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


def strip(data: bytes) -> str:
    return ANSI_RE.sub("", data.decode(errors="replace"))


class Daemon:
    """Isolated dev_daemon on an ephemeral port; killed on exit."""

    def __init__(self, tmp: Path, name: str) -> None:
        self.desc = tmp / f"{name}-runtime.json"
        # Capture daemon output: DEVNULL made a crash/timeout undiagnosable.
        self.log_path = tmp / f"{name}.daemon.log"
        self._log = open(self.log_path, "wb")  # noqa: SIM115 - closed in stop()
        self.proc = subprocess.Popen(
            [
                "uv", "run", "python",
                str(REPO_ROOT / "apps" / "cli-ts" / "scripts" / "dev_daemon.py"),
                "--descriptor", str(self.desc),
                "--database", str(tmp / f"{name}.sqlite3"),
                "--workspace", str(tmp / f"{name}-ws"),
            ],
            cwd=REPO_ROOT,
            stdout=self._log,
            stderr=subprocess.STDOUT,
        )
        for _ in range(60):
            if self.desc.exists():
                break
            time.sleep(0.5)
        if not self.desc.exists():
            self.proc.terminate()
            raise AssertionError(f"daemon {name} never wrote descriptor")
        self._wait_ready(name)

    def _wait_ready(self, name: str) -> None:
        """Poll the daemon over HTTP until it answers (any status = up).

        Descriptor existence alone is not readiness; a fixed sleep raced under
        the loaded e2e chain and produced flaky 'no streamed reply' failures.
        """
        data = json.loads(self.desc.read_text("utf-8"))
        base_url = f"http://{data['host']}:{data['port']}"
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                urllib.request.urlopen(base_url, timeout=1)
                return
            except urllib.error.HTTPError:
                return  # server answered (4xx/5xx) -> it is up
            except Exception:
                time.sleep(0.3)
        self.proc.terminate()
        raise AssertionError(f"daemon {name} did not become reachable at {base_url}")

    def stop(self) -> None:
        self.proc.terminate()
        self.proc.wait(timeout=10)
        # The Popen handle is the `uv run` wrapper; sweep the python child
        # by its exact descriptor path (orphan found in iteration-21).
        subprocess.run(
            ["pkill", "-f", f"dev_daemon.py --descriptor {self.desc}"],
            check=False, capture_output=True,
        )
        self._log.close()


def run_tui(desc: Path, rows: int, cols: int, body) -> None:
    """Spawn the real CLI in a pty of the given size; `body(master)` drives it."""
    master, slave = pty.openpty()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    proc = subprocess.Popen(
        [str(TSX), str(CLI_ENTRY), "--descriptor", str(desc)],
        stdin=slave, stdout=slave, stderr=slave, close_fds=True,
        # Keep the run hermetic: never read/write the developer's real
        # ~/.agent-os/cli-ts-state.json (history/theme/goal persistence).
        env={**os.environ, "AGENT_OS_CLI_STATE": str(Path(desc).parent / "cli-ts-state.json")},
    )
    os.close(slave)
    try:
        try:
            body(master)
        except AssertionError:
            # Surface what the TUI actually rendered so a flake is diagnosable.
            try:
                tail = strip(drain(master, 0.5))
                sys.stderr.write("\n[pty-smoke] TUI output at failure (tail):\n" + tail[-2000:] + "\n")
            except Exception:
                pass
            raise
        os.write(master, b"\x03")  # Ctrl-C
        drain(master, 3)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            raise AssertionError("Ctrl-C did not exit the TUI within 10s")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Never let cleanup mask the real AssertionError (it must not
                # escape as TimeoutExpired, or the phase retry is defeated).
                proc.kill()
                proc.wait(timeout=5)


def phase1(master: int) -> None:
    out = drain(master, BOOT_TIMEOUT, until="/help")
    assert "/help" in strip(out), "initial render missing status line"

    out = type_keys(master, "hello pty")
    assert "hello pty" in strip(out), "typed input did not echo"

    os.write(master, b"\r")
    out = drain(master, TURN_TIMEOUT, until="deterministic")
    assert "deterministic" in strip(out), (
        f"Enter did not submit / no streamed reply within {TURN_TIMEOUT:.0f}s"
    )


def phase2(master: int) -> None:
    out = drain(master, BOOT_TIMEOUT, until="/help")
    assert "/help" in strip(out), "narrow boot: missing status line"

    type_keys(master, "hi")
    os.write(master, b"\r")
    out = drain(master, TURN_TIMEOUT, until="流式")
    text = strip(out)
    assert "deterministic" in text, "narrow terminal: no streamed reply"
    assert "流式" in text, "narrow terminal: CJK reply corrupted"

    # resize 12x40 -> 30x100: TUI must relayout and stay responsive
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
    drain(master, 1)
    type_keys(master, "/help")
    os.write(master, b"\r")
    out = drain(master, 15)
    assert "files" in strip(out), "post-resize: /help did not render"


def phase3(master: int) -> None:
    """Approval flow in a real pty (iteration-18): turn 2 of the scripted
    daemon proposes workspace.edit -> WAITING_APPROVAL in ASK mode; pressing
    'y' is the human-only approve path and the continuation text streams."""
    out = drain(master, BOOT_TIMEOUT, until="/help")
    assert "/help" in strip(out), "approval phase: missing status line"

    type_keys(master, "hi")
    os.write(master, b"\r")
    out = drain(master, TURN_TIMEOUT, until="deterministic")
    assert "deterministic" in strip(out), "approval phase: turn 1 did not stream"

    # Regression guard (iteration-18): turn 2 must not be rejected with a
    # stale expected_event_sequence after a durable-resolved turn 1.
    type_keys(master, "edit please")
    os.write(master, b"\r")
    out = drain(master, TURN_TIMEOUT, until="[y] approve")
    out += drain(master, 3)  # settle frames
    text = strip(out)
    assert "does not match current sequence" not in text, (
        "turn 2 rejected with stale expected_event_sequence"
    )
    assert "approval required" in text, "approval card did not render"
    assert "unknown capability" not in text, (
        "approval card flashed an empty snapshot frame"
    )
    assert "workspace.edit" in text, "approval card missing capability id"
    assert "digest " in text, "approval card missing digest line"

    os.write(master, b"y")
    out = drain(master, TURN_TIMEOUT, until="edit applied")
    assert "edit applied" in strip(out), "approve (y) did not apply the edit"


def run_phase(tmp: Path, name: str, rows: int, cols: int, body, attempts: int = 2) -> None:
    """Run a phase with a fresh daemon, retrying once with diagnostics.

    The race is a daemon/TUI turn-timing flake under the loaded e2e chain; a
    fresh-daemon retry keeps the gate meaningful while daemon logs (captured in
    Daemon) make any residual failure diagnosable.
    """
    last_error: AssertionError | None = None
    for attempt in range(attempts):
        daemon = Daemon(tmp, f"{name}-a{attempt}")
        try:
            run_tui(daemon.desc, rows, cols, body)
            return
        except AssertionError as exc:
            last_error = exc
            sys.stderr.write(f"[pty-smoke] {name} attempt {attempt + 1}/{attempts} failed: {exc}\n")
            if attempt + 1 == attempts and daemon.log_path.exists():
                log = daemon.log_path.read_text(errors="replace")
                sys.stderr.write(f"[pty-smoke] {name} daemon log tail:\n{log[-2000:]}\n")
        finally:
            daemon.stop()
    raise last_error if last_error is not None else AssertionError(name)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cli-ts-pty-") as tmp_str:
        tmp = Path(tmp_str)
        run_phase(tmp, "p1", 24, 80, phase1)
        run_phase(tmp, "p2", 12, 40, phase2)
        run_phase(tmp, "p3", 24, 80, phase3)

    print("[pty-smoke] PASS: render / typing echo / Enter submit+stream / "
          "Ctrl-C exit / narrow+resize relayout / approval card y-approve")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"[pty-smoke] FAIL: {exc}")
        sys.exit(1)
