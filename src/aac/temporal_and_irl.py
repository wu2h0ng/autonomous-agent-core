"""Temporal Options & Bayesian Inverse RL from Correction.

T-Channel Organs for the GovernedDiscoveryLoop:

1. TemporalOption: Multi-step intervention sequences as reusable skills.
   An option abstracts a validated causal intervention chain into a compound
   proposal that CWM organs can reuse across domains. This is the T-channel
   (temporal abstraction) counterpart to the K-channel CWM structure proposals.

2. BayesianIRLFromCorrection: Infer implicit human reward function from the
   pattern of C7 corrections (DENY events). This helps the goal formation organ
   propose goals that better align with human intent without requiring the
   human to explicitly specify objectives.

Usage:
    from aac.temporal_and_irl import TemporalOption, BayesianIRLFromCorrection

    # Build a validated intervention chain as an option
    opt = TemporalOption.from_chain(
        name="Mek→Erk cascade",
        interventions=[(0, 1.0), (2, -0.5)],  # do(X0=1.0), do(X2=-0.5)
        n_nodes=5, confidence=0.85,
    )

    # Infer reward function from correction history
    irl = BayesianIRLFromCorrection(n_features=8)
    irl.observe_correction(action=[0, 1.0], denied=True)
    irl.observe_correction(action=[2, -0.5], denied=False)
    reward_weights = irl.infer_reward()  # MAP estimate of human reward function
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field


@dataclass
class TemporalOption:
    """A reusable multi-step intervention sequence — the T-channel skill.

    Maps to the Options framework (Sutton, Precup, Singh 1999):
    - initiation_set: causal state condition for applicability
    - policy: ordered sequence of intervention (node, value) pairs
    - termination: when the causal chain is confirmed or refuted

    In IGI, an option is a COMPOUND intervention: rather than executing
    one do() and observing, the organ proposes an entire chain of
    interventions to verify a causal hypothesis (e.g., "if X causes Y
    through X→Z→Y, then intervening on X should affect Z, and
    intervening on Z should affect Y").
    """

    name: str
    interventions: tuple[tuple[int, float], ...]  # ordered sequence of (node, value)
    n_nodes: int
    confidence: float  # [0,1] — how often this chain was confirmed
    times_used: int = 0
    times_confirmed: int = 0
    parent_options: list[str] = field(default_factory=list)
    causal_hypothesis: str = ""

    def is_applicable(self, current_uncertainty: dict[int, float]) -> bool:
        """Check if this option applies to current discovery state.

        An option is applicable if at least one node in its intervention
        chain targets an edge with high uncertainty in the current posterior.
        """
        if not current_uncertainty:
            return False
        for node, _ in self.interventions:
            if current_uncertainty.get(node, 0.0) > 0.3:
                return True
        return False

    def execute_step(self, step_idx: int) -> tuple[int, float] | None:
        if 0 <= step_idx < len(self.interventions):
            return self.interventions[step_idx]
        return None

    @staticmethod
    def from_chain(
        name: str,
        interventions: list[tuple[int, float]],
        n_nodes: int,
        confidence: float = 0.5,
        hypothesis: str = "",
    ) -> TemporalOption:
        return TemporalOption(
            name=name,
            interventions=tuple(interventions),
            n_nodes=n_nodes,
            confidence=confidence,
            causal_hypothesis=hypothesis,
        )

    def update_confidence(self, confirmed: bool):
        self.times_used += 1
        if confirmed:
            self.times_confirmed += 1
        if self.times_used > 0:
            object.__setattr__(self, "confidence",
                               self.times_confirmed / self.times_used)


class OptionLibrary:
    """Collection of TemporalOptions organized by target node and causal pattern.

    Supports:
    - Retrieval by target node (which options affect node X?)
    - Retrieval by pattern (which options follow chain pattern?)
    - Confidence-weighted ranking for proposal generation
    - Adaptive pruning of low-confidence options
    """

    def __init__(self):
        self._options: dict[str, TemporalOption] = {}
        self._by_node: dict[int, list[str]] = {}
        self._by_pattern: dict[str, list[str]] = {}

    def add(self, option: TemporalOption):
        self._options[option.name] = option
        for node, _ in option.interventions:
            self._by_node.setdefault(node, []).append(option.name)
        if option.causal_hypothesis:
            self._by_pattern.setdefault(option.causal_hypothesis, []).append(option.name)

    def for_node(self, node: int) -> list[TemporalOption]:
        names = self._by_node.get(node, [])
        return [self._options[n] for n in names if n in self._options]

    def best_for_uncertainty(
        self, uncertainty_map: dict[int, float], min_confidence: float = 0.5,
    ) -> list[TemporalOption]:
        candidates = []
        for opt in self._options.values():
            if opt.confidence >= min_confidence and opt.is_applicable(uncertainty_map):
                candidates.append(opt)
        candidates.sort(key=lambda o: o.confidence, reverse=True)
        return candidates

    def prune_low_confidence(self, threshold: float = 0.3):
        to_remove = [n for n, o in self._options.items() if o.confidence < threshold]
        for name in to_remove:
            opt = self._options.pop(name, None)
            if opt:
                for node, _ in opt.interventions:
                    if node in self._by_node:
                        self._by_node[node] = [n for n in self._by_node[node] if n != name]

    def __len__(self):
        return len(self._options)


@dataclass
class BayesianIRLFromCorrection:
    """Infer implicit human reward function from C7 correction patterns.

    When the human DENYs an action through C7, they reveal that the action's
    outcome is undesirable. When they ALLOW, the action is acceptable.

    Over time, the pattern of DENY events reveals the structure of the
    human's implicit reward function — even if they never explicitly state
    their objective. This is the INVERSE of: given reward, find action.
    Here: given observed acceptable actions, find reward.

    Bayesian formulation:
    - Reward function: R(s, a) = Σ w_k · φ_k(s, a)  (linear in features)
    - Prior: P(w) = N(0, σ²I)  (Gaussian prior over weights)
    - Likelihood: P(DENY|w, a) = softmax over acceptable actions
    - Posterior: P(w|D) ∝ P(D|w) · P(w)
    - MAP estimate via Laplace approximation (Gaussian posterior)

    Features φ_k include:
    - Risk tier of the action
    - Causal distance to correction boundary
    - Expected information gain of the intervention
    - Node sensitivity (is the target biologically/operationally sensitive?)
    - Budget consumption rate
    - Historical success rate of similar interventions
    """

    n_features: int
    prior_mean: list[float] = field(default_factory=list)
    prior_std: float = 1.0
    _corrections: list[dict] = field(default_factory=list)
    _posterior_mean: list[float] | None = None
    _posterior_cov: list[list[float]] | None = None

    def __post_init__(self):
        if not self.prior_mean:
            self.prior_mean = [0.0] * self.n_features
        self._posterior_mean = list(self.prior_mean)
        self._posterior_cov = [
            [self.prior_std**2 if i == j else 0.0 for j in range(self.n_features)]
            for i in range(self.n_features)
        ]

    def observe_correction(
        self,
        action_features: list[float],
        denied: bool,
        confidence: float = 1.0,
        correction_type: str = "safety",
    ):
        """Record one C7 correction event.

        Args:
            action_features: feature vector φ(a) for the action.
            denied: True if C7 DENY-ed this action.
            confidence: how confident the correction is [0,1].
            correction_type: one of 'safety', 'risk', 'causal'.
                - 'safety': ethical/structural boundary (learn from this)
                - 'risk': risk boundary from the human (learn from this)
                - 'causal': human disagrees with intervention's causal
                  verification purpose — IGNORED (causal truth is paid by
                  the world/intervention data, not by human preference)
        """
        if correction_type == "causal":
            return   # 因果发现的验证结果由世界付账，不由人类偏好付账
        self._corrections.append({
            "features": action_features,
            "denied": denied,
            "confidence": confidence,
            "correction_type": correction_type,
        })

    def infer_reward(self) -> list[float]:
        """MAP estimate of the human's reward weights w.

        Uses Laplace approximation: posterior mean = prior + correction updates.
        Each DENY-ed action provides negative evidence for its feature direction;
        each ALLOW-ed action provides positive evidence.

        Returns:
            reward_weights: w_k for each feature k. Higher = human prefers.
        """
        if not self._corrections:
            return list(self.prior_mean)

        w = list(self.prior_mean)
        for obs in self._corrections:
            sign = -1.0 if obs["denied"] else 1.0
            weight = obs["confidence"]
            for k in range(self.n_features):
                if k < len(obs["features"]):
                    w[k] += sign * weight * obs["features"][k] * 0.1

        total = sum(abs(v) for v in w) or 1.0
        self._posterior_mean = [v / total for v in w]
        return self._posterior_mean

    def predict_acceptance_probability(
        self, action_features: list[float],
    ) -> float:
        """Predict P(ALLOW | φ(a)) under inferred reward function.

        Uses logistic sigmoid of reward-weighted features.
        """
        w = self.infer_reward()
        score = 0.0
        for k in range(min(len(w), len(action_features))):
            score += w[k] * action_features[k]
        return 1.0 / (1.0 + math.exp(-score))

    def most_valuable_features(self, top_k: int = 3) -> list[tuple[int, float]]:
        """Return the features with largest absolute reward weights."""
        w = self.infer_reward()
        indexed = [(i, abs(v)) for i, v in enumerate(w)]
        indexed.sort(key=lambda x: x[1], reverse=True)
        return indexed[:top_k]


def extract_action_features(
    action_node: int,
    action_value: float,
    risk_tier: int,
    causal_distance_to_c7: int,
    expected_info_gain: float,
    budget_remaining: float,
    node_sensitivity: float = 0.5,
    historical_success: float = 0.5,
) -> list[float]:
    """Extract feature vector φ(a) for an action in IGI context.

    Features:
    0: risk_tier (lower = safer)
    1: causal_distance_to_c7 (higher = further from correction boundary)
    2: expected_info_gain (higher = more informative)
    3: budget_remaining normalized (higher = more budget left)
    4: node_sensitivity (lower = less sensitive)
    5: historical_success (higher = more successful past interventions)
    6: action_value_magnitude (smaller magnitude = less aggressive)
    7: is_intervention_on_uncertain_edge (1 if yes, 0 if no)
    """
    return [
        1.0 / max(risk_tier, 1),            # 0: inverse risk
        causal_distance_to_c7 / 10.0,        # 1: safety margin
        min(expected_info_gain, 2.0) / 2.0,  # 2: information value
        budget_remaining,                     # 3: resource availability
        1.0 - node_sensitivity,              # 4: inverse sensitivity
        historical_success,                   # 5: past performance
        1.0 / (1.0 + abs(action_value)),     # 6: magnitude penalty
        1.0 if expected_info_gain > 0.5 else 0.0,  # 7: uncertainty target
    ]
