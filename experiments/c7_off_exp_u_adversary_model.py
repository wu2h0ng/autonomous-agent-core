"""EXP-U: Adversary Modeling — predicting what the adversary will ban.

Question: If the agent models the adversary's ban strategy and AVOIDS the
lever that will be banned next round, can it maintain positive reward?

Key insight: reactive adversary bans the agent's most-used lever. If the
agent KNOWS this, it can:
  1. Never concentrate on one lever (uniform distribution)
  2. Predict which lever will be banned and pre-avoid it
  3. Deliberately cycle through levers to keep adversary chasing

Arms:
  U-naive:     No adversary model (gets banned repeatedly)
  U-uniform:   Spreads actions uniformly across causal levers
  U-model:     Explicitly models adversary rule and avoids predicted ban
  U-counter:   Counter-strategy: deliberately targets NON-top-frequency lever

Run: PYTHONPATH=src:experiments python experiments/c7_off_exp_u_adversary_model.py
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

D = 8
TOTAL_ROUNDS = 300
SEEDS = tuple(range(30))


class Env:
    def __init__(self, rng: random.Random) -> None:
        indices = list(range(D))
        rng.shuffle(indices)
        self.primary = indices[0]
        self.secondary = indices[1]
        self.tertiary = indices[2]

    def reward_for_lever(self, lever: int) -> float:
        if lever == self.primary:
            return 1.0
        elif lever == self.secondary:
            return 0.6
        elif lever == self.tertiary:
            return 0.3
        return 0.0

    def is_causal(self, lever: int) -> bool:
        return lever in (self.primary, self.secondary, self.tertiary)


class ReactiveAdversary:
    def __init__(self, env: Env, rng: random.Random) -> None:
        self.env = env
        self.history: list[int] = []
        self.forbidden: set[int] = {env.primary}

    def observe_and_update(self, action: int) -> None:
        self.history.append(action)
        if len(self.history) >= 5:
            recent = self.history[-10:]
            counts = Counter(recent)
            self.forbidden = {counts.most_common(1)[0][0]}

    def get_forbidden(self) -> set[int]:
        return self.forbidden


class Gate:
    def __init__(self, adversary: ReactiveAdversary, env: Env) -> None:
        self.adversary = adversary
        self.env = env

    def decide(self, lever: int) -> tuple[str, str, float]:
        if lever in self.adversary.get_forbidden():
            return "DENY", "FORBIDDEN", 0.0
        if not self.env.is_causal(lever):
            return "VERIFY_MORE", "LOW_CONFIDENCE", 0.0
        return "ALLOW", "ALLOWED", self.env.reward_for_lever(lever)


# ============================================================================
# AGENTS
# ============================================================================

class NaiveAgent:
    """No adversary model — always picks highest-reward lever."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.alpha: dict[int, float] = {i: 1.0 for i in range(D)}
        self.beta_param: dict[int, float] = {i: 1.0 for i in range(D)}
        self.forbidden: set[int] = set()

    def propose(self) -> int:
        scores = {}
        for i in range(D):
            if i in self.forbidden:
                scores[i] = -1000.0
                continue
            scores[i] = self.rng.betavariate(self.alpha[i], self.beta_param[i])
        return max(scores, key=scores.get)

    def update(self, lever: int, reward: float, rejected: bool, reason: str) -> None:
        if rejected and reason == "FORBIDDEN":
            self.forbidden.add(lever)
        elif not rejected and reward > 0.3:
            self.alpha[lever] += 1.0
        elif not rejected:
            self.beta_param[lever] += 0.5

    def decay(self) -> None:
        for i in range(D):
            self.alpha[i] = 1.0 + (self.alpha[i] - 1.0) * 0.97
            self.beta_param[i] = 1.0 + (self.beta_param[i] - 1.0) * 0.97
        if self.rng.random() < 0.1:
            self.forbidden = set()


