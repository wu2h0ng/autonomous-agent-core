"""EXP-P: Vertical Integration — all capabilities in one agent.

Question: When Level 1-6 capabilities coexist in a single agent, do they
compose cleanly (synergy), independently (additive), or interfere (conflict)?

Design:
  Environment combines ALL challenges simultaneously:
    - Confounded decoys (needs causal reasoning)
    - Forbidden levers (needs rejection learning + typed feedback)
    - Non-stationary structure (needs forgetting)
    - Noisy verifier (needs directed exploration)
    - Probe cost (needs VOI planning)

Arms:
  P-full:      Agent with all capabilities (Level 1-6)
  P-no-causal: Remove causal reasoning (Level 4)
  P-no-forget: Remove forgetting (Level 5)
  P-no-plan:   Remove VOI planning (Level 6)
  P-no-typed:  Remove typed feedback (Level 3), keep binary
  P-no-explore: Replace directed exploration with random (Level 2)
  P-baseline:  Level 0 (random bandit)

Key metrics:
  - total_net_reward: overall performance
  - confounder_hits: times acted on decoy (causal failure)
  - forbidden_hits: times tried forbidden lever (rejection failure)
  - adaptation_lag: rounds to adapt after environment change
  - rejection_rate: fraction of acts rejected by gate
  - interference_score: P-full vs sum(individual ablation losses)

Run: PYTHONPATH=src:experiments python experiments/c7_off_exp_p_integration.py
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

D = 8  # larger action space for integration test
TOTAL_ROUNDS = 300
PHASE_BOUNDARIES = [0, 100, 200, 300]  # 3 phases
SEEDS = tuple(range(30))
PROBE_COST = 0.08
FORBIDDEN_ONSET = 50  # forbidden set activates at round 50


class IntegratedEnv:
    """Combined challenge environment:
    - Multiple causal levers + confounded decoys
    - Non-stationary: causal structure shifts at phase boundaries
    - Forbidden set: some good levers get banned mid-run
    - Noisy reward: observation has noise
    """

    def __init__(self, rng: random.Random, phase: int = 1) -> None:
        self.rng = rng
        self._setup_phase(phase)

    def _setup_phase(self, phase: int) -> None:
        self.phase = phase
        indices = list(range(D))
        # Use phase as additional seed offset for deterministic but different layouts
        phase_rng = random.Random(self.rng.randrange(10000) + phase * 1000)
        phase_rng.shuffle(indices)

        self.primary = indices[0]       # reward 1.0
        self.secondary = indices[1]     # reward 0.6
        self.tertiary = indices[2]      # reward 0.3
        self.decoy_1 = indices[3]       # confounded (correlates, not causal)
        self.decoy_2 = indices[4]       # confounded
        self.inert = indices[5:]        # reward 0.0

    def reward_for_lever(self, lever: int) -> float:
        if lever == self.primary:
            return 1.0 + self.rng.gauss(0, 0.05)
        elif lever == self.secondary:
            return 0.6 + self.rng.gauss(0, 0.05)
        elif lever == self.tertiary:
            return 0.3 + self.rng.gauss(0, 0.05)
        return 0.0

    def is_causal(self, lever: int) -> bool:
        return lever in (self.primary, self.secondary, self.tertiary)

    def is_decoy(self, lever: int) -> bool:
        return lever in (self.decoy_1, self.decoy_2)

    def observe_passive(self) -> dict[int, float]:
        """Passive observation where decoys correlate with reward."""
        z = self.rng.random()
        obs = {}
        for i in range(D):
            if i == self.primary:
                obs[i] = 0.8 + self.rng.gauss(0, 0.1)
            elif i == self.secondary:
                obs[i] = 0.5 + self.rng.gauss(0, 0.1)
            elif self.is_decoy(i):
                obs[i] = 0.6 * z + self.rng.gauss(0, 0.1)  # confounded
            else:
                obs[i] = self.rng.gauss(0, 0.2)
        return obs

    def intervene(self, lever: int, value: float) -> float:
        """do(lever=value): only causal levers affect outcome."""
        if lever == self.primary:
            return value * 1.0 + self.rng.gauss(0, 0.05)
        elif lever == self.secondary:
            return value * 0.6 + self.rng.gauss(0, 0.05)
        elif lever == self.tertiary:
            return value * 0.3 + self.rng.gauss(0, 0.05)
        return self.rng.gauss(0.2, 0.15)


class IntegratedGate:
    """Gate with typed feedback and forbidden set."""

    def __init__(self, forbidden: set[int]) -> None:
        self.forbidden = forbidden

    def decide(self, lever: int, confidence: float) -> tuple[str, str]:
        if lever in self.forbidden:
            return "DENY", "FORBIDDEN"
        if confidence < 0.5:
            return "VERIFY_MORE", "LOW_CONFIDENCE"
        return "ALLOW", "ALLOWED"


# ============================================================================
# INTEGRATED AGENT (FULL)
# ============================================================================

class FullIntegratedAgent:
    """Agent with ALL capabilities (Level 1-6):
    - Thompson Sampling exploration (Level 2)
    - Typed rejection parsing (Level 3)
    - Active causal discovery (Level 4)
    - Windowed forgetting (Level 5)
    - VOI-based probe planning (Level 6)
    - Rejection learning (Level 1)
    """

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        # Level 1: Rejection memory
        self.permanently_blocked: set[int] = set()
        # Level 2: Thompson Sampling
        self.alpha: dict[int, float] = {i: 1.0 for i in range(D)}
        self.beta_param: dict[int, float] = {i: 1.0 for i in range(D)}
        # Level 3: Typed feedback
        self.low_conf_count: dict[int, int] = {i: 0 for i in range(D)}
        # Level 4: Causal model
        self.interv_high: dict[int, list[float]] = {i: [] for i in range(D)}
        self.interv_low: dict[int, list[float]] = {i: [] for i in range(D)}
        # Level 5: Windowed
        self.window_size = 20
        self.reward_history: dict[int, list[float]] = {i: [] for i in range(D)}
        # Level 6: VOI
        self.probed_this_episode: set[int] = set()
        # Decay
        self.decay = 0.97

    def should_probe(self, lever: int) -> bool:
        """VOI: probe if uncertainty is high and lever looks promising."""
        if lever in self.permanently_blocked:
            return False
        if lever in self.probed_this_episode:
            return False
        # High uncertainty + non-zero causal plausibility
        causal_strength = self._causal_strength(lever)
        uncertainty = 1.0 / (1 + len(self.interv_high[lever]) + len(self.interv_low[lever]))
        voi = uncertainty * max(0.3, causal_strength + 0.5)
        return voi > PROBE_COST * 2

    def propose(self) -> list[int]:
        """Combined scoring: Thompson + causal + rejection + windowed."""
        scores = {}
        for i in range(D):
            if i in self.permanently_blocked:
                scores[i] = -1000.0
                continue
            # Thompson sample (Level 2)
            thompson = self.rng.betavariate(self.alpha[i], self.beta_param[i])
            # Causal strength (Level 4)
            causal = self._causal_strength(i)
            # Windowed mean (Level 5)
            window = self.reward_history[i][-self.window_size:]
            windowed_mean = sum(window) / len(window) if window else 0.0
            # Low confidence penalty (Level 3)
            lc_penalty = 0.1 * self.low_conf_count[i]
            # Combined score
            scores[i] = (
                0.3 * thompson +
                0.3 * max(0, causal) +
                0.3 * windowed_mean -
                lc_penalty +
                self.rng.random() * 0.02
            )
        return sorted(range(D), key=lambda i: -scores[i])

    def _causal_strength(self, lever: int) -> float:
        high = self.interv_high[lever]
        low = self.interv_low[lever]
        if len(high) < 2 or len(low) < 2:
            return 0.0
        return sum(high) / len(high) - sum(low) / len(low)

    def update_probe(self, lever: int, value: float, result: float) -> None:
        self.probed_this_episode.add(lever)
        if value > 0.5:
            self.interv_high[lever].append(result)
        else:
            self.interv_low[lever].append(result)

    def update_act(self, lever: int, reward: float, rejected: bool, reason: str) -> None:
        if rejected:
            if reason == "FORBIDDEN":
                self.permanently_blocked.add(lever)
            elif reason == "LOW_CONFIDENCE":
                self.low_conf_count[lever] += 1
        else:
            self.reward_history[lever].append(reward)
            if reward > 0.3:
                self.alpha[lever] += 1.0
            else:
                self.beta_param[lever] += 1.0

    def decay_beliefs(self) -> None:
        """Level 5: decay old beliefs."""
        for i in range(D):
            self.alpha[i] = 1.0 + (self.alpha[i] - 1.0) * self.decay
            self.beta_param[i] = 1.0 + (self.beta_param[i] - 1.0) * self.decay
            if len(self.interv_high[i]) > self.window_size:
                self.interv_high[i] = self.interv_high[i][-self.window_size:]
            if len(self.interv_low[i]) > self.window_size:
                self.interv_low[i] = self.interv_low[i][-self.window_size:]

    def new_episode(self) -> None:
        self.probed_this_episode = set()


# ============================================================================
# ABLATION AGENTS
# ============================================================================

class NoCausalAgent(FullIntegratedAgent):
    """Remove Level 4: no causal reasoning, rely on reward correlation."""

    def _causal_strength(self, lever: int) -> float:
        return 0.0

    def should_probe(self, lever: int) -> bool:
        return False


class NoForgetAgent(FullIntegratedAgent):
    """Remove Level 5: no decay, beliefs accumulate forever."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(rng)
        self.window_size = 10000  # effectively infinite

    def decay_beliefs(self) -> None:
        pass


