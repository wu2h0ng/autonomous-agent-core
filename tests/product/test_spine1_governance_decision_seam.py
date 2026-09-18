"""SPINE-1 batch 6: governed-decision seam contract + experimentation loop.

The seam contract lives in core packages/contracts (generic, versioned RPC schema); the
experimentation loop lives in the domain pack and consumes it.
"""

from __future__ import annotations

from agent_os_contracts import (
    ALLOW,
    DENY,
    SEAM_CONTRACT_VERSION,
    GovernanceDecisionRequest,
    GovernanceDecisionResponse,
    VerifiedCandidate,
    request_from_json,
    request_to_json,
    response_from_json,
    response_to_json,
)
from domain_packs.data_agent.experimentation import ActiveExperimentationLoop, ExperimentLedger


def test_request_json_roundtrip_preserves_verified_candidates() -> None:
    request = GovernanceDecisionRequest(
        task_id="task-1",
        risk_tier="R3",
        candidate_actions=("notify", "do_nothing"),
        evidence_count=5,
        approved=True,
        verified_candidates=(
            VerifiedCandidate(action="notify", verified=True, confidence=0.7, evidence_count=5),
        ),
    )

    restored = request_from_json(request_to_json(request))

    assert restored == request
    assert restored.verified_candidates[0].action == "notify"
    assert restored.contract_version == SEAM_CONTRACT_VERSION


def test_response_json_roundtrip() -> None:
    response = GovernanceDecisionResponse(
        task_id="task-1",
        verdict=DENY,
        chosen_action=None,
        confidence=0.2,
        reason="insufficient evidence",
        audit_ref="audit:1",
    )

    assert response_from_json(response_to_json(response)) == response


class _Event:
    def __init__(self, step: str, payload: dict) -> None:
        self.step = step
        self.payload = payload


class _Result:
    def __init__(self, events: list[_Event]) -> None:
        self.trace_events = events


class _Runtime:
    def __init__(self, result: _Result) -> None:
        self._result = result

    def run(self, question: str, parameters: dict) -> _Result:
        return self._result


def test_experimentation_records_only_allow_confirmed_driver() -> None:
    result = _Result(
        [_Event("governed_decision", {"verdict": ALLOW, "chosen_action": "notify"})]
    )
    ledger = ExperimentLedger()

    round_result = ActiveExperimentationLoop(runtime=_Runtime(result), ledger=ledger).run_round(
        "why did gmv drop", {}
    )

    assert round_result.chosen_action == "notify"
    assert ledger.resolved() == {"notify"}


def test_experimentation_records_nothing_without_allow() -> None:
    result = _Result([_Event("governed_decision", {"verdict": DENY, "chosen_action": "notify"})])
    ledger = ExperimentLedger()

    round_result = ActiveExperimentationLoop(runtime=_Runtime(result), ledger=ledger).run_round(
        "why did gmv drop", {}
    )

    assert round_result.chosen_action is None
    assert ledger.resolved() == set()
