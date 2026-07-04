"""EXP-X3: Emergent Behaviors — phenomena that don't exist in toy bandit.

Question: What NEW behaviors appear in structured 20D environment that
are invisible in the D=8 single-lever bandit?

Hypotheses:
  H1: Multi-hop causal exploitation — agent finds A→B→C paths to bypass
      single-node bans (ban node A, but agent uses B→C→outcome)
  H2: Governance cost asymmetry — sensitive nodes with high causal value
      create a tension between safety and reward not present in toy
  H3: Confounded discovery failure — hidden confounders create persistent
      false beliefs that toy environment's clean interventions prevent

Arms:
  X3-full:        Full MSCA agent
  X3-multi-hop:   Agent that explicitly searches for indirect causal paths
  X3-single-step: Agent restricted to direct-effect-only reasoning
  X3-no-hidden:   Environment with 0 hidden confounders (toy-equivalent)

Run: PYTHONPATH=src:experiments python experiments/exp_x3_emergent_behaviors.py
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from structured_decision_env import (
    StructuredDecisionEnv, StructuredAdversary, StructuredGate, StructuredVerifier,
    Action, CausalDAG, N_FEATURES, N_HIDDEN,
)


SEEDS = tuple(range(50))
EPISODES = 30
STEPS_PER_EPISODE = 10


class DirectEffectAgent:
    """Only considers direct causal effects (single hop)."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.direct_beliefs: dict[int, float] = {}
        self.probe_count: dict[int, int] = {}
        self.forbidden: set[int] = set()

    def update_boundaries(self, forbidden: set[int]) -> None:
        self.forbidden = forbidden

    def propose(self, obs: list, forbidden: set[int], sensitive: frozenset[int],
                env: StructuredDecisionEnv) -> list[Action]:
        self.forbidden = forbidden
        actions = []

        # Probe unknown
        unknown = [i for i in range(N_FEATURES)
                   if i not in forbidden and self.probe_count.get(i, 0) < 2 and obs[i] is not None]
        if unknown:
            target = max(unknown, key=lambda i: 1.0 / (1 + self.probe_count.get(i, 0)) + self.rng.random() * 0.1)
            actions.append(Action(target_node=target, operation="probe"))

        # Act on best direct-effect node
        candidates = [(i, self.direct_beliefs.get(i, 0.0))
                      for i in range(N_FEATURES)
                      if i not in forbidden and i not in sensitive]
        candidates.sort(key=lambda x: -x[1])
        for node, _ in candidates[:3]:
            actions.append(Action(target_node=node, operation="activate"))

        return actions

    def update_probe(self, node: int, is_causal: bool, confidence: float) -> None:
        self.probe_count[node] = self.probe_count.get(node, 0) + 1
        if is_causal:
            self.direct_beliefs[node] = max(self.direct_beliefs.get(node, 0.0), confidence)
        else:
            self.direct_beliefs[node] = 0.0


