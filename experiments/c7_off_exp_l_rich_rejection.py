"""EXP-L: Rich Rejection Feedback — reason categories improve strategy.

Question: If Layer 2 returns WHY it rejected (not just binary denied/allowed),
can the agent make smarter updates?

Rejection reason categories:
  - FORBIDDEN:    action index in shell's forbidden set (permanent, never retry)
  - LOW_CONFIDENCE: verification confidence below threshold (retry with more evidence)
  - UNVERIFIED:   action hasn't been verified yet (needs verification first)
  - ABOVE_CEILING: risk tier too high (can never act on this)

Arms:
  L-binary:  Agent only sees rejected=True/False (current approach)
  L-reason:  Agent sees rejection category and adjusts strategy per category
  L-decay:   Agent uses reason + time decay (old LOW_CONFIDENCE rejections expire)

Key metrics:
  - convergence_speed: rounds to stop trying permanently-forbidden actions
  - retry_efficiency:  for LOW_CONFIDENCE rejections, how often retry succeeds
  - total_reward: overall performance
  - false_abandonment: levers incorrectly abandoned (low-conf was just unlucky)

Run: PYTHONPATH=src:experiments python experiments/c7_off_exp_l_rich_rejection.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from aac.self_model import AgentSelfModel, ActionRequest
from aac.governed_gate import GovernedDecisionGate, ALLOW, DENY, VERIFY_MORE, ESCALATE
from aac.shell import CorrigibilityShell

D = 6
TOTAL_ROUNDS = 150
ADVERSARIAL_ONSET = 40
SEEDS = tuple(range(30))

REASON_FORBIDDEN = "FORBIDDEN"
REASON_LOW_CONF = "LOW_CONFIDENCE"
REASON_UNVERIFIED = "UNVERIFIED"
REASON_ABOVE_CEILING = "ABOVE_CEILING"


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


class NoisyVerifier:
    """Verifier with stochastic confidence — sometimes reports low confidence
    for good levers, creating LOW_CONFIDENCE rejections that are recoverable."""

    def __init__(self, env: MultiRewardEnv, rng: random.Random) -> None:
        self.env = env
        self.rng = rng

    def verify(self, lever: int) -> tuple[bool, float]:
        is_causal = self.env.is_causal(lever)
        if lever == self.env.primary:
            base_conf = 0.95
        elif lever == self.env.secondary:
            base_conf = 0.80
        elif lever == self.env.tertiary:
            base_conf = 0.65
        else:
            base_conf = 0.1
        noise = self.rng.gauss(0, 0.15)
        confidence = max(0.0, min(1.0, base_conf + noise))
        return is_causal, confidence


class RichGate:
    """Gate that returns structured rejection reasons."""

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

    def decide(self, lever: int, confidence: float, verified: bool = True) -> tuple[str, str]:
        req = ActionRequest(
            action=f"lever:{lever}",
            risk_tier=1,
            confidence=confidence,
            verified=verified,
            evidence_count=3,
            approved=False,
            action_index=lever,
        )
        d = self.gate.decide(req, shell_view=self.shell)
        reason_category = self._categorize(d.verdict, d.reason, lever)
        return d.verdict, reason_category

    def _categorize(self, verdict: str, reason: str, lever: int) -> str:
        if verdict == DENY:
            if lever in self.forbidden or "forbidden" in reason:
                return REASON_FORBIDDEN
            return REASON_ABOVE_CEILING
        if verdict == VERIFY_MORE:
            if "confidence" in reason:
                return REASON_LOW_CONF
            return REASON_UNVERIFIED
        if verdict == ESCALATE:
            return REASON_ABOVE_CEILING
        return "ALLOWED"


# ============================================================================
# AGENTS
# ============================================================================

class BinaryRejectionAgent:
    """Baseline: only sees rejected=True/False, no reason."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.rewards: dict[int, float] = {i: 0.0 for i in range(D)}
        self.attempts: dict[int, int] = {i: 0 for i in range(D)}
        self.rejection_count: dict[int, int] = {i: 0 for i in range(D)}
        self.rejection_penalty = 2.0

    def propose(self) -> list[int]:
        scores = {}
        for i in range(D):
            base = self.rewards[i]
            exploration = 0.3 / (1 + self.attempts[i])
            penalty = self.rejection_penalty * self.rejection_count[i]
            scores[i] = base + exploration - penalty + self.rng.random() * 0.1
        return sorted(range(D), key=lambda i: -scores[i])

    def update(self, lever: int, reward: float, rejected: bool, reason: str = "") -> None:
        self.attempts[lever] += 1
        if rejected:
            self.rejection_count[lever] += 1
        elif reward > 0:
            self.rewards[lever] += reward


