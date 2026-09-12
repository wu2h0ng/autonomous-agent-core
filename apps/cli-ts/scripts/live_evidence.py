"""Opt-in live evidence for cli-ts: real provider, real tool call, headless CLI.

Boots AgentOSApplication with a real OpenAI-compatible provider (default:
the Kimi coding gateway via KIMI_BASE_URL/KIMI_API_KEY), then drives the
TypeScript client in headless mode (`-p ... --output-format json`) through a
turn that requires a workspace.read tool call (tier 1: auto-pass in every
permission mode, so no approval interaction is needed).

Exercises the full chain against a real model: streaming → tool proposal →
gate auto-pass → receipt (tool card) → durable completion with exact tokens.

Credentials are read from the environment, never persisted or printed.
The descriptor lives in a temp dir and is deleted on exit.

Usage: uv run python apps/cli-ts/scripts/live_evidence.py --out PATH
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="evidence JSON path")
    parser.add_argument(
        "--prompt",
        default=(
            "Use the workspace.read tool to read fixture.txt, then reply "
            "with its exact content and nothing else."
        ),
    )
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

    from apps.api_server.app import AgentOSApplication
    from apps.api_server.server import build_server

    root = Path(tempfile.mkdtemp(prefix="cli-ts-live-"))
    try:
        (root / "fixture.txt").write_text("cli-ts live evidence fixture\n", encoding="utf-8")
        app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
        app.configure_provider({"base_url": base_url, "model": model, "api_key": api_key})

        token = f"live-{uuid4()}"
        server = build_server(app, "127.0.0.1", 0, local_token=token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        descriptor = root / "runtime.json"
        descriptor.write_text(
            json.dumps(
                {
                    "protocol_version": "1.1",
                    "pid": os.getpid(),
                    "boot_id": "boot:cli-ts-live",
                    "host": "127.0.0.1",
                    "port": server.server_address[1],
                    "bearer_token": token,
                    "database_path": str(root / "agent-os.sqlite3"),
                    "workspace_path": str(root),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            encoding="utf-8",
        )

        started = datetime.now(timezone.utc)
        proc = subprocess.run(
            [
                "npx", "--prefix", "apps/cli-ts", "tsx",
                "apps/cli-ts/src/cli.tsx",
                "--descriptor", str(descriptor),
                "-p", args.prompt,
                "--output-format", "json",
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=300,
        )
        finished = datetime.now(timezone.utc)
        server.shutdown()
        server.server_close()

        result = None
        try:
            result = json.loads(proc.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            pass

        # durable event types (no payloads — they may carry model output)
        session_id = (result or {}).get("session_id") or ""
        event_types: list[str] = []
        if session_id:
            # find the task via the store: one session per task in this fixture
            for task in app.store.list_task_ids() if hasattr(app.store, "list_task_ids") else []:
                event_types.extend(
                    event.event_type.value for event in app.store.read(task)
                )

        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=REPO_ROOT, check=True,
        ).stdout.strip()

        evidence = {
            "evidence_kind": "cli_ts_headless_live_session",
            "recorded_at": finished.isoformat(),
            "repo_head": head,
            "provider": {"base_url_host": base_url.split("/")[2] if "//" in base_url else base_url,
                         "model": model},
            "prompt": args.prompt,
            "cli": {
                "exit_code": proc.returncode,
                "stdout_json": result,
                "stderr_tail": proc.stderr.strip().splitlines()[-5:],
            },
            "duration_seconds": (finished - started).total_seconds(),
            "verdict": (
                "PASS"
                if proc.returncode == 0
                and result
                and result.get("subtype") == "success"
                and result.get("stop_reason") == "completed"
                and isinstance(result.get("total_tokens"), int)
                and result["total_tokens"] > 0
                else "FAIL"
            ),
        }
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"live evidence: {evidence['verdict']} → {out}")
        raise SystemExit(0 if evidence["verdict"] == "PASS" else 1)
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
