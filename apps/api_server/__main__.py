from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from agent_os_contracts import (
    ObservationBindingDescriptor,
    PrincipalIdentity,
    canonical_json,
)

from . import _data_agent_situated_startup as situated_startup
from .app import AgentOSApplication
from .server import serve


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agent OS local API and Task Workspace"
    )
    parser.add_argument("--database", default="agent-os.sqlite3")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--data-agent-situated-config")
    parser.add_argument("--observation-admin-config")
    parser.add_argument("--perception-once", action="store_true")
    parser.add_argument("--perception-worker-id", default="agent-os-cli")
    args = parser.parse_args()
    application = (
        situated_startup._build_data_agent_situated_application(
            config_path=args.data_agent_situated_config,
            database=args.database,
            workspace=args.workspace,
        )
        if args.data_agent_situated_config is not None
        else AgentOSApplication(database=args.database, workspace=args.workspace)
    )
    admin_applications: dict[str, AgentOSApplication] = {}
    if args.observation_admin_config is not None:
        config = json.loads(
            Path(args.observation_admin_config).read_text(encoding="utf-8")
        )
        if not isinstance(config, dict):
            raise ValueError("observation admin config must be an object")
        token_env = config.get("token_env")
        if not isinstance(token_env, str) or not token_env:
            raise ValueError("observation admin config requires token_env")
        token = os.environ.get(token_env)
        if not token:
            raise ValueError("observation admin credential is unavailable")
        principal = PrincipalIdentity.model_validate(config.get("principal"))
        descriptors = tuple(
            ObservationBindingDescriptor.model_validate(item)
            for item in config.get("observation_binding_descriptors", [])
        )
        admin_applications[token] = AgentOSApplication(
            database=args.database,
            workspace=args.workspace,
            principal=principal,
            observation_binding_descriptors=descriptors,
        )
    if args.perception_once:
        try:
            receipt = application.run_active_perception_once(
                worker_id=args.perception_worker_id
            )
            print(canonical_json(receipt))
        finally:
            application.store.close()
        return
    if admin_applications:
        serve(
            application,
            args.host,
            args.port,
            admin_applications=admin_applications,
        )
    else:
        serve(application, args.host, args.port)


if __name__ == "__main__":
    main()
