from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    EnvironmentEventAdmissionReceipt,
    RelevanceDisposition,
    content_digest,
)
from agent_os_core import DeterministicProvider
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore
from apps.api_server.app import AgentOSApplication
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
    BoundControllerDecision,
    BudgetUsage,
    ControllerBindingConfig,
    DeterministicProviderUsageProbe,
    EffectFreeSandboxGate,
    EvaluationExecutionMode,
    FrozenEvaluationUnit,
    HiddenScore,
    HiddenScorerPort,
    MatchedBudgetLedger,
    MeteredControllerRunner,
    OperatorBurdenReceipt,
    RunnerIsolation,
    ScoredDecisionReceipt,
    ScorerIsolation,
    SrlE2EFalsifierHarness,
    SituatedStewardController,
    TrustedFrozenUnitLoader,
    UsageSnapshot,
    seal_hidden_score,
    seal_operator_burden,
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


def _public_fixture() -> tuple[
    PublicResponsibilityState,
    StaticBudgetConfiguration,
    PublicContentManifest,
    dict[str, bytes],
]:
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
    return state, budget, manifest, contents


def _public_state() -> tuple[PublicResponsibilityState, StaticBudgetConfiguration]:
    state, budget, _, _ = _public_fixture()
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
    def __init__(self, candidate: DecisionCandidate, probe: _Probe) -> None:
        self.candidate = candidate
        self.probe = probe

    def decide(self, unit: FrozenEvaluationUnit) -> DecisionCandidate:
        assert unit.public_state.state_digest == self.candidate.public_state_digest
        self.probe.record_provider_call()
        return self.candidate


class _Probe:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def probe_digest(self) -> str:
        return "9" * 64

    def record_provider_call(self) -> None:
        self.calls += 1

    def snapshot(self) -> UsageSnapshot:
        payload = {
            "provider_calls": self.calls,
            "input_tokens": self.calls * 5,
            "output_tokens": self.calls * 2,
            "retries": 0,
            "tool_invocations": 0,
            "provider_cost_microunits": self.calls * 10,
        }
        return UsageSnapshot(**payload, snapshot_digest=content_digest(payload))


class _SilentController:
    def __init__(self, candidate: DecisionCandidate) -> None:
        self.candidate = candidate

    def decide(self, unit: FrozenEvaluationUnit) -> DecisionCandidate:
        assert unit.public_state.state_digest == self.candidate.public_state_digest
        return self.candidate


class _ExternalMarkerController(_Controller):
    def __init__(
        self,
        candidate: DecisionCandidate,
        probe: _Probe,
        marker: list[str],
    ) -> None:
        super().__init__(candidate, probe)
        self.marker = marker

    def decide(self, unit: FrozenEvaluationUnit) -> DecisionCandidate:
        self.marker.append("controller-called")
        return super().decide(unit)


class _TamperedBindingRunner(MeteredControllerRunner):
    def run(self, unit: FrozenEvaluationUnit) -> BoundControllerDecision:
        decision = super().run(unit)
        return BoundControllerDecision(
            candidate=decision.candidate,
            usage_receipt=decision.usage_receipt,
            binding_receipt=decision.binding_receipt.model_copy(
                update={"candidate_digest": "f" * 64}
            ),
        )


def _binding_config() -> ControllerBindingConfig:
    return ControllerBindingConfig(
        controller_digest="1" * 64,
        prompt_digest="2" * 64,
        model_digest="3" * 64,
        tool_catalog_digest="4" * 64,
    )


def _runner(
    controller: object,
    probe: object,
    *,
    baseline: bool,
    tampered: bool = False,
) -> MeteredControllerRunner:
    runner_type = _TamperedBindingRunner if tampered else MeteredControllerRunner
    config = _binding_config()
    return runner_type(
        controller=controller,  # type: ignore[arg-type]
        usage_probe=probe,  # type: ignore[arg-type]
        binding_config=config,
        clock=lambda: NOW,
        monotonic=lambda: 1.0,
        isolation=RunnerIsolation.TEST_ONLY_IN_PROCESS,
        sandbox_receipt=(
            EffectFreeSandboxGate.issue(
                controller_digest=config.controller_digest,
                capability_ids=(),
                isolation=RunnerIsolation.TEST_ONLY_IN_PROCESS,
            )
            if baseline
            else None
        ),
    )


class _Scorer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.decisions: list[BlindedDecision] = []

    @property
    def isolation(self) -> ScorerIsolation:
        return ScorerIsolation.TEST_ONLY_IN_PROCESS

    @property
    def scorer_process_digest(self) -> str:
        return "8" * 64

    def score(
        self,
        *,
        decision: BlindedDecision,
        sealed_slot_tokens: tuple[str, ...],
        custody_token: str,
    ) -> ScoredDecisionReceipt:
        self.calls.append((decision.slot_token, sealed_slot_tokens))
        self.decisions.append(decision)
        return seal_hidden_score(
            decision=decision,
            custody_token=custody_token,
            scorer_process_digest=self.scorer_process_digest,
            score=HiddenScore(
                decision_ok=True,
                false_work=False,
                missed_critical=False,
                mandatory_help_ok=True,
                executor_ok=False,
                severe_safety_violation=False,
            ),
        )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )


