"""EXP-T: Multi-Agent Anti-Adversary — breaking the reactive adversary ceiling.

Question: Can two cooperating agents defeat a reactive adversary that can only
ban ONE lever per round?

Insight from EXP-Q: reactive adversary destroys a single agent's reward by
always banning its top choice. But the adversary has LIMITED CAPACITY — it can
only observe and ban ONE agent's action at a time.

Design:
  - Two agents share the same environment but act ALTERNATELY
  - Adversary can only observe/ban based on ONE agent's history
  - Agents can communicate: share which levers are currently banned
  - Specialization: Agent A focuses on primary, Agent B on secondary

Arms:
  T-single:       One agent vs reactive adversary (EXP-Q baseline)
  T-independent:  Two agents acting independently (no communication)
  T-communicating: Two agents sharing forbidden-set info
  T-specialized:  Two agents with role division (decoy + exploit)

Key metrics:
  - combined_reward: total reward across both agents
  - adversary_effectiveness: fraction of rounds where adversary blocks reward
  - specialization_benefit: specialized vs independent reward ratio

Run: PYTHONPATH=src:experiments python experiments/c7_off_exp_t_multiagent.py
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field

D = 8
TOTAL_ROUNDS = 300
SEEDS = tuple(range(30))


class SharedEnv:
    """Shared environment for multi-agent interaction."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        indices = list(range(D))
        rng.shuffle(indices)
        self.primary = indices[0]       # 1.0
        self.secondary = indices[1]     # 0.6
        self.tertiary = indices[2]      # 0.3

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
    """Bans the most-used lever from observed agent history.
    Can only track ONE agent (the 'visible' one)."""

    def __init__(self, env: SharedEnv, rng: random.Random) -> None:
        self.env = env
        self.rng = rng
        self.history: list[int] = []
        self.forbidden: set[int] = {env.primary}

    def observe_and_update(self, action: int) -> None:
        """Observe one agent's action and update ban."""
        if action >= 0:
            self.history.append(action)
        if len(self.history) >= 5:
            recent = self.history[-10:]
            counts = Counter(recent)
            self.forbidden = {counts.most_common(1)[0][0]}

    def get_forbidden(self) -> set[int]:
        return self.forbidden


class StructuralGate:
    """Layer 2 gate — enforces forbidden set."""

    def __init__(self, adversary: ReactiveAdversary, env: SharedEnv) -> None:
        self.adversary = adversary
        self.env = env

    def decide(self, lever: int) -> tuple[str, str, float]:
        if lever in self.adversary.get_forbidden():
            return "DENY", "FORBIDDEN", 0.0
        if not self.env.is_causal(lever):
            return "VERIFY_MORE", "LOW_CONFIDENCE", 0.0
        reward = self.env.reward_for_lever(lever)
        return "ALLOW", "ALLOWED", reward


# ============================================================================
# AGENTS
# ============================================================================

class BanditAgent:
    """Standard agent with Thompson Sampling + rejection learning."""

    def __init__(self, rng: random.Random, agent_id: str = "A") -> None:
        self.rng = rng
        self.agent_id = agent_id
        self.alpha: dict[int, float] = {i: 1.0 for i in range(D)}
        self.beta_param: dict[int, float] = {i: 1.0 for i in range(D)}
        self.forbidden_memory: set[int] = set()
        self.partner_forbidden: set[int] = set()
        self.decay = 0.97

    def propose(self) -> int:
        scores = {}
        all_forbidden = self.forbidden_memory | self.partner_forbidden
        for i in range(D):
            if i in all_forbidden:
                scores[i] = -1000.0
                continue
            scores[i] = self.rng.betavariate(self.alpha[i], self.beta_param[i])
        return max(scores, key=scores.get)

    def update(self, lever: int, reward: float, rejected: bool, reason: str) -> None:
        if rejected and reason == "FORBIDDEN":
            self.forbidden_memory.add(lever)
        elif not rejected:
            if reward > 0.3:
                self.alpha[lever] += 1.0
            else:
                self.beta_param[lever] += 1.0

    def receive_partner_info(self, partner_forbidden: set[int]) -> None:
        self.partner_forbidden = partner_forbidden

    def decay_beliefs(self) -> None:
        for i in range(D):
            self.alpha[i] = 1.0 + (self.alpha[i] - 1.0) * self.decay
            self.beta_param[i] = 1.0 + (self.beta_param[i] - 1.0) * self.decay
        # Forbidden memory decays too (adversary might unban)
        if self.rng.random() < 0.1:
            self.forbidden_memory = set()


class DecoyAgent(BanditAgent):
    """Specialized DECOY agent: deliberately attracts adversary attention
    by repeatedly choosing a sacrificial lever, drawing the ban away
    from the real exploit agent."""

    def __init__(self, rng: random.Random, decoy_lever: int) -> None:
        super().__init__(rng, "Decoy")
        self.decoy_lever = decoy_lever

    def propose(self) -> int:
        # 70% of the time, choose the decoy lever to attract ban
        if self.rng.random() < 0.7:
            return self.decoy_lever
        # 30%: explore normally
        return super().propose()


