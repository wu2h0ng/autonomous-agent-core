"""Minimal MCP stdio client for Mandate terminal (no hard mcp SDK dependency).

Implements JSON-RPC initialize + tools/list + tools/call over stdio.
Config file: `.agent_os/mcp.json`
{
  "servers": {
    "demo": {"command": "python3", "args": ["-m", "some_mcp_server"], "env": {}}
  }
}
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


class McpError(RuntimeError):
    pass


@dataclass
class McpServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class McpTool:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def capability_id(self) -> str:
        return f"mcp.{self.server}.{self.name}"

    def openai_name(self) -> str:
        return self.capability_id.replace(".", "__")


@dataclass
class _ServerSession:
    config: McpServerConfig
    process: subprocess.Popen[str]
    next_id: int = 1
    lock: threading.Lock = field(default_factory=threading.Lock)

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        with self.lock:
            req_id = self.next_id
            self.next_id += 1
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params or {},
            }
            assert self.process.stdin is not None
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
            assert self.process.stdout is not None
            while True:
                line = self.process.stdout.readline()
                if line == "":
                    raise McpError(f"MCP server {self.config.name} closed stdout")
                message = json.loads(line)
                if message.get("id") != req_id:
                    continue
                if "error" in message:
                    raise McpError(str(message["error"]))
                return message.get("result")


def load_mcp_configs(workspace: Path) -> list[McpServerConfig]:
    path = Path(workspace) / ".agent_os" / "mcp.json"
    if not path.is_file():
        env_path = os.environ.get("AGENT_OS_MCP_CONFIG")
        if not env_path:
            return []
        path = Path(env_path)
        if not path.is_file():
            return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    servers = raw.get("servers", {})
    if not isinstance(servers, dict):
        raise McpError("mcp.json servers must be an object")
    configs: list[McpServerConfig] = []
    for name, spec in servers.items():
        if not isinstance(spec, dict):
            continue
        command = str(spec.get("command", "")).strip()
        if not command:
            continue
        args = [str(item) for item in spec.get("args", [])]
        env = {str(k): str(v) for k, v in dict(spec.get("env", {})).items()}
        configs.append(McpServerConfig(name=str(name), command=command, args=args, env=env))
    return configs


class MandateMcpHub:
    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)
        self._sessions: dict[str, _ServerSession] = {}
        self._tools: dict[str, McpTool] = {}

    def start(self) -> list[McpTool]:
        self.close()
        tools: list[McpTool] = []
        for config in load_mcp_configs(self.workspace):
            env = {**os.environ, **config.env}
            process = subprocess.Popen(
                [config.command, *config.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self.workspace),
                env=env,
            )
            session = _ServerSession(config=config, process=process)
            try:
                session.request(
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "agent-os-terminal", "version": "3"},
                    },
                )
                # notifications/initialized is optional for many servers
                try:
                    assert process.stdin is not None
                    process.stdin.write(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "method": "notifications/initialized",
                                "params": {},
                            }
                        )
                        + "\n"
                    )
                    process.stdin.flush()
                except Exception:
                    pass
                listed = session.request("tools/list", {})
                for item in listed.get("tools", []):
                    tool = McpTool(
                        server=config.name,
                        name=str(item.get("name", "")),
                        description=str(item.get("description") or f"MCP tool {item.get('name')}"),
                        input_schema=dict(item.get("inputSchema") or {"type": "object"}),
                    )
                    if not tool.name:
                        continue
                    self._tools[tool.capability_id] = tool
                    tools.append(tool)
                self._sessions[config.name] = session
            except Exception:
                process.kill()
                raise
        return tools

    def tool_ids(self) -> list[str]:
        return sorted(self._tools.keys())

    def tool_openai_specs(self) -> list[dict[str, Any]]:
        specs = []
        for tool in self._tools.values():
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.openai_name(),
                        "description": f"[MCP:{tool.server}] {tool.description}",
                        "parameters": tool.input_schema
                        if tool.input_schema.get("type")
                        else {"type": "object", "additionalProperties": True},
                    },
                }
            )
        return specs

    def call(self, capability_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(capability_id)
        if tool is None:
            raise McpError(f"unknown MCP tool: {capability_id}")
        session = self._sessions.get(tool.server)
        if session is None:
            raise McpError(f"MCP server not running: {tool.server}")
        result = session.request(
            "tools/call",
            {"name": tool.name, "arguments": arguments},
        )
        return result if isinstance(result, dict) else {"result": result}

    def close(self) -> None:
        for session in self._sessions.values():
            try:
                session.process.terminate()
            except Exception:
                pass
        self._sessions.clear()
        self._tools.clear()

    def __enter__(self) -> "MandateMcpHub":
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
