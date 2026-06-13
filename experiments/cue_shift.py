"""G1 falsification experiment: AttentionField ablations on LatentCueForaging.

Ablation bodies (ADR-0002 pre-registered):
  A1  Fixed random attention (never reallocates).
  A2  Full attention (m=K, pays K*alpha per step).
  A3  Uniform exploration (attention rotates evenly + fixed explore rate,
      i.e. v0 spirit migrated to the cue environment).

Modulated body = full AttentionField (IP-based allocation + exploit gate
+ pressure-shrunk budget).

G1 gate (seeds 0-9, >=1000 steps each, default env params):
  1. Modulated beats A1 AND A3 on per-step regret AND post-shift recovery
     in >=7/10 seeds each.
  2. Modulated has better survival/avg budget than A2 (selective attention
     is metabolically necessary under attention cost).
  3. No special-case code for any single ablation.

Run: PYTHONPATH=src python experiments/cue_shift.py
"""

from __future__ import annotations

import random
import sys

from aac.attention import AttentionField
from aac.policy import PolicySelector
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from aac.world_model import ActionOutcomeModel
from envs.cue_foraging import LatentCueForaging


# -- variant constants ----------------------------------------------------
MODULATED = "modulated"
A1_FIXED = "a1_fixed"
A2_FULL = "a2_full"
A3_UNIFORM = "a3_uniform"


def _run_variant(
    variant: str,
    seed: int,
    max_steps: int = 1200,
    K: int = 12,
    k_rel: int = 2,
    m: int = 3,
    n_actions: int = 4,
    regime_period: int = 60,
    reward_hit: float = 3.0,
    reward_miss: float = -0.5,
    noise: float = 0.3,
    attention_cost: float = 0.2,
    # Environment-validity parameters (ADR-0002: may fix env, not mechanism):
    budget: float = 80.0,
    metabolic_cost: float = 0.3,
    capacity: float = 120.0,
    safe_budget: float = 60.0,
) -> dict:
    """Run one seed of one variant; return metrics dict."""
    rng = random.Random(seed)
    # A2 needs m=K so it CAN attend all cues (and pays K*alpha).
    effective_m = K if variant == A2_FULL else m
    env = LatentCueForaging(
        K=K, k_rel=k_rel, m=effective_m, n_actions=n_actions,
        regime_period=regime_period, reward_hit=reward_hit,
        reward_miss=reward_miss, noise=noise,
        attention_cost=attention_cost, rng=rng,
    )
    shell = CorrigibilityShell()
    viability = ViabilityCore(
        budget=budget, metabolic_cost=metabolic_cost,
        capacity=capacity, safe_budget=safe_budget,
    )
    model = ActionOutcomeModel(n_actions=n_actions)
    policy = PolicySelector(rng=rng)
    attention = AttentionField(K=K, m=m)

    # A1: pre-rolled fixed random attention indices (never change)
    a1_fixed_indices = list(range(min(m, K)))
    rng.shuffle(a1_fixed_indices)
    a1_fixed_indices = sorted(a1_fixed_indices[:m])

    survived = 0
    regret_sum = 0.0
    budget_sum = 0.0
    last_regime = env.regime_index
    recovery: list[int] = []
    since_shift: int | None = None

    for _ in range(max_steps):
        if shell.paused or not viability.alive:
            break

        cues = env.get_cue_vector()

        # -- attention selection (variant-dependent) ----------------------
        if variant == A2_FULL:
            attended = list(range(K))
        elif variant == A1_FIXED:
            attended = list(a1_fixed_indices)
        elif variant == A3_UNIFORM:
            # Rotate: pick m cues starting from (step % K)
            start = survived % K
            attended = [(start + j) % K for j in range(m)]
        else:  # MODULATED
            attended = attention.select_attention(pressure=viability.pressure)

        # -- pay attention cost -------------------------------------------
        env.pay_attention(len(attended), viability)

        # -- observe attended cues ----------------------------------------
        env.observe(attended)

        # -- action selection ---------------------------------------------
        policy.forbidden = shell.forbidden
        if variant == A3_UNIFORM:
            # Fixed explore rate (v0 spirit)
            explore = 0.5
        elif variant in (MODULATED,):
            if attention.should_exploit(model.total_uncertainty()):
                explore = 0.1  # low → exploit
            else:
                explore = 0.7  # high → explore
        else:
            # A1, A2: use AttentionField's explore drive
            attention.sync_explore_drive(model.total_uncertainty())
            explore = attention.explore_drive

        action = policy.select(model, explore, viability.pressure)
        reward = env.act(action, attended)
        viability.ingest(reward)
        viability.metabolize()
        surprise = model.update(action, reward)

        # -- update attention field (all variants that have it) -----------
        if variant != A3_UNIFORM:
            cue_tuple = tuple(cues[i] for i in range(K))
            attention.update(reward, cue_tuple, attended)
            # v1.1: feed surprise for regime-shift detection (ADR-0004)
            attention.on_surprise(surprise)
        # v1.1: advance step counter for uniform window tracking
        attention._steps_since_reset += 1

        survived += 1
        regret_sum += env.last_regret
        budget_sum += viability.budget

        # -- track regime shifts and recovery -----------------------------
        if env.regime_index != last_regime:
            last_regime = env.regime_index
            since_shift = 0
        elif since_shift is not None:
            since_shift += 1
            if model.best_action() == env.best_action_for(env.get_cue_vector()):
                recovery.append(since_shift)
                since_shift = None

    return {
        "steps": survived,
        "regret_per_step": round(regret_sum / max(1, survived), 4),
        "mean_recovery": round(sum(recovery) / max(1, len(recovery)), 2),
        "recoveries": len(recovery),
        "avg_budget": round(budget_sum / max(1, survived), 2),
    }


