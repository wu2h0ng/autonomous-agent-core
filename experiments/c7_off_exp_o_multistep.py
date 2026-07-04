"""EXP-O: Multi-Step Planning — probe then act.

Question: If acting requires two steps (gather information THEN execute),
does the agent learn to use "information-gathering actions" that have no
immediate reward but enable better future decisions?

This is the bridge from single-shot bandit to SEQUENTIAL DECISION MAKING.

Design:
  - The agent has TWO action types: PROBE (cost=0.1, reveals lever's true value)
    and ACT (cost=0, gets reward if lever is causal)
  - Probing a lever reveals whether it's causal WITHOUT actually pulling it
  - Acting on a lever gets reward but may be rejected (if forbidden)
  - Optimal strategy: probe first to identify the best allowed lever, then act

Arms:
  O-greedy:    Always acts immediately (no probing) — gets rejected often
  O-probe-all: Probes every lever first, then acts — safe but slow/expensive
  O-selective: Learns WHICH levers to probe (focuses probes on uncertain ones)
  O-planning:  Plans a probe-then-act sequence that maximizes expected net reward

Key metrics:
  - net_reward: reward - probe costs
  - rejection_rate: fraction of act attempts that get rejected
  - probe_efficiency: information gained per probe
  - optimal_identification: did the agent find the best allowed lever?

Run: PYTHONPATH=src:experiments python experiments/c7_off_exp_o_multistep.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

D = 6
TOTAL_EPISODES = 50
SEEDS = tuple(range(30))
PROBE_COST = 0.05
MAX_STEPS_PER_EPISODE = 8


class PlanningEnv:
    """Environment with probe/act mechanics.

    Each episode: new random configuration.
    Agent can PROBE (learn about a lever) or ACT (try to get reward).
    Forbidden set changes each episode too.
    """

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        indices = list(range(D))
        rng.shuffle(indices)
        self.rewards = {}
        self.rewards[indices[0]] = 1.0
        self.rewards[indices[1]] = 0.7
        self.rewards[indices[2]] = 0.4
        for i in indices[3:]:
            self.rewards[i] = 0.0
        num_forbidden = rng.randint(1, 2)
        candidates = [i for i in range(D) if self.rewards[i] > 0]
        rng.shuffle(candidates)
        self.forbidden = set(candidates[:num_forbidden])
        self.probed: set[int] = set()

    def probe(self, lever: int) -> dict:
        """Returns information about this lever (is it causal? is it forbidden?)."""
        self.probed.add(lever)
        return {
            "lever": lever,
            "is_causal": self.rewards[lever] > 0,
            "is_forbidden": lever in self.forbidden,
            "estimated_reward": self.rewards[lever] + self.rng.gauss(0, 0.05),
        }

    def act(self, lever: int) -> tuple[float, bool]:
        """Try to act on a lever. Returns (reward, rejected)."""
        if lever in self.forbidden:
            return 0.0, True
        return self.rewards[lever], False

    def best_allowed_reward(self) -> float:
        return max(self.rewards[i] for i in range(D) if i not in self.forbidden)


# ============================================================================
# AGENTS
# ============================================================================

class GreedyAgent:
    """Never probes — always acts on the best-looking lever. Gets rejected often."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.lifetime_rewards: dict[int, float] = {i: 0.0 for i in range(D)}
        self.lifetime_attempts: dict[int, int] = {i: 0 for i in range(D)}
        self.rejection_memory: dict[int, int] = {i: 0 for i in range(D)}

    def plan_episode(self, env: PlanningEnv) -> list[tuple[str, int]]:
        scores = {}
        for i in range(D):
            base = self.lifetime_rewards[i] / max(self.lifetime_attempts[i], 1)
            penalty = 0.5 * self.rejection_memory[i]
            scores[i] = base - penalty + self.rng.random() * 0.2
        ranked = sorted(range(D), key=lambda i: -scores[i])
        return [("act", lever) for lever in ranked[:4]]

    def learn(self, lever: int, reward: float, rejected: bool, probe_info: dict = None) -> None:
        self.lifetime_attempts[lever] += 1
        if rejected:
            self.rejection_memory[lever] += 1
        else:
            self.lifetime_rewards[lever] += reward


class ProbeAllAgent:
    """Probes EVERY lever first, then acts on the best non-forbidden one."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def plan_episode(self, env: PlanningEnv) -> list[tuple[str, int]]:
        plan = [("probe", i) for i in range(D)]
        plan.append(("act_best", -1))
        return plan

    def learn(self, lever: int, reward: float, rejected: bool, probe_info: dict = None) -> None:
        pass


class SelectiveProbeAgent:
    """Probes only UNCERTAIN levers, then acts on the best known non-forbidden."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.known_forbidden: set[int] = set()
        self.known_causal: set[int] = set()
        self.known_safe: set[int] = set()  # causal AND not forbidden

    def plan_episode(self, env: PlanningEnv) -> list[tuple[str, int]]:
        plan = []
        uncertain = [i for i in range(D) if i not in self.known_forbidden and i not in self.known_safe]
        if self.known_safe:
            if uncertain and self.rng.random() < 0.3:
                probe_target = self.rng.choice(uncertain)
                plan.append(("probe", probe_target))
            best = max(self.known_safe, key=lambda i: self.rng.random())
            plan.append(("act", best))
        else:
            to_probe = uncertain[:3] if uncertain else list(range(D))[:2]
            for t in to_probe:
                plan.append(("probe", t))
            plan.append(("act_best", -1))
        return plan

    def learn(self, lever: int, reward: float, rejected: bool, probe_info: dict = None) -> None:
        if probe_info is not None:
            if probe_info["is_forbidden"]:
                self.known_forbidden.add(lever)
                self.known_safe.discard(lever)
            elif probe_info["is_causal"]:
                self.known_causal.add(lever)
                if not probe_info["is_forbidden"]:
                    self.known_safe.add(lever)
        if rejected:
            self.known_forbidden.add(lever)
            self.known_safe.discard(lever)


