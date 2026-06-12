"""G1' falsification experiment (ADR-0010): does relevance realization pay off
once the agent has the organ to act on it, under lethal re-framing?

Shared contextual backbone isolates relevance as the ONLY variable across
B0-B3 (all use ContextualActionModel; same exploit/explore policy; they differ
ONLY in how attention selects cues). B4 swaps in the non-contextual model to
show the contextual organ was the missing piece.

  B0 modulated : AttentionField IP selection      + ContextualActionModel
  B1 fixed     : fixed random m cues (never moves) + ContextualActionModel
  B2 full      : attend all K (pays K*alpha)       + ContextualActionModel
  B3 uniform   : rotating m cues                   + ContextualActionModel
  B4 control   : AttentionField IP selection       + non-contextual model

G1' gate (seeds 0-9; pre-registered in ADR-0010, do not move):
  1. B0 survival > B1 AND > B3, >=7/10 each.
  2. B0 behavioural recovery faster than B1 AND B3, >=7/10 each.
  3. B0 survival > B2, >=7/10 (selective attention is metabolically necessary).
  4. No special-case code for any single ablation.
  5. If B0 fails to beat B3 on BOTH survival and recovery -> claim 2 more
     deeply falsified -> escalate founder (ADR-0010 D5).

Run: PYTHONPATH=src python experiments/cue_shift_g1prime.py
"""
from __future__ import annotations

import random
from collections import deque

from aac.attention import AttentionField
from aac.contextual import ContextualActionModel
from aac.viability import ViabilityCore
from aac.world_model import ActionOutcomeModel
from envs.lethal_cue_foraging import LethalCueForaging

B0, B1, B2, B3, B4 = "B0_mod", "B1_fixed", "B2_full", "B3_uniform", "B4_noctx"
VARIANTS = [B0, B1, B2, B3, B4]

RECOVERY_W = 20
RECOVERY_THETA = 0.7


def _run(variant: str, seed: int, max_steps: int, *, regime_period: int,
         budget: float, metabolic_cost: float, capacity: float,
         safe_budget: float) -> dict:
    rng = random.Random(seed)
    K, k_rel, m, n_actions = 12, 2, 3, 4
    env = LethalCueForaging(K=K, k_rel=k_rel, m=m, n_actions=n_actions,
                            regime_period=regime_period, rng=rng)
    viability = ViabilityCore(budget=budget, metabolic_cost=metabolic_cost,
                              capacity=capacity, safe_budget=safe_budget)
    attention = AttentionField(K=K, m=m)
    cmodel = ContextualActionModel(n_actions=n_actions)
    ncmodel = ActionOutcomeModel(n_actions=n_actions)

    fixed_idx = sorted(rng.sample(range(K), m))

    survived = 0
    regret_sum = 0.0
    recovery: list[int] = []
    since_shift: int | None = None
    window: deque[int] = deque(maxlen=RECOVERY_W)
    last_regime = env.regime_index

    for _ in range(max_steps):
        if not viability.alive:
            break
        cues = env.get_cue_vector()

        # -- attention selection (the ONLY axis that differs B0-B3) ----------
        if variant == B2:
            attended = list(range(K))
        elif variant == B1:
            attended = list(fixed_idx)
        elif variant == B3:
            start = survived % K
            attended = [(start + j) % K for j in range(m)]
        else:  # B0, B4: adaptive IP attention
            attended = attention.select_attention(pressure=viability.pressure)

        env.pay_attention(len(attended), viability)
        observed = env.observe(attended)
        optimal = env.best_action_for(cues)  # decision-time ground truth

        # -- action selection -------------------------------------------------
        if variant == B4:
            explore = 0.1 if attention.should_exploit(ncmodel.total_uncertainty()) else 0.6
            if rng.random() < explore:
                action = rng.randrange(n_actions)
            else:
                action = ncmodel.best_action()
        else:  # contextual variants share one policy
            if cmodel.confident(observed):
                action = cmodel.best_action(observed)
            else:
                action = rng.randrange(n_actions)

        correct = int(action == optimal)
        reward = env.act(action, attended)
        viability.ingest(reward)
        viability.metabolize()

        # -- model update -----------------------------------------------------
        if variant == B4:
            surprise = ncmodel.update(action, reward)
        else:
            q_before = cmodel._q_for(cmodel._key(observed))[action]
            surprise = abs(reward - q_before)
            cmodel.update(observed, action, reward)

        # -- frozen AttentionField dynamics (B0, B4 only) ---------------------
        if variant in (B0, B4):
            attention.update(reward, tuple(cues), attended)
            attention.on_surprise(surprise)
            attention._steps_since_reset += 1

        survived += 1
        regret_sum += env.last_regret

        # -- behavioural recovery (fixed metric, ADR-0010 D4) -----------------
        if env.regime_index != last_regime:
            last_regime = env.regime_index
            since_shift = 0
            window.clear()
        elif since_shift is not None:
            since_shift += 1
            window.append(correct)
            if len(window) == RECOVERY_W and sum(window) / RECOVERY_W >= RECOVERY_THETA:
                recovery.append(since_shift)
                since_shift = None

    return {
        "steps": survived,
        "regret_per_step": round(regret_sum / max(1, survived), 4),
        "mean_recovery": round(sum(recovery) / max(1, len(recovery)), 2) if recovery else None,
        "recoveries": len(recovery),
    }


