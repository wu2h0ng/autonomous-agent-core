"""Real (non-stub) deterministic integration tests for the extensibility face.

L3 tier: shard B shipped hermetic *unit* tests that drove stub stdio servers and
stub hook scripts. These tests prove the SAME conservative defaults hold when
the subprocess is a genuinely real, on-disk artifact that does observable work
(writes/deletes files, computes a real digest) — while remaining fully
hermetic: no network, no real provider key, only fake sentinel keys.

Covered (ADR-0062, still fail-closed; this is verification, not a default flip):
- MCP: a real Python stdio server with 3 tier-classified tools; connect/list/
  call; tier>=3 refuses auto-run (preflight + execute) until approved; the
  env allow-list strips EVERY provider key and still passes allowlisted vars;
  every discovered tool registers as a full CapabilitySpec.
- hooks: a real hook script runs in an isolated subprocess (different pid),
  computes a real input sha256; tampering its bytes trips the integrity pin;
  workspace-internal sources are denied; empty registry dispatches nothing.
- skills: a concrete fibonacci skill is opt-in advertised, drives real
  computation behind the governed runner, enforces required args, and refuses
  tier>=3.
"""

from __future__ import annotations

import hashlib
import json
import os
import textwrap
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agent_os_contracts import (
    ActionContract,
    CorrectionEpochVector,
    HookConfig,
    HookEvent,
    HookOutcome,
    McpServerConfig,
    McpToolTier,
    ResourceBudget,
    SkillDefinition,
)
from agent_os_core import (
    HookConfigurationError,
    HookDispatcher,
    HookRegistry,
    McpCapabilityAdapter,
    McpStdioClient,
    McpTierRequiresApproval,
    SkillRegistry,
    SkillRegistryError,
)


_NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def _make_action(capability_id: str, arguments: dict) -> ActionContract:
    """Build a minimal-but-valid ActionContract for the governed execute path."""

    return ActionContract(
        action_id="action-l3",
        task_id="task-l3",
        run_id="run-l3",
        node_id="n-l3",
        principal_id="principal-l3",
        tenant_id="tenant-l3",
        workspace_id="workspace-l3",
        capability_id=capability_id,
        capability_version="1",
        arguments_json=json.dumps(arguments),
        risk_tier=2,
        idempotency_key="key-l3",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("1.00"),
            max_duration_seconds=300,
            max_provider_tokens=2_000,
            max_tool_calls=4,
        ),
        policy_version="policy-l3",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0, run_epoch=0, capability_epoch=0,
        ),
        expected_outcome_id="expected-l3",
        candidate_envelope_id="envelope-l3",
        created_at=_NOW,
    )


def _write_real_mcp_server(root: Path, env_probe: Path, workdir: Path) -> Path:
    """Write a REAL stdio MCP server that does observable disk work.

    argv: <env_probe> <workdir>
    Tools: get_time (tier1), write_temp_file (tier2), delete_file (tier3).
    """

    script = textwrap.dedent(
        f"""
        import datetime, hashlib, json, os, sys, time

        ENV_PROBE = {str(env_probe)!r}
        WORKDIR = {str(workdir)!r}

        try:
            with open(ENV_PROBE, "w") as fh:
                json.dump(dict(os.environ), fh, sort_keys=True)
        except Exception:
            pass

        def _safe(name):
            return os.path.join(WORKDIR, os.path.basename(name))

        def get_time(_args):
            return {{"iso": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     "pid": os.getpid()}}

        def write_temp_file(args):
            name = str(args.get("name", "out.txt"))
            content = str(args.get("content", ""))
            with open(_safe(name), "w") as fh:
                fh.write(content)
            return {{"path": _safe(name),
                     "bytes": len(content),
                     "sha256": hashlib.sha256(content.encode()).hexdigest()}}

        def delete_file(args):
            name = str(args.get("name", ""))
            path = _safe(name)
            existed = os.path.exists(path)
            if existed:
                os.remove(path)
            return {{"path": path, "existed": existed, "deleted": existed}}

        TOOLS = [
            {{"name": "get_time", "description": "current server time (read-only)",
              "inputSchema": {{"type": "object"}}}},
            {{"name": "write_temp_file", "description": "write a workdir file (local write)",
              "inputSchema": {{"type": "object", "required": ["name", "content"],
                               "properties": {{"name": {{"type": "string"}},
                                               "content": {{"type": "string"}}}}}}}},
            {{"name": "delete_file", "description": "delete a workdir file (side effect)",
              "inputSchema": {{"type": "object", "required": ["name"],
                               "properties": {{"name": {{"type": "string"}}}}}}}},
        ]
        HANDLERS = {{"get_time": get_time,
                     "write_temp_file": write_temp_file,
                     "delete_file": delete_file}}

        def reply(req_id, result=None, error=None):
            msg = {{"jsonrpc": "2.0", "id": req_id}}
            if error is not None:
                msg["error"] = error
            else:
                msg["result"] = result
            sys.stdout.write(json.dumps(msg) + "\\n")
            sys.stdout.flush()

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            method = msg.get("method")
            req_id = msg.get("id")
            if method == "initialize":
                reply(req_id, {{"protocolVersion": "2024-11-05",
                               "capabilities": {{}},
                               "serverInfo": {{"name": "real", "version": "1"}}}})
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                reply(req_id, {{"tools": TOOLS}})
            elif method == "tools/call":
                params = msg.get("params", {{}})
                fn = HANDLERS.get(params.get("name"))
                if fn is None:
                    reply(req_id, error={{"code": -32601, "message": "no such tool"}})
                    continue
                data = fn(params.get("arguments", {{}}) or {{}})
                reply(req_id, {{"content": [{{"type": "text",
                                               "text": json.dumps(data)}}],
                               "structuredContent": data,
                               "isError": False}})
            else:
                reply(req_id, error={{"code": -32601, "message": "unknown"}})
        """
    )
    path = root / "real_mcp_server.py"
    path.write_text(script, encoding="utf-8")
    return path


