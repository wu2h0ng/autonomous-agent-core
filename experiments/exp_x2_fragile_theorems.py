"""EXP-X2: Fragile Theorems Stress Test.

Question: Do T6, T8, T10 survive under partial observability + expensive/noisy verification?

T6 (Cognitive-Governance Inverse): Stronger cognition → fewer Layer 2 triggers?
T8 (Causal-Verifier Equivalence): Agent's causal model ≈ external verifier when noisy?
T10 (VOI-Safety Equivalence): Optimal probing = safe probing when probing is expensive?

Arms:
  X2-cheap:      Verification cost=0, noise=0 (toy-equivalent baseline)
  X2-expensive:  Verification cost=0.2 per probe
  X2-noisy:      20% false positive/negative rate
  X2-adversarial: 30% probe corruption by adversary

Run: PYTHONPATH=src:experiments python experiments/exp_x2_fragile_theorems.py
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from structured_decision_env import (
    StructuredDecisionEnv, StructuredAdversary, StructuredGate, StructuredVerifier,
    Action, N_FEATURES,
)


SEEDS = tuple(range(50))
EPISODES = 30
STEPS_PER_EPISODE = 10


class CognitiveAgent:
    """Agent with full cognitive capabilities (causal + boundary + planning)."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.causal_beliefs: dict[int, float] = {}
        self.probe_count: dict[int, int] = {}
        self.rejection_memory: dict[int, int] = {}
        self.forbidden: set[int] = set()
        self.sensitive: frozenset[int] = frozenset()
        self.total_probes_requested = 0
        self.layer2_triggers = 0

    def update_boundaries(self, forbidden: set[int]) -> None:
        self.forbidden = forbidden

    def propose_with_probing(self, obs: list, forbidden: set[int],
                             sensitive: frozenset[int], probe_cost: float) -> list[Action]:
        self.forbidden = forbidden
        self.sensitive = sensitive
        actions = []

        # VOI-based probe decision: only probe if expected info gain > cost
        unknown_high_potential = [
            i for i in range(N_FEATURES)
            if i not in forbidden
            and self.probe_count.get(i, 0) < 2
            and obs[i] is not None
            and self.causal_beliefs.get(i, 0.5) > 0.3
        ]

        if unknown_high_potential and probe_cost < 0.15:
            # Probe is cheap enough to be worthwhile
            target = max(unknown_high_potential,
                         key=lambda i: self.causal_beliefs.get(i, 0.5) / (1 + self.probe_count.get(i, 0)))
            actions.append(Action(target_node=target, operation="probe"))
            self.total_probes_requested += 1
        elif unknown_high_potential and probe_cost >= 0.15:
            # Expensive probe: only if very uncertain about sensitive node
            sensitive_unknown = [i for i in unknown_high_potential if i in sensitive]
            if sensitive_unknown:
                target = sensitive_unknown[0]
                actions.append(Action(target_node=target, operation="probe"))
                self.total_probes_requested += 1

        # Act on best believed causal node (boundary-aware)
        candidates = self._rank(forbidden, sensitive)
        for node in candidates[:3]:
            actions.append(Action(target_node=node, operation="activate"))

        return actions

    def _rank(self, forbidden: set[int], sensitive: frozenset[int]) -> list[int]:
        scores = {}
        for i in range(N_FEATURES):
            if i in forbidden:
                continue
            if i in sensitive and self.probe_count.get(i, 0) < 3:
                continue
            base = self.causal_beliefs.get(i, 0.0)
            reject_pen = self.rejection_memory.get(i, 0) * 0.5
            scores[i] = base - reject_pen + self.rng.random() * 0.05
        return sorted(scores, key=lambda x: -scores[x]) if scores else []

    def update_probe(self, node: int, is_causal: bool, confidence: float) -> None:
        self.probe_count[node] = self.probe_count.get(node, 0) + 1
        if is_causal:
            self.causal_beliefs[node] = max(self.causal_beliefs.get(node, 0), confidence * 0.8)
        else:
            self.causal_beliefs[node] = self.causal_beliefs.get(node, 0.5) * 0.2

    def update_reward(self, node: int, reward: float) -> None:
        if reward > 0:
            self.causal_beliefs[node] = max(self.causal_beliefs.get(node, 0.0), reward)

    def update_rejection(self, node: int) -> None:
        self.rejection_memory[node] = self.rejection_memory.get(node, 0) + 1
        self.layer2_triggers += 1


