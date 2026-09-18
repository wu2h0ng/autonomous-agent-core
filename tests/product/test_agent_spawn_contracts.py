from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    AGENT_SPAWN_CAPABILITY_ID,
    DEFAULT_MAX_CHILDREN_IN_FLIGHT,
    EXPLORE_ALLOWED_CAPABILITY_IDS,
    MAX_CHILD_AGENTS_ENV_VAR,
    MAX_CHILD_AGENT_TEXT_CHARS,
    STOP_REASON_STOPPED_BY_OPERATOR,
    CapabilityGrant,
    CapabilityGrantStatus,
    ChildAgentAttribution,
    ChildAgentCapabilityDenied,
    ChildAgentContractError,
    ChildAgentFanOutConfig,
    ChildAgentFinished,
    ChildAgentGrantWidening,
    ChildAgentLimitExceeded,
    ChildAgentLink,
    ChildAgentSpawnCommand,
    ChildAgentSpawnResult,
    ChildAgentSpawned,
    ChildAgentStatus,
    ChildAgentTurnAttribution,
    ChildAgentType,
    ResourceBudget,
    TaskEventDraft,
    TaskEventType,
    derive_child_grants,
    enforce_child_agent_limit,
)


NOW = datetime(2026, 9, 19, 8, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=4)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _budget(
    *,
    cost: str = "1",
    duration: int = 600,
    tokens: int = 10_000,
    tool_calls: int = 50,
) -> ResourceBudget:
    return ResourceBudget(
        max_cost_usd=Decimal(cost),
        max_duration_seconds=duration,
        max_provider_tokens=tokens,
        max_tool_calls=tool_calls,
    )


def _grant(
    *,
    grant_id: str,
    capability_id: str,
    principal_id: str = "principal-1",
    tenant_id: str = "tenant-1",
    workspace_id: str = "workspace-1",
    capability_version: str = "1.0",
    max_risk_tier: int = 2,
    budget_limit: ResourceBudget | None = None,
    status: CapabilityGrantStatus = CapabilityGrantStatus.ACTIVE,
    granted_at: datetime = NOW,
    expires_at: datetime = LATER,
) -> CapabilityGrant:
    return CapabilityGrant(
        grant_id=grant_id,
        principal_id=principal_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        capability_id=capability_id,
        capability_version=capability_version,
        max_risk_tier=max_risk_tier,
        budget_limit=budget_limit or _budget(),
        status=status,
        granted_by="operator-1",
        granted_at=granted_at,
        expires_at=expires_at,
    )


def _parent_grants() -> tuple[CapabilityGrant, ...]:
    return (
        _grant(
            grant_id="grant-read",
            capability_id="workspace.read",
            max_risk_tier=1,
        ),
        _grant(
            grant_id="grant-edit",
            capability_id="workspace.edit",
            max_risk_tier=2,
        ),
        _grant(
            grant_id="grant-spawn",
            capability_id=AGENT_SPAWN_CAPABILITY_ID,
            max_risk_tier=2,
        ),
    )