def main() -> None:
    # CLI: --regime-period N (default 60)
    regime_period = 60
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--regime-period" and i < len(sys.argv) - 1:
            regime_period = int(sys.argv[i + 1])
    max_steps = max(1200, regime_period * 20)  # ~20 regime shifts

    seeds = list(range(10))
    variants = [MODULATED, A1_FIXED, A2_FULL, A3_UNIFORM]
    results: dict[str, list[dict]] = {v: [] for v in variants}

    # -- header -----------------------------------------------------------
    print(f"regime_period={regime_period}  max_steps={max_steps}")
    header = f"{'seed':>4}"
    for v in variants:
        header += f"  {v:>10} regret  recov  steps  budget"
    print(header)

    for seed in seeds:
        line = f"{seed:>4}"
        for v in variants:
            r = _run_variant(v, seed=seed, max_steps=max_steps,
                             regime_period=regime_period)
            results[v].append(r)
            line += f"  {r['regret_per_step']:>10.4f} {r['mean_recovery']:>6.2f} {r['steps']:>6d} {r['avg_budget']:>7.2f}"
        print(line)

    # -- aggregate --------------------------------------------------------
    n = len(seeds)
    print(f"\n{'='*80}")
    print("AGGREGATE:")
    for v in variants:
        avg_regret = sum(r["regret_per_step"] for r in results[v]) / n
        avg_recov = sum(r["mean_recovery"] for r in results[v]) / n
        avg_steps = sum(r["steps"] for r in results[v]) / n
        avg_budget = sum(r["avg_budget"] for r in results[v]) / n
        print(f"  {v:>10}: regret={avg_regret:.4f}  recovery={avg_recov:.2f}  "
              f"steps={avg_steps:.0f}  budget={avg_budget:.2f}")

    # -- G1 gate ----------------------------------------------------------
    mod = results[MODULATED]

    # Criterion 1a: modulated beats A1 on regret AND recovery >=7/10
    a1 = results[A1_FIXED]
    regret_beats_a1 = sum(
        1 for i in range(n)
        if mod[i]["regret_per_step"] < a1[i]["regret_per_step"]
    )
    recov_beats_a1 = sum(
        1 for i in range(n)
        if mod[i]["mean_recovery"] < a1[i]["mean_recovery"]
    )

    # Criterion 1b: modulated beats A3 on regret AND recovery >=7/10
    a3 = results[A3_UNIFORM]
    regret_beats_a3 = sum(
        1 for i in range(n)
        if mod[i]["regret_per_step"] < a3[i]["regret_per_step"]
    )
    recov_beats_a3 = sum(
        1 for i in range(n)
        if mod[i]["mean_recovery"] < a3[i]["mean_recovery"]
    )

    # Criterion 2: modulated survives better than A2 (avg budget/steps)
    a2 = results[A2_FULL]
    mod_avg_budget = sum(r["avg_budget"] for r in mod) / n
    a2_avg_budget = sum(r["avg_budget"] for r in a2) / n
    budget_better = mod_avg_budget > a2_avg_budget

    print(f"\n{'='*80}")
    print("G1 PRE-REGISTERED GATE:")
    print(f"  1a. Modulated regret < A1 in {regret_beats_a1}/{n} seeds (need >=7)")
    print(f"  1a. Modulated recovery < A1 in {recov_beats_a1}/{n} seeds (need >=7)")
    print(f"  1b. Modulated regret < A3 in {regret_beats_a3}/{n} seeds (need >=7)")
    print(f"  1b. Modulated recovery < A3 in {recov_beats_a3}/{n} seeds (need >=7)")
    print(f"  2.  Modulated avg budget ({mod_avg_budget:.2f}) > A2 ({a2_avg_budget:.2f}): {budget_better}")

    c1a = regret_beats_a1 >= 7 and recov_beats_a1 >= 7
    c1b = regret_beats_a3 >= 7 and recov_beats_a3 >= 7
    c2 = budget_better
    verdict = "MET" if (c1a and c1b and c2) else "NOT MET"
    print(f"\n  G1: {verdict}")


if __name__ == "__main__":
    main()
