from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    Commitment,
    EdgeSpec,
    ExpectedOutcome,
    Goal,
    IdempotencyMode,
    MandateTaskLinkCommand,
    MandateTaskLinkRevocationCommand,
    NodeKind,
    NodeSpec,
    ObservedOutcome,
    OutcomePortfolio,
    OutcomePortfolioCreateCommand,
    HelpClass,
    OutcomePortfolioHelpGap,
    OutcomePortfolioHelpRequest,
    OutcomeStatus,
    PersistentCommitmentAttachCommand,
    PersistentCommitmentState,
    ResourceBudget,
    SettlementCommand,
    WorkflowGraph,
    content_digest,
)
from agent_os_core import (
    MandateOutcomePortfolioDenied,
    SQLiteMandateOutcomePortfolioStore,
    SQLiteMandateResponsibilityStore,
)
from tests.product.test_mandate_observation_authorization import NOW, _apps, _command
from tests.product.test_mandate_responsibility_store import _admin


def _budget() -> ResourceBudget:
    return ResourceBudget(
        max_cost_usd=Decimal("1.00"),
        max_duration_seconds=60,
        max_provider_tokens=100,
        max_tool_calls=10,
    )


def _workflow() -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id="workflow:portfolio",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="principal:owner",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(
            NodeSpec(
                node_id="inspect",
                kind=NodeKind.TOOL,
                capability="workspace.read",
                idempotency=IdempotencyMode.IDEMPOTENT,
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="inspect", target="done"),),
    )


def _portfolio_setup(tmp_path):
    database, owner, admin = _apps(tmp_path)
    admin.authorize_mandate_observation_binding(
        "mandate:build-agent-os", _command()
    )
    task = owner.create_task(
        Goal(
            goal_id="goal:portfolio",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            created_by="principal:owner",
            created_at=NOW,
            statement="Ship a portfolio settlement",
        ).model_dump(mode="json")
    )
    store = SQLiteMandateOutcomePortfolioStore(
        database,
        clock=lambda: NOW,
        task_reader=owner.tasks,
    )
    return database, owner, admin, task, store


def test_portfolio_contract_rejects_activation_true() -> None:
    with pytest.raises(ValidationError):
        OutcomePortfolio.model_validate(
            {
                "portfolio_id": "p1",
                "principal_id": "principal:owner",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "mandate_id": "mandate:build-agent-os",
                "desired_outcomes": ("Ship Agent OS",),
                "workspace_record_digest": "a" * 64,
                "operational_mandate_ref_digest": "b" * 64,
                "correction_epoch": 0,
                "created_by": "principal:security",
                "created_at": NOW,
                "command_digest": "c" * 64,
                "record_digest": "d" * 64,
                "task_activation_authorized": True,
            }
        )


def test_only_same_scope_admin_can_create_portfolio(tmp_path) -> None:
    _, owner, _, _, store = _portfolio_setup(tmp_path)
    command = OutcomePortfolioCreateCommand(reason="own outcomes")
    with pytest.raises(MandateOutcomePortfolioDenied, match="TENANT_ADMIN"):
        store.create_portfolio(command, "mandate:build-agent-os", owner.principal)
    with pytest.raises(MandateOutcomePortfolioDenied):
        store.create_portfolio(
            command,
            "mandate:build-agent-os",
            _admin(tenant_id="tenant:other"),
        )


def test_attach_rejects_task_without_active_mandate_link(tmp_path) -> None:
    _, owner, admin, task, store = _portfolio_setup(tmp_path)
    store.create_portfolio(
        OutcomePortfolioCreateCommand(),
        "mandate:build-agent-os",
        admin.principal,
    )
    commitment = Commitment(
        commitment_id="commitment:unlinked",
        task_id=task.task_id,
        goal_id="goal:portfolio",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        accepted_by="principal:owner",
        accepted_at=NOW,
        deliverables=("x",),
        acceptance_criteria=("y",),
        budget=_budget(),
        risk_tier=0,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(hours=2),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="expected:unlinked",
        task_id=task.task_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=3600,
        frozen_at=NOW,
    )
    owner.tasks.commit_task(task.task_id, commitment, _workflow(), expected)
    task = owner.tasks.get_task(task.task_id)
    with pytest.raises(MandateOutcomePortfolioDenied, match="MandateTaskLink"):
        store.attach_commitment(
            PersistentCommitmentAttachCommand(
                task_id=task.task_id,
                commitment_digest=content_digest(task.commitment),
                expected_outcome_digest=content_digest(task.expected_outcome),
            ),
            "mandate:build-agent-os",
            admin.principal,
        )


