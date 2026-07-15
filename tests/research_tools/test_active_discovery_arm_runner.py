from __future__ import annotations

from dataclasses import replace

import pytest

from research_tools.active_discovery.arm_runner import (
    ARM_RUN_SCHEMA,
    ArmKind,
    MatchedArmRunSpec,
    RunnerValidationError,
    run_matched_arms,
    select_visible_voi_candidate,
    update_visible_beliefs,
)
from research_tools.active_discovery.budget import BudgetLedger
from research_tools.active_discovery.canonical import canonical_json
from research_tools.active_discovery.catalogue import VisibleProbeCandidate
from research_tools.active_discovery.contracts import (
    ProbeObservation,
    ProbeRequest,
    PublicEnvironmentDescriptor,
)
from research_tools.active_discovery.families.manifest import FamilyCode
from research_tools.active_discovery.families.unified import UnifiedFamilyAdapter
from research_tools.active_discovery.referee import (
    HiddenScore,
    ProbeHalted,
    RefereeNotSealed,
    SealedRefereeSession,
)
from research_tools.active_discovery.selector import (
    HypothesisPrediction,
    OutcomeLikelihood,
)


class _NeverHalted:
    def halted(self, episode_id: str) -> bool:
        return False


class _AlwaysHalted:
    def halted(self, episode_id: str) -> bool:
        return True


class _ScoreTrapAdapter:
    def __init__(self, inner: UnifiedFamilyAdapter) -> None:
        self.inner = inner
        self.hidden_score_calls = 0
        self.state_digest_calls = 0

    @property
    def manifest(self):  # type: ignore[no-untyped-def]
        return self.inner.manifest

    @property
    def catalogue(self):  # type: ignore[no-untyped-def]
        return self.inner.catalogue

    def public_descriptor(self) -> PublicEnvironmentDescriptor:
        return self.inner.public_descriptor()

    def state_digest(self) -> str:
        self.state_digest_calls += 1
        return self.inner.state_digest()

    def execute(self, request: ProbeRequest) -> ProbeObservation:
        return self.inner.execute(request)

    def hidden_score(
        self, bundle_digest: str, transcript: tuple[ProbeObservation, ...]
    ) -> HiddenScore:
        self.hidden_score_calls += 1
        raise AssertionError("matched-arm runner must not request hidden score")


def _spec_mapping(manifest_digest: str, *, random_seed: int = 101) -> dict[str, object]:
    return {
        "schema_version": ARM_RUN_SCHEMA,
        "mode": "NOT_EVIDENCE",
        "run_id": "batch-2a-development-run",
        "family_manifest_digest": manifest_digest,
        "budget_units": 4,
        "random_seed": random_seed,
    }


def _trap_factory(
    prototype: UnifiedFamilyAdapter,
    created: list[_ScoreTrapAdapter] | None = None,
):  # type: ignore[no-untyped-def]
    def factory() -> _ScoreTrapAdapter:
        adapter = _ScoreTrapAdapter(
            UnifiedFamilyAdapter.from_manifest(prototype.manifest)
        )
        if created is not None:
            created.append(adapter)
        return adapter

    return factory


def test_matched_arm_spec_is_closed_and_not_evidence_only() -> None:
    prototype = UnifiedFamilyAdapter.build(
        family_code=FamilyCode.F2,
        seed=71,
        probe_budget_units=4,
    )
    unknown = _spec_mapping(prototype.manifest.manifest_digest)
    unknown["oracle_score"] = 1
    with pytest.raises(RunnerValidationError, match="unknown fields"):
        MatchedArmRunSpec.from_mapping(unknown)

    wrong_mode = _spec_mapping(prototype.manifest.manifest_digest)
    wrong_mode["mode"] = "EVIDENCE"
    with pytest.raises(RunnerValidationError, match="NOT_EVIDENCE"):
        MatchedArmRunSpec.from_mapping(wrong_mode)


def _relabel(candidate: VisibleProbeCandidate) -> VisibleProbeCandidate:
    mapping = {
        candidate.zero_status_label: "renamed-zero",
        candidate.nonzero_status_label: "renamed-nonzero",
    }
    predictions = tuple(
        HypothesisPrediction(
            prediction.hypothesis_id,
            tuple(
                OutcomeLikelihood(
                    mapping[outcome.outcome_label], outcome.probability_micros
                )
                for outcome in prediction.outcomes
            ),
        )
        for prediction in candidate.predictions
    )
    return replace(
        candidate,
        zero_status_label="renamed-zero",
        nonzero_status_label="renamed-nonzero",
        predictions=predictions,
    )


