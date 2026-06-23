from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..corrigibility import ShellView

_DEFAULT_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "cookie",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "secret_token",
        "token",
    }
)
_APPROVAL_REQUIRED_RISK_LEVELS = frozenset({"R4", "R5"})
_NO_APPROVAL_SIDE_EFFECT_CLASSES = frozenset({"", "none", "read", "read_only", "readonly"})

__all__ = [
    "AgentRunContext",
    "AgentRuntime",
    "AgentToolCall",
    "AgentToolResult",
    "AgentTraceWriter",
    "InMemoryCheckpointStore",
    "PolicyDecision",
    "RunStateSnapshot",
    "RuntimePolicyGate",
    "StructuredOutputValidator",
    "ToolRegistry",
    "ToolSpec",
    "TrustedLoopAgentRuntimeAdapter",
]


@dataclass(frozen=True)
class AgentRunContext:
    tenant_id: str
    workspace_id: str
    trace_id: str
    principal_id: str = ""
    principal_role: str = ""
    run_id: str = ""
    policy_scope: frozenset[str] = field(default_factory=frozenset)
    approval_id: str | None = None
    checkpoint_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    required_keys: tuple[str, ...] = ()
    risk_level: str = "R1"
    side_effect_class: str = "none"
    required_permissions: tuple[str, ...] = ()
    requires_evidence: bool = False
    requires_approval: bool = False
    timeout_ms: int | None = None
    allow_when_paused: bool = False


@dataclass(frozen=True)
class AgentToolCall:
    call_id: str
    tool_name: str
    args: Mapping[str, Any] = field(default_factory=dict)
    context_ref: str | None = None


@dataclass(frozen=True)
class AgentToolResult:
    call_id: str
    tool_name: str
    status: str
    output: Any | None = None
    error_code: str | None = None
    error_message: str | None = None
    trace_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    code: str
    reason: str = ""


@dataclass(frozen=True)
class RunStateSnapshot:
    run_id: str
    trace_id: str
    step_id: str
    status: str
    pending_tool_call: AgentToolCall | None = None
    last_result: AgentToolResult | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    last_completed_boundary: str | None = None


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._by_run_id: dict[str, RunStateSnapshot] = {}

    def save(self, snapshot: RunStateSnapshot) -> None:
        self._by_run_id[snapshot.run_id] = snapshot

    def get(self, run_id: str) -> RunStateSnapshot | None:
        return self._by_run_id.get(run_id)