def test_create_attach_and_settle_not_met(tmp_path) -> None:
    database, owner, admin, task, store = _portfolio_setup(tmp_path)
    portfolio = store.create_portfolio(
        OutcomePortfolioCreateCommand(reason="track mandate outcomes"),
        "mandate:build-agent-os",
        admin.principal,
    )
    assert portfolio.task_activation_authorized is False
    assert portfolio.capability_grant_authorized is False
    assert portfolio.external_effects_authorized is False
    assert portfolio.desired_outcomes
    SQLiteMandateResponsibilityStore(database, clock=lambda: NOW).create_link(
        MandateTaskLinkCommand(task_id=task.task_id, reason="owned work"),
        "mandate:build-agent-os",
        admin.principal,
    )

    commitment = Commitment(
        commitment_id="commitment:portfolio",
        task_id=task.task_id,
        goal_id="goal:portfolio",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        accepted_by="principal:owner",
        accepted_at=NOW,
        deliverables=("settlement ledger",),
        acceptance_criteria=("tests pass",),
        budget=_budget(),
        risk_tier=0,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(hours=2),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="expected:portfolio",
        task_id=task.task_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=3600,
        frozen_at=NOW,
    )
    owner.tasks.commit_task(task.task_id, commitment, _workflow(), expected)
    running = owner.tasks.start_run(task.task_id)
    assert running.run is not None
    task = owner.tasks.get_task(task.task_id)
    attached = store.attach_commitment(
        PersistentCommitmentAttachCommand(
            task_id=task.task_id,
            commitment_digest=content_digest(task.commitment),
            expected_outcome_digest=content_digest(task.expected_outcome),
            reason="bind task",
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    assert attached.state is PersistentCommitmentState.OPEN

    observed = ObservedOutcome(
        observed_outcome_id="observed:portfolio",
        expected_outcome_id=expected.expected_outcome_id,
        task_id=task.task_id,
        run_id=running.run.run_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        status=OutcomeStatus.NOT_MET,
        score=0.0,
        confidence=1.0,
        evidence_refs=("test-report:1",),
        observed_at=NOW,
    )
    owner.tasks.record_outcome(task.task_id, observed)
    current = owner.tasks.current_outcome(task.task_id)
    assert current is not None
    settlement = store.settle(
        SettlementCommand(
            commitment_record_id=attached.commitment_record_id,
            expected_outcome_digest=content_digest(task.expected_outcome),
            observed_outcome_digest=content_digest(current),
            observed_status=OutcomeStatus.NOT_MET,
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    assert settlement.resulting_state is PersistentCommitmentState.SETTLED_NOT_MET
    view = store.get_view("mandate:build-agent-os", admin.principal)
    assert view.commitments[0].state is PersistentCommitmentState.SETTLED_NOT_MET


def test_invalid_outcome_cannot_settle_met(tmp_path) -> None:
    database, owner, admin, task, store = _portfolio_setup(tmp_path)
    store.create_portfolio(
        OutcomePortfolioCreateCommand(),
        "mandate:build-agent-os",
        admin.principal,
    )
    SQLiteMandateResponsibilityStore(database, clock=lambda: NOW).create_link(
        MandateTaskLinkCommand(task_id=task.task_id, reason="owned work"),
        "mandate:build-agent-os",
        admin.principal,
    )
    commitment = Commitment(
        commitment_id="commitment:invalid",
        task_id=task.task_id,
        goal_id="goal:portfolio",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        accepted_by="principal:owner",
        accepted_at=NOW,
        deliverables=("x",),
        acceptance_criteria=("y",),
        budget=_budget(),
        risk_tier=0,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(hours=2),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="expected:invalid",
        task_id=task.task_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=999.0,
        observation_window_seconds=3600,
        frozen_at=NOW,
    )
    owner.tasks.commit_task(task.task_id, commitment, _workflow(), expected)
    running = owner.tasks.start_run(task.task_id)
    assert running.run is not None
    task = owner.tasks.get_task(task.task_id)
    attached = store.attach_commitment(
        PersistentCommitmentAttachCommand(
            task_id=task.task_id,
            commitment_digest=content_digest(task.commitment),
            expected_outcome_digest=content_digest(task.expected_outcome),
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    observed = ObservedOutcome(
        observed_outcome_id="observed:unresolved",
        expected_outcome_id=expected.expected_outcome_id,
        task_id=task.task_id,
        run_id=running.run.run_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        status=OutcomeStatus.UNRESOLVED,
        score=None,
        confidence=0.0,
        evidence_refs=(),
        unresolved_gaps=("missing_evidence",),
        observed_at=NOW,
    )
    owner.tasks.record_outcome(task.task_id, observed)
    current = owner.tasks.current_outcome(task.task_id)
    settlement = store.settle(
        SettlementCommand(
            commitment_record_id=attached.commitment_record_id,
            expected_outcome_digest=content_digest(task.expected_outcome),
            observed_outcome_digest=content_digest(current),
            observed_status=OutcomeStatus.UNRESOLVED,
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    assert settlement.resulting_state is PersistentCommitmentState.INVALID
    assert settlement.resulting_state is not PersistentCommitmentState.SETTLED_MET


def test_help_request_rejects_activation_flags() -> None:
    srl = {
        "help_request_id": "help-request:test",
        "mandate_id": "mandate:build-agent-os",
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "standing_mission_id": "standing-mission:" + ("a" * 64),
        "help_class": HelpClass.INFORMATION.value,
        "unknowns": ("missing outcome",),
        "acquisition_attempts": ("checked ObservedOutcome",),
        "unsafe_boundary": "cannot invent missing truth",
        "minimum_answer": "provide ObservedOutcome",
        "continuable_work": ("inspect portfolio view",),
        "expires_at": (NOW + timedelta(hours=24)).isoformat(),
        "cancellation_policy": "superseded_by_resolved_gap",
        "escalation_policy": "mandate_admin",
        "requested_at": NOW.isoformat(),
    }
    base: dict[str, object] = {
        "portfolio_id": "outcome-portfolio:test",
        "gap_kind": OutcomePortfolioHelpGap.MISSING_OBSERVED_OUTCOME.value,
        "srl_help": srl,
    }
    for field in (
        "authority_granted",
        "external_effects_authorized",
        "task_activation_authorized",
        "capability_grant_authorized",
    ):
        payload = {**base, field: True}
        with pytest.raises(ValidationError):
            OutcomePortfolioHelpRequest.model_validate(payload)
    valid = OutcomePortfolioHelpRequest.model_validate(base)
    assert valid.srl_help.help_class is HelpClass.INFORMATION
    assert valid.authority_granted is False
    assert valid.external_effects_authorized is False
    assert valid.task_activation_authorized is False
    assert valid.capability_grant_authorized is False


def test_settle_without_observed_outcome_emits_help_request(tmp_path) -> None:
    database, owner, admin, task, store = _portfolio_setup(tmp_path)
    store.create_portfolio(
        OutcomePortfolioCreateCommand(reason="track outcomes"),
        "mandate:build-agent-os",
        admin.principal,
    )
    SQLiteMandateResponsibilityStore(database, clock=lambda: NOW).create_link(
        MandateTaskLinkCommand(task_id=task.task_id, reason="owned work"),
        "mandate:build-agent-os",
        admin.principal,
    )
    commitment = Commitment(
        commitment_id="commitment:no-outcome",
        task_id=task.task_id,
        goal_id="goal:portfolio",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        accepted_by="principal:owner",
        accepted_at=NOW,
        deliverables=("x",),
        acceptance_criteria=("y",),
        budget=_budget(),
        risk_tier=0,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(hours=2),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="expected:no-outcome",
        task_id=task.task_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=3600,
        frozen_at=NOW,
    )
    owner.tasks.commit_task(task.task_id, commitment, _workflow(), expected)
    owner.tasks.start_run(task.task_id)
    task = owner.tasks.get_task(task.task_id)
    attached = store.attach_commitment(
        PersistentCommitmentAttachCommand(
            task_id=task.task_id,
            commitment_digest=content_digest(task.commitment),
            expected_outcome_digest=content_digest(task.expected_outcome),
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    assert attached.state is PersistentCommitmentState.OPEN
    with pytest.raises(MandateOutcomePortfolioDenied, match="ObservedOutcome"):
        store.settle(
            SettlementCommand(
                commitment_record_id=attached.commitment_record_id,
                expected_outcome_digest=content_digest(task.expected_outcome),
                observed_outcome_digest="a" * 64,
                observed_status=OutcomeStatus.VERIFIED,
            ),
            "mandate:build-agent-os",
            admin.principal,
        )
    help_requests = store.list_help_requests("mandate:build-agent-os", admin.principal)
    assert len(help_requests) == 1
    assert help_requests[0].gap_kind is OutcomePortfolioHelpGap.MISSING_OBSERVED_OUTCOME
    assert help_requests[0].mandate_id == "mandate:build-agent-os"
    assert help_requests[0].task_id == task.task_id
    assert help_requests[0].authority_granted is False
    assert help_requests[0].srl_help.standing_mission_id != (
        "standing-mission:mandate:build-agent-os"
    )
    connection = __import__("sqlite3").connect(database)
    connection.row_factory = __import__("sqlite3").Row
    try:
        row = connection.execute(
            "SELECT record_json FROM mandate_workspace_records "
            "WHERE mandate_id = ? AND tenant_id = ? AND workspace_id = ?",
            ("mandate:build-agent-os", "tenant:local", "workspace:local"),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    from agent_os_contracts import MandateWorkspaceRecord

    workspace = MandateWorkspaceRecord.model_validate_json(str(row["record_json"]))
    assert (
        help_requests[0].srl_help.standing_mission_id
        == workspace.standing_mission.standing_mission_id
    )
    assert help_requests[0].srl_help.standing_mission_id == (
        f"standing-mission:{workspace.standing_mission.parent_mandate_digest}"
    )


def test_settle_after_link_revoke_emits_help_request(tmp_path) -> None:
    database, owner, admin, task, store = _portfolio_setup(tmp_path)
    store.create_portfolio(
        OutcomePortfolioCreateCommand(reason="track outcomes"),
        "mandate:build-agent-os",
        admin.principal,
    )
    responsibility = SQLiteMandateResponsibilityStore(
        database, clock=lambda: NOW
    )
    link = responsibility.create_link(
        MandateTaskLinkCommand(task_id=task.task_id, reason="owned work"),
        "mandate:build-agent-os",
        admin.principal,
    )
    commitment = Commitment(
        commitment_id="commitment:revoked-link",
        task_id=task.task_id,
        goal_id="goal:portfolio",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        accepted_by="principal:owner",
        accepted_at=NOW,
        deliverables=("x",),
        acceptance_criteria=("y",),
        budget=_budget(),
        risk_tier=0,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(hours=2),
    )
    expected_outcome = ExpectedOutcome(
        expected_outcome_id="expected:revoked-link",
        task_id=task.task_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=3600,
        frozen_at=NOW,
    )
    owner.tasks.commit_task(task.task_id, commitment, _workflow(), expected_outcome)
    running = owner.tasks.start_run(task.task_id)
    assert running.run is not None
    task = owner.tasks.get_task(task.task_id)
    attached = store.attach_commitment(
        PersistentCommitmentAttachCommand(
            task_id=task.task_id,
            commitment_digest=content_digest(task.commitment),
            expected_outcome_digest=content_digest(task.expected_outcome),
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    observed = ObservedOutcome(
        observed_outcome_id="observed:revoked-link",
        expected_outcome_id=expected_outcome.expected_outcome_id,
        task_id=task.task_id,
        run_id=running.run.run_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        status=OutcomeStatus.NOT_MET,
        score=0.0,
        confidence=1.0,
        evidence_refs=("test-report:1",),
        observed_at=NOW,
    )
    owner.tasks.record_outcome(task.task_id, observed)
    current = owner.tasks.current_outcome(task.task_id)
    assert current is not None
    responsibility.revoke_link(
        MandateTaskLinkRevocationCommand(
            expected_link_digest=link.record_digest,
            reason="revoke for test",
        ),
        "mandate:build-agent-os",
        link.link_id,
        admin.principal,
    )
    with pytest.raises(MandateOutcomePortfolioDenied, match="MandateTaskLink"):
        store.settle(
            SettlementCommand(
                commitment_record_id=attached.commitment_record_id,
                expected_outcome_digest=content_digest(task.expected_outcome),
                observed_outcome_digest=content_digest(current),
                observed_status=OutcomeStatus.NOT_MET,
            ),
            "mandate:build-agent-os",
            admin.principal,
        )
    help_requests = store.list_help_requests("mandate:build-agent-os", admin.principal)
    revoked_helps = [
        h for h in help_requests
        if h.gap_kind is OutcomePortfolioHelpGap.REVOKED_TASK_LINK
    ]
    assert len(revoked_helps) >= 1
    assert revoked_helps[0].task_id == task.task_id
    assert revoked_helps[0].authority_granted is False


def test_list_help_requests_requires_admin(tmp_path) -> None:
    database, owner, admin, task, store = _portfolio_setup(tmp_path)
    with pytest.raises(MandateOutcomePortfolioDenied):
        store.list_help_requests("mandate:build-agent-os", owner.principal)
    help_requests = store.list_help_requests("mandate:build-agent-os", admin.principal)
    assert help_requests == ()


def test_get_view_includes_help_requests(tmp_path) -> None:
    database, owner, admin, task, store = _portfolio_setup(tmp_path)
    store.create_portfolio(
        OutcomePortfolioCreateCommand(),
        "mandate:build-agent-os",
        admin.principal,
    )
    view = store.get_view("mandate:build-agent-os", admin.principal)
    assert view.help_requests == ()
    help_requests = store.list_help_requests("mandate:build-agent-os", admin.principal)
    assert help_requests == ()

    responsibility = SQLiteMandateResponsibilityStore(database, clock=lambda: NOW)
    responsibility.create_link(
        MandateTaskLinkCommand(task_id=task.task_id, reason="owned work"),
        "mandate:build-agent-os",
        admin.principal,
    )
    commitment = Commitment(
        commitment_id="commitment:view",
        task_id=task.task_id,
        goal_id="goal:portfolio",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        accepted_by="principal:owner",
        accepted_at=NOW,
        deliverables=("x",),
        acceptance_criteria=("y",),
        budget=_budget(),
        risk_tier=0,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(hours=2),
    )
    expected_outcome = ExpectedOutcome(
        expected_outcome_id="expected:view",
        task_id=task.task_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=3600,
        frozen_at=NOW,
    )
    owner.tasks.commit_task(task.task_id, commitment, _workflow(), expected_outcome)
    task = owner.tasks.get_task(task.task_id)
    attached = store.attach_commitment(
        PersistentCommitmentAttachCommand(
            task_id=task.task_id,
            commitment_digest=content_digest(task.commitment),
            expected_outcome_digest=content_digest(task.expected_outcome),
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    with pytest.raises(MandateOutcomePortfolioDenied, match="ObservedOutcome"):
        store.settle(
            SettlementCommand(
                commitment_record_id=attached.commitment_record_id,
                expected_outcome_digest=content_digest(task.expected_outcome),
                observed_outcome_digest="a" * 64,
                observed_status=OutcomeStatus.VERIFIED,
            ),
            "mandate:build-agent-os",
            admin.principal,
        )
    view = store.get_view("mandate:build-agent-os", admin.principal)
    assert len(view.help_requests) == 1
    assert view.help_requests[0].gap_kind is OutcomePortfolioHelpGap.MISSING_OBSERVED_OUTCOME


def test_attach_commitment_without_link_emits_help_request(tmp_path) -> None:
    database, owner, admin, task, store = _portfolio_setup(tmp_path)
    store.create_portfolio(
        OutcomePortfolioCreateCommand(),
        "mandate:build-agent-os",
        admin.principal,
    )
    commitment = Commitment(
        commitment_id="commitment:no-link",
        task_id=task.task_id,
        goal_id="goal:portfolio",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        accepted_by="principal:owner",
        accepted_at=NOW,
        deliverables=("x",),
        acceptance_criteria=("y",),
        budget=_budget(),
        risk_tier=0,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(hours=2),
    )
    expected_outcome = ExpectedOutcome(
        expected_outcome_id="expected:no-link",
        task_id=task.task_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=3600,
        frozen_at=NOW,
    )
    owner.tasks.commit_task(task.task_id, commitment, _workflow(), expected_outcome)
    task = owner.tasks.get_task(task.task_id)
    with pytest.raises(MandateOutcomePortfolioDenied, match="MandateTaskLink"):
        store.attach_commitment(
            PersistentCommitmentAttachCommand(
                task_id=task.task_id,
                commitment_digest=content_digest(task.commitment),
                expected_outcome_digest=content_digest(task.expected_outcome),
            ),
            "mandate:build-agent-os",
            admin.principal,
        )
    help_requests = store.list_help_requests("mandate:build-agent-os", admin.principal)
    assert len(help_requests) >= 1
    gap_kinds = {h.gap_kind for h in help_requests}
    assert OutcomePortfolioHelpGap.MISSING_TASK_LINK in gap_kinds


def test_admin_respond_operator_decision_closes_help_request(tmp_path) -> None:
    from agent_os_contracts import (
        OutcomePortfolioHelpRespondCommand,
        SrlHelpResponseKind,
    )

    database, owner, admin, task, store = _portfolio_setup(tmp_path)
    store.create_portfolio(
        OutcomePortfolioCreateCommand(),
        "mandate:build-agent-os",
        admin.principal,
    )
    SQLiteMandateResponsibilityStore(database, clock=lambda: NOW).create_link(
        MandateTaskLinkCommand(task_id=task.task_id, reason="owned work"),
        "mandate:build-agent-os",
        admin.principal,
    )
    commitment = Commitment(
        commitment_id="commitment:respond",
        task_id=task.task_id,
        goal_id="goal:portfolio",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        accepted_by="principal:owner",
        accepted_at=NOW,
        deliverables=("x",),
        acceptance_criteria=("y",),
        budget=_budget(),
        risk_tier=0,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(hours=2),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="expected:respond",
        task_id=task.task_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=3600,
        frozen_at=NOW,
    )
    owner.tasks.commit_task(task.task_id, commitment, _workflow(), expected)
    task = owner.tasks.get_task(task.task_id)
    attached = store.attach_commitment(
        PersistentCommitmentAttachCommand(
            task_id=task.task_id,
            commitment_digest=content_digest(task.commitment),
            expected_outcome_digest=content_digest(task.expected_outcome),
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    with pytest.raises(MandateOutcomePortfolioDenied, match="ObservedOutcome"):
        store.settle(
            SettlementCommand(
                commitment_record_id=attached.commitment_record_id,
                expected_outcome_digest=content_digest(task.expected_outcome),
                observed_outcome_digest="a" * 64,
                observed_status=OutcomeStatus.VERIFIED,
            ),
            "mandate:build-agent-os",
            admin.principal,
        )
    open_help = store.list_help_requests("mandate:build-agent-os", admin.principal)
    assert len(open_help) == 1
    responded = store.respond_help_request(
        OutcomePortfolioHelpRespondCommand(
            response_kind=SrlHelpResponseKind.OPERATOR_DECISION,
            decision="MORE_INFO",
            notes="need observed outcome digest",
        ),
        "mandate:build-agent-os",
        open_help[0].help_request_id,
        admin.principal,
    )
    assert responded.response is not None
    assert responded.response.response_kind is SrlHelpResponseKind.OPERATOR_DECISION
    assert responded.response.decision == "MORE_INFO"
    assert responded.authority_granted is False
    assert store.list_help_requests("mandate:build-agent-os", admin.principal) == ()
    resolved = store.list_help_requests(
        "mandate:build-agent-os",
        admin.principal,
        include_resolved=True,
    )
    assert len(resolved) == 1
    assert resolved[0].response is not None


def test_respond_capability_grant_fails_closed(tmp_path) -> None:
    from agent_os_contracts import (
        OutcomePortfolioHelpRespondCommand,
        SrlHelpResponseKind,
    )
    from agent_os_core import MandateOutcomePortfolioDenied as Denied

    database, owner, admin, task, store = _portfolio_setup(tmp_path)
    store.create_portfolio(
        OutcomePortfolioCreateCommand(),
        "mandate:build-agent-os",
        admin.principal,
    )
    SQLiteMandateResponsibilityStore(database, clock=lambda: NOW).create_link(
        MandateTaskLinkCommand(task_id=task.task_id, reason="owned work"),
        "mandate:build-agent-os",
        admin.principal,
    )
    commitment = Commitment(
        commitment_id="commitment:grant-deny",
        task_id=task.task_id,
        goal_id="goal:portfolio",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        accepted_by="principal:owner",
        accepted_at=NOW,
        deliverables=("x",),
        acceptance_criteria=("y",),
        budget=_budget(),
        risk_tier=0,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(hours=2),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="expected:grant-deny",
        task_id=task.task_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=3600,
        frozen_at=NOW,
    )
    owner.tasks.commit_task(task.task_id, commitment, _workflow(), expected)
    task = owner.tasks.get_task(task.task_id)
    attached = store.attach_commitment(
        PersistentCommitmentAttachCommand(
            task_id=task.task_id,
            commitment_digest=content_digest(task.commitment),
            expected_outcome_digest=content_digest(task.expected_outcome),
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    with pytest.raises(Denied, match="ObservedOutcome"):
        store.settle(
            SettlementCommand(
                commitment_record_id=attached.commitment_record_id,
                expected_outcome_digest=content_digest(task.expected_outcome),
                observed_outcome_digest="b" * 64,
                observed_status=OutcomeStatus.VERIFIED,
            ),
            "mandate:build-agent-os",
            admin.principal,
        )
    help_id = store.list_help_requests(
        "mandate:build-agent-os", admin.principal
    )[0].help_request_id
    with pytest.raises(Denied, match="cannot grant capability"):
        store.respond_help_request(
            OutcomePortfolioHelpRespondCommand(
                response_kind=SrlHelpResponseKind.CAPABILITY_GRANT,
            ),
            "mandate:build-agent-os",
            help_id,
            admin.principal,
        )
    assert len(store.list_help_requests("mandate:build-agent-os", admin.principal)) == 1


def test_successful_settle_auto_cancels_matching_open_help(tmp_path) -> None:
    from agent_os_contracts import SrlHelpResponseKind

    database, owner, admin, task, store = _portfolio_setup(tmp_path)
    store.create_portfolio(
        OutcomePortfolioCreateCommand(),
        "mandate:build-agent-os",
        admin.principal,
    )
    SQLiteMandateResponsibilityStore(database, clock=lambda: NOW).create_link(
        MandateTaskLinkCommand(task_id=task.task_id, reason="owned work"),
        "mandate:build-agent-os",
        admin.principal,
    )
    commitment = Commitment(
        commitment_id="commitment:auto-cancel",
        task_id=task.task_id,
        goal_id="goal:portfolio",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        accepted_by="principal:owner",
        accepted_at=NOW,
        deliverables=("x",),
        acceptance_criteria=("y",),
        budget=_budget(),
        risk_tier=0,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(hours=2),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="expected:auto-cancel",
        task_id=task.task_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=3600,
        frozen_at=NOW,
    )
    owner.tasks.commit_task(task.task_id, commitment, _workflow(), expected)
    running = owner.tasks.start_run(task.task_id)
    assert running.run is not None
    task = owner.tasks.get_task(task.task_id)
    attached = store.attach_commitment(
        PersistentCommitmentAttachCommand(
            task_id=task.task_id,
            commitment_digest=content_digest(task.commitment),
            expected_outcome_digest=content_digest(task.expected_outcome),
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    with pytest.raises(MandateOutcomePortfolioDenied, match="ObservedOutcome"):
        store.settle(
            SettlementCommand(
                commitment_record_id=attached.commitment_record_id,
                expected_outcome_digest=content_digest(task.expected_outcome),
                observed_outcome_digest="c" * 64,
                observed_status=OutcomeStatus.VERIFIED,
            ),
            "mandate:build-agent-os",
            admin.principal,
        )
    assert len(store.list_help_requests("mandate:build-agent-os", admin.principal)) == 1
    observed = ObservedOutcome(
        observed_outcome_id="observed:auto-cancel",
        expected_outcome_id=expected.expected_outcome_id,
        task_id=task.task_id,
        run_id=running.run.run_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        status=OutcomeStatus.NOT_MET,
        score=0.0,
        confidence=1.0,
        evidence_refs=("test-report:1",),
        observed_at=NOW,
    )
    owner.tasks.record_outcome(task.task_id, observed)
    current = owner.tasks.current_outcome(task.task_id)
    assert current is not None
    settlement = store.settle(
        SettlementCommand(
            commitment_record_id=attached.commitment_record_id,
            expected_outcome_digest=content_digest(task.expected_outcome),
            observed_outcome_digest=content_digest(current),
            observed_status=OutcomeStatus.NOT_MET,
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    assert settlement.resulting_state is PersistentCommitmentState.SETTLED_NOT_MET
    assert store.list_help_requests("mandate:build-agent-os", admin.principal) == ()
    resolved = store.list_help_requests(
        "mandate:build-agent-os",
        admin.principal,
        include_resolved=True,
    )
    assert len(resolved) == 1
    assert resolved[0].response is not None
    assert resolved[0].response.response_kind is SrlHelpResponseKind.CANCELLATION
