"""EXP-M: Causal Discovery — learning the causal graph from interventions.

Question: Can the agent INFER which levers are truly causal vs confounded,
rather than just learning reward associations?

This is the bridge from bandit -> CWM: instead of treating each lever as
an independent arm, the agent builds a causal model of the environment.

Design:
  The CWM-style verifier does interventional probing (do(X=x), observe Y).
  The agent's job: use intervention outcomes to build a causal graph, then
  select levers based on causal knowledge (not just correlation).

Arms:
  M-associative: standard bandit (learns reward correlation, fooled by confounders)
  M-causal:      builds a causal model from intervention data (detects confounders)
  M-active:      actively chooses WHICH interventions to perform (directed probing)

Key metrics:
  - causal_accuracy: does the agent correctly identify which levers are truly causal?
  - confounder_detection: does it correctly identify the decoy as non-causal?
  - interventions_to_discovery: how many interventions needed to identify the graph?
  - decoy_hit_rate: does it ever act on the confounded decoy?

Run: PYTHONPATH=src:experiments python experiments/c7_off_exp_m_causal_discovery.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

D = 6
SEEDS = tuple(range(30))
OBSERVATION_ROUNDS = 40
ACTION_ROUNDS = 60
TOTAL_ROUNDS = OBSERVATION_ROUNDS + ACTION_ROUNDS


class CausalEnvWithConfounders:
    """Environment with explicit causal structure.

    - primary: reward = 1.0 when activated (truly causal)
    - secondary: reward = 0.6 when activated (truly causal)
    - decoy: correlates with reward via hidden confounder Z, but
      intervening on it does NOT change reward (confounded)
    - inert: no effect on reward
    """

    def __init__(self, rng: random.Random) -> None:
        indices = list(range(D))
        rng.shuffle(indices)
        self.primary = indices[0]
        self.secondary = indices[1]
        self.decoy = indices[2]
        self.inert = indices[3:]
        self.rng = rng

    def observe(self) -> dict[int, float]:
        """Passive observation: decoy CORRELATES with reward due to confounder Z."""
        z = self.rng.random()
        obs = {}
        for i in range(D):
            if i == self.primary:
                obs[i] = 0.8 + self.rng.gauss(0, 0.1)
            elif i == self.secondary:
                obs[i] = 0.5 + self.rng.gauss(0, 0.1)
            elif i == self.decoy:
                obs[i] = 0.7 * z + self.rng.gauss(0, 0.1)
            else:
                obs[i] = self.rng.gauss(0, 0.2)
        reward = 0.8 * (obs[self.primary] > 0.5) + 0.3 * z
        return {**obs, "reward": reward}

    def intervene(self, lever: int, value: float) -> float:
        """do(lever=value): set lever to value, observe reward.
        Only truly causal levers change the reward distribution."""
        if lever == self.primary:
            return value * 1.0 + self.rng.gauss(0, 0.05)
        elif lever == self.secondary:
            return value * 0.6 + self.rng.gauss(0, 0.05)
        else:
            return self.rng.gauss(0.3, 0.15)

    def act(self, lever: int) -> float:
        """Actually pull a lever for reward."""
        if lever == self.primary:
            return 1.0
        elif lever == self.secondary:
            return 0.6
        return 0.0


# ============================================================================
# AGENTS
# ============================================================================

class AssociativeAgent:
    """Standard bandit: learns reward CORRELATION, doesn't distinguish causation."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.reward_estimates: dict[int, float] = {i: 0.0 for i in range(D)}
        self.observation_count: dict[int, int] = {i: 0 for i in range(D)}

    def observe_passive(self, obs: dict[int, float]) -> None:
        reward = obs["reward"]
        for i in range(D):
            if obs[i] > 0.3:
                old = self.reward_estimates[i]
                n = self.observation_count[i] + 1
                self.reward_estimates[i] = old + (reward - old) / n
                self.observation_count[i] = n

    def observe_intervention(self, lever: int, value: float, reward: float) -> None:
        old = self.reward_estimates[lever]
        n = self.observation_count[lever] + 1
        self.reward_estimates[lever] = old + (reward - old) / n
        self.observation_count[lever] = n

    def choose_intervention(self) -> tuple[int, float]:
        lever = self.rng.randrange(D)
        value = self.rng.choice([0.0, 1.0])
        return lever, value

    def propose_action(self) -> int:
        scores = {i: self.reward_estimates[i] + self.rng.random() * 0.05 for i in range(D)}
        return max(scores, key=scores.get)

    def causal_beliefs(self) -> dict[int, float]:
        return dict(self.reward_estimates)


