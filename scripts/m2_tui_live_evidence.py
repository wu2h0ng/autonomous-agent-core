"""Opt-in M2 live evidence: one real-provider textual TUI session.

Drives AgentTuiApp (the M2 textual TUI) end to end against a live daemon
backed by a real OpenAI-compatible provider (default: the Kimi coding
gateway via KIMI_BASE_URL/KIMI_API_KEY), then writes a durable evidence
JSON under m2-evidence/.

Credentials are read from the environment and never persisted.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> Path:
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
    from apps.cli.surface_client import SurfaceClient
    from apps.cli.tui_app import AgentTuiApp
    from apps.cli.tui_controller import TuiController
    from apps.runtime_daemon.descriptor import load_runtime_descriptor

    root = Path(tempfile.mkdtemp(prefix="m2-live-"))
    (root / "fixture.txt").write_text("M2 live evidence fixture\n", encoding="utf-8")
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
                "boot_id": "boot:m2-live-evidence",
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

    client = SurfaceClient(load_runtime_descriptor(descriptor))
    snapshot = client.open_session("M2 live textual TUI evidence session")
    session_id = snapshot.session.session_id
    task_id = snapshot.session.task_id

    frame_counts = {"chunk": 0, "gap": 0, "stream_end": 0}
    original_stream_frames = client.stream_frames

    def _counting_stream_frames(*args: object, **kwargs: object):
        batch = original_stream_frames(*args, **kwargs)
        for frame in batch.frames:
            frame_counts[frame.kind.value.lower()] += 1
        return batch

    client.stream_frames = _counting_stream_frames  # type: ignore[method-assign]

    controller = TuiController(client=client, session_id=session_id, task_id=task_id)
    tui = AgentTuiApp(controller)

    prompt = (
        "Use the workspace.read tool to read fixture.txt, then reply with "
        "its exact content and nothing else."
    )
    started = datetime.now(timezone.utc)

    async def _drive() -> None:
        from textual.widgets import Input

        async with tui.run_test() as pilot:
            tui.query_one("#prompt", Input).value = prompt
            await pilot.click("#prompt")
            await pilot.press("enter")
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                await pilot.pause(0.5)
                if controller.turns >= 1 and controller.status == "idle":
                    break
            await pilot.press("f2")  # operator-only mode cycle (E2)
            await pilot.pause(0.3)

    asyncio.run(_drive())
    finished = datetime.now(timezone.utc)
    server.shutdown()
    server.server_close()

    events = []
    for event in app.store.read(task_id):
        payload = json.loads(event.payload_json)
        events.append(
            {
                "sequence": event.sequence,
                "event_type": event.event_type.value,
                "payload": payload,
            }
        )

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    ).stdout.strip()

    evidence = {
        "evidence_kind": "m2_tui_live_session",
        "branch": subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=True,
        ).stdout.strip(),
        "commit": head,
        "provider": {
            "endpoint_class": "openai-compatible",
            "base_url": base_url,
            "model": model,
        },
        "session_id": session_id,
        "task_id": task_id,
        "prompt": prompt,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_seconds": round((finished - started).total_seconds(), 3),
        "tui": {
            "transcript": [
                {
                    "role": message.role,
                    "content": message.content,
                    "interrupted": message.interrupted,
                }
                for message in controller.messages
            ],
            "turns": controller.turns,
            "tokens_total": controller.tokens_total,
            "usage_line": controller.usage_line(),
            "status_line": controller.status_line(),
            "final_mode": controller.mode,
        },
        "stream_frames_observed": frame_counts,
        "durable_events": events,
    }

    out_dir = REPO_ROOT / "m2-evidence"
    out_dir.mkdir(exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"tui-live-session-{stamp}.json"
    out_path.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(f"evidence written: {out_path}")
    return out_path


if __name__ == "__main__":
    main()
