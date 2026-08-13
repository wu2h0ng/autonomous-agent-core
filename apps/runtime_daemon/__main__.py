"""agent-os-runtime: foreground Agent OS runtime daemon."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from . import (
    DEFAULT_RUNTIME_DESCRIPTOR,
    RuntimeConfig,
    serve_foreground,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-os-runtime")
    parser.add_argument("--database", default="agent-os.sqlite3")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--descriptor", default=None)
    args = parser.parse_args()
    config = RuntimeConfig(
        database=Path(args.database),
        workspace=Path(args.workspace),
        descriptor_path=Path(
            args.descriptor or DEFAULT_RUNTIME_DESCRIPTOR
        ),
        host=args.host,
        port=args.port,
        environment=dict(os.environ),
    )
    raise SystemExit(serve_foreground(config))


if __name__ == "__main__":
    main()
