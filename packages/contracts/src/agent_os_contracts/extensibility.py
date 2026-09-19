"""Typed extensibility contracts: typed hooks, MCP, and skills (shard B).

This module freezes the *shape* of the three extensibility surfaces the
terminal agent CLI grows on top of the governed capability spine. It is a
pure contract layer: it carries no runtime behavior, no authority, and no
execution path. The conservative, fail-closed defaults these types encode
are enforced in ``agent_os_core`` (runtime) and pinned in ADR-0062 (pending
founder ratification).

Design sources (design-only GC cards, NOT implementation authority):
- ``docs/product/GC-TYPED-HOOKS-2026-09-18.md``
- ``docs/product/GC-MCP-FORM-AND-BOUNDARY-2026-09-18.md``
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field

from .common import ContractModel, NonEmptyStr


# --------------------------------------------------------------------------- #
# Typed hooks
# --------------------------------------------------------------------------- #


class HookEvent(str, Enum):
    """The fixed v1 hook seam vocabulary.

    Additive only: new events are an additive v1 extension; unknown event
    keys are rejected at load time (fail-closed), never silently ignored.
    """

    TURN_STARTED = "turn.started"
    TURN_ENDED = "turn.ended"
    TOOL_PRE = "tool.pre"
    TOOL_POST = "tool.post"
    APPROVAL_REQUESTED = "approval.requested"
    PROVIDER_PRE = "provider.pre"
    PROVIDER_POST = "provider.post"


class HookOutcome(str, Enum):
    """Durable audit outcome for a single hook dispatch."""

    OK = "OK"
    DENIED = "DENIED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class HookSourceKind(str, Enum):
    """Where a hook entry may be loaded from.

    ``OPERATOR_FILE`` is the ONLY allowed source in v1. Repository/workspace
    sources (``.agent-os/hooks/`` under the workspace, ``AGENTS.md``
    declarations, etc.) are forbidden by default because the workspace is
    writable by the agent itself, which would make model output executable
    code. This is enforced in the runtime loader.
    """

    OPERATOR_FILE = "operator_file"


class HookOnError(str, Enum):
    """Per-hook failure policy."""

    SKIP_AND_RECORD = "skip_and_record"
    FAIL_CLOSED = "fail_closed"


class HookConfig(ContractModel):
    """One registered hook entry.

    The payload handed to a hook is a frozen, read-only snapshot; the v1
    hook return value is always ``None`` (observer only). A hook never
    receives a write handle, a permit, an approval gateway, or the
    correction admin port.
    """

    hook_id: NonEmptyStr
    event: HookEvent
    source_kind: HookSourceKind = HookSourceKind.OPERATOR_FILE
    # Absolute path to the hook entry artifact (an isolated-process script or
    # module entry). Must live OUTSIDE the workspace by policy.
    source_path: NonEmptyStr
    entry: NonEmptyStr = "main"
    # Integrity pin: sha256 of the loaded bytes. Mismatch => hook is not
    # loaded and a durable audit record is written (fail-closed).
    sha256: NonEmptyStr
    hooks_schema_version: NonEmptyStr = "hooks-v1"
    enabled: bool = True
    required: bool = False
    on_error: HookOnError = HookOnError.SKIP_AND_RECORD


class HookDispatchRecord(ContractModel):
    """Durable audit record written for every hook dispatch attempt."""

    hook_id: NonEmptyStr
    event: HookEvent
    outcome: HookOutcome
    latency_ms: int = Field(ge=0)
    # Why the hook was skipped (integrity mismatch, source forbidden,
    # disabled, global kill-switch, subprocess failure ...). Machine-readable.
    reason: NonEmptyStr = "none"
    correlation_id: NonEmptyStr = "correlation:none"


# --------------------------------------------------------------------------- #
# MCP (Model Context Protocol)
# --------------------------------------------------------------------------- #


class McpTransport(str, Enum):
    """Allowed MCP transport.

    v1 ONLY allows local stdio. Network/SSE/HTTP transports are forbidden:
    they enlarge the outbound and credential-exposure surface and are not in
    the minimal slice.
    """

    STDIO = "stdio"


class McpToolTier(int, Enum):
    """Our own classification of an MCP tool.

    The server's self-reported risk level can only RAISE our tier, never
    lower it. A tool at tier >= 3 MUST go through the normal human approval
    gate; it is never auto-executed.
    """

    READ_ONLY = 1
    LOCAL_WRITE = 2
    SIDE_EFFECT = 3


class McpServerConfig(ContractModel):
    """One configured local stdio MCP server.

    Conservative defaults:
    - ``enabled`` defaults to ``False`` (opt-in);
    - transport is fixed to ``stdio`` (no network);
    - ``env_allowlist`` restricts the environment the server subprocess sees;
      provider keys (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, ...) are
      NEVER inherited from the daemon process.
    """

    server_id: NonEmptyStr
    transport: Literal[McpTransport.STDIO] = McpTransport.STDIO
    command: NonEmptyStr
    args: tuple[str, ...] = ()
    # Explicit allow-list of environment variable NAMES passed to the server
    # subprocess. Anything not listed (including every provider key) is
    # dropped before spawn. An empty allow-list means "pass nothing".
    env_allowlist: tuple[str, ...] = ()
    enabled: bool = False
    # Our ceiling for this server's tools. The server's self-reported level
    # may raise a tool above this, never lower it.
    max_tier: McpToolTier = McpToolTier.READ_ONLY


# Names that must NEVER be inherited by an MCP server / hook subprocess, even
# if they appear in an allow-list. This is enforced in the runtime spawner.
FORBIDDEN_SUBPROCESS_ENV_NAMES: frozenset[str] = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "OPENAI_BASE_URL",
        "ANTHROPIC_BASE_URL",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "KIMI_API_KEY",
        "DASHSCOPE_API_KEY",
        "OPENROUTER_API_KEY",
    }
)


# --------------------------------------------------------------------------- #
# Minimal model-agnostic skills face
# --------------------------------------------------------------------------- #


class SkillDefinition(ContractModel):
    """A minimal, model-agnostic skill descriptor.

    A skill is metadata the agent can DISCOVER and QUERY; it is not an
    executable payload in the daemon process. Loading/executing a skill
    goes through the governed capability spine. Skills are opt-in: an
    undeclared skill is never loaded.
    """

    name: NonEmptyStr
    description: NonEmptyStr
    # JSON Schema (draft 2020-12 subset) describing the skill input. Kept as
    # a plain frozen mapping; the runtime validates against it.
    input_schema: dict[str, Any] = Field(default_factory=dict)
    # Our risk tier for the skill; tier >= 3 requires human approval.
    tier: int = Field(default=1, ge=1, le=5)
    # Whether the skill is declared/enabled. Defaults to False so an
    # undeclared skill is inert.
    enabled: bool = False