@dataclass(frozen=True)
class _ToolRegistration:
    spec: ToolSpec
    tool: Callable[..., Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, _ToolRegistration] = {}

    def register(self, name: str, tool: Callable[..., Any]) -> None:
        """Backward-compatible registration for the original thin shell API."""
        self.register_tool(ToolSpec(name=name, description=name), tool)

    def register_tool(self, spec: ToolSpec, tool: Callable[..., Any]) -> None:
        if not spec.name:
            raise ValueError("tool name is required")
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = _ToolRegistration(spec=spec, tool=tool)

    def spec_for(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise KeyError(f"tool not registered: {name}")
        return self._tools[name].spec

    def call(self, name: str, **kwargs: Any) -> Any:
        if name not in self._tools:
            raise KeyError(f"tool not registered: {name}")
        return self._tools[name].tool(**kwargs)


class StructuredOutputValidator:
    def require_keys(self, payload: Mapping[str, Any], keys: tuple[str, ...]) -> None:
        missing = [key for key in keys if key not in payload or payload[key] in (None, "")]
        if missing:
            raise ValueError(f"missing required output keys: {', '.join(missing)}")


@dataclass
class AgentTraceWriter:
    events: list[dict[str, Any]] = field(default_factory=list)
    sensitive_keys: frozenset[str] = field(default_factory=lambda: _DEFAULT_SENSITIVE_KEYS)

    def write(self, step: str, payload: dict[str, Any]) -> None:
        self.events.append({"step": step, "payload": self._redact(payload)})

    def _redact(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                if str(key) in self.sensitive_keys:
                    redacted[str(key)] = "[REDACTED]"
                else:
                    redacted[str(key)] = self._redact(item)
            return redacted
        if isinstance(value, tuple):
            return tuple(self._redact(item) for item in value)
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value


class RuntimePolicyGate:
    def __init__(
        self,
        *,
        shell_view: ShellView | None = None,
        supported_risk_levels: frozenset[str] | None = None,
    ) -> None:
        self.shell_view = shell_view
        self.supported_risk_levels = supported_risk_levels or frozenset(
            {"R0", "R1", "R2", "R3", "R4", "R5"}
        )

    def check(self, *, context: AgentRunContext, tool_spec: ToolSpec) -> PolicyDecision:
        missing_context = [
            name
            for name, value in (
                ("tenant_id", context.tenant_id),
                ("workspace_id", context.workspace_id),
                ("principal_id", context.principal_id),
                ("run_id", context.run_id),
                ("trace_id", context.trace_id),
            )
            if not value
        ]
        if missing_context:
            return PolicyDecision(
                allowed=False,
                code="DENY_INVALID_CONTEXT",
                reason=f"missing context: {', '.join(missing_context)}",
            )

        if (
            self.shell_view is not None
            and self.shell_view.paused
            and not tool_spec.allow_when_paused
        ):
            self.shell_view.observe(
                {
                    "event": "agent_runtime_refused_paused",
                    "trace_id": context.trace_id,
                    "run_id": context.run_id,
                    "tool_name": tool_spec.name,
                }
            )
            return PolicyDecision(
                allowed=False,
                code="DENY_PAUSED",
                reason="corrigibility shell is paused",
            )

        if tool_spec.risk_level not in self.supported_risk_levels:
            return PolicyDecision(
                allowed=False,
                code="DENY_UNSUPPORTED_RISK",
                reason=f"unsupported risk level: {tool_spec.risk_level}",
            )

        missing_permissions = set(tool_spec.required_permissions) - set(context.policy_scope)
        if missing_permissions:
            return PolicyDecision(
                allowed=False,
                code="DENY_MISSING_PERMISSION",
                reason=f"missing permissions: {', '.join(sorted(missing_permissions))}",
            )

        requires_runtime_approval = (
            tool_spec.requires_approval
            or tool_spec.risk_level in _APPROVAL_REQUIRED_RISK_LEVELS
            or tool_spec.side_effect_class.lower() not in _NO_APPROVAL_SIDE_EFFECT_CLASSES
        )
        if requires_runtime_approval and not context.approval_id:
            return PolicyDecision(
                allowed=False,
                code="DENY_REQUIRES_APPROVAL",
                reason="tool requires approval_id",
            )

        return PolicyDecision(allowed=True, code="ALLOW")


class AgentRuntime:
    """Self-developed runtime substrate for one policy-gated tool boundary."""

    def __init__(
        self,
        tools: ToolRegistry | None = None,
        *,
        policy_gate: RuntimePolicyGate | None = None,
        trace_writer: AgentTraceWriter | None = None,
        checkpoint_store: InMemoryCheckpointStore | None = None,
        validator: StructuredOutputValidator | None = None,
    ) -> None:
        self.tools = tools or ToolRegistry()
        self.policy_gate = policy_gate or RuntimePolicyGate()
        self.trace_writer = trace_writer or AgentTraceWriter()
        self.checkpoint_store = checkpoint_store
        self.validator = validator or StructuredOutputValidator()

    def run_tool(self, name: str, context: AgentRunContext, **kwargs: Any) -> AgentToolResult:
        """Compatibility wrapper over the governed invocation path."""
        return self.invoke_tool(
            AgentToolCall(
                call_id=f"compat:{name}:{context.run_id or context.trace_id or 'unknown'}",
                tool_name=name,
                args=kwargs,
            ),
            context,
        )

    def invoke_tool(self, call: AgentToolCall, context: AgentRunContext) -> AgentToolResult:
        self.trace_writer.write(
            "agent_runtime.invocation_started",
            {
                "call_id": call.call_id,
                "tool_name": call.tool_name,
                "run_id": context.run_id,
                "trace_id": context.trace_id,
            },
        )

        result = self._invoke_tool(call, context)
        self.trace_writer.write(
            "agent_runtime.invocation_finished",
            {
                "call_id": call.call_id,
                "tool_name": call.tool_name,
                "trace_id": context.trace_id,
                "run_id": context.run_id,
                "status": result.status,
                "error_code": result.error_code,
            },
        )
        self._checkpoint(call, context, result)
        return result

    def _invoke_tool(self, call: AgentToolCall, context: AgentRunContext) -> AgentToolResult:
        unreplayable_inputs = context.metadata.get("nondeterministic_inputs")
        if unreplayable_inputs and not context.metadata.get("replay_capture_id"):
            result = AgentToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status="validation_error",
                error_code="UNREPLAYABLE_INPUT",
                error_message="nondeterministic inputs require a replay_capture_id",
                trace_id=context.trace_id,
                metadata={"unreplayable_inputs": tuple(unreplayable_inputs)},
            )
            self.trace_writer.write(
                "agent_runtime.validation_failed",
                {
                    "call_id": call.call_id,
                    "tool_name": call.tool_name,
                    "error_code": result.error_code,
                },
            )
            return result

        try:
            tool_spec = self.tools.spec_for(call.tool_name)
        except KeyError as exc:
            result = AgentToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status="validation_error",
                error_code="TOOL_NOT_REGISTERED",
                error_message=str(exc),
                trace_id=context.trace_id,
            )
            self.trace_writer.write(
                "agent_runtime.validation_failed",
                {
                    "call_id": call.call_id,
                    "tool_name": call.tool_name,
                    "error_code": result.error_code,
                },
            )
            return result

        policy = self.policy_gate.check(context=context, tool_spec=tool_spec)
        if not policy.allowed:
            result = AgentToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status="denied",
                error_code=policy.code,
                error_message=policy.reason,
                trace_id=context.trace_id,
            )
            self.trace_writer.write(
                "agent_runtime.policy_denied",
                {
                    "call_id": call.call_id,
                    "tool_name": call.tool_name,
                    "error_code": policy.code,
                },
            )
            return result

        self.trace_writer.write(
            "agent_runtime.policy_allowed",
            {"call_id": call.call_id, "tool_name": call.tool_name},
        )

        try:
            self.validator.require_keys(call.args, tool_spec.required_keys)
        except ValueError as exc:
            result = AgentToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status="validation_error",
                error_code="INVALID_TOOL_INPUT",
                error_message=str(exc),
                trace_id=context.trace_id,
            )
            self.trace_writer.write(
                "agent_runtime.validation_failed",
                {
                    "call_id": call.call_id,
                    "tool_name": call.tool_name,
                    "error_code": result.error_code,
                },
            )
            return result

        self.trace_writer.write(
            "agent_runtime.tool_started",
            {"call_id": call.call_id, "tool_name": call.tool_name},
        )
        try:
            output = self.tools.call(call.tool_name, context=context, **dict(call.args))
        except Exception as exc:  # noqa: BLE001 - runtime surfaces tool failures as data
            result = AgentToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status="tool_error",
                error_code=exc.__class__.__name__,
                error_message=str(exc),
                trace_id=context.trace_id,
            )
            self.trace_writer.write(
                "agent_runtime.tool_failed",
                {
                    "call_id": call.call_id,
                    "tool_name": call.tool_name,
                    "error_code": result.error_code,
                },
            )
            return result

        result = AgentToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            status="ok",
            output=output,
            trace_id=context.trace_id,
        )
        self.trace_writer.write(
            "agent_runtime.tool_succeeded",
            {"call_id": call.call_id, "tool_name": call.tool_name},
        )
        return result

    def _checkpoint(
        self,
        call: AgentToolCall,
        context: AgentRunContext,
        result: AgentToolResult,
    ) -> None:
        if self.checkpoint_store is None or not context.run_id:
            return
        self.checkpoint_store.save(
            RunStateSnapshot(
                run_id=context.run_id,
                trace_id=context.trace_id,
                step_id=call.call_id,
                status=result.status,
                pending_tool_call=None,
                last_result=result,
                metadata={"tool_name": call.tool_name},
                last_completed_boundary="agent_runtime.invoke_tool",
            )
        )