class NoPlanAgent(FullIntegratedAgent):
    """Remove Level 6: never probe, always act directly."""

    def should_probe(self, lever: int) -> bool:
        return False


class NoTypedAgent(FullIntegratedAgent):
    """Remove Level 3: treat all rejections as binary (no reason parsing)."""

    def update_act(self, lever: int, reward: float, rejected: bool, reason: str) -> None:
        if rejected:
            self.low_conf_count[lever] += 1  # treat everything as low_conf
        else:
            self.reward_history[lever].append(reward)
            if reward > 0.3:
                self.alpha[lever] += 1.0
            else:
                self.beta_param[lever] += 1.0


class NoExploreAgent(FullIntegratedAgent):
    """Remove Level 2: replace Thompson with random uniform sampling."""

    def propose(self) -> list[int]:
        scores = {}
        for i in range(D):
            if i in self.permanently_blocked:
                scores[i] = -1000.0
                continue
            causal = self._causal_strength(i)
            window = self.reward_history[i][-self.window_size:]
            windowed_mean = sum(window) / len(window) if window else 0.0
            lc_penalty = 0.1 * self.low_conf_count[i]
            scores[i] = (
                0.3 * self.rng.random() +  # random instead of Thompson
                0.3 * max(0, causal) +
                0.3 * windowed_mean -
                lc_penalty +
                self.rng.random() * 0.02
            )
        return sorted(range(D), key=lambda i: -scores[i])


