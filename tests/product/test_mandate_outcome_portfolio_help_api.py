from __future__ import annotations

from datetime import timedelta

import pytest

from agent_os_contracts import (
    Commitment,
    ExpectedOutcome,
    MandateTaskLinkCommand,
    OutcomePortfolioCreateCommand,
    OutcomeStatus,
    PersistentCommitmentAttachCommand,
    SettlementCommand,
    content_digest,
)
from agent_os_core import (
    MandateOutcomePortfolioDenied,
    SQLiteMandateResponsibilityStore,
)
from tests.product.test_mandate_observation_authorization import NOW
from tests.product.test_mandate_outcome_portfolio import (
    _budget,
    _portfolio_setup,
    _workflow,
)
from tests.product.test_mandate_responsibility_api import _request, _server


MANDATE_ID = "mandate:build-agent-os"
ADMIN_TOKEN = "portfolio-help-admin"
OWNER_TOKEN = "portfolio-help-owner"


def _help_path() -> str:
    return f"/v1/mandates/{MANDATE_ID}/outcome-portfolio/help-requests"


def _view_path() -> str:
    return f"/v1/mandates/{MANDATE_ID}/outcome-portfolio"


def _setup_with_help_request(tmp_path):
    database, owner, admin, task, store = _portfolio_setup(tmp_path)
    store.create_portfolio(
        OutcomePortfolioCreateCommand(),
        MANDATE_ID,
        admin.principal,
    )
    responsibility = SQLiteMandateResponsibilityStore(database, clock=lambda: NOW)
    responsibility.create_link(
        MandateTaskLinkCommand(task_id=task.task_id, reason="owned work"),
        MANDATE_ID,
        admin.principal,
    )
    commitment = Commitment(
        commitment_id="commitment:help-http",
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
        expected_outcome_id="expected:help-http",
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
    commitment_truth = task.commitment
    expected_truth = task.expected_outcome
    assert commitment_truth is not None
    assert expected_truth is not None
    attached = store.attach_commitment(
        PersistentCommitmentAttachCommand(
            task_id=task.task_id,
            commitment_digest=content_digest(commitment_truth),
            expected_outcome_digest=content_digest(expected_truth),
        ),
        MANDATE_ID,
        admin.principal,
    )
    with pytest.raises(MandateOutcomePortfolioDenied, match="ObservedOutcome"):
        store.settle(
            SettlementCommand(
                commitment_record_id=attached.commitment_record_id,
                expected_outcome_digest=content_digest(expected_truth),
                observed_outcome_digest="a" * 64,
                observed_status=OutcomeStatus.VERIFIED,
            ),
            MANDATE_ID,
            admin.principal,
        )
    return database, owner, admin, task, store


def test_get_view_excludes_help_requests_for_non_admin_reader(tmp_path) -> None:
    _, owner, admin, _, store = _setup_with_help_request(tmp_path)

    admin_view = store.get_view(MANDATE_ID, admin.principal)
    assert len(admin_view.help_requests) == 1

    owner_view = store.get_view(MANDATE_ID, owner.principal)
    assert owner_view.help_requests == ()
    assert owner_view.portfolio == admin_view.portfolio
    assert owner_view.commitments == admin_view.commitments
    assert owner_view.settlements == admin_view.settlements


def test_admin_lists_help_requests_over_http(tmp_path) -> None:
    _, owner, admin, task, _ = _setup_with_help_request(tmp_path)

    with _server(owner, {ADMIN_TOKEN: admin}) as base:
        status, payload, headers = _request(base, _help_path(), token=ADMIN_TOKEN)

    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    items = payload["help_requests"]
    assert isinstance(items, list)
    assert len(items) == 1
    assert items[0]["gap_kind"] == "MISSING_OBSERVED_OUTCOME"
    assert items[0]["task_id"] == task.task_id
    assert items[0]["srl_help"]["mandate_id"] == MANDATE_ID
    assert items[0]["authority_granted"] is False
    assert items[0]["task_activation_authorized"] is False
    assert items[0]["capability_grant_authorized"] is False
    assert items[0]["external_effects_authorized"] is False


def test_help_requests_route_requires_authenticated_admin(tmp_path) -> None:
    _, owner, admin, _, _ = _setup_with_help_request(tmp_path)

    with _server(owner, {ADMIN_TOKEN: admin, OWNER_TOKEN: owner}) as base:
        missing_status, missing, _ = _request(base, _help_path())
        invalid_status, invalid, _ = _request(base, _help_path(), token="invalid")
        owner_status, owner_error, _ = _request(
            base, _help_path(), token=OWNER_TOKEN
        )

    assert (missing_status, invalid_status) == (401, 401)
    assert missing["error"] == "admin_authentication_required"
    assert invalid["error"] == "admin_authentication_failed"
    assert owner_status == 403
    assert owner_error["error"] == "MandateOutcomePortfolioDenied"


def test_non_admin_http_view_does_not_leak_help_requests(tmp_path) -> None:
    _, owner, admin, _, _ = _setup_with_help_request(tmp_path)

    with _server(owner, {ADMIN_TOKEN: admin}) as base:
        list_status, listed, _ = _request(base, _help_path(), token=ADMIN_TOKEN)
        owner_status, owner_view, _ = _request(base, _view_path())
        admin_status, admin_view, _ = _request(base, _view_path(), token=ADMIN_TOKEN)

    assert (list_status, owner_status, admin_status) == (200, 200, 200)
    listed_items = listed["help_requests"]
    assert isinstance(listed_items, list)
    assert len(listed_items) == 1
    assert owner_view["help_requests"] == []
    assert admin_view["help_requests"] == listed_items
    owner_portfolio = owner_view["portfolio"]
    assert isinstance(owner_portfolio, dict)
    assert owner_portfolio["task_activation_authorized"] is False
    assert owner_portfolio["capability_grant_authorized"] is False
    assert owner_portfolio["external_effects_authorized"] is False


def test_admin_responds_to_help_request_over_http(tmp_path) -> None:
    import urllib.parse

    _, owner, admin, task, store = _setup_with_help_request(tmp_path)
    open_help = store.list_help_requests(MANDATE_ID, admin.principal)
    assert len(open_help) == 1
    help_id = open_help[0].help_request_id
    path = (
        f"/v1/mandates/{MANDATE_ID}/outcome-portfolio/help-requests/"
        f"{urllib.parse.quote(help_id, safe='')}:respond"
    )
    with _server(owner, {ADMIN_TOKEN: admin, OWNER_TOKEN: owner}) as base:
        owner_status, owner_err, _ = _request(
            base,
            path,
            method="POST",
            body={"response_kind": "CANCELLATION", "notes": "gap fixed"},
            token=OWNER_TOKEN,
        )
        status, payload, _ = _request(
            base,
            path,
            method="POST",
            body={"response_kind": "CANCELLATION", "notes": "gap fixed"},
            token=ADMIN_TOKEN,
        )
        listed_status, listed, _ = _request(base, _help_path(), token=ADMIN_TOKEN)
        resolved_status, resolved, _ = _request(
            base,
            _help_path() + "?include_resolved=true",
            token=ADMIN_TOKEN,
        )

    assert owner_status == 403
    assert owner_err["error"] == "MandateOutcomePortfolioDenied"
    assert status == 201
    assert payload["response"]["response_kind"] == "CANCELLATION"
    assert payload["authority_granted"] is False
    assert payload["task_activation_authorized"] is False
    assert payload["capability_grant_authorized"] is False
    assert payload["external_effects_authorized"] is False
    assert listed_status == 200
    assert resolved_status == 200
    assert listed["help_requests"] == []
    assert len(resolved["help_requests"]) == 1
    assert resolved["help_requests"][0]["task_id"] == task.task_id


def test_http_respond_rejects_capability_grant(tmp_path) -> None:
    import urllib.parse

    _, owner, admin, _, store = _setup_with_help_request(tmp_path)
    help_id = store.list_help_requests(MANDATE_ID, admin.principal)[0].help_request_id
    path = (
        f"/v1/mandates/{MANDATE_ID}/outcome-portfolio/help-requests/"
        f"{urllib.parse.quote(help_id, safe='')}:respond"
    )
    with _server(owner, {ADMIN_TOKEN: admin}) as base:
        status, payload, _ = _request(
            base,
            path,
            method="POST",
            body={"response_kind": "CAPABILITY_GRANT"},
            token=ADMIN_TOKEN,
        )

    assert status == 403
    assert payload["error"] == "MandateOutcomePortfolioDenied"
