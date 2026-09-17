#!/usr/bin/env python3
"""pty smoke for the cli-ts TUI — drives the SHIPPED entry in a real pty.

Why this exists (iteration-16): unit tests and the headless path cannot catch
terminal-handling regressions (raw mode, per-key input parsing, incremental
redraw). This script boots the hermetic dev_daemon, runs the real CLI
(`src/cli.tsx`) under Bun — the shipped runtime — types keystrokes ONE BYTE AT A
TIME (like a human), and asserts:

  phase 1 (24x80): the home panel owns the first frame, typed input echoes, Enter
                   submits and the deterministic reply streams in, Ctrl-C exits.
  phase 2 (12x40): the same flow under a tiny terminal (narrow home variant,
                   wrapping stress, CJK intact), then a mid-session resize to
                   30x100 must relayout and keep the TUI responsive.
  phase 3 (24x80): turn 2 of the scripted daemon proposes workspace.edit -> the
                   approval card renders, and `y` is the human-only approve path
                   that applies the edit.

WHY THE ASSERTIONS READ THE SCREEN, NOT THE BYTE STREAM: the full-screen view
redraws incrementally, so an ANSI-stripped byte stream carries "hello pty" split
across frames (measured) and a substring assertion on it would be unreliable.
Content is therefore read from the reconstructed terminal screen
(`scripts/frame_reader.py`) — i.e. assert what a human sees.

PROVENANCE OF THE STRINGS: this script used to drive the Ink client through the
same entry (`node_modules/.bin/tsx` + Ink's status line) and asserted Ink's
wording. The entry's TUI is now the full-screen view, so every string below was
re-measured against it; the ones that differ from Ink are marked.

Lessons encoded:
  - Never write multi-byte input in a single pty write — the kernel coalesces
    it into one read and a trailing \\r is then parsed as paste text, not
    Return (false alarm in iteration-16). Per-key writes are required.
  - Each phase needs its OWN daemon: dev_daemon's scripted provider advances one
    turn per submit (turn 1 = streaming text, turn 2 = edit proposal), so
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

HERE = Path("/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/os-sandbox/apps/cli-ts/scripts")
sys.path.insert(0, str(HERE))
from frame_reader import Screen  # noqa: E402

REPO_ROOT = HERE.parents[2]
CLI_DIR = REPO_ROOT / "apps" / "cli-ts"
CLI_ENTRY = CLI_DIR / "src" / "cli.tsx"
# The shipped runtime. Under Bun the entry mounts the full-screen view; under
# node it deliberately refuses with actionable advice (it has no native FFI).
BUN = os.path.expanduser("~/.bun/bin/bun")

# Generous, env-overridable timeouts: under a loaded `e2e` chain (multiple uv
# daemons + a cold Bun start) a fixed readiness sleep and 10s/20s drains raced.
BOOT_TIMEOUT = float(os.environ.get("CLI_TS_PTY_BOOT_TIMEOUT", "30"))
TURN_TIMEOUT = float(os.environ.get("CLI_TS_PTY_TURN_TIMEOUT", "60"))

# A wide (CJK) glyph occupies two terminal cells; frame_reader stores the glyph
# plus a spacer cell, so `text_rows()` renders 终端流式 as "终 端 流 式". Collapse
# ONLY the gap between two CJK glyphs, so unrelated words are never joined.
CJK_GAP_RE = re.compile(r"(?<=[\u3400-\u9fff\u3000-\u303f\uff00-\uffef])[ ]+(?=[\u3400-\u9fff])")


def cjk_join(text: str) -> str:
    """Undo the wide-char spacer cells so CJK substrings can be asserted."""
    return CJK_GAP_RE.sub("", text)


class Tui:
    """A pty running the CLI, plus the reconstructed screen for assertions."""

    def __init__(self, master: int, rows: int, cols: int) -> None:
        self.master = master
        self.screen = Screen(rows, cols)

    def text(self) -> str:
        return "\n".join(self.screen.text_rows())

    def pump(self, seconds: float, until: str | None = None) -> str:
        """Read for up to `seconds`, early-exit once `until` is on screen."""
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

    def wait_for(self, needle: str, seconds: float) -> str:
        text = self.pump(seconds, until=needle)
        assert needle in text, f"{needle!r} did not reach the screen within {seconds:.0f}s"
        return text

    def type(self, text: str) -> None:
        """Type like a human: one key per write with a small gap."""
        for ch in text:
            os.write(self.master, ch.encode())
            self.pump(0.15)

    def press(self, data: bytes) -> None:
        os.write(self.master, data)

    def resize(self, rows: int, cols: int) -> None:
        """Resize the pty; the renderer repaints, so the screen is rebuilt.

        `frame_reader.Screen` has no resize, and a fresh screen is the honest
        model here: on SIGWINCH the view repaints at the new size rather than
        editing the old cells in place.
        """
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.screen = Screen(rows, cols)
        self.pump(2.0)


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
    """Spawn the real CLI in a pty of the given size; `body(tui)` drives it."""
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    env = {
        **os.environ,
        "PATH": os.path.dirname(BUN) + ":" + os.environ.get("PATH", ""),
        "TERM": os.environ.get("TERM", "xterm-256color"),
        # Keep the run hermetic: never read/write the developer's real
        # ~/.agent-os/cli-ts-state.json (history/theme/goal persistence).
        "AGENT_OS_CLI_STATE": str(Path(desc).parent / "cli-ts-state.json"),
    }
    proc = subprocess.Popen(
        [BUN, "run", str(CLI_ENTRY), "--descriptor", str(desc)],
        stdin=slave, stdout=slave, stderr=slave, close_fds=True,
        cwd=str(CLI_DIR), env=env,
    )
    os.close(slave)
    tui = Tui(master, rows, cols)
    try:
        try:
            body(tui)
        except AssertionError:
            # Surface what the TUI actually rendered so a flake is diagnosable.
            try:
                sys.stderr.write(
                    "\n[pty-smoke] TUI screen at failure:\n" + tui.pump(0.5) + "\n"
                )
            except Exception:
                pass
            raise
        tui.press(b"\x03")  # Ctrl-C
        tui.pump(3)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            raise AssertionError("Ctrl-C did not exit the TUI within 10s")
        assert proc.returncode == 0, f"Ctrl-C exit code was {proc.returncode}, expected 0"
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


def phase1(tui: Tui) -> None:
    boot = tui.wait_for("Quick start", BOOT_TIMEOUT)
    # #18: the home panel must own the first frame (the session opens lazily).
    assert "governed terminal agent" in boot, "home panel missing on the first frame"
    assert "◆ noem v" in boot, "top status line missing on the first frame"

    tui.type("hello pty")
    assert "hello pty" in tui.text(), "typed input did not echo in the composer"

    tui.press(b"\r")
    reply = tui.wait_for("deterministic", TURN_TIMEOUT)
    assert "终端流式验证通过" in cjk_join(reply), "streamed reply missing its CJK tail"


def phase2(tui: Tui) -> None:
    # 40 columns < 60, so the panel must use Ink's NARROW variant (no card).
    boot = tui.wait_for("workspace cli-ts", BOOT_TIMEOUT)
    assert "◆ noem v" in boot, "narrow boot: top status line missing"

    tui.type("hi")
    tui.press(b"\r")
    # At 12 rows the transcript is only ~3 lines tall and sticky-scrolls to the
    # bottom, so no single frame holds the whole reply (pumping until it appears
    # would simply time out). Scroll up through the transcript and assert on the
    # union of the frames — which also proves scrolling works under a tiny
    # terminal, the point of this phase.
    tui.pump(12)
    frames = []
    for _ in range(14):
        frames.append(tui.text())
        tui.press(b"\x1b[5~")  # xterm page-up
        tui.pump(0.4)
    frames.append(tui.text())
    text = "\n".join(frames)
    assert "deterministic" in text, "narrow terminal: the reply never streamed"
    assert "流式" in cjk_join(text), "narrow terminal: CJK reply corrupted"

    # resize 12x40 -> 30x100: the TUI must relayout and stay responsive. The
    # palette during `/` typing is the cheapest proof of responsiveness that
    # does not depend on a scrolled transcript row surviving the resize.
    tui.resize(30, 100)
    tui.type("/help")
    text = tui.wait_for("commands", 15)
    assert "/help" in text, "post-resize: the palette did not offer /help"


def phase3(tui: Tui) -> None:
    """Approval flow in a real pty (iteration-18): turn 2 of the scripted
    daemon proposes workspace.edit -> WAITING_APPROVAL in ASK mode; pressing
    'y' is the human-only approve path and the continuation text streams."""
    tui.wait_for("Quick start", BOOT_TIMEOUT)

    tui.type("hi")
    tui.press(b"\r")
    tui.wait_for("deterministic", TURN_TIMEOUT)

    # Regression guard (iteration-18): turn 2 must not be rejected with a
    # stale expected_event_sequence after a durable-resolved turn 1.
    tui.type("edit please")
    tui.press(b"\r")
    tui.wait_for("approval required", TURN_TIMEOUT)
    # The card renders progressively, so the frame that first shows "approval
    # required" can still be missing the digest row (measured). Assert on the
    # settled frame, not on the frame that satisfied the wait.
    card = tui.pump(2.5)
    assert "does not match current sequence" not in card, (
        "turn 2 rejected with stale expected_event_sequence"
    )
    assert "workspace.edit" in card, "approval card missing capability id"
    assert "digest " in card, "approval card missing digest line"
    assert "unknown capability" not in card, (
        "approval card flashed an empty snapshot frame"
    )
    assert "[y] approve" in card, "approval card missing the approve affordance"

    tui.press(b"y")
    applied = tui.wait_for("edit applied", TURN_TIMEOUT)
    assert "fixture.txt" in applied, "approve (y) did not report the edited file"


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

    print("[pty-smoke] PASS: home panel first frame / typing echo / Enter "
          "submit+stream / Ctrl-C exit (rc 0) / narrow+resize relayout / "
          "approval card y-approve")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"[pty-smoke] FAIL: {exc}")
        sys.exit(1)