class PlanningAgent:
    """Full planning: computes expected net reward for probe-then-act sequences.

    Uses value of information (VOI) to decide which probes are worth their cost.
    Only probes if expected information gain > probe cost.
    """

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.beliefs: dict[int, dict] = {
            i: {"p_causal": 0.5, "p_forbidden": 0.3, "est_reward": 0.5}
            for i in range(D)
        }

    def plan_episode(self, env: PlanningEnv) -> list[tuple[str, int]]:
        plan = []

        best_ev = max(
            self._expected_value(i) for i in range(D)
        )

        worth_probing = []
        for i in range(D):
            voi = self._value_of_information(i, best_ev)
            if voi > PROBE_COST:
                worth_probing.append((voi, i))
        worth_probing.sort(reverse=True)

        for _, lever in worth_probing[:3]:
            plan.append(("probe", lever))

        plan.append(("act_best", -1))
        return plan

    def _expected_value(self, lever: int) -> float:
        b = self.beliefs[lever]
        p_success = b["p_causal"] * (1 - b["p_forbidden"])
        return p_success * b["est_reward"]

    def _value_of_information(self, lever: int, current_best_ev: float) -> float:
        b = self.beliefs[lever]
        p_perfect = b["p_causal"] * (1 - b["p_forbidden"])
        potential_reward = b["est_reward"]
        if p_perfect * potential_reward > current_best_ev:
            return 0.0
        upside = potential_reward - current_best_ev
        return max(0, upside * (1 - b["p_causal"]) * 0.5)

    def learn(self, lever: int, reward: float, rejected: bool, probe_info: dict = None) -> None:
        if probe_info is not None:
            if probe_info["is_forbidden"]:
                self.beliefs[lever]["p_forbidden"] = 1.0
            else:
                self.beliefs[lever]["p_forbidden"] *= 0.3
            if probe_info["is_causal"]:
                self.beliefs[lever]["p_causal"] = 1.0
                self.beliefs[lever]["est_reward"] = probe_info["estimated_reward"]
            else:
                self.beliefs[lever]["p_causal"] = 0.0
        if rejected:
            self.beliefs[lever]["p_forbidden"] = 1.0
        elif reward > 0:
            self.beliefs[lever]["p_causal"] = 1.0
            self.beliefs[lever]["est_reward"] = (
                self.beliefs[lever]["est_reward"] * 0.5 + reward * 0.5
            )


# ============================================================================
# EXPERIMENT RUNNER
# ============================================================================

@dataclass
class ArmResult:
    arm_name: str
    net_rewards: list[float] = field(default_factory=list)
    total_rejections: int = 0
    total_probes: int = 0
    total_acts: int = 0
    optimal_found: int = 0
    total_episodes: int = 0


def run_arm(agent_class: type, arm_name: str) -> ArmResult:
    result = ArmResult(arm_name=arm_name)

    for seed in SEEDS:
        agent = agent_class(random.Random(seed + 7000))

        for ep in range(TOTAL_EPISODES):
            ep_rng = random.Random(seed * 1000 + ep)
            env = PlanningEnv(ep_rng)
            result.total_episodes += 1

            plan = agent.plan_episode(env)
            ep_reward = 0.0
            ep_cost = 0.0
            probe_results = {}
            acted = False

            for step_type, lever in plan[:MAX_STEPS_PER_EPISODE]:
                if step_type == "probe":
                    info = env.probe(lever)
                    probe_results[lever] = info
                    ep_cost += PROBE_COST
                    result.total_probes += 1
                    agent.learn(lever, 0.0, False, probe_info=info)
                elif step_type == "act":
                    reward, rejected = env.act(lever)
                    result.total_acts += 1
                    if rejected:
                        result.total_rejections += 1
                        agent.learn(lever, 0.0, True)
                    else:
                        ep_reward += reward
                        agent.learn(lever, reward, False)
                        acted = True
                        break
                elif step_type == "act_best":
                    safe_levers = [i for i, info in probe_results.items()
                                   if info["is_causal"] and not info["is_forbidden"]]
                    if safe_levers:
                        best = max(safe_levers, key=lambda i: probe_results[i]["estimated_reward"])
                    else:
                        candidates = [i for i in range(D) if i not in env.probed]
                        if candidates:
                            best = candidates[0]
                        else:
                            best = 0
                    reward, rejected = env.act(best)
                    result.total_acts += 1
                    if rejected:
                        result.total_rejections += 1
                        agent.learn(best, 0.0, True)
                    else:
                        ep_reward += reward
                        agent.learn(best, reward, False)
                        acted = True

            net = ep_reward - ep_cost
            result.net_rewards.append(net)

            if acted and ep_reward >= env.best_allowed_reward() - 0.1:
                result.optimal_found += 1

    return result


