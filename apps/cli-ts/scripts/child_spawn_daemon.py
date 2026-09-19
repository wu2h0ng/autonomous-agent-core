#!/usr/bin/env python3
"""Hermetic dev daemon for the CHILD-ROW-DURING-TURN pty check.

Same shape as `stop_daemon.py` (scripted deterministic provider, no network,
no credentials, ephemeral port, private 0600 descriptor) with child agents
ENABLED and a scripted spawn sequence:

  call 1 (parent): proposes agent.spawn -> an explore child that reads the
                   fixture.  The child runs INLINE on the parent's thread.
  call 2 (child):  proposes workspace.read (the child's first action).
  call 3 (child):  text "child done" -> child finishes.
  call 4 (parent): text "parent done" -> parent finishes.

The permission mode is set to ACCEPT_IN_WORKSPACE via the HTTP API after the
session is opened by the pty driver, so the spawn and the child's read are
auto-approved without an approval-parking window.

Usage: uv run python apps/cli-ts/scripts/child_spawn_daemon.py \
         --descriptor PATH --database PATH --workspace PATH
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "os_core" / "src"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--descriptor", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    from apps.api_server.app import AgentOSApplication
    from apps.api_server.server import build_server
    from agent_os_contracts import ProviderToolProposal
    from agent_os_core import DeterministicProvider

    root = Path(args.workspace)
    root.mkdir(parents=True, exist_ok=True)
    (root / "fixture.txt").write_text("child fixture\n", encoding="utf-8")
    database = Path(args.database)
    descriptor_path = Path(args.descriptor)

    # Enable child agents for this daemon.
    os.environ["AGENT_OS_CHILD_AGENTS"] = "on"

    app = AgentOSApplication(database=database, workspace=root)
    class DelayedProvider(DeterministicProvider):
        """Holds the child's first provider call open for 5s."""
        def complete(self, request):
            if len(self.requests) == 1:  # child's first call (call 2 overall)
                time.sleep(5.0)
            return super().complete(request)

    app.provider = DelayedProvider(
        scripted=(
            # call 1: parent proposes agent.spawn
            (
                "",
                (
                    ProviderToolProposal(
                        proposal_id="call-spawn",
                        capability_id="agent.spawn",
                        arguments_json=json.dumps({
                            "prompt": "read the fixture and report",
                            "description": "read-only recon",
                            "agent_type": "explore",
                        }),
                    ),
                ),
            ),
            # call 2: child proposes workspace.read
            (
                "",
                (
                    ProviderToolProposal(
                        proposal_id="call-read",
                        capability_id="workspace.read",
                        arguments_json=json.dumps({"path": "fixture.txt"}),
                    ),
                ),
            ),
            # call 3: child finishes
            ("child done", ()),
            # call 4: parent finishes
            ("parent done", ()),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True

    token = f"child-{os.urandom(16).hex()}"
    server = build_server(app, "127.0.0.1", 0, local_token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    descriptor = {
        "protocol_version": "1.1",
        "pid": os.getpid(),
        "boot_id": f"boot:child-{os.urandom(4).hex()}",
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

    print(f"child daemon listening on 127.0.0.1:{port}", flush=True)
    print(f"descriptor: {descriptor_path}", flush=True)
    print(f"workspace: {root}", flush=True)
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