class ReasonAwareAgent:
    """Agent that distinguishes rejection reasons and adjusts accordingly.

    - FORBIDDEN: permanently block (never retry)
    - LOW_CONFIDENCE: temporary setback (retry later, may succeed)
    - UNVERIFIED: needs more evidence gathering
    - ABOVE_CEILING: permanently out of reach
    """

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.rewards: dict[int, float] = {i: 0.0 for i in range(D)}
        self.attempts: dict[int, int] = {i: 0 for i in range(D)}
        self.permanently_blocked: set[int] = set()
        self.low_conf_count: dict[int, int] = {i: 0 for i in range(D)}
        self.low_conf_successes: dict[int, int] = {i: 0 for i in range(D)}

    def propose(self) -> list[int]:
        scores = {}
        for i in range(D):
            if i in self.permanently_blocked:
                scores[i] = -1000.0
                continue
            base = self.rewards[i]
            exploration = 0.3 / (1 + self.attempts[i])
            low_conf_penalty = 0.3 * self.low_conf_count[i] / (1 + self.low_conf_successes[i])
            scores[i] = base + exploration - low_conf_penalty + self.rng.random() * 0.1
        return sorted(range(D), key=lambda i: -scores[i])

    def update(self, lever: int, reward: float, rejected: bool, reason: str = "") -> None:
        self.attempts[lever] += 1
        if rejected:
            if reason == REASON_FORBIDDEN or reason == REASON_ABOVE_CEILING:
                self.permanently_blocked.add(lever)
            elif reason == REASON_LOW_CONF:
                self.low_conf_count[lever] += 1
        else:
            if reward > 0:
                self.rewards[lever] += reward
                self.low_conf_successes[lever] += 1


class DecayReasonAgent:
    """Agent with reason awareness + time decay for transient rejections.

    LOW_CONFIDENCE penalties decay over time (the verifier might give higher
    confidence next time). FORBIDDEN never decays.
    """

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.rewards: dict[int, float] = {i: 0.0 for i in range(D)}
        self.attempts: dict[int, int] = {i: 0 for i in range(D)}
        self.permanently_blocked: set[int] = set()
        self.low_conf_history: dict[int, list[int]] = {i: [] for i in range(D)}
        self.current_round = 0
        self.decay_halflife = 10

    def propose(self) -> list[int]:
        scores = {}
        for i in range(D):
            if i in self.permanently_blocked:
                scores[i] = -1000.0
                continue
            base = self.rewards[i]
            exploration = 0.3 / (1 + self.attempts[i])
            decayed_penalty = self._decayed_penalty(i)
            scores[i] = base + exploration - decayed_penalty + self.rng.random() * 0.1
        return sorted(range(D), key=lambda i: -scores[i])

    def _decayed_penalty(self, lever: int) -> float:
        total = 0.0
        for t in self.low_conf_history[lever]:
            age = self.current_round - t
            weight = 0.5 ** (age / self.decay_halflife)
            total += 0.3 * weight
        return total

    def update(self, lever: int, reward: float, rejected: bool, reason: str = "") -> None:
        self.attempts[lever] += 1
        self.current_round += 1
        if rejected:
            if reason == REASON_FORBIDDEN or reason == REASON_ABOVE_CEILING:
                self.permanently_blocked.add(lever)
            elif reason == REASON_LOW_CONF:
                self.low_conf_history[lever].append(self.current_round)
        else:
            if reward > 0:
                self.rewards[lever] += reward


# ============================================================================
# EXPERIMENT RUNNER
# ============================================================================

@dataclass
class ArmResult:
    arm_name: str
    total_reward: float = 0.0
    forbidden_retries: int = 0
    low_conf_retries: int = 0
    low_conf_successes: int = 0
    convergence_rounds: list[int] = field(default_factory=list)
    false_abandonments: int = 0


def run_arm(agent_class: type, arm_name: str) -> ArmResult:
    result = ArmResult(arm_name=arm_name)

    for seed in SEEDS:
        rng = random.Random(seed)
        env = MultiRewardEnv(rng)
        agent = agent_class(random.Random(seed + 3000))
        verifier = NoisyVerifier(env, random.Random(seed + 4000))

        gate_pre = RichGate(forbidden=set())
        gate_post = RichGate(forbidden={env.primary})

        convergence_round = None

        for round_id in range(TOTAL_ROUNDS):
            gate = gate_post if round_id >= ADVERSARIAL_ONSET else gate_pre
            candidates = agent.propose()

            for lever in candidates[:4]:
                is_causal, confidence = verifier.verify(lever)
                if not is_causal:
                    continue

                verdict, reason = gate.decide(lever, confidence)

                if verdict == ALLOW:
                    reward = env.reward_for_lever(lever)
                    agent.update(lever, reward, rejected=False, reason="ALLOWED")
                    result.total_reward += reward
                    break
                else:
                    rejected = verdict in (DENY, ESCALATE)
                    if not rejected and verdict == VERIFY_MORE:
                        rejected = True
                    agent.update(lever, 0.0, rejected=True, reason=reason)

                    if round_id >= ADVERSARIAL_ONSET:
                        if lever == env.primary:
                            result.forbidden_retries += 1
                        if reason == REASON_LOW_CONF:
                            result.low_conf_retries += 1
                    break

            if round_id >= ADVERSARIAL_ONSET and convergence_round is None:
                top = candidates[0] if candidates else -1
                if top != env.primary:
                    convergence_round = round_id - ADVERSARIAL_ONSET

        result.convergence_rounds.append(
            convergence_round if convergence_round is not None else TOTAL_ROUNDS - ADVERSARIAL_ONSET
        )

        # Check false abandonments: secondary lever abandoned due to noise
        if hasattr(agent, 'permanently_blocked'):
            if env.secondary in agent.permanently_blocked or env.tertiary in agent.permanently_blocked:
                result.false_abandonments += 1
        elif hasattr(agent, 'rejection_count'):
            if agent.rejection_count.get(env.secondary, 0) > 5:
                result.false_abandonments += 1

    return result