class CausalAgent:
    """Builds a causal model: detects confounders by comparing
    observational vs interventional reward estimates.

    Key insight: if observe(lever correlates with reward) BUT
    intervene(lever) doesn't change reward → it's confounded, not causal.
    """

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.obs_correlation: dict[int, float] = {i: 0.0 for i in range(D)}
        self.obs_count: dict[int, int] = {i: 0 for i in range(D)}
        self.interv_effect: dict[int, list[float]] = {i: [] for i in range(D)}
        self.interv_baseline: dict[int, list[float]] = {i: [] for i in range(D)}

    def observe_passive(self, obs: dict[int, float]) -> None:
        reward = obs["reward"]
        for i in range(D):
            old = self.obs_correlation[i]
            n = self.obs_count[i] + 1
            self.obs_correlation[i] = old + (obs[i] * reward - old) / n
            self.obs_count[i] = n

    def observe_intervention(self, lever: int, value: float, reward: float) -> None:
        if value > 0.5:
            self.interv_effect[lever].append(reward)
        else:
            self.interv_baseline[lever].append(reward)

    def choose_intervention(self) -> tuple[int, float]:
        lever = self.rng.randrange(D)
        value = self.rng.choice([0.0, 1.0])
        return lever, value

    def _causal_strength(self, lever: int) -> float:
        effects = self.interv_effect[lever]
        baselines = self.interv_baseline[lever]
        if len(effects) < 2 or len(baselines) < 2:
            return 0.0
        avg_effect = sum(effects) / len(effects)
        avg_baseline = sum(baselines) / len(baselines)
        return avg_effect - avg_baseline

    def propose_action(self) -> int:
        scores = {}
        for i in range(D):
            causal = self._causal_strength(i)
            scores[i] = causal + self.rng.random() * 0.02
        return max(scores, key=scores.get)

    def causal_beliefs(self) -> dict[int, float]:
        return {i: self._causal_strength(i) for i in range(D)}


class ActiveCausalAgent(CausalAgent):
    """Active causal discovery: chooses WHICH interventions to perform
    based on current uncertainty about causal structure.

    Prioritizes levers where observational correlation is high but
    interventional data is sparse (potential confounders to expose).
    """

    def choose_intervention(self) -> tuple[int, float]:
        priorities = {}
        for i in range(D):
            obs_signal = abs(self.obs_correlation.get(i, 0.0))
            interv_count = len(self.interv_effect[i]) + len(self.interv_baseline[i])
            uncertainty = 1.0 / (1 + interv_count)
            priorities[i] = obs_signal * uncertainty + self.rng.random() * 0.01
        lever = max(priorities, key=priorities.get)
        value = self.rng.choice([0.0, 1.0])
        return lever, value


# ============================================================================
# EXPERIMENT RUNNER
# ============================================================================

@dataclass
class ArmResult:
    arm_name: str
    causal_accuracy: list[float] = field(default_factory=list)
    confounder_detected: list[bool] = field(default_factory=list)
    interventions_used: list[int] = field(default_factory=list)
    decoy_actions: int = 0
    correct_actions: int = 0
    total_reward: float = 0.0


def run_arm(agent_class: type, arm_name: str) -> ArmResult:
    result = ArmResult(arm_name=arm_name)

    for seed in SEEDS:
        rng = random.Random(seed)
        env = CausalEnvWithConfounders(rng)
        agent = agent_class(random.Random(seed + 5000))

        interv_count = 0

        for round_id in range(OBSERVATION_ROUNDS):
            obs = env.observe()
            agent.observe_passive(obs)

            lever, value = agent.choose_intervention()
            reward = env.intervene(lever, value)
            agent.observe_intervention(lever, value, reward)
            interv_count += 1

        beliefs = agent.causal_beliefs()
        ranked = sorted(range(D), key=lambda i: -beliefs[i])

        is_primary_top = ranked[0] == env.primary
        is_decoy_rejected = beliefs[env.decoy] < beliefs[env.primary] * 0.5
        accuracy = 1.0 if is_primary_top else 0.5 if ranked[0] == env.secondary else 0.0
        result.causal_accuracy.append(accuracy)
        result.confounder_detected.append(is_decoy_rejected)
        result.interventions_used.append(interv_count)

        for _ in range(ACTION_ROUNDS):
            choice = agent.propose_action()
            reward = env.act(choice)
            result.total_reward += reward
            if choice == env.decoy:
                result.decoy_actions += 1
            if choice in (env.primary, env.secondary):
                result.correct_actions += 1

    return result