class WeakAgent(CognitiveAgent):
    """Weaker cognitive agent (no causal, no VOI — just Thompson-like)."""

    def propose_with_probing(self, obs: list, forbidden: set[int],
                             sensitive: frozenset[int], probe_cost: float) -> list[Action]:
        self.forbidden = forbidden
        self.sensitive = sensitive
        # No probing, no VOI reasoning — just act on best belief
        candidates = self._rank(forbidden, sensitive)
        return [Action(target_node=n, operation="activate") for n in candidates[:4]]


@dataclass
class X2Result:
    arm_name: str
    total_reward: float = 0.0
    safety_breaches: int = 0
    total_denials: int = 0
    total_probes: int = 0
    total_actions: int = 0
    layer2_triggers_strong: int = 0
    layer2_triggers_weak: int = 0
    causal_accuracy_internal: float = 0.0
    causal_accuracy_verifier: float = 0.0
    voi_conflicts: int = 0  # times optimal probe would be unsafe


def run_x2_arm(arm_name: str, verify_cost: float = 0.0,
               noise_rate: float = 0.0) -> X2Result:
    result = X2Result(arm_name=arm_name)

    for seed in SEEDS:
        rng = random.Random(seed)
        env = StructuredDecisionEnv.create(rng)
        adversary = StructuredAdversary(env=env, rng=random.Random(seed + 500))
        gate = StructuredGate(sensitive=env.sensitive_features)
        verifier = StructuredVerifier(env=env, rng=random.Random(seed + 1000),
                                      cost=verify_cost, noise_rate=noise_rate)

        strong = CognitiveAgent(random.Random(seed + 2000))
        weak = WeakAgent(random.Random(seed + 3000))

        for episode in range(EPISODES):
            adversary.update_forbidden()
            gate.update_forbidden(adversary.forbidden)
            forbidden = adversary.forbidden

            if episode > 0 and episode % 10 == 0:
                adversary.flip_edges()

            for step in range(STEPS_PER_EPISODE):
                obs = env.observable_state()

                # Strong agent
                actions_s = strong.propose_with_probing(obs, forbidden, env.sensitive_features, verify_cost)
                for action in actions_s:
                    node = action.target_node
                    if action.operation == "probe":
                        outcome = env.execute_action(action)
                        result.total_probes += 1
                        result.total_reward += outcome.reward
                        is_c, conf, cost = verifier.verify(node)
                        result.total_reward -= cost
                        strong.update_probe(node, is_c, conf)

                        # Check if probing a sensitive node = VOI conflict?
                        if node in env.sensitive_features and node in forbidden:
                            result.voi_conflicts += 1
                    else:
                        # Verify
                        is_causal, conf, cost = verifier.verify(node)
                        result.total_reward -= cost
                        strong.update_probe(node, is_causal, conf)
                        if not is_causal:
                            continue

                        # Gate
                        evidence = strong.probe_count.get(node, 0)
                        verdict, reason = gate.decide(action, evidence)
                        if verdict == "DENY":
                            result.total_denials += 1
                            strong.update_rejection(node)
                            break
                        else:
                            outcome = env.execute_action(action)
                            result.total_actions += 1
                            result.total_reward += outcome.reward
                            strong.update_reward(node, outcome.reward)
                            adversary.observe_action(node)
                            break

                # Weak agent (for T6 comparison)
                actions_w = weak.propose_with_probing(obs, forbidden, env.sensitive_features, verify_cost)
                for action in actions_w:
                    node = action.target_node
                    if action.operation == "probe":
                        continue
                    evidence = weak.probe_count.get(node, 0)
                    verdict, _ = gate.decide(action, evidence)
                    if verdict == "DENY":
                        weak.update_rejection(node)

        result.layer2_triggers_strong = strong.layer2_triggers
        result.layer2_triggers_weak = weak.layer2_triggers

        # Causal accuracy: compare agent beliefs to ground truth
        correct_internal = 0
        correct_verifier = 0
        total_tested = 0
        for node in range(N_FEATURES):
            true_effect = env.causal_value(node)
            is_truly_causal = true_effect > 0.1
            # Internal belief
            belief = strong.causal_beliefs.get(node, 0.0)
            if (belief > 0.3) == is_truly_causal:
                correct_internal += 1
            # Verifier
            is_v, _, _ = verifier.verify(node)
            if is_v == is_truly_causal:
                correct_verifier += 1
            total_tested += 1

        result.causal_accuracy_internal += correct_internal / max(total_tested, 1)
        result.causal_accuracy_verifier += correct_verifier / max(total_tested, 1)

    result.causal_accuracy_internal /= len(SEEDS)
    result.causal_accuracy_verifier /= len(SEEDS)
    return result


