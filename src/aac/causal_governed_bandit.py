"""Causal Governed Bandit — M-GAP-3 near-optimal intervention selection.

Thompson-sampling causal bandit with C7 governance constraints, peril-modulated
exploration, and DiBS posterior integration. Replaces the fixed heuristic
disposer D with a Bayesian-optimal intervention selector.

M-GAP-3 Algorithm:
  State = DiBS posterior P(G | h_t)
  Arm   = do(X=x), X in intervenable set
  Reward = -peril_after + gamma * info_gain
  gamma = gamma0 * (1 - peril_before)   # peril kernel
  Selection = Thompson sample DAG -> compute causal effect -> argmax

Regret bound: O(sqrt(T * log|G_0|)) + T * Delta_C7 + O(K log T / Delta_min^2)

Key properties:
- Pure stdlib. Integrates with GovernedDiBS from bayesian_dag_posterior.
- C7-governed: only legal interventions pass through.
- Peril-modulated: high peril -> pure exploitation (safe mode).
- Regret tracking: cumulative regret vs oracle and vs UCB1 baseline.
"""
from __future__ import annotations

import math
import random


class CausalBanditArm:
    """An intervention arm: do(node=value) on an intervenable node.

    Args:
        node: the causal variable index to intervene on.
        value: the intervention value.
        is_legal: whether C7 allows this intervention.
    """

    def __init__(self, node: int, value: float, is_legal: bool = True):
        self.node = node
        self.value = value
        self.is_legal = is_legal

    def __repr__(self):
        return f"do(X{self.node}={self.value:.2f})"


