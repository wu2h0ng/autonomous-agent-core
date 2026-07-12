from __future__ import annotations

import argparse

from .app import AgentOSApplication
from .server import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent OS local API and Task Workspace")
    parser.add_argument("--database", default="agent-os.sqlite3")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    serve(AgentOSApplication(database=args.database, workspace=args.workspace), args.host, args.port)


if __name__ == "__main__":
    main()