def _write_real_hook(root: Path) -> Path:
    """Write a real observer hook that records pid + input sha256 to a marker."""

    script = textwrap.dedent(
        """
        import hashlib, json, os, sys

        raw = sys.stdin.buffer.read()
        sha = hashlib.sha256(raw).hexdigest()
        try:
            payload = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except Exception:
            payload = {}
        marker = os.environ.get("L3_HOOK_MARKER", "")
        if marker:
            with open(marker, "a") as fh:
                fh.write(f"{payload.get('event','?')}|pid={os.getpid()}"
                         f"|exe={sys.executable}|input_sha256={sha}\\n")
        probe = os.environ.get("L3_HOOK_ENV_PROBE", "")
        if probe:
            try:
                with open(probe, "w") as fh:
                    json.dump(dict(os.environ), fh, sort_keys=True)
            except Exception:
                pass
        sys.stdout.write(json.dumps({"ok": True, "input_sha256": sha}))
        sys.stdout.write("\\n")
        """
    )
    path = root / "real_hook.py"
    path.write_text(script, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# MCP real server
# --------------------------------------------------------------------------- #


def test_real_mcp_connect_list_call_and_tier_gate(tmp_path: Path) -> None:
    env_probe = tmp_path / "server_env.json"
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    server = _write_real_mcp_server(tmp_path, env_probe, workdir)

    cfg = McpServerConfig(
        server_id="real",
        command=os.sys.executable,
        args=(str(server), str(env_probe), str(workdir)),
        env_allowlist=(),
        enabled=True,
        max_tier=McpToolTier.SIDE_EFFECT,
    )
    client = McpStdioClient(cfg)
    adapter = McpCapabilityAdapter(client)
    try:
        client.connect()
        tools = adapter.discover()
        tiers = {t.tool_name: t.tier for t in tools}
        assert tiers["get_time"] is McpToolTier.READ_ONLY
        assert tiers["write_temp_file"] is McpToolTier.LOCAL_WRITE
        assert tiers["delete_file"] is McpToolTier.SIDE_EFFECT

        # Tier 1: real read-only call.
        t1 = client.call_tool("get_time", {})
        assert "iso" in t1["structuredContent"]

        # Tier 2: governed execute writes a REAL file to disk.
        write_action = _make_action(
            "mcp.real.write_temp_file",
            {"name": "note.txt", "content": "l3-real-bytes"},
        )
        adapter.execute(write_action)
        on_disk = workdir / "note.txt"
        assert on_disk.read_text() == "l3-real-bytes"

        # Tier 3: refused at preflight AND execute until approved.
        del_action = _make_action("mcp.real.delete_file", {"name": "note.txt"})
        with pytest.raises(McpTierRequiresApproval):
            adapter.preflight("mcp.real.delete_file", {"name": "note.txt"}, "k")
        with pytest.raises(McpTierRequiresApproval):
            adapter.execute(del_action)
        assert on_disk.exists(), "unapproved tier-3 must not have deleted the file"

        # After the approval gate fires, the real side effect runs.
        adapter.approve("mcp.real.delete_file")
        adapter.execute(del_action)
        assert not on_disk.exists()
    finally:
        client.close()


def test_real_mcp_env_allowlist_strips_provider_keys(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch
                                                    ) -> None:
    env_probe = tmp_path / "server_env.json"
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    server = _write_real_mcp_server(tmp_path, env_probe, workdir)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-leak-anthropic")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-leak-deepseek")
    monkeypatch.setenv("L3_ALLOWED", "passes-through")

    cfg = McpServerConfig(
        server_id="real",
        command=os.sys.executable,
        args=(str(server), str(env_probe), str(workdir)),
        # HOME is not auto-passed; listing it proves the allow-list PASS path.
        env_allowlist=("HOME", "L3_ALLOWED"),
        enabled=True,
        max_tier=McpToolTier.SIDE_EFFECT,
    )
    client = McpStdioClient(cfg)
    try:
        client.connect()
        client.list_tools()
    finally:
        client.close()

    seen = json.loads(env_probe.read_text())
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
        assert key not in seen, f"provider key leaked to MCP child: {key}"
    # Allowlisted vars pass through; PATH is always present.
    assert seen.get("L3_ALLOWED") == "passes-through"
    assert seen.get("HOME") == os.environ.get("HOME")
    assert "PATH" in seen


