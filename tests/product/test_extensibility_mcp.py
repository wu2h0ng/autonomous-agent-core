"""Hermetic tests for the MCP local stdio client (shard B / ADR-0062).

Proves the conservative defaults in CODE against a stub stdio MCP server
(a local Python script):
- stdio transport only (no network);
- forced env allow-list: daemon provider keys are NOT inherited;
- tool tier classification (1/2/3) and tier>=3 requires approval;
- discovery -> typed capability specs -> tool call round-trip;
- disabled server is never spawned.

No external network, no real provider key.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

from agent_os_contracts import McpServerConfig, McpToolTier
from agent_os_core import (
    McpCapabilityAdapter,
    McpClientError,
    McpStdioClient,
    McpTierRequiresApproval,
    build_restricted_env,
    classify_tool_tier,
)


def _write_stub_server(root: Path, env_probe_path: Path) -> Path:
    """Write a minimal JSON-RPC-over-stdio MCP stub server."""

    script = textwrap.dedent(
        f"""
        import json, sys, os
        env_probe = {str(env_probe_path)!r}
        # Snapshot the env the server was spawned with.
        try:
            with open(env_probe, "w") as fh:
                json.dump(dict(os.environ), fh)
        except Exception:
            pass

        tools = [
            {{"name": "read_note", "description": "Read a note (read-only)",
              "inputSchema": {{"type": "object", "properties": {{"id": {{"type": "string"}}}}}}}},
            {{"name": "delete_note", "description": "Delete a note by id (side effect)",
              "inputSchema": {{"type": "object", "properties": {{"id": {{"type": "string"}}}}}}}},
        ]

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            method = msg.get("method")
            if method == "initialize":
                reply = {{"jsonrpc": "2.0", "id": msg["id"],
                          "result": {{"protocolVersion": "2024-11-05",
                                     "capabilities": {{}},
                                     "serverInfo": {{"name": "stub", "version": "0"}}}}}}
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                reply = {{"jsonrpc": "2.0", "id": msg["id"], "result": {{"tools": tools}}}}
            elif method == "tools/call":
                name = msg["params"]["name"]
                args = msg["params"].get("arguments", {{}})
                reply = {{"jsonrpc": "2.0", "id": msg["id"],
                          "result": {{"content": [{{"type": "text",
                                                     "text": f"called:{{name}}:{{args}}"}}]}}}}
            else:
                reply = {{"jsonrpc": "2.0", "id": msg.get("id"),
                          "error": {{"code": -32601, "message": "unknown"}}}}
            sys.stdout.write(json.dumps(reply) + "\\n")
            sys.stdout.flush()
        """
    )
    path = root / "stub_mcp_server.py"
    path.write_text(script, encoding="utf-8")
    return path


def test_disabled_server_is_never_spawned() -> None:
    cfg = McpServerConfig(
        server_id="off",
        command="/usr/bin/python3",
        enabled=False,
    )
    with pytest.raises(McpClientError, match="disabled"):
        McpStdioClient(cfg)


def test_build_restricted_env_drops_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak-001")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-leak-002")
    monkeypatch.setenv("ALLOW_PLAIN", "visible")
    env = build_restricted_env(("ALLOW_PLAIN", "OPENAI_API_KEY"))
    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["ALLOW_PLAIN"] == "visible"


def test_classify_tool_tier_is_conservative_and_capped() -> None:
    assert classify_tool_tier(
        tool_name="read_note", description="read", server_ceiling=McpToolTier.READ_ONLY
    ) is McpToolTier.READ_ONLY
    assert classify_tool_tier(
        tool_name="edit_file", description="edit", server_ceiling=McpToolTier.SIDE_EFFECT
    ) is McpToolTier.LOCAL_WRITE
    # "delete" => tier 3, but the server ceiling caps it.
    assert classify_tool_tier(
        tool_name="delete_note", description="delete", server_ceiling=McpToolTier.READ_ONLY
    ) is McpToolTier.READ_ONLY
    # No ceiling => delete lands at tier 3.
    assert classify_tool_tier(
        tool_name="delete_note", description="delete", server_ceiling=McpToolTier.SIDE_EFFECT
    ) is McpToolTier.SIDE_EFFECT


def test_discovery_and_tool_call_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_probe = tmp_path / "server_env.json"
    server = _write_stub_server(tmp_path, env_probe)
    # Plant a sentinel key in the daemon env to prove it is NOT inherited.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-daemon-sentinel-mcp")

    cfg = McpServerConfig(
        server_id="local",
        command=os.sys.executable,
        args=(str(server),),
        env_allowlist=("ALLOW_PLAIN",),
        enabled=True,
        max_tier=McpToolTier.SIDE_EFFECT,
    )
    client = McpStdioClient(cfg)
    adapter = McpCapabilityAdapter(client)
    try:
        client.connect()
        tools = adapter.discover()
        ids = sorted(t.capability_id for t in tools)
        assert ids == [
            "mcp.local.delete_note",
            "mcp.local.read_note",
        ]

        # read_note is tier 1: callable without approval.
        specs = adapter.specs()
        assert specs["mcp.local.read_note"].risk_tier == 1
        assert specs["mcp.local.delete_note"].risk_tier == 3

        # Direct tool call round-trip.
        result = client.call_tool("read_note", {"id": "n1"})
        assert "called:read_note" in result["content"][0]["text"]
    finally:
        client.close()

    # Prove the server subprocess never saw the daemon provider key.
    seen = json.loads(env_probe.read_text())
    assert "OPENAI_API_KEY" not in seen
    assert "ANTHROPIC_API_KEY" not in seen


def test_tier3_requires_approval_before_execution(tmp_path: Path) -> None:
    env_probe = tmp_path / "server_env2.json"
    server = _write_stub_server(tmp_path, env_probe)
    cfg = McpServerConfig(
        server_id="local",
        command=os.sys.executable,
        args=(str(server),),
        enabled=True,
        max_tier=McpToolTier.SIDE_EFFECT,
    )
    client = McpStdioClient(cfg)
    adapter = McpCapabilityAdapter(client)
    try:
        client.connect()
        adapter.discover()
        # tier-3 tool refuses preflight without approval.
        with pytest.raises(McpTierRequiresApproval):
            adapter.preflight("mcp.local.delete_note", {"id": "x"}, "action:k")
        # After approval it passes.
        adapter.approve("mcp.local.delete_note")
        adapter.preflight("mcp.local.delete_note", {"id": "x"}, "action:k")
    finally:
        client.close()


def test_adapter_registers_full_capability_specs(tmp_path: Path) -> None:
    env_probe = tmp_path / "server_env3.json"
    server = _write_stub_server(tmp_path, env_probe)
    cfg = McpServerConfig(
        server_id="local",
        command=os.sys.executable,
        args=(str(server),),
        enabled=True,
        max_tier=McpToolTier.SIDE_EFFECT,
    )
    client = McpStdioClient(cfg)
    adapter = McpCapabilityAdapter(client)
    try:
        client.connect()
        tools = adapter.discover()
        specs = adapter.specs()
        # Every discovered tool has a full CapabilitySpec (Form B lesson).
        for t in tools:
            spec = specs[t.capability_id]
            assert spec.capability_id == t.capability_id
            assert spec.risk_tier == t.tier.value
            assert spec.timeout_seconds >= 1
            assert spec.side_effect_guarantee is not None
    finally:
        client.close()