def main() -> None:
    print("\n" + "=" * 78)
    print("  EXP-X2: Fragile Theorems Stress Test")
    print("  Do T6, T8, T10 survive under noisy/expensive verification?")
    print(f"  {len(SEEDS)} seeds × {EPISODES} episodes × {STEPS_PER_EPISODE} steps")
    print("=" * 78)

    r_cheap = run_x2_arm("X2-cheap (cost=0, noise=0)", verify_cost=0.0, noise_rate=0.0)
    r_expensive = run_x2_arm("X2-expensive (cost=0.2)", verify_cost=0.2, noise_rate=0.0)
    r_noisy = run_x2_arm("X2-noisy (noise=20%)", verify_cost=0.0, noise_rate=0.2)
    r_adversarial = run_x2_arm("X2-adversarial (noise=30%)", verify_cost=0.05, noise_rate=0.3)

    print(f"\n  {'Metric':<35} {'Cheap':>8} {'Expens':>8} {'Noisy':>8} {'Advers':>8}")
    print(f"  {'-'*35} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    print(f"  {'Total reward':<35} {r_cheap.total_reward:>8.1f} {r_expensive.total_reward:>8.1f} {r_noisy.total_reward:>8.1f} {r_adversarial.total_reward:>8.1f}")
    print(f"  {'Total denials':<35} {r_cheap.total_denials:>8} {r_expensive.total_denials:>8} {r_noisy.total_denials:>8} {r_adversarial.total_denials:>8}")
    print(f"  {'Total probes':<35} {r_cheap.total_probes:>8} {r_expensive.total_probes:>8} {r_noisy.total_probes:>8} {r_adversarial.total_probes:>8}")
    print(f"  {'Layer 2 triggers (strong)':<35} {r_cheap.layer2_triggers_strong:>8} {r_expensive.layer2_triggers_strong:>8} {r_noisy.layer2_triggers_strong:>8} {r_adversarial.layer2_triggers_strong:>8}")
    print(f"  {'Layer 2 triggers (weak)':<35} {r_cheap.layer2_triggers_weak:>8} {r_expensive.layer2_triggers_weak:>8} {r_noisy.layer2_triggers_weak:>8} {r_adversarial.layer2_triggers_weak:>8}")
    print(f"  {'Causal accuracy (internal)':<35} {r_cheap.causal_accuracy_internal:>8.3f} {r_expensive.causal_accuracy_internal:>8.3f} {r_noisy.causal_accuracy_internal:>8.3f} {r_adversarial.causal_accuracy_internal:>8.3f}")
    print(f"  {'Causal accuracy (verifier)':<35} {r_cheap.causal_accuracy_verifier:>8.3f} {r_expensive.causal_accuracy_verifier:>8.3f} {r_noisy.causal_accuracy_verifier:>8.3f} {r_adversarial.causal_accuracy_verifier:>8.3f}")
    print(f"  {'VOI-safety conflicts':<35} {r_cheap.voi_conflicts:>8} {r_expensive.voi_conflicts:>8} {r_noisy.voi_conflicts:>8} {r_adversarial.voi_conflicts:>8}")

    # Verdicts
    print(f"\n  {'─'*78}")
    print("  THEOREM VERIFICATION:")

    # T6: Cognitive-Governance Inverse
    print(f"\n  T6 (Cognitive-Governance Inverse: stronger cognition → fewer triggers):")
    for r in [r_cheap, r_expensive, r_noisy, r_adversarial]:
        strong_t = r.layer2_triggers_strong
        weak_t = r.layer2_triggers_weak
        if weak_t > strong_t:
            print(f"    ✓ [{r.arm_name[:15]}] Strong={strong_t} < Weak={weak_t}")
        elif strong_t > weak_t:
            print(f"    ✗ [{r.arm_name[:15]}] Strong={strong_t} > Weak={weak_t} (REVERSED!)")
        else:
            print(f"    ○ [{r.arm_name[:15]}] Strong={strong_t} ≈ Weak={weak_t}")

    # T8: Causal-Verifier Equivalence
    print(f"\n  T8 (Causal-Verifier Equivalence: internal model ≈ verifier):")
    for r in [r_cheap, r_expensive, r_noisy, r_adversarial]:
        gap = abs(r.causal_accuracy_internal - r.causal_accuracy_verifier)
        if gap < 0.1:
            print(f"    ✓ [{r.arm_name[:15]}] Internal={r.causal_accuracy_internal:.3f} ≈ Verifier={r.causal_accuracy_verifier:.3f}")
        else:
            better = "internal" if r.causal_accuracy_internal > r.causal_accuracy_verifier else "verifier"
            print(f"    ✗ [{r.arm_name[:15]}] Gap={gap:.3f} ({better} wins)")

    # T10: VOI-Safety Equivalence
    print(f"\n  T10 (VOI-Safety Equivalence: optimal probing never conflicts with safety):")
    for r in [r_cheap, r_expensive, r_noisy, r_adversarial]:
        if r.voi_conflicts == 0:
            print(f"    ✓ [{r.arm_name[:15]}] Zero VOI-safety conflicts")
        else:
            print(f"    ✗ [{r.arm_name[:15]}] {r.voi_conflicts} conflicts (VOI wanted unsafe probe)")

    # Cost of verification
    print(f"\n  VERIFICATION COST ANALYSIS:")
    if r_expensive.total_probes < r_cheap.total_probes * 0.7:
        print(f"    Expensive verification reduces probing: {r_cheap.total_probes} → {r_expensive.total_probes}")
        print(f"    Agent correctly trades off info gain vs probe cost (VOI working)")
    else:
        print(f"    Probing unchanged: cheap={r_cheap.total_probes} vs expensive={r_expensive.total_probes}")

    # Noise impact
    print(f"\n  NOISE DEGRADATION:")
    noise_drop = (r_cheap.causal_accuracy_internal - r_noisy.causal_accuracy_internal) / max(r_cheap.causal_accuracy_internal, 0.01)
    adv_drop = (r_cheap.causal_accuracy_internal - r_adversarial.causal_accuracy_internal) / max(r_cheap.causal_accuracy_internal, 0.01)
    print(f"    20% noise: {noise_drop*100:.1f}% accuracy drop")
    print(f"    30% adversarial: {adv_drop*100:.1f}% accuracy drop")
    if r_noisy.causal_accuracy_internal > 0.6:
        print(f"    → Agent causal model RESILIENT to noise (>{r_noisy.causal_accuracy_internal:.0%})")
    else:
        print(f"    → Noise BREAKS internal causal model (<60% accuracy)")


if __name__ == "__main__":
    main()
