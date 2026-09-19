#!/usr/bin/env python3
"""Hermetic dev daemon for the RESUME pty check.

Same shape as `stop_daemon.py` (scripted deterministic provider, no network, no
credentials, ephemeral port, private 0600 descriptor, no default descriptor
path) with the scripted sequence a resume needs to be observable:

  call 1: held for --hold-ms, then proposes a tier-1 workspace.read. The hold
          gives the operator a real mid-turn window to press the stop key, and
          the proposal is what the stop suppresses (it must never be
          dispatched).
  call 2: text. It MUST be reached once the session has been resumed: that is
          the end-to-end proof that the terminal got out of the dead end and a
          new turn really runs, not merely that a status string changed.

Usage: uv run python apps/cli-ts/scripts/resume_daemon.py \
         --descriptor PATH --database PATH --workspace PATH [--hold-ms N]
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

RESUMED_TEXT = "the resumed turn ran"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--descriptor", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--hold-ms", type=int, default=8000)
    args = parser.parse_args()

    from apps.api_server.app import AgentOSApplication
    from apps.api_server.server import build_server
    from agent_os_contracts import ProviderToolProposal
    from agent_os_core import DeterministicProvider
    from agent_os_core.provider import ProviderRequest, ProviderResponse

    class HoldingProvider(DeterministicProvider):
        """Holds the first provider call open so a mid-turn stop is reachable."""

        def __init__(self, hold_ms: int, **kwargs: object) -> None:
            super().__init__(**kwargs)  # type: ignore[arg-type]
            self._hold_ms = hold_ms
            self.calls = 0

        def complete(self, request: ProviderRequest) -> ProviderResponse:
            self.calls += 1
            if self.calls == 1 and self._hold_ms > 0:
                time.sleep(self._hold_ms / 1000)
            return super().complete(request)

    root = Path(args.workspace)
    root.mkdir(parents=True, exist_ok=True)
    (root / "fixture.txt").write_text("cli-ts spike fixture\n", encoding="utf-8")
    database = Path(args.database)
    descriptor_path = Path(args.descriptor)

    app = AgentOSApplication(database=database, workspace=root)
    app.provider = HoldingProvider(
        args.hold_ms,
        scripted=(
            (
                "",
                (
                    ProviderToolProposal(
                        proposal_id="call-read-1",
                        capability_id="workspace.read",
                        arguments_json=json.dumps({"path": "fixture.txt"}),
                    ),
                ),
            ),
            (RESUMED_TEXT, ()),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True

    token = f"resume-{os.urandom(16).hex()}"
    # Port 0: an ephemeral port. A fixed port collided between two workstreams.
    server = build_server(app, "127.0.0.1", 0, local_token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    descriptor = {
        "protocol_version": "1.1",
        "pid": os.getpid(),
        "boot_id": f"boot:resume-{os.urandom(4).hex()}",
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

    print(f"resume daemon listening on 127.0.0.1:{port}", flush=True)
    print(f"descriptor: {descriptor_path}", flush=True)
    print(f"workspace: {root}", flush=True)
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
