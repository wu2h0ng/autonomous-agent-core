from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import RelevanceDisposition, content_digest
from agent_os_core import DeterministicProvider
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore
from product_evals.srl_e2e_falsifier.contracts import (
    CandidateKind,
    DecisionCandidate,
    PublicContentManifest,
    PublicContentManifestEntry,
    PublicContentMediaType,
    PublicContentRole,
    PublicResponsibilityState,
    PublicResponsibilityStateVerifier,
    StaticBudgetConfiguration,
    decision_candidate_digest,
    public_content_entry_digest,
    public_content_manifest_digest,
    static_budget_configuration_bytes,
    static_budget_configuration_digest,
)
from product_evals.srl_e2e_falsifier.harness import (
    ArmId,
    ArmMetrics,
    BlindedDecision,
    BudgetUsage,
    FrozenEvaluationUnit,
    HiddenScore,
    HiddenScorerPort,
    MatchedBudgetLedger,
    OperatorBurden,
    SrlE2EFalsifierHarness,
    SituatedStewardController,
)
from tests.product._steward_app import admitted_application
from tests.product.test_provider_relevance_assessor import (
    NOW,
    _assessor,
    _draft,
    _event,
    _invocation,
    _mandate,
    _projection,
    _trust,
)


def _entry(role: PublicContentRole, raw: bytes) -> PublicContentManifestEntry:
    payload: dict[str, Any] = {
        "role": role,
        "media_type": PublicContentMediaType.APPLICATION_JSON,
        "content_digest": hashlib.sha256(raw).hexdigest(),
    }
    payload["entry_digest"] = public_content_entry_digest(payload)
    return PublicContentManifestEntry.model_validate(payload)


def _public_state() -> tuple[PublicResponsibilityState, StaticBudgetConfiguration]:
    budget_payload = {
        "max_llm_calls": 2,
        "max_input_tokens": 1000,
        "max_output_tokens": 500,
        "max_retries": 1,
        "max_tool_invocations": 4,
        "max_wall_seconds": 60,
    }
    budget = StaticBudgetConfiguration.model_validate(
        {
            **budget_payload,
            "configuration_digest": static_budget_configuration_digest(
                budget_payload
            ),
        }
    )
    raws = (
        b'{"mission":"keep quality green"}',
        b'{"event":"quality gate failed"}',
        b'{"projection":"commitment at risk"}',
        b'{"evidence":"typed receipt"}',
        static_budget_configuration_bytes(budget),
    )
    roles = (
        PublicContentRole.MISSION,
        PublicContentRole.EVENT,
        PublicContentRole.PROJECTION,
        PublicContentRole.EVIDENCE,
        PublicContentRole.STATIC_BUDGET,
    )
    entries = tuple(_entry(role, raw) for role, raw in zip(roles, raws, strict=True))
    manifest_payload: dict[str, Any] = {"entries": entries}
    manifest_payload["manifest_root_digest"] = public_content_manifest_digest(
        manifest_payload
    )
    manifest = PublicContentManifest.model_validate(manifest_payload)
    contents = {
        entry.entry_digest: raw for entry, raw in zip(entries, raws, strict=True)
    }
    state = PublicResponsibilityStateVerifier.build(
        manifest=manifest,
        content_by_entry_digest=contents,
        static_budget_configuration=budget,
        mandate_digest="a" * 64,
        environment_binding_digest="b" * 64,
        correction_epoch=0,
        mission_entry_digest=entries[0].entry_digest,
        event_entry_digests=(entries[1].entry_digest,),
        projection_entry_digests=(entries[2].entry_digest,),
        evidence_entry_digests=(entries[3].entry_digest,),
        static_budget_entry_digest=entries[4].entry_digest,
    )
    return state, budget


def _candidate(
    state: PublicResponsibilityState, *, candidate_id: str
) -> DecisionCandidate:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "candidate_id": candidate_id,
        "candidate_kind": CandidateKind.NONE,
        "public_state_digest": state.state_digest,
        "no_external_effect": True,
        "desired_outcome": None,
        "acceptance_criteria": (),
        "missing_input_kind": None,
        "minimum_question": None,
        "created_at": "2026-07-17T00:00:00Z",
    }
    payload["candidate_digest"] = decision_candidate_digest(payload)
    return DecisionCandidate.model_validate(payload)


class _Controller:
    def __init__(self, candidate: DecisionCandidate, usage: BudgetUsage) -> None:
        self.candidate = candidate
        self.usage = usage

    def decide(self, unit: FrozenEvaluationUnit) -> tuple[DecisionCandidate, BudgetUsage]:
        assert unit.public_state.state_digest == self.candidate.public_state_digest
        return self.candidate, self.usage


class _Scorer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.decisions: list[BlindedDecision] = []

    def score(
        self,
        *,
        decision: BlindedDecision,
        sealed_slot_tokens: tuple[str, ...],
    ) -> HiddenScore:
        self.calls.append((decision.slot_token, sealed_slot_tokens))
        self.decisions.append(decision)
        return HiddenScore(
            decision_ok=True,
            false_work=False,
            missed_critical=False,
            mandatory_help_ok=True,
            executor_ok=False,
            severe_safety_violation=False,
        )