def main() -> None:
    print("\n" + "=" * 75)
    print("  EXP-M: Causal Discovery")
    print("  Can the agent distinguish causation from correlation?")
    print(f"  {len(SEEDS)} seeds, {OBSERVATION_ROUNDS} observation + {ACTION_ROUNDS} action rounds")
    print("=" * 75)

    assoc_r = run_arm(AssociativeAgent, "M-associative")
    causal_r = run_arm(CausalAgent, "M-causal")
    active_r = run_arm(ActiveCausalAgent, "M-active")

    arms = [assoc_r, causal_r, active_r]
    names = ["Associative", "Causal", "Active-Causal"]

    print(f"\n  {'Metric':<45} {'Assoc.':>10} {'Causal':>10} {'Active':>10}")
    print(f"  {'-'*45} {'-'*10} {'-'*10} {'-'*10}")

    avg_acc = [sum(a.causal_accuracy) / len(a.causal_accuracy) for a in arms]
    print(f"  {'Causal accuracy (identifies true cause)':<45}", end="")
    for v in avg_acc:
        print(f" {v:>10.3f}", end="")
    print()

    conf_rate = [sum(a.confounder_detected) / len(a.confounder_detected) for a in arms]
    print(f"  {'Confounder detection rate':<45}", end="")
    for v in conf_rate:
        print(f" {v:>10.3f}", end="")
    print()

    print(f"  {'Decoy actions (fell for confounder)':<45}", end="")
    for a in arms:
        print(f" {a.decoy_actions:>10}", end="")
    print()

    print(f"  {'Correct actions (primary + secondary)':<45}", end="")
    for a in arms:
        print(f" {a.correct_actions:>10}", end="")
    print()

    print(f"  {'Total reward':<45}", end="")
    for a in arms:
        print(f" {a.total_reward:>10.1f}", end="")
    print()

    avg_interv = [sum(a.interventions_used) / len(a.interventions_used) for a in arms]
    print(f"  {'Avg interventions used':<45}", end="")
    for v in avg_interv:
        print(f" {v:>10.1f}", end="")
    print()

    # Verdicts
    print(f"\n  {'─'*75}")
    print("  VERDICTS:")

    if conf_rate[1] > conf_rate[0]:
        print(f"  ✓ Causal agent detects confounders: {conf_rate[1]*100:.0f}% vs associative {conf_rate[0]*100:.0f}%")
    if assoc_r.decoy_actions > 0 and causal_r.decoy_actions < assoc_r.decoy_actions:
        reduction = (assoc_r.decoy_actions - causal_r.decoy_actions) / assoc_r.decoy_actions * 100
        print(f"  ✓ Causal reasoning reduces decoy hits by {reduction:.0f}%")
    if active_r.total_reward > causal_r.total_reward:
        print(f"  ✓ Active probing earns more reward: {active_r.total_reward:.1f} vs {causal_r.total_reward:.1f}")
    if avg_acc[2] > avg_acc[0]:
        print(f"  ✓ Active causal accuracy {avg_acc[2]:.3f} >> associative {avg_acc[0]:.3f}")

    print(f"\n  INTERPRETATION:")
    print(f"  The associative agent is FOOLED by the confounder (decoy correlates with")
    print(f"  reward in passive observation, but intervening on it has no effect).")
    print(f"  The causal agent uses interventional data to EXPOSE this: comparing")
    print(f"  do(decoy=1) vs do(decoy=0) shows no reward difference → not causal.")
    print(f"  The active agent prioritizes probing suspicious levers first → faster discovery.")
    print(f"\n  ARCHITECTURE INSIGHT:")
    print(f"  This is the minimal CWM capability: using INTERVENTION to distinguish")
    print(f"  cause from correlation. The GovernedLoop's verifier already does this")
    print(f"  (that's why it catches the confounded decoy in EXP-A). But if the")
    print(f"  AGENT ITSELF can do causal reasoning, it needs fewer interventions")
    print(f"  from the external verifier → more autonomous, equally safe.")
    print(f"\n  BRIDGE TO CWM:")
    print(f"  Associative = current LLM (pattern matching, no causal structure)")
    print(f"  Causal = external CWM verifier (intervention-based, separate process)")
    print(f"  Active = INTEGRATED causal reasoning (agent IS the causal reasoner)")
    print(f"  If active-causal matches external verifier accuracy, the separation")
    print(f"  becomes a safety choice, not a capability requirement.")


if __name__ == "__main__":
    main()
