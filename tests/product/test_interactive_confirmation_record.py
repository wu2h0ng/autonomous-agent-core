"""The interactive confirmation is an authority decision: it must be durable.

Why this exists: the governance spine requires that a consequential action's
authority be reconstructable from durable evidence after the fact. A refusal on
the confirmation path was recorded (``_record_denial`` writes an
``ApprovalDecision`` with disposition ``REJECT``) while the *confirmation*
wrote nothing at all: policy admitted a tier<3 action without needing an
``ApprovalDecision``, so the admitted effect carried only a policy decision
whose ``approval_id`` named no decision. The confirmation of a tier<3 action —
and, worse, the authorization of a tier>=3 action — was therefore not
answerable from the stream: not "who authorized this effect", not "when", and
no digest-bound ``APPROVE`` for a safety projection to find.

These tests pin the record itself (shape, binding, ordering before the effect)
and the eval-visible consequence (a successful governed task no longer reports
zero approval events when a confirmation occurred).
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from agent_os_contracts import (
    ActionContract,
    ApprovalDecision,
    ApprovalDisposition,
    PrincipalRole,
    ProviderToolProposal,
    TaskEventType,
)
from agent_os_core import AutoApproveGateway, DeterministicProvider, InvalidTransitionError
from agent_os_core.agent_loop import UNIDENTIFIED_GATEWAY_AUTHORITY, gateway_authority_id
from apps.api_server.app import AgentOSApplication


class _DenyAllGateway:
    authority_id = "gateway:test-deny-all"

    def confirm(self, action, preview) -> bool:
        return False


class _ApproveAllGateway:
    """A test-support gateway that also confirms tier>=3 actions."""

    authority_id = "gateway:test-approve-all"

    def confirm(self, action, preview) -> bool:
        return True


class _AnonymousGateway:
    """A gateway that declares no authority identity (third-party shape)."""

    def confirm(self, action, preview) -> bool:
        return True


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
                    {
                        "path": "fixture.txt",
                        "old_string": "stable\n",
                        "new_string": "fixed\n",
                    },
                ),
            ),
        ),
        ("fixed complete", ()),
    )


def _confirmation_app(tmp_path: Path, gateway) -> tuple[AgentOSApplication, str]:
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    app.provider = DeterministicProvider(
        scripted=_edit_script(),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    session, loop = app.open_chat_session("fix the fixture", gateway)
    result = loop.run_turn(session, "fix the fixture")
    assert result.stop_reason == "completed"
    return app, session.task_id


def _events(app: AgentOSApplication, task_id: str) -> list:
    return list(app.tasks._event_store.read(task_id))


def _as_mapping(event) -> dict:
    return {
        "event_type": str(getattr(event.event_type, "value", event.event_type)),
        "sequence": event.sequence,
        "occurred_at": str(event.occurred_at),
        "payload": event.decoded_payload(),
    }


def test_tier2_confirmation_is_recorded_as_a_durable_approval(tmp_path: Path) -> None:
    app, task_id = _confirmation_app(tmp_path, AutoApproveGateway())
    events = _events(app, task_id)

    approvals = [
        event for event in events if event.event_type is TaskEventType.APPROVAL_RECORDED
    ]
    assert len(approvals) == 1
    recorded = ApprovalDecision.model_validate(
        approvals[0].decoded_payload()["approval"]
    )
    assert recorded.disposition is ApprovalDisposition.APPROVE
    assert recorded.actor_id == app.principal.principal_id
    assert recorded.actor_role is app.principal.role
    assert recorded.reason == "confirmation approved by gateway:auto-approve"
    assert recorded.expires_at > recorded.decided_at

    proposed = [
        event for event in events if event.event_type is TaskEventType.ACTION_PROPOSED
    ]
    assert len(proposed) == 1
    action = ActionContract.model_validate(proposed[0].decoded_payload()["action"])
    assert recorded.action_digest == action.action_digest()

    receipts = [
        event
        for event in events
        if event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
    ]
    assert len(receipts) == 1
    # Authority precedes the effect it authorizes: a record written after the
    # receipt would answer nothing about who authorized the dispatch.
    assert approvals[0].sequence < receipts[0].sequence
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "fixed\n"


def test_confirmation_is_visible_to_the_eval_approval_projection(tmp_path: Path) -> None:
    """The eval-visible consequence: a confirmed task is not an approvals=0 task."""
    from product_evals.terminal_agent_eval.metrics import (
        count_approvals,
        count_unsafe_actions,
    )

    app, task_id = _confirmation_app(tmp_path, AutoApproveGateway())
    projection = [_as_mapping(event) for event in _events(app, task_id)]

    assert count_approvals(projection) == 1
    assert count_unsafe_actions(projection) == 0


def test_tier3_confirmation_is_recorded_before_its_receipt(tmp_path: Path) -> None:
    """An approved tier>=3 action must not project as an unsafe action.

    Before the record existed this is exactly what happened: a tier>=3 action
    was authorized by an in-memory approval, dispatched, and then counted
    unsafe because no digest-bound APPROVE preceded its receipt.
    """
    from product_evals.terminal_agent_eval.metrics import (
        count_approvals,
        count_unsafe_actions,
    )

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=False)
    app = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        trusted_shell_profile=True,
    )
    app.provider = DeterministicProvider(
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-shell", "workspace.shell", {"command": "git status"}
                    ),
                ),
            ),
            ("shell done", ()),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    session, loop = app.open_chat_session("run a shell command", _ApproveAllGateway())
    loop.run_turn(session, "run git status")

    events = _events(app, session.task_id)
    receipts = [
        event
        for event in events
        if event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
    ]
    assert receipts, "the tier>=3 action was never dispatched"
    approvals = [
        event for event in events if event.event_type is TaskEventType.APPROVAL_RECORDED
    ]
    assert len(approvals) == 1
    assert approvals[0].sequence < receipts[0].sequence
    recorded = ApprovalDecision.model_validate(
        approvals[0].decoded_payload()["approval"]
    )
    assert recorded.disposition is ApprovalDisposition.APPROVE
    assert recorded.reason == "confirmation approved by gateway:test-approve-all"

    projection = [_as_mapping(event) for event in events]
    assert count_approvals(projection) == 1
    assert count_unsafe_actions(projection) == 0


def test_denied_confirmation_records_only_the_refusal(tmp_path: Path) -> None:
    """The record must not manufacture an APPROVE alongside a refusal."""
    app, task_id = _confirmation_app(tmp_path, _DenyAllGateway())
    approvals = [
        event
        for event in _events(app, task_id)
        if event.event_type is TaskEventType.APPROVAL_RECORDED
    ]
    assert len(approvals) == 1
    recorded = ApprovalDecision.model_validate(
        approvals[0].decoded_payload()["approval"]
    )
    assert recorded.disposition is ApprovalDisposition.REJECT
    assert recorded.reason == "confirmation denied by gateway:test-deny-all"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


def test_gateway_without_a_declared_authority_is_never_recorded_as_the_operator(
    tmp_path: Path,
) -> None:
    """An undeclared authority is recorded as unidentified, not as a human."""
    app, task_id = _confirmation_app(tmp_path, _AnonymousGateway())
    approvals = [
        event
        for event in _events(app, task_id)
        if event.event_type is TaskEventType.APPROVAL_RECORDED
    ]
    assert len(approvals) == 1
    recorded = ApprovalDecision.model_validate(
        approvals[0].decoded_payload()["approval"]
    )
    assert recorded.reason == "confirmation approved by gateway:unidentified"
    assert gateway_authority_id(object()) == UNIDENTIFIED_GATEWAY_AUTHORITY
    assert gateway_authority_id(AutoApproveGateway()) == "gateway:auto-approve"


def test_confirmation_that_does_not_bind_the_action_fails_closed(tmp_path: Path) -> None:
    """The failure path: an unbound confirmation raises and writes nothing."""
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    app.provider = DeterministicProvider(
        scripted=_edit_script(),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    session, loop = app.open_chat_session("fix the fixture", AutoApproveGateway())
    action = loop._actions.build_action(
        task_id=session.task_id,
        run_id=session.run_id,
        node_id="unbound",
        capability_id="workspace.edit",
        principal=app.principal,
        args={"path": "fixture.txt", "old_string": "stable", "new_string": "fixed"},
        expected=session.expected,
        envelope_id=session.envelope_id,
        risk_tier=2,
    )
    now = datetime.now(action.created_at.tzinfo)
    foreign = ApprovalDecision(
        approval_id="approval-foreign",
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        action_digest="0" * 64,
        actor_id=app.principal.principal_id,
        actor_role=PrincipalRole.PRINCIPAL,
        disposition=ApprovalDisposition.APPROVE,
        reason="confirmation approved by gateway:auto-approve",
        decided_at=now,
        expires_at=now.replace(year=now.year + 1),
    )
    with pytest.raises(InvalidTransitionError):
        loop._record_confirmation(session, action, foreign)
    assert not [
        event
        for event in _events(app, session.task_id)
        if event.event_type is TaskEventType.APPROVAL_RECORDED
    ]
