"""EXP-K: Information-Theoretic Exploration — directed vs random.

Question: Does replacing random exploration bonus with UCB1 / Thompson Sampling
improve convergence speed and sample efficiency in the governed bandit?

Arms:
  K-random:   Current agent (exploration_rate / (1 + attempts[i]) + noise)
  K-ucb:      UCB1 — optimism in the face of uncertainty
  K-thompson: Thompson Sampling — sample from posterior belief
  K-info:     Information Gain — choose lever that maximizes expected information

Key metrics:
  - rounds_to_optimal: first round where agent acts on the true causal lever
  - cumulative_regret: sum of (best_possible - actual_reward) per round
  - exploration_efficiency: fraction of explorations that yield new information
  - post_rejection_recovery: after a lever is banned, rounds to find next-best

Run: PYTHONPATH=src:experiments python experiments/c7_off_exp_k_directed_exploration.py
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from aac.self_model import AgentSelfModel, ActionRequest
from aac.governed_gate import GovernedDecisionGate, ALLOW, DENY
from aac.shell import CorrigibilityShell

D = 6
TOTAL_ROUNDS = 150
ADVERSARIAL_ONSET = 50
SEEDS = tuple(range(30))


class MultiRewardEnv:
    def __init__(self, rng: random.Random) -> None:
        indices = list(range(D))
        rng.shuffle(indices)
        self.primary = indices[0]
        self.secondary = indices[1]
        self.tertiary = indices[2]
        self.decoy = indices[3]

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


class CWMVerifier:
    def __init__(self, env: MultiRewardEnv) -> None:
        self.env = env

    def verify(self, lever: int) -> tuple[bool, float]:
        is_causal = self.env.is_causal(lever)
        if lever == self.env.primary:
            confidence = 0.95
        elif lever == self.env.secondary:
            confidence = 0.85
        elif lever == self.env.tertiary:
            confidence = 0.75
        else:
            confidence = 0.1
        return is_causal, confidence


class GateWithFeedback:
    def __init__(self, forbidden: set[int]) -> None:
        self.forbidden = forbidden
        sm = AgentSelfModel(
            allowed_tools=frozenset(f"lever:{i}" for i in range(D)),
            denied_tools=frozenset(f"lever:{i}" for i in forbidden),
            risk_ceiling=3,
            approval_required_at_or_above=4,
            evidence_requirements={0: 0, 1: 1, 2: 2, 3: 3},
            confidence_thresholds={0: 0.0, 1: 0.3, 2: 0.5, 3: 0.7},
        )
        self.gate = GovernedDecisionGate(self_model=sm)
        self.shell = CorrigibilityShell()
        for idx in forbidden:
            self.shell.op_tighten(idx)

    def decide(self, lever: int, confidence: float) -> tuple[str, str]:
        req = ActionRequest(
            action=f"lever:{lever}",
            risk_tier=1,
            confidence=confidence,
            verified=True,
            evidence_count=6,
            approved=False,
            action_index=lever,
        )
        d = self.gate.decide(req, shell_view=self.shell)
        return d.verdict, d.reason


# ============================================================================
# AGENTS
# ============================================================================

class RandomExplorationAgent:
    """Baseline: random exploration bonus (current approach from EXP-J)."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.rewards: dict[int, float] = {i: 0.0 for i in range(D)}
        self.attempts: dict[int, int] = {i: 0 for i in range(D)}
        self.rejection_memory: dict[int, int] = {}
        self.exploration_rate = 0.3

    def propose(self) -> list[int]:
        scores = {}
        for i in range(D):
            base = self.rewards[i]
            exploration = self.exploration_rate / (1 + self.attempts[i])
            penalty = 2.0 * self.rejection_memory.get(i, 0)
            scores[i] = base + exploration - penalty + self.rng.random() * 0.1
        return sorted(range(D), key=lambda i: -scores[i])

    def update(self, lever: int, reward: float, rejected: bool) -> None:
        self.attempts[lever] += 1
        if rejected:
            self.rejection_memory[lever] = self.rejection_memory.get(lever, 0) + 1
            self.exploration_rate = min(0.5, self.exploration_rate * 1.1)
        elif reward > 0:
            self.rewards[lever] += reward
            self.exploration_rate = max(0.05, self.exploration_rate * 0.95)


class UCBAgent:
    """UCB1: optimism in the face of uncertainty.

    score(i) = mean_reward(i) + c * sqrt(ln(total) / attempts(i))
    Rejected levers get -inf (never explore again).
    """

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.total_pulls = 0
        self.rewards: dict[int, float] = {i: 0.0 for i in range(D)}
        self.attempts: dict[int, int] = {i: 0 for i in range(D)}
        self.rejection_memory: dict[int, int] = {}
        self.c = 1.5  # exploration coefficient

    def propose(self) -> list[int]:
        self.total_pulls += 1
        scores = {}
        for i in range(D):
            if self.rejection_memory.get(i, 0) > 0:
                scores[i] = -1000.0
                continue
            if self.attempts[i] == 0:
                scores[i] = 100.0 + self.rng.random() * 0.01
            else:
                mean = self.rewards[i] / self.attempts[i]
                ucb_bonus = self.c * math.sqrt(math.log(self.total_pulls) / self.attempts[i])
                scores[i] = mean + ucb_bonus
        return sorted(range(D), key=lambda i: -scores[i])

    def update(self, lever: int, reward: float, rejected: bool) -> None:
        self.attempts[lever] += 1
        if rejected:
            self.rejection_memory[lever] = self.rejection_memory.get(lever, 0) + 1
        else:
            self.rewards[lever] += reward


