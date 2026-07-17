import pytest
from dataclasses import replace

from experiments.continual_retention_f1 import (
    ArmBudget,
    CorrectionEvent,
    DualStoreRetentionArm,
    EpisodeConfig,
    EvaluatorFixture,
    EpisodeExecutor,
    FeedbackEvent,
    FrozenQualificationConfig,
    RawObservation,
    HiddenScorer,
    OperationMeter,
    QualificationTrial,
    SingleStoreConfig,
    SingleStoreReplayStabilityArm,
    adjudicate,
    freeze_strongest_single_store,
    make_non_oracle_arm,
)


BUDGET = ArmBudget(2, 2)


def test_contracts_are_closed_and_budget_is_positive():
    obs = RawObservation((("f", "v"),), ("a", "b"))
    assert set(obs.to_dict()) == {"features", "authorized_actions"}
    assert not {"seed", "phase", "context_id", "optimal_action"} & set(obs.to_dict())
    with pytest.raises(ValueError):
        ArmBudget(0, 1)


def test_fixture_is_balanced_and_hides_context_and_action_truth():
    plan = EvaluatorFixture.build(7, EpisodeConfig(blocks_per_phase=2))
    assert len(plan.changed_contexts) == len(plan.unchanged_contexts) == 4
    assert {step.phase for step in plan.latent_steps} == {"A1", "B", "A2"}
    assert all(
        set(step.observation.to_dict()) == {"features", "authorized_actions"}
        for step in plan.public_steps
    )
    other = EvaluatorFixture.build(8, EpisodeConfig(blocks_per_phase=2))
    assert plan.phase_lengths != other.phase_lengths
    counts = {
        feature: sum(step.observation.features == feature for step in plan.public_steps)
        for feature in {step.observation.features for step in plan.public_steps}
    }
    assert len(set(counts.values())) > 1


def test_single_store_exact_budget_correction_and_frozen_tuning():
    arm = SingleStoreReplayStabilityArm(SingleStoreConfig(), BUDGET)
    obs = RawObservation((("x", "y"),), ("p", "q"))
    action = arm.act(obs)
    before = arm.decision_state()
    event = FeedbackEvent("e1", obs, action, 1.0)
    meter = OperationMeter(BUDGET)
    arm = SingleStoreReplayStabilityArm(SingleStoreConfig(), BUDGET)
    arm.bind_meter(meter)
    arm.observe(event)
    assert meter.snapshot().updates == 2
    assert meter.snapshot().replays == 0
    arm.correct(CorrectionEvent("e1"))
    assert arm.decision_state() == before
    with pytest.raises(ValueError, match="invalidated"):
        arm.observe(event)
    frozen = FrozenQualificationConfig.freeze("a" * 64, SingleStoreConfig())
    with pytest.raises(ValueError, match="frozen"):
        frozen.for_result_seed(stability=0.5)


def test_oracle_is_not_in_non_oracle_factory_and_baselines_are_available():
    for name in ("single-store", "reset", "recency", "static", "wsls"):
        assert make_non_oracle_arm(name, BUDGET)
    with pytest.raises(ValueError, match="evaluator-only"):
        make_non_oracle_arm("oracle", BUDGET)


def test_qualification_search_is_equal_metered_and_frozen():
    meter = OperationMeter(BUDGET)
    trials = (
        QualificationTrial(SingleStoreConfig(stability=0.1), 0.7),
        QualificationTrial(SingleStoreConfig(stability=0.4), 0.8),
    )
    frozen = freeze_strongest_single_store(
        qualification_seed_digest="b" * 64,
        baseline_trials=trials,
        candidate_search_trials=2,
        meter=meter,
    )
    assert frozen.selected.stability == 0.4
    assert frozen.search_trials == meter.snapshot().search_trials == 2
    with pytest.raises(ValueError, match="exactly equal"):
        freeze_strongest_single_store(
            qualification_seed_digest="b" * 64,
            baseline_trials=trials,
            candidate_search_trials=1,
            meter=OperationMeter(BUDGET),
        )