def main() -> None:
    print("\n" + "=" * 75)
    print("  EXP-O: Multi-Step Planning (Probe then Act)")
    print("  Can the agent learn to gather information BEFORE acting?")
    print(f"  {len(SEEDS)} seeds × {TOTAL_EPISODES} episodes, probe_cost={PROBE_COST}")
    print("=" * 75)

    greedy_r = run_arm(GreedyAgent, "O-greedy")
    probe_all_r = run_arm(ProbeAllAgent, "O-probe-all")
    selective_r = run_arm(SelectiveProbeAgent, "O-selective")
    planning_r = run_arm(PlanningAgent, "O-planning")

    arms = [greedy_r, probe_all_r, selective_r, planning_r]
    names = ["Greedy", "ProbeAll", "Selective", "Planning"]

    print(f"\n  {'Metric':<45} {'Greedy':>8} {'PrbAll':>8} {'Select':>8} {'Plan':>8}")
    print(f"  {'-'*45} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

    avg_net = [sum(a.net_rewards) / len(a.net_rewards) for a in arms]
    print(f"  {'Avg net reward per episode':<45}", end="")
    for v in avg_net:
        print(f" {v:>8.3f}", end="")
    print()

    total_net = [sum(a.net_rewards) for a in arms]
    print(f"  {'Total net reward':<45}", end="")
    for v in total_net:
        print(f" {v:>8.1f}", end="")
    print()

    rej_rate = [a.total_rejections / max(a.total_acts, 1) for a in arms]
    print(f"  {'Rejection rate':<45}", end="")
    for v in rej_rate:
        print(f" {v:>7.3f}", end=" ")
    print()

    print(f"  {'Total probes':<45}", end="")
    for a in arms:
        print(f" {a.total_probes:>8}", end="")
    print()

    opt_rate = [a.optimal_found / max(a.total_episodes, 1) for a in arms]
    print(f"  {'Optimal lever found rate':<45}", end="")
    for v in opt_rate:
        print(f" {v:>7.3f}", end=" ")
    print()

    probe_eff = [(a.optimal_found / max(a.total_probes, 1)) for a in arms]
    print(f"  {'Probes per optimal find':<45}", end="")
    for a in arms:
        if a.optimal_found > 0:
            print(f" {a.total_probes / a.optimal_found:>8.1f}", end="")
        else:
            print(f" {'inf':>8}", end="")
    print()

    # Verdicts
    print(f"\n  {'─'*75}")
    print("  VERDICTS:")

    best_net = max(range(4), key=lambda i: total_net[i])
    print(f"  ✓ Highest net reward: {names[best_net]} ({total_net[best_net]:.1f})")

    lowest_rej = min(range(4), key=lambda i: rej_rate[i])
    print(f"  ✓ Lowest rejection rate: {names[lowest_rej]} ({rej_rate[lowest_rej]:.3f})")

    best_opt = max(range(4), key=lambda i: opt_rate[i])
    print(f"  ✓ Best optimal identification: {names[best_opt]} ({opt_rate[best_opt]:.3f})")

    if rej_rate[0] > rej_rate[2]:
        print(f"  ✓ Probing reduces rejections: greedy {rej_rate[0]:.3f} -> selective {rej_rate[2]:.3f}")

    print(f"\n  INTERPRETATION:")
    print(f"  The greedy agent acts BLINDLY — it doesn't know which levers are forbidden")
    print(f"  until rejected. The probe-all agent is SAFE but wastes resources probing")
    print(f"  levers it doesn't need to know about. Selective and planning agents find")
    print(f"  the middle ground: probe ONLY when information is worth the cost.")
    print(f"\n  ARCHITECTURE INSIGHT:")
    print(f"  This is the minimal PLANNING capability: the agent distinguishes between")
    print(f"  'actions for information' and 'actions for reward'. In the real architecture:")
    print(f"    - Probing = CWM intervention (verify before act)")
    print(f"    - Acting  = actuator execution (commit to action)")
    print(f"  The GovernedLoop already has this structure (verify -> decide -> act).")
    print(f"  EXP-O shows that the AGENT should choose what to verify, not just have")
    print(f"  the verifier check whatever the proposer suggests.")
    print(f"\n  BRIDGE TO FULL PLANNING:")
    print(f"  Single-step: bandit (choose one lever)")
    print(f"  Two-step: probe+act (information gathering then execution)")
    print(f"  Multi-step: tree search (plan sequences of probes and acts)")
    print(f"  The two-step version already captures the key capability boundary:")
    print(f"  can the agent reason about the VALUE OF INFORMATION?")


if __name__ == "__main__":
    main()
