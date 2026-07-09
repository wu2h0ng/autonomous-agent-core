"""Online learned selection policy for the strong-locus crossover.

A tabular Q/UCB policy that learns which interventions reduce posterior entropy
from the single-environment trajectory it shares with the governed loop. It
proposes interventions; the deterministic disposer still holds final authority.

Boundary contract (RR-0043 / CWM-LEARN-4):
  - No cross-environment pretraining.
  - No held-out source-domain data.
  - No pretrained encoder carried across environments.
  - Per-seed random init.

Pure stdlib.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Protocol

try:
    from .organ_tools import PosteriorState, belief_update
except ImportError:
    from organ_tools import PosteriorState, belief_update


@dataclass
class LearnedSelector:
    """Tabular UCB selector over (node, value) intervention candidates."""

    candidate_keys: list[tuple[int, float]]
    seed: int = 0
    ucb_alpha: float = 1.0

    # per-arm statistics learned online within the current trajectory
    counts: dict[tuple[int, float], int] = field(default_factory=dict)
    rewards: dict[tuple[int, float], float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key in self.candidate_keys:
            self.counts.setdefault(key, 0)
            self.rewards.setdefault(key, 0.0)

    def select(self, step: int) -> tuple[int, float]:
        """UCB1 selection: balance exploitation and exploration."""
        rng = random.Random(self.seed + step)
        best_key: tuple[int, float] | None = None
        best_score = float("-inf")
        for key in self.candidate_keys:
            n = self.counts.get(key, 0)
            mean_reward = self.rewards.get(key, 0.0) / max(1, n)
            bonus = self.ucb_alpha * math.sqrt(math.log(step + 2) / max(1, n))
            score = mean_reward + bonus
            if score > best_score or (score == best_score and rng.random() < 0.5):
                best_score = score
                best_key = key
        assert best_key is not None
        return best_key

    def update(
        self,
        key: tuple[int, float],
        reward: float,
    ) -> None:
        """Record observed reward for the selected intervention."""
        self.counts[key] = self.counts.get(key, 0) + 1
        self.rewards[key] = self.rewards.get(key, 0.0) + reward


@dataclass
class LearnedSelectResult:
    edge_scores: dict[tuple[int, int], float]
    interventions_spent: int
    posterior_state: PosteriorState
    trace: list[dict[str, Any]] = field(default_factory=list)


class Disposer(Protocol):
    def __call__(self, action_index: int, risk_tier: int = 1) -> str:
        """Return ALLOW, VERIFY_MORE, ESCALATE, or DENY."""


def _default_allow_disposer(action_index: int, risk_tier: int = 1) -> str:
    return "ALLOW"


def run_learned_select(
    observational: list[list[float]],
    consultable_interventions: dict[tuple[int, float], list[list[float]]],
    budget: int,
    n_particles: int = 50,
    seed: int = 0,
    ucb_alpha: float = 1.0,
    disposer: Disposer | None = None,
) -> LearnedSelectResult:
    """Run the online learned selection arm.

    The selector learns from entropy reduction rewards observed only within the
    current environment trajectory. No weights are loaded from other environments.
    The learned policy proposes; the disposer callback decides whether to execute.
    """
    disposer = disposer or _default_allow_disposer
    rng = random.Random(seed)
    candidate_keys = sorted(consultable_interventions.keys())
    if not candidate_keys:
        raise ValueError("No consultable interventions provided")

    selector = LearnedSelector(
        candidate_keys=candidate_keys, seed=seed, ucb_alpha=ucb_alpha
    )
    observations: list[list[float]] = [list(row) for row in observational]
    posterior: PosteriorState | None = None
    spent = 0
    trace: list[dict[str, Any]] = []

    for step in range(budget):
        posterior = belief_update(observations, posterior, n_particles, seed=seed + step)
        entropy_before = _approx_entropy(posterior.weights)

        target, value = selector.select(step)
        key = (target, value)
        if key not in consultable_interventions:
            trace.append({"step": step, "event": "key_missing", "key": key})
            break

        verdict = disposer(target, risk_tier=1)
        if verdict != "ALLOW":
            trace.append(
                {"step": step, "event": "disposer_reject", "verdict": verdict, "spent": spent}
            )
            break

        sampled = rng.choice(consultable_interventions[key])
        observations.append(list(sampled))
        spent += 1

        posterior = belief_update(observations, posterior, n_particles, seed=seed + step + 1)
        entropy_after = _approx_entropy(posterior.weights)
        reward = max(0.0, entropy_before - entropy_after)
        selector.update(key, reward)

        trace.append(
            {
                "step": step,
                "event": "intervene",
                "target": target,
                "value": value,
                "reward": reward,
                "spent": spent,
            }
        )

    if posterior is None:
        posterior = belief_update(observations, None, n_particles, seed=seed)
    edge_scores = posterior.to_dibs(seed).edge_marginals()

    return LearnedSelectResult(
        edge_scores=edge_scores,
        interventions_spent=spent,
        posterior_state=posterior,
        trace=trace,
    )


def _approx_entropy(weights: list[float]) -> float:
    ent = 0.0
    for w in weights:
        if w > 1e-15:
            ent -= w * math.log(w)
    return ent


if __name__ == "__main__":
    import sys

    sys.path.insert(0, "experiments")
    from scm_generator import generate_scm, SCMConfig

    world = generate_scm(SCMConfig(n_nodes=6, n_obs=200, seed=42))
    all_keys = list(world.interventions.keys())
    rng = random.Random(123)
    rng.shuffle(all_keys)
    consultable = {k: world.interventions[k] for k in all_keys[: len(all_keys) // 2]}

    result = run_learned_select(
        world.observational,
        consultable,
        budget=3,
        seed=42,
        n_particles=20,
    )
    print("interventions_spent:", result.interventions_spent)
    print("edge_scores sample:", sorted(result.edge_scores.items(), key=lambda x: x[1], reverse=True)[:5])
    print("trace:", result.trace)
