#!/usr/bin/env python3
"""Opt-in live evidence: real provider, MULTI-TURN, real pty TUI.

Companion to live_evidence.py (which is headless single-turn). This script
boots AgentOSApplication with the real OpenAI-compatible provider (default:
Kimi coding gateway), then drives the REAL Ink TUI in a real pty through two
dependent turns:

  turn 1: "Reply with exactly: turn one ok"   (model must comply verbatim)
  turn 2: "What did I ask you to reply with?" (requires turn-1 context)

Assertions:
  - turn 1 reply streams into the TUI
  - turn 2 is NOT rejected with a stale expected_event_sequence
    (iteration-18 regression guard against the real kernel, not the stub)
  - turn 2 answer references turn-1 content (durable multi-turn context)
  - clean Ctrl-C exit

Credentials come from the environment, are never persisted or printed.
Model output is recorded only as booleans + a redacted tail (no payloads).

Usage: uv run python apps/cli-ts/scripts/live_multiturn_pty.py --out PATH
"""

from __future__ import annotations

import argparse
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
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[3]
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z]")

TURN1_PROMPT = "Reply with exactly: turn one ok"
TURN1_EXPECT = "turn one ok"
TURN2_PROMPT = "What did I ask you to reply with? One short line."


def drain(master: int, seconds: float, until: str | None = None) -> bytes:
    end = time.time() + seconds
    buf = b""
    while time.time() < end:
        r, _, _ = select.select([master], [], [], 0.2)
        if master in r:
            try:
                buf += os.read(master, 65536)
            except OSError:
                break
            if until and until.lower() in strip(buf).lower():
                break
    return buf


def type_keys(master: int, text: str) -> None:
    for ch in text:
        os.write(master, ch.encode())
        drain(master, 0.05)


def strip(data: bytes) -> str:
    return ANSI_RE.sub("", data.decode(errors="replace"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="evidence JSON path")
    args = parser.parse_args()

    base_url = (
        os.environ.get("AGENT_OS_PROVIDER_BASE_URL")
        or os.environ.get("KIMI_BASE_URL")
        or ""
    ).rstrip("/")
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("KIMI_API_KEY") or ""
    model = os.environ.get("AGENT_OS_PROVIDER_MODEL", "k2d6-agent")
    if not base_url or not api_key:
        raise SystemExit(
            "live evidence requires KIMI_BASE_URL+KIMI_API_KEY "
            "(or AGENT_OS_PROVIDER_BASE_URL+OPENAI_API_KEY)"
        )

    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "packages" / "contracts" / "src"))
    sys.path.insert(0, str(REPO_ROOT / "packages" / "os_core" / "src"))
    from apps.api_server.app import AgentOSApplication
    from apps.api_server.server import build_server

    started = datetime.now(timezone.utc)
    root = Path(tempfile.mkdtemp(prefix="cli-ts-live-pty-"))
    checks: dict[str, bool] = {}
    exit_code: int | None = None
    try:
        app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
        app.configure_provider({"base_url": base_url, "model": model, "api_key": api_key})
        token = f"live-{uuid4()}"
        server = build_server(app, "127.0.0.1", 0, local_token=token)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        desc = root / "runtime.json"
        desc.write_text(
            json.dumps(
                {
                    "protocol_version": "1.1",
                    "pid": os.getpid(),
                    "boot_id": "boot:cli-ts-live-pty",
                    "host": "127.0.0.1",
                    "port": server.server_address[1],
                    "bearer_token": token,
                    "database_path": str(root / "agent-os.sqlite3"),
                    "workspace_path": str(root),
                    "created_at": started.isoformat(),
                }
            ),
            encoding="utf-8",
        )

        master, slave = pty.openpty()
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        proc = subprocess.Popen(
            [
                str(REPO_ROOT / "apps" / "cli-ts" / "node_modules" / ".bin" / "tsx"),
                str(REPO_ROOT / "apps" / "cli-ts" / "src" / "cli.tsx"),
                "--descriptor", str(desc),
            ],
            stdin=slave, stdout=slave, stderr=slave, close_fds=True,
        )
        os.close(slave)
        try:
            out = drain(master, 15, until="/help")
            checks["boot_status_line"] = "/help" in strip(out)

            type_keys(master, TURN1_PROMPT)
            os.write(master, b"\r")
            t1 = strip(drain(master, 90, until=TURN1_EXPECT))
            checks["turn1_model_reply"] = TURN1_EXPECT in t1.lower()

            type_keys(master, TURN2_PROMPT)
            os.write(master, b"\r")
            t2 = strip(drain(master, 90, until=TURN1_EXPECT))
            checks["turn2_no_stale_sequence_error"] = (
                "does not match current sequence" not in t2
            )
            checks["turn2_multiturn_context"] = TURN1_EXPECT in t2.lower()

            os.write(master, b"\x03")
            drain(master, 3)
            proc.wait(timeout=8)
            exit_code = proc.returncode
            checks["clean_ctrl_c_exit"] = exit_code == 0
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
        server.shutdown()
        server.server_close()
    finally:
        finished = datetime.now(timezone.utc)

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd=REPO_ROOT, check=True,
    ).stdout.strip()
    evidence = {
        "evidence_kind": "cli_ts_pty_live_multiturn",
        "recorded_at": finished.isoformat(),
        "duration_seconds": (finished - started).total_seconds(),
        "repo_head": head,
        "provider": {
            "base_url_host": base_url.split("/")[2] if "//" in base_url else base_url,
            "model": model,
        },
        "turns": [
            {"prompt": TURN1_PROMPT, "expected": TURN1_EXPECT},
            {"prompt": TURN2_PROMPT, "requires_context_of": 1},
        ],
        "checks": checks,
        "cli_exit_code": exit_code,
        "passed": all(checks.values()),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    status = "PASS" if evidence["passed"] else "FAIL"
    print(f"[live-pty-multiturn] {status}: {checks} -> {out_path}")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