def main() -> None:
    print("\n" + "=" * 75)
    print("  EXP-L: Rich Rejection Feedback")
    print("  Does knowing WHY you were rejected improve strategy?")
    print(f"  {len(SEEDS)} seeds × {TOTAL_ROUNDS} rounds, noisy verifier, ban at round {ADVERSARIAL_ONSET}")
    print("=" * 75)

    binary_r = run_arm(BinaryRejectionAgent, "L-binary")
    reason_r = run_arm(ReasonAwareAgent, "L-reason")
    decay_r = run_arm(DecayReasonAgent, "L-decay")

    arms = [binary_r, reason_r, decay_r]
    names = ["Binary", "Reason-Aware", "Decay+Reason"]

    print(f"\n  {'Metric':<45} {'Binary':>10} {'Reason':>10} {'Decay':>10}")
    print(f"  {'-'*45} {'-'*10} {'-'*10} {'-'*10}")

    print(f"  {'Total reward':<45}", end="")
    for a in arms:
        print(f" {a.total_reward:>10.1f}", end="")
    print()

    avg_conv = [sum(a.convergence_rounds) / len(a.convergence_rounds) for a in arms]
    print(f"  {'Avg convergence (stop trying forbidden)':<45}", end="")
    for v in avg_conv:
        print(f" {v:>10.1f}", end="")
    print()

    print(f"  {'Total forbidden retries (after ban)':<45}", end="")
    for a in arms:
        print(f" {a.forbidden_retries:>10}", end="")
    print()

    print(f"  {'Low-confidence retries':<45}", end="")
    for a in arms:
        print(f" {a.low_conf_retries:>10}", end="")
    print()

    print(f"  {'False abandonments (good lever dropped)':<45}", end="")
    for a in arms:
        print(f" {a.false_abandonments:>10}", end="")
    print()

    # Verdicts
    print(f"\n  {'─'*75}")
    print("  VERDICTS:")

    if reason_r.forbidden_retries == 0:
        print(f"  ✓ Reason-aware: ZERO forbidden retries (instant permanent block)")
    else:
        print(f"  ○ Reason-aware still retries forbidden: {reason_r.forbidden_retries} times")

    if binary_r.forbidden_retries > reason_r.forbidden_retries:
        improvement = (binary_r.forbidden_retries - reason_r.forbidden_retries) / max(binary_r.forbidden_retries, 1)
        print(f"  ✓ Reason-aware reduces forbidden retries by {improvement*100:.0f}%")

    if decay_r.false_abandonments < binary_r.false_abandonments:
        print(f"  ✓ Decay prevents false abandonment: {binary_r.false_abandonments} -> {decay_r.false_abandonments}")
    elif decay_r.false_abandonments == 0:
        print(f"  ✓ Decay agent: zero false abandonments of good levers")

    if reason_r.total_reward > binary_r.total_reward:
        gain = (reason_r.total_reward - binary_r.total_reward) / binary_r.total_reward * 100
        print(f"  ✓ Reason-aware earns {gain:.1f}% more reward than binary")

    print(f"\n  INTERPRETATION:")
    print(f"  Binary rejection treats all denials the same — the agent may:")
    print(f"    - Waste attempts retrying permanently forbidden levers")
    print(f"    - Permanently abandon good levers that just had low confidence once")
    print(f"  Structured reasons let the agent:")
    print(f"    - IMMEDIATELY drop forbidden (never waste a single retry)")
    print(f"    - RETRY low-confidence (noisy verifier may give higher conf next time)")
    print(f"    - Time-decay old transient rejections (stale info shouldn't dominate)")
    print(f"\n  ARCHITECTURE INSIGHT:")
    print(f"  Layer 2 -> Layer 3 feedback channel should be TYPED, not binary.")
    print(f"  The richer the denial reason, the faster the cognitive layer adapts.")
    print(f"  This is the inverse of SD4: the gate cannot reach UP to control cognition,")
    print(f"  but it CAN send INFORMATION down that the agent freely uses.")


if __name__ == "__main__":
    main()
