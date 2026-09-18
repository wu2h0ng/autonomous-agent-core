"""Typed contract layer for Form B: a parent session spawning child sessions.

Frozen for the 2026-09-19 parallel batch. Five consumer branches import this
module; every name here is frozen and additive-only (a field may be added,
never changed or removed).

Capability id ``agent.spawn`` is declared here; this module stays domain-free
and names no domain semantics. Registering that capability with the developer
domain pack, and wiring it through the ordinary capability adapter, is the
consumers' duty.

Grant invariant, enforced in this module (never the caller's duty)::

    child_grants subset-of parent_grants subset-of task_grants
    principal / tenant / workspace cannot widen
    max_risk_tier(child) <= max_risk_tier(parent)
    budget_limit(child) <= parent's remaining budget
    a tier>=3 action still needs a real operator ApprovalDecision bound to the
    child's action digest (enforced by the kernel, not by this module)

The single entry point the kernel calls for that invariant is
:func:`derive_child_grants`. Its keyword-only signature is::

    derive_child_grants(
        *,
        parent_grants: Sequence[CapabilityGrant],
        proposed_child_grants: Sequence[CapabilityGrant],
        parent_remaining_budget: ResourceBudget,
        agent_type: ChildAgentType = ChildAgentType.GENERAL,
        nested_spawn_enabled: bool = False,
        task_grants: Sequence[CapabilityGrant] | None = None,
    ) -> tuple[CapabilityGrant, ...]

It returns the validated child grants (the caller's own objects, canonically
ordered) or raises a :class:`ChildAgentContractError` subclass. It never edits
or re-derives a grant, and it never silently narrows one.

Durable model (append-only, additive): ``CHILD_AGENT_SPAWNED`` carries
:class:`ChildAgentSpawned`, ``CHILD_AGENT_FINISHED`` carries
:class:`ChildAgentFinished`, and child session events carry the
:class:`ChildAgentLink` fields ``parent_session_id`` / ``parent_turn_id`` /
``spawn_id``.

No prompt or completion TEXT is ever carried by a durable record: the events
carry ``prompt_digest`` / ``summary_digest`` only, following the metrics and
provider-attempt precedent. ``ChildAgentSpawnResult.text`` is the parent
turn's in-memory, bounded result for the operator, never a durable record and
never an echo of the prompt.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from .capability import CapabilityGrant, CapabilityGrantStatus
from .common import ContractModel, NonEmptyStr
from .evidence import Sha256Digest
from .resource import ResourceBudget

AGENT_SPAWN_CAPABILITY_ID = "agent.spawn"

EXPLORE_ALLOWED_CAPABILITY_IDS: tuple[str, ...] = (
    "workspace.read",
    "workspace.search",
)
"""The frozen read-only subset an ``explore`` child may hold.

No edit, apply_patch, run_tests, shell, todo_write or artifact.write.
"""

MAX_CHILD_AGENT_DESCRIPTION_CHARS = 80
MAX_CHILD_AGENT_TEXT_CHARS = 20_000
DEFAULT_MAX_CHILDREN_IN_FLIGHT = 4
MAX_CHILD_AGENTS_ENV_VAR = "AGENT_OS_MAX_CHILD_AGENTS"
STOP_REASON_STOPPED_BY_OPERATOR = "stopped_by_operator"
"""Frozen stop reason on a child that ends because the operator stopped it."""

ChildAgentDescription = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_CHILD_AGENT_DESCRIPTION_CHARS,
    ),
]
"""Operator-visible label: non-empty, at most 80 characters."""

ChildAgentText = Annotated[
    str,
    StringConstraints(max_length=MAX_CHILD_AGENT_TEXT_CHARS),
]
"""Bounded final assistant text; verbatim, so it is never stripped here."""


class ChildAgentType(str, Enum):
    """Frozen agent-type restriction.

    ``GENERAL`` inherits the parent's capability set minus ``agent.spawn``
    unless nested spawns are explicitly enabled (default OFF). ``EXPLORE`` is
    the read-only subset in :data:`EXPLORE_ALLOWED_CAPABILITY_IDS`.
    """

    GENERAL = "general"
    EXPLORE = "explore"

    def allowed_capability_ids(self) -> tuple[str, ...] | None:
        """Return the type's hard capability allowlist, or None for GENERAL."""
        if self is ChildAgentType.EXPLORE:
            return EXPLORE_ALLOWED_CAPABILITY_IDS
        return None


class ChildAgentStatus(str, Enum):
    """Frozen terminal status of one child agent run."""

    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    TIMEOUT = "timeout"
    LIMIT = "limit"


