"""Language Orientation Organ — LLM-based causal edge direction proposal.

Wraps the existing LLMPriorOrgan infrastructure (prior_organ_llm.py) to produce
causal orientation proposals instead of action beliefs. Implements the CWMOrgan
protocol so it can be plugged into GovernedDiscoveryLoop alongside data skeleton
organs (LinearGGMOrgan, PolynomialOrgan).

This is the RR-0046 §27 pattern: data organ proposes skeleton, language organ
proposes orientation, intervention verification confirms. Composition of organs
achieves what neither can alone — especially in nonlinear domains where pure
data orientation is 0/k (saturation makes all directions look equivalent).

Safety (inherited from LLMPriorOrgan):
- LLM output is UNTRUSTED and strictly parsed — only orientation proposals survive
- No action/policy/shell/gate channel can be smuggled through the LLM
- DeterministicStubBackend for offline, zero-spend testing
- Real LLM requires founder key/budget (ADR-0019 §5)

Usage:
    from aac.language_orientation_organ import LanguageOrientationOrgan
    from aac.prior_organ_llm import DeterministicStubBackend
    backend = DeterministicStubBackend()
    organ = LanguageOrientationOrgan(backend, variable_labels)
    proposals = organ.propose_orientation(skeleton_edges)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .prior_organ_llm import LLMBackend, DeterministicStubBackend, _safe_belief_delta, _safe_uncertainty
from .cwm_organ import StructureProposal, CWMOrgan


@dataclass
class LanguageOrientationOrgan(CWMOrgan):
    """CWM organ that proposes causal edge directions from variable semantics.

    Takes an undirected skeleton + variable labels, queries the LLM backend
    for causal direction knowledge, and returns directed edge proposals.
    Inherits all safety guarantees from LLMPriorOrgan (strict parsing,
    no action/policy/shell surface).
    """

    backend: LLMBackend
    variable_labels: list[str]

    def _build_prompt(
        self, skeleton: frozenset, labels: list[str],
    ) -> str:
        parts = ["You are a causal reasoning module. Given the following variables and undirected edges, propose the causal direction for each edge."]
        parts.append(f"Variables ({len(labels)}): " + ", ".join(f"{i}:{lab}" for i, lab in enumerate(labels)))
        edge_descs = []
        for undir in skeleton:
            parts_list = list(undir)
            if len(parts_list) == 2:
                i, j = parts_list
                edge_descs.append(f"  ({i}:{labels[i]}) -- ({j}:{labels[j]})")
        if edge_descs:
            parts.append("Undirected edges:\n" + "\n".join(edge_descs))
        parts.append("For each edge, return: edge=(i,j) direction=i→j or j→i score=0.0-1.0")
        return " | ".join(parts)

    def _parse_orientations(
        self, raw: Any, skeleton: frozenset, n_nodes: int,
    ) -> list[StructureProposal]:
        proposals = []
        if not isinstance(raw, Mapping):
            return proposals
        orientations = raw.get("orientations")
        if not isinstance(orientations, list):
            return proposals
        for item in orientations:
            if not isinstance(item, Mapping):
                continue
            try:
                i = int(item.get("i", -1))
                j = int(item.get("j", -1))
                direction = str(item.get("direction", ""))
                score = float(item.get("score", 0.5))
            except (TypeError, ValueError):
                continue
            if not (0 <= i < n_nodes and 0 <= j < n_nodes):
                continue
            if i == j:
                continue
            if frozenset({i, j}) not in skeleton:
                continue
            directed = frozenset({(i, j) if direction == f"{i}→{j}" else (j, i)})
            proposals.append(StructureProposal(
                edges=directed,
                score=min(1.0, max(0.0, score)),
                is_directed=True,
                provenance="LanguageOrientation",
            ))
        return proposals

    def propose_orientation(self, skeleton: frozenset) -> list[StructureProposal]:
        n = len(self.variable_labels)
        prompt = self._build_prompt(skeleton, self.variable_labels)
        raw = self.backend.propose(prompt)
        return self._parse_orientations(raw, skeleton, n)


@dataclass
class ChainStubBackend:
    """Stub LLM backend that always proposes i→j direction (chain forward).

    Simulates an LLM that knows the causal chain goes from node 0→1→2→...→n-1.
    Used for offline, zero-spend testing of the language orientation organ
    on causal chain domains where the true direction is known.

    This is the RR-0046 §27 setup: the language organ knows the causal direction
    from variable semantics, and the intervention verifier confirms it.
    """

    confidence: float = 0.85

    def propose(self, prompt: str) -> Mapping[str, Any]:
        orientations = []
        for line in prompt.split("\n"):
            line = line.strip()
            if line.startswith("(") and ") -- (" in line:
                try:
                    i_str = line.split(":")[0].split("(")[1].strip()
                    j_str = line.split(":")[0].split("(")[1].strip() if "(" in line.split("--")[0] else ""
                    parts_first = line.split("--")[0].strip()
                    parts_second = line.split("--")[1].strip()
                    i = int(parts_first.split(":")[0].replace("(", "").strip())
                    j = int(parts_second.split(":")[0].replace("(", "").strip())
                    if i < j:
                        direction = f"{i}→{j}"
                    else:
                        direction = f"{j}→{i}"
                    orientations.append({
                        "i": min(i, j), "j": max(i, j),
                        "direction": direction, "score": self.confidence,
                    })
                except (ValueError, IndexError):
                    continue
        return {"orientations": orientations}