def main() -> None:
    regime_period = 80
    max_steps = max(1600, regime_period * 20)
    seeds = list(range(10))
    params = dict(regime_period=regime_period, budget=120.0, metabolic_cost=0.1,
                  capacity=200.0, safe_budget=50.0)

    results: dict[str, list[dict]] = {v: [] for v in VARIANTS}
    print(f"regime_period={regime_period}  max_steps={max_steps}  params={params}")
    print(f"{'seed':>4}  " + "  ".join(f"{v:>10}:steps/recov" for v in VARIANTS))
    for seed in seeds:
        row = f"{seed:>4}  "
        cells = []
        for v in VARIANTS:
            r = _run(v, seed, max_steps, **params)
            results[v].append(r)
            rec = r["mean_recovery"]
            cells.append(f"{r['steps']:>6d}/{('--' if rec is None else f'{rec:.0f}'):>4}")
        print(row + "  ".join(f"{c:>13}" for c in cells))

    n = len(seeds)
    print("\n" + "=" * 72 + "\nAGGREGATE (mean steps | mean recovery | #recoveries):")
    for v in VARIANTS:
        steps = sum(r["steps"] for r in results[v]) / n
        recs = [r["mean_recovery"] for r in results[v] if r["mean_recovery"] is not None]
        mr = sum(recs) / len(recs) if recs else float("nan")
        nrec = sum(r["recoveries"] for r in results[v])
        print(f"  {v:>10}: steps={steps:7.1f}  recovery={mr:6.2f}  #rec={nrec}")

    # -- G1' pre-registered gate (ADR-0010) -------------------------------
    mod, b1, b2, b3 = results[B0], results[B1], results[B2], results[B3]

    def beats_steps(other: list[dict]) -> int:
        return sum(1 for i in range(n) if mod[i]["steps"] > other[i]["steps"])

    def beats_recovery(other: list[dict]) -> int:
        # faster recovery = smaller mean_recovery; a variant that never recovers
        # (None) loses. B0 wins the seed if it recovered and other did better-or-not.
        won = 0
        for i in range(n):
            mr = mod[i]["mean_recovery"]
            orr = other[i]["mean_recovery"]
            if mr is None:
                continue  # B0 didn't recover -> not a win
            if orr is None or mr < orr:
                won += 1
        return won

    s_b1, s_b3, s_b2 = beats_steps(b1), beats_steps(b3), beats_steps(b2)
    r_b1, r_b3 = beats_recovery(b1), beats_recovery(b3)

    print("\n" + "=" * 72 + "\nG1' PRE-REGISTERED GATE:")
    print(f"  1. B0 steps > B1: {s_b1}/{n} ; > B3: {s_b3}/{n}   (need >=7 each)")
    print(f"  2. B0 recovery faster than B1: {r_b1}/{n} ; than B3: {r_b3}/{n}  (need >=7 each)")
    print(f"  3. B0 steps > B2: {s_b2}/{n}   (need >=7)")
    c1 = s_b1 >= 7 and s_b3 >= 7
    c2 = r_b1 >= 7 and r_b3 >= 7
    c3 = s_b2 >= 7
    verdict = "MET" if (c1 and c2 and c3) else "NOT MET"
    print(f"\n  G1': {verdict}")
    if verdict == "NOT MET" and not (s_b3 >= 7 and r_b3 >= 7):
        print("  -> D5 trigger: B0 fails to beat B3 on both axes; escalate founder "
              "for claim-2 final disposition (ADR-0010 D5).")


if __name__ == "__main__":
    main()