def _derive(
    proposed: tuple[CapabilityGrant, ...],
    **overrides: object,
) -> tuple[CapabilityGrant, ...]:
    kwargs: dict[str, object] = {
        "parent_grants": _parent_grants(),
        "proposed_child_grants": proposed,
        "parent_remaining_budget": _budget(),
        "agent_type": ChildAgentType.GENERAL,
    }
    kwargs.update(overrides)
    return derive_child_grants(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Command / result shapes
# --------------------------------------------------------------------------


def test_spawn_command_defaults_match_frozen_input() -> None:
    command = ChildAgentSpawnCommand(
        prompt="count the failing tests",
        description="triage failing tests",
    )

    assert command.agent_type is ChildAgentType.GENERAL
    assert command.agent_type == "general"
    assert command.max_steps is None
    assert command.model_dump(mode="json")["agent_type"] == "general"


def test_spawn_command_rejects_over_long_description() -> None:
    with pytest.raises(ValidationError):
        ChildAgentSpawnCommand(prompt="x", description="d" * 81)


def test_spawn_command_rejects_unknown_agent_type() -> None:
    with pytest.raises(ValidationError):
        ChildAgentSpawnCommand(
            prompt="x",
            description="d",
            agent_type="planner",  # type: ignore[arg-type]
        )


def test_spawn_result_keeps_frozen_status_vocabulary() -> None:
    result = ChildAgentSpawnResult(
        child_session_id="session-child",
        child_task_id="task-child",
        status="completed",  # type: ignore[arg-type]
        text="all 12 tests pass",
        steps=4,
        tokens=812,
        stop_reason="completed",
    )

    assert {status.value for status in ChildAgentStatus} == {
        "completed",
        "failed",
        "stopped",
        "timeout",
        "limit",
    }
    assert result.status is ChildAgentStatus.COMPLETED
    assert result.model_dump(mode="json")["status"] == "completed"


def test_stopped_child_result_requires_stop_reason() -> None:
    with pytest.raises(ValidationError, match="stop reason"):
        ChildAgentSpawnResult(
            child_session_id="session-child",
            child_task_id="task-child",
            status=ChildAgentStatus.STOPPED,
        )

    stopped = ChildAgentSpawnResult(
        child_session_id="session-child",
        child_task_id="task-child",
        status=ChildAgentStatus.STOPPED,
        stop_reason=STOP_REASON_STOPPED_BY_OPERATOR,
    )
    assert stopped.stop_reason == "stopped_by_operator"


def test_spawn_result_text_is_bounded() -> None:
    with pytest.raises(ValidationError):
        ChildAgentSpawnResult(
            child_session_id="session-child",
            child_task_id="task-child",
            status=ChildAgentStatus.COMPLETED,
            text="t" * (MAX_CHILD_AGENT_TEXT_CHARS + 1),
        )


# --------------------------------------------------------------------------
# Durable records: digests only, no prompt or completion text
# --------------------------------------------------------------------------


def test_durable_spawn_record_carries_prompt_digest_and_no_prompt_text() -> None:
    fields = ChildAgentSpawned.model_fields
    assert set(fields) == {
        "schema_version",
        "spawn_id",
        "parent_session_id",
        "parent_turn_id",
        "child_session_id",
        "child_task_id",
        "agent_type",
        "description",
        "prompt_digest",
    }
    assert "prompt" not in fields and "text" not in fields

    spawned = ChildAgentSpawned(
        spawn_id="spawn-1",
        parent_session_id="session-parent",
        parent_turn_id="turn-1",
        child_session_id="session-child",
        child_task_id="task-child",
        agent_type=ChildAgentType.EXPLORE,
        description="read-only recon",
        prompt_digest=DIGEST_A,
    )

    assert spawned.prompt_digest == DIGEST_A
    with pytest.raises(ValidationError):
        ChildAgentSpawned.model_validate(
            {**spawned.model_dump(mode="json"), "prompt_digest": "not-a-digest"}
        )
    with pytest.raises(ValidationError):
        ChildAgentSpawned.model_validate(
            {**spawned.model_dump(mode="json"), "prompt": "raw prompt text"}
        )


def test_durable_finished_record_carries_summary_digest_and_no_text() -> None:
    fields = ChildAgentFinished.model_fields
    assert set(fields) == {
        "schema_version",
        "spawn_id",
        "status",
        "steps",
        "tokens",
        "stop_reason",
        "summary_digest",
    }
    assert "text" not in fields and "summary" not in fields

    finished = ChildAgentFinished(
        spawn_id="spawn-1",
        status=ChildAgentStatus.LIMIT,
        steps=12,
        tokens=4096,
        stop_reason="max_steps",
        summary_digest=DIGEST_B,
    )

    assert finished.summary_digest == DIGEST_B
    with pytest.raises(ValidationError):
        ChildAgentFinished.model_validate(
            {**finished.model_dump(mode="json"), "summary": "raw completion text"}
        )


def test_child_session_event_link_fields_are_exactly_the_frozen_three() -> None:
    spawned = ChildAgentSpawned(
        spawn_id="spawn-1",
        parent_session_id="session-parent",
        parent_turn_id="turn-1",
        child_session_id="session-child",
        child_task_id="task-child",
        agent_type=ChildAgentType.GENERAL,
        description="fix the flaky test",
        prompt_digest=DIGEST_A,
    )
    link = ChildAgentLink.from_spawned(spawned)

    assert link.event_link_fields() == {
        "parent_session_id": "session-parent",
        "parent_turn_id": "turn-1",
        "spawn_id": "spawn-1",
    }
    assert link.child_session_id == "session-child"


def test_new_event_types_are_registered_additively() -> None:
    assert TaskEventType.CHILD_AGENT_SPAWNED.value == "CHILD_AGENT_SPAWNED"
    assert TaskEventType.CHILD_AGENT_FINISHED.value == "CHILD_AGENT_FINISHED"
    # pre-existing events are untouched
    assert TaskEventType.SESSION_CLOSED.value == "SESSION_CLOSED"
    assert TaskEventType.SESSION_TURN_COMPLETED.value == "SESSION_TURN_COMPLETED"


def test_spawned_event_payload_encodes_digest_only() -> None:
    spawned = ChildAgentSpawned(
        spawn_id="spawn-1",
        parent_session_id="session-parent",
        parent_turn_id="turn-1",
        child_session_id="session-child",
        child_task_id="task-child",
        agent_type=ChildAgentType.GENERAL,
        description="fix the flaky test",
        prompt_digest=DIGEST_A,
    )
    draft = TaskEventDraft.build(
        event_id="event-1",
        task_id="task-child",
        event_type=TaskEventType.CHILD_AGENT_SPAWNED,
        payload=spawned.model_dump(mode="json"),
        occurred_at=NOW,
    )
    payload = draft.decoded_payload()

    assert payload["prompt_digest"] == DIGEST_A
    assert "prompt" not in payload
    assert payload["spawn_id"] == "spawn-1"


# --------------------------------------------------------------------------
# Attribution roll-up: totals INCLUDE children and say so
# --------------------------------------------------------------------------


def _child_row(**overrides: object) -> ChildAgentAttribution:
    payload: dict[str, object] = {
        "spawn_id": "spawn-1",
        "child_session_id": "session-child",
        "child_task_id": "task-child",
        "agent_type": ChildAgentType.GENERAL,
        "description": "fix the flaky test",
        "status": ChildAgentStatus.COMPLETED,
        "steps": 5,
        "tokens": 900,
    }
    payload.update(overrides)
    return ChildAgentAttribution.model_validate(payload)


def test_turn_attribution_totals_include_children() -> None:
    attribution = ChildAgentTurnAttribution(
        parent_session_id="session-parent",
        parent_turn_id="turn-1",
        children=(_child_row(),),
        parent_own_steps=3,
        parent_own_tokens=100,
        total_steps=8,
        total_tokens=1000,
    )

    assert attribution.children_included_in_totals is True
    assert attribution.total_steps == attribution.parent_own_steps + sum(
        child.steps for child in attribution.children
    )


def test_turn_attribution_rejects_totals_that_exclude_children() -> None:
    with pytest.raises(ValidationError, match="must include child steps"):
        ChildAgentTurnAttribution(
            parent_session_id="session-parent",
            parent_turn_id="turn-1",
            children=(_child_row(),),
            parent_own_steps=3,
            parent_own_tokens=100,
            total_steps=3,
            total_tokens=1000,
        )

    with pytest.raises(ValidationError, match="must include child tokens"):
        ChildAgentTurnAttribution(
            parent_session_id="session-parent",
            parent_turn_id="turn-1",
            children=(_child_row(),),
            parent_own_steps=3,
            parent_own_tokens=100,
            total_steps=8,
            total_tokens=100,
        )


def test_turn_attribution_cannot_disclaim_child_totals() -> None:
    with pytest.raises(ValidationError):
        ChildAgentTurnAttribution.model_validate(
            {
                "parent_session_id": "session-parent",
                "parent_turn_id": "turn-1",
                "children": [],
                "parent_own_steps": 3,
                "parent_own_tokens": 100,
                "total_steps": 3,
                "total_tokens": 100,
                "children_included_in_totals": False,
            }
        )


def test_turn_attribution_orders_children_and_rejects_duplicates() -> None:
    attribution = ChildAgentTurnAttribution(
        parent_session_id="session-parent",
        parent_turn_id="turn-1",
        children=(_child_row(spawn_id="spawn-2"), _child_row(spawn_id="spawn-1")),
        total_steps=10,
        total_tokens=1800,
    )
    assert [child.spawn_id for child in attribution.children] == [
        "spawn-1",
        "spawn-2",
    ]

    with pytest.raises(ValidationError, match="unique spawn ids"):
        ChildAgentTurnAttribution(
            parent_session_id="session-parent",
            parent_turn_id="turn-1",
            children=(_child_row(), _child_row()),
            total_steps=10,
            total_tokens=1800,
        )


# --------------------------------------------------------------------------
# Fan-out bound: typed rejection, never a silent queue
# --------------------------------------------------------------------------


def test_fan_out_defaults_to_four_and_reads_the_env_var() -> None:
    assert ChildAgentFanOutConfig().max_children_in_flight == 4
    assert DEFAULT_MAX_CHILDREN_IN_FLIGHT == 4
    assert (
        ChildAgentFanOutConfig.from_env({}).max_children_in_flight
        == DEFAULT_MAX_CHILDREN_IN_FLIGHT
    )
    assert (
        ChildAgentFanOutConfig.from_env(
            {MAX_CHILD_AGENTS_ENV_VAR: "2"}
        ).max_children_in_flight
        == 2
    )
    assert (
        ChildAgentFanOutConfig.from_env(
            {MAX_CHILD_AGENTS_ENV_VAR: "  "}
        ).max_children_in_flight
        == DEFAULT_MAX_CHILDREN_IN_FLIGHT
    )


def test_fan_out_env_garbage_is_typed_not_silent() -> None:
    for raw in ("four", "0", "-3"):
        with pytest.raises(ChildAgentContractError):
            ChildAgentFanOutConfig.from_env({MAX_CHILD_AGENTS_ENV_VAR: raw})


def test_exceeding_the_fan_out_bound_is_a_typed_rejection() -> None:
    config = ChildAgentFanOutConfig(max_children_in_flight=4)

    enforce_child_agent_limit(in_flight_children=3, config=config)

    with pytest.raises(ChildAgentLimitExceeded, match="fan-out bound is 4"):
        enforce_child_agent_limit(in_flight_children=4, config=config)

    with pytest.raises(ChildAgentContractError):
        enforce_child_agent_limit(in_flight_children=-1, config=config)


def test_limit_exceeded_is_a_contract_error() -> None:
    assert issubclass(ChildAgentLimitExceeded, ChildAgentContractError)
    assert issubclass(ChildAgentGrantWidening, ChildAgentContractError)
    assert issubclass(ChildAgentCapabilityDenied, ChildAgentContractError)


# --------------------------------------------------------------------------
# Grant derivation: positive paths
# --------------------------------------------------------------------------


def test_general_child_narrower_grant_is_derived() -> None:
    derived = _derive(
        (
            _grant(
                grant_id="child-read",
                capability_id="workspace.read",
                max_risk_tier=1,
                budget_limit=_budget(cost="0.5", tokens=1000, tool_calls=5),
            ),
            _grant(
                grant_id="child-edit",
                capability_id="workspace.edit",
                max_risk_tier=2,
                budget_limit=_budget(cost="0.25", tokens=500, tool_calls=2),
            ),
        )
    )

    assert [grant.grant_id for grant in derived] == ["child-edit", "child-read"]


def test_explore_child_gets_the_read_only_subset() -> None:
    derived = _derive(
        (
            _grant(
                grant_id="child-read",
                capability_id="workspace.read",
                max_risk_tier=1,
            ),
            _grant(
                grant_id="child-search",
                capability_id="workspace.search",
                max_risk_tier=1,
            ),
        ),
        parent_grants=(
            *_parent_grants(),
            _grant(grant_id="grant-search", capability_id="workspace.search"),
        ),
        agent_type=ChildAgentType.EXPLORE,
    )

    assert {grant.capability_id for grant in derived} == set(
        EXPLORE_ALLOWED_CAPABILITY_IDS
    )


def test_nested_spawn_needs_the_explicit_opt_in() -> None:
    derived = _derive(
        (_grant(grant_id="child-spawn", capability_id=AGENT_SPAWN_CAPABILITY_ID),),
        nested_spawn_enabled=True,
    )

    assert [grant.capability_id for grant in derived] == [AGENT_SPAWN_CAPABILITY_ID]


def test_task_grants_chain_is_accepted_when_consistent() -> None:
    derived = _derive(
        (
            _grant(
                grant_id="child-read",
                capability_id="workspace.read",
                max_risk_tier=1,
            ),
        ),
        task_grants=_parent_grants(),
    )

    assert [grant.capability_id for grant in derived] == ["workspace.read"]


def test_derivation_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        derive_child_grants(
            _parent_grants(),  # type: ignore[call-arg]
            (  # type: ignore[call-arg]
                _grant(grant_id="child-read", capability_id="workspace.read"),
            ),
        )


# --------------------------------------------------------------------------
# Grant derivation: negative cases (each one typed, none silent)
# --------------------------------------------------------------------------


def test_child_cannot_widen_tenant() -> None:
    with pytest.raises(ChildAgentGrantWidening, match="tenant"):
        _derive(
            (
                _grant(
                    grant_id="child-read",
                    capability_id="workspace.read",
                    tenant_id="tenant-2",
                ),
            )
        )


def test_child_cannot_widen_workspace() -> None:
    with pytest.raises(ChildAgentGrantWidening, match="workspace"):
        _derive(
            (
                _grant(
                    grant_id="child-read",
                    capability_id="workspace.read",
                    workspace_id="workspace-2",
                ),
            )
        )


def test_child_cannot_widen_principal() -> None:
    with pytest.raises(ChildAgentGrantWidening, match="principal"):
        _derive(
            (
                _grant(
                    grant_id="child-read",
                    capability_id="workspace.read",
                    principal_id="principal-2",
                ),
            )
        )


def test_child_cannot_raise_the_risk_tier() -> None:
    with pytest.raises(ChildAgentGrantWidening, match="risk tier"):
        _derive(
            (
                _grant(
                    grant_id="child-read",
                    capability_id="workspace.read",
                    max_risk_tier=3,
                ),
            )
        )


def test_child_cannot_raise_the_grant_budget() -> None:
    with pytest.raises(ChildAgentGrantWidening, match="parent grant budget"):
        _derive(
            (
                _grant(
                    grant_id="child-edit",
                    capability_id="workspace.edit",
                    budget_limit=_budget(cost="5", tokens=50_000),
                ),
            ),
            parent_grants=(
                _grant(
                    grant_id="grant-edit",
                    capability_id="workspace.edit",
                    budget_limit=_budget(cost="1", tokens=10_000),
                ),
            ),
            parent_remaining_budget=_budget(cost="9", tokens=90_000),
        )


def test_child_cannot_exceed_the_parent_remaining_budget() -> None:
    with pytest.raises(ChildAgentGrantWidening, match="remaining budget"):
        _derive(
            (
                _grant(
                    grant_id="child-edit",
                    capability_id="workspace.edit",
                    budget_limit=_budget(cost="1", tokens=9000),
                ),
            ),
            parent_remaining_budget=_budget(cost="0.5", tokens=100),
        )


def test_child_cannot_gain_a_capability_the_parent_lacks() -> None:
    with pytest.raises(ChildAgentGrantWidening, match="not granted to the parent"):
        _derive(
            (
                _grant(
                    grant_id="child-shell",
                    capability_id="workspace.shell",
                    max_risk_tier=3,
                ),
            )
        )


def test_general_child_cannot_spawn_while_nested_spawns_are_off() -> None:
    with pytest.raises(ChildAgentCapabilityDenied, match="nested spawns are disabled"):
        _derive(
            (
                _grant(
                    grant_id="child-spawn",
                    capability_id=AGENT_SPAWN_CAPABILITY_ID,
                ),
            )
        )


def test_explore_child_cannot_hold_a_write_capability() -> None:
    with pytest.raises(ChildAgentCapabilityDenied, match="read-only"):
        _derive(
            (
                _grant(
                    grant_id="child-edit",
                    capability_id="workspace.edit",
                    max_risk_tier=2,
                ),
            ),
            agent_type=ChildAgentType.EXPLORE,
        )

    for forbidden in (
        "workspace.apply_patch",
        "workspace.run_tests",
        "session.todo_write",
        "artifact.write",
        "workspace.shell",
    ):
        with pytest.raises(ChildAgentCapabilityDenied):
            _derive(
                (
                    _grant(
                        grant_id=f"child-{forbidden}",
                        capability_id=forbidden,
                        max_risk_tier=1,
                    ),
                ),
                agent_type=ChildAgentType.EXPLORE,
                parent_grants=(
                    _grant(
                        grant_id=f"grant-{forbidden}",
                        capability_id=forbidden,
                        max_risk_tier=3,
                    ),
                ),
            )


def test_child_grant_cannot_outlive_the_parent_grant() -> None:
    with pytest.raises(ChildAgentGrantWidening, match="outlive"):
        _derive(
            (
                _grant(
                    grant_id="child-read",
                    capability_id="workspace.read",
                    max_risk_tier=1,
                    expires_at=LATER + timedelta(hours=1),
                ),
            )
        )


def test_expired_parent_grant_is_refused() -> None:
    with pytest.raises(ChildAgentGrantWidening, match="already expired"):
        _derive(
            (
                _grant(
                    grant_id="child-read",
                    capability_id="workspace.read",
                    max_risk_tier=1,
                ),
            ),
            parent_grants=(
                _grant(
                    grant_id="grant-read",
                    capability_id="workspace.read",
                    granted_at=NOW - timedelta(hours=2),
                    expires_at=NOW - timedelta(hours=1),
                ),
            ),
        )


def test_revoked_parent_grants_grant_nothing() -> None:
    with pytest.raises(ChildAgentContractError, match="active parent grants"):
        _derive(
            (_grant(grant_id="child-read", capability_id="workspace.read"),),
            parent_grants=(
                _grant(
                    grant_id="grant-read",
                    capability_id="workspace.read",
                    status=CapabilityGrantStatus.REVOKED,
                ),
            ),
        )


def test_inactive_child_grant_is_refused() -> None:
    with pytest.raises(ChildAgentContractError, match="ACTIVE"):
        _derive(
            (
                _grant(
                    grant_id="child-read",
                    capability_id="workspace.read",
                    status=CapabilityGrantStatus.REVOKED,
                ),
            )
        )


def test_duplicate_child_capability_is_refused() -> None:
    with pytest.raises(ChildAgentContractError, match="duplicate capability"):
        _derive(
            (
                _grant(
                    grant_id="child-read-a",
                    capability_id="workspace.read",
                    max_risk_tier=1,
                ),
                _grant(
                    grant_id="child-read-b",
                    capability_id="workspace.read",
                    max_risk_tier=1,
                ),
            )
        )


def test_parent_grants_must_share_one_identity() -> None:
    with pytest.raises(ChildAgentContractError, match="more than one"):
        _derive(
            (_grant(grant_id="child-read", capability_id="workspace.read"),),
            parent_grants=(
                _grant(grant_id="grant-read", capability_id="workspace.read"),
                _grant(
                    grant_id="grant-edit",
                    capability_id="workspace.edit",
                    tenant_id="tenant-2",
                ),
            ),
        )


def test_parent_grant_outside_the_task_grants_is_refused() -> None:
    with pytest.raises(ChildAgentGrantWidening, match="outside the task grants"):
        _derive(
            (_grant(grant_id="child-read", capability_id="workspace.read"),),
            task_grants=(_grant(grant_id="task-edit", capability_id="workspace.edit"),),
        )


def test_no_proposed_child_grant_is_refused() -> None:
    with pytest.raises(ChildAgentContractError, match="at least one"):
        _derive(())
