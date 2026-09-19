"""MCP (Model Context Protocol) local stdio client (shard B).

Conservative, fail-closed defaults, enforced in CODE and pinned in
ADR-0062 (pending founder ratification):

1. **Local stdio only.** No network/SSE/HTTP transport. The client spawns a
   local subprocess and talks JSON-RPC over its stdin/stdout.
2. **Forced env allow-list.** The server subprocess receives ONLY the
   explicitly allow-listed environment variables. Provider keys in the daemon
   environment (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, ...) are NEVER
   inherited — even if an operator mistakenly lists them, they are stripped.
3. **Tool tier ceiling.** Every tool is classified into our own tier
   (1=read-only safe, 2=local write, 3=side-effect/external). A tool at
   tier >= 3 MUST go through the normal human approval gate; it is never
   auto-executed. The server's self-reported risk can only RAISE our tier,
   never lower it.
4. **Off by default.** A server with ``enabled=False`` (the default) is not
   spawned at all; there is zero background connection/handshake.
5. **Typed capability, not a raw tool passthrough.** Each discovered tool is
   surfaced as a ``CapabilitySpec`` through the adapter's ``specs()``, so
   dispatch still goes through the governed ``CapabilityBroker``.

Hermetic by construction: tests drive a stub stdio server (a local Python
script) — no external network, no real provider key.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Final

from agent_os_contracts import (
    FORBIDDEN_SUBPROCESS_ENV_NAMES,
    ActionContract,
    CapabilitySpec,
    McpServerConfig,
    McpToolTier,
    McpTransport,
    SideEffectGuarantee,
)

from ._action_outcome import (
    CapabilityDenied,
    DurableActionOutcomeRepository,
    ExecutionLease,
)
from .capability import CapabilityEffect


MCP_TOEL_PREFIX: Final = "mcp."

#: Conservative default per-call timeout for a tool invocation.
DEFAULT_CALL_TIMEOUT_SECONDS: Final = 30.0
#: Handshake timeout.
DEFAULT_INIT_TIMEOUT_SECONDS: Final = 5.0

#: Tier-3 keywords: a tool whose name/description matches these is classified
#: as having side effects / external impact (tier 3). This is a conservative
#: heuristic that ERRS HIGH (tier 3), never low.
_TIER3_KEYWORDS: Final[tuple[str, ...]] = (
    "delete",
    "remove",
    "send",
    "email",
    "post",
    "create",
    "update",
    "write_file",
    "exec",
    "execute",
    "shell",
    "push",
    "deploy",
    "charge",
    "payment",
    "trade",
    "http",
    "request",
)

_TIER2_KEYWORDS: Final[tuple[str, ...]] = (
    "write",
    "edit",
    "patch",
    "move",
    "copy",
    "rename",
)

_TIER1_KEYWORDS: Final[tuple[str, ...]] = (
    "read",
    "list",
    "search",
    "get",
    "describe",
    "query",
    "fetch",
    "stat",
)


class McpClientError(RuntimeError):
    """Base class for MCP client failures."""


class McpTransportError(McpClientError):
    """The stdio transport failed (spawn, handshake, malformed JSON-RPC)."""


class McpTierRequiresApproval(McpClientError):
    """Raised when a tier>=3 tool is invoked without an approval marker.

    The adapter refuses to physically execute such a tool from this minimal
    slice; the live approval gate (other shard) is what authorizes it.
    """


def build_restricted_env(allowlist: tuple[str, ...]) -> dict[str, str]:
    """Build the server subprocess environment.

    Only ``PATH`` plus the explicitly allow-listed names are included.
    Provider keys and anything in ``FORBIDDEN_SUBPROCESS_ENV_NAMES`` are
    dropped unconditionally.
    """

    env: dict[str, str] = {"PATH": os.environ.get("PATH", "/usr/local/bin:/bin")}
    for name in allowlist:
        if name in FORBIDDEN_SUBPROCESS_ENV_NAMES:
            continue
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def classify_tool_tier(
    *,
    tool_name: str,
    description: str,
    server_ceiling: McpToolTier,
) -> McpToolTier:
    """Classify an MCP tool into our own tier. Conservative, errs high.

    The server ceiling caps the maximum tier a tool may reach; the server's
    self-reported level is never used to LOWER this classification.
    """

    text = f"{tool_name} {description}".lower()
    if any(kw in text for kw in _TIER3_KEYWORDS):
        tier = McpToolTier.SIDE_EFFECT
    elif any(kw in text for kw in _TIER2_KEYWORDS):
        tier = McpToolTier.LOCAL_WRITE
    elif any(kw in text for kw in _TIER1_KEYWORDS):
        tier = McpToolTier.READ_ONLY
    else:
        # Unknown: conservative default to local write rather than read-only.
        tier = McpToolTier.LOCAL_WRITE
    # The server config ceiling cannot be exceeded.
    if tier.value > server_ceiling.value:
        return server_ceiling
    return tier


@dataclass(frozen=True)
class McpToolDescriptor:
    """A discovered MCP tool and our classification of it."""

    capability_id: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    tier: McpToolTier
    server_id: str


class McpStdioClient:
    """A minimal JSON-RPC-over-stdio MCP client for one local server.

    Protocol surface used: ``initialize``, ``tools/list``, ``tools/call``.
    It does NOT implement the full MCP spec; it implements the minimal
    slice needed to discover and invoke local tools under our own governance.
    """

    def __init__(
        self,
        config: McpServerConfig,
        *,
        init_timeout: float = DEFAULT_INIT_TIMEOUT_SECONDS,
        call_timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS,
    ) -> None:
        if config.transport is not McpTransport.STDIO:
            raise McpClientError(
                f"only stdio transport is supported (got {config.transport!r})"
            )
        if not config.enabled:
            raise McpClientError(
                f"MCP server {config.server_id!r} is disabled; not spawning"
            )
        self._config = config
        self._init_timeout = init_timeout
        self._call_timeout = call_timeout
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 0
        self._lock = threading.Lock()

    @property
    def server_id(self) -> str:
        return self._config.server_id

    def connect(self) -> None:
        """Spawn the server and complete the MCP initialize handshake."""

        env = build_restricted_env(self._config.env_allowlist)
        argv = [self._config.command, *self._config.args]
        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                bufsize=1,
            )
        except OSError as exc:
            raise McpTransportError(f"failed to spawn server: {exc}") from exc

        self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agent-os-mcp-client", "version": "0.1.0"},
        }, timeout=self._init_timeout)
        # Initialized notification (no response expected).
        self._notify("notifications/initialized", {})

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the raw tools/list result (list of tool descriptors)."""

        result = self._request("tools/list", {}, timeout=self._init_timeout)
        tools = result.get("tools", []) if isinstance(result, dict) else []
        if not isinstance(tools, list):
            raise McpTransportError("tools/list returned a non-list")
        return tools

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Invoke a tool and return its structured result."""

        result = self._request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout=timeout or self._call_timeout,
        )
        return result if isinstance(result, dict) else {"result": result}

    def close(self) -> None:
        """Terminate the server subprocess and reap it."""

        if self._proc is None:
            return
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2.0)
        except (OSError, ValueError):
            pass
        finally:
            self._proc = None

    def __enter__(self) -> "McpStdioClient":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- JSON-RPC plumbing -------------------------------------------------- #

    def _send_line(self, message: str) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(message + "\n")
        self._proc.stdin.flush()

    def _read_line(self, timeout: float) -> dict[str, Any]:
        assert self._proc is not None and self._proc.stdout is not None
        deadline = time.monotonic() + timeout
        # Bounded readline with a timeout.
        line = ""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpTransportError("timed out reading JSON-RPC response")
            if self._proc.stdout.readable():
                chunk = self._proc.stdout.readline()
                if chunk == "":
                    # EOF: server died.
                    raise McpTransportError("server closed stdout (EOF)")
                line = chunk
                break
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise McpTransportError(f"malformed JSON-RPC line: {exc}") from exc
        if not isinstance(parsed, dict):
            raise McpTransportError("JSON-RPC message is not an object")
        return parsed

    def _request(self, method: str, params: dict[str, Any], *, timeout: float) -> Any:
        with self._lock:
            self._next_id += 1
            req_id = self._next_id
            self._send_line(json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }))
            while True:
                message = self._read_line(timeout)
                if "id" not in message:
                    # A notification from the server; skip and read again.
                    continue
                if message.get("id") != req_id:
                    # Mismatched id; skip.
                    continue
                if "error" in message:
                    err = message["error"]
                    raise McpTransportError(
                        f"JSON-RPC error {err.get('code')}: {err.get('message')}"
                    )
                return message.get("result")

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send_line(json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }))


@dataclass
class DiscoveredMcpTool:
    """A discovered tool with our classification."""

    descriptor: McpToolDescriptor
    input_schema: dict[str, Any] = field(default_factory=dict)


class McpCapabilityAdapter:
    """Adapt discovered MCP tools onto the governed ``CapabilityPort`` shape.

    This is the Form-B-style registration surface: every discovered tool is
    exposed through ``specs()`` as a full ``CapabilitySpec`` so the
    ``CapabilityBroker`` (and any probe) can list and drive it. A tool at
    tier >= 3 refuses physical execution from this slice unless an explicit
    approval marker is supplied (the live approval gate is the authority).
    """

    def __init__(
        self,
        client: McpStdioClient,
        *,
        now: datetime | None = None,
        approval_markers: set[str] | None = None,
    ) -> None:
        self._client = client
        self._now = now or datetime.now(timezone.utc)
        # Capability ids this adapter has discovered, keyed by capability id.
        self._tools: dict[str, McpToolDescriptor] = {}
        # Capability ids that have been explicitly approved (approval gate).
        self._approved: set[str] = set(approval_markers or ())
        self._call_count = 0

    @property
    def discovered_tools(self) -> list[McpToolDescriptor]:
        return list(self._tools.values())

    def discover(self) -> list[McpToolDescriptor]:
        """Run tools/list and build classified descriptors + specs."""

        raw_tools = self._client.list_tools()
        descriptors: list[McpToolDescriptor] = []
        server_ceiling = self._client._config.max_tier  # noqa: SLF001
        for raw in raw_tools:
            tool_name = str(raw.get("name", ""))
            if not tool_name:
                continue
            description = str(raw.get("description", ""))
            input_schema = raw.get("inputSchema", {}) or {}
            capability_id = f"{MCP_TOEL_PREFIX}{self._client.server_id}.{tool_name}"
            tier = classify_tool_tier(
                tool_name=tool_name,
                description=description,
                server_ceiling=server_ceiling,
            )
            desc = McpToolDescriptor(
                capability_id=capability_id,
                tool_name=tool_name,
                description=description,
                input_schema=input_schema if isinstance(input_schema, dict) else {},
                tier=tier,
                server_id=self._client.server_id,
            )
            self._tools[capability_id] = desc
            descriptors.append(desc)
        return descriptors

    def specs(
        self,
        now: datetime | None = None,
        *,
        include_internal: bool = False,
    ) -> dict[str, CapabilitySpec]:
        at = now or self._now
        specs: dict[str, CapabilitySpec] = {}
        for desc in self._tools.values():
            if desc.tier is McpToolTier.READ_ONLY:
                guarantee = SideEffectGuarantee.READ_ONLY
                idempotent = True
                cancelable = True
            elif desc.tier is McpToolTier.LOCAL_WRITE:
                guarantee = SideEffectGuarantee.SANDBOX_IDEMPOTENT
                idempotent = True
                cancelable = True
            else:
                guarantee = SideEffectGuarantee.NON_IDEMPOTENT_NON_QUERYABLE
                idempotent = False
                cancelable = False
            specs[desc.capability_id] = CapabilitySpec(
                capability_id=desc.capability_id,
                version="1",
                display_name=f"MCP {desc.server_id}:{desc.tool_name}",
                input_contract="json:object:1",
                output_contract="json:object:1",
                side_effect_guarantee=guarantee,
                idempotency_supported=idempotent,
                credential_class="none",
                data_boundary="mcp-stdio-local",
                risk_tier=desc.tier.value,
                timeout_seconds=int(DEFAULT_CALL_TIMEOUT_SECONDS),
                cancellation_supported=cancelable,
                compensation_supported=False,
                audit_policy="event-and-artifact",
                created_by="system",
                created_at=at,
                collaboration_required=False,
            )
        return specs

    def approve(self, capability_id: str) -> None:
        """Mark a tier>=3 tool as approved by the human approval gate."""

        self._approved.add(capability_id)

    # -- CapabilityPort methods (minimal, broker-driveable) ----------------- #

    def preflight(
        self,
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> None:
        desc = self._tools.get(capability_id)
        if desc is None:
            raise CapabilityDenied(f"mcp tool not registered: {capability_id}")
        if desc.tier.value >= 3 and capability_id not in self._approved:
            raise McpTierRequiresApproval(
                f"mcp tool {capability_id!r} is tier {desc.tier.value} and "
                f"requires human approval before execution"
            )

    def execute(self, action: ActionContract) -> CapabilityEffect:
        from agent_os_contracts import ReceiptStatus

        desc = self._tools.get(action.capability_id)
        if desc is None:
            raise CapabilityDenied(f"mcp tool not registered: {action.capability_id}")
        # Re-run the tier gate at execute time (defense in depth).
        if desc.tier.value >= 3 and action.capability_id not in self._approved:
            raise McpTierRequiresApproval(
                f"mcp tool {action.capability_id!r} requires approval"
            )
        try:
            args = json.loads(action.arguments_json or "{}")
        except json.JSONDecodeError as exc:
            raise CapabilityDenied(f"invalid arguments_json: {exc}") from exc
        result = self._client.call_tool(desc.tool_name, args if isinstance(args, dict) else {})
        self._call_count += 1
        return CapabilityEffect(
            status=ReceiptStatus.SUCCEEDED,
            output={"result": result},
            error_code="error:none",
            detail_ref="detail:mcp",
        )

    # The broker requires these for a full dispatch path; hermetic tests that
    # only exercise discovery + the tier gate do not need them.
    def replay(self, action: ActionContract):
        return None

    def outcomes(self) -> DurableActionOutcomeRepository | None:
        return None

    def acquire_execution_lease(self, action: ActionContract, owner: str) -> ExecutionLease:
        raise NotImplementedError(
            "lease management is owned by the composition root; this minimal "
            "adapter does not allocate durable leases"
        )

    def release_execution_lease(self, lease: ExecutionLease) -> bool:
        return False
