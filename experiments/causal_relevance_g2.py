"""G2 falsification experiment for claim 2 (ADR-0011).

Run:
    PYTHONPATH=src python experiments/causal_relevance_g2.py

The parameters below are declared before the first G2 run and must not be
tuned after seeing results.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from aac.attention import AttentionField
from aac.causal_relevance import CausalRelevanceField
from aac.contextual import ContextualActionModel
from aac.factorized_contextual import (
    Candidate,
    FactorizedContextualActionModel,
    candidate_sets_from_attended,
)
from aac.viability import ViabilityCore
from envs.scheduled_cue_foraging import (
    ScheduledLethalCueForaging,
    generate_balanced_relevant_sets,
    max_fixed_subset_coverage,
)


B0 = "G2_B0_causal"
B1 = "G2_B1_fixed"
B2 = "G2_B2_full"
B3 = "G2_B3_uniform"
B4 = "G2_B4_g1prime"
B5 = "G2_B5_random_posterior"
VARIANTS = [B0, B1, B2, B3, B4, B5]

K = 12
K_REL = 2
M = 3
N_ACTIONS = 4
N_REGIMES = 20
REGIME_PERIOD = 60
MAX_STEPS = N_REGIMES * REGIME_PERIOD
ADAPTATION_H = 40

BUDGET = 250.0
CAPACITY = 300.0
SAFE_BUDGET = 80.0
METABOLIC_COST = 0.05
REWARD_HIT = 2.0
REWARD_MISS = -1.5
NOISE = 0.3
ATTENTION_COST = 0.08
MAX_FIXED_COVER_FRACTION = 0.25


@dataclass(frozen=True)
class G2Verdict:
    verdict: str
    steps_b1: int
    steps_b3: int
    steps_b4: int
    adaptation_b1: int
    adaptation_b3: int
    adaptation_b4: int
    steps_b2: int
    adaptation_b5: int


def _build_env(seed: int, schedule: list[tuple[int, ...]]) -> ScheduledLethalCueForaging:
    return ScheduledLethalCueForaging(
        relevant_sets=schedule,
        K=K,
        k_rel=K_REL,
        m=M,
        n_actions=N_ACTIONS,
        regime_period=REGIME_PERIOD,
        reward_hit=REWARD_HIT,
        reward_miss=REWARD_MISS,
        noise=NOISE,
        attention_cost=ATTENTION_COST,
        rng=random.Random(20_000 + seed),
    )


def _factorized_policy(
    rng: random.Random,
    model: FactorizedContextualActionModel,
    cues: tuple[int, ...],
    candidates: list[Candidate],
) -> tuple[int, Candidate | None]:
    hypothesis = model.best_hypothesis(cues, candidates)
    if hypothesis is not None and model.confident(cues, hypothesis):
        return model.best_action(cues, hypothesis), hypothesis
    return rng.randrange(N_ACTIONS), hypothesis


def _causal_policy(
    rng: random.Random,
    field: CausalRelevanceField,
    model: FactorizedContextualActionModel,
    cues: tuple[int, ...],
    candidates: list[Candidate],
) -> tuple[int, Candidate | None]:
    hypothesis = field.best_hypothesis()
    if hypothesis not in candidates:
        hypothesis = model.best_hypothesis(cues, candidates)
    if (
        hypothesis is not None
        and field.confidence() >= field.confidence_threshold
        and model.confident(cues, hypothesis)
    ):
        return model.best_action(cues, hypothesis), hypothesis
    return rng.randrange(N_ACTIONS), hypothesis


def _update_factorized_candidates(
    model: FactorizedContextualActionModel,
    cues: tuple[int, ...],
    candidates: list[Candidate],
    action: int,
    reward: float,
) -> None:
    for candidate in candidates:
        model.update(cues, candidate, action, reward)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _run_variant(variant: str, seed: int, schedule: list[tuple[int, ...]]) -> dict[str, float]:
    rng = random.Random(10_000 + seed)
    env = _build_env(seed, schedule)
    viability = ViabilityCore(
        budget=BUDGET,
        metabolic_cost=METABOLIC_COST,
        capacity=CAPACITY,
        safe_budget=SAFE_BUDGET,
    )
    causal = CausalRelevanceField(K=K, k_rel=K_REL, m=M)
    random_causal = CausalRelevanceField(K=K, k_rel=K_REL, m=M, ablate_posterior=True)
    factorized = FactorizedContextualActionModel(n_actions=N_ACTIONS)
    attention = AttentionField(K=K, m=M)
    contextual = ContextualActionModel(n_actions=N_ACTIONS)
    fixed_idx = sorted(random.Random(30_000 + seed).sample(range(K), M))

    steps = 0
    regret_sum = 0.0
    adaptation_areas: list[float] = []
    current_window: list[int] | None = None
    remaining_adaptation = 0

    for _ in range(MAX_STEPS):
        if not viability.alive:
            break
        cues = env.get_cue_vector()

        if variant == B0:
            attended = causal.select_attention(pressure=viability.pressure, rng=rng)
        elif variant == B1:
            attended = list(fixed_idx)
        elif variant == B2:
            attended = list(range(K))
        elif variant == B3:
            start = steps % K
            attended = [(start + j) % K for j in range(M)]
        elif variant == B4:
            attended = attention.select_attention(pressure=viability.pressure)
        elif variant == B5:
            attended = random_causal.select_attention(pressure=viability.pressure, rng=rng)
        else:
            raise ValueError(f"unknown variant {variant}")

        env.pay_attention(len(attended), viability)
        observed = env.observe(attended)
        optimal = env.best_action_for(cues)
        candidates = candidate_sets_from_attended(attended, K_REL)

        if variant == B0:
            action, _ = _causal_policy(rng, causal, factorized, cues, candidates)
            prediction_before = {
                c: factorized.value(cues, c, action) for c in candidates
            }
        elif variant == B4:
            if contextual.confident(observed):
                action = contextual.best_action(observed)
            else:
                action = rng.randrange(N_ACTIONS)
            q_before = contextual._q_for(contextual._key(observed))[action]
            prediction_before = {}
        else:
            action, _ = _factorized_policy(rng, factorized, cues, candidates)
            prediction_before = {
                c: factorized.value(cues, c, action) for c in candidates
            }

        correct = int(action == optimal)
        if remaining_adaptation > 0 and current_window is not None:
            current_window.append(correct)
            remaining_adaptation -= 1
            if remaining_adaptation == 0:
                adaptation_areas.append(sum(current_window) / ADAPTATION_H)
                current_window = None

        old_regime = env.regime_index
        reward = env.act(action, attended)
        viability.ingest(reward)
        viability.metabolize()

        if variant == B4:
            surprise = abs(reward - q_before)
            contextual.update(observed, action, reward)
            attention.update(reward, tuple(cues), attended)
            attention.on_surprise(surprise)
            attention._steps_since_reset += 1
        else:
            if candidates:
                best_error = min(abs(reward - pred) for pred in prediction_before.values())
            else:
                best_error = abs(reward)
            _update_factorized_candidates(factorized, cues, candidates, action, reward)
            if variant == B0:
                causal.on_surprise(best_error)
                causal.update(cues, attended, action, reward, prediction_before)
            elif variant == B5:
                random_causal.update(cues, attended, action, reward, prediction_before)

        steps += 1
        regret_sum += env.last_regret

        if env.regime_index != old_regime:
            if current_window is not None and remaining_adaptation > 0:
                current_window.extend([0] * remaining_adaptation)
                adaptation_areas.append(sum(current_window) / ADAPTATION_H)
            current_window = []
            remaining_adaptation = ADAPTATION_H

    if current_window is not None and remaining_adaptation > 0:
        current_window.extend([0] * remaining_adaptation)
        adaptation_areas.append(sum(current_window) / ADAPTATION_H)

    return {
        "steps": float(steps),
        "regret_per_step": regret_sum / max(1, steps),
        "adaptation_area": _mean(adaptation_areas),
        "adaptation_windows": float(len(adaptation_areas)),
    }


def judge_g2(results: dict[str, list[dict[str, float]]]) -> G2Verdict:
    n = len(results[B0])
    b0 = results[B0]

    def wins(metric: str, other: str) -> int:
        return sum(1 for i in range(n) if b0[i][metric] > results[other][i][metric])

    verdict = G2Verdict(
        verdict="",
        steps_b1=wins("steps", B1),
        steps_b3=wins("steps", B3),
        steps_b4=wins("steps", B4),
        adaptation_b1=wins("adaptation_area", B1),
        adaptation_b3=wins("adaptation_area", B3),
        adaptation_b4=wins("adaptation_area", B4),
        steps_b2=wins("steps", B2),
        adaptation_b5=wins("adaptation_area", B5),
    )
    met = (
        verdict.steps_b1 >= 7
        and verdict.steps_b3 >= 7
        and verdict.steps_b4 >= 7
        and verdict.adaptation_b1 >= 7
        and verdict.adaptation_b3 >= 7
        and verdict.adaptation_b4 >= 7
        and verdict.steps_b2 >= 7
        and verdict.adaptation_b5 >= 8
    )
    return G2Verdict(
        verdict="MET" if met else "NOT MET",
        steps_b1=verdict.steps_b1,
        steps_b3=verdict.steps_b3,
        steps_b4=verdict.steps_b4,
        adaptation_b1=verdict.adaptation_b1,
        adaptation_b3=verdict.adaptation_b3,
        adaptation_b4=verdict.adaptation_b4,
        steps_b2=verdict.steps_b2,
        adaptation_b5=verdict.adaptation_b5,
    )


def main() -> None:
    seeds = list(range(10))
    results: dict[str, list[dict[str, float]]] = {v: [] for v in VARIANTS}
    print("G2 parameters (ADR-0011, fixed before first run):")
    print(
        f"K={K} k_rel={K_REL} m={M} regimes={N_REGIMES} "
        f"regime_period={REGIME_PERIOD} max_steps={MAX_STEPS}"
    )
    print(
        f"budget={BUDGET} capacity={CAPACITY} metabolic={METABOLIC_COST} "
        f"attention_cost={ATTENTION_COST} rewards=({REWARD_HIT},{REWARD_MISS})"
    )
    print(f"{'seed':>4}  " + "  ".join(f"{v:>22}:steps/adapt" for v in VARIANTS))

    for seed in seeds:
        schedule = generate_balanced_relevant_sets(
            K=K,
            k_rel=K_REL,
            m=M,
            n_regimes=N_REGIMES,
            rng=random.Random(40_000 + seed),
            max_cover_fraction=MAX_FIXED_COVER_FRACTION,
        )
        cover = max_fixed_subset_coverage(schedule, K, M)
        cells = []
        for variant in VARIANTS:
            row = _run_variant(variant, seed, schedule)
            results[variant].append(row)
            cells.append(f"{row['steps']:5.0f}/{row['adaptation_area']:.2f}")
        print(f"{seed:>4}  " + "  ".join(f"{c:>22}" for c in cells) + f"  cover={cover}")

    print("\nAGGREGATE:")
    for variant in VARIANTS:
        rows = results[variant]
        print(
            f"  {variant:>22}: "
            f"steps={_mean([r['steps'] for r in rows]):7.1f}  "
            f"adapt={_mean([r['adaptation_area'] for r in rows]):.3f}  "
            f"regret={_mean([r['regret_per_step'] for r in rows]):.3f}"
        )

    verdict = judge_g2(results)
    print("\nG2 PRE-REGISTERED GATE:")
    print(
        f"  steps: B0>B1 {verdict.steps_b1}/10, "
        f"B0>B3 {verdict.steps_b3}/10, B0>B4 {verdict.steps_b4}/10 (need >=7)"
    )
    print(
        f"  adaptation: B0>B1 {verdict.adaptation_b1}/10, "
        f"B0>B3 {verdict.adaptation_b3}/10, B0>B4 {verdict.adaptation_b4}/10 (need >=7)"
    )
    print(f"  metabolic: B0>B2 steps {verdict.steps_b2}/10 (need >=7)")
    print(f"  ablation: B0>B5 adaptation {verdict.adaptation_b5}/10 (need >=8)")
    print(f"\n  G2: {verdict.verdict}")


if __name__ == "__main__":
    main()