def test_single_store_uses_reservoir_not_last_n_replay():
    config = SingleStoreConfig(reservoir_size=2)
    arm = SingleStoreReplayStabilityArm(config, BUDGET)
    observation = RawObservation((("opaque", "context"),), ("a", "b"))
    for index in range(8):
        arm.observe(FeedbackEvent(f"event-{index}", observation, "a", float(index % 2)))
    assert arm.reservoir_event_digests != ("event-6", "event-7")


def test_cheap_baselines_have_distinct_public_update_rules():
    obs = RawObservation((("ctx", "value"),), ("a", "b", "c", "d"))
    arms = {
        name: make_non_oracle_arm(name, BUDGET)
        for name in ("reset", "recency", "static", "wsls")
    }
    for index in range(20):
        for arm in arms.values():
            action = arm.act(obs)
            arm.observe(
                FeedbackEvent(
                    f"{index}-{type(arm).__name__}", obs, action, float(index % 2)
                )
            )
    assert len({arm.decision_state() for arm in arms.values()}) >= 3


def test_dual_store_is_equivariant_under_action_renaming():
    left_obs = RawObservation((("d1", "v1"),), ("a", "b"))
    right_obs = RawObservation((("renamed", "value"),), ("x", "y"))
    left = DualStoreRetentionArm(BUDGET)
    right = DualStoreRetentionArm(BUDGET)
    assert {"a": "x", "b": "y"}[left.act(left_obs)] == right.act(right_obs)


def test_full_learned_trajectory_is_equivariant_under_opaque_renaming():
    plan = EvaluatorFixture.build(31, EpisodeConfig(blocks_per_phase=2))
    action_tokens = plan.public_steps[0].observation.authorized_actions
    action_map = {
        token: f"renamed-{index}" for index, token in enumerate(action_tokens)
    }
    feature_tokens = {
        token
        for step in plan.public_steps
        for pair in step.observation.features
        for token in pair
    }
    feature_map = {
        token: f"opaque-{index}" for index, token in enumerate(sorted(feature_tokens))
    }

    def map_observation(observation):
        return RawObservation(
            tuple(
                (feature_map[key], feature_map[value])
                for key, value in observation.features
            ),
            tuple(action_map[action] for action in observation.authorized_actions),
        )

    mapped = replace(
        plan,
        public_steps=tuple(
            replace(step, observation=map_observation(step.observation))
            for step in plan.public_steps
        ),
        latent_steps=tuple(
            replace(step, optimal_action=action_map[step.optimal_action])
            for step in plan.latent_steps
        ),
    )
    left = EpisodeExecutor().execute(plan, DualStoreRetentionArm(BUDGET))
    right = EpisodeExecutor().execute(mapped, DualStoreRetentionArm(BUDGET))
    assert tuple(action_map[action] for action in left.actions) == right.actions
    assert left.rewards == right.rewards
    assert (
        HiddenScorer.score(plan, left).metrics
        == HiddenScorer.score(mapped, right).metrics
    )


def test_dual_store_slow_prototypes_are_consumed_and_behavior_is_distinct():
    obs = RawObservation((("ctx", "opaque"),), ("a", "b"))
    dual = DualStoreRetentionArm(BUDGET)
    single = SingleStoreReplayStabilityArm(
        SingleStoreConfig(learning_rate=0.7, stability=0.35), BUDGET
    )
    dual.bind_meter(OperationMeter(BUDGET))
    single.bind_meter(OperationMeter(BUDGET))
    stream = (
        FeedbackEvent("a-good", obs, "a", 1.0),
        FeedbackEvent("a-bad", obs, "a", 0.0),
        FeedbackEvent("b-good", obs, "b", 1.0),
        FeedbackEvent("b-bad", obs, "b", 0.0),
    )
    for event in stream:
        dual.observe(event)
        single.observe(event)
    assert dual.prototype_versions(obs) >= 2
    assert dual.retrieval_count > 0
    assert dual.decision_state() != single.decision_state()


