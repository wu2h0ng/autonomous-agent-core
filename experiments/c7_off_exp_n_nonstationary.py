"""EXP-N: Non-Stationary Environments — changing causal structure.

Question: When the causal structure CHANGES (the true causal lever switches),
can the agent detect the change and adapt, or does it get stuck on stale beliefs?

This tests whether rejection memory / causal beliefs need a FORGETTING mechanism.

Design:
  - Phase 1 (rounds 0-49): primary lever = A, secondary = B
  - Phase 2 (rounds 50-99): primary lever shifts to C, secondary = D
  - Phase 3 (rounds 100-149): primary shifts BACK to A (tests reactivation)

Arms:
  N-static:    Agent with no forgetting (beliefs are permanent)
  N-windowed:  Agent with sliding window (only recent N observations matter)
  N-changepoint: Agent with explicit change detection (monitors reward rate drop)
  N-bayesian:  Agent with Bayesian belief update + prior decay

Key metrics:
  - adaptation_speed: rounds after change to find new optimal lever
  - stale_action_rate: fraction of rounds acting on the OLD optimal after change
  - total_regret: cumulative gap between best and actual reward
  - reactivation_speed: rounds to re-find A when it becomes optimal again

Run: PYTHONPATH=src:experiments python experiments/c7_off_exp_n_nonstationary.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

D = 6
TOTAL_ROUNDS = 150
PHASE_1_END = 50
PHASE_2_END = 100
SEEDS = tuple(range(30))


class NonStationaryEnv:
    """Environment where the causal structure changes at phase boundaries."""

    def __init__(self, rng: random.Random) -> None:
        indices = list(range(D))
        rng.shuffle(indices)
        self.phase_1_primary = indices[0]
        self.phase_1_secondary = indices[1]
        self.phase_2_primary = indices[2]
        self.phase_2_secondary = indices[3]
        self.current_phase = 1

    def set_phase(self, phase: int) -> None:
        self.current_phase = phase

    @property
    def primary(self) -> int:
        if self.current_phase == 1 or self.current_phase == 3:
            return self.phase_1_primary
        return self.phase_2_primary

    @property
    def secondary(self) -> int:
        if self.current_phase == 1 or self.current_phase == 3:
            return self.phase_1_secondary
        return self.phase_2_secondary

    def reward_for_lever(self, lever: int) -> float:
        if lever == self.primary:
            return 1.0
        elif lever == self.secondary:
            return 0.6
        return 0.0


class SimpleVerifier:
    def __init__(self, env: NonStationaryEnv) -> None:
        self.env = env

    def verify(self, lever: int) -> tuple[bool, float]:
        is_causal = lever in (self.env.primary, self.env.secondary)
        confidence = 0.9 if is_causal else 0.1
        return is_causal, confidence


# ============================================================================
# AGENTS
# ============================================================================

class StaticAgent:
    """No forgetting: beliefs accumulate forever. Gets stuck on stale knowledge."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.rewards: dict[int, float] = {i: 0.0 for i in range(D)}
        self.attempts: dict[int, int] = {i: 0 for i in range(D)}

    def propose(self) -> list[int]:
        scores = {}
        for i in range(D):
            base = self.rewards[i] / max(self.attempts[i], 1)
            exploration = 0.2 / (1 + self.attempts[i])
            scores[i] = base + exploration + self.rng.random() * 0.05
        return sorted(range(D), key=lambda i: -scores[i])

    def update(self, lever: int, reward: float) -> None:
        self.attempts[lever] += 1
        self.rewards[lever] += reward

    def reset_signal(self) -> None:
        pass


