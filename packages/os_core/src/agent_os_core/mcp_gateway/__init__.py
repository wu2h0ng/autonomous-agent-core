"""MCP Gateway runtime (workstream C / ADR-0013).

OS Core hosts MCP server/tool registration, lifecycle, risk-ceiling
validation, feature-flag gating, tenant/scope/pause enforcement on
invocation, and an audit trail. Concrete MCP transports (the actual
stdio/SSE bridges to external MCP servers) live OUTSIDE OS Core and are
injected as per-tool handler callables. OS Core never imports an external
MCP SDK or a concrete transport adapter.

This capability is behind ``RuntimeFeatureFlags.mcp_gateway`` (default
``False``). When the flag is off, ``attach`` registers nothing in the runtime
``ToolRegistry`` and ``invoke`` denies every call with ``feature_disabled``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from agent_os_contracts import (
    McpServerRegistration,
    McpToolContract,
    RuntimeFeatureFlags,
)

from ..agent_runtime import AgentRunContext, AgentToolResult, ToolSpec

__all__ = [
    "McpGatewayRegistry",
    "McpInvocationAuditEntry",
    "McpToolDenied",
    "McpToolRouter",
]

_RISK_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}
_PROPOSAL_RISK_LEVELS = frozenset({"R4", "R5"})


class McpToolDenied(Exception):
    """Raised when an MCP tool invocation is denied by gateway policy."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class McpInvocationAuditEntry:
    tool_id: str
    server_id: str
    tenant_id: str
    trace_id: str
    decision: str  # "allowed" | "denied"
    reason: str
    invoked_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class McpGatewayRegistry:
    """Registry of MCP server registrations and their tool contracts.

    OS Core only hosts registration, lifecycle, and policy validation. The
    concrete transport for each tool is injected as a handler callable so
    OS Core never imports an external MCP SDK.
    """

    def __init__(self) -> None:
        self._servers: dict[str, McpServerRegistration] = {}
        self._tools: dict[str, McpToolContract] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register_server(self, registration: McpServerRegistration) -> None:
        if registration.server_id in self._servers:
            raise ValueError(f"server already registered: {registration.server_id}")
        self._servers[registration.server_id] = registration

    def _set_server_state(self, server_id: str, state: str) -> None:
        current = self.server_for(server_id)
        self._servers[server_id] = replace(current, state=state)

    def activate_server(self, server_id: str) -> None:
        self._set_server_state(server_id, "active")

    def suspend_server(self, server_id: str) -> None:
        self._set_server_state(server_id, "suspended")

    def server_for(self, server_id: str) -> McpServerRegistration:
        if server_id not in self._servers:
            raise KeyError(f"server not registered: {server_id}")
        return self._servers[server_id]

    def register_tool(
        self,
        tool: McpToolContract,
        *,
        handler: Callable[..., Any],
    ) -> None:
        if tool.server_id not in self._servers:
            raise ValueError(f"server not registered: {tool.server_id}")
        server = self._servers[tool.server_id]
        if server.state != "active":
            raise ValueError(
                f"cannot register tool on non-active server: {tool.server_id} "
                f"(state={server.state})"
            )
        if _RISK_ORDER[tool.risk_level] > _RISK_ORDER[server.risk_ceiling]:
            raise ValueError(
                f"tool risk level {tool.risk_level} exceeds server risk ceiling "
                f"{server.risk_ceiling}"
            )
        if tool.tool_id in self._tools:
            raise ValueError(f"tool already registered: {tool.tool_id}")
        self._tools[tool.tool_id] = tool
        self._handlers[tool.tool_id] = handler

    def tool_for(self, tool_id: str) -> McpToolContract:
        if tool_id not in self._tools:
            raise KeyError(f"tool not registered: {tool_id}")
        return self._tools[tool_id]

    def handler_for(self, tool_id: str) -> Callable[..., Any]:
        if tool_id not in self._handlers:
            raise KeyError(f"handler not registered: {tool_id}")
        return self._handlers[tool_id]

    def active_tools(self) -> tuple[McpToolContract, ...]:
        active: list[McpToolContract] = []
        for tool in self._tools.values():
            server = self._servers.get(tool.server_id)
            if server is not None and server.state == "active":
                active.append(tool)
        return tuple(active)