def _real_srl_controller(
    tmp_path: Path,
) -> tuple[SituatedStewardController, FrozenEvaluationUnit, DeterministicProvider]:
    state, budget = _public_state()
    event = _event()
    projection = _projection()
    mandate = _mandate()
    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.CREATE_TASK),
        invocation_binding=_invocation(),
    )
    assessor = _assessor(provider)
    trust = _trust()
    control = SQLiteSituatedAssessmentStore(
        tmp_path / "control.sqlite3", mandates=(mandate,)
    )
    app, receipt = admitted_application(
        database=tmp_path / "runtime.sqlite3",
        workspace=tmp_path / "workspace",
        trust=trust,
        control=control,
        event_id=event.environment_event_id,
        projection_id=projection.projection_id,
        clock=lambda: NOW,
        assessor=assessor,
    )
    unit = FrozenEvaluationUnit(
        unit_id="unit-real-srl",
        public_state=state,
        budget=budget,
        event_id=event.environment_event_id,
        projection_id=projection.projection_id,
        admission_receipt_id=receipt.receipt_id,
    )
    return (
        SituatedStewardController(
            application=app,
            usage=BudgetUsage(llm_calls=1, wall_seconds=1),
        ),
        unit,
        provider,
    )


def test_harness_seals_three_matched_arms_before_hidden_scoring(
    tmp_path: Path,
) -> None:
    srl, unit, provider = _real_srl_controller(tmp_path)
    state = unit.public_state
    budget = unit.budget
    usage = BudgetUsage(
        llm_calls=1,
        input_tokens=20,
        output_tokens=10,
        retries=0,
        tool_invocations=1,
        wall_seconds=1,
        provider_cost_microunits=10,
    )
    candidates = {
        ArmId.DIRECT: _candidate(state, candidate_id="ARM-DIRECT-LEAK"),
        ArmId.WORKFLOW: _candidate(state, candidate_id="ARM-WORKFLOW-LEAK"),
        ArmId.SRL: _candidate(state, candidate_id="ARM-SRL-LEAK"),
    }
    scorer = _Scorer()
    harness = SrlE2EFalsifierHarness(
        controllers={
            ArmId.DIRECT: _Controller(candidates[ArmId.DIRECT], usage),
            ArmId.WORKFLOW: _Controller(candidates[ArmId.WORKFLOW], usage),
            ArmId.SRL: srl,
        },
        hidden_scorer=scorer,
        budget_ledger=MatchedBudgetLedger(),
        blinding_nonce_digest="c" * 64,
    )

    report = harness.evaluate_unit(
        unit,
        burdens={
            arm: OperatorBurden(
                hcw_minutes=1.0,
                auth_minutes=0.0,
                help_minutes=0.0,
                help_count=0,
                latency_ms=100,
            )
            for arm in ArmId
        },
    )

    assert set(report.metrics) == set(ArmId)
    assert all(isinstance(metric, ArmMetrics) for metric in report.metrics.values())
    sealed_tokens = tuple(sorted(call[0] for call in scorer.calls))
    assert tuple(call[0] for call in scorer.calls) == sealed_tokens
    assert all(call[1] == sealed_tokens for call in scorer.calls)
    assert not any(
        isinstance(value, ArmId)
        for call in scorer.calls
        for group in call
        for value in (group if isinstance(group, tuple) else (group,))
    )
    assert "arm_id" not in inspect.signature(HiddenScorerPort.score).parameters
    assert "sealed_arm_ids" not in inspect.signature(HiddenScorerPort.score).parameters
    for decision in scorer.decisions:
        assert not hasattr(decision.normalized, "candidate_id")
        assert not hasattr(decision.normalized, "candidate_digest")
        assert not hasattr(decision.normalized, "created_at")
        assert "ARM-DIRECT-LEAK" not in repr(decision)
        assert "ARM-WORKFLOW-LEAK" not in repr(decision)
        assert "ARM-SRL-LEAK" not in repr(decision)
    assert all(
        report.metrics[arm].budget_configuration_digest
        == budget.configuration_digest
        for arm in ArmId
    )
    assert len(provider.decision_requests) == 1


def test_harness_rejects_fake_srl_controller_and_budget_overrun() -> None:
    state, budget = _public_state()
    unit = FrozenEvaluationUnit(
        unit_id="unit-1",
        public_state=state,
        budget=budget,
        event_id="event-1",
        projection_id="projection-1",
        admission_receipt_id="receipt-1",
    )
    candidate = _candidate(state, candidate_id="candidate-1")
    normal = _Controller(candidate, BudgetUsage())
    with pytest.raises(TypeError, match="real SituatedStewardController"):
        SrlE2EFalsifierHarness(
            controllers={arm: normal for arm in ArmId},
            hidden_scorer=_Scorer(),
            budget_ledger=MatchedBudgetLedger(),
            blinding_nonce_digest="c" * 64,
        )

    ledger = MatchedBudgetLedger()
    with pytest.raises(ValueError, match="budget exceeded"):
        ledger.seal(
            arm_id=ArmId.DIRECT,
            unit=unit,
            usage=BudgetUsage(llm_calls=budget.max_llm_calls + 1),
        )


def test_srl_arm_calls_real_admission_required_mandate_steward(
    tmp_path: Path,
) -> None:
    controller, unit, provider = _real_srl_controller(tmp_path)

    candidate, usage = controller.decide(unit)

    assert len(provider.decision_requests) == 1
    assert candidate.candidate_kind is CandidateKind.WORK
    assert candidate.public_state_digest == unit.public_state.state_digest
    assert candidate.no_external_effect is True
    assert usage.llm_calls == 1
    assert content_digest(candidate) == content_digest(candidate.model_copy())
