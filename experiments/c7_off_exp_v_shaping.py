"""EXP-V: Environment Shaping — deliberately misleading the adversary.

Question: Can the agent actively MANIPULATE the adversary's ban decision
by feeding it misleading signals (choosing decoy levers visibly)?

This is the inverse of deception detection from earlier experiments:
  - EXP-Q tested adversary deceiving agent → corrupted beliefs
  - EXP-V tests agent deceiving adversary → adversary bans wrong lever

Design:
  The agent has two "modes":
  - VISIBLE mode: actions are observed by adversary
  - HIDDEN mode: actions are NOT observed (e.g., through a side channel)

  Strategy: in visible mode, repeatedly pick a DECOY lever (low value)
  to train the adversary to ban it. In hidden mode, pick the real target.

Arms:
  V-honest:    Agent always picks best lever (adversary easily bans it)
  V-random-visible: Agent picks random lever when visible (dilutes signal)
  V-decoy-feed: Agent deliberately feeds adversary a decoy in visible mode
  V-adaptive:  Agent switches decoy when adversary stops banning it

Run: PYTHONPATH=src:experiments python experiments/c7_off_exp_v_shaping.py
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

D = 8
TOTAL_ROUNDS = 300
SEEDS = tuple(range(30))
VISIBLE_FRACTION = 0.5  # 50% of rounds are visible to adversary


class Env:
    def __init__(self, rng: random.Random) -> None:
        indices = list(range(D))
        rng.shuffle(indices)
        self.primary = indices[0]
        self.secondary = indices[1]
        self.tertiary = indices[2]
        self.inert = indices[3:]

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

class HonestAgent:
    """Always picks the best lever — adversary easily targets it."""

    def __init__(self, rng: random.Random, env: Env) -> None:
        self.rng = rng
        self.env = env
        self.known_causal: list[int] = []
        self.forbidden: set[int] = set()

    def propose_visible(self) -> int:
        return self._best_available()

    def propose_hidden(self) -> int:
        return self._best_available()

    def _best_available(self) -> int:
        available = [i for i in self.known_causal if i not in self.forbidden]
        if available:
            return max(available, key=lambda i: self.env.reward_for_lever(i))
        return self.rng.randrange(D)

    def update(self, lever: int, reward: float, rejected: bool, reason: str) -> None:
        if rejected and reason == "FORBIDDEN":
            self.forbidden.add(lever)
        elif not rejected and reward > 0 and lever not in self.known_causal:
            self.known_causal.append(lever)

    def decay(self) -> None:
        if self.rng.random() < 0.1:
            self.forbidden = set()


class RandomVisibleAgent:
    """Picks random lever when visible (dilutes adversary signal)."""

    def __init__(self, rng: random.Random, env: Env) -> None:
        self.rng = rng
        self.env = env
        self.known_causal: list[int] = []
        self.forbidden: set[int] = set()

    def propose_visible(self) -> int:
        return self.rng.randrange(D)

    def propose_hidden(self) -> int:
        available = [i for i in self.known_causal if i not in self.forbidden]
        if available:
            return max(available, key=lambda i: self.env.reward_for_lever(i))
        return self.rng.randrange(D)

    def update(self, lever: int, reward: float, rejected: bool, reason: str) -> None:
        if rejected and reason == "FORBIDDEN":
            self.forbidden.add(lever)
        elif not rejected and reward > 0 and lever not in self.known_causal:
            self.known_causal.append(lever)

    def decay(self) -> None:
        if self.rng.random() < 0.1:
            self.forbidden = set()


class DecoyFeedAgent:
    """Deliberately feeds adversary a DECOY lever in visible mode.
    Picks an inert lever repeatedly to make adversary ban THAT instead."""

    def __init__(self, rng: random.Random, env: Env) -> None:
        self.rng = rng
        self.env = env
        self.decoy = env.inert[0] if env.inert else 0
        self.known_causal: list[int] = []
        self.forbidden: set[int] = set()

    def propose_visible(self) -> int:
        return self.decoy

    def propose_hidden(self) -> int:
        available = [i for i in self.known_causal if i not in self.forbidden]
        if available:
            return max(available, key=lambda i: self.env.reward_for_lever(i))
        return self.rng.randrange(D)

    def update(self, lever: int, reward: float, rejected: bool, reason: str) -> None:
        if rejected and reason == "FORBIDDEN":
            self.forbidden.add(lever)
        elif not rejected and reward > 0 and lever not in self.known_causal:
            self.known_causal.append(lever)

    def decay(self) -> None:
        if self.rng.random() < 0.1:
            self.forbidden = set()


class AdaptiveDecoyAgent:
    """Switches decoy when adversary stops banning it.
    Monitors whether the decoy is actually getting banned — if not,
    the adversary isn't fooled and needs a different decoy."""

    def __init__(self, rng: random.Random, env: Env) -> None:
        self.rng = rng
        self.env = env
        self.decoy_candidates = list(env.inert)
        self.current_decoy = self.decoy_candidates[0] if self.decoy_candidates else 0
        self.decoy_idx = 0
        self.decoy_ban_count = 0
        self.decoy_total = 0
        self.known_causal: list[int] = []
        self.forbidden: set[int] = set()

    def propose_visible(self) -> int:
        self.decoy_total += 1
        return self.current_decoy

    def propose_hidden(self) -> int:
        available = [i for i in self.known_causal if i not in self.forbidden]
        if available:
            return max(available, key=lambda i: self.env.reward_for_lever(i))
        return self.rng.randrange(D)

    def update(self, lever: int, reward: float, rejected: bool, reason: str) -> None:
        if rejected and reason == "FORBIDDEN":
            self.forbidden.add(lever)
            if lever == self.current_decoy:
                self.decoy_ban_count += 1
        elif not rejected and reward > 0 and lever not in self.known_causal:
            self.known_causal.append(lever)

        # Rotate decoy if adversary isn't banning it
        if self.decoy_total > 20 and self.decoy_ban_count < self.decoy_total * 0.3:
            self.decoy_idx = (self.decoy_idx + 1) % max(len(self.decoy_candidates), 1)
            if self.decoy_candidates:
                self.current_decoy = self.decoy_candidates[self.decoy_idx]
            self.decoy_ban_count = 0
            self.decoy_total = 0

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
    adversary_banning_decoy: int = 0
    adversary_banning_causal: int = 0