class McpToolRouter:
    """Bridge MCP tools into the runtime ``ToolRegistry`` with policy + audit.

    Gated by ``RuntimeFeatureFlags.mcp_gateway`` (default ``False``). When off,
    ``attach`` registers nothing and ``invoke`` denies every call.

    Enforcement layers (on top of ``RuntimePolicyGate`` which owns context
    risk-ceiling + approval gating when invoked via ``AgentRuntime``):

    1. feature flag enabled
    2. tool / server registered
    3. server state == active
    4. tenant match
    5. server allowed scopes intersect run policy scope (fail-closed if empty)
    6. corrigibility pause shell not paused
    7. tool risk level within the run context risk ceiling
    """

    def __init__(
        self,
        registry: McpGatewayRegistry,
        feature_flags: RuntimeFeatureFlags,
        *,
        shell: Any | None = None,
        now: Callable[[], str] | None = None,
        trace_sink: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.registry = registry
        self.feature_flags = feature_flags
        self._shell = shell
        self._now = now or _now_iso
        self._trace_sink = trace_sink
        self._audit: list[McpInvocationAuditEntry] = []

    def _paused(self) -> bool:
        if self._shell is None:
            return False
        return bool(self._shell.paused)

    def _tool_spec_for(self, tool: McpToolContract) -> ToolSpec:
        side_effect = "proposal" if tool.risk_level in _PROPOSAL_RISK_LEVELS else "read"
        return ToolSpec(
            name=tool.tool_id,
            description=tool.description,
            risk_level=tool.risk_level,
            side_effect_class=side_effect,
            allow_when_paused=False,
        )

    def attach(self, tool_registry: Any) -> None:
        """Register all active MCP tools as typed ``ToolSpec`` entries.

        No-op when the ``mcp_gateway`` feature flag is off.
        """
        if not self.feature_flags.mcp_gateway:
            return
        for tool in self.registry.active_tools():
            spec = self._tool_spec_for(tool)
            tool_registry.register_tool(spec, self._make_wrapper(tool.tool_id))

    def _make_wrapper(self, tool_id: str) -> Callable[..., Any]:
        def _wrapped(context: AgentRunContext, **kwargs: Any) -> Any:
            result = self.invoke(tool_id, context, **kwargs)
            if result.status != "ok":
                raise McpToolDenied(
                    result.error_code or "denied",
                    result.error_message or "",
                )
            return result.output

        return _wrapped

    def _audit_record(
        self,
        tool_id: str,
        server_id: str,
        context: AgentRunContext,
        decision: str,
        reason: str,
    ) -> None:
        self._audit.append(
            McpInvocationAuditEntry(
                tool_id=tool_id,
                server_id=server_id,
                tenant_id=context.tenant_id,
                trace_id=context.trace_id,
                decision=decision,
                reason=reason,
                invoked_at=self._now(),
            )
        )

    def _emit(self, step: str, payload: dict[str, Any]) -> None:
        if self._trace_sink is not None:
            self._trace_sink(step, dict(payload))

    def invoke(
        self,
        tool_id: str,
        context: AgentRunContext,
        **kwargs: Any,
    ) -> AgentToolResult:
        call_id = f"mcp:{tool_id}:{context.run_id or context.trace_id or 'unknown'}"
        self._emit("mcp.invocation_started", {"tool_id": tool_id, "trace_id": context.trace_id})

        def _deny(reason: str, server_id: str = "") -> AgentToolResult:
            self._audit_record(tool_id, server_id, context, "denied", reason)
            self._emit(
                "mcp.invocation_denied",
                {"tool_id": tool_id, "reason": reason, "trace_id": context.trace_id},
            )
            return AgentToolResult(
                call_id=call_id,
                tool_name=tool_id,
                status="denied",
                error_code=reason,
                error_message=reason,
                trace_id=context.trace_id,
            )

        if not self.feature_flags.mcp_gateway:
            return _deny("feature_disabled")
        try:
            tool = self.registry.tool_for(tool_id)
        except KeyError:
            return _deny("tool_not_found")
        try:
            server = self.registry.server_for(tool.server_id)
        except KeyError:
            return _deny("server_not_found")
        if server.state != "active":
            return _deny("server_not_active", server.server_id)
        if server.tenant_id != context.tenant_id:
            return _deny("tenant_mismatch", server.server_id)
        if not server.allowed_scopes or not (
            set(server.allowed_scopes) & set(context.policy_scope)
        ):
            return _deny("scope_denied", server.server_id)
        if self._paused():
            return _deny("paused", server.server_id)
        if _RISK_ORDER[tool.risk_level] > _RISK_ORDER[context.risk_ceiling]:
            return _deny("risk_exceeds_context_ceiling", server.server_id)

        handler = self.registry.handler_for(tool_id)
        try:
            output = handler(**kwargs)
        except Exception as exc:  # noqa: BLE001 - transport failures surface as data
            self._audit_record(tool_id, server.server_id, context, "executed_error", "tool_error")
            return AgentToolResult(
                call_id=call_id,
                tool_name=tool_id,
                status="tool_error",
                error_code=exc.__class__.__name__,
                error_message=str(exc),
                trace_id=context.trace_id,
            )
        self._audit_record(tool_id, server.server_id, context, "allowed", "ok")
        self._emit(
            "mcp.invocation_finished",
            {"tool_id": tool_id, "status": "ok", "trace_id": context.trace_id},
        )
        return AgentToolResult(
            call_id=call_id,
            tool_name=tool_id,
            status="ok",
            output=output,
            trace_id=context.trace_id,
        )

    def audit_entries(self) -> tuple[McpInvocationAuditEntry, ...]:
        return tuple(self._audit)