def _load_frozen_unit(
    root: Path,
    *,
    receipt: EnvironmentEventAdmissionReceipt,
) -> tuple[TrustedFrozenUnitLoader, FrozenEvaluationUnit]:
    state, budget, public_manifest, contents = _public_fixture()
    event = _event()
    projection = _projection()
    _write_json(root / "public_state.json", state.model_dump(mode="json"))
    _write_json(root / "public_manifest.json", public_manifest.model_dump(mode="json"))
    _write_json(root / "budget.json", budget.model_dump(mode="json"))
    _write_json(root / "event.json", event.model_dump(mode="json"))
    _write_json(root / "projection.json", projection.model_dump(mode="json"))
    _write_json(root / "admission.json", receipt.model_dump(mode="json"))
    content_paths: dict[str, str] = {}
    for entry_digest, raw in contents.items():
        relative = f"content/{entry_digest}.bin"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        content_paths[entry_digest] = relative
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "unit_id": "unit-real-srl",
        "public_state_path": "public_state.json",
        "public_manifest_path": "public_manifest.json",
        "budget_path": "budget.json",
        "event_path": "event.json",
        "projection_path": "projection.json",
        "admission_receipt_path": "admission.json",
        "content_paths": content_paths,
        "public_state_digest": state.state_digest,
        "public_manifest_root_digest": public_manifest.manifest_root_digest,
        "budget_configuration_digest": budget.configuration_digest,
        "event_digest": content_digest(event),
        "projection_digest": content_digest(projection),
        "admission_receipt_digest": receipt.receipt_digest,
    }
    payload["manifest_digest"] = content_digest(payload)
    _write_json(root / "unit_manifest.json", payload)
    loader = TrustedFrozenUnitLoader(custody_key=b"unit-custody-key" * 4)
    return loader, loader.load(root)


def _real_srl_controller(
    tmp_path: Path,
) -> tuple[
    MeteredControllerRunner,
    FrozenEvaluationUnit,
    DeterministicProvider,
    TrustedFrozenUnitLoader,
]:
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
    loader, unit = _load_frozen_unit(tmp_path / "unit", receipt=receipt)
    controller = SituatedStewardController(
        application=app,
        admission_receipt=receipt,
    )
    return (
        _runner(
            controller,
            DeterministicProviderUsageProbe(provider),
            baseline=False,
        ),
        unit,
        provider,
        loader,
    )


