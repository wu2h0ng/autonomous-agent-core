"""M1 S2: durable, operator-authored, DENY-only permission rules.

A deny rule can only restrict: it downgrades the frozen E2 matrix to DENY_BY_RULE and
can never allow, auto-approve tier-3, or pre-empt C7. Revocation is durable.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    SurfaceBeginTurnCommand,
    SurfaceClientRef,
    SurfaceSetPermissionModeCommand,
    SurfaceStreamBinding,
    TaskEventType,
)
from agent_os_core import (
    DeferredApprovalGateway,
    DeterministicProvider,
    PermissionDenyRule,
    PermissionRuleKind,
    SQLitePermissionRuleStore,
    active_deny_rule,
    apply_deny_rules,
    evaluate_permission_gate,
    rule_matches,
)
from agent_os_core.permission_gate import PermissionGateOutcome
from agent_os_core.provider import ProviderToolProposal

from apps.api_server.app import AgentOSApplication

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _rule(rule_id: str = "rule-1", capability_id: str = "workspace.edit", **kw: object) -> PermissionDenyRule:
    return PermissionDenyRule(
        rule_id=rule_id,
        capability_id=capability_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="operator",
        created_at=NOW,
        reason="deploy freeze",
        **kw,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Rule matching / store
# ---------------------------------------------------------------------------


def test_only_the_deny_kind_exists() -> None:
    # There is deliberately no ALLOW kind: a rule can never grant authority.
    assert [kind.value for kind in PermissionRuleKind] == ["DENY"]


def test_rule_matches_exact_and_wildcard() -> None:
    assert rule_matches(_rule(capability_id="workspace.edit"), "workspace.edit")
    assert not rule_matches(_rule(capability_id="workspace.edit"), "workspace.read")
    assert rule_matches(_rule(capability_id="*"), "workspace.shell")


def test_active_deny_rule_respects_scope_and_revocation() -> None:
    rule = _rule()
    assert (
        active_deny_rule([rule], "workspace.edit", "tenant:local", "workspace:local")
        is rule
    )
    # wrong scope
    assert active_deny_rule([rule], "workspace.edit", "tenant:other", "workspace:local") is None
    # revoked
    revoked = rule.model_copy(update={"revoked_at": NOW})
    assert active_deny_rule([revoked], "workspace.edit", "tenant:local", "workspace:local") is None


def test_store_save_list_and_revoke(tmp_path: Path) -> None:
    store = SQLitePermissionRuleStore(tmp_path / "rules.sqlite3")
    store.save(_rule(rule_id="r1"))
    store.save(_rule(rule_id="r2", capability_id="workspace.shell"))
    active = store.list_active(tenant_id="tenant:local", workspace_id="workspace:local")
    assert {r.rule_id for r in active} == {"r1", "r2"}

    assert store.revoke("r1") is True
    assert store.revoke("missing") is False
    remaining = store.list_active(tenant_id="tenant:local", workspace_id="workspace:local")
    assert [r.rule_id for r in remaining] == ["r2"]

    # durable across reopen
    store.close()
    reopened = SQLitePermissionRuleStore(tmp_path / "rules.sqlite3")
    assert [r.rule_id for r in reopened.list_active(tenant_id="tenant:local", workspace_id="workspace:local")] == ["r2"]
    reopened.close()


# ---------------------------------------------------------------------------
# Gate application (purely restrictive)
# ---------------------------------------------------------------------------


def _allow_decision():
    return evaluate_permission_gate(
        capability_id="workspace.edit", mode="ACCEPT_IN_WORKSPACE", mode_event_id="evt-1"
    )


def test_deny_rule_downgrades_a_mode_auto_allow() -> None:
    decision = _allow_decision()
    assert decision.outcome is PermissionGateOutcome.MODE_AUTO_ALLOW

    gated = apply_deny_rules(
        decision,
        capability_id="workspace.edit",
        rules=[_rule()],
        tenant_id="tenant:local",
        workspace_id="workspace:local",
    )
    assert gated.outcome is PermissionGateOutcome.DENY_BY_RULE
    assert gated.basis == "rule"
    assert gated.rule_id == "rule-1"
    assert gated.risk_tier == decision.risk_tier


def test_deny_rule_does_not_change_a_non_matching_capability() -> None:
    decision = _allow_decision()
    unchanged = apply_deny_rules(
        decision,
        capability_id="workspace.apply_patch",
        rules=[_rule()],
        tenant_id="tenant:local",
        workspace_id="workspace:local",
    )
    assert unchanged is decision


def test_apply_deny_rules_preserves_an_existing_denial() -> None:
    # An out-of-allowlist denial must keep its own audit semantics; a '*' rule
    # must not relabel it as DENY_BY_RULE.
    decision = evaluate_permission_gate(
        capability_id="workspace.exfiltrate", mode="ACCEPT_IN_WORKSPACE", mode_event_id=None
    )
    assert decision.outcome is PermissionGateOutcome.DENY_OUT_OF_ALLOWLIST
    gated = apply_deny_rules(
        decision,
        capability_id="workspace.exfiltrate",
        rules=[_rule(capability_id="*")],
        tenant_id="tenant:local",
        workspace_id="workspace:local",
    )
    assert gated.outcome is PermissionGateOutcome.DENY_OUT_OF_ALLOWLIST


def test_store_is_tenant_scoped(tmp_path: Path) -> None:
    store = SQLitePermissionRuleStore(tmp_path / "rules.sqlite3")
    store.save(_rule(rule_id="r1"))
    assert store.list_active(tenant_id="tenant:other", workspace_id="workspace:local") == []
    store.close()


def test_apply_deny_rules_never_produces_an_allow_outcome() -> None:
    allowed = {
        PermissionGateOutcome.TIER_DEFAULT_AUTO_PASS,
        PermissionGateOutcome.MODE_AUTO_ALLOW,
    }
    for capability_id in ("workspace.read", "workspace.edit", "workspace.shell"):
        for mode in ("ASK", "ACCEPT_READ_ONLY", "ACCEPT_IN_WORKSPACE"):
            decision = evaluate_permission_gate(
                capability_id=capability_id, mode=mode, mode_event_id="e"
            )
            gated = apply_deny_rules(
                decision,
                capability_id=capability_id,
                rules=[_rule(capability_id="*")],
                tenant_id="tenant:local",
                workspace_id="workspace:local",
            )
            # a wildcard DENY rule always denies; it never adds an allow
            assert gated.outcome is PermissionGateOutcome.DENY_BY_RULE
            assert gated.outcome not in allowed


# ---------------------------------------------------------------------------
# Integration through the product chat path
# ---------------------------------------------------------------------------


def _proposal(call_id: str, capability_id: str, arguments: dict) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def _edit_script() -> tuple:
    return (
        (
            "",
            (
                _proposal(
                    "call-edit",
                    "workspace.edit",
                    {"path": "fixture.txt", "old_string": "stable\n", "new_string": "fixed\n"},
                ),
            ),
        ),
        ("edit applied", ()),
    )


def _client_ref() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="tui-1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:local",
    )


def _wait_for(predicate, description: str, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError(f"{description} did not occur within {timeout}s")


def _begin_turn(app: AgentOSApplication, session_id: str) -> None:
    task_id = app.surface_task_for_session(session_id)
    stream_id = app.subscribe_stream(session_id)
    app.surface.begin_turn(
        SurfaceBeginTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            session_id=session_id,
            text="do the edit",
            stream=SurfaceStreamBinding(runtime_boot_id=app.runtime_boot_id, stream_id=stream_id),
            expected_event_sequence=app.surface_current_sequence(task_id),
            idempotency_key=f"turn:{session_id}:{time.monotonic_ns()}",
            requested_at=datetime.now(timezone.utc),
        )
    )


def _run_turn(app: AgentOSApplication, session_id: str) -> None:
    task_id = app.surface_task_for_session(session_id)
    _begin_turn(app, session_id)

    def _done():
        events = [
            event
            for event in app.store.read(task_id)
            if event.event_type is TaskEventType.SESSION_TURN_COMPLETED
        ]
        return events or None

    _wait_for(_done, "turn completion")


def _chat_app(root: Path) -> AgentOSApplication:
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=_edit_script(), invocation_binding=app.provider.invocation_binding
    )
    app.provider_configured = True
    return app


def _set_mode(app: AgentOSApplication, session_id: str, mode: str) -> None:
    task_id = app.surface_task_for_session(session_id)
    app.surface.set_permission_mode(
        SurfaceSetPermissionModeCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            session_id=session_id,
            mode=mode,  # type: ignore[arg-type]
            expected_event_sequence=app.surface_current_sequence(task_id),
            idempotency_key=f"mode:{session_id}:{mode}:{time.monotonic_ns()}",
            requested_at=datetime.now(timezone.utc),
        )
    )


def _verdicts(app: AgentOSApplication, task_id: str) -> list[dict]:
    return [
        json.loads(event.payload_json)
        for event in app.store.read(task_id)
        if event.event_type is TaskEventType.POLICY_VERDICT_RECORDED
    ]


def _shell_script() -> tuple:
    return (
        (
            "",
            (_proposal("call-shell", "workspace.shell", {"command": "echo hi"}),),
        ),
        ("shell done", ()),
    )


def test_deny_rule_blocks_resolving_a_pending_approval(tmp_path: Path) -> None:
    from agent_os_contracts import ApprovalDisposition
    from agent_os_core import RunExecutionError

    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    app.provider = DeterministicProvider(
        scripted=_shell_script(), invocation_binding=app.provider.invocation_binding
    )
    app.provider_configured = True
    session, _loop = app.open_chat_session("hi", DeferredApprovalGateway())
    _set_mode(app, session.session_id, "ACCEPT_IN_WORKSPACE")
    _begin_turn(app, session.session_id)

    def _pending():
        projected = app.tasks.project_session(session.task_id, session.session_id)
        return projected.pending_continuation

    pending = _wait_for(_pending, "pending approval")
    assert pending is not None

    # The operator adds a DENY rule AFTER the action was escalated; resolving the
    # pending approval must now be refused (fail closed), not executed.
    app.permission_rule_store.save(_rule(capability_id="workspace.shell"))
    with pytest.raises(RunExecutionError):
        app.decide_session_approval(
            session.session_id,
            pending.action.action_digest(),
            ApprovalDisposition.APPROVE,
            "approved earlier",
        )
    rule_denials = [
        verdict
        for verdict in _verdicts(app, session.task_id)
        if verdict.get("basis") == "rule" and verdict.get("verdict") == "DENY"
    ]
    assert rule_denials and rule_denials[0]["rule_id"] == "rule-1"


def test_deny_rule_blocks_a_mode_auto_allowed_edit(tmp_path: Path) -> None:
    app = _chat_app(tmp_path)
    # Add the rule BEFORE the session loop is built, so it is consulted this turn.
    app.permission_rule_store.save(_rule(capability_id="workspace.edit"))
    session, _loop = app.open_chat_session("hi", DeferredApprovalGateway())
    _set_mode(app, session.session_id, "ACCEPT_IN_WORKSPACE")
    task_id = app.surface_task_for_session(session.session_id)
    _run_turn(app, session.session_id)

    rule_denials = [
        verdict
        for verdict in _verdicts(app, task_id)
        if verdict.get("basis") == "rule" and verdict.get("verdict") == "DENY"
    ]
    assert rule_denials, "expected a DENY-by-rule policy verdict"
    assert rule_denials[0]["rule_id"] == "rule-1"
    # No mode auto-allow for the edit this turn.
    assert not [
        verdict
        for verdict in _verdicts(app, task_id)
        if verdict.get("basis") == "permission_mode"
        and verdict.get("capability_id") == "workspace.edit"
    ]