class ChildAgentContractError(ValueError):
    """Base for every typed rejection of the agent-spawn contract layer."""


class ChildAgentLimitExceeded(ChildAgentContractError):
    """Fan-out bound exceeded: a typed rejection, never a silent queue."""


class ChildAgentGrantWidening(ChildAgentContractError):
    """A proposed child grant widens what the parent holds.

    Covers capability, identity, risk tier, budget or lifetime, and a parent
    chain that is already inconsistent with the task grants (fail-closed).
    """


class ChildAgentCapabilityDenied(ChildAgentContractError):
    """The child's agent type forbids the requested capability."""


class ChildAgentSpawnCommand(ContractModel):
    """Typed input of ``agent.spawn`` (frozen)."""

    prompt: NonEmptyStr
    description: ChildAgentDescription
    agent_type: ChildAgentType = ChildAgentType.GENERAL
    max_steps: int | None = Field(default=None, ge=1)


class ChildAgentSpawnResult(ContractModel):
    """Typed output of ``agent.spawn`` (frozen).

    ``text`` is the child's final assistant text, bounded by
    :data:`MAX_CHILD_AGENT_TEXT_CHARS` and never an echo of the prompt. This
    record is returned to the parent turn; it is never durable.
    """

    child_session_id: NonEmptyStr
    child_task_id: NonEmptyStr
    status: ChildAgentStatus
    text: ChildAgentText = ""
    steps: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    stop_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _require_stop_reason_for_stop(self) -> ChildAgentSpawnResult:
        if self.status is ChildAgentStatus.STOPPED and self.stop_reason is None:
            raise ValueError(
                "a stopped child agent result requires a stop reason "
                f"({STOP_REASON_STOPPED_BY_OPERATOR} when an operator stopped it)"
            )
        return self


class ChildAgentSpawned(ContractModel):
    """Payload of the durable ``CHILD_AGENT_SPAWNED`` event (digest-only).

    Carries ``prompt_digest``, never the prompt text.
    """

    spawn_id: NonEmptyStr
    parent_session_id: NonEmptyStr
    parent_turn_id: NonEmptyStr
    child_session_id: NonEmptyStr
    child_task_id: NonEmptyStr
    agent_type: ChildAgentType
    description: ChildAgentDescription
    prompt_digest: Sha256Digest


class ChildAgentFinished(ContractModel):
    """Payload of the durable ``CHILD_AGENT_FINISHED`` event (digest-only).

    Carries ``summary_digest``, never the child's completion text; a child
    with no summary text digests the empty string.
    """

    spawn_id: NonEmptyStr
    status: ChildAgentStatus
    steps: int = Field(ge=0)
    tokens: int = Field(ge=0)
    stop_reason: NonEmptyStr | None = None
    summary_digest: Sha256Digest


class ChildAgentLink(ContractModel):
    """Parent-child link fields; every child session event carries them.

    ``event_link_fields`` returns exactly the three fields a child session
    event must expose, so a producer cannot carry a partial link.
    """

    spawn_id: NonEmptyStr
    parent_session_id: NonEmptyStr
    parent_turn_id: NonEmptyStr
    child_session_id: NonEmptyStr
    child_task_id: NonEmptyStr
    agent_type: ChildAgentType

    @classmethod
    def from_spawned(cls, spawned: ChildAgentSpawned) -> ChildAgentLink:
        return cls(
            spawn_id=spawned.spawn_id,
            parent_session_id=spawned.parent_session_id,
            parent_turn_id=spawned.parent_turn_id,
            child_session_id=spawned.child_session_id,
            child_task_id=spawned.child_task_id,
            agent_type=spawned.agent_type,
        )

    def event_link_fields(self) -> dict[str, str]:
        return {
            "parent_session_id": self.parent_session_id,
            "parent_turn_id": self.parent_turn_id,
            "spawn_id": self.spawn_id,
        }


class ChildAgentAttribution(ContractModel):
    """Per-child row of a parent turn's attribution roll-up."""

    spawn_id: NonEmptyStr
    child_session_id: NonEmptyStr
    child_task_id: NonEmptyStr
    agent_type: ChildAgentType
    description: ChildAgentDescription
    status: ChildAgentStatus
    steps: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    stop_reason: NonEmptyStr | None = None


