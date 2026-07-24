"""Tiny stdio MCP server used by terminal MCP product tests."""

from __future__ import annotations

import json
import sys


def main() -> None:
    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        req_id = message.get("id")
        if method == "initialize":
            _reply(
                req_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fixture-mcp", "version": "0"},
                },
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _reply(
                req_id,
                {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo a message",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        }
                    ]
                },
            )
        elif method == "tools/call":
            args = (message.get("params") or {}).get("arguments") or {}
            _reply(
                req_id,
                {
                    "content": [
                        {"type": "text", "text": f"echo:{args.get('text', '')}"}
                    ]
                },
            )
        elif req_id is not None:
            _reply(req_id, {})


def _reply(req_id: object, result: object) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
