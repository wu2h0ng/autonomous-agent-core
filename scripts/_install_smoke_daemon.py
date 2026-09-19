#!/usr/bin/env python3
"""Hermetic daemon launcher for the Python install smoke.

Run with the INSTALLED tool venv python (so `apps.*` / `agent_os_*` resolve
from the installed distribution under $UV_TOOL_DIR, NOT the source tree):

    <UV_TOOL_DIR>/autonomous-agent-core/bin/python \
        scripts/_install_smoke_daemon.py \
        --descriptor <tmp> --database <tmp> --workspace <tmp>

It composes AgentOSApplication with a scripted DeterministicProvider (no
network, no credentials), flips `provider_configured` so the surface actually
serves a turn, serves the authenticated loopback surface, and writes a private
descriptor. The real `agent-os-runtime` console script refuses a turn with no
provider (HTTP 503 "configure and verify a provider"); this launcher stands in
for a configured operator and is the equivalent of apps/cli-ts/scripts/dev_daemon.py,
but run against the INSTALLED packages rather than the source tree.

Scripted reply (one entry per provider call): the literal stub text the turn
driver asserts on.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path

STUB_TEXT = "install smoke deterministic reply from the installed daemon"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--descriptor", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # No sys.path manipulation on purpose: this process is the tool venv python,
    # so these imports come from the INSTALLED distribution.
    from apps.api_server.app import AgentOSApplication
    from apps.api_server.server import build_server
    from agent_os_contracts import SURFACE_PROTOCOL_VERSION
    from agent_os_core.provider import DeterministicProvider

    root = Path(args.workspace)
    root.mkdir(parents=True, exist_ok=True)
    fixture = root / "fixture.txt"
    if not fixture.exists():
        fixture.write_text("install smoke fixture\n", encoding="utf-8")
    database = Path(args.database)
    descriptor_path = Path(args.descriptor)

    app = AgentOSApplication(database=database, workspace=root)
    app.provider = DeterministicProvider(
        text=STUB_TEXT,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True

    token = f"smoke-{os.urandom(16).hex()}"
    server = build_server(app, "127.0.0.1", 0, local_token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    descriptor = {
        "protocol_version": SURFACE_PROTOCOL_VERSION,
        "pid": os.getpid(),
        "boot_id": f"boot:smoke-{os.urandom(4).hex()}",
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

    print(f"smoke daemon listening on 127.0.0.1:{port}", flush=True)
    print(f"descriptor: {descriptor_path}", flush=True)

    # Hermetic test daemon: no durable cleanup matters (db/workspace/descriptor
    # all live in a temp dir the runner deletes). Exit hard on SIGTERM/SIGINT so
    # the runner's stop step never has to escalate to SIGKILL and never leaves an
    # orphan. server.shutdown() can deadlock when called from a Python signal
    # handler that is already blocked in thread.join(); os._exit cannot.
    def _shutdown(signum: int, frame: object) -> None:
        os._exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    try:
        thread.join()
    except KeyboardInterrupt:
        os._exit(0)


if __name__ == "__main__":
    main()