class CausalGovernedBandit:
    """Causal bandit with governance constraints per M-GAP-3.

    Selects interventions by Thompson-sampling from the DiBS DAG posterior,
    computing causal effects through the sampled DAG, and selecting the arm
    that maximizes expected reward.

    Args:
        n_nodes: number of causal variables.
        arms: list of CausalBanditArm (intervention candidates).
        gamma0: base exploration weight. Default 1.0.
        target_node: which node's outcome determines reward. Default 0.
        seed: RNG seed.
    """

    def __init__(
        self,
        n_nodes: int,
        arms: list[CausalBanditArm] | None = None,
        gamma0: float = 1.0,
        target_node: int = 0,
        seed: int = 0,
    ):
        self.n = n_nodes
        self.arms = arms or []
        self.gamma0 = gamma0
        self.target = target_node
        self.rng = random.Random(seed)

        self.legal_arms = [a for a in self.arms if a.is_legal]
        self.n_legal = len(self.legal_arms)

        self.t = 0
        self.history: list[dict] = []
        self.cumulative_reward = 0.0
        self.cumulative_regret = 0.0
        self._arm_counts = {i: 0 for i in range(len(self.arms))}
        self._arm_rewards = {i: 0.0 for i in range(len(self.arms))}
        self._peril_trajectory: list[float] = []

    def peril_kernel(self, peril: float) -> float:
        """Compute exploration weight gamma from current peril level.

        gamma = gamma0 * (1 - peril)
        High peril -> gamma -> 0 -> pure exploitation (safe mode).
        Low peril -> gamma -> gamma0 -> full exploration.
        """
        return self.gamma0 * max(0.0, 1.0 - peril)

    def thompson_sample(
        self,
        di_particles: list[frozenset],
        di_weights: list[float],
        obs: list[list[float]] | None = None,
        peril: float = 0.0,
    ) -> tuple[int, CausalBanditArm, dict]:
        """Select the best arm via Thompson sampling from DiBS posterior.

        1. Sample a DAG from the particle posterior.
        2. For each legal arm, estimate causal effect on target node
           by propagating the intervention through the sampled DAG.
        3. Compute reward = -peril_after_estimate + gamma * info_gain.
        4. Return the arm with maximum expected reward.

        Args:
            di_particles: list of DAG candidate frozensets.
            di_weights: posterior weights for each particle.
            obs: observational data for likelihood estimation.
            peril: current peril level Phi_t in [0, 1].

        Returns:
            (arm_index, arm, debug_info_dict)
        """
        gamma = self.peril_kernel(peril)
        if not self.legal_arms:
            return (-1, CausalBanditArm(-1, 0.0), {"gamma": gamma, "reason": "no_legal_arms"})

        sample_idx = self._sample_from_weights(di_weights)
        sampled_dag = di_particles[sample_idx]

        best_idx = 0
        best_score = float("-inf")
        scores = []

        for i, arm in enumerate(self.arms):
            if not arm.is_legal:
                scores.append(float("-inf"))
                continue

            causal_effect = self._estimate_causal_effect(sampled_dag, arm.node, arm.value, self.target)

            info_gain = self._estimate_info_gain(
                sampled_dag, arm.node, obs, di_particles, di_weights,
            )

            peril_after_estimate = self._estimate_peril_after(arm, causal_effect, peril)

            reward = -peril_after_estimate + gamma * info_gain
            scores.append(reward)

            if reward > best_score:
                best_score = reward
                best_idx = i

        return (
            best_idx,
            self.arms[best_idx],
            {
                "gamma": gamma,
                "peril": peril,
                "sampled_particle": sample_idx,
                "scores": scores,
                "best_score": best_score,
            },
        )

    def update(
        self,
        arm_idx: int,
        outcome: list[float],
        peril_before: float,
        peril_after: float,
        info_gain: float = 0.0,
    ):
        """Update bandit state after observing intervention outcome.

        Args:
            arm_idx: index of the selected arm.
            outcome: the observed data row after intervention.
            peril_before: peril level before the action.
            peril_after: peril level after the action.
            info_gain: estimated information gain from this intervention.
        """
        gamma = self.peril_kernel(peril_before)
        reward = -peril_after + gamma * info_gain

        self._arm_counts[arm_idx] = self._arm_counts.get(arm_idx, 0) + 1
        self._arm_rewards[arm_idx] = self._arm_rewards.get(arm_idx, 0.0) + reward

        self.cumulative_reward += reward
        self._peril_trajectory.append(peril_after)

        self.history.append({
            "t": self.t,
            "arm_idx": arm_idx,
            "arm_node": self.arms[arm_idx].node if arm_idx < len(self.arms) else -1,
            "arm_value": self.arms[arm_idx].value if arm_idx < len(self.arms) else 0.0,
            "peril_before": peril_before,
            "peril_after": peril_after,
            "gamma": gamma,
            "info_gain": info_gain,
            "reward": reward,
        })
        self.t += 1

    def compute_regret(
        self, oracle_reward_per_arm: list[float] | None = None
    ) -> float:
        """Compute cumulative regret.

        Regret = sum_t (mu(a*) - mu(a_t))
        where a* is the optimal arm and a_t is the selected arm at round t.

        If oracle_reward_per_arm is not provided, uses the best observed mean.
        """
        if oracle_reward_per_arm is not None:
            oracle_best = max(oracle_reward_per_arm)
        else:
            oracle_best = max(
                (self._arm_rewards[i] / max(self._arm_counts[i], 1)
                 for i in range(len(self.arms))),
                default=0.0,
            )

        regret = 0.0
        for h in self.history:
            arm_r = h["reward"]
            regret += max(0.0, oracle_best - arm_r)
        self.cumulative_regret = regret
        return regret

    def governance_regret(
        self, forbidden_arms: set[int], oracle_reward_per_arm: list[float],
    ) -> float:
        """Compute the governance regret from C7-prohibited arms.

        Delta_C7 = max_{a in forbidden} mu(a) - max_{a in legal} mu(a)
        Cumulative governance regret = T * Delta_C7
        """
        best_forbidden = max(
            (oracle_reward_per_arm[i] for i in forbidden_arms
             if i < len(oracle_reward_per_arm)),
            default=0.0,
        )
        best_legal = max(
            (oracle_reward_per_arm[i] for i in range(len(oracle_reward_per_arm))
             if i not in forbidden_arms),
            default=0.0,
        )
        delta_c7 = max(0.0, best_forbidden - best_legal)
        return self.t * delta_c7

    def arm_statistics(self) -> dict[int, dict]:
        """Return per-arm statistics: pulls, mean reward, UCB bound."""
        stats = {}
        for i in range(len(self.arms)):
            n = self._arm_counts.get(i, 0)
            mean_r = self._arm_rewards.get(i, 0.0) / max(n, 1)
            ucb = mean_r + math.sqrt(2.0 * math.log(max(self.t, 1)) / max(n, 1))
            stats[i] = {
                "node": self.arms[i].node,
                "value": self.arms[i].value,
                "legal": self.arms[i].is_legal,
                "pulls": n,
                "mean_reward": mean_r,
                "ucb": ucb,
            }
        return stats

    @property
    def best_arm_index(self) -> int:
        """Index of the arm with highest empirical mean reward."""
        if not self.legal_arms:
            return -1
        best = max(
            range(len(self.arms)),
            key=lambda i: (
                self._arm_rewards.get(i, 0.0) / max(self._arm_counts.get(i, 1), 1)
                if self.arms[i].is_legal else float("-inf")
            ),
        )
        return best if self.arms[best].is_legal else -1

    @property
    def peril_mean(self) -> float:
        if not self._peril_trajectory:
            return 0.0
        return sum(self._peril_trajectory) / len(self._peril_trajectory)

    def _sample_from_weights(self, weights: list[float]) -> int:
        r = self.rng.random()
        cum = 0.0
        for i, w in enumerate(weights):
            cum += w
            if r <= cum:
                return i
        return len(weights) - 1

    def _estimate_causal_effect(
        self,
        dag: frozenset,
        intervene_node: int,
        intervene_value: float,
        target_node: int,
    ) -> float:
        """Estimate causal effect of do(X=value) on target through given DAG.

        For linear SCM: propagates the intervention value through DAG edges.
        If intervene_node is an ancestor of target_node in the DAG, the effect
        is estimated as the product of edge coefficients along the path.

        Simplified estimate: uses topological distance and edge presence.
        """
        if intervene_node == target_node:
            return 1.0

        parents = {j: [] for j in range(self.n)}
        for u, v in dag:
            parents[v].append(u)

        descendants = self._descendants(intervene_node, dag)
        if target_node not in descendants:
            return 0.0

        paths = self._find_paths(intervene_node, target_node, dag, max_paths=10)
        if not paths:
            return 0.0

        effect = 0.0
        for path in paths:
            path_effect = 1.0
            for i in range(len(path) - 1):
                n_children = len([c for c in parents.get(path[i+1], [])])
                path_effect *= 0.5 / max(n_children, 1)
            effect += path_effect * abs(intervene_value)

        return min(effect, 1.0)

    def _descendants(self, node: int, dag: frozenset) -> set[int]:
        children = {j for u, j in dag if u == node}
        result = set(children)
        for c in list(children):
            result |= self._descendants(c, dag)
        return result

    def _find_paths(
        self, src: int, dst: int, dag: frozenset,
        max_paths: int = 10, max_depth: int = 10,
    ) -> list[list[int]]:
        children = {j: [] for j in range(self.n)}
        for u, v in dag:
            children[u].append(v)
        paths = []

        def dfs(node, visited, current_path):
            if len(paths) >= max_paths:
                return
            if node == dst:
                paths.append(list(current_path))
                return
            if len(current_path) >= max_depth:
                return
            for child in children.get(node, []):
                if child not in visited:
                    visited.add(child)
                    current_path.append(child)
                    dfs(child, visited, current_path)
                    current_path.pop()
                    visited.discard(child)

        dfs(src, {src}, [src])
        return paths

    def _estimate_info_gain(
        self,
        sampled_dag: frozenset,
        intervene_node: int,
        obs: list[list[float]] | None,
        di_particles: list[frozenset],
        di_weights: list[float],
    ) -> float:
        """Estimate information gain from intervening on a node.

        Simplified: uses the number of DAG candidates that would be
        discriminated by this intervention. If the intervene node has
        ambiguous parent sets across particles, intervening provides
        high information gain.

        Returns estimated EIG in [0, 1].
        """
        if obs is None:
            return 0.1

        parent_sets = {}
        for p_idx, dag in enumerate(di_particles):
            parents = tuple(sorted(u for u, v in dag if v == intervene_node))
            parent_sets[parents] = parent_sets.get(parents, 0.0) + di_weights[p_idx]

        if len(parent_sets) <= 1:
            return 0.0

        entropy = 0.0
        for w in parent_sets.values():
            if w > 0:
                entropy -= w * math.log(w)
        max_entropy = math.log(len(parent_sets))
        if max_entropy <= 0:
            return 0.0
        return entropy / max_entropy

    def _estimate_peril_after(
        self,
        arm: CausalBanditArm,
        causal_effect: float,
        peril_before: float,
    ) -> float:
        """Estimate peril after taking action.

        If the intervention has a strong causal effect, it likely reduces
        uncertainty and therefore peril. If the effect is weak or zero, peril
        stays the same or increases (wasted intervention).
        """
        if abs(causal_effect) < 0.01:
            return min(1.0, peril_before + 0.02)
        reduction = min(0.3, abs(causal_effect) * 0.5)
        return max(0.0, peril_before - reduction)


