"""UncertaintyMap — structured causal uncertainty replacing scalar confidence.

Defect fix #3: scalar confidence (0.5) collapses heterogeneous uncertainty into
one uninformative number. The UncertaintyMap tracks per-edge:

  presence_prob: P(edge exists) [0,1]
  direction_prob: P(X→Y | edge exists) [0,1]
  identifiability: "data_sufficient" | "data_limited" | "objectively_unidentifiable"
  evidence_sources: {"ci_test", "intervention", "temporal", "llm", "mechanism"}
  last_updated: monotonic round counter
  validation_status: "unverified" | "ci_test_only" | "intervention_verified"

This enables the engine to:
- Know what it doesn't know (data_limited vs objectively_unidentifiable)
- Prioritize which edges need more evidence (low presence prob + data_limited)
- Route through the two-phase pipeline (exploratory → confirmatory)
- Decide when to consult LLM (objectively_unidentifiable edges)

Replaces scalar confidence throughout the codebase.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Identifiability(str):  # Enum-like for simplicity
    DATA_SUFFICIENT = "data_sufficient"
    DATA_LIMITED = "data_limited"
    OBJECTIVELY_UNIDENTIFIABLE = "objectively_unidentifiable"


class ValidationStatus(str):
    UNVERIFIED = "unverified"
    CI_TEST_ONLY = "ci_test_only"
    INTERVENTION_VERIFIED = "intervention_verified"
    TEMPORAL_CONFIRMED = "temporal_confirmed"
    LLM_CONSISTENT = "llm_consistent"


@dataclass
class EdgeUncertainty:
    presence_prob: float = 0.5
    direction_prob: float = 0.5
    identifiability: str = Identifiability.DATA_LIMITED
    evidence_sources: set[str] = field(default_factory=set)
    last_updated: int = 0
    validation: str = ValidationStatus.UNVERIFIED
    ci_statistic: float = 0.0         # partial correlation or HSIC p-value
    intervention_effect: float = 0.0  # do()-based effect size
    anm_score_forward: float = 0.0   # ANM direction score X→Y
    anm_score_reverse: float = 0.0   # ANM direction score Y→X


@dataclass
class UncertaintyMap:
    """Per-edge structured uncertainty for the entire causal discovery pipeline.

    Maintains presence + direction probabilities, evidence sources, and
    identifiability classes for every possible edge pair in the system.
    Supports the two-phase (exploratory → confirmatory) architecture.
    """

    n_nodes: int
    edges: dict[tuple[int, int], EdgeUncertainty] = field(default_factory=dict)
    _round: int = 0

    def __post_init__(self):
        for i in range(self.n_nodes):
            for j in range(i + 1, self.n_nodes):
                self.edges[(i, j)] = EdgeUncertainty()
                self.edges[(j, i)] = EdgeUncertainty()

    def update_ci_test(self, i: int, j: int, pcorr: float, pvalue: float = 0.0):
        """Record CI test evidence."""
        self._round += 1
        for direction in [(i, j), (j, i)]:
            e = self.edges[direction]
            e.ci_statistic = pcorr
            e.presence_prob = 0.5 + 0.5 * min(pcorr, 1.0) if pvalue < 0.05 else 0.5 * (1 - pvalue)
            e.evidence_sources.add("ci_test")
            e.last_updated = self._round
            if e.validation == ValidationStatus.UNVERIFIED:
                e.validation = ValidationStatus.CI_TEST_ONLY
            if pcorr < 0.05:
                e.identifiability = Identifiability.OBJECTIVELY_UNIDENTIFIABLE
            elif pvalue > 0.10:
                e.identifiability = Identifiability.DATA_LIMITED
            else:
                e.identifiability = Identifiability.DATA_SUFFICIENT

    def update_intervention(self, i: int, j: int, effect_size: float):
        """Record intervention-based evidence. Flags as verified."""
        self._round += 1
        for src, tgt, eff in [(i, j, effect_size), (j, i, -effect_size)]:
            e = self.edges[(src, tgt)]
            e.intervention_effect = abs(eff)
            e.evidence_sources.add("intervention")
            e.last_updated = self._round
            if abs(eff) > 0.3:
                e.validation = ValidationStatus.INTERVENTION_VERIFIED
                e.identifiability = Identifiability.DATA_SUFFICIENT
                e.presence_prob = 0.9
                e.direction_prob = 0.9 if eff > 0 else 0.1
            else:
                e.presence_prob = max(0.1, e.presence_prob - 0.2)

    def update_anm(self, i: int, j: int, score_fwd: float, score_rev: float):
        """Record ANM direction scores."""
        self._round += 1
        e_ij = self.edges[(i, j)]; e_ji = self.edges[(j, i)]
        e_ij.anm_score_forward = score_fwd; e_ij.anm_score_reverse = score_rev
        e_ji.anm_score_forward = score_rev; e_ji.anm_score_reverse = score_fwd
        for e in (e_ij, e_ji):
            e.evidence_sources.add("anm")
            e.last_updated = self._round
        if score_fwd > score_rev + 0.05:
            e_ij.direction_prob = 0.8; e_ji.direction_prob = 0.2
        elif score_rev > score_fwd + 0.05:
            e_ij.direction_prob = 0.2; e_ji.direction_prob = 0.8

    def update_temporal(self, i: int, j: int, i_before_j: bool):
        """Record temporal precedence evidence."""
        self._round += 1
        e_ij = self.edges[(i, j)]; e_ji = self.edges[(j, i)]
        for e in (e_ij, e_ji):
            e.evidence_sources.add("temporal")
            e.last_updated = self._round
        if i_before_j:
            e_ij.direction_prob = max(e_ij.direction_prob, 0.7)
            e_ji.direction_prob = min(e_ji.direction_prob, 0.3)
            e_ij.validation = ValidationStatus.TEMPORAL_CONFIRMED

    def update_llm(self, i: int, j: int, direction_i_to_j: bool):
        """Record LLM semantic knowledge (proposal only, not verification)."""
        self._round += 1
        e_ij = self.edges[(i, j)]; e_ji = self.edges[(j, i)]
        for e in (e_ij, e_ji):
            e.evidence_sources.add("llm")
            e.last_updated = self._round
        if direction_i_to_j:
            e_ij.direction_prob += 0.1; e_ji.direction_prob -= 0.1
            if e_ij.validation == ValidationStatus.UNVERIFIED:
                e_ij.validation = ValidationStatus.LLM_CONSISTENT
        e_ij.direction_prob = max(0.05, min(0.95, e_ij.direction_prob))
        e_ji.direction_prob = max(0.05, min(0.95, e_ji.direction_prob))

    def best_dag(self) -> frozenset[tuple[int, int]]:
        """Extract MAP DAG from uncertainty map."""
        edges = set()
        for i in range(self.n_nodes):
            for j in range(i + 1, self.n_nodes):
                p_ij = self.edges[(i, j)]
                p_ji = self.edges[(j, i)]
                if p_ij.presence_prob < 0.3 and p_ji.presence_prob < 0.3:
                    continue  # edge likely doesn't exist
                if p_ij.direction_prob > p_ji.direction_prob:
                    edges.add((i, j))
                else:
                    edges.add((j, i))
        return frozenset(edges)

    def edges_needing_evidence(self, min_presence: float = 0.3) -> list[tuple[int, int]]:
        """Return edges that need more evidence — for active intervention selection."""
        needy = []
        for i in range(self.n_nodes):
            for j in range(i + 1, self.n_nodes):
                e = self.edges[(i, j)]
                if e.identifiability == Identifiability.OBJECTIVELY_UNIDENTIFIABLE:
                    continue
                if e.presence_prob < 0.7 and e.validation != ValidationStatus.INTERVENTION_VERIFIED:
                    needy.append((i, j))
        needy.sort(key=lambda p: abs(self.edges[p].presence_prob - 0.5), reverse=True)
        return needy  # most uncertain first

    def edges_needing_llm(self) -> list[tuple[int, int]]:
        """Return edges that are objectively unidentifiable — LLM consultation candidates."""
        return [(i, j) for (i, j), e in self.edges.items()
                if i < j and e.identifiability == Identifiability.OBJECTIVELY_UNIDENTIFIABLE
                and e.presence_prob > 0.3]

    def global_confidence(self) -> dict:
        """Multi-dimensional confidence report — replaces scalar confidence."""
        all_edges = [(i, j) for i in range(self.n_nodes) for j in range(i + 1, self.n_nodes)]
        n = max(len(all_edges), 1)
        return {
            "n_data_sufficient": sum(1 for e in all_edges
                if self.edges[(0, 1)].identifiability == Identifiability.DATA_SUFFICIENT),
            "n_data_limited": sum(1 for e in all_edges
                if self.edges[e].identifiability == Identifiability.DATA_LIMITED),
            "n_objectively_unidentifiable": sum(1 for e in all_edges
                if self.edges[e].identifiability == Identifiability.OBJECTIVELY_UNIDENTIFIABLE),
            "n_intervention_verified": sum(1 for e in all_edges
                if self.edges[e].validation == ValidationStatus.INTERVENTION_VERIFIED),
            "n_needs_evidence": len(self.edges_needing_evidence()),
            "n_needs_llm": len(self.edges_needing_llm()),
            "mean_presence_prob": sum(self.edges[e].presence_prob for e in all_edges) / n,
        }