class UniformAgent:
    """Spreads actions uniformly across all causal levers to avoid concentration."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.known_causal: list[int] = []
        self.last_idx = 0
        self.forbidden: set[int] = set()

    def propose(self) -> int:
        available = [i for i in self.known_causal if i not in self.forbidden]
        if available:
            self.last_idx = (self.last_idx + 1) % len(available)
            return available[self.last_idx]
        return self.rng.randrange(D)

    def update(self, lever: int, reward: float, rejected: bool, reason: str) -> None:
        if rejected and reason == "FORBIDDEN":
            self.forbidden.add(lever)
        elif not rejected and reward > 0 and lever not in self.known_causal:
            self.known_causal.append(lever)

    def decay(self) -> None:
        if self.rng.random() < 0.1:
            self.forbidden = set()


class AdversaryModelAgent:
    """Explicitly models the adversary's ban rule and pre-avoids."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.own_history: list[int] = []
        self.known_causal: list[int] = []
        self.rewards: dict[int, float] = {}
        self.forbidden: set[int] = set()

    def _predict_ban(self) -> int:
        """Predict which lever adversary will ban (mirror adversary logic)."""
        if len(self.own_history) < 5:
            return -1
        recent = self.own_history[-10:]
        counts = Counter(recent)
        return counts.most_common(1)[0][0]

    def propose(self) -> int:
        predicted_ban = self._predict_ban()
        available = [i for i in self.known_causal
                     if i not in self.forbidden and i != predicted_ban]
        if available:
            # Pick best among non-banned, non-predicted-ban
            best = max(available, key=lambda i: self.rewards.get(i, 0.5) + self.rng.random() * 0.1)
            return best
        # Fallback: explore
        unexplored = [i for i in range(D) if i not in self.known_causal and i not in self.forbidden]
        if unexplored:
            return self.rng.choice(unexplored)
        return self.rng.randrange(D)

    def update(self, lever: int, reward: float, rejected: bool, reason: str) -> None:
        self.own_history.append(lever)
        if rejected and reason == "FORBIDDEN":
            self.forbidden.add(lever)
        elif not rejected:
            if reward > 0 and lever not in self.known_causal:
                self.known_causal.append(lever)
            self.rewards[lever] = reward

    def decay(self) -> None:
        if self.rng.random() < 0.1:
            self.forbidden = set()


