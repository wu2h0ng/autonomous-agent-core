import pytest

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
    SingleStoreConfig,
    SingleStoreReplayStabilityArm,
    adjudicate,
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


def test_single_store_exact_budget_correction_and_frozen_tuning():
    arm = SingleStoreReplayStabilityArm(SingleStoreConfig(), BUDGET)
    obs = RawObservation((("x", "y"),), ("p", "q"))
    action = arm.act(obs)
    before = arm.decision_state()
    event = FeedbackEvent("e1", obs, action, 1.0)
    arm.observe(event)
    assert (arm.cost().updates, arm.cost().replays) == (2, 2)
    arm.correct(CorrectionEvent("e1"))
    assert arm.decision_state() == before
    frozen = FrozenQualificationConfig.freeze("a" * 64, SingleStoreConfig())
    with pytest.raises(ValueError, match="frozen"):
        frozen.for_result_seed(stability=0.5)


def test_oracle_is_not_in_non_oracle_factory_and_baselines_are_available():
    for name in ("single-store", "reset", "recency", "static", "wsls"):
        assert make_non_oracle_arm(name, BUDGET)
    with pytest.raises(ValueError, match="evaluator-only"):
        make_non_oracle_arm("oracle", BUDGET)


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


def test_kill_rules_are_mechanical_and_ordered():
    base = dict(
        candidate_adaptation=2.0,
        baseline_adaptation=2.5,
        candidate_retention=0.80,
        baseline_retention=0.79,
        candidate_cost=1.0,
        baseline_cost=1.0,
        candidate_safe=True,
        leaked=False,
        key_quality=0.7,
        oracle_gap=0.2,
    )
    assert adjudicate(**base).status == "KILL_TC1"
    assert adjudicate(**replace_metrics(base, leaked=True)).status == "INVALID"
    assert (
        adjudicate(**replace_metrics(base, key_quality=0.96)).status
        == "TRIVIAL_INVALID"
    )


def test_executor_and_hidden_scorer_cover_every_authorized_step():
    plan = EvaluatorFixture.build(11, EpisodeConfig(blocks_per_phase=2))
    arm = SingleStoreReplayStabilityArm(SingleStoreConfig(), BUDGET)
    trace = EpisodeExecutor(feedback_delay=2).execute(plan, arm)
    metrics = HiddenScorer.score(plan, trace)
    assert len(trace.actions) == len(plan.public_steps)
    assert metrics.coverage == 1.0
    assert metrics.total_regret_denominator == len(plan.public_steps)
    assert metrics.return_a_retention >= 0.0


def replace_metrics(values, **changes):
    return values | changes
