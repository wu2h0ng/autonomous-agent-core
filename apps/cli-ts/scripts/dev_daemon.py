#!/usr/bin/env python3
"""Hermetic dev daemon for the cli-ts spike.

Composes AgentOSApplication on a temp workspace with a scripted streaming
DeterministicProvider (no network, no credentials), serves the authenticated
surface protocol on 127.0.0.1, and writes a private descriptor (0600) so the
TS client can attach via --descriptor. Ctrl-C to stop.

Usage: uv run python apps/cli-ts/scripts/dev_daemon.py [descriptor-path]
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "os_core" / "src"))

SCRIPT_TEXT = (
    "cli-ts spike deterministic reply: the surface protocol carries these "
    "streaming chunks end to end, with begin-turn reservation, per-frame "
    "binding and honest gap semantics. 终端流式验证通过。"
)


def main() -> None:
    from apps.api_server.app import AgentOSApplication
    from apps.api_server.server import build_server
    from packages.os_core.src.agent_os_core.provider import DeterministicProvider

    descriptor_path = Path(
        sys.argv[1] if len(sys.argv) > 1 else Path.home() / ".agent-os" / "runtime.json"
    )

    root = Path(tempfile.mkdtemp(prefix="cli-ts-spike-"))
    (root / "fixture.txt").write_text("cli-ts spike fixture\n", encoding="utf-8")
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=((SCRIPT_TEXT, ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True

    token = f"spike-{os.urandom(16).hex()}"
    server = build_server(app, "127.0.0.1", 0, local_token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    descriptor = {
        "protocol_version": "1.1",
        "pid": os.getpid(),
        "boot_id": f"boot:spike-{os.urandom(4).hex()}",
        "host": "127.0.0.1",
        "port": port,
        "bearer_token": token,
        "database_path": str(root / "agent-os.sqlite3"),
        "workspace_path": str(root),
        "created_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    }
    descriptor_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor_path.write_text(json.dumps(descriptor, indent=2), encoding="utf-8")
    os.chmod(descriptor_path, 0o600)

    print(f"dev daemon listening on 127.0.0.1:{port}", flush=True)
    print(f"descriptor: {descriptor_path}", flush=True)
    print(f"workspace: {root}", flush=True)
    print("Ctrl-C to stop.", flush=True)
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
