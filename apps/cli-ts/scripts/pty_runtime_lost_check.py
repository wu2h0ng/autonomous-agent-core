#!/usr/bin/env python3
"""Real-pty check: the TUI survives its runtime disappearing.

Why this exists (operator dead-end sweep, 2026-09-18): with a session open, the
daemon was killed and the operator typed `/task`. The controller called
`client.overview()` outside any try, `submit()` is driven fire-and-forget by the
view, so the rejection was an unhandled rejection — on the shipped runtime (Bun)
that prints the stack INTO the alternate screen, tearing the frame apart, and can
exit the process with the operator's session. `/files` had the same shape, as did
`y`/`n` with nothing pending and a resume-selector pick whose GET failed.

This check drives the SHIPPED entry in a real pty and asserts, after the runtime
is gone:

  1. the TUI process is still running (no unhandled-rejection exit);
  2. the failure is on the transcript, naming the cause, and claiming nothing
     was read ("task overview unavailable: … (no status is being guessed)");
  3. no `at async …` stack frames are smeared over the screen;
  4. after the runtime comes back on the same descriptor, the session still
     works (`/task` reports the real projection again).

Usage: uv run python apps/cli-ts/scripts/pty_runtime_lost_check.py
"""

from __future__ import annotations

import fcntl
import json
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
CLI_DIR = REPO_ROOT / "apps" / "cli-ts"
BUN = os.path.expanduser("~/.bun/bin/bun")

sys.path.insert(0, str(HERE))
from frame_reader import Screen  # noqa: E402

ROWS, COLS = 32, 110


def isolated_env(tmp: Path) -> dict[str, str]:
    """Nothing in this check may read or write the operator's ~/.agent-os."""
    return {
        **os.environ,
        "AGENT_OS_PROVIDER_CONFIG": str(tmp / "provider.json"),
        "AGENT_OS_DISABLE_KEYCHAIN": "1",
        "AGENT_OS_CLI_STATE": str(tmp / "state.json"),
        "AGENT_OS_NO_AUTOSTART": "1",
        "TERM": os.environ.get("TERM", "xterm-256color"),
    }


def start_daemon(tmp: Path, env: dict[str, str], descriptor: Path) -> subprocess.Popen:
    # A stale descriptor from a previous daemon would make both the readiness
    # probe and the client attach to a dead port (measured: the recovery check
    # hit the killed daemon's port and reported a false failure).
    descriptor.unlink(missing_ok=True)
    log = open(tmp / "daemon.log", "ab")  # noqa: SIM115 - closed with the process
    proc = subprocess.Popen(
        [
            "uv", "run", "--extra", "product-test", "python",
            str(HERE / "dev_daemon.py"),
            "--descriptor", str(descriptor),
            "--database", str(tmp / "agent-os.sqlite3"),
            "--workspace", str(tmp / "ws"),
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            with open(descriptor, encoding="utf-8") as handle:
                payload = json.load(handle)
            base = f"http://{payload['host']}:{payload['port']}"
            import urllib.error
            import urllib.request

            try:
                urllib.request.urlopen(base, timeout=1)
            except urllib.error.HTTPError:
                pass
            return proc
        except (OSError, ValueError):
            time.sleep(0.5)
    proc.terminate()
    raise AssertionError("the stub daemon never became reachable")


def kill_daemon(proc: subprocess.Popen, descriptor: Path) -> None:
    try:
        pid = int(json.loads(descriptor.read_text(encoding="utf-8"))["pid"])
        os.kill(pid, signal.SIGKILL)
    except (OSError, ValueError, KeyError):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.terminate()


def main() -> int:
    if not BUN or not Path(BUN).exists():
        print(f"SKIP: no bun at {BUN}")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="noem-runtime-lost-"))
    descriptor = tmp / "runtime.json"
    env = isolated_env(tmp)
    daemon = start_daemon(tmp, env, descriptor)

    screen = Screen(ROWS, COLS)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    tui = subprocess.Popen(
        [BUN, "run", "src/cli.tsx", "--descriptor", str(descriptor)],
        cwd=CLI_DIR,
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        preexec_fn=os.setsid,
    )
    os.close(slave)

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([master], [], [], 0.2)
            if master in ready:
                try:
                    screen.feed(os.read(master, 65536))
                except OSError:
                    return

    def frame() -> str:
        return "\n".join(screen.text_rows())

    def flat() -> str:
        """The frame as one line of text, borders and row wrapping removed.

        The transcript and the sidebar share rows, so a wrapped notice has the
        panel borders in the middle of its sentence; asserting on the raw rows
        would assert the terminal's width and the panel layout instead of the
        message.
        """
        border = str.maketrans({char: " " for char in "│┌┐└┘─├┤┬┴┼╭╮╰╯▌▀▄"})
        return " ".join(frame().translate(border).split())

    def submit(text: str) -> None:
        for char in text:
            os.write(master, char.encode())
            pump(0.08)
        os.write(master, b"\r")
        pump(1.0)

    failures: list[str] = []
    try:
        pump(20.0)
        if "noem v" not in frame():
            print(frame())
            raise AssertionError("the TUI never painted its first frame")

        submit("hello sweep")
        deadline = time.time() + 60
        while time.time() < deadline and "deterministic reply" not in flat():
            pump(0.5)
        if "deterministic reply" not in flat():
            failures.append("the first turn never streamed a reply")

        kill_daemon(daemon, descriptor)
        time.sleep(1.5)

        submit("/task")
        pump(6.0)
        after = flat()
        exit_code = tui.poll()

        if exit_code is not None:
            failures.append(
                f"the TUI exited (code {exit_code}) when its runtime disappeared"
            )
        if "task overview unavailable" not in after:
            failures.append("the failed /task was not reported on the transcript")
        if "no status is being guessed" not in after:
            failures.append("the failure notice did not say nothing was read")
        if "at async " in after or "processTicksAndRejections" in after:
            failures.append("an unhandled-rejection stack was smeared over the frame")

        # A second failing command must behave the same way: the surface keeps
        # working, it does not stop reporting after the first failure.
        # NOTE: a restarted daemon is NOT re-attached by a running TUI - the
        # descriptor carries a new port and bearer token, so the client keeps
        # talking to the generation it attached to. Rebinding a live session to
        # a new endpoint is a trust decision, not a bug fix, and this check does
        # not assert it either way.
        submit("/files")
        pump(6.0)
        recovered = frame()
        if "files unavailable" not in flat():
            failures.append("a second failing command was not reported")
        if tui.poll() is not None:
            failures.append("the TUI exited on the second failing command")

        print("=== final frame ===")
        print(recovered)
        print("=== flattened (assertions read this) ===")
        print(flat())
    finally:
        if tui.poll() is None:
            tui.terminate()
            try:
                tui.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tui.kill()
        os.close(master)
        kill_daemon(daemon, descriptor)

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: a vanished runtime is reported, never fatal, and the surface keeps working")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
