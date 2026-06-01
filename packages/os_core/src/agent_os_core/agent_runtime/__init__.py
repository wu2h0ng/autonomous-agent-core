from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentRunContext:
    tenant_id: str
    workspace_id: str
    trace_id: str


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, tool: Callable[..., Any]) -> None:
        if not name:
            raise ValueError("tool name is required")
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = tool

    def call(self, name: str, **kwargs: Any) -> Any:
        if name not in self._tools:
            raise KeyError(f"tool not registered: {name}")
        return self._tools[name](**kwargs)


class StructuredOutputValidator:
    def require_keys(self, payload: dict[str, Any], keys: tuple[str, ...]) -> None:
        missing = [key for key in keys if key not in payload or payload[key] in (None, "")]
        if missing:
            raise ValueError(f"missing required output keys: {', '.join(missing)}")


@dataclass
class AgentTraceWriter:
    events: list[dict[str, Any]] = field(default_factory=list)

    def write(self, step: str, payload: dict[str, Any]) -> None:
        self.events.append({"step": step, "payload": payload})


class AgentRuntime:
    """Minimal self-developed runtime shell for deterministic tool execution."""

    def __init__(self, tools: ToolRegistry | None = None) -> None:
        self.tools = tools or ToolRegistry()

    def run_tool(self, name: str, context: AgentRunContext, **kwargs: Any) -> Any:
        return self.tools.call(name, context=context, **kwargs)