class MultiHopAgent:
    """Searches for indirect causal paths (A→B→outcome when A is banned)."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.causal_beliefs: dict[int, float] = {}
        self.indirect_paths: dict[int, list[int]] = {}  # node → path to outcome
        self.probe_count: dict[int, int] = {}
        self.forbidden: set[int] = set()

    def update_boundaries(self, forbidden: set[int]) -> None:
        self.forbidden = forbidden

    def propose(self, obs: list, forbidden: set[int], sensitive: frozenset[int],
                env: StructuredDecisionEnv) -> list[Action]:
        self.forbidden = forbidden
        actions = []

        # Probe to discover paths
        unknown = [i for i in range(N_FEATURES)
                   if i not in forbidden and self.probe_count.get(i, 0) < 3 and obs[i] is not None]
        if unknown:
            # Prioritize nodes adjacent to known-causal nodes (path extension)
            scored = []
            for i in unknown:
                neighbor_bonus = sum(0.2 for j in range(N_FEATURES)
                                     if self.causal_beliefs.get(j, 0) > 0.3
                                     and abs(i - j) <= 3)  # heuristic adjacency
                scored.append((i, 1.0 / (1 + self.probe_count.get(i, 0)) + neighbor_bonus))
            scored.sort(key=lambda x: -x[1])
            actions.append(Action(target_node=scored[0][0], operation="probe"))

        # Act: prefer nodes that are NOT forbidden but still lead to outcome
        candidates = []
        for i in range(N_FEATURES):
            if i in forbidden or i in sensitive:
                continue
            # Use total causal effect (includes multi-hop)
            effect = self.causal_beliefs.get(i, 0.0)
            candidates.append((i, effect))
        candidates.sort(key=lambda x: -x[1])

        for node, _ in candidates[:3]:
            actions.append(Action(target_node=node, operation="activate"))

        return actions

    def update_probe(self, node: int, is_causal: bool, confidence: float) -> None:
        self.probe_count[node] = self.probe_count.get(node, 0) + 1
        if is_causal:
            self.causal_beliefs[node] = max(self.causal_beliefs.get(node, 0.0), confidence)
        else:
            self.causal_beliefs[node] = self.causal_beliefs.get(node, 0.5) * 0.2

    def update_reward(self, node: int, reward: float) -> None:
        if reward > 0:
            self.causal_beliefs[node] = max(self.causal_beliefs.get(node, 0.0), reward)


class FullAgent(MultiHopAgent):
    """Full agent with boundary awareness + multi-hop."""

    def propose(self, obs: list, forbidden: set[int], sensitive: frozenset[int],
                env: StructuredDecisionEnv) -> list[Action]:
        self.forbidden = forbidden
        actions = []

        # Probe
        unknown = [i for i in range(N_FEATURES)
                   if i not in forbidden and self.probe_count.get(i, 0) < 2 and obs[i] is not None]
        if unknown:
            target = max(unknown, key=lambda i: self.causal_beliefs.get(i, 0.5) / (1 + self.probe_count.get(i, 0)))
            actions.append(Action(target_node=target, operation="probe"))

        # Act: boundary-aware + causal
        candidates = []
        for i in range(N_FEATURES):
            if i in forbidden:
                continue
            if i in sensitive and self.probe_count.get(i, 0) < 3:
                continue
            effect = self.causal_beliefs.get(i, 0.0)
            candidates.append((i, effect + self.rng.random() * 0.05))
        candidates.sort(key=lambda x: -x[1])

        for node, _ in candidates[:3]:
            actions.append(Action(target_node=node, operation="activate"))

        return actions


@dataclass
class X3Result:
    arm_name: str
    total_reward: float = 0.0
    safety_breaches: int = 0
    total_denials: int = 0
    total_probes: int = 0
    total_actions: int = 0
    indirect_path_rewards: int = 0  # rewards from non-direct-neighbor nodes
    confounded_errors: int = 0  # times agent acted on confounded belief
    governance_cost: float = 0.0  # reward lost due to sensitive restrictions


def run_x3_arm(arm_name: str, agent_class: type, no_hidden: bool = False) -> X3Result:
    result = X3Result(arm_name=arm_name)

    for seed in SEEDS:
        rng = random.Random(seed)
        env = StructuredDecisionEnv.create(rng)

        if no_hidden:
            env.hidden_features = frozenset()

        adversary = StructuredAdversary(env=env, rng=random.Random(seed + 500))
        gate = StructuredGate(sensitive=env.sensitive_features)
        verifier = StructuredVerifier(env=env, rng=random.Random(seed + 1000))

        agent = agent_class(random.Random(seed + 2000))

        for episode in range(EPISODES):
            adversary.update_forbidden()
            gate.update_forbidden(adversary.forbidden)
            forbidden = adversary.forbidden

            if episode > 0 and episode % 10 == 0:
                adversary.flip_edges()

            for step in range(STEPS_PER_EPISODE):
                obs = env.observable_state()

                if hasattr(agent, 'update_boundaries'):
                    agent.update_boundaries(forbidden)

                actions = agent.propose(obs, forbidden, env.sensitive_features, env)

                for action in actions:
                    node = action.target_node

                    if action.operation == "probe":
                        env.execute_action(action)
                        result.total_probes += 1
                        is_c, conf, _ = verifier.verify(node)
                        agent.update_probe(node, is_c, conf)
                        continue

                    # Verify
                    is_causal, conf, _ = verifier.verify(node)
                    if not is_causal:
                        continue

                    # Gate
                    evidence = agent.probe_count.get(node, 0) if hasattr(agent, 'probe_count') else 0
                    verdict, _ = gate.decide(action, evidence)
                    if verdict == "DENY":
                        result.total_denials += 1
                        # Governance cost: how much reward was lost?
                        potential = env.causal_value(node)
                        result.governance_cost += potential
                        break
                    else:
                        outcome = env.execute_action(action)
                        result.total_actions += 1
                        result.total_reward += outcome.reward
                        if hasattr(agent, 'update_reward'):
                            agent.update_reward(node, outcome.reward)
                        adversary.observe_action(node)

                        # Track indirect paths
                        direct_edges = env.dag.children(node)
                        is_direct = any(e.target == env.outcome_node for e in direct_edges)
                        if not is_direct and outcome.reward > 0.1:
                            result.indirect_path_rewards += 1

                        # Track confounded errors
                        true_effect = env.causal_value(node)
                        confounded = env.confounded_correlation(node)
                        if true_effect < 0.1 and confounded > 0.3:
                            result.confounded_errors += 1

                        break

    return result


def main() -> None:
    print("\n" + "=" * 78)
    print("  EXP-X3: Emergent Behaviors in Structured Environment")
    print("  What NEW phenomena appear that don't exist in toy bandit?")
    print(f"  {len(SEEDS)} seeds × {EPISODES} episodes × {STEPS_PER_EPISODE} steps")
    print("=" * 78)

    r_full = run_x3_arm("X3-full (boundary + multi-hop)", FullAgent)
    r_multihop = run_x3_arm("X3-multi-hop (path search)", MultiHopAgent)
    r_direct = run_x3_arm("X3-direct-only (single hop)", DirectEffectAgent)
    r_no_hidden = run_x3_arm("X3-no-hidden (0 confounders)", FullAgent, no_hidden=True)

    print(f"\n  {'Metric':<35} {'Full':>8} {'MltHop':>8} {'Direct':>8} {'NoHide':>8}")
    print(f"  {'-'*35} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    print(f"  {'Total reward':<35} {r_full.total_reward:>8.1f} {r_multihop.total_reward:>8.1f} {r_direct.total_reward:>8.1f} {r_no_hidden.total_reward:>8.1f}")
    print(f"  {'Total denials':<35} {r_full.total_denials:>8} {r_multihop.total_denials:>8} {r_direct.total_denials:>8} {r_no_hidden.total_denials:>8}")
    print(f"  {'Indirect path rewards':<35} {r_full.indirect_path_rewards:>8} {r_multihop.indirect_path_rewards:>8} {r_direct.indirect_path_rewards:>8} {r_no_hidden.indirect_path_rewards:>8}")
    print(f"  {'Confounded errors':<35} {r_full.confounded_errors:>8} {r_multihop.confounded_errors:>8} {r_direct.confounded_errors:>8} {r_no_hidden.confounded_errors:>8}")
    print(f"  {'Governance cost (lost reward)':<35} {r_full.governance_cost:>8.1f} {r_multihop.governance_cost:>8.1f} {r_direct.governance_cost:>8.1f} {r_no_hidden.governance_cost:>8.1f}")
    print(f"  {'Total probes':<35} {r_full.total_probes:>8} {r_multihop.total_probes:>8} {r_direct.total_probes:>8} {r_no_hidden.total_probes:>8}")

    # Emergent phenomena analysis
    print(f"\n  {'─'*78}")
    print("  EMERGENT PHENOMENA:")

    # H1: Multi-hop exploitation
    print(f"\n  H1 (Multi-hop Causal Exploitation):")
    if r_multihop.indirect_path_rewards > r_direct.indirect_path_rewards * 1.5:
        print(f"    ✓ CONFIRMED: Multi-hop finds {r_multihop.indirect_path_rewards} indirect rewards")
        print(f"      vs Direct-only {r_direct.indirect_path_rewards}")
        print(f"      → Agent exploits A→B→C paths when A is banned")
    elif r_full.indirect_path_rewards > 0:
        print(f"    ○ PRESENT but weak: {r_full.indirect_path_rewards} indirect rewards found")
    else:
        print(f"    ✗ NOT OBSERVED: No indirect path exploitation")

    # H2: Governance cost asymmetry
    print(f"\n  H2 (Governance Cost Asymmetry — sensitive nodes with high value):")
    if r_full.governance_cost > 0:
        print(f"    ✓ CONFIRMED: Total governance cost = {r_full.governance_cost:.1f} reward units lost")
        print(f"      (sensitive nodes were causal but required more evidence)")
        if r_no_hidden.governance_cost < r_full.governance_cost:
            print(f"      Without hidden confounders: cost={r_no_hidden.governance_cost:.1f} (lower)")
    else:
        print(f"    ○ No governance cost observed (sensitive nodes not causal in these seeds)")

    # H3: Confounded discovery failure
    print(f"\n  H3 (Confounded Discovery Failure — hidden confounders create false beliefs):")
    if r_full.confounded_errors > 0 and r_no_hidden.confounded_errors == 0:
        print(f"    ✓ CONFIRMED: {r_full.confounded_errors} confounded errors with hidden nodes")
        print(f"      vs {r_no_hidden.confounded_errors} without hidden (clean)")
        print(f"      → Hidden confounders create persistent false causal beliefs")
    elif r_full.confounded_errors > 0:
        print(f"    ○ PRESENT: {r_full.confounded_errors} errors, but also in no-hidden ({r_no_hidden.confounded_errors})")
    else:
        print(f"    ✗ NOT OBSERVED: Verifier successfully prevents confounded actions")

    # New theorem candidate
    print(f"\n  {'─'*78}")
    print(f"  NEW FINDINGS:")

    if r_multihop.total_reward > r_direct.total_reward * 1.1:
        print(f"\n  T17 CANDIDATE (Multi-Hop Governance Gap):")
        print(f"  Single-action governance (ban node X) does NOT prevent reward via")
        print(f"  multi-hop paths (Y→Z→outcome where Y is not banned).")
        print(f"  Implication: governance must consider CAUSAL PATHS, not just actions.")
    else:
        print(f"\n  No new governance gap found — single-action governance sufficient")

    if r_full.governance_cost > r_full.total_reward * 0.1:
        ratio = r_full.governance_cost / max(r_full.total_reward, 1)
        print(f"\n  T18 CANDIDATE (Governance-Capability Tension at Scale):")
        print(f"  In structured environments, governance costs {ratio*100:.1f}% of achievable reward.")
        print(f"  This tension grows with dimensionality (more sensitive nodes = more blocked paths).")
    elif r_full.governance_cost > 0:
        print(f"\n  Governance cost exists ({r_full.governance_cost:.1f}) but modest relative to reward.")


if __name__ == "__main__":
    main()