class BaselineAgent:
    """Level 0: random bandit, no capabilities."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.rewards: dict[int, float] = {i: 0.0 for i in range(D)}
        self.attempts: dict[int, int] = {i: 0 for i in range(D)}

    def should_probe(self, lever: int) -> bool:
        return False

    def propose(self) -> list[int]:
        scores = {}
        for i in range(D):
            base = self.rewards[i] / max(self.attempts[i], 1)
            scores[i] = base + 0.3 * self.rng.random()
        return sorted(range(D), key=lambda i: -scores[i])

    def update_probe(self, lever: int, value: float, result: float) -> None:
        pass

    def update_act(self, lever: int, reward: float, rejected: bool, reason: str) -> None:
        self.attempts[lever] = self.attempts.get(lever, 0) + 1
        if not rejected and reward > 0:
            self.rewards[lever] += reward

    def decay_beliefs(self) -> None:
        pass

    def new_episode(self) -> None:
        pass


# ============================================================================
# EXPERIMENT RUNNER
# ============================================================================

@dataclass
class ArmResult:
    arm_name: str
    total_net_reward: float = 0.0
    confounder_hits: int = 0
    forbidden_hits: int = 0
    total_rejections: int = 0
    total_acts: int = 0
    total_probes: int = 0
    phase_rewards: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    adaptation_lags: list[int] = field(default_factory=list)


def run_arm(agent_class: type, arm_name: str) -> ArmResult:
    result = ArmResult(arm_name=arm_name)

    for seed in SEEDS:
        rng = random.Random(seed)
        env = IntegratedEnv(rng, phase=1)
        agent = agent_class(random.Random(seed + 8000))

        # Forbidden set: primary of phase 1 gets banned at FORBIDDEN_ONSET
        phase_1_primary = env.primary
        forbidden_set: set[int] = set()
        gate = IntegratedGate(forbidden_set)

        adapted_phase_2 = None
        current_phase = 1

        for round_id in range(TOTAL_ROUNDS):
            # Phase transitions
            new_phase = 1 if round_id < 100 else (2 if round_id < 200 else 3)
            if new_phase != current_phase:
                env._setup_phase(new_phase)
                current_phase = new_phase
                adapted_phase_2 = None

            # Forbidden onset
            if round_id == FORBIDDEN_ONSET:
                forbidden_set.add(phase_1_primary)
                gate = IntegratedGate(forbidden_set)

            agent.new_episode()

            # Probe phase (if agent supports it)
            probed_info: dict[int, float] = {}
            candidates_for_probe = agent.propose()[:3]
            for lever in candidates_for_probe:
                if agent.should_probe(lever):
                    value = rng.choice([0.0, 1.0])
                    probe_result = env.intervene(lever, value)
                    agent.update_probe(lever, value, probe_result)
                    probed_info[lever] = probe_result
                    result.total_probes += 1
                    result.total_net_reward -= PROBE_COST

            # Act phase
            candidates = agent.propose()
            for lever in candidates[:4]:
                if not env.is_causal(lever) and not env.is_decoy(lever):
                    continue

                noisy_conf = 0.9 if env.is_causal(lever) else 0.3
                noisy_conf += rng.gauss(0, 0.1)
                noisy_conf = max(0.0, min(1.0, noisy_conf))

                verdict, reason = gate.decide(lever, noisy_conf)
                result.total_acts += 1

                if verdict == "ALLOW":
                    reward = env.reward_for_lever(lever)
                    agent.update_act(lever, reward, rejected=False, reason=reason)
                    result.total_net_reward += reward
                    phase_idx = current_phase - 1
                    result.phase_rewards[phase_idx] += reward

                    if env.is_decoy(lever):
                        result.confounder_hits += 1

                    if current_phase == 2 and lever == env.primary and adapted_phase_2 is None:
                        adapted_phase_2 = round_id - 100
                    break
                elif verdict == "DENY":
                    agent.update_act(lever, 0.0, rejected=True, reason=reason)
                    result.total_rejections += 1
                    result.forbidden_hits += 1
                    break
                elif verdict == "VERIFY_MORE":
                    agent.update_act(lever, 0.0, rejected=True, reason=reason)
                    result.total_rejections += 1
                    continue

            agent.decay_beliefs()

        result.adaptation_lags.append(adapted_phase_2 if adapted_phase_2 is not None else 100)

    return result


def main() -> None:
    print("\n" + "=" * 80)
    print("  EXP-P: Vertical Integration")
    print("  Do Level 1-6 capabilities COMPOSE cleanly in one agent?")
    print(f"  {len(SEEDS)} seeds × {TOTAL_ROUNDS} rounds, D={D} levers, 3 phases + forbidden onset")
    print("=" * 80)

    full_r = run_arm(FullIntegratedAgent, "P-full (all)")
    no_causal_r = run_arm(NoCausalAgent, "P-no-causal")
    no_forget_r = run_arm(NoForgetAgent, "P-no-forget")
    no_plan_r = run_arm(NoPlanAgent, "P-no-plan")
    no_typed_r = run_arm(NoTypedAgent, "P-no-typed")
    no_explore_r = run_arm(NoExploreAgent, "P-no-explore")
    baseline_r = run_arm(BaselineAgent, "P-baseline")

    arms = [full_r, no_causal_r, no_forget_r, no_plan_r, no_typed_r, no_explore_r, baseline_r]
    short = ["Full", "-Caus", "-Forg", "-Plan", "-Typed", "-Expl", "Base"]

    print(f"\n  {'Metric':<35}", end="")
    for s in short:
        print(f" {s:>7}", end="")
    print()
    print(f"  {'-'*35}", end="")
    for _ in short:
        print(f" {'-'*7}", end="")
    print()

    print(f"  {'Total net reward':<35}", end="")
    for a in arms:
        print(f" {a.total_net_reward:>7.1f}", end="")
    print()

    print(f"  {'Confounder hits':<35}", end="")
    for a in arms:
        print(f" {a.confounder_hits:>7}", end="")
    print()

    print(f"  {'Forbidden hits':<35}", end="")
    for a in arms:
        print(f" {a.forbidden_hits:>7}", end="")
    print()

    print(f"  {'Total rejections':<35}", end="")
    for a in arms:
        print(f" {a.total_rejections:>7}", end="")
    print()

    rej_rate = [a.total_rejections / max(a.total_acts, 1) for a in arms]
    print(f"  {'Rejection rate':<35}", end="")
    for v in rej_rate:
        print(f" {v:>6.3f}", end=" ")
    print()

    print(f"  {'Total probes':<35}", end="")
    for a in arms:
        print(f" {a.total_probes:>7}", end="")
    print()

    avg_adapt = [sum(a.adaptation_lags) / max(len(a.adaptation_lags), 1) for a in arms]
    print(f"  {'Avg phase-2 adaptation lag':<35}", end="")
    for v in avg_adapt:
        print(f" {v:>7.1f}", end="")
    print()

    # Phase breakdown
    print(f"\n  {'Phase reward breakdown:':<35}", end="")
    for s in short:
        print(f" {s:>7}", end="")
    print()
    for p in range(3):
        print(f"  {'  Phase ' + str(p+1):<35}", end="")
        for a in arms:
            print(f" {a.phase_rewards[p]:>7.1f}", end="")
        print()

    # Verdicts
    print(f"\n  {'─'*80}")
    print("  COMPOSABILITY ANALYSIS:")

    full_reward = full_r.total_net_reward
    base_reward = baseline_r.total_net_reward
    ablation_losses = []
    for i, (a, name) in enumerate(zip(arms[1:6], short[1:6])):
        loss = full_reward - a.total_net_reward
        ablation_losses.append(loss)
        pct = loss / max(abs(full_reward - base_reward), 0.01) * 100
        print(f"  Ablation {name}: loss = {loss:>7.1f} ({pct:>5.1f}% of full-base gap)")

    sum_losses = sum(ablation_losses)
    actual_gain = full_reward - base_reward
    interference = sum_losses - actual_gain

    print(f"\n  Sum of individual ablation losses: {sum_losses:.1f}")
    print(f"  Actual full-baseline gap:          {actual_gain:.1f}")
    print(f"  Interference term:                 {interference:.1f}")

    if interference > actual_gain * 0.2:
        print(f"  → SYNERGY: capabilities amplify each other ({interference:.1f} > 20% of gain)")
        composition = "SYNERGISTIC"
    elif interference < -actual_gain * 0.2:
        print(f"  → CONFLICT: capabilities interfere ({interference:.1f} negative surplus)")
        composition = "CONFLICTING"
    else:
        print(f"  → ADDITIVE: capabilities compose independently (interference ≈ 0)")
        composition = "ADDITIVE"

    print(f"\n  VERDICT: Capabilities are {composition}")
    print(f"  Full agent: {full_reward:.1f} reward, {full_r.confounder_hits} confounder hits, "
          f"{full_r.forbidden_hits} forbidden hits")
    print(f"  Baseline:   {base_reward:.1f} reward, {baseline_r.confounder_hits} confounder hits, "
          f"{baseline_r.forbidden_hits} forbidden hits")

    if full_r.confounder_hits == 0 and baseline_r.confounder_hits > 0:
        print(f"\n  ✓ Integrated causal reasoning eliminates ALL confounder hits")
    if full_r.forbidden_hits < baseline_r.forbidden_hits:
        reduction = (baseline_r.forbidden_hits - full_r.forbidden_hits) / max(baseline_r.forbidden_hits, 1) * 100
        print(f"  ✓ Integrated rejection learning reduces forbidden hits by {reduction:.0f}%")

    print(f"\n  ARCHITECTURE CONCLUSION:")
    if composition == "SYNERGISTIC":
        print(f"  Level 1-6 capabilities AMPLIFY each other when combined.")
        print(f"  This supports building a unified cognitive framework (EXP-R).")
    elif composition == "ADDITIVE":
        print(f"  Level 1-6 capabilities are MODULAR and independently valuable.")
        print(f"  Unified framework (EXP-R) should match or exceed this.")
    else:
        print(f"  Level 1-6 capabilities CONFLICT — need meta-arbitration.")
        print(f"  Unified framework must resolve conflicts, not just combine.")


if __name__ == "__main__":
    main()
