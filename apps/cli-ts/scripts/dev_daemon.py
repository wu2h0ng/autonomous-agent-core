#!/usr/bin/env python3
"""Hermetic dev daemon for the cli-ts spike.

Composes AgentOSApplication with a scripted streaming DeterministicProvider
(no network, no credentials), serves the authenticated surface protocol on
127.0.0.1, and writes a private descriptor (0600) for the TS client.

Scripted provider sequence (one entry per provider call):
  turn 1: plain streaming text reply
  turn 2: workspace.edit proposal (fixture.txt) -> WAITING_APPROVAL in ASK mode;
          after APPROVE -> "edit applied" text
  turn 3: second workspace.edit proposal -> auto-allowed under
          ACCEPT_IN_WORKSPACE; then "second edit applied" text

Usage: uv run python apps/cli-ts/scripts/dev_daemon.py \
         [--descriptor PATH] [--database PATH] [--workspace PATH]
Pass stable --database/--workspace paths to test daemon-restart resume.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import SURFACE_PROTOCOL_VERSION  # noqa: E402

TURN1_TEXT = (
    "cli-ts spike deterministic reply: the surface protocol carries these "
    "streaming chunks end to end, with begin-turn reservation, per-frame "
    "binding and honest gap semantics. 终端流式验证通过。\n\n"
    "```python\n"
    "# highlighted fixture for the syntax-scope check\n"
    'def greet(name: str) -> str:\n'
    '    return "hello " + name\n'
    "```\n"
)
TURN2_TEXT = "edit applied: fixture.txt updated after human approval"
TURN3_TEXT = "second edit applied: auto-allowed under ACCEPT_IN_WORKSPACE"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--descriptor", default=None)
    parser.add_argument("--database", default=None)
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args()

    from apps.api_server.app import AgentOSApplication
    from apps.api_server.server import build_server
    from agent_os_contracts import ProviderToolProposal
    from agent_os_core.provider import DeterministicProvider

    if args.workspace:
        root = Path(args.workspace)
        root.mkdir(parents=True, exist_ok=True)
    else:
        root = Path(tempfile.mkdtemp(prefix="cli-ts-spike-"))
    fixture = root / "fixture.txt"
    if not fixture.exists():
        fixture.write_text("cli-ts spike fixture\n", encoding="utf-8")
    database = Path(args.database) if args.database else root / "agent-os.sqlite3"
    descriptor_path = Path(
        args.descriptor or (Path.home() / ".agent-os" / "runtime.json")
    )

    app = AgentOSApplication(database=database, workspace=root)
    app.provider = DeterministicProvider(
        scripted=(
            (TURN1_TEXT, ()),
            (
                "",
                (
                    ProviderToolProposal(
                        proposal_id="call-edit-1",
                        capability_id="workspace.edit",
                        arguments_json=json.dumps(
                            {
                                "path": "fixture.txt",
                                "old_string": "cli-ts spike fixture",
                                "new_string": "cli-ts spike fixture (edited)",
                            }
                        ),
                    ),
                ),
            ),
            (TURN2_TEXT, ()),
            (
                "",
                (
                    ProviderToolProposal(
                        proposal_id="call-edit-2",
                        capability_id="workspace.edit",
                        arguments_json=json.dumps(
                            {
                                "path": "fixture.txt",
                                "old_string": "(edited)",
                                "new_string": "(edited twice)",
                            }
                        ),
                    ),
                ),
            ),
            (TURN3_TEXT, ()),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True

    token = f"spike-{os.urandom(16).hex()}"
    server = build_server(app, "127.0.0.1", 0, local_token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    descriptor = {
        "protocol_version": SURFACE_PROTOCOL_VERSION,
        "pid": os.getpid(),
        "boot_id": f"boot:spike-{os.urandom(4).hex()}",
        "host": "127.0.0.1",
        "port": port,
        "bearer_token": token,
        "database_path": str(database),
        "workspace_path": str(root),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    descriptor_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor_path.write_text(json.dumps(descriptor, indent=2), encoding="utf-8")
    os.chmod(descriptor_path, 0o600)

    print(f"dev daemon listening on 127.0.0.1:{port}", flush=True)
    print(f"descriptor: {descriptor_path}", flush=True)
    print(f"database: {database}", flush=True)
    print(f"workspace: {root}", flush=True)
    print("Ctrl-C to stop.", flush=True)
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
