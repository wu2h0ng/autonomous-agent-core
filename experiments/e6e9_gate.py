"""E6/E9 self-maintenance verification on G11 MultiObjectiveEnv.

Tests whether AgentSelfModelUpdater, OrganRegulator, and SelfMaintenanceLoop
improve G10 decisions in a multi-objective regime-shifting environment.

No LLM calls — pure deterministic mechanisms. Fast to run.

Arms:
  P0_FROZEN        — G10 gate + uniform weights (existing baseline)
  P0_E6_SELF       — G10 + AgentSelfModelUpdater (runtime confidence calibration)
  P0_E9_MAINT      — G10 + SelfMaintenanceLoop (periodic health checks)
  P0_E6E9          — G10 + both E6 and E9

Run: PYTHONPATH=src python experiments/e6e9_gate.py
"""

from __future__ import annotations

import math
import random
import sys

from aac.agent import Agent
from aac.governed_gate import ALLOW, GovernedDecisionGate
from aac.organ_regulator import OrganRegulator
from aac.self_maintenance import MaintenanceAction, SelfMaintenanceLoop
from aac.self_model import AgentSelfModel
from aac.self_model_updater import AgentSelfModelUpdater
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from aac.weight_memory import WeightMemory

try:
    from envs.multi_objective import MultiObjectiveEnv
except ImportError:
    from multi_objective import MultiObjectiveEnv  # type: ignore

try:
    from experiments._g7_common import STEPS, WINDOW, wilcoxon_one_sided
except ModuleNotFoundError:
    STEPS = 2000
    WINDOW = 15

    def wilcoxon_one_sided(diffs: list[float]) -> float:
        non_zero = [d for d in diffs if d != 0]
        if not non_zero:
            return 1.0
        abs_diffs = sorted((abs(d), i) for i, d in enumerate(non_zero))
        ranks = {}
        i = 0
        while i < len(abs_diffs):
            j = i
            while j < len(abs_diffs) and abs_diffs[j][0] == abs_diffs[i][0]:
                j += 1
            avg_rank = (i + j + 1) / 2.0
            for k in range(i, j):
                ranks[abs_diffs[k][1]] = avg_rank
            i = j
        w_plus = sum(ranks[idx] for idx, d in enumerate(non_zero) if d > 0)
        n = len(non_zero)
        mu = n * (n + 1) / 4.0
        sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)
        if sigma < 1e-9:
            return 1.0 if w_plus <= mu else 0.0
        z = (w_plus - 0.5 - mu) / sigma
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


RFINAL_SEEDS = tuple(range(870, 900))
N_ACTIONS = 8
N_METRICS = 3
N_REGIMES = 4
PERIOD = 100
G10_KAPPA = 0.5
G10_TEMP_FLOOR = 0.1


def _bootstrap_ci_mean(values, n_boot=10000, alpha=0.05, seed=12345):
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[int((1 - alpha / 2) * n_boot)]
    return lo, hi


def _cosine_distance(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na < 1e-9 or nb < 1e-9:
        return 1.0
    return 1.0 - dot / (na * nb)


def _make_self_model():
    return AgentSelfModel(
        allowed_tools=frozenset({f"action_{i}" for i in range(N_ACTIONS)}),
        denied_tools=frozenset(),
        approval_required_at_or_above=4,
        evidence_requirements={0: 0, 1: 1, 2: 1, 3: 2, 4: 3, 5: 3},
        confidence_thresholds={0: 0.0, 1: 0.5, 2: 0.6, 3: 0.7, 4: 0.8, 5: 0.9},
        risk_ceiling=5,
    )


def _run_arm(seed, env, *, e6=False, e9=False):
    """Run one seed with optional E6/E9 self-maintenance."""
    N = env.n_actions
    shell = CorrigibilityShell()
    viability = ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0)
    sm = _make_self_model()
    gate = GovernedDecisionGate(sm)
    agent = Agent(
        n_actions=N, shell=shell, rng=random.Random(20000 + seed),
        viability=viability, policy_gate=True, gate_kappa=G10_KAPPA, gate_temp_floor=G10_TEMP_FLOOR,
        governed_gate=gate, verifier=_noop_verifier(),
    )

    self_updater = AgentSelfModelUpdater(n_actions=N, calibration_lr=0.1) if e6 else None
    regulator = OrganRegulator() if e9 else None
    if e9:
        regulator.register_organ("g10_policy", initial_credit=0.7)
    maintenance = None
    if e9:
        maintenance = SelfMaintenanceLoop(
            viability=viability, organ_regulator=regulator,
            self_model_updater=self_updater, gate=gate, shell_view=shell.view(),
            check_interval=20, pressure_threshold=0.3,
        )

    current_weights = [1.0 / env.n_metrics] * env.n_metrics
    memory = WeightMemory()
    area = 0.0
    window_left = 0

    for t in range(STEPS):
        # ── Oracle weight switching ───────────────────────────────
        prev_w = current_weights
        current_weights = list(env.true_weights)
        if _cosine_distance(prev_w, current_weights) > 0.05:
            memory.snapshot_model(prev_w, agent.model)
            memory.warm_start_model(agent.model, current_weights)

        # ── Action selection (G10) ────────────────────────────────
        if shell.paused or not viability.alive:
            break
        policy = agent.policy
        policy.forbidden = shell.forbidden
        explore = agent.relevance.explore_drive if agent.modulate_relevance else 0.5
        action = policy.select(agent.model, explore, viability.pressure)
        reward = env.act(action, current_weights)
        viability.ingest(reward)
        viability.metabolize()
        agent.model.update(action, reward)
        agent.steps += 1
        agent.relevance.update(
            agent.model.last_surprise, viability.pressure, agent.model.total_uncertainty()
        )

        # ── E6: Self-model calibration ───────────────────────────
        if e6 and self_updater is not None:
            deltas = self_updater.after_action(
                action=str(action), risk_tier=0,
                predicted_confidence=agent.policy._confidence(agent.model),
                evidence_count=1, outcome=reward, outcome_baseline=0.0,
            )
            sm.apply_updates(deltas)

        # ── E9: Organ regulation + maintenance ───────────────────
        if e9 and regulator is not None:
            outcome_positive = reward > 0.0
            regulator.record_outcome("g10_policy", advice_applied=True, outcome_positive=outcome_positive)
            regulator.check_deweight("g10_policy")

        if e9 and maintenance is not None:
            actions = maintenance.step({"model": agent.model, "viability": viability})
            for ma in actions:
                maintenance.execute_maintenance(ma, lambda a: None)

        # ── Regret ────────────────────────────────────────────────
        if env.just_shifted:
            window_left = WINDOW
        if window_left > 0:
            area += env.last_regret
            window_left -= 1

    memory.snapshot_model(current_weights, agent.model)
    return area


