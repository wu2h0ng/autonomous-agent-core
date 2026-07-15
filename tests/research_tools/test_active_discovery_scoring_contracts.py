from __future__ import annotations

from dataclasses import replace

import pytest

from research_tools.active_discovery.scoring_contracts import (
    ChallengeCatalogue,
    ChallengePrediction,
    ChallengeSequence,
    ChallengeStep,
    DiscoveryScoreBundle,
    OutcomeAtom,
    ScoringContractError,
    StatefulTestAssertion,
    StatefulTestCase,
    StatefulTestIR,
    StatefulTestStep,
    TraceProbability,
    BehaviorTrace,
)


def _trace(label: str, *, changed: bool = False) -> BehaviorTrace:
    return BehaviorTrace(
        atoms=(
            OutcomeAtom.create(
                status_code=0,
                stdout=label,
                stderr="",
                output={"value": label},
                state_relation="CHANGED" if changed else "SAME",
            ),
        )
    )


def _catalogue() -> ChallengeCatalogue:
    first = _trace("a")
    second = _trace("b", changed=True)
    sequence = ChallengeSequence.create(
        reset_slot="clean-0",
        steps=(ChallengeStep.create(operation_id="op", payload={"x": 1}),),
        traces=tuple(sorted((first, second), key=lambda item: item.canonical_bytes)),
    )
    return ChallengeCatalogue.create(
        instance_public_digest="1" * 64,
        sequences=(sequence,),
        probe_sequence_digests=("2" * 64,),
    )


def _test_ir(payload: object | None = None) -> StatefulTestIR:
    assertion = StatefulTestAssertion.create(
        source="STATUS_CODE", operator="EQ", expected=0
    )
    step = StatefulTestStep.create(
        operation_id="op",
        payload={"held_out": 1} if payload is None else payload,
        assertions=(assertion,),
    )
    return StatefulTestIR(
        tests=(
            StatefulTestCase.create(
                test_id="test-1",
                reset_slot="test-reset-1",
                steps=(step,),
                provenance_refs=("public-descriptor",),
            ),
        )
    )


def _bundle(catalogue: ChallengeCatalogue) -> DiscoveryScoreBundle:
    sequence = catalogue.sequences[0]
    first, second = sequence.traces
    prediction = ChallengePrediction(
        challenge_digest=sequence.challenge_digest,
        probabilities=(
            TraceProbability(first.trace_digest, 600_000),
            TraceProbability(second.trace_digest, 400_000),
        ),
        predicted_trace_digest=first.trace_digest,
    )
    return DiscoveryScoreBundle.create(
        experiment_id="R-ACTIVE-DISCOVERY-1",
        instance_public_digest=catalogue.instance_public_digest,
        arm_id="ACTIVE_VOI",
        actor_binding_digest="3" * 64,
        prefix_index=0,
        parent_bundle_digest=None,
        predictions=(prediction,),
        test_ir=_test_ir(),
        transcript_prefix_digest="4" * 64,
        consumed_units=0,
        budget_receipt_digest="5" * 64,
        catalogue=catalogue,
    )


def test_score_bundle_is_closed_canonical_and_replays_exact_digest() -> None:
    catalogue = _catalogue()
    bundle = _bundle(catalogue)

    replay = DiscoveryScoreBundle.from_mapping(bundle.to_mapping(), catalogue)

    assert replay == bundle
    assert replay.bundle_digest == bundle.bundle_digest
    assert replay.canonical_bytes == bundle.canonical_bytes

    unknown = bundle.to_mapping()
    unknown["scorer_path"] = "candidate-controlled.py"
    with pytest.raises(ScoringContractError, match="unknown fields"):
        DiscoveryScoreBundle.from_mapping(unknown, catalogue)


