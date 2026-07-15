from __future__ import annotations

from dataclasses import replace

import pytest

from research_tools.active_discovery.scored_arm_runner import (
    ScoredArmInput,
    ScoredRunnerError,
    run_scored_arm_collection,
)
from research_tools.active_discovery.scoring_contracts import (
    BehaviorTrace,
    ChallengeCatalogue,
    ChallengePrediction,
    ChallengeSequence,
    ChallengeStep,
    DiscoveryScoreBundle,
    OutcomeAtom,
    StatefulTestAssertion,
    StatefulTestCase,
    StatefulTestIR,
    StatefulTestStep,
    TraceProbability,
)
from research_tools.active_discovery.scoring_referee import (
    BundleByteStore,
    ScoringHalted,
    ScoringReferee,
)


class _NeverHalted:
    def halted(self, episode_id: str) -> bool:
        return False


class _AlwaysHalted:
    def halted(self, episode_id: str) -> bool:
        return True


def _catalogue() -> ChallengeCatalogue:
    traces = tuple(
        sorted(
            (
                BehaviorTrace(
                    atoms=(
                        OutcomeAtom.create(
                            status_code=0,
                            stdout=label,
                            stderr="",
                            output={"value": label},
                            state_relation="SAME",
                        ),
                    )
                )
                for label in ("a", "b")
            ),
            key=lambda item: item.canonical_bytes,
        )
    )
    return ChallengeCatalogue.create(
        instance_public_digest="1" * 64,
        sequences=(
            ChallengeSequence.create(
                reset_slot="clean",
                steps=(ChallengeStep.create(operation_id="op", payload={"x": 1}),),
                traces=traces,
            ),
        ),
        probe_sequence_digests=(),
    )


def _chain(arm_id: str, catalogue: ChallengeCatalogue) -> tuple[DiscoveryScoreBundle, ...]:
    challenge = catalogue.sequences[0]
    assertion = StatefulTestAssertion.create(
        source="STATUS_CODE", operator="EQ", expected=0
    )
    test_ir = StatefulTestIR(
        tests=(
            StatefulTestCase.create(
                test_id="test",
                reset_slot="test-reset",
                steps=(
                    StatefulTestStep.create(
                        operation_id="op",
                        payload={"held": 1},
                        assertions=(assertion,),
                    ),
                ),
                provenance_refs=("public-descriptor",),
            ),
        )
    )
    parent: str | None = None
    bundles: list[DiscoveryScoreBundle] = []
    for prefix in range(5):
        bundle = DiscoveryScoreBundle.create(
            experiment_id="R-ACTIVE-DISCOVERY-1",
            instance_public_digest=catalogue.instance_public_digest,
            arm_id=arm_id,
            actor_binding_digest="2" * 64,
            prefix_index=prefix,
            parent_bundle_digest=parent,
            predictions=(
                ChallengePrediction(
                    challenge_digest=challenge.challenge_digest,
                    probabilities=tuple(
                        TraceProbability(item.trace_digest, 500_000)
                        for item in challenge.traces
                    ),
                    predicted_trace_digest=challenge.traces[0].trace_digest,
                ),
            ),
            test_ir=test_ir,
            transcript_prefix_digest=format(prefix + 3, "x") * 64,
            consumed_units=prefix,
            budget_receipt_digest=format(prefix + 8, "x") * 64,
            catalogue=catalogue,
        )
        bundles.append(bundle)
        parent = bundle.bundle_digest
    return tuple(bundles)


def _input(arm_id: str, adapter_identity: str, catalogue: ChallengeCatalogue) -> ScoredArmInput:
    return ScoredArmInput(
        arm_id=arm_id,
        adapter_identity=adapter_identity,
        catalogue=catalogue,
        prefix_bundles=_chain(arm_id, catalogue),
    )


def test_runner_commits_exact_k0_to_k4_chains_without_score_feedback() -> None:
    catalogue = _catalogue()
    referee = ScoringReferee(
        episode_id="matched",
        expected_arm_ids=("A", "B"),
        halt_authority=_NeverHalted(),
        bundle_store=BundleByteStore(),
    )
    receipt = run_scored_arm_collection(
        referee=referee,
        arms=(
            _input("A", "adapter-a", catalogue),
            _input("B", "adapter-b", catalogue),
        ),
    )

    assert receipt.arm_count == 2
    assert receipt.bundle_count == 10
    assert receipt.final_consumed_units == 4
    assert not hasattr(receipt, "scores")
    assert referee.is_closed


def test_runner_prevalidates_missing_prefix_adapter_reuse_and_parity_before_writes() -> None:
    catalogue = _catalogue()
    store = BundleByteStore()
    referee = ScoringReferee(
        episode_id="matched",
        expected_arm_ids=("A", "B"),
        halt_authority=_NeverHalted(),
        bundle_store=store,
    )
    missing = replace(
        _input("A", "adapter-a", catalogue),
        prefix_bundles=_chain("A", catalogue)[:-1],
    )
    with pytest.raises(ScoredRunnerError, match="k=0..4"):
        run_scored_arm_collection(
            referee=referee,
            arms=(missing, _input("B", "adapter-b", catalogue)),
        )
    assert store.stored_bundle_count == 0

    reuse_referee = ScoringReferee(
        episode_id="matched-2",
        expected_arm_ids=("A", "B"),
        halt_authority=_NeverHalted(),
        bundle_store=BundleByteStore(),
    )
    with pytest.raises(ScoredRunnerError, match="fresh adapter"):
        run_scored_arm_collection(
            referee=reuse_referee,
            arms=(
                _input("A", "same-adapter", catalogue),
                _input("B", "same-adapter", catalogue),
            ),
        )

    parity_referee = ScoringReferee(
        episode_id="matched-3",
        expected_arm_ids=("A", "B"),
        halt_authority=_NeverHalted(),
        bundle_store=BundleByteStore(),
    )
    b = _input("B", "adapter-b", catalogue)
    mismatched = replace(
        b,
        prefix_bundles=tuple(
            replace(item, actor_binding_digest="9" * 64) for item in b.prefix_bundles
        ),
    )
    with pytest.raises(ScoredRunnerError, match="actor binding parity"):
        run_scored_arm_collection(
            referee=parity_referee,
            arms=(_input("A", "adapter-a", catalogue), mismatched),
        )


def test_runner_halt_yields_no_collection_receipt_or_hidden_score() -> None:
    catalogue = _catalogue()
    store = BundleByteStore()
    referee = ScoringReferee(
        episode_id="halted",
        expected_arm_ids=("A",),
        halt_authority=_AlwaysHalted(),
        bundle_store=store,
    )

    with pytest.raises(ScoringHalted, match="halt"):
        run_scored_arm_collection(
            referee=referee,
            arms=(_input("A", "adapter-a", catalogue),),
        )
    assert store.stored_bundle_count == 0
    assert not referee.is_closed
