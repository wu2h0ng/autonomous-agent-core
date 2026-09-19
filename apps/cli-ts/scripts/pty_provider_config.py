#!/usr/bin/env python3
"""P5 frame gate: the interactive `/provider` setup wizard renders a MASKED key
input, submits to the local surface, and never leaks the fake key to a frame.

Hermetic by construction:
  * a loopback OpenAI-compatible stub answers the daemon's configure smoke test
    (no live call to any vendor, no money);
  * the daemon runs with AGENT_OS_PROVIDER_CONFIG pointed at a temp dir and
    AGENT_OS_DISABLE_KEYCHAIN=1, so the real keychain and ~/.agent-os are untouched;
  * the fake key is `sk-test-secret-...` and is asserted absent from EVERY raw
    pty frame and from the persisted provider.json.

Run from apps/cli-ts:

    uv run python scripts/pty_provider_config.py
"""
from __future__ import annotations

import fcntl
import json
import os
import pty
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from frame_reader import Screen  # noqa: E402

ROOT = HERE.parents[2]
CLI = ROOT / "apps" / "cli-ts"

FAKE_KEY = "sk-test-secret-zyx9"
LOCATE_TIMEOUT = 25.0


class _StubChat(BaseHTTPRequestHandler):
    """Loopback OpenAI-compatible /chat/completions for the configure smoke test."""

    def log_message(self, *args: object) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if not self.path.endswith("/chat/completions"):
            self.send_response(404)
            self.end_headers()
            return
        payload = {
            "id": "stub",
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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


def pump(fd: int, screen: Screen, seconds: float, raw: bytearray) -> None:
    end = time.time() + seconds
    while time.time() < end:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            raw.extend(chunk)
            screen.feed(chunk)


def wait_row(fd: int, screen: Screen, token: str, what: str, raw: bytearray) -> int:
    deadline = time.time() + LOCATE_TIMEOUT
    while time.time() < deadline:
        idx = screen.find_row(token)
        if idx >= 0:
            return idx
        pump(fd, screen, 0.4, raw)
    raise AssertionError(f"{what} row ({token!r}) never rendered")


def send_str(fd: int, text: str, gap: float = 0.02) -> None:
    for ch in text:
        os.write(fd, ch.encode("utf-8"))
        time.sleep(gap)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="p5-provider-"))
    descriptor = tmp / "r.json"
    workspace = tmp / "ws"
    workspace.mkdir()
    provider_config = tmp / "provider.json"

    # Loopback stub for the configure smoke test.
    stub = ThreadingHTTPServer(("127.0.0.1", 0), _StubChat)
    stub_port = stub.server_address[1]
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    stub_base = f"http://127.0.0.1:{stub_port}/v1"

    daemon_env = dict(os.environ)
    daemon_env["AGENT_OS_PROVIDER_CONFIG"] = str(provider_config)
    daemon_env["AGENT_OS_DISABLE_KEYCHAIN"] = "1"
    daemon = subprocess.Popen(
        [
            sys.executable, "apps/cli-ts/scripts/dev_daemon.py",
            "--descriptor", str(descriptor),
            "--database", str(tmp / "a.sqlite3"),
            "--workspace", str(workspace),
        ],
        cwd=ROOT,
        env=daemon_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        if descriptor.exists():
            break
        time.sleep(0.5)
    time.sleep(1.5)

    screen = Screen(40, 120)
    raw = bytearray()
    pid: int | None = None
    try:
        pid, fd = spawn(descriptor)
        pump(fd, screen, 6, raw)

        # 1) Open the setup wizard.
        send_str(fd, "/provider setup")
        os.write(fd, b"\r")
        pump(fd, screen, 2, raw)
        wait_row(fd, screen, "DeepSeek", "preset list", raw)

        # 2) Move to the last preset (Custom OpenAI-compatible) and choose it.
        for _ in range(5):
            os.write(fd, b"\x1b[B")  # Down
            time.sleep(0.05)
        os.write(fd, b"\r")
        pump(fd, screen, 2, raw)
        wait_row(fd, screen, "base_url", "provider form", raw)

        # 3) Type the stub base URL, tab to model, type model, tab twice (model ->
        #    endpoint class -> api_key), then type the fake key.
        send_str(fd, stub_base)
        os.write(fd, b"\t")
        pump(fd, screen, 0.5, raw)
        send_str(fd, "stub-model")
        os.write(fd, b"\t")  # -> endpoint class (cycles, leave as openai-compatible)
        time.sleep(0.1)
        os.write(fd, b"\t")  # -> api_key
        pump(fd, screen, 0.5, raw)

        # 4) Type the fake key. It must render as bullets, never as itself.
        send_str(fd, FAKE_KEY, gap=0.01)
        pump(fd, screen, 1, raw)
        key_row = wait_row(fd, screen, "api_key", "masked key row", raw)
        row_text = "".join(t for t, _, _, _ in screen.spans(key_row))
        assert "•" in row_text, f"key row shows no mask bullets: {row_text!r}"
        assert FAKE_KEY not in row_text, f"plaintext key leaked into a frame row: {row_text!r}"

        # 5) Submit.
        os.write(fd, b"\r")
        pump(fd, screen, 4, raw)

        # Success card: redacted model + key source, no plaintext key.
        try:
            wait_row(fd, screen, "configured", "success card", raw)
        except AssertionError:
            print("--- SCREEN DUMP AFTER SUBMIT ---", file=sys.stderr)
            for i in range(screen.rows):
                print("".join(t for t, _, _, _ in screen.spans(i)), file=sys.stderr)
            raise
        all_rows = "\n".join(
            "".join(t for t, _, _, _ in screen.spans(i)) for i in range(screen.rows)
        )
        assert FAKE_KEY not in all_rows, "plaintext key leaked into a rendered row after submit"

        # The fake key must never have been on the wire to the pty at all.
        assert FAKE_KEY.encode() not in bytes(raw), (
            "plaintext key bytes appeared in the raw pty stream"
        )

        # provider.json holds only non-secret fields.
        assert provider_config.exists(), "provider.json was not persisted"
        persisted = provider_config.read_text(encoding="utf-8")
        assert "sk-" not in persisted, f"api_key leaked into provider.json: {persisted!r}"
        assert "stub-model" in persisted, f"model not persisted: {persisted!r}"
        assert "base_url" in persisted, f"base_url not persisted: {persisted!r}"

        os.write(fd, b"\x03")
        time.sleep(0.4)
        print("P5_PROVIDER_CONFIG_PASS: masked key, redacted success card, provider.json clean")
        return 0
    finally:
        if pid is not None:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        daemon.terminate()
        try:
            daemon.wait(timeout=5)
        except subprocess.TimeoutExpired:
            daemon.kill()
        stub.shutdown()
        stub.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
