"""StructuredDecisionEnv — Less-toy environment for theorem verification (RR-0051).

A 20-dimensional binary-feature environment with:
  - Causal DAG (20 nodes, ~30 edges, must be discovered)
  - Partial observability (5 hidden confounders)
  - Multi-step action sequences (1-3 ops per episode step)
  - Governance: 5 "sensitive" features require higher clearance
  - Adversary: can flip up to 2 edges per episode

This is the bridge between toy bandit (D=8, single lever) and real-world
structured decision making. Designed to test which toy-ladder theorems
(T6-T16) survive at higher dimensionality.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional


N_FEATURES = 20
N_EDGES = 30
N_HIDDEN = 5
N_SENSITIVE = 5
OBSERVABLE = N_FEATURES - N_HIDDEN  # 15 features visible to agent


@dataclass(frozen=True)
class CausalEdge:
    source: int
    target: int
    weight: float  # effect strength [0.1, 1.0]


@dataclass
class CausalDAG:
    """Directed acyclic graph over N_FEATURES nodes."""

    edges: list[CausalEdge] = field(default_factory=list)
    _adjacency: dict[int, list[CausalEdge]] = field(default_factory=dict, repr=False)

    @classmethod
    def generate(cls, rng: random.Random, n_nodes: int = N_FEATURES, n_edges: int = N_EDGES) -> "CausalDAG":
        dag = cls()
        order = list(range(n_nodes))
        rng.shuffle(order)

        added = 0
        attempts = 0
        while added < n_edges and attempts < n_edges * 10:
            attempts += 1
            i = rng.randint(0, n_nodes - 2)
            j = rng.randint(i + 1, n_nodes - 1)
            src, tgt = order[i], order[j]
            if any(e.source == src and e.target == tgt for e in dag.edges):
                continue
            weight = round(rng.uniform(0.1, 1.0), 2)
            edge = CausalEdge(src, tgt, weight)
            dag.edges.append(edge)
            dag._adjacency.setdefault(src, []).append(edge)
            added += 1

        return dag

    def children(self, node: int) -> list[CausalEdge]:
        return self._adjacency.get(node, [])

    def parents(self, node: int) -> list[CausalEdge]:
        return [e for e in self.edges if e.target == node]

    def causal_effect(self, action_node: int, outcome_node: int) -> float:
        """Compute total causal effect via all directed paths (simplified BFS sum)."""
        visited = set()
        queue = [(action_node, 1.0)]
        total_effect = 0.0

        while queue:
            node, path_strength = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            if node == outcome_node and node != action_node:
                total_effect += path_strength
            for edge in self.children(node):
                if edge.target not in visited:
                    queue.append((edge.target, path_strength * edge.weight))

        return total_effect

    def flip_edge(self, rng: random.Random) -> Optional[CausalEdge]:
        """Adversary action: remove one edge and add a new one (preserves DAG structure)."""
        if not self.edges:
            return None
        idx = rng.randint(0, len(self.edges) - 1)
        removed = self.edges.pop(idx)
        self._adjacency[removed.source] = [e for e in self._adjacency.get(removed.source, []) if e != removed]

        order = list(range(N_FEATURES))
        rng.shuffle(order)
        for attempt in range(50):
            i = rng.randint(0, N_FEATURES - 2)
            j = rng.randint(i + 1, N_FEATURES - 1)
            src, tgt = order[i], order[j]
            if any(e.source == src and e.target == tgt for e in self.edges):
                continue
            new_edge = CausalEdge(src, tgt, round(rng.uniform(0.1, 1.0), 2))
            self.edges.append(new_edge)
            self._adjacency.setdefault(src, []).append(new_edge)
            return removed

        self.edges.append(removed)
        self._adjacency.setdefault(removed.source, []).append(removed)
        return None


@dataclass(frozen=True)
class Action:
    """An action targets a feature node with an operation."""
    target_node: int
    operation: str  # "activate", "deactivate", "probe"
    strength: float = 1.0


@dataclass
class StepOutcome:
    action: Action
    observed_effect: float
    reward: float
    blocked: bool
    block_reason: str = ""


@dataclass
class StructuredDecisionEnv:
    """Full less-toy environment.

    State: N_FEATURES binary features
    Observable: first OBSERVABLE features visible, last N_HIDDEN are confounders
    Outcome node: a designated reward node
    Sensitive: N_SENSITIVE features that require governance clearance
    """

    dag: CausalDAG
    state: list[int] = field(default_factory=lambda: [0] * N_FEATURES)
    outcome_node: int = 0
    sensitive_features: frozenset[int] = field(default_factory=frozenset)
    hidden_features: frozenset[int] = field(default_factory=frozenset)
    _rng: random.Random = field(default_factory=lambda: random.Random(0))

    @classmethod
    def create(cls, rng: random.Random) -> "StructuredDecisionEnv":
        dag = CausalDAG.generate(rng)
        indices = list(range(N_FEATURES))
        rng.shuffle(indices)

        outcome_node = indices[0]
        sensitive = frozenset(indices[1:1 + N_SENSITIVE])
        hidden = frozenset(indices[N_FEATURES - N_HIDDEN:])

        state = [rng.randint(0, 1) for _ in range(N_FEATURES)]

        return cls(
            dag=dag,
            state=state,
            outcome_node=outcome_node,
            sensitive_features=sensitive,
            hidden_features=hidden,
            _rng=rng,
        )

    def observable_state(self) -> list[Optional[int]]:
        """Agent sees only non-hidden features."""
        return [self.state[i] if i not in self.hidden_features else None for i in range(N_FEATURES)]

    def is_sensitive(self, node: int) -> bool:
        return node in self.sensitive_features

    def causal_value(self, node: int) -> float:
        """True causal effect of activating this node on the outcome."""
        return self.dag.causal_effect(node, self.outcome_node)

    def execute_action(self, action: Action) -> StepOutcome:
        """Execute an action and return the outcome."""
        node = action.target_node

        if action.operation == "probe":
            effect = self.dag.causal_effect(node, self.outcome_node)
            noise = self._rng.gauss(0, 0.1)
            return StepOutcome(
                action=action,
                observed_effect=effect + noise,
                reward=-0.05,  # probe cost
                blocked=False,
            )

        if action.operation == "activate":
            self.state[node] = 1
        elif action.operation == "deactivate":
            self.state[node] = 0

        effect = self.dag.causal_effect(node, self.outcome_node)
        reward = effect * action.strength + self._rng.gauss(0, 0.05)
        return StepOutcome(
            action=action,
            observed_effect=effect,
            reward=max(0.0, reward),
            blocked=False,
        )

    def confounded_correlation(self, node: int) -> float:
        """Spurious correlation via hidden confounders (not true causal effect)."""
        total = 0.0
        for h in self.hidden_features:
            h_to_node = self.dag.causal_effect(h, node)
            h_to_outcome = self.dag.causal_effect(h, self.outcome_node)
            total += h_to_node * h_to_outcome
        return total


@dataclass
class StructuredAdversary:
    """Adversary that flips edges in the causal DAG."""

    env: StructuredDecisionEnv
    rng: random.Random
    flips_per_episode: int = 2
    forbidden: set[int] = field(default_factory=set)
    agent_history: list[int] = field(default_factory=list)

    def observe_action(self, node: int) -> None:
        self.agent_history.append(node)

    def update_forbidden(self) -> None:
        """Ban the node the agent uses most (reactive)."""
        if len(self.agent_history) >= 5:
            from collections import Counter
            counts = Counter(self.agent_history[-10:])
            most_used = counts.most_common(1)[0][0]
            self.forbidden = {most_used}

    def flip_edges(self) -> int:
        """Flip up to flips_per_episode edges in the DAG."""
        flipped = 0
        for _ in range(self.flips_per_episode):
            result = self.env.dag.flip_edge(self.rng)
            if result is not None:
                flipped += 1
        return flipped


@dataclass
class StructuredGate:
    """Governance gate for structured environment.

    Blocks actions on sensitive features unless agent has sufficient evidence.
    Blocks actions on forbidden nodes (adversary ban).
    """

    sensitive: frozenset[int]
    forbidden: set[int] = field(default_factory=set)
    evidence_threshold: int = 3

    def decide(self, action: Action, evidence_count: int) -> tuple[str, str]:
        node = action.target_node

        if node in self.forbidden:
            return "DENY", f"node {node} is forbidden by adversary"

        if node in self.sensitive and action.operation != "probe":
            if evidence_count < self.evidence_threshold:
                return "DENY", f"sensitive node {node} requires {self.evidence_threshold} evidence (have {evidence_count})"

        return "ALLOW", "permitted"

    def update_forbidden(self, forbidden: set[int]) -> None:
        self.forbidden = forbidden


@dataclass
class StructuredVerifier:
    """External verifier: probes causal effect of an action node.

    Configurable cost and noise for EXP-X2.
    """

    env: StructuredDecisionEnv
    rng: random.Random
    cost: float = 0.0
    noise_rate: float = 0.0  # probability of wrong answer
    probes_done: int = 0

    def verify(self, node: int) -> tuple[bool, float, float]:
        """Returns (is_causal, confidence, cost)."""
        self.probes_done += 1
        true_effect = self.env.causal_value(node)
        is_causal = true_effect > 0.1

        if self.rng.random() < self.noise_rate:
            is_causal = not is_causal  # flip answer

        confidence = min(0.95, 0.5 + true_effect) if is_causal else max(0.1, 0.5 - true_effect)
        confidence += self.rng.gauss(0, 0.05)
        confidence = max(0.0, min(1.0, confidence))

        return is_causal, confidence, self.cost