def test_harness_seals_three_matched_arms_before_hidden_scoring(
    tmp_path: Path,
) -> None:
    srl, unit, provider, loader = _real_srl_controller(tmp_path)
    state = unit.public_state
    budget = unit.budget
    candidates = {
        ArmId.DIRECT: _candidate(state, candidate_id="ARM-DIRECT-LEAK"),
        ArmId.WORKFLOW: _candidate(state, candidate_id="ARM-WORKFLOW-LEAK"),
        ArmId.SRL: _candidate(state, candidate_id="ARM-SRL-LEAK"),
    }
    scorer = _Scorer()
    direct_probe = _Probe()
    workflow_probe = _Probe()
    harness = SrlE2EFalsifierHarness(
        runners={
            ArmId.DIRECT: _runner(
                _Controller(candidates[ArmId.DIRECT], direct_probe),
                direct_probe,
                baseline=True,
            ),
            ArmId.WORKFLOW: _runner(
                _Controller(candidates[ArmId.WORKFLOW], workflow_probe),
                workflow_probe,
                baseline=True,
            ),
            ArmId.SRL: srl,
        },
        hidden_scorer=scorer,
        budget_ledger=MatchedBudgetLedger(),
        blinding_nonce_digest="c" * 64,
        unit_loader=loader,
    )

    report = harness._evaluate_test_only_in_process(
        unit,
        burdens={
            arm: seal_operator_burden(
                unit_id=unit.unit_id,
                rater_id="blind-rater-1",
                transcript_digest="7" * 64,
                window_started_at=NOW,
                window_ended_at=NOW,
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
    assert report.admissible is False
    assert report.execution_mode is EvaluationExecutionMode.TEST_ONLY_IN_PROCESS
    assert "SCORER_NOT_INDEPENDENT_PROCESS" in report.inadmissible_reasons


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
    probes = {arm: _Probe() for arm in ArmId}
    with pytest.raises(TypeError, match="real SituatedStewardController"):
        SrlE2EFalsifierHarness(
            runners={
                arm: _runner(
                    _Controller(candidate, probes[arm]),
                    probes[arm],
                    baseline=arm is not ArmId.SRL,
                )
                for arm in ArmId
            },
            hidden_scorer=_Scorer(),
            budget_ledger=MatchedBudgetLedger(),
            blinding_nonce_digest="c" * 64,
            unit_loader=TrustedFrozenUnitLoader(custody_key=b"x" * 32),
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
    runner, unit, provider, _ = _real_srl_controller(tmp_path)

    decision = runner.run(unit)
    candidate, usage = decision.candidate, decision.usage

    assert len(provider.decision_requests) == 1
    assert candidate.candidate_kind is CandidateKind.WORK
    assert candidate.public_state_digest == unit.public_state.state_digest
    assert candidate.no_external_effect is True
    assert usage.llm_calls == 1
    assert content_digest(candidate) == content_digest(candidate.model_copy())


def test_trusted_loader_rejects_public_construction_and_budget_swap(
    tmp_path: Path,
) -> None:
    _, unit, _, loader = _real_srl_controller(tmp_path)
    public = FrozenEvaluationUnit(
        unit_id=unit.unit_id,
        public_state=unit.public_state,
        budget=unit.budget,
        event_id=unit.event_id,
        projection_id=unit.projection_id,
        admission_receipt_id=unit.admission_receipt_id,
    )
    with pytest.raises(ValueError, match="lacks trusted custody"):
        loader.verify(public)

    replacement_payload: dict[str, object] = {
        "max_llm_calls": 99,
        "max_input_tokens": 1000,
        "max_output_tokens": 500,
        "max_retries": 1,
        "max_tool_invocations": 4,
        "max_wall_seconds": 60,
    }
    replacement_payload["configuration_digest"] = static_budget_configuration_digest(
        replacement_payload
    )
    _write_json(tmp_path / "unit" / "budget.json", replacement_payload)
    with pytest.raises(ValueError, match="budget|manifest|content"):
        loader.load(tmp_path / "unit")


def test_harness_rejects_controller_binding_receipt_drift_before_scoring(
    tmp_path: Path,
) -> None:
    srl, unit, _, loader = _real_srl_controller(tmp_path)
    candidate = _candidate(unit.public_state, candidate_id="candidate-baseline")
    scorer = _Scorer()
    direct_probe = _Probe()
    workflow_probe = _Probe()
    harness = SrlE2EFalsifierHarness(
        runners={
            ArmId.DIRECT: _runner(
                _Controller(candidate, direct_probe),
                direct_probe,
                baseline=True,
                tampered=True,
            ),
            ArmId.WORKFLOW: _runner(
                _Controller(candidate, workflow_probe),
                workflow_probe,
                baseline=True,
            ),
            ArmId.SRL: srl,
        },
        hidden_scorer=scorer,
        budget_ledger=MatchedBudgetLedger(),
        blinding_nonce_digest="c" * 64,
        unit_loader=loader,
    )
    burdens = {
        arm: seal_operator_burden(
            unit_id=unit.unit_id,
            rater_id="blind-rater-1",
            transcript_digest="7" * 64,
            window_started_at=NOW,
            window_ended_at=NOW,
            hcw_minutes=1.0,
            auth_minutes=0.0,
            help_minutes=0.0,
            help_count=0,
            latency_ms=1,
        )
        for arm in ArmId
    }

    with pytest.raises(ValueError, match="controller binding receipt"):
        harness._evaluate_test_only_in_process(unit, burdens=burdens)
    assert scorer.calls == []


def test_public_evaluate_fails_before_any_controller_or_provider_call(
    tmp_path: Path,
) -> None:
    srl, unit, provider, loader = _real_srl_controller(tmp_path)
    candidate = _candidate(unit.public_state, candidate_id="baseline")
    direct_probe = _Probe()
    workflow_probe = _Probe()
    external_marker: list[str] = []
    harness = SrlE2EFalsifierHarness(
        runners={
            ArmId.DIRECT: _runner(
                _ExternalMarkerController(candidate, direct_probe, external_marker),
                direct_probe,
                baseline=True,
            ),
            ArmId.WORKFLOW: _runner(
                _Controller(candidate, workflow_probe), workflow_probe, baseline=True
            ),
            ArmId.SRL: srl,
        },
        hidden_scorer=_Scorer(),
        budget_ledger=MatchedBudgetLedger(),
        blinding_nonce_digest="c" * 64,
        unit_loader=loader,
    )
    burden = seal_operator_burden(
        unit_id=unit.unit_id,
        rater_id="blind-rater-1",
        transcript_digest="7" * 64,
        window_started_at=NOW,
        window_ended_at=NOW,
        hcw_minutes=1.0,
        auth_minutes=0.0,
        help_minutes=0.0,
        help_count=0,
        latency_ms=1,
    )

    with pytest.raises(RuntimeError, match="independent subprocess custody"):
        harness.evaluate_unit(unit, burdens={arm: burden for arm in ArmId})
    assert direct_probe.calls == 0
    assert workflow_probe.calls == 0
    assert external_marker == []
    assert provider.decision_requests == []


def test_srl_controller_rechecks_exact_steward_identity_after_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner, unit, provider, _ = _real_srl_controller(tmp_path)
    controller = runner.controller
    assert isinstance(controller, SituatedStewardController)
    application = controller._application
    original = application.propose_situated_work

    def swap_after_call(
        event_id: str,
        projection_id: str,
        admission_receipt_id: str,
    ) -> object:
        result = original(event_id, projection_id, admission_receipt_id)
        application._mandate_steward = object()  # type: ignore[assignment]
        return result

    monkeypatch.setattr(application, "propose_situated_work", swap_after_call)

    with pytest.raises(TypeError, match="concrete MandateSteward"):
        runner.run(unit)
    assert len(provider.decision_requests) == 1


def test_metered_runner_rejects_controller_without_observable_usage(
    tmp_path: Path,
) -> None:
    _, unit, _, _ = _real_srl_controller(tmp_path)
    probe = _Probe()
    runner = _runner(
        _SilentController(_candidate(unit.public_state, candidate_id="silent")),
        probe,
        baseline=True,
    )

    with pytest.raises(ValueError, match="not observably metered"):
        runner.run(unit)


def test_baseline_without_capability_empty_sandbox_receipt_is_rejected(
    tmp_path: Path,
) -> None:
    srl, unit, _, loader = _real_srl_controller(tmp_path)
    candidate = _candidate(unit.public_state, candidate_id="baseline")
    direct_probe = _Probe()
    workflow_probe = _Probe()
    direct_without_sandbox = _runner(
        _Controller(candidate, direct_probe),
        direct_probe,
        baseline=False,
    )

    with pytest.raises(ValueError, match="effect-free sandbox receipt"):
        SrlE2EFalsifierHarness(
            runners={
                ArmId.DIRECT: direct_without_sandbox,
                ArmId.WORKFLOW: _runner(
                    _Controller(candidate, workflow_probe),
                    workflow_probe,
                    baseline=True,
                ),
                ArmId.SRL: srl,
            },
            hidden_scorer=_Scorer(),
            budget_ledger=MatchedBudgetLedger(),
            blinding_nonce_digest="c" * 64,
            unit_loader=loader,
        )


def test_srl_composition_rejects_duck_application_even_if_isinstance(
    tmp_path: Path,
) -> None:
    _real_srl_controller(tmp_path)
    receipt = EnvironmentEventAdmissionReceipt.model_validate(
        json.loads((tmp_path / "unit" / "admission.json").read_text())
    )

    class DuckAgentOSApplication(AgentOSApplication):
        pass

    duck = object.__new__(DuckAgentOSApplication)
    with pytest.raises(TypeError, match="concrete AgentOSApplication"):
        SituatedStewardController(application=duck, admission_receipt=receipt)


def test_operator_burden_receipt_drift_fails_before_any_controller(
    tmp_path: Path,
) -> None:
    srl, unit, _, loader = _real_srl_controller(tmp_path)
    probes = {arm: _Probe() for arm in (ArmId.DIRECT, ArmId.WORKFLOW)}
    candidate = _candidate(unit.public_state, candidate_id="baseline")
    harness = SrlE2EFalsifierHarness(
        runners={
            ArmId.DIRECT: _runner(
                _Controller(candidate, probes[ArmId.DIRECT]),
                probes[ArmId.DIRECT],
                baseline=True,
            ),
            ArmId.WORKFLOW: _runner(
                _Controller(candidate, probes[ArmId.WORKFLOW]),
                probes[ArmId.WORKFLOW],
                baseline=True,
            ),
            ArmId.SRL: srl,
        },
        hidden_scorer=_Scorer(),
        budget_ledger=MatchedBudgetLedger(),
        blinding_nonce_digest="c" * 64,
        unit_loader=loader,
    )
    valid = seal_operator_burden(
        unit_id=unit.unit_id,
        rater_id="blind-rater-1",
        transcript_digest="7" * 64,
        window_started_at=NOW,
        window_ended_at=NOW,
        hcw_minutes=1.0,
        auth_minutes=0.0,
        help_minutes=0.0,
        help_count=0,
        latency_ms=1,
    )
    forged = OperatorBurdenReceipt(
        **{
            **valid.__dict__,
            "transcript_digest": "6" * 64,
        }
    )

    with pytest.raises(ValueError, match="burden receipt provenance"):
        harness._evaluate_test_only_in_process(
            unit, burdens={arm: forged for arm in ArmId}
        )
    assert all(probe.calls == 0 for probe in probes.values())
