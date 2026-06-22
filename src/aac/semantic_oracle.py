"""Offline semantic oracle backend (G6b de-risking, ADR-0019 §2/§5).

This is a deterministic, zero-spend STAND-IN for a semantic LLM: it brings
perfect word-knowledge (the same TAXONOMY the env uses) and reads the action
labels out of the prompt the same way a real LLM would. Its purpose is to prove,
BEFORE spending a cent, that :class:`SemanticRegimeEnv` is exploitable by
semantic knowledge — i.e. an organ that understands the labels recognises the
best action zero-shot, where a numeric learner cannot.

It is NOT the G6b result. A real LLM has imperfect, general knowledge; whether
that suffices is the paid run (ADR-0019 §5). This oracle is the upper bound:
"if the organ knew the words, would the env reward it?" — and it lets the whole
LLMPriorOrgan pipeline + C6/C7 guarantees be exercised on a semantic env offline.

The oracle is a plain ``LLMBackend``: its output flows through the SAME untrusted
strict parser as a real LLM, so it has no more authority than any other backend.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Mapping

from envs.semantic_regime import TAXONOMY


def _parse_prompt(prompt: str) -> tuple[str | None, list[str], tuple[float, ...]]:
    category: str | None = None
    labels: list[str] = []
    mu: tuple[float, ...] = ()
    for part in prompt.split(" | "):
        if part.startswith("category="):
            category = part[len("category=") :].strip() or None
        elif part.startswith("actions="):
            for tok in part[len("actions=") :].split():
                idx, _, lab = tok.partition(":")
                if idx.isdigit():
                    while len(labels) <= int(idx):
                        labels.append("")
                    labels[int(idx)] = lab
        elif part.startswith("mu="):
            try:
                val = ast.literal_eval(part[len("mu=") :].strip())
                mu = tuple(float(x) for x in val)
            except (ValueError, SyntaxError, TypeError):
                mu = ()
    return category, labels, mu


@dataclass
class SemanticOracleBackend:
    """Perfect-knowledge stand-in for a semantic LLM. Belief proposal only."""

    knowledge: Mapping[str, tuple[str, ...]] = None  # type: ignore[assignment]
    high_target: float = 5.0  # where a member action's mu should sit
    low_target: float = -1.0  # where a non-member action's mu should sit
    confidence: float = 0.9

    def __post_init__(self) -> None:
        if self.knowledge is None:
            self.knowledge = TAXONOMY

    def propose(self, prompt: str) -> Mapping[str, Any]:
        category, labels, mu = _parse_prompt(prompt)
        if category is None or not labels or category not in self.knowledge:
            return {"belief_delta": {}, "uncertainty": 0.0}
        members = set(self.knowledge[category])
        # Set each action toward its semantically-correct level (member high,
        # others low). Deltas are RELATIVE to the current mu so they don't run
        # away across shifts: a stale-high action gets pulled back down, the new
        # best gets pushed up — one-step, zero-shot, bounded. The /confidence
        # cancels merge's *uncertainty weight so the post-merge mu lands on target.
        delta: dict[int, float] = {}
        for i, lab in enumerate(labels):
            target = self.high_target if lab in members else self.low_target
            cur = mu[i] if i < len(mu) else 0.0
            delta[i] = (target - cur) / self.confidence
        return {"belief_delta": delta, "uncertainty": self.confidence}