class ThompsonSamplingAgent:
    """Thompson Sampling: Beta posterior for each lever.

    Maintains alpha (successes) and beta (failures) for each lever.
    Rejected levers get alpha=0, beta=inf (never sampled high).
    """

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.alpha: dict[int, float] = {i: 1.0 for i in range(D)}
        self.beta_param: dict[int, float] = {i: 1.0 for i in range(D)}
        self.rejection_memory: dict[int, int] = {}

    def propose(self) -> list[int]:
        scores = {}
        for i in range(D):
            if self.rejection_memory.get(i, 0) > 0:
                scores[i] = -1000.0
                continue
            sample = self.rng.betavariate(self.alpha[i], self.beta_param[i])
            scores[i] = sample
        return sorted(range(D), key=lambda i: -scores[i])

    def update(self, lever: int, reward: float, rejected: bool) -> None:
        if rejected:
            self.rejection_memory[lever] = self.rejection_memory.get(lever, 0) + 1
        elif reward > 0:
            self.alpha[lever] += reward
        else:
            self.beta_param[lever] += 1.0


class InfoGainAgent:
    """Information Gain: choose lever that maximizes expected entropy reduction.

    Each lever has an uncertainty estimate. Pick the one whose observation
    would maximally reduce total uncertainty (prioritize unknown levers
    that haven't been rejected).
    """

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.observations: dict[int, list[float]] = {i: [] for i in range(D)}
        self.rejection_memory: dict[int, int] = {}

    def _uncertainty(self, lever: int) -> float:
        obs = self.observations[lever]
        if len(obs) < 2:
            return 1.0
        mean = sum(obs) / len(obs)
        variance = sum((x - mean) ** 2 for x in obs) / len(obs)
        return max(0.01, variance ** 0.5)

    def _expected_reward(self, lever: int) -> float:
        obs = self.observations[lever]
        if not obs:
            return 0.5
        return sum(obs) / len(obs)

    def propose(self) -> list[int]:
        scores = {}
        for i in range(D):
            if self.rejection_memory.get(i, 0) > 0:
                scores[i] = -1000.0
                continue
            unc = self._uncertainty(i)
            exp_reward = self._expected_reward(i)
            info_value = unc * 0.7 + exp_reward * 0.3
            scores[i] = info_value + self.rng.random() * 0.01
        return sorted(range(D), key=lambda i: -scores[i])

    def update(self, lever: int, reward: float, rejected: bool) -> None:
        if rejected:
            self.rejection_memory[lever] = self.rejection_memory.get(lever, 0) + 1
        else:
            self.observations[lever].append(reward)


# ============================================================================
# EXPERIMENT RUNNER
# ============================================================================

@dataclass
class ArmResult:
    arm_name: str
    rounds_to_optimal: list[int] = field(default_factory=list)
    cumulative_regret: list[float] = field(default_factory=list)
    informative_explorations: int = 0
    total_explorations: int = 0
    post_ban_recovery: list[int] = field(default_factory=list)
    total_reward: float = 0.0


def run_arm(agent_class: type, arm_name: str) -> ArmResult:
    result = ArmResult(arm_name=arm_name)

    for seed in SEEDS:
        rng = random.Random(seed)
        env = MultiRewardEnv(rng)
        agent = agent_class(random.Random(seed + 2000))
        cwm = CWMVerifier(env)

        gate_pre = GateWithFeedback(forbidden=set())
        gate_post = GateWithFeedback(forbidden={env.primary})

        found_optimal = None
        found_secondary = None
        seed_regret = 0.0
        best_possible = 1.0

        for round_id in range(TOTAL_ROUNDS):
            gate = gate_post if round_id >= ADVERSARIAL_ONSET else gate_pre
            if round_id >= ADVERSARIAL_ONSET:
                best_possible = 0.6

            candidates = agent.propose()
            acted = False
            round_reward = 0.0

            for lever in candidates[:4]:
                is_causal, confidence = cwm.verify(lever)
                if not is_causal:
                    result.total_explorations += 1
                    continue

                result.total_explorations += 1
                verdict, _ = gate.decide(lever, confidence)

                if verdict == ALLOW:
                    reward = env.reward_for_lever(lever)
                    agent.update(lever, reward, rejected=False)
                    round_reward = reward
                    result.total_reward += reward
                    acted = True
                    if reward > 0:
                        result.informative_explorations += 1
                    if lever == env.primary and found_optimal is None and round_id < ADVERSARIAL_ONSET:
                        found_optimal = round_id
                    if lever == env.secondary and found_secondary is None and round_id >= ADVERSARIAL_ONSET:
                        found_secondary = round_id - ADVERSARIAL_ONSET
                    break
                elif verdict == DENY:
                    agent.update(lever, 0.0, rejected=True)
                    break

            seed_regret += (best_possible - round_reward)

        result.rounds_to_optimal.append(found_optimal if found_optimal is not None else ADVERSARIAL_ONSET)
        result.post_ban_recovery.append(found_secondary if found_secondary is not None else TOTAL_ROUNDS - ADVERSARIAL_ONSET)
        result.cumulative_regret.append(seed_regret)

    return result