def test_probability_vector_and_explicit_contract_fail_closed() -> None:
    catalogue = _catalogue()
    bundle = _bundle(catalogue)
    prediction = bundle.predictions[0]
    first, second = prediction.probabilities
    lower_probability = min(
        prediction.probabilities, key=lambda item: item.probability_micros
    )

    with pytest.raises(ScoringContractError, match="sum exactly"):
        DiscoveryScoreBundle.create(
            **bundle.creation_arguments(
                catalogue=catalogue,
                predictions=(
                    replace(
                        prediction,
                        probabilities=(
                            replace(first, probability_micros=500_000),
                            replace(second, probability_micros=400_000),
                        ),
                    ),
                ),
            )
        )

    with pytest.raises(ScoringContractError, match="maximum-probability"):
        DiscoveryScoreBundle.create(
            **bundle.creation_arguments(
                catalogue=catalogue,
                predictions=(
                    replace(
                        prediction,
                        predicted_trace_digest=lower_probability.trace_digest,
                    ),
                ),
            )
        )


def test_prefix_chain_and_consumed_units_are_immutable_bindings() -> None:
    catalogue = _catalogue()
    bundle = _bundle(catalogue)

    with pytest.raises(ScoringContractError, match="prefix zero"):
        DiscoveryScoreBundle.create(
            **bundle.creation_arguments(
                catalogue=catalogue,
                parent_bundle_digest="a" * 64,
            )
        )
    with pytest.raises(ScoringContractError, match="consumed_units"):
        DiscoveryScoreBundle.create(
            **bundle.creation_arguments(catalogue=catalogue, consumed_units=1)
        )


def test_stateful_test_ir_is_inert_bounded_and_disjoint() -> None:
    catalogue = _catalogue()
    sequence = catalogue.sequences[0]
    challenge_payload = sequence.steps[0].payload_json
    assertion = StatefulTestAssertion.create(
        source="STATUS_CODE", operator="EQ", expected=0
    )
    copied_challenge = StatefulTestIR(
        tests=(
            StatefulTestCase.create(
                test_id="copy",
                reset_slot="reset",
                steps=(
                    StatefulTestStep(
                        operation_id="op",
                        payload_json=challenge_payload,
                        assertions=(assertion,),
                    ),
                ),
                provenance_refs=("public-descriptor",),
            ),
        )
    )
    with pytest.raises(ScoringContractError, match="challenge"):
        copied_challenge.validate_disjoint(catalogue.forbidden_sequence_digests)

    with pytest.raises(ScoringContractError, match="fixed literal"):
        StatefulTestAssertion.create(
            source="STDOUT", operator="EQ", expected="$actual.stdout"
        )

    case = _test_ir().tests[0]
    with pytest.raises(ScoringContractError, match="1-16"):
        StatefulTestIR(tests=tuple(replace(case, test_id=f"t-{i}") for i in range(17)))
    with pytest.raises(ScoringContractError, match="1-8"):
        StatefulTestCase.create(
            test_id="too-long",
            reset_slot="reset",
            steps=tuple(case.steps[0] for _ in range(9)),
            provenance_refs=("public-descriptor",),
        )


def test_complete_trace_duplicate_means_duplicate_encoding_not_repeated_atom() -> None:
    atom = OutcomeAtom.create(
        status_code=0,
        stdout="same",
        stderr="",
        output={},
        state_relation="SAME",
    )
    repeated_atoms_are_valid = BehaviorTrace(atoms=(atom, atom))
    distinct = BehaviorTrace(
        atoms=(atom, replace(atom, stdout="different"))
    )
    steps = (
        ChallengeStep.create(operation_id="op", payload={"n": 1}),
        ChallengeStep.create(operation_id="op", payload={"n": 2}),
    )

    sequence = ChallengeSequence.create(
        reset_slot="clean",
        steps=steps,
        traces=tuple(
            sorted((repeated_atoms_are_valid, distinct), key=lambda item: item.canonical_bytes)
        ),
    )
    assert len(sequence.traces) == 2

    with pytest.raises(ScoringContractError, match="duplicate complete-trace"):
        ChallengeSequence.create(
            reset_slot="clean",
            steps=steps,
            traces=(repeated_atoms_are_valid, repeated_atoms_are_valid),
        )