def test_visible_voi_selection_and_update_are_label_permutation_invariant() -> None:
    adapter = UnifiedFamilyAdapter.build(
        family_code=FamilyCode.F3,
        seed=73,
        probe_budget_units=4,
    )
    catalogue = adapter.catalogue
    relabeled = tuple(_relabel(candidate) for candidate in catalogue.candidates)

    selected = select_visible_voi_candidate(
        catalogue.initial_weights, catalogue.candidates
    )
    selected_relabeled = select_visible_voi_candidate(
        catalogue.initial_weights, relabeled
    )
    updated = update_visible_beliefs(catalogue.initial_weights, selected, status_code=0)
    updated_relabeled = update_visible_beliefs(
        catalogue.initial_weights, selected_relabeled, status_code=0
    )

    assert selected.probe_id == selected_relabeled.probe_id
    assert tuple(item.probability_micros for item in updated) == tuple(
        item.probability_micros for item in updated_relabeled
    )


def test_matched_runner_uses_fresh_adapters_exact_budgets_and_no_hidden_score() -> None:
    prototype = UnifiedFamilyAdapter.build(
        family_code=FamilyCode.F2,
        seed=79,
        probe_budget_units=4,
    )
    spec = MatchedArmRunSpec.from_mapping(
        _spec_mapping(prototype.manifest.manifest_digest)
    )
    created: list[_ScoreTrapAdapter] = []

    receipt = run_matched_arms(
        spec=spec,
        adapter_factory=_trap_factory(prototype, created),
        halt_authority=_NeverHalted(),
    )

    assert len(created) == 3
    assert len({id(adapter.inner) for adapter in created}) == 3
    assert {arm.arm_kind for arm in receipt.arms} == set(ArmKind)
    assert {arm.consumed_units for arm in receipt.arms} == {4}
    assert {len(arm.selected_probe_ids) for arm in receipt.arms} == {4}
    assert {len(arm.observation_digests) for arm in receipt.arms} == {4}
    assert {adapter.hidden_score_calls for adapter in created} == {0}
    public_receipt = canonical_json(receipt.to_mapping()).lower()
    assert "score" not in public_receipt
    assert "oracle" not in public_receipt


@pytest.mark.parametrize("family_code", (FamilyCode.F2, FamilyCode.F3, FamilyCode.F4))
def test_matched_runner_replays_same_seed_to_exact_receipt_digest(
    family_code: FamilyCode,
) -> None:
    prototype = UnifiedFamilyAdapter.build(
        family_code=family_code,
        seed=83,
        probe_budget_units=4,
    )
    spec = MatchedArmRunSpec.from_mapping(
        _spec_mapping(prototype.manifest.manifest_digest, random_seed=107)
    )

    first = run_matched_arms(
        spec=spec,
        adapter_factory=_trap_factory(prototype),
        halt_authority=_NeverHalted(),
    )
    replay = run_matched_arms(
        spec=spec,
        adapter_factory=_trap_factory(prototype),
        halt_authority=_NeverHalted(),
    )

    assert first == replay
    assert first.receipt_digest == replay.receipt_digest


def test_matched_runner_halts_before_returning_partial_receipt() -> None:
    prototype = UnifiedFamilyAdapter.build(
        family_code=FamilyCode.F4,
        seed=89,
        probe_budget_units=4,
    )
    spec = MatchedArmRunSpec.from_mapping(
        _spec_mapping(prototype.manifest.manifest_digest)
    )
    created: list[_ScoreTrapAdapter] = []

    with pytest.raises(ProbeHalted, match="halt"):
        run_matched_arms(
            spec=spec,
            adapter_factory=_trap_factory(prototype, created),
            halt_authority=_AlwaysHalted(),
        )

    assert len(created) == 1
    assert created[0].state_digest_calls == 0
    assert created[0].hidden_score_calls == 0


def test_unified_hidden_score_is_available_only_through_sealed_referee() -> None:
    adapter = UnifiedFamilyAdapter.build(
        family_code=FamilyCode.F3,
        seed=97,
        probe_budget_units=4,
    )
    session = SealedRefereeSession(
        episode_id="sealed-hidden-check",
        adapter=adapter,
        budget=BudgetLedger(0),
        halt_authority=_NeverHalted(),
    )

    with pytest.raises(RefereeNotSealed, match="sealed"):
        session.score_sealed()

    session.seal(bundle_digest="9" * 64)
    assert session.score_sealed().score_micros == 0
