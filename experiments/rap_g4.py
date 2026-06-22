"""G4 falsification experiment for P3 RAP v0 (ADR-0014, T-P3.4).

Run:
    PYTHONPATH=src python experiments/rap_g4.py

This is the pre-committed r-final gate run. Do not tune the mechanism,
environment, epsilon, or criteria after seeing results.

Gate summary (ADR-0014):
  G4-1: C-rap mean regret < B-fixed in >=7/10 seeds.
  G4-2: under NODE_DROP, C-rap drop-regret area <= B-central in >=7/10
        seeds, and aggregate C-rap mean regret is not dominated by
        B-central (C-rap <= B-central + EPSILON).
  G4-3: orchestration tax(C-rap) < 0.40 and <= 1.25 * tax(B-central), all seeds.
  G4-4: every C-rap bond has TRACE evidence and the shell audit verifies.

Truth boundary:
  Nodes, C-rap routing, and B-central never read regret/best_action/regime.
  The Ring-0 OutcomeJudge inside RAPCoordinator reads regret only for
  settlement, matching the project's judge-sees-truth soundness model.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Mapping

from aac.outcome_judge import OutcomeJudge
from aac.rap import RAPField
from aac.rap_baselines import CentralBaseline, FixedBaseline, scan_fixed_baseline
from aac.rap_coordinator import ConfidenceReputationRouting, RAPCoordinator
from aac.rap_nodes import DecisionNode, default_node_factories
from aac.shell import CorrigibilityShell
from envs.rap_mixture import (
    DisturbanceKind,
    RAPPerturbationEnv,
    SegmentSpec,
    generate_segments,
)

RUN_LABEL = "r-final"
SEEDS = tuple(range(10))
STEPS = 1500
SCAN_STEPS = 1500
N_ACTIONS = 8
DISTURBANCE_RATE = 0.25
EPSILON = 0.05
STALENESS_WINDOW = 10

# Small, pre-run interpretation of ADR-0014's overhead formula.
# RAP per executed bond: NEED + BID*n + BOND + TRACE*2 + DISSOLVE + bid_eval*n.
# RAP no-bond fallback: NEED + BID*n + bid_eval*n.
# Central per step: score/evaluate n nodes + dispatch one selected node.
C_RAP_FIXED_MESSAGES = 1 + 1 + 2 + 1  # NEED + BOND + 2 TRACE + DISSOLVE
B_CENTRAL_FIXED_OVERHEAD = 1  # dispatch after central scoring

PREFERRED_BY_SEGMENT: Mapping[str, frozenset[str]] = {
    "stable": frozenset({"world_model_greedy", "contextual"}),
    "shifting": frozenset({"efe_policy", "stale_revisit", "random"}),
    "noisy": frozenset({"random", "contextual"}),
}


@dataclass(frozen=True)
class RunMetrics:
    mean_regret: float
    drop_regret_area: float
    drop_steps: int
    orchestration_tax: float
    bonds: int = 0
    skipped: int = 0
    audit_ok: bool = True
    evidence_ok: bool = True
    off_segment_wins: int = 0
    stale_window_wins: int = 0
    dropped_winner_wins: int = 0


@dataclass(frozen=True)
class SeedResult:
    seed: int
    fixed_node_id: str
    c_rap: RunMetrics
    b_fixed: RunMetrics
    b_central: RunMetrics


@dataclass(frozen=True)
class G4Verdict:
    verdict: str
    quality_wins: int
    drop_recovery_wins: int
    central_non_dominated: bool
    tax_all: bool
    evidence_all: bool
    c_mean_regret: float
    fixed_mean_regret: float
    central_mean_regret: float


def _mean(xs: list[float] | tuple[float, ...]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _tax(overhead_ops: int, decision_ops: int) -> float:
    total = overhead_ops + decision_ops
    return overhead_ops / total if total else 1.0


def _node_ids() -> tuple[str, ...]:
    return tuple(sorted(default_node_factories(N_ACTIONS)))


def _segments(seed: int, *, disturbed: bool) -> tuple[SegmentSpec, ...]:
    return generate_segments(
        rng=random.Random(10_000 + seed),
        total_steps=STEPS,
        node_ids=_node_ids(),
        disturbance_rate=DISTURBANCE_RATE if disturbed else 0.0,
    )


def _env(
    seed: int, segments: tuple[SegmentSpec, ...], *, salt: int
) -> RAPPerturbationEnv:
    return RAPPerturbationEnv(
        n_actions=N_ACTIONS,
        rng=random.Random(salt + seed),
        segments=segments,
    )


def _nodes(seed: int, *, salt: int) -> dict[str, DecisionNode]:
    factories = default_node_factories(N_ACTIONS)
    return {
        node_id: factory(random.Random(salt + seed * 100 + i))
        for i, (node_id, factory) in enumerate(sorted(factories.items()))
    }


def _fixed_scan(seed: int) -> str:
    factories = default_node_factories(N_ACTIONS)

    def env_factory(rng: random.Random) -> RAPPerturbationEnv:
        return RAPPerturbationEnv(
            n_actions=N_ACTIONS,
            rng=rng,
            segments=generate_segments(
                rng=random.Random(30_000 + seed),
                total_steps=SCAN_STEPS,
                node_ids=_node_ids(),
                disturbance_rate=0.0,
            ),
        )

    return scan_fixed_baseline(
        node_factories=factories,
        env_factory=env_factory,
        steps=SCAN_STEPS,
        seed=40_000 + seed,
    ).node_id


def _drop_area_add(segment_disturbance: str, regret: float) -> tuple[float, int]:
    if segment_disturbance == DisturbanceKind.NODE_DROP.value:
        return regret, 1
    return 0.0, 0


def _empty_run() -> RunMetrics:
    return RunMetrics(
        mean_regret=float("inf"),
        drop_regret_area=float("inf"),
        drop_steps=0,
        orchestration_tax=1.0,
        audit_ok=False,
        evidence_ok=False,
    )


def run_c_rap(seed: int, segments: tuple[SegmentSpec, ...]) -> RunMetrics:
    env = _env(seed, segments, salt=50_000)
    shell = CorrigibilityShell()
    field = RAPField(shell=shell.view())
    nodes = _nodes(seed, salt=60_000)
    coord = RAPCoordinator(
        field=field,
        shell=shell.view(),
        judge=OutcomeJudge(),
        nodes=list(nodes.values()),
        routing=ConfidenceReputationRouting(),
    )

    regret_sum = 0.0
    drop_regret_sum = 0.0
    drop_steps = 0
    bonds = 0
    skipped = 0
    overhead_ops = 0
    decision_ops = 0
    off_segment_wins = 0
    stale_window_wins = 0
    dropped_winner_wins = 0

    for _ in range(STEPS):
        situation = env.situation()
        result = coord.run_need(env)
        if result is None:
            # A failed auction is not a free pause. Time passes and the world
            # receives the deterministic garbage action, so regret is counted.
            env.act(env.garbage_action())
            regret = env.last_regret
            skipped += 1
            bid_count = len(nodes)
            overhead_ops += 1 + bid_count + bid_count
        else:
            regret = float(result["regret"])
            bonds += 1
            bid_count = int(result.get("bid_count", len(nodes)))
            overhead_ops += C_RAP_FIXED_MESSAGES + bid_count + bid_count
            if not result.get("dropped") and not result.get("lagged"):
                decision_ops += 1
            winner = str(result["winner"])
            preferred = PREFERRED_BY_SEGMENT.get(
                str(situation.get("segment")), frozenset()
            )
            if winner not in preferred:
                off_segment_wins += 1
                if int(situation.get("segment_elapsed", 0)) < STALENESS_WINDOW:
                    stale_window_wins += 1
            if winner == situation.get("dropped_node"):
                dropped_winner_wins += 1

        regret_sum += regret
        add, n = _drop_area_add(str(situation.get("disturbance")), regret)
        drop_regret_sum += add
        drop_steps += n

    bond_ids = {
        e.payload["bond_id"]
        for e in shell.audit.entries()
        if e.payload.get("event") == "rap_dissolve"
    }
    trace_bond_ids = {
        e.payload["bond_id"]
        for e in shell.audit.entries()
        if e.payload.get("event") == "rap_trace"
    }
    evidence_ok = len(bond_ids) == bonds and bond_ids.issubset(trace_bond_ids)
    return RunMetrics(
        mean_regret=regret_sum / STEPS,
        drop_regret_area=drop_regret_sum / drop_steps if drop_steps else float("inf"),
        drop_steps=drop_steps,
        orchestration_tax=_tax(overhead_ops, decision_ops),
        bonds=bonds,
        skipped=skipped,
        audit_ok=shell.audit.verify(),
        evidence_ok=evidence_ok,
        off_segment_wins=off_segment_wins,
        stale_window_wins=stale_window_wins,
        dropped_winner_wins=dropped_winner_wins,
    )


def run_fixed(
    seed: int, segments: tuple[SegmentSpec, ...], fixed_node_id: str
) -> RunMetrics:
    env = _env(seed, segments, salt=50_000)
    nodes = _nodes(seed, salt=70_000)
    fixed = FixedBaseline(nodes[fixed_node_id])
    regret_sum = 0.0
    drop_regret_sum = 0.0
    drop_steps = 0
    for _ in range(STEPS):
        situation = env.situation()
        step = fixed.step(env)
        regret_sum += step.regret
        add, n = _drop_area_add(str(situation.get("disturbance")), step.regret)
        drop_regret_sum += add
        drop_steps += n
    return RunMetrics(
        mean_regret=regret_sum / STEPS,
        drop_regret_area=drop_regret_sum / drop_steps if drop_steps else float("inf"),
        drop_steps=drop_steps,
        orchestration_tax=0.0,
    )


def run_central(seed: int, segments: tuple[SegmentSpec, ...]) -> RunMetrics:
    env = _env(seed, segments, salt=50_000)
    nodes = _nodes(seed, salt=80_000)
    central = CentralBaseline(nodes=nodes)
    regret_sum = 0.0
    drop_regret_sum = 0.0
    drop_steps = 0
    overhead_ops = 0
    decision_ops = 0
    node_count = len(nodes)
    for _ in range(STEPS):
        situation = env.situation()
        step = central.step(env)
        regret_sum += step.regret
        overhead_ops += node_count + B_CENTRAL_FIXED_OVERHEAD
        if not step.dropped and not step.lagged:
            decision_ops += 1
        add, n = _drop_area_add(str(situation.get("disturbance")), step.regret)
        drop_regret_sum += add
        drop_steps += n
    return RunMetrics(
        mean_regret=regret_sum / STEPS,
        drop_regret_area=drop_regret_sum / drop_steps if drop_steps else float("inf"),
        drop_steps=drop_steps,
        orchestration_tax=_tax(overhead_ops, decision_ops),
    )


def run_seed(seed: int) -> SeedResult:
    segments = _segments(seed, disturbed=True)
    fixed_node_id = _fixed_scan(seed)
    return SeedResult(
        seed=seed,
        fixed_node_id=fixed_node_id,
        c_rap=run_c_rap(seed, segments),
        b_fixed=run_fixed(seed, segments, fixed_node_id),
        b_central=run_central(seed, segments),
    )


def judge_g4(results: list[SeedResult]) -> G4Verdict:
    quality_wins = sum(
        1 for r in results if r.c_rap.mean_regret < r.b_fixed.mean_regret
    )
    drop_recovery_wins = sum(
        1 for r in results if r.c_rap.drop_regret_area <= r.b_central.drop_regret_area
    )
    c_mean = _mean([r.c_rap.mean_regret for r in results])
    fixed_mean = _mean([r.b_fixed.mean_regret for r in results])
    central_mean = _mean([r.b_central.mean_regret for r in results])
    central_non_dominated = c_mean <= central_mean + EPSILON
    tax_all = all(
        r.c_rap.orchestration_tax < 0.40
        and r.c_rap.orchestration_tax <= r.b_central.orchestration_tax * 1.25
        for r in results
    )
    evidence_all = all(r.c_rap.audit_ok and r.c_rap.evidence_ok for r in results)
    met = (
        quality_wins >= 7
        and drop_recovery_wins >= 7
        and central_non_dominated
        and tax_all
        and evidence_all
    )
    return G4Verdict(
        verdict="MET" if met else "NOT MET",
        quality_wins=quality_wins,
        drop_recovery_wins=drop_recovery_wins,
        central_non_dominated=central_non_dominated,
        tax_all=tax_all,
        evidence_all=evidence_all,
        c_mean_regret=c_mean,
        fixed_mean_regret=fixed_mean,
        central_mean_regret=central_mean,
    )


def main() -> None:
    print("G4 RAP v0 gate (ADR-0014, T-P3.4)")
    print(
        f"run={RUN_LABEL} seeds={SEEDS[0]}-{SEEDS[-1]} steps={STEPS} "
        f"n_actions={N_ACTIONS} disturbance_rate={DISTURBANCE_RATE} epsilon={EPSILON}"
    )
    print(
        f"{'seed':>4} {'fixed':>18} | {'C-rap':>8} {'B-fixed':>8} "
        f"{'B-cent':>8} | {'drop C/Bc':>15} | {'tax C/Bc':>15} | "
        f"{'bonds':>5} {'skip':>4} {'stale':>5} {'dropW':>5}"
    )
    results: list[SeedResult] = []
    for seed in SEEDS:
        row = run_seed(seed)
        results.append(row)
        print(
            f"{seed:>4} {row.fixed_node_id:>18} | "
            f"{row.c_rap.mean_regret:8.3f} {row.b_fixed.mean_regret:8.3f} "
            f"{row.b_central.mean_regret:8.3f} | "
            f"{row.c_rap.drop_regret_area:6.3f}/{row.b_central.drop_regret_area:<6.3f} | "
            f"{row.c_rap.orchestration_tax:6.3f}/{row.b_central.orchestration_tax:<6.3f} | "
            f"{row.c_rap.bonds:5d} {row.c_rap.skipped:4d} "
            f"{row.c_rap.stale_window_wins:5d} {row.c_rap.dropped_winner_wins:5d}"
        )

    verdict = judge_g4(results)
    print("\nAGGREGATE:")
    print(f"  C-rap mean regret:    {verdict.c_mean_regret:.3f}")
    print(f"  B-fixed mean regret:  {verdict.fixed_mean_regret:.3f}")
    print(f"  B-central mean regret:{verdict.central_mean_regret:.3f}")
    print(
        "  C-rap diagnostics: "
        f"off-segment wins={sum(r.c_rap.off_segment_wins for r in results)}, "
        f"early-segment stale wins={sum(r.c_rap.stale_window_wins for r in results)}, "
        f"dropped-winner wins={sum(r.c_rap.dropped_winner_wins for r in results)}"
    )

    print("\nG4 PRE-REGISTERED GATE:")
    print(f"  G4-1 quality vs B-fixed:     {verdict.quality_wins}/10 (need >=7)")
    print(f"  G4-2 NODE_DROP recovery:     {verdict.drop_recovery_wins}/10 (need >=7)")
    print(
        "  G4-2 central non-dominated: "
        f"{verdict.central_non_dominated} "
        f"(C <= B-central + {EPSILON})"
    )
    print(f"  G4-3 orchestration tax:      {verdict.tax_all} (need True, all seeds)")
    print(
        f"  G4-4 evidence/audit:         {verdict.evidence_all} (need True, all seeds)"
    )
    print("\n  G4: " + verdict.verdict)


if __name__ == "__main__":
    main()