class WindowedAgent:
    """Sliding window: only uses last W observations per lever."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.window_size = 15
        self.history: dict[int, list[float]] = {i: [] for i in range(D)}

    def propose(self) -> list[int]:
        scores = {}
        for i in range(D):
            window = self.history[i][-self.window_size:]
            if window:
                base = sum(window) / len(window)
            else:
                base = 0.5
            exploration = 0.3 / (1 + len(self.history[i]))
            scores[i] = base + exploration + self.rng.random() * 0.05
        return sorted(range(D), key=lambda i: -scores[i])

    def update(self, lever: int, reward: float) -> None:
        self.history[lever].append(reward)

    def reset_signal(self) -> None:
        pass


class ChangePointAgent:
    """Explicit change detection: monitors reward rate, resets on drop."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.rewards: dict[int, float] = {i: 0.0 for i in range(D)}
        self.attempts: dict[int, int] = {i: 0 for i in range(D)}
        self.recent_rewards: list[float] = []
        self.recent_window = 10
        self.baseline_rate: float = 0.0
        self.drop_threshold = 0.3

    def propose(self) -> list[int]:
        scores = {}
        for i in range(D):
            base = self.rewards[i] / max(self.attempts[i], 1)
            exploration = 0.3 / (1 + self.attempts[i])
            scores[i] = base + exploration + self.rng.random() * 0.05
        return sorted(range(D), key=lambda i: -scores[i])

    def update(self, lever: int, reward: float) -> None:
        self.attempts[lever] += 1
        self.rewards[lever] += reward
        self.recent_rewards.append(reward)

        if len(self.recent_rewards) > self.recent_window:
            recent_rate = sum(self.recent_rewards[-self.recent_window:]) / self.recent_window
            if self.baseline_rate > 0 and recent_rate < self.baseline_rate - self.drop_threshold:
                self._soft_reset()
            if recent_rate > self.baseline_rate:
                self.baseline_rate = recent_rate * 0.9 + self.baseline_rate * 0.1

    def _soft_reset(self) -> None:
        for i in range(D):
            self.rewards[i] *= 0.2
            self.attempts[i] = max(1, self.attempts[i] // 3)
        self.baseline_rate = 0.0

    def reset_signal(self) -> None:
        pass


class BayesianDecayAgent:
    """Bayesian with prior decay: old evidence contributes less over time."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.alpha: dict[int, float] = {i: 1.0 for i in range(D)}
        self.beta_param: dict[int, float] = {i: 1.0 for i in range(D)}
        self.decay = 0.95

    def propose(self) -> list[int]:
        scores = {}
        for i in range(D):
            sample = self.rng.betavariate(self.alpha[i], self.beta_param[i])
            scores[i] = sample
        return sorted(range(D), key=lambda i: -scores[i])

    def update(self, lever: int, reward: float) -> None:
        for i in range(D):
            self.alpha[i] = 1.0 + (self.alpha[i] - 1.0) * self.decay
            self.beta_param[i] = 1.0 + (self.beta_param[i] - 1.0) * self.decay
        if reward > 0.5:
            self.alpha[lever] += 1.0
        else:
            self.beta_param[lever] += 1.0

    def reset_signal(self) -> None:
        pass


# ============================================================================
# EXPERIMENT RUNNER
# ============================================================================

@dataclass
class ArmResult:
    arm_name: str
    phase_1_reward: float = 0.0
    phase_2_reward: float = 0.0
    phase_3_reward: float = 0.0
    phase_2_adaptation: list[int] = field(default_factory=list)
    phase_3_reactivation: list[int] = field(default_factory=list)
    stale_actions_phase_2: int = 0
    total_regret: float = 0.0


def run_arm(agent_class: type, arm_name: str) -> ArmResult:
    result = ArmResult(arm_name=arm_name)

    for seed in SEEDS:
        rng = random.Random(seed)
        env = NonStationaryEnv(rng)
        agent = agent_class(random.Random(seed + 6000))
        verifier = SimpleVerifier(env)

        adapted_phase_2 = None
        reactivated_phase_3 = None

        for round_id in range(TOTAL_ROUNDS):
            if round_id < PHASE_1_END:
                env.set_phase(1)
            elif round_id < PHASE_2_END:
                env.set_phase(2)
            else:
                env.set_phase(3)

            candidates = agent.propose()
            round_reward = 0.0

            for lever in candidates[:4]:
                is_causal, confidence = verifier.verify(lever)
                if is_causal and confidence > 0.5:
                    reward = env.reward_for_lever(lever)
                    agent.update(lever, reward)
                    round_reward = reward

                    if round_id >= PHASE_1_END and round_id < PHASE_2_END:
                        result.phase_2_reward += reward
                        if lever == env.phase_1_primary:
                            result.stale_actions_phase_2 += 1
                        if lever == env.phase_2_primary and adapted_phase_2 is None:
                            adapted_phase_2 = round_id - PHASE_1_END
                    elif round_id >= PHASE_2_END:
                        result.phase_3_reward += reward
                        if lever == env.phase_1_primary and reactivated_phase_3 is None:
                            reactivated_phase_3 = round_id - PHASE_2_END
                    else:
                        result.phase_1_reward += reward
                    break
                elif not is_causal:
                    continue
                else:
                    break

            best = 1.0
            result.total_regret += (best - round_reward)

        result.phase_2_adaptation.append(adapted_phase_2 if adapted_phase_2 is not None else PHASE_2_END - PHASE_1_END)
        result.phase_3_reactivation.append(reactivated_phase_3 if reactivated_phase_3 is not None else TOTAL_ROUNDS - PHASE_2_END)

    return result


def main() -> None:
    print("\n" + "=" * 75)
    print("  EXP-N: Non-Stationary Environments")
    print("  Can the agent adapt when the causal structure CHANGES?")
    print(f"  {len(SEEDS)} seeds × {TOTAL_ROUNDS} rounds")
    print(f"  Phase 1: rounds 0-{PHASE_1_END-1} | Phase 2: {PHASE_1_END}-{PHASE_2_END-1} | Phase 3: {PHASE_2_END}-{TOTAL_ROUNDS-1}")
    print("=" * 75)

    static_r = run_arm(StaticAgent, "N-static")
    window_r = run_arm(WindowedAgent, "N-windowed")
    change_r = run_arm(ChangePointAgent, "N-changepoint")
    bayes_r = run_arm(BayesianDecayAgent, "N-bayesian")

    arms = [static_r, window_r, change_r, bayes_r]
    names = ["Static", "Windowed", "ChangePt", "Bayesian"]

    print(f"\n  {'Metric':<45} {'Static':>8} {'Window':>8} {'ChgPt':>8} {'Bayes':>8}")
    print(f"  {'-'*45} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

    print(f"  {'Phase 1 reward (should be equal)':<45}", end="")
    for a in arms:
        print(f" {a.phase_1_reward:>8.1f}", end="")
    print()

    print(f"  {'Phase 2 reward (tests adaptation)':<45}", end="")
    for a in arms:
        print(f" {a.phase_2_reward:>8.1f}", end="")
    print()

    print(f"  {'Phase 3 reward (tests reactivation)':<45}", end="")
    for a in arms:
        print(f" {a.phase_3_reward:>8.1f}", end="")
    print()

    avg_adapt = [sum(a.phase_2_adaptation) / len(a.phase_2_adaptation) for a in arms]
    print(f"  {'Avg adaptation rounds (phase 2)':<45}", end="")
    for v in avg_adapt:
        print(f" {v:>8.1f}", end="")
    print()

    avg_react = [sum(a.phase_3_reactivation) / len(a.phase_3_reactivation) for a in arms]
    print(f"  {'Avg reactivation rounds (phase 3)':<45}", end="")
    for v in avg_react:
        print(f" {v:>8.1f}", end="")
    print()

    print(f"  {'Stale actions in phase 2':<45}", end="")
    for a in arms:
        print(f" {a.stale_actions_phase_2:>8}", end="")
    print()

    print(f"  {'Total regret':<45}", end="")
    for a in arms:
        print(f" {a.total_regret:>8.1f}", end="")
    print()

    # Verdicts
    print(f"\n  {'─'*75}")
    print("  VERDICTS:")

    best_adapt = min(range(4), key=lambda i: avg_adapt[i])
    print(f"  ✓ Fastest adaptation: {names[best_adapt]} ({avg_adapt[best_adapt]:.1f} rounds)")

    best_regret = min(range(4), key=lambda i: arms[i].total_regret)
    print(f"  ✓ Lowest total regret: {names[best_regret]} ({arms[best_regret].total_regret:.1f})")

    if static_r.stale_actions_phase_2 > window_r.stale_actions_phase_2:
        print(f"  ✓ Static agent STUCK: {static_r.stale_actions_phase_2} stale actions vs windowed {window_r.stale_actions_phase_2}")

    best_react = min(range(4), key=lambda i: avg_react[i])
    print(f"  ✓ Fastest reactivation: {names[best_react]} ({avg_react[best_react]:.1f} rounds)")

    print(f"\n  INTERPRETATION:")
    print(f"  The static agent accumulates evidence that becomes WRONG after a change.")
    print(f"  It takes much longer to 'unlearn' an old optimum than to learn a new one.")
    print(f"  Forgetting mechanisms (window / decay / changepoint) enable adaptation:")
    print(f"    - Window: simple, loses ALL old info (can't reactivate quickly)")
    print(f"    - Changepoint: detects shifts, resets selectively")
    print(f"    - Bayesian decay: smooth forgetting, maintains priors")
    print(f"\n  ARCHITECTURE INSIGHT:")
    print(f"  Rejection memory from EXP-J needs DECAY too. If the forbidden set changes")
    print(f"  (e.g., a lever gets re-permitted), static rejection memory would forever")
    print(f"  avoid it. The governance architecture must support:")
    print(f"    1. Permanent constraints (Layer 1/2: structural, never decay)")
    print(f"    2. Transient constraints (Layer 3: cognitive, should decay)")
    print(f"  This maps exactly to ADR-0050's layer separation.")


if __name__ == "__main__":
    main()