class _NoopVerifier:
    def verify(self, cand):
        from aac.governed_loop import VerifyResult
        return VerifyResult(is_effective=True, confidence=1.0, evidence_count=1, interventions=0)


def _noop_verifier():
    return _NoopVerifier()


def gate():
    seeds = RFINAL_SEEDS
    n = len(seeds)
    arms = {
        "P0_FROZEN":   {"e6": False, "e9": False},
        "P0_E6_SELF":  {"e6": True,  "e9": False},
        "P0_E9_MAINT": {"e6": False, "e9": True},
        "P0_E6E9":     {"e6": True,  "e9": True},
    }

    print(f"E6/E9 self-maintenance gate  seeds={min(seeds)}..{max(seeds)} steps={STEPS}")
    header = f"{'seed':>4} | " + " ".join(f"{x:>12}" for x in arms)
    print(header)

    areas = {x: [] for x in arms}
    for seed in seeds:
        env = MultiObjectiveEnv(
            n_actions=N_ACTIONS, n_metrics=N_METRICS, n_regimes=N_REGIMES,
            period=PERIOD, rng=random.Random(50000 + seed),
        )
        row = {}
        for arm_name, cfg in arms.items():
            row[arm_name] = _run_arm(seed, env, **cfg)
            areas[arm_name].append(row[arm_name])
        print(f"{seed:>4} | " + " ".join(f"{row[x]:12.1f}" for x in arms))

    means = {x: sum(v) / n for x, v in areas.items()}
    print("\nAGGREGATE:")
    for x in arms:
        print(f"  {x}: mean={means[x]:.1f}")

    # Gate checks: E6 and E9 vs FROZEN
    for arm_name, label in [("P0_E6_SELF", "E6 self-model calibration"),
                              ("P0_E9_MAINT", "E9 maintenance loop"),
                              ("P0_E6E9", "E6+E9 combined")]:
        wins = sum(1 for i in range(n) if areas[arm_name][i] < areas["P0_FROZEN"][i])
        p = wilcoxon_one_sided([areas["P0_FROZEN"][i] - areas[arm_name][i] for i in range(n)])
        mean_c = means[arm_name]
        mean_b = means["P0_FROZEN"]
        reduction = 1.0 - mean_c / max(1e-9, mean_b) if mean_b > 0 else 0.0
        ci_lo, ci_hi = _bootstrap_ci_mean([areas["P0_FROZEN"][i] - areas[arm_name][i] for i in range(n)])
        passed = wins >= 25 and p < 0.01 and ci_lo > 0
        print(f"\n{label}")
        print(f"  mean={mean_c:.1f} vs FROZEN={mean_b:.1f}  reduction={reduction:.1%}")
        print(f"  wins: {wins}/{n}  p={p:.6f}  CI=[{ci_lo:.1f},{ci_hi:.1f}]")
        print(f"  {'PASS' if passed else 'FAIL'}")


if __name__ == "__main__":
    gate()
