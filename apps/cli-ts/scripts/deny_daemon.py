#!/usr/bin/env python3
"""Hermetic dev daemon for the DENIAL-frame check (privileged-path visibility).

Same shape as `dev_daemon.py` (scripted streaming provider, no network, no
credentials, ephemeral port, private 0600 descriptor) with one difference that
makes it a different daemon rather than a flag: it seeds a durable operator
DENY rule before the session opens, so a scripted turn produces BOTH a policy
refusal and an ordinary tool failure in one transcript.

Scripted provider sequence (one entry per provider call):
  call 1: two tool proposals in ONE message —
            workspace.edit  → refused by the seeded DENY rule (never proposed,
                              never dispatched, no receipt: the verdict IS the
                              whole record of it);
            workspace.read  → allowed, dispatched, and fails normally because
                              the file does not exist.
  call 2: text claiming the work was done. That claim is the point: the card is
          the only thing on screen that contradicts it.

The daemon deliberately has NO default descriptor path: a hermetic evidence
daemon must never be able to write the operator's `~/.agent-os/runtime.json`.

Usage: uv run python apps/cli-ts/scripts/deny_daemon.py \
         --descriptor PATH --database PATH --workspace PATH
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "os_core" / "src"))

RULE_ID = "rule-deploy-freeze"
RULE_REASON = "deploy freeze"
DENIED_CAPABILITY = "workspace.edit"
# The model's answer after both proposals were refused/failed. It is FALSE, and
# it is the reason a refusal has to be visible on the surface rather than only
# in the durable log.
FINAL_TEXT = "done - I updated fixture.txt"
MISSING_PATH = "missing-file.txt"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--descriptor", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--rule-id", default=RULE_ID)
    parser.add_argument("--rule-reason", default=RULE_REASON)
    args = parser.parse_args()

    from apps.api_server.app import AgentOSApplication
    from apps.api_server.server import build_server
    from agent_os_contracts import ProviderToolProposal
    from agent_os_core import (
        DeterministicProvider,
        PermissionDenyRule,
        PermissionRuleKind,
    )

    root = Path(args.workspace)
    root.mkdir(parents=True, exist_ok=True)
    fixture = root / "fixture.txt"
    fixture.write_text("cli-ts spike fixture\n", encoding="utf-8")
    database = Path(args.database)
    descriptor_path = Path(args.descriptor)

    app = AgentOSApplication(database=database, workspace=root)
    app.provider = DeterministicProvider(
        scripted=(
            (
                "",
                (
                    ProviderToolProposal(
                        proposal_id="call-denied-edit",
                        capability_id=DENIED_CAPABILITY,
                        arguments_json=json.dumps(
                            {
                                "path": "fixture.txt",
                                "old_string": "cli-ts spike fixture",
                                "new_string": "cli-ts spike fixture (edited)",
                            }
                        ),
                    ),
                    ProviderToolProposal(
                        proposal_id="call-missing-read",
                        capability_id="workspace.read",
                        arguments_json=json.dumps({"path": MISSING_PATH}),
                    ),
                ),
            ),
            (FINAL_TEXT, ()),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    app.permission_rule_store.save(
        PermissionDenyRule(
            rule_id=args.rule_id,
            kind=PermissionRuleKind.DENY,
            capability_id=DENIED_CAPABILITY,
            tenant_id=app.principal.tenant_id,
            workspace_id=app.principal.workspace_id,
            created_by="operator",
            created_at=datetime.now(timezone.utc),
            reason=args.rule_reason,
        )
    )

    token = f"deny-{os.urandom(16).hex()}"
    # Port 0: an ephemeral port. A fixed port collided between two workstreams.
    server = build_server(app, "127.0.0.1", 0, local_token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    descriptor = {
        "protocol_version": "1.1",
        "pid": os.getpid(),
        "boot_id": f"boot:deny-{os.urandom(4).hex()}",
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

    print(f"deny daemon listening on 127.0.0.1:{port}", flush=True)
    print(f"descriptor: {descriptor_path}", flush=True)
    print(f"workspace: {root}", flush=True)
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