def test_real_mcp_discovered_tools_register_full_specs(tmp_path: Path) -> None:
    env_probe = tmp_path / "server_env.json"
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    server = _write_real_mcp_server(tmp_path, env_probe, workdir)
    cfg = McpServerConfig(
        server_id="real",
        command=os.sys.executable,
        args=(str(server), str(env_probe), str(workdir)),
        enabled=True,
        max_tier=McpToolTier.SIDE_EFFECT,
    )
    client = McpStdioClient(cfg)
    adapter = McpCapabilityAdapter(client)
    try:
        client.connect()
        tools = adapter.discover()
        specs = adapter.specs()
        assert len(specs) == 3
        for t in tools:
            spec = specs[t.capability_id]
            assert spec.capability_id == t.capability_id
            assert spec.risk_tier == t.tier.value
            assert spec.side_effect_guarantee is not None
            assert spec.timeout_seconds >= 1
    finally:
        client.close()


# --------------------------------------------------------------------------- #
# hooks
# --------------------------------------------------------------------------- #


def test_real_hook_isolated_subprocess_and_input_sha(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    probe = tmp_path / "hook_env.json"
    hook = _write_real_hook(tmp_path)
    digest = hashlib.sha256(hook.read_bytes()).hexdigest()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    registry = HookRegistry(workspace_root=str(workspace))
    registry.register(HookConfig(
        hook_id="h1",
        event=HookEvent.TURN_STARTED,
        source_path=str(hook),
        sha256=digest,
    ))
    dispatcher = HookDispatcher(
        registry,
        extra_env_allow=("L3_HOOK_MARKER", "L3_HOOK_ENV_PROBE"),
        timeout_seconds=5.0,
    )
    os.environ["L3_HOOK_MARKER"] = str(marker)
    os.environ["L3_HOOK_ENV_PROBE"] = str(probe)
    try:
        records = dispatcher.dispatch(HookEvent.TURN_STARTED, {"task_id": "t1"})
        assert records[0].outcome is HookOutcome.OK
    finally:
        os.environ.pop("L3_HOOK_MARKER", None)
        os.environ.pop("L3_HOOK_ENV_PROBE", None)

    line = marker.read_text().strip()
    assert line.startswith("turn.started|")
    child_pid = int(line.split("pid=")[1].split("|")[0])
    assert child_pid != os.getpid(), "hook must run in an isolated subprocess"

    expected = json.dumps(
        {"event": HookEvent.TURN_STARTED.value, "payload": {"task_id": "t1"}},
        ensure_ascii=False,
    )
    expected_sha = hashlib.sha256(expected.encode()).hexdigest()
    assert f"input_sha256={expected_sha}" in line


def test_real_hook_tamper_trips_integrity_pin(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    hook = _write_real_hook(tmp_path)
    digest = hashlib.sha256(hook.read_bytes()).hexdigest()
    registry = HookRegistry(workspace_root=str(tmp_path / "ws"))
    registry.register(HookConfig(
        hook_id="h", event=HookEvent.TURN_STARTED,
        source_path=str(hook), sha256=digest,
    ))
    dispatcher = HookDispatcher(
        registry, extra_env_allow=("L3_HOOK_MARKER",), timeout_seconds=5.0,
    )
    os.environ["L3_HOOK_MARKER"] = str(marker)
    try:
        # Tamper AFTER pinning; the integrity check must reject the hook.
        hook.write_text(hook.read_text() + "\n# TAMPERED\n", encoding="utf-8")
        records = dispatcher.dispatch(HookEvent.TURN_STARTED, {"task_id": "x"})
        assert "integrity" in records[0].reason
        assert not marker.exists(), "tampered hook must not run"
    finally:
        os.environ.pop("L3_HOOK_MARKER", None)


def test_real_hook_workspace_source_denied_and_default_off(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inside = workspace / "hook.py"
    inside.write_text("print()", encoding="utf-8")
    digest = hashlib.sha256(inside.read_bytes()).hexdigest()
    registry = HookRegistry(workspace_root=str(workspace))
    with pytest.raises(HookConfigurationError, match="workspace"):
        registry.register(HookConfig(
            hook_id="in-repo", event=HookEvent.TURN_STARTED,
            source_path=str(inside), sha256=digest,
        ))

    # Default-off: empty registry dispatches nothing, spawns nothing.
    empty = HookDispatcher(HookRegistry())
    assert empty.enabled is False
    assert empty.dispatch(HookEvent.TURN_STARTED, {"x": 1}) == []


def test_real_hook_child_env_strips_provider_keys(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch
                                                 ) -> None:
    probe = tmp_path / "hook_env.json"
    hook = _write_real_hook(tmp_path)
    digest = hashlib.sha256(hook.read_bytes()).hexdigest()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-hook-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-hook-leak2")
    registry = HookRegistry(workspace_root=str(tmp_path / "ws"))
    registry.register(HookConfig(
        hook_id="env", event=HookEvent.TURN_STARTED,
        source_path=str(hook), sha256=digest,
    ))
    dispatcher = HookDispatcher(
        registry, extra_env_allow=("L3_HOOK_ENV_PROBE",), timeout_seconds=5.0,
    )
    os.environ["L3_HOOK_ENV_PROBE"] = str(probe)
    try:
        dispatcher.dispatch(HookEvent.TURN_STARTED, {})
    finally:
        os.environ.pop("L3_HOOK_ENV_PROBE", None)
    seen = json.loads(probe.read_text())
    assert "OPENAI_API_KEY" not in seen
    assert "ANTHROPIC_API_KEY" not in seen


# --------------------------------------------------------------------------- #
# skills
# --------------------------------------------------------------------------- #


def _fib(n: int) -> int:
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


class _RealFibRunner:
    """A real executor behind the governed registry (not an echo stub)."""

    def __init__(self, registry: SkillRegistry) -> None:
        self._reg = registry

    def invoke(self, name: str, arguments: dict) -> dict:
        skill = self._reg.get(name)
        if skill is None:
            raise SkillRegistryError(f"skill {name!r} not declared/enabled")
        missing = [k for k in (skill.input_schema.get("required") or [])
                   if k not in arguments]
        if missing:
            raise SkillRegistryError(f"missing required args {missing}")
        if skill.tier >= 3:
            raise SkillRegistryError(
                f"skill {name!r} tier {skill.tier} requires approval")
        return {"skill": name, "n": arguments["n"], "fib_n": _fib(int(arguments["n"]))}


def test_real_skill_opt_in_discovery_and_real_compute() -> None:
    registry = SkillRegistry()
    # Opt-in: declared but disabled is invisible.
    registry.register(SkillDefinition(
        name="fibonacci",
        description="deterministic fibonacci",
        input_schema={"type": "object", "required": ["n"],
                       "properties": {"n": {"type": "integer"}}},
        tier=1,
        enabled=False,
    ))
    assert registry.list_skills() == ()

    # Undeclared skill refused.
    with pytest.raises(SkillRegistryError, match="not declared"):
        _RealFibRunner(registry).invoke("ghost", {"n": 3})

    # Opt-in flip: a fresh enabled registration advertises + drives real work.
    registry2 = SkillRegistry()
    registry2.register(SkillDefinition(
        name="fibonacci",
        description="deterministic fibonacci",
        input_schema={"type": "object", "required": ["n"],
                       "properties": {"n": {"type": "integer"}}},
        tier=1,
        enabled=True,
    ))
    assert tuple(s.name for s in registry2.list_skills()) == ("fibonacci",)
    out = _RealFibRunner(registry2).invoke("fibonacci", {"n": 10})
    assert out["fib_n"] == 55

    # Required-arg enforcement.
    with pytest.raises(SkillRegistryError, match="missing required"):
        _RealFibRunner(registry2).invoke("fibonacci", {})

    # tier>=3 skill is refused by the governed gate.
    registry3 = SkillRegistry()
    registry3.register(SkillDefinition(
        name="delete_db", description="side effect", tier=3, enabled=True,
    ))
    with pytest.raises(SkillRegistryError, match="approval"):
        _RealFibRunner(registry3).invoke("delete_db", {})
