from __future__ import annotations

import argparse

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
    serve(
        application,
        args.host,
        args.port,
    )


if __name__ == "__main__":
    main()
