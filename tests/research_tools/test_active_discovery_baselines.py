from __future__ import annotations

from dataclasses import replace

import pytest

from research_tools.active_discovery.baselines import (
    PUBLIC_COVERAGE_STRATA,
    REQUIRED_BASELINES,
    BaselineContractError,
    BaselineKind,
    HumanPrefixEvent,
    HumanProtocolBinding,
    HumanProtocolError,
    ModelArmParityRecord,
    ModelParityBinding,
    RandomSeedSet,
    StratifiedProbe,
    build_random_stratified_plans,
    build_systematic_covering_plan,
    human_missing_disposition,
    validate_human_bundle_protocol,
    verify_model_arm_parity,
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


def _digest(label: str) -> str:
    return format(sum(label.encode("utf-8")) + 1, "x").rjust(64, "0")[-64:]


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
        instance_public_digest=_digest("instance"),
        sequences=(
            ChallengeSequence.create(
                reset_slot="clean",
                steps=(ChallengeStep.create(operation_id="op", payload={"x": 1}),),
                traces=traces,
            ),
        ),
        probe_sequence_digests=(),
    )


def _human_chain(catalogue: ChallengeCatalogue) -> tuple[DiscoveryScoreBundle, ...]:
    challenge = catalogue.sequences[0]
    probabilities = tuple(
        TraceProbability(item.trace_digest, 500_000) for item in challenge.traces
    )
    assertion = StatefulTestAssertion.create(
        source="STATUS_CODE", operator="EQ", expected=0
    )
    test_ir = StatefulTestIR(
        tests=(
            StatefulTestCase.create(
                test_id="human-test",
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
            arm_id=BaselineKind.HUMAN_STRONG.value,
            actor_binding_digest=_digest("human-operator"),
            prefix_index=prefix,
            parent_bundle_digest=parent,
            predictions=(
                ChallengePrediction(
                    challenge_digest=challenge.challenge_digest,
                    probabilities=probabilities,
                    predicted_trace_digest=challenge.traces[0].trace_digest,
                ),
            ),
            test_ir=test_ir,
            transcript_prefix_digest=_digest(f"transcript-{prefix}"),
            consumed_units=prefix,
            budget_receipt_digest=_digest(f"budget-{prefix}"),
            catalogue=catalogue,
        )
        bundles.append(bundle)
        parent = bundle.bundle_digest
    return tuple(bundles)


def _probes() -> tuple[StratifiedProbe, ...]:
    return (
        StratifiedProbe(
            "probe-z",
            0,
            ("BOUNDARY", "PAIRWISE_INTERACTION", "STATE_CHANGE"),
        ),
        StratifiedProbe(
            "probe-a", 1, ("REPETITION", "ORDERING", "ERROR_RECOVERY")
        ),
        StratifiedProbe("probe-b", 2, ("BOUNDARY", "ORDERING")),
        StratifiedProbe("probe-c", 3, ("STATE_CHANGE", "ERROR_RECOVERY")),
        StratifiedProbe("probe-d", 4, ("PAIRWISE_INTERACTION", "REPETITION")),
        StratifiedProbe("probe-e", 5, ("BOUNDARY", "ERROR_RECOVERY")),
    )


def _parity_binding() -> ModelParityBinding:
    return ModelParityBinding(
        provider="provider",
        model_checkpoint="model@checkpoint",
        decoding_digest=_digest("decoding"),
        model_seed=17,
        system_prompt_digest=_digest("system"),
        task_prompt_digest=_digest("task"),
        context_window_tokens=32_000,
        reasoning_token_budget=8_000,
        tool_call_budget=16,
        output_token_cap=4_000,
        bundle_size_cap_bytes=64_000,
        public_interface_digest=_digest("public-interface"),
        hidden_commitment_set_digest=_digest("hidden-set"),
        retry_policy_digest=_digest("retry"),
        reset_policy_digest=_digest("reset"),
        timeout_millis=120_000,
        probe_budget_units=4,
        scorer_and_adjudication_digest=_digest("score-adjudication"),
    )


def _human_binding() -> HumanProtocolBinding:
    return HumanProtocolBinding(
        ui_digest=_digest("ui"),
        instructions_digest=_digest("instructions"),
        eligibility_screen_digest=_digest("eligibility"),
        practice_task_digest=_digest("practice"),
        event_log_schema_digest=_digest("events"),
        public_interface_digest=_digest("public-interface"),
        break_policy_digest=_digest("breaks"),
        allowed_notes_digest=_digest("notes"),
        compensation_class="fixed-session",
        wall_clock_cap_seconds=3_600,
        operator_count=1,
        practice_disjoint_from_scoring=True,
        source_access_allowed=False,
        shell_access_allowed=False,
        filesystem_access_allowed=False,
        network_access_allowed=False,
        other_people_allowed=False,
        model_assistance_allowed=False,
        hidden_outcome_access_allowed=False,
        score_feedback_allowed=False,
    )


def test_required_baselines_are_explicit_and_not_reduced_to_old_stable_order() -> None:
    assert REQUIRED_BASELINES == frozenset(
        {
            BaselineKind.SYSTEMATIC_COVERING,
            BaselineKind.RANDOM_STRATIFIED,
            BaselineKind.PASSIVE_ZERO_QUERY,
            BaselineKind.FREEFORM_ENGINEER,
            BaselineKind.HUMAN_STRONG,
            BaselineKind.TRACE_MEMO,
            BaselineKind.GENERIC_TESTS,
        }
    )
    plan = build_systematic_covering_plan(probes=_probes(), budget_units=4)
    assert plan.covered_strata == PUBLIC_COVERAGE_STRATA
    assert len(plan.selected_probe_ids) <= 4
    assert plan.planner_name == "PUBLIC_SCHEMA_GREEDY_COVER"

    incomplete = tuple(
        replace(item, strata=tuple(s for s in item.strata if s != "ERROR_RECOVERY"))
        for item in _probes()
    )
    with pytest.raises(BaselineContractError, match="every public stratum"):
        build_systematic_covering_plan(probes=incomplete, budget_units=4)


def test_random_stratified_uses_frozen_full_seed_set_without_best_seed_selection() -> None:
    seeds = RandomSeedSet.create((101, 103, 107, 109))
    first = build_random_stratified_plans(
        probes=_probes(), budget_units=4, seed_set=seeds
    )
    replay = build_random_stratified_plans(
        probes=_probes(), budget_units=4, seed_set=seeds
    )
    assert first == replay
    assert first.seed_set_digest == seeds.seed_set_digest
    assert tuple(item.seed for item in first.plans) == seeds.seeds
    assert all(item.covered_strata == PUBLIC_COVERAGE_STRATA for item in first.plans)
    assert all(len(set(item.selected_probe_ids)) == len(item.selected_probe_ids) for item in first.plans)


def test_model_arm_parity_and_passive_zero_query_accounting_fail_closed() -> None:
    binding = _parity_binding()
    records = (
        ModelArmParityRecord(BaselineKind.SYSTEMATIC_COVERING, binding, 4),
        ModelArmParityRecord(BaselineKind.RANDOM_STRATIFIED, binding, 4),
        ModelArmParityRecord(BaselineKind.FREEFORM_ENGINEER, binding, 4),
        ModelArmParityRecord(BaselineKind.PASSIVE_ZERO_QUERY, binding, 0),
    )
    receipt = verify_model_arm_parity(records)
    assert receipt.non_passive_probe_budget_units == 4
    assert receipt.passive_consumed_units == 0
    assert receipt.no_score_feedback

    drifted = replace(binding, output_token_cap=binding.output_token_cap + 1)
    with pytest.raises(BaselineContractError, match="model/input/output parity"):
        verify_model_arm_parity((*records[:-1], replace(records[-1], binding=drifted)))
    with pytest.raises(BaselineContractError, match="zero-query"):
        ModelArmParityRecord(BaselineKind.PASSIVE_ZERO_QUERY, binding, 1)


def test_human_protocol_losslessly_seals_k0_to_k4_without_narrative_adapter() -> None:
    catalogue = _catalogue()
    bundles = _human_chain(catalogue)
    binding = _human_binding()
    events = tuple(
        HumanPrefixEvent(
            prefix_index=index,
            bundle_digest=bundle.bundle_digest,
            protocol_binding_digest=binding.binding_digest,
            wall_elapsed_millis=index * 1_000,
            active_elapsed_millis=index * 800,
            bundle_edit_events=index + 1,
        )
        for index, bundle in enumerate(bundles)
    )
    receipt = validate_human_bundle_protocol(
        binding=binding,
        operator_identity="independent-engineer-01",
        catalogue=catalogue,
        prefix_bundles=bundles,
        prefix_events=events,
        self_reported_effort="HIGH",
        model_scores_visible=False,
    )

    assert receipt.prefix_bundle_digests == tuple(item.bundle_digest for item in bundles)
    assert receipt.canonical_bundle_bytes == tuple(item.canonical_bytes for item in bundles)
    assert receipt.probe_count == 4
    assert receipt.wall_elapsed_millis == 4_000
    assert receipt.active_elapsed_millis == 3_200
    assert not hasattr(receipt, "narrative")
    assert not hasattr(receipt, "scores")
    assert not hasattr(receipt, "model_token_equivalent")


def test_human_protocol_rejects_backfill_invalid_vectors_and_forbidden_access() -> None:
    catalogue = _catalogue()
    bundles = _human_chain(catalogue)
    binding = _human_binding()
    events = tuple(
        HumanPrefixEvent(
            prefix_index=index,
            bundle_digest=bundle.bundle_digest,
            protocol_binding_digest=binding.binding_digest,
            wall_elapsed_millis=index * 1_000,
            active_elapsed_millis=index * 800,
            bundle_edit_events=1,
        )
        for index, bundle in enumerate(bundles)
    )
    with pytest.raises(HumanProtocolError, match="k=0..4"):
        validate_human_bundle_protocol(
            binding=binding,
            operator_identity="engineer",
            catalogue=catalogue,
            prefix_bundles=bundles[:-1],
            prefix_events=events[:-1],
            self_reported_effort="MEDIUM",
            model_scores_visible=False,
        )
    with pytest.raises(HumanProtocolError, match="model scores"):
        validate_human_bundle_protocol(
            binding=binding,
            operator_identity="engineer",
            catalogue=catalogue,
            prefix_bundles=bundles,
            prefix_events=events,
            self_reported_effort="MEDIUM",
            model_scores_visible=True,
        )
    with pytest.raises(HumanProtocolError, match="forbidden access"):
        replace(binding, network_access_allowed=True)

    assert human_missing_disposition(model_scores_visible=True).replaceable is False
    assert human_missing_disposition(model_scores_visible=True).blocks_strongest_claim