class ChildAgentTurnAttribution(ContractModel):
    """Attribution projection for one parent turn (frozen).

    ``children`` exposes per-child status/steps/tokens. ``total_steps`` and
    ``total_tokens`` INCLUDE the children and say so:
    ``children_included_in_totals`` is pinned ``True``, and the totals are
    validated against the child rows, so a roll-up that excludes children
    cannot be constructed.
    """

    parent_session_id: NonEmptyStr
    parent_turn_id: NonEmptyStr
    children: tuple[ChildAgentAttribution, ...] = ()
    parent_own_steps: int = Field(default=0, ge=0)
    parent_own_tokens: int = Field(default=0, ge=0)
    total_steps: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    children_included_in_totals: Literal[True] = True

    @field_validator("children", mode="after")
    @classmethod
    def _order_children(
        cls, values: tuple[ChildAgentAttribution, ...]
    ) -> tuple[ChildAgentAttribution, ...]:
        ordered = tuple(sorted(values, key=lambda child: child.spawn_id))
        if len({child.spawn_id for child in ordered}) != len(ordered):
            raise ValueError("attribution children must have unique spawn ids")
        return ordered

    @model_validator(mode="after")
    def _validate_totals_include_children(self) -> ChildAgentTurnAttribution:
        child_steps = sum(child.steps for child in self.children)
        child_tokens = sum(child.tokens for child in self.children)
        if self.total_steps != self.parent_own_steps + child_steps:
            raise ValueError("parent turn total_steps must include child steps")
        if self.total_tokens != self.parent_own_tokens + child_tokens:
            raise ValueError("parent turn total_tokens must include child tokens")
        return self


class ChildAgentFanOutConfig(ContractModel):
    """Fan-out bound: at most N children in flight per parent turn.

    Default :data:`DEFAULT_MAX_CHILDREN_IN_FLIGHT` (4), overridden by the
    ``AGENT_OS_MAX_CHILD_AGENTS`` environment variable.
    """

    max_children_in_flight: int = Field(
        default=DEFAULT_MAX_CHILDREN_IN_FLIGHT,
        ge=1,
    )

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> ChildAgentFanOutConfig:
        """Read the bound from ``AGENT_OS_MAX_CHILD_AGENTS``.

        Unset or blank falls back to the default. A set-but-invalid value
        raises :class:`ChildAgentContractError` rather than being ignored, so
        a misconfiguration is visible instead of silently changing the bound.
        """

        raw = env.get(MAX_CHILD_AGENTS_ENV_VAR)
        if raw is None or not raw.strip():
            return cls()
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise ChildAgentContractError(
                f"{MAX_CHILD_AGENTS_ENV_VAR} must be a positive integer"
            ) from exc
        if value < 1:
            raise ChildAgentContractError(
                f"{MAX_CHILD_AGENTS_ENV_VAR} must be a positive integer"
            )
        return cls(max_children_in_flight=value)


def enforce_child_agent_limit(
    *,
    in_flight_children: int,
    config: ChildAgentFanOutConfig,
) -> None:
    """Reject a spawn when the parent turn already holds N children in flight.

    Exceeding the bound is a typed :class:`ChildAgentLimitExceeded`, never a
    silent queue.
    """

    if in_flight_children < 0:
        raise ChildAgentContractError("in-flight child count cannot be negative")
    if in_flight_children >= config.max_children_in_flight:
        raise ChildAgentLimitExceeded(
            "parent turn already holds "
            f"{in_flight_children} children in flight; the fan-out bound is "
            f"{config.max_children_in_flight}"
        )


def _active_grants(
    grants: Sequence[CapabilityGrant],
) -> tuple[CapabilityGrant, ...]:
    return tuple(
        grant for grant in grants if grant.status is CapabilityGrantStatus.ACTIVE
    )