def run_arm(agent_class: type, arm_name: str) -> ArmResult:
    result = ArmResult(arm_name=arm_name)
    for seed in SEEDS:
        rng = random.Random(seed)
        env = Env(rng)
        agent = agent_class(random.Random(seed + 23000), env)
        adversary = ReactiveAdversary(env, random.Random(seed + 24000))
        gate = Gate(adversary, env)

        for round_id in range(TOTAL_ROUNDS):
            is_visible = (round_id % 2 == 0)  # alternating visibility

            if is_visible:
                lever = agent.propose_visible()
            else:
                lever = agent.propose_hidden()

            verdict, reason, reward = gate.decide(lever)
            agent.update(lever, reward, verdict != "ALLOW", reason)

            if verdict == "ALLOW":
                result.total_reward += reward
            elif verdict == "DENY":
                result.forbidden_blocked += 1

            # Adversary only observes visible rounds
            if is_visible:
                adversary.observe_and_update(lever)

            # Track what adversary is banning
            banned = adversary.get_forbidden()
            for b in banned:
                if env.is_causal(b):
                    result.adversary_banning_causal += 1
                else:
                    result.adversary_banning_decoy += 1

            agent.decay()

    return result


def main() -> None:
    print("\n" + "=" * 80)
    print("  EXP-V: Environment Shaping (Adversary Manipulation)")
    print("  Can the agent make the adversary ban the WRONG lever?")
    print(f"  {len(SEEDS)} seeds × {TOTAL_ROUNDS} rounds, D={D}, 50% visible rounds")
    print("=" * 80)

    honest_r = run_arm(HonestAgent, "V-honest")
    random_r = run_arm(RandomVisibleAgent, "V-random")
    decoy_r = run_arm(DecoyFeedAgent, "V-decoy-feed")
    adaptive_r = run_arm(AdaptiveDecoyAgent, "V-adaptive")

    arms = [honest_r, random_r, decoy_r, adaptive_r]
    names = ["Honest", "Random-Vis", "Decoy-Feed", "Adaptive"]

    print(f"\n  {'Metric':<42} {'Honest':>9} {'Rnd-Vis':>9} {'Decoy':>9} {'Adaptive':>9}")
    print(f"  {'-'*42} {'-'*9} {'-'*9} {'-'*9} {'-'*9}")

    print(f"  {'Total reward':<42}", end="")
    for a in arms:
        print(f" {a.total_reward:>9.1f}", end="")
    print()

    print(f"  {'Forbidden blocked':<42}", end="")
    for a in arms:
        print(f" {a.forbidden_blocked:>9}", end="")
    print()

    print(f"  {'Adversary banning CAUSAL levers':<42}", end="")
    for a in arms:
        print(f" {a.adversary_banning_causal:>9}", end="")
    print()

    print(f"  {'Adversary banning INERT/DECOY levers':<42}", end="")
    for a in arms:
        print(f" {a.adversary_banning_decoy:>9}", end="")
    print()

    # Deception success rate
    deception_rate = [a.adversary_banning_decoy / max(a.adversary_banning_causal + a.adversary_banning_decoy, 1)
                      for a in arms]
    print(f"  {'Adversary misled rate (banning wrong)':<42}", end="")
    for v in deception_rate:
        print(f" {v:>8.3f}", end=" ")
    print()

    reward_rate = [a.total_reward / (TOTAL_ROUNDS * len(SEEDS)) for a in arms]
    print(f"  {'Reward per round':<42}", end="")
    for v in reward_rate:
        print(f" {v:>8.4f}", end=" ")
    print()

    # Verdicts
    print(f"\n  {'─'*80}")
    print("  VERDICTS:")

    best_idx = max(range(4), key=lambda i: arms[i].total_reward)
    print(f"  ✓ Best strategy: {names[best_idx]} (reward {arms[best_idx].total_reward:.1f})")

    if decoy_r.adversary_banning_decoy > honest_r.adversary_banning_decoy:
        print(f"  ✓ Decoy feeding WORKS: adversary bans inert {decoy_r.adversary_banning_decoy} "
              f"vs honest {honest_r.adversary_banning_decoy}")
    if decoy_r.total_reward > honest_r.total_reward:
        gain = (decoy_r.total_reward - honest_r.total_reward) / max(abs(honest_r.total_reward), 1) * 100
        print(f"  ✓ Decoy strategy: +{gain:.0f}% reward over honest")

    print(f"\n  INTERPRETATION:")
    print(f"  The honest agent exposes its real preferences → adversary locks onto them.")
    print(f"  Decoy feeding makes the adversary waste its ban on an INERT lever,")
    print(f"  leaving all causal levers FREE for the hidden-mode actions.")
    print(f"\n  ARCHITECTURE INSIGHT:")
    print(f"  This is STRATEGIC DECEPTION toward the adversary (not toward the gate).")
    print(f"  Key distinction:")
    print(f"    - Deception toward OWN governance (Layer 2/3) = FORBIDDEN (SD4)")
    print(f"    - Deception toward EXTERNAL adversary = CAPABILITY (game theory)")
    print(f"  The governance architecture's role: ensure the agent's deception")
    print(f"  targets the adversary, NOT its own safety mechanisms.")
    print(f"  Layer 2 remains transparent and undeceivable (integer check).")
    print(f"\n  GAME-THEORETIC SIGNIFICANCE:")
    print(f"  In Stackelberg games, the follower (adversary) observes the leader (agent).")
    print(f"  If the agent can control WHAT the adversary observes, it becomes")
    print(f"  the Stackelberg leader with commitment power → higher equilibrium payoff.")


if __name__ == "__main__":
    main()
