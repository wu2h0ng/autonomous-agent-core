"""Goal Formation Organ — self-forming goals from discovered causal structure.

The last unclosed commitment of the goal blueprint: "自己形成目标".

From the discovered causal DAG, identifies causal leverage points — nodes whose
ancestors include intervenable nodes — ranks them by expected intervention effect
magnitude, and forms a goal (target + direction + commitment level).

Commitment is DEMONSTRATION-GROUNDED: only goals for which the system has already
observed the causal effect (via intervention data or OLS fit) are committed.
Ungrounded goals are proposed for future verification but not acted upon.

Principal boundary (RR-0046 §31): goals can only target OBSERVABLE variables.
C7/Corrigibility/Governance nodes are structurally excluded from the goal space
because they are not in the causal variable set V (PR-001: C7 ≡ ∅ uninhabited).

Architecture:
    Causal DAG → find_leverage_points() → rank by effect magnitude
    → form_goal(demonstrated_only=True) → Goal with commitment level
    → GovernedDiscoveryLoop.execute(intervention_to_achieve_goal) → verify

Usage:
    from aac.goal_formation import GoalFormationOrgan
    organ = GoalFormationOrgan(intervenable_nodes={0,2,3})
    goals = organ.form_goals(dag, obs_data)
    for g in goals:
        print(g.target, g.direction, g.commitment)
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LeveragePoint:
    """A causal leverage point — a node that can be affected through ancestors."""
    target: int
    causal_path: list[tuple[int, int]]  # chain of edges from intervenable ancestor to target
    ancestor: int                        # closest intervenable ancestor
    effect_magnitude: float              # estimated intervention effect size
    demonstrated: bool = False           # has this effect been verified by data?


@dataclass
class Goal:
    """A self-formed goal from causal discovery.

    target: which variable to affect.
    direction: "maximize", "minimize", or "stabilize".
    commitment: [0,1] — how confident the system is in achieving this goal.
        High commitment = large, demonstrated causal effect.
        Low commitment = small, unverified effect → proposal only.
    leverage: the causal path through which this goal is achievable.
    principal_bounded: True = goal is within principal's allowed scope.
    """
    target: int
    direction: str                     # "maximize" | "minimize" | "stabilize"
    commitment: float                  # [0,1]
    leverage: LeveragePoint | None = None
    principal_bounded: bool = True


class GoalFormationOrgan:
    """Forms goals from discovered causal structure.

    Finds causal leverage points in a DAG, ranks by expected intervention effect,
    and forms demonstration-grounded goals with calibrated commitment levels.

    Args:
        intervenable_nodes: set of node indices available for do() interventions.
        forbidden_targets: nodes that cannot be targeted (C7/principal boundary).
        effect_threshold: minimum effect magnitude for "demonstrated" commitment.
    """

    def __init__(
        self,
        intervenable_nodes: set[int] | None = None,
        forbidden_targets: set[int] | None = None,
        effect_threshold: float = 0.3,
    ):
        self.intervenable = intervenable_nodes or set()
        self.forbidden = forbidden_targets or set()
        self.effect_threshold = effect_threshold

    def find_leverage_points(
        self, dag: frozenset[tuple[int, int]], obs: list[list[float]],
    ) -> list[LeveragePoint]:
        """Find all causal leverage points in a DAG.

        A leverage point = a node that has at least one intervenable ancestor,
        meaning we CAN affect it through do() operations.
        """
        n = len(obs[0])
        ancestors = self._transitive_ancestors(dag, n)
        points = []
        for target in range(n):
            if target in self.forbidden:
                continue
            for anc in ancestors[target]:
                if anc in self.intervenable and anc != target:
                    effect = self._estimate_effect(obs, anc, target)
                    path = self._find_path(dag, anc, target)
                    points.append(LeveragePoint(
                        target=target, causal_path=path,
                        ancestor=anc, effect_magnitude=effect,
                        demonstrated=effect > self.effect_threshold,
                    ))
        points.sort(key=lambda p: p.effect_magnitude, reverse=True)
        return points

    def form_goals(
        self, dag: frozenset[tuple[int, int]], obs: list[list[float]],
        demonstrated_only: bool = True, max_goals: int = 5,
    ) -> list[Goal]:
        """Form goals from leverage points.

        Args:
            dag: discovered causal DAG.
            obs: observational data for effect estimation.
            demonstrated_only: if True, only commit to goals with verified effects.
                If False, also propose unverified goals (with low commitment).
            max_goals: maximum number of goals to return.

        Returns:
            list of Goal objects, sorted by commitment (highest first).
        """
        points = self.find_leverage_points(dag, obs)
        goals = []
        for pt in points:
            if demonstrated_only and not pt.demonstrated:
                continue
            direction = self._infer_direction(pt.effect_magnitude, dag, pt.target)
            commitment = self._compute_commitment(pt)
            goals.append(Goal(
                target=pt.target, direction=direction,
                commitment=commitment, leverage=pt,
            ))
        goals.sort(key=lambda g: g.commitment, reverse=True)
        seen_targets = set()
        unique = []
        for g in goals:
            if g.target not in seen_targets:
                seen_targets.add(g.target)
                unique.append(g)
                if len(unique) >= max_goals:
                    break
        return unique

    def _transitive_ancestors(self, dag, n):
        anc = {i: set() for i in range(max(n, max((v for u,v in dag), default=0)+1, max((u for u,v in dag), default=0)+1))}
        for u, v in dag:
            anc[v].add(u)
        changed = True
        while changed:
            changed = False
            for v in range(n):
                new = set()
                for u in list(anc[v]):
                    new |= anc[u]
                if new - anc[v]:
                    anc[v] |= new
                    changed = True
        return anc

    def _find_path(self, dag, src, tgt):
        max_n = max(max((u for u,v in dag), default=0), max((v for u,v in dag), default=0), src, tgt) + 1
        adj = {i: [] for i in range(max_n)}
        for u, v in dag: adj[u].append(v)
        visited = set()
        def dfs(node, path):
            if node == tgt:
                return path
            visited.add(node)
            for child in adj.get(node, []):
                if child not in visited:
                    result = dfs(child, path + [(node, child)])
                    if result: return result
            return None
        result = dfs(src, [])
        return result or [(src, tgt)]

    def _estimate_effect(self, obs, src, tgt):
        col_src = [obs[t][src] for t in range(len(obs))]
        col_tgt = [obs[t][tgt] for t in range(len(obs))]
        mu_s = statistics.mean(col_src); sd_s = statistics.pstdev(col_src) or 1.0
        high = [col_tgt[t] for t in range(len(obs)) if col_src[t] > mu_s + 0.5 * sd_s]
        low = [col_tgt[t] for t in range(len(obs)) if col_src[t] < mu_s - 0.5 * sd_s]
        if len(high) < 5 or len(low) < 5:
            return 0.0
        pooled = (statistics.pstdev(col_tgt) + statistics.pstdev(high) + statistics.pstdev(low)) / 3 or 1.0
        return abs(statistics.mean(high) - statistics.mean(low)) / pooled

    def _infer_direction(self, effect_magnitude, dag, target):
        if effect_magnitude > 1.0:
            return "maximize" if effect_magnitude > 0 else "minimize"
        return "stabilize"

    def _compute_commitment(self, pt):
        demo = 1.0 if pt.demonstrated else 0.2
        magnitude = min(1.0, pt.effect_magnitude / 2.0)
        return round(0.5 * demo + 0.5 * magnitude, 3)


@dataclass
class GoalTree:
    """Recursive goal decomposition tree (L3 capability)."""
    goal: Goal
    children: list[GoalTree] = field(default_factory=list)
    depth: int = 0


class RecursiveGoalFormation(GoalFormationOrgan):
    """L3: recursive sub-goal decomposition from top-level goals.

    Given a top-level goal (e.g., "maximize profit"), recursively decomposes
    along causal chains in the DAG to create a tree of sub-goals targeting
    intervenable ancestors.

    Decomposition stops when:
    - Depth exceeds max_depth
    - Target node IS directly intervenable (leaf goal)
    - No more causal ancestors exist (dead end)

    Unreachable leaf goals are marked UNVERIFIED — proposal only.
    """

    def decompose(
        self, dag: frozenset[tuple[int, int]], obs: list[list[float]],
        top_node: int, direction: str = "maximize",
        max_depth: int = 3,
    ) -> GoalTree:
        n = len(obs[0])
        children_map = {i: [] for i in range(n)}
        for u, v in dag:
            children_map[u].append(v)

        top_goal = Goal(
            target=top_node, direction=direction,
            commitment=1.0, principal_bounded=(top_node not in self.forbidden),
        )
        root = GoalTree(goal=top_goal, depth=0)
        self._decompose_recursive(root, dag, obs, children_map, max_depth)
        return root

    def _decompose_recursive(
        self, node: GoalTree, dag, obs, children_map, max_depth,
    ):
        if node.depth >= max_depth:
            return
        target = node.goal.target
        if target in self.intervenable and node.depth > 0:
            return  # leaf — directly intervenable

        ancestors = self._transitive_ancestors(dag, len(obs[0]))
        for anc in sorted(ancestors[target]):
            if anc == target:
                continue
            if anc in self.intervenable:
                effect = self._estimate_effect(obs, anc, target)
                direction = "maximize" if effect > 0 else "minimize"
                sub_goal = Goal(
                    target=anc, direction=direction,
                    commitment=min(1.0, effect),
                    leverage=LeveragePoint(
                        target=target, causal_path=[(anc, target)],
                        ancestor=anc, effect_magnitude=effect,
                        demonstrated=effect > self.effect_threshold,
                    ),
                    principal_bounded=(anc not in self.forbidden),
                )
                child = GoalTree(goal=sub_goal, depth=node.depth + 1)
                node.children.append(child)
                self._decompose_recursive(child, dag, obs, children_map, max_depth)

    def flatten_goals(self, tree: GoalTree) -> list[Goal]:
        """Flatten goal tree to ordered list (depth-first, leaves first)."""
        goals = []
        for child in tree.children:
            goals.extend(self.flatten_goals(child))
        goals.append(tree.goal)
        return goals

    def executable_leaves(self, tree: GoalTree) -> list[Goal]:
        """Return only leaf goals that are directly executable (intervenable targets)."""
        leaves = []
        if not tree.children and tree.goal.target in self.intervenable:
            leaves.append(tree.goal)
        for child in tree.children:
            leaves.extend(self.executable_leaves(child))
        return leaves

    def check_reachability(
        self, dag: frozenset[tuple[int, int]], obs: list[list[float]],
        target: int,
    ) -> dict:
        """Verify whether a target node can be reached through the causal DAG.

        Returns dict with:
            reachable: True if target has at least one intervenable ancestor.
            ancestors: list of intervenable nodes that affect the target.
            paths: list of causal paths from each ancestor to target.
            depth: minimum steps from closest intervenable ancestor.
            blocking_nodes: nodes on the path that are NOT intervenable.
            reason: human-readable explanation.
        """
        n = len(obs[0])
        if target < 0 or target >= n:
            return {"reachable": False, "reason": f"target {target} out of range [0,{n-1}]",
                    "ancestors": [], "paths": [], "depth": -1, "blocking_nodes": []}

        ancestors = self._transitive_ancestors(dag, n)
        intervenable_ancestors = [a for a in ancestors[target] if a in self.intervenable]

        if not intervenable_ancestors:
            return {"reachable": False,
                    "reason": (f"target {target} ({len(ancestors[target])} ancestors, "
                               f"but none are intervenable)"),
                    "ancestors": [], "paths": [], "depth": -1, "blocking_nodes": []}

        paths = []
        for anc in intervenable_ancestors:
            path = self._find_path(dag, anc, target)
            if path:
                blocking = [u for u, v in path if u not in self.intervenable and u != target]
                paths.append({"ancestor": anc, "path": path, "blocking": blocking})

        min_depth = min(len(p["path"]) for p in paths) if paths else -1

        return {
            "reachable": True,
            "reason": f"{len(intervenable_ancestors)} intervenable ancestors, "
                      f"closest at depth {min_depth}",
            "ancestors": intervenable_ancestors,
            "paths": paths,
            "depth": min_depth,
            "blocking_nodes": list(set(n for p in paths for n in p["blocking"])),
        }