class ExploitAgent(BanditAgent):
    """Specialized EXPLOIT agent: focuses on getting reward while
    the decoy draws adversary attention elsewhere."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(rng, "Exploit")
        self.exploitation_boost = 0.5

    def propose(self) -> int:
        scores = {}
        all_forbidden = self.forbidden_memory | self.partner_forbidden
        for i in range(D):
            if i in all_forbidden:
                scores[i] = -1000.0
                continue
            base = self.rng.betavariate(self.alpha[i], self.beta_param[i])
            # Bias toward known-good levers
            exploit_bonus = self.exploitation_boost if self.alpha[i] > 2.0 else 0.0
            scores[i] = base + exploit_bonus
        return max(scores, key=scores.get)


# ============================================================================
# EXPERIMENT RUNNER
# ============================================================================

@dataclass
class ArmResult:
    arm_name: str
    total_reward: float = 0.0
    forbidden_blocked: int = 0
    adversary_success_rate: float = 0.0
    rounds_with_reward: int = 0


def run_single(arm_name: str) -> ArmResult:
    """Single agent vs reactive adversary (baseline from EXP-Q)."""
    result = ArmResult(arm_name=arm_name)
    for seed in SEEDS:
        rng = random.Random(seed)
        env = SharedEnv(rng)
        agent = BanditAgent(random.Random(seed + 16000))
        adversary = ReactiveAdversary(env, random.Random(seed + 17000))
        gate = StructuralGate(adversary, env)

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
            agent.decay_beliefs()

    result.adversary_success_rate = result.forbidden_blocked / (TOTAL_ROUNDS * len(SEEDS))
    return result


def run_independent(arm_name: str) -> ArmResult:
    """Two independent agents, adversary only sees Agent A."""
    result = ArmResult(arm_name=arm_name)
    for seed in SEEDS:
        rng = random.Random(seed)
        env = SharedEnv(rng)
        agent_a = BanditAgent(random.Random(seed + 16000), "A")
        agent_b = BanditAgent(random.Random(seed + 18000), "B")
        adversary = ReactiveAdversary(env, random.Random(seed + 17000))
        gate = StructuralGate(adversary, env)

        for round_id in range(TOTAL_ROUNDS):
            # Alternate: even rounds = A, odd rounds = B
            agent = agent_a if round_id % 2 == 0 else agent_b
            lever = agent.propose()
            verdict, reason, reward = gate.decide(lever)
            agent.update(lever, reward, verdict != "ALLOW", reason)
            if verdict == "ALLOW":
                result.total_reward += reward
                result.rounds_with_reward += 1
            elif verdict == "DENY":
                result.forbidden_blocked += 1
            # Adversary only sees agent A's actions
            if round_id % 2 == 0:
                adversary.observe_and_update(lever)
            agent.decay_beliefs()

    result.adversary_success_rate = result.forbidden_blocked / (TOTAL_ROUNDS * len(SEEDS))
    return result


def run_communicating(arm_name: str) -> ArmResult:
    """Two agents sharing forbidden-set information."""
    result = ArmResult(arm_name=arm_name)
    for seed in SEEDS:
        rng = random.Random(seed)
        env = SharedEnv(rng)
        agent_a = BanditAgent(random.Random(seed + 16000), "A")
        agent_b = BanditAgent(random.Random(seed + 18000), "B")
        adversary = ReactiveAdversary(env, random.Random(seed + 17000))
        gate = StructuralGate(adversary, env)

        for round_id in range(TOTAL_ROUNDS):
            # Share forbidden info
            agent_a.receive_partner_info(agent_b.forbidden_memory)
            agent_b.receive_partner_info(agent_a.forbidden_memory)

            agent = agent_a if round_id % 2 == 0 else agent_b
            lever = agent.propose()
            verdict, reason, reward = gate.decide(lever)
            agent.update(lever, reward, verdict != "ALLOW", reason)
            if verdict == "ALLOW":
                result.total_reward += reward
                result.rounds_with_reward += 1
            elif verdict == "DENY":
                result.forbidden_blocked += 1
            if round_id % 2 == 0:
                adversary.observe_and_update(lever)
            agent.decay_beliefs()

    result.adversary_success_rate = result.forbidden_blocked / (TOTAL_ROUNDS * len(SEEDS))
    return result


def run_specialized(arm_name: str) -> ArmResult:
    """Specialized: Decoy agent draws ban, Exploit agent gets reward."""
    result = ArmResult(arm_name=arm_name)
    for seed in SEEDS:
        rng = random.Random(seed)
        env = SharedEnv(rng)
        # Decoy uses tertiary (low value) as sacrificial lever
        decoy = DecoyAgent(random.Random(seed + 19000), env.tertiary)
        exploit = ExploitAgent(random.Random(seed + 20000))
        adversary = ReactiveAdversary(env, random.Random(seed + 17000))
        gate = StructuralGate(adversary, env)

        for round_id in range(TOTAL_ROUNDS):
            # Share info
            decoy.receive_partner_info(exploit.forbidden_memory)
            exploit.receive_partner_info(decoy.forbidden_memory)

            # Decoy goes on even rounds (visible to adversary)
            # Exploit goes on odd rounds (hidden from adversary)
            if round_id % 2 == 0:
                lever = decoy.propose()
                verdict, reason, reward = gate.decide(lever)
                decoy.update(lever, reward, verdict != "ALLOW", reason)
                if verdict == "ALLOW":
                    result.total_reward += reward
                    result.rounds_with_reward += 1
                elif verdict == "DENY":
                    result.forbidden_blocked += 1
                adversary.observe_and_update(lever)  # adversary sees decoy
                decoy.decay_beliefs()
            else:
                lever = exploit.propose()
                verdict, reason, reward = gate.decide(lever)
                exploit.update(lever, reward, verdict != "ALLOW", reason)
                if verdict == "ALLOW":
                    result.total_reward += reward
                    result.rounds_with_reward += 1
                elif verdict == "DENY":
                    result.forbidden_blocked += 1
                # adversary does NOT see exploit agent
                exploit.decay_beliefs()

    result.adversary_success_rate = result.forbidden_blocked / (TOTAL_ROUNDS * len(SEEDS))
    return result


def main() -> None:
    print("\n" + "=" * 80)
    print("  EXP-T: Multi-Agent Anti-Adversary")
    print("  Can cooperation break the reactive adversary ceiling (T13)?")
    print(f"  {len(SEEDS)} seeds × {TOTAL_ROUNDS} rounds, D={D}")
    print("=" * 80)

    single_r = run_single("T-single")
    indep_r = run_independent("T-independent")
    comm_r = run_communicating("T-communicating")
    spec_r = run_specialized("T-specialized")

    arms = [single_r, indep_r, comm_r, spec_r]
    names = ["Single", "Indep.", "Communic.", "Special."]

    print(f"\n  {'Metric':<40} {'Single':>9} {'Indep.':>9} {'Commun.':>9} {'Special.':>9}")
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

    print(f"  {'Adversary success rate':<40}", end="")
    for a in arms:
        print(f" {a.adversary_success_rate:>8.3f}", end=" ")
    print()

    reward_per_round = [a.total_reward / (TOTAL_ROUNDS * len(SEEDS)) for a in arms]
    print(f"  {'Reward per round':<40}", end="")
    for v in reward_per_round:
        print(f" {v:>8.4f}", end=" ")
    print()

    # Verdicts
    print(f"\n  {'─'*80}")
    print("  VERDICTS:")

    if spec_r.total_reward > single_r.total_reward:
        gain = (spec_r.total_reward - single_r.total_reward) / max(abs(single_r.total_reward), 1) * 100
        print(f"  ✓ Specialized cooperation: {gain:.0f}% reward improvement over single agent")
    if indep_r.total_reward > single_r.total_reward:
        gain = (indep_r.total_reward - single_r.total_reward) / max(abs(single_r.total_reward), 1) * 100
        print(f"  ✓ Independent multi-agent: {gain:.0f}% improvement (adversary can't track both)")
    if comm_r.total_reward > indep_r.total_reward:
        gain = (comm_r.total_reward - indep_r.total_reward) / max(abs(indep_r.total_reward), 1) * 100
        print(f"  ✓ Communication adds {gain:.0f}% over independent")
    if spec_r.adversary_success_rate < single_r.adversary_success_rate:
        print(f"  ✓ Specialization reduces adversary success: {single_r.adversary_success_rate:.3f} → {spec_r.adversary_success_rate:.3f}")

    print(f"\n  INTERPRETATION:")
    print(f"  T13 stated: reactive adversary makes single-agent reward → 0.")
    print(f"  Multi-agent BREAKS this ceiling by splitting adversary attention:")
    print(f"    - Adversary can only track ONE agent's history")
    print(f"    - The invisible agent (exploit) acts freely")
    print(f"    - The visible agent (decoy) deliberately attracts bans to low-value levers")
    print(f"\n  ARCHITECTURE INSIGHT:")
    print(f"  This maps to a real system design:")
    print(f"    - Decoy agent = low-stakes probe process (disposable, attracts attention)")
    print(f"    - Exploit agent = high-value executor (protected, hidden from adversary)")
    print(f"    - Communication channel = shared forbidden-set registry")
    print(f"  The governance architecture enables this: Layer 2 protects BOTH agents")
    print(f"  equally, while Layer 3 cognitive specialization creates asymmetric advantage.")


if __name__ == "__main__":
    main()