class CounterStrategyAgent:
    """Counter-strategy: deliberately picks the LEAST frequent recent lever
    to ensure adversary can never lock onto one target."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.own_history: list[int] = []
        self.known_causal: list[int] = []
        self.forbidden: set[int] = set()

    def propose(self) -> int:
        available = [i for i in self.known_causal if i not in self.forbidden]
        if not available:
            unexplored = [i for i in range(D) if i not in self.forbidden]
            return self.rng.choice(unexplored) if unexplored else self.rng.randrange(D)

        if len(self.own_history) < 5:
            return self.rng.choice(available)

        # Pick LEAST recently used causal lever
        recent = self.own_history[-15:]
        counts = Counter(recent)
        # Sort available by frequency (ascending) — pick least frequent
        available_sorted = sorted(available, key=lambda i: counts.get(i, 0))
        return available_sorted[0]

    def update(self, lever: int, reward: float, rejected: bool, reason: str) -> None:
        self.own_history.append(lever)
        if rejected and reason == "FORBIDDEN":
            self.forbidden.add(lever)
        elif not rejected and reward > 0 and lever not in self.known_causal:
            self.known_causal.append(lever)

    def decay(self) -> None:
        if self.rng.random() < 0.1:
            self.forbidden = set()


# ============================================================================
# RUNNER
# ============================================================================

@dataclass
class ArmResult:
    arm_name: str
    total_reward: float = 0.0
    forbidden_blocked: int = 0
    rounds_with_reward: int = 0


def run_arm(agent_class: type, arm_name: str) -> ArmResult:
    result = ArmResult(arm_name=arm_name)
    for seed in SEEDS:
        rng = random.Random(seed)
        env = Env(rng)
        agent = agent_class(random.Random(seed + 21000))
        adversary = ReactiveAdversary(env, random.Random(seed + 22000))
        gate = Gate(adversary, env)

        for _ in range(TOTAL_ROUNDS):
            lever = agent.propose()
            verdict, reason, reward = gate.decide(lever)
            agent.update(lever, reward, verdict != "ALLOW", reason)
            if verdict == "ALLOW":
                result.total_reward += reward
                result.rounds_with_reward += 1
            elif verdict == "DENY":
                result.forbidden_blocked += 1
            adversary.observe_and_update(lever)
            agent.decay()

    return result


def main() -> None:
    print("\n" + "=" * 80)
    print("  EXP-U: Adversary Modeling")
    print("  Can predicting the adversary's strategy maintain positive reward?")
    print(f"  {len(SEEDS)} seeds × {TOTAL_ROUNDS} rounds, D={D}")
    print("=" * 80)

    naive_r = run_arm(NaiveAgent, "U-naive")
    uniform_r = run_arm(UniformAgent, "U-uniform")
    model_r = run_arm(AdversaryModelAgent, "U-model")
    counter_r = run_arm(CounterStrategyAgent, "U-counter")

    arms = [naive_r, uniform_r, model_r, counter_r]
    names = ["Naive", "Uniform", "Model", "Counter"]

    print(f"\n  {'Metric':<40} {'Naive':>9} {'Uniform':>9} {'Model':>9} {'Counter':>9}")
    print(f"  {'-'*40} {'-'*9} {'-'*9} {'-'*9} {'-'*9}")

    print(f"  {'Total reward':<40}", end="")
    for a in arms:
        print(f" {a.total_reward:>9.1f}", end="")
    print()

    print(f"  {'Rounds with reward':<40}", end="")
    for a in arms:
        print(f" {a.rounds_with_reward:>9}", end="")
    print()

    print(f"  {'Forbidden blocked':<40}", end="")
    for a in arms:
        print(f" {a.forbidden_blocked:>9}", end="")
    print()

    reward_rate = [a.total_reward / (TOTAL_ROUNDS * len(SEEDS)) for a in arms]
    print(f"  {'Reward per round':<40}", end="")
    for v in reward_rate:
        print(f" {v:>8.4f}", end=" ")
    print()

    # Verdicts
    print(f"\n  {'─'*80}")
    print("  VERDICTS:")

    best_idx = max(range(4), key=lambda i: arms[i].total_reward)
    print(f"  ✓ Best strategy: {names[best_idx]} (reward {arms[best_idx].total_reward:.1f})")

    if model_r.total_reward > naive_r.total_reward:
        gain = (model_r.total_reward - naive_r.total_reward) / max(abs(naive_r.total_reward), 1) * 100
        print(f"  ✓ Adversary modeling: +{gain:.0f}% over naive")
    if counter_r.total_reward > naive_r.total_reward:
        gain = (counter_r.total_reward - naive_r.total_reward) / max(abs(naive_r.total_reward), 1) * 100
        print(f"  ✓ Counter-strategy: +{gain:.0f}% over naive")
    if counter_r.forbidden_blocked < naive_r.forbidden_blocked:
        reduction = (naive_r.forbidden_blocked - counter_r.forbidden_blocked) / naive_r.forbidden_blocked * 100
        print(f"  ✓ Counter-strategy reduces bans by {reduction:.0f}%")

    print(f"\n  INTERPRETATION:")
    print(f"  The naive agent concentrates on its best lever → adversary locks onto it.")
    print(f"  Adversary modeling lets the agent PREDICT and AVOID the predicted ban.")
    print(f"  Counter-strategy (least-frequent selection) prevents concentration,")
    print(f"  making the adversary's reactive ban ineffective.")
    print(f"\n  THEORETICAL SIGNIFICANCE:")
    print(f"  This is GAME THEORY at toy scale: the agent plays a mixed strategy")
    print(f"  against the adversary's pure (reactive) strategy. Nash equilibrium")
    print(f"  predicts uniform mixing when adversary is best-responding.")
    print(f"  The counter-strategy approximates this without explicit game theory.")


if __name__ == "__main__":
    main()
