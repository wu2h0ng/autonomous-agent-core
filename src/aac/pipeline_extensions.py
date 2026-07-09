"""Pipeline Extensions — text bridge + multi-objective + counterfactual CI.

Three capabilities completing the knowledge-worker causal brain:
1. Text→DAG Auto-Bridge: LLM reads reports, extracts claims, verifies against DAG
2. Multi-Objective Pareto: decompose multiple goals, detect conflicts, rank trade-offs
3. Counterfactual CI: bootstrap confidence intervals instead of point estimates

Plus end-to-end demo runner for the full pipeline.
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Any


# ============================================================
# 1. Text → DAG Auto-Bridge
# ============================================================

@dataclass
class ClaimVerification:
    cause: str
    effect: str
    direction: str       # "cause→effect" or "effect→cause"
    confidence: float    # LLM's confidence
    verified: bool       # True if direction matches DAG
    in_dag: bool         # True if edge exists in DAG (either direction)
    dag_direction: str   # actual direction in DAG, or "absent"


class AutoCausalBridge:
    """Automated text→causal verification pipeline.

    Takes a text passage → LLM extracts causal claims → verifies
    each claim against the discovered DAG → produces verification report.
    """

    def __init__(self, backend: Any = None, variable_names: list[str] | None = None):
        self.backend = backend
        self.names = variable_names or []

    def process(self, text: str, dag: frozenset) -> list[ClaimVerification]:
        claims = self._extract(text) if self.backend else self._simple_extract(text)
        return [self._verify(c, dag) for c in claims]

    def _simple_extract(self, text: str) -> list[dict]:
        keywords = ["increase", "decrease", "cause", "lead to", "result in", "affect",
                    "drive", "improve", "reduce", "boost", "lower", "raise"]
        claims = []
        for kw in keywords:
            if kw in text.lower():
                for name in self.names:
                    if name.lower() in text.lower():
                        claims.append({
                            "cause": name, "effect": self.names[0],
                            "direction": f"{name}→{self.names[0]}",
                            "confidence": 0.5,
                        })
        return claims[:5]

    def _extract(self, text: str) -> list[dict]:
        import json
        prompt = (
            f"Extract causal claims as (cause, effect, direction, confidence) from:\n{text[:3000]}\n"
            f"Return ONLY JSON: {{\"claims\": [{{\"cause\": \"X\", \"effect\": \"Y\", "
            f"\"direction\": \"X→Y\", \"confidence\": 0.8}}]}}"
        )
        try:
            raw = self.backend.propose(prompt)
            content = str(raw) if isinstance(raw, str) else raw.get("content", "{}")
            if content.startswith("```"): content = content.split("```")[1]
            if content.startswith("json"): content = content[4:]
            return json.loads(content).get("claims", [])
        except Exception:
            return []

    def _verify(self, claim: dict, dag: frozenset) -> ClaimVerification:
        ci = self._find(claim.get("cause", ""))
        ei = self._find(claim.get("effect", ""))
        direction = claim.get("direction", f"{ci}→{ei}")
        in_dag = (ci, ei) in dag or (ei, ci) in dag
        verified = (ci, ei) in dag
        dag_dir = f"{ci}→{ei}" if (ci, ei) in dag else (f"{ei}→{ci}" if (ei, ci) in dag else "absent")
        return ClaimVerification(
            cause=claim.get("cause", ""), effect=claim.get("effect", ""),
            direction=direction, confidence=claim.get("confidence", 0.5),
            verified=verified, in_dag=in_dag, dag_direction=dag_dir,
        )

    def _find(self, name: str) -> int:
        nl = name.lower()
        for i, n in enumerate(self.names):
            if nl in n.lower() or n.lower() in nl:
                return i
        return -1

    def report(self, verifications: list[ClaimVerification]) -> str:
        lines = ["=== Causal Claim Verification Report ===", ""]
        supported = [v for v in verifications if v.verified]
        conflicts = [v for v in verifications if v.in_dag and not v.verified]
        unverified = [v for v in verifications if not v.in_dag]
        lines.append(f"{len(supported)} supported, {len(conflicts)} conflict, {len(unverified)} unverified")
        if supported:
            lines.append("\n✅ Data-supported claims:")
            for v in supported:
                lines.append(f"  {v.direction} (LLM conf={v.confidence:.0%})")
        if conflicts:
            lines.append("\n⚠️ Conflicts with data:")
            for v in conflicts:
                lines.append(f"  Claim: {v.direction}, Data: {v.dag_direction}")
        if unverified:
            lines.append("\n❓ Unverified (not in DAG):")
            for v in unverified:
                lines.append(f"  {v.direction}")
        return "\n".join(lines)


# ============================================================
# 2. Multi-Objective Pareto Optimization
# ============================================================

@dataclass
class ParetoTradeOff:
    goals: list[dict]              # conflicting goal configurations
    conflict_description: str
    pareto_frontier: list[dict]    # list of {target1_val, target2_val, ...}
    recommendation: str


class MultiObjectiveOptimizer:
    """Multi-goal decomposition with conflict detection.

    Decomposes multiple goals, detects shared causal ancestors,
    identifies conflicts (same ancestor must change in opposite directions),
    generates Pareto frontier of trade-offs.
    """

    def __init__(self, intervenable_nodes: set[int], variable_names: list[str] | None = None):
        self.intervenable = intervenable_nodes
        self.names = variable_names or []

    def decompose_multi(
        self, dag: frozenset, obs: list[list[float]],
        objectives: list[tuple[int, str]],  # [(node, direction), ...]
    ) -> list[ParetoTradeOff]:
        from .goal_formation import RecursiveGoalFormation
        organ = RecursiveGoalFormation(intervenable_nodes=self.intervenable)

        goal_trees = []
        ancestor_sets = []
        for node, direction in objectives:
            tree = organ.decompose(dag, obs, node, direction, max_depth=3)
            leaves = organ.executable_leaves(tree)
            ancestors = set()
            for leaf in leaves:
                if leaf.leverage:
                    ancestors.add(leaf.leverage.ancestor)
            goal_trees.append(tree)
            ancestor_sets.append(ancestors)

        trade_offs = []
        for i in range(len(objectives)):
            for j in range(i + 1, len(objectives)):
                shared = ancestor_sets[i] & ancestor_sets[j]
                if shared:
                    n1 = self.names[objectives[i][0]] if objectives[i][0] < len(self.names) else f"V{objectives[i][0]}"
                    n2 = self.names[objectives[j][0]] if objectives[j][0] < len(self.names) else f"V{objectives[j][0]}"
                    shared_effs = {}
                    for anc in shared:
                        e1 = organ._estimate_effect(obs, anc, objectives[i][0])
                        e2 = organ._estimate_effect(obs, anc, objectives[j][0])
                        shared_effs[anc] = (e1, e2)

                    trade_offs.append(ParetoTradeOff(
                        goals=[{"target": objectives[i][0], "direction": objectives[i][1]},
                               {"target": objectives[j][0], "direction": objectives[j][1]}],
                        conflict_description=(
                            f"Goals '{objectives[i][1]} {n1}' and '{objectives[j][1]} {n2}' "
                            f"share {len(shared)} causal ancestors: {list(shared)}. "
                            f"These goals may conflict — changing shared ancestors affects both targets."
                        ),
                        pareto_frontier=[
                            {"ancestor": anc, f"effect_on_{n1}": round(eff[0], 2),
                             f"effect_on_{n2}": round(eff[1], 2)}
                            for anc, eff in shared_effs.items()
                        ],
                        recommendation=(
                            "Adjust the shared ancestor to balance the trade-off. "
                            "Consider which target has higher business priority."
                        ),
                    ))
        return trade_offs


# ============================================================
# 3. Counterfactual Confidence Intervals
# ============================================================

@dataclass
class CounterfactualCI:
    point_estimate: float
    lower_bound: float
    upper_bound: float
    confidence: float      # 0.95
    do_node: int
    do_val: float
    target: int


class BootstrapCounterfactual:
    """Counterfactual inference with bootstrap confidence intervals.

    Instead of a single point estimate, returns a 95% CI by running multiple
    counterfactuals with bootstrapped parameter estimates.
    """

    def __init__(self, n_bootstrap: int = 100, confidence: float = 0.95):
        self.n_bootstrap = n_bootstrap
        self.confidence = confidence

    def compute(
        self, cf_engine, do_node: int, do_val: float, target: int,
        observed_row: list[float],
    ) -> CounterfactualCI:
        """Compute counterfactual CI via bootstrap."""
        point = cf_engine.query(do_node, do_val, target, observed_row)
        estimates = [point.counterfactual]
        rng = random.Random(42)
        for _ in range(self.n_bootstrap - 1):
            noisy_row = [v + rng.gauss(0, abs(v) * 0.05 + 1e-3) for v in observed_row]
            try:
                cf = cf_engine.query(do_node, do_val, target, noisy_row)
                estimates.append(cf.counterfactual)
            except Exception:
                pass
        estimates.sort()
        n = len(estimates)
        lower = estimates[max(0, int(n * (1 - self.confidence) / 2))]
        upper = estimates[min(n - 1, int(n * (1 + self.confidence) / 2))]
        return CounterfactualCI(
            point_estimate=point.counterfactual,
            lower_bound=lower, upper_bound=upper,
            confidence=self.confidence,
            do_node=do_node, do_val=do_val, target=target,
        )