def test_kill_rules_are_typed_mechanical_and_all_reachable():
    plan = EvaluatorFixture.build(13, EpisodeConfig(blocks_per_phase=2))
    candidate = HiddenScorer.score(
        plan, EpisodeExecutor().execute(plan, DualStoreRetentionArm(BUDGET))
    )
    baseline = HiddenScorer.score(
        plan,
        EpisodeExecutor().execute(
            plan, SingleStoreReplayStabilityArm(SingleStoreConfig(), BUDGET)
        ),
    )
    oracle = HiddenScorer.oracle_ceiling(plan)
    assert adjudicate(candidate, (baseline,), oracle).status in {
        "KILL_TC1",
        "NO_ADOPT",
        "OVERHEAD",
        "TRIVIAL_INVALID",
        "QUALIFIED_FOR_RESULT_FREEZE_REVIEW",
    }
    assert (
        adjudicate(replace(candidate, custody_valid=False), (baseline,), oracle).status
        == "INVALID"
    )
    assert (
        adjudicate(
            replace(candidate, correction_valid=False), (baseline,), oracle
        ).status
        == "INVALID"
    )
    safe_oracle = oracle
    no_adopt_candidate = replace(
        candidate,
        metrics=replace(
            candidate.metrics,
            adaptation_speed=baseline.metrics.adaptation_speed + 20,
            return_a_retention=baseline.metrics.return_a_retention + 0.10,
        ),
    )
    assert adjudicate(no_adopt_candidate, (baseline,), safe_oracle).status == "NO_ADOPT"
    overhead_candidate = replace(
        candidate,
        metrics=replace(
            candidate.metrics,
            adaptation_speed=max(0, baseline.metrics.adaptation_speed - 20),
            return_a_retention=baseline.metrics.return_a_retention + 0.04,
            negative_transfer=0.0,
            correction_rollback_latency=0,
            post_correction_wrong_actions=0,
        ),
        cost=replace(candidate.cost, updates=max(1, baseline.cost.charged_work * 3)),
    )
    assert adjudicate(overhead_candidate, (baseline,), safe_oracle).status == "OVERHEAD"
    survivor = replace(
        overhead_candidate,
        metrics=replace(overhead_candidate.metrics, return_a_retention=1.0),
        cost=baseline.cost,
    )
    assert (
        adjudicate(survivor, (baseline,), safe_oracle).status
        == "QUALIFIED_FOR_RESULT_FREEZE_REVIEW"
    )


def test_executor_and_hidden_scorer_cover_every_authorized_step():
    plan = EvaluatorFixture.build(11, EpisodeConfig(blocks_per_phase=2))
    arm = SingleStoreReplayStabilityArm(SingleStoreConfig(), BUDGET)
    trace = EpisodeExecutor(feedback_delay=2).execute(plan, arm)
    scored = HiddenScorer.score(plan, trace)
    metrics = scored.metrics
    assert len(trace.actions) == len(plan.public_steps)
    assert metrics.coverage == 1.0
    assert metrics.total_regret_denominator == len(plan.public_steps)
    assert metrics.return_a_retention >= 0.0
    assert trace.cost.updates > 0
    assert trace.correction_receipts
    corrupted = next(item for item in trace.feedback_receipts if item.corrupted)
    assert corrupted.delivered_reward == 1.0 - trace.rewards[corrupted.action_turn]
    assert metrics.correction_rollback_latency >= 0
    with pytest.raises(ValueError, match="sealed"):
        type(trace)(
            trace.arm_id,
            trace.actions,
            trace.rewards,
            trace.feedback_receipts,
            trace.correction_receipts,
            trace.cost,
            trace.budget,
            trace.action_digest,
            trace.seal_digest,
        )

    object.__setattr__(trace, "action_digest", "0" * 64)
    with pytest.raises(ValueError, match="digest"):
        HiddenScorer.score(plan, trace)


def test_executor_rejects_arm_that_exceeds_external_budget():
    class OverBudgetArm(SingleStoreReplayStabilityArm):
        def observe(self, feedback):
            super().observe(feedback)
            assert self._meter is not None
            self._meter.update(self.budget.max_updates_per_feedback + 1)

    plan = EvaluatorFixture.build(19, EpisodeConfig(blocks_per_phase=2))
    with pytest.raises(RuntimeError, match="operation budget"):
        EpisodeExecutor().execute(plan, OverBudgetArm(SingleStoreConfig(), BUDGET))


def replace_metrics(values, **changes):
    return values | changes