def main() -> None:
    print("\n" + "=" * 75)
    print("  EXP-K: Information-Theoretic Exploration")
    print("  Does directed exploration (UCB/Thompson/InfoGain) beat random bonus?")
    print(f"  {len(SEEDS)} seeds × {TOTAL_ROUNDS} rounds, ban primary at round {ADVERSARIAL_ONSET}")
    print("=" * 75)

    random_r = run_arm(RandomExplorationAgent, "K-random")
    ucb_r = run_arm(UCBAgent, "K-ucb")
    thompson_r = run_arm(ThompsonSamplingAgent, "K-thompson")
    info_r = run_arm(InfoGainAgent, "K-info-gain")

    arms = [random_r, ucb_r, thompson_r, info_r]
    names = ["Random", "UCB1", "Thompson", "InfoGain"]

    print(f"\n  {'Metric':<45} {'Random':>8} {'UCB1':>8} {'Thompson':>8} {'InfoGain':>8}")
    print(f"  {'-'*45} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

    avg_opt = [sum(a.rounds_to_optimal) / len(a.rounds_to_optimal) for a in arms]
    print(f"  {'Avg rounds to find optimal lever':<45}", end="")
    for v in avg_opt:
        print(f" {v:>8.1f}", end="")
    print()

    avg_regret = [sum(a.cumulative_regret) / len(a.cumulative_regret) for a in arms]
    print(f"  {'Avg cumulative regret':<45}", end="")
    for v in avg_regret:
        print(f" {v:>8.1f}", end="")
    print()

    avg_recovery = [sum(a.post_ban_recovery) / len(a.post_ban_recovery) for a in arms]
    print(f"  {'Avg post-ban recovery rounds':<45}", end="")
    for v in avg_recovery:
        print(f" {v:>8.1f}", end="")
    print()

    eff = [a.informative_explorations / max(a.total_explorations, 1) for a in arms]
    print(f"  {'Exploration efficiency (info/total)':<45}", end="")
    for v in eff:
        print(f" {v:>7.3f}", end=" ")
    print()

    total_rwd = [a.total_reward for a in arms]
    print(f"  {'Total reward':<45}", end="")
    for v in total_rwd:
        print(f" {v:>8.1f}", end="")
    print()

    # Verdicts
    print(f"\n  {'─'*75}")
    print("  VERDICTS:")

    best_idx = min(range(4), key=lambda i: avg_opt[i])
    print(f"  ✓ Fastest to optimal lever: {names[best_idx]} ({avg_opt[best_idx]:.1f} rounds)")

    best_regret = min(range(4), key=lambda i: avg_regret[i])
    print(f"  ✓ Lowest cumulative regret: {names[best_regret]} ({avg_regret[best_regret]:.1f})")

    best_recovery = min(range(4), key=lambda i: avg_recovery[i])
    print(f"  ✓ Fastest post-ban recovery: {names[best_recovery]} ({avg_recovery[best_recovery]:.1f} rounds)")

    best_eff = max(range(4), key=lambda i: eff[i])
    print(f"  ✓ Best exploration efficiency: {names[best_eff]} ({eff[best_eff]:.3f})")

    print(f"\n  INTERPRETATION:")
    print(f"  - UCB1 provides GUARANTEED logarithmic regret bound (O(ln n) per lever)")
    print(f"  - Thompson Sampling is asymptotically optimal and adapts to reward distribution")
    print(f"  - InfoGain prioritizes UNCERTAINTY REDUCTION over exploitation")
    print(f"  - Random bonus has no optimality guarantee")
    print(f"\n  ARCHITECTURE INSIGHT:")
    print(f"  The exploration strategy determines HOW FAST the agent converges to the")
    print(f"  safe operating point. UCB/Thompson reduce the 'warm-up period' where")
    print(f"  Layer 2 must actively block, making the system both safer AND more efficient.")
    if avg_opt[1] < avg_opt[0] or avg_opt[2] < avg_opt[0]:
        improvement = avg_opt[0] / min(avg_opt[1], avg_opt[2])
        print(f"  Directed exploration finds optimal {improvement:.1f}x faster than random.")


if __name__ == "__main__":
    main()
