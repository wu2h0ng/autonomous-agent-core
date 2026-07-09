"""G11: LLM strategy weight organ + G10 confidence-gated policy (CWM-IDENT-4 instance).

Tests whether adding an LLM weight-proposal organ to G10's confidence-gated policy
produces super-additive capability in a multi-objective regime-shifting environment.

Arms:
  A0_RANDOM       — random action, uniform weights (lower bound)
  A1_UCB_UNIFORM  — UCB action selection, uniform weights
  P0_FROZEN       — G10 confidence gate, uniform weights (existing MET baseline)
  P0_GRID_WEIGHTS — G10 gate, UCB over discretized weight simplex
  P0_ORACLE       — G10 gate, ground-truth weights (upper bound)
  P0_LLM_WEIGHTS  — G10 gate, LLM proposes weights, gate decides (CANDIDATE)
  P0_LLM_NO_GATE  — G10 gate, LLM proposes weights, always adopted (ablation)

Gates (preregistered):
  G11-1  strategy-dimension:     mean(P0_GRID_WEIGHTS) < mean(P0_FROZEN)
  G11-2  LLM-beats-learning:     mean(P0_LLM_WEIGHTS) < mean(P0_GRID_WEIGHTS)
  G11-3  LLM-not-oracle:         mean(P0_LLM_WEIGHTS) >= mean(P0_ORACLE)
  G11-4  gate-filters:           rejected proposals have higher weight error
  G11-5  C6/C7 intact:           zero correction events
  G11-6  not-token-effect:       P0_LLM >20% reduction over P0_GRID

Run:  PYTHONPATH=src python -m experiments.strategy_gated_g11 [--stub]
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
from dataclasses import dataclass

from aac.agent import Agent
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from aac.weight_memory import WeightMemory

try:
    from aac.llm_weight_organ import LLMWeightOrgan, SimpleLLMBackend
except ImportError:
    from llm_weight_organ import LLMWeightOrgan, SimpleLLMBackend  # type: ignore

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
        """One-sided Wilcoxon signed-rank test (pure stdlib)."""
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


# ── Frozen parameters ──────────────────────────────────────────────
RFINAL_SEEDS = tuple(range(840, 870))
N_ACTIONS = 8
N_METRICS = 3
N_REGIMES = 4
PERIOD = 100   # longer period = more time to benefit from correct weights
G10_KAPPA = 0.5
G10_TEMP_FLOOR = 0.1
WEIGHT_GRID_SIZE = 15         # discretized simplex points for UCB
LLM_CALL_INTERVAL = 10        # steps between LLM API calls
WEIGHT_SWITCH_INTERVAL = 10   # steps between weight-switch evaluations
LLM_GATE_CONFIDENCE_MIN = 0.6
LLM_GATE_COSINE_THRESHOLD = 0.05
LLM_GATE_RELIABILITY_MIN = 0.7
DELTA = 0.20                  # target reduction margin


def _bootstrap_ci_mean(
    values: list[float], *, n_boot: int = 10000, alpha: float = 0.05, seed: int = 12345
) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[int((1 - alpha / 2) * n_boot)]
    return lo, hi


# ── Simplex UCB weight selection ───────────────────────────────────

def _generate_simplex_grid(n_metrics: int, n_points: int) -> list[list[float]]:
    """Generate n_points approximately uniformly on the (n_metrics-1)-simplex."""
    if n_metrics == 3:
        points: list[list[float]] = []
        step = int(math.sqrt(n_points))
        for i in range(step + 1):
            for j in range(step + 1 - i):
                if len(points) >= n_points:
                    break
                w1 = i / max(1, step)
                w2 = j / max(1, step)
                w3 = 1.0 - w1 - w2
                if w3 >= 0.0:
                    points.append([w1, w2, w3])
        return points[:n_points]
    points = []
    for _ in range(n_points):
        raw = [random.Random(_ + 9999).random() for _ in range(n_metrics)]
        total = sum(raw)
        points.append([w / total for w in raw])
    return points


@dataclass
class SimplexUCB:
    """UCB over a discretized simplex grid for weight selection."""
    points: list[list[float]]
    values: list[float]
    counts: list[int]
    t: int = 0

    def select(self) -> int:
        best_idx = 0
        best_val = float("-inf")
        for i in range(len(self.points)):
            if self.counts[i] == 0:
                return i
            ucb = self.values[i] + math.sqrt(2.0 * math.log(self.t + 2) / max(1, self.counts[i]))
            if ucb > best_val:
                best_val = ucb
                best_idx = i
        return best_idx

    def update(self, idx: int, reward: float) -> None:
        self.counts[idx] += 1
        n = self.counts[idx]
        self.values[idx] = ((n - 1) * self.values[idx] + reward) / n
        self.t += 1


# ── Arms ───────────────────────────────────────────────────────────

def _run_arm(
    seed: int,
    env: MultiObjectiveEnv,
    *,
    weight_source: str,
    llm_organ: LLMWeightOrgan | None = None,
) -> float:
    """Run one seed with WeightMemory decoupling strategy and action loops."""
    N = env.n_actions
    shell = CorrigibilityShell()
    viability = ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0)
    agent = Agent(
        n_actions=N, shell=shell, rng=random.Random(20000 + seed),
        viability=viability, policy_gate=True, gate_kappa=G10_KAPPA, gate_temp_floor=G10_TEMP_FLOOR,
    )

    current_weights = [1.0 / env.n_metrics] * env.n_metrics
    grid_ucb: SimplexUCB | None = None
    ucb_point_idx: int | None = None
    memory = WeightMemory()
    if weight_source == "grid_ucb":
        grid_ucb = SimplexUCB(
            points=_generate_simplex_grid(env.n_metrics, WEIGHT_GRID_SIZE),
            values=[0.0] * WEIGHT_GRID_SIZE, counts=[0] * WEIGHT_GRID_SIZE,
        )

    area = 0.0
    window_left = 0
    weight_switched = False

    for t in range(STEPS):
        # ── Weight proposal ──────────────────────────────────────
        prev_weights = current_weights
        if weight_source == "llm" and llm_organ is not None:
            w, conf, fresh = llm_organ.propose(env.situation())
            if fresh and w is not None and conf >= LLM_GATE_CONFIDENCE_MIN:
                if _cosine_distance(current_weights, w) >= LLM_GATE_COSINE_THRESHOLD:
                    current_weights = w
                    weight_switched = True
        elif weight_source == "llm_no_gate" and llm_organ is not None:
            w, _conf, fresh = llm_organ.propose(env.situation())
            if fresh and w is not None:
                current_weights = w
                weight_switched = True
        elif weight_source == "grid_ucb" and grid_ucb is not None and t % WEIGHT_SWITCH_INTERVAL == 0:
            idx = grid_ucb.select()
            ucb_point_idx = idx
            current_weights = list(grid_ucb.points[idx])
            weight_switched = True
        elif weight_source == "oracle":
            current_weights = list(env.true_weights)
            if _cosine_distance(prev_weights, current_weights) > 0.05:
                weight_switched = True

        # ── Two-loop decoupling ──────────────────────────────────
        if weight_switched:
            memory.snapshot_model(prev_weights, agent.model)
            warm = memory.warm_start_model(agent.model, current_weights)
            weight_switched = False

        # ── Action selection (G10 loop, unchanged) ────────────────
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

        # ── Regret ────────────────────────────────────────────────
        if env.just_shifted:
            window_left = WINDOW
        if window_left > 0:
            area += env.last_regret
            window_left -= 1

        if weight_source == "grid_ucb" and grid_ucb is not None and ucb_point_idx is not None:
            grid_ucb.update(ucb_point_idx, reward)

    # Final snapshot
    memory.snapshot_model(current_weights, agent.model)
    return area


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na < 1e-9 or nb < 1e-9:
        return 1.0
    return 1.0 - dot / (na * nb)


# ── Gate runner ───────────────────────────────────────────────────

def gate(stub: bool = False) -> None:
    seeds = RFINAL_SEEDS
    n = len(seeds)

    llm_organ: LLMWeightOrgan | None = None
    if not stub:
        backend = SimpleLLMBackend()
        llm_organ = LLMWeightOrgan(
            backend=backend, n_metrics=N_METRICS, call_interval=LLM_CALL_INTERVAL,
        )
    else:
        class StubBackend:
            def propose(self, _p): return {"weights": None, "confidence": 0.0}
        llm_organ = LLMWeightOrgan(
            backend=StubBackend(), n_metrics=N_METRICS, call_interval=LLM_CALL_INTERVAL,
        )

    arms = {
        "A0_RANDOM":        {"source": "uniform",       "llm": None},
        "A1_UCB_UNIFORM":   {"source": "uniform",       "llm": None},
        "P0_FROZEN":        {"source": "uniform",       "llm": None},
        "P0_GRID_WEIGHTS":  {"source": "grid_ucb",      "llm": None},
        "P0_ORACLE":        {"source": "oracle",         "llm": None},
        "P0_LLM_WEIGHTS":   {"source": "llm",            "llm": llm_organ},
        "P0_LLM_NO_GATE":   {"source": "llm_no_gate",    "llm": llm_organ},
    }

    print(f"G11 strategy weight + G10 gate  run=r-final seeds={min(seeds)}..{max(seeds)} steps={STEPS}")
    print(f"  LLM: {'stub' if stub else 'live'}")
    header = f"{'seed':>4} | " + " ".join(f"{x:>12}" for x in arms)
    print(header)

    areas: dict[str, list[float]] = {x: [] for x in arms}
    for seed in seeds:
        env = MultiObjectiveEnv(
            n_actions=N_ACTIONS, n_metrics=N_METRICS, n_regimes=N_REGIMES,
            period=PERIOD, rng=random.Random(30000 + seed),
        )
        row: dict[str, float] = {}
        for arm_name, cfg in arms.items():
            if arm_name == "A0_RANDOM":
                row[arm_name] = _run_random_arm(seed, env)
            elif arm_name == "A1_UCB_UNIFORM":
                row[arm_name] = _run_ucb_arm(seed, env)
            else:
                row[arm_name] = _run_arm(
                    seed, env, weight_source=cfg["source"], llm_organ=cfg["llm"],
                )
            areas[arm_name].append(row[arm_name])
        print(f"{seed:>4} | " + " ".join(f"{row[x]:12.1f}" for x in arms if x in row))

    # Aggregate
    means = {x: sum(v) / n for x, v in areas.items()}
    print("\nAGGREGATE:")
    for x in arms:
        print(f"  {x}: mean={means[x]:.1f}")

    # Gate checks
    _gate_check("G11-1 strategy-dim: GRID < FROZEN",
        areas["P0_GRID_WEIGHTS"], areas["P0_FROZEN"], n, delta=0.0)
    _gate_check("G11-2 LLM-beats-learning: LLM < GRID",
        areas["P0_LLM_WEIGHTS"], areas["P0_GRID_WEIGHTS"], n, delta=DELTA)
    _gate_check("G11-6 not-token: LLM >20% cut vs GRID",
        areas["P0_LLM_WEIGHTS"], areas["P0_GRID_WEIGHTS"], n, delta=0.0, pct_check=True)


def _run_random_arm(seed: int, env: MultiObjectiveEnv) -> float:
    rng = random.Random(40000 + seed)
    area = 0.0
    window_left = 0
    for _ in range(STEPS):
        action = rng.randrange(env.n_actions)
        reward = env.act(action, [1.0 / env.n_metrics] * env.n_metrics)
        if env.just_shifted:
            window_left = WINDOW
        if window_left > 0:
            area += env.last_regret
            window_left -= 1
    return area


def _run_ucb_arm(seed: int, env: MultiObjectiveEnv) -> float:
    """UCB action selection with uniform weights (A1 baseline)."""
    N = env.n_actions
    counts = [0] * N
    values = [0.0] * N
    area = 0.0
    window_left = 0
    for t in range(STEPS):
        best_val = float("-inf")
        action = 0
        for a in range(N):
            if counts[a] == 0:
                action = a
                break
            ucb = values[a] + math.sqrt(2.0 * math.log(t + 2) / max(1, counts[a]))
            if ucb > best_val:
                best_val = ucb
                action = a
        reward = env.act(action, [1.0 / env.n_metrics] * env.n_metrics)
        counts[action] += 1
        n_a = counts[action]
        values[action] = ((n_a - 1) * values[action] + reward) / n_a
        if env.just_shifted:
            window_left = WINDOW
        if window_left > 0:
            area += env.last_regret
            window_left -= 1
    return area


def _gate_check(
    label: str,
    candidate: list[float],
    baseline: list[float],
    n: int,
    delta: float = DELTA,
    pct_check: bool = False,
) -> None:
    wins = sum(1 for i in range(n) if candidate[i] < baseline[i])
    p = wilcoxon_one_sided([baseline[i] - candidate[i] for i in range(n)])
    mean_c = sum(candidate) / n
    mean_b = sum(baseline) / n
    reduction = 1.0 - mean_c / max(1e-9, mean_b) if mean_b > 0 else 0.0
    ci_lo, ci_hi = _bootstrap_ci_mean([baseline[i] - candidate[i] for i in range(n)])

    if pct_check:
        passed = reduction >= 0.20 and ci_lo > 0
    else:
        passed = wins >= 25 and p < 0.01 and ci_lo > 0

    print(f"\n{label}")
    print(f"  wins: {wins}/{n}  p={p:.6f}  mean_reduction={reduction:.1%}  CI=[{ci_lo:.1f},{ci_hi:.1f}]")
    print(f"  {'PASS' if passed else 'FAIL'}")


# ── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    stub = "--stub" in sys.argv or os.environ.get("G11_STUB", "") == "1"
    gate(stub=stub)
