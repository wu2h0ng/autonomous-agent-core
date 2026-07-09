"""User Intent Parser — LLM-based NL → structured causal goal.

Maps natural language user queries ("maximize profit", "how do I increase sales?")
to structured goals in the discovered DAG's variable space.

The LLM is a PROPOSER only — its output is a candidate goal that must be verified
against the actual DAG (does the target node exist? does it have intervenable
ancestors?). If verification fails, the system honestly reports "cannot execute
this goal" rather than silently mapping to a wrong node.

Architecture:
    User query → LLM proposes {target_node, direction} 
    → verify against DAG (target exists, has ancestors)
    → RecursiveGoalFormation.decompose()
    → executable leaves → ExecutionBridge

Usage:
    parser = UserIntentParser(llm_backend, variable_names=["price","discount",...])
    goal = parser.parse("increase sales", dag, obs)
    if goal.verified:
        tree = organ.decompose(dag, obs, goal.target, goal.direction)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedGoal:
    target: int
    direction: str       # "maximize" | "minimize" | "stabilize"
    confidence: float    # LLM's confidence in this mapping
    verified: bool       # True if target exists in DAG AND has intervenable ancestors
    reason: str = ""     # explanation if unverified


class UserIntentParser:
    """LLM-based natural language → causal goal parser.

    Args:
        backend: LLM backend (LLMAPIBackend, DeterministicStubBackend, etc.).
        variable_names: human-readable names of variables in the DAG.
        intervenable_nodes: which nodes can be acted upon.
    """

    def __init__(
        self, backend: Any, variable_names: list[str],
        intervenable_nodes: set[int] | None = None,
    ):
        self.backend = backend
        self.names = variable_names
        self.intervenable = intervenable_nodes or set(range(len(variable_names)))

    def parse(
        self, query: str, dag: frozenset[tuple[int, int]], obs: list[list[float]],
    ) -> ParsedGoal:
        """Parse user NL query into a verified causal goal.

        Args:
            query: user's natural language query.
            dag: discovered causal DAG.
            obs: observational data for ancestor verification.

        Returns:
            ParsedGoal with verified=True if the goal is executable.
        """
        proposed = self._llm_propose(query)
        target = proposed.get("target", -1)
        direction = proposed.get("direction", "maximize")
        confidence = proposed.get("confidence", 0.0)

        verified, reason = self._verify(target, direction, dag, obs)
        return ParsedGoal(
            target=target, direction=direction,
            confidence=confidence, verified=verified, reason=reason,
        )

    def _llm_propose(self, query: str) -> dict:
        prompt = (
            f"Given these variables: {', '.join(f'{i}:{n}' for i,n in enumerate(self.names))}\n"
            f"User asks: \"{query}\"\n"
            f"Which variable should be the TARGET? Which DIRECTION (maximize/minimize/stabilize)?\n"
            f"Return ONLY JSON: {{\"target\": int, \"direction\": \"maximize\", \"confidence\": 0.8}}"
        )
        try:
            raw = self.backend.propose(prompt)
            if isinstance(raw, dict) and "target" in raw:
                return {"target": int(raw["target"]), "direction": str(raw.get("direction", "maximize")),
                        "confidence": float(raw.get("confidence", 0.5))}
            if isinstance(raw, str):
                content = raw.strip()
                if content.startswith("```"): content = content.split("```")[1]
                if content.startswith("json"): content = content[4:]
                d = json.loads(content)
                return {"target": int(d.get("target", -1)), "direction": str(d.get("direction", "maximize")),
                        "confidence": float(d.get("confidence", 0.5))}
        except Exception:
            pass
        return {"target": -1, "direction": "maximize", "confidence": 0.0}

    def _verify(self, target, direction, dag, obs):
        n = len(obs[0])
        if target < 0 or target >= n:
            return False, f"target node {target} out of range [0,{n-1}]"
        from .goal_formation import RecursiveGoalFormation
        ancestors = RecursiveGoalFormation._transitive_ancestors(
            RecursiveGoalFormation.__new__(RecursiveGoalFormation), dag, n,
        )
        intervenable_ancestors = ancestors[target] & self.intervenable
        if not intervenable_ancestors:
            return False, f"target node {target} has no intervenable ancestors"
        return True, f"verified: {len(intervenable_ancestors)} intervenable ancestors"