def ucb1_baseline(
    arms: list[CausalBanditArm],
    n_rounds: int,
    oracle_rewards: list[float] | None = None,
    seed: int = 0,
) -> dict:
    """Standard UCB1 bandit (no causal structure) as a baseline.

    Each arm is treated as independent. UCB = mean + sqrt(2*ln(t)/n).

    Returns dict with cumulative reward, regret, arm statistics.
    """
    rng = random.Random(seed)
    n_arms = len(arms)
    counts = [0] * n_arms
    rewards_sum = [0.0] * n_arms
    total_reward = 0.0
    regret = 0.0

    oracle_best = max(oracle_rewards) if oracle_rewards else 0.0

    legal_indices = [i for i, a in enumerate(arms) if a.is_legal]
    if not legal_indices:
        return {"total_reward": 0.0, "regret": 0.0, "counts": counts}

    for t in range(1, n_rounds + 1):
        ucb_values = []
        for i in range(n_arms):
            if counts[i] == 0:
                ucb_values.append(float("inf"))
            else:
                mean_r = rewards_sum[i] / counts[i]
                exploration = math.sqrt(2.0 * math.log(t) / counts[i])
                ucb_values.append(mean_r + exploration)

        best = max(
            legal_indices,
            key=lambda i: ucb_values[i],
        )

        r = oracle_rewards[best] + rng.gauss(0, 0.1) if oracle_rewards else rng.random()
        r = max(0.0, r)

        counts[best] += 1
        rewards_sum[best] += r
        total_reward += r

        if oracle_rewards:
            regret += max(0.0, oracle_best - r)

    return {
        "total_reward": total_reward,
        "regret": regret,
        "counts": counts,
        "mean_rewards": [rewards_sum[i] / max(counts[i], 1) for i in range(n_arms)],
    }