def derive_child_grants(
    *,
    parent_grants: Sequence[CapabilityGrant],
    proposed_child_grants: Sequence[CapabilityGrant],
    parent_remaining_budget: ResourceBudget,
    agent_type: ChildAgentType = ChildAgentType.GENERAL,
    nested_spawn_enabled: bool = False,
    task_grants: Sequence[CapabilityGrant] | None = None,
) -> tuple[CapabilityGrant, ...]:
    """Validate one child's proposed grants against its parent's grants.

    Returns the validated child grants in canonical order, or raises a
    :class:`ChildAgentContractError` subclass. Widening is impossible by
    construction: the function compares and refuses, it never merges, narrows
    or rewrites a grant.

    Rejection precedence (first failing check wins; every one is typed):

    1. ``ChildAgentContractError`` — no active parent grants, parent grants
       spanning more than one principal/tenant/workspace, a duplicate active
       parent or child capability, a non-ACTIVE proposed child grant, or no
       proposed child grant.
    2. ``ChildAgentGrantWidening`` — the parent grants are outside
       ``task_grants`` (when given).
    3. ``ChildAgentGrantWidening`` — the child widens principal, tenant or
       workspace.
    4. ``ChildAgentCapabilityDenied`` — the agent type forbids the capability:
       an ``explore`` child outside the read-only subset, or a child granted
       ``agent.spawn`` while ``nested_spawn_enabled`` is False.
    5. ``ChildAgentGrantWidening`` — the parent does not hold the capability.
    6. ``ChildAgentGrantWidening`` — the child risk tier exceeds the parent
       grant's risk tier.
    7. ``ChildAgentGrantWidening`` — the child budget exceeds the parent
       grant's budget or the parent's remaining budget.
    8. ``ChildAgentGrantWidening`` — the parent grant is already expired at
       the child's ``granted_at``, or the child grant outlives the parent
       grant.

    This function does not decide approvals: a tier>=3 child action still
    needs a real operator ``ApprovalDecision`` bound to the child's action
    digest, which the kernel enforces on the single dispatch path.
    """

    parent = _active_grants(parent_grants)
    if not parent:
        raise ChildAgentContractError(
            "child agent grant derivation requires active parent grants"
        )

    identities = {
        (grant.principal_id, grant.tenant_id, grant.workspace_id) for grant in parent
    }
    if len(identities) != 1:
        raise ChildAgentContractError(
            "parent grants span more than one principal/tenant/workspace"
        )
    parent_identity = identities.pop()

    parent_by_capability: dict[tuple[str, str], CapabilityGrant] = {}
    for grant in parent:
        key = (grant.capability_id, grant.capability_version)
        if key in parent_by_capability:
            raise ChildAgentContractError(
                "parent grants contain a duplicate active capability"
            )
        parent_by_capability[key] = grant

    if task_grants is not None:
        task_keys = {
            (grant.capability_id, grant.capability_version)
            for grant in _active_grants(task_grants)
        }
        for key, grant in parent_by_capability.items():
            if key not in task_keys:
                raise ChildAgentGrantWidening(
                    f"parent grant {grant.capability_id}@{grant.capability_version} "
                    "is outside the task grants"
                )

    if not proposed_child_grants:
        raise ChildAgentContractError(
            "child agent grant derivation requires at least one proposed child grant"
        )

    allowed_capability_ids = agent_type.allowed_capability_ids()
    seen_child_keys: set[tuple[str, str]] = set()
    for grant in proposed_child_grants:
        key = (grant.capability_id, grant.capability_version)
        if key in seen_child_keys:
            raise ChildAgentContractError(
                "proposed child grants contain a duplicate capability"
            )
        seen_child_keys.add(key)
        if grant.status is not CapabilityGrantStatus.ACTIVE:
            raise ChildAgentContractError("proposed child grant must be ACTIVE")
        if (
            grant.principal_id,
            grant.tenant_id,
            grant.workspace_id,
        ) != parent_identity:
            raise ChildAgentGrantWidening(
                "child grant cannot widen principal, tenant or workspace"
            )
        if (
            allowed_capability_ids is not None
            and grant.capability_id not in allowed_capability_ids
        ):
            raise ChildAgentCapabilityDenied(
                f"{agent_type.value} child agents are read-only; "
                f"{grant.capability_id} is outside {allowed_capability_ids}"
            )
        if (
            grant.capability_id == AGENT_SPAWN_CAPABILITY_ID
            and not nested_spawn_enabled
        ):
            raise ChildAgentCapabilityDenied(
                "nested spawns are disabled by default; a child cannot hold "
                f"{AGENT_SPAWN_CAPABILITY_ID}"
            )
        parent_grant = parent_by_capability.get(key)
        if parent_grant is None:
            raise ChildAgentGrantWidening(
                f"child capability {grant.capability_id}@{grant.capability_version} "
                "is not granted to the parent"
            )
        if grant.max_risk_tier > parent_grant.max_risk_tier:
            raise ChildAgentGrantWidening(
                "child risk tier cannot exceed the parent grant risk tier"
            )
        if not grant.budget_limit.fits_within(parent_grant.budget_limit):
            raise ChildAgentGrantWidening(
                "child budget cannot exceed the parent grant budget"
            )
        if not grant.budget_limit.fits_within(parent_remaining_budget):
            raise ChildAgentGrantWidening(
                "child budget cannot exceed the parent's remaining budget"
            )
        if parent_grant.expires_at <= grant.granted_at:
            raise ChildAgentGrantWidening(
                "parent grant is already expired at the child's granted_at"
            )
        if grant.expires_at > parent_grant.expires_at:
            raise ChildAgentGrantWidening("child grant cannot outlive the parent grant")

    return tuple(
        sorted(
            proposed_child_grants,
            key=lambda grant: (
                grant.capability_id,
                grant.capability_version,
                grant.grant_id,
            ),
        )
    )