class TrustedLoopAgentRuntimeAdapter:
    """Thin adapter proving TrustedLoop execution can sit behind the runtime envelope."""

    TOOL_NAME = "trusted_loop.evaluate"

    def __init__(
        self,
        trusted_loop: Any,
        *,
        shell_view: ShellView | None = None,
        trace_writer: AgentTraceWriter | None = None,
    ) -> None:
        self.trusted_loop = trusted_loop
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name=self.TOOL_NAME,
                description="Evaluate a question through TrustedLoopRuntime.",
                required_keys=("question", "parameters"),
                required_permissions=("trusted_loop:evaluate",),
            ),
            self._evaluate_tool,
        )
        self.runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(shell_view=shell_view),
            trace_writer=trace_writer,
        )

    def evaluate(
        self,
        *,
        context: AgentRunContext,
        question: str,
        parameters: dict[str, object],
    ) -> AgentToolResult:
        return self.runtime.invoke_tool(
            AgentToolCall(
                call_id=f"{self.TOOL_NAME}:{context.run_id or context.trace_id}",
                tool_name=self.TOOL_NAME,
                args={"question": question, "parameters": parameters},
            ),
            context,
        )

    def _evaluate_tool(
        self,
        *,
        question: str,
        parameters: dict[str, object],
        context: AgentRunContext,
    ) -> Any:
        return self.trusted_loop.evaluate(question, parameters)
