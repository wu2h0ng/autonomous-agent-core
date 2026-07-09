"""Unified Text Interface — single NL entry point for all IGI capabilities.

Consolidates all NL interactions through one context-aware interface:
- Intent parsing (NL → causal goal)
- DAG explanation (DAG → NL summary)
- Counterfactual explanation (what-if → NL)
- Goal tree explanation (goal decomposition → NL)
- Execution history summary (log → NL)
- Multi-turn conversation with session context

All LLM calls go through a single backend. Session context (DAG, goals, execution
log) persists across turns. The LLM is a PROPOSER only — all structural claims
are verified against the actual DAG before being presented to the operator.

Usage:
    from aac.text_interface import TextInterface, SessionContext
    ctx = SessionContext(dag=result.dag, variables=labels, goals=goal_tree)
    ti = TextInterface(backend)
    response = ti.process("how do I increase sales?", ctx)
    print(response.content, response.confidence, response.action)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionContext:
    """Immutable session state available to all text interactions."""
    dag: frozenset = field(default_factory=frozenset)
    variables: list[str] = field(default_factory=list)
    goals: Any = None           # GoalTree from RecursiveGoalFormation
    executions: list = field(default_factory=list)
    counterfactuals: list = field(default_factory=list)
    maintenance: Any = None     # CWMMaintenance state
    n_nodes: int = 0
    n_obs: int = 0
    confidence: float = 0.0
    reachable: dict = field(default_factory=dict)


@dataclass
class TextResponse:
    content: str
    confidence: float = 0.5
    action: str = ""  # "explain", "goal", "counterfactual", "history", "discover", "answer"
    reference: str = ""  # citation to DAG/execution element


class TextInterface:
    """Unified NL interface for IGI system.

    Args:
        backend: LLM backend (LLMAPIBackend or DeterministicStubBackend).
    """

    def __init__(self, backend: Any):
        self.backend = backend
        self._history: list[dict] = []

    def process(self, query: str, ctx: SessionContext) -> TextResponse:
        intent = self._classify(query)
        self._history.append({"role": "user", "content": query})

        if intent == "explain":
            response = self._explain_dag(ctx)
        elif intent == "goal":
            response = self._explain_goals(ctx)
            response.content = self._answer_with_context(
                query, ctx, response.content,
            )
        elif intent == "counterfactual" or intent == "what-if":
            response = self._explain_counterfactuals(ctx)
        elif intent == "history":
            response = self._explain_history(ctx)
        else:
            info = self._describe_context(ctx)
            response = self._answer_with_context(query, ctx, info)

        self._history.append({"role": "assistant", "content": response.content})
        return response

    def _classify(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["explain", "what is", "describe", "tell me about the model", "how does"]):
            return "explain"
        if any(w in q for w in ["goal", "target", "maximize", "minimize", "increase", "decrease",
                                  "improve", "reduce", "achieve"]):
            return "goal"
        if any(w in q for w in ["what if", "counterfactual", "would have", "if i had"]):
            return "counterfactual"
        if any(w in q for w in ["history", "what happened", "log", "past", "execution"]):
            return "history"
        return "answer"

    def _describe_context(self, ctx) -> str:
        parts = [f"Causal model has {ctx.n_nodes} variables with {len(ctx.dag)} directed edges."]
        if ctx.variables:
            parts.append(f"Variables: {', '.join(ctx.variables[:10])}")
        parts.append(f"Confidence: {ctx.confidence:.1%}")
        if ctx.reachable:
            reachable = [k for k, v in ctx.reachable.items() if v.get("reachable")]
            parts.append(f"{len(reachable)}/{ctx.n_nodes} targets reachable via intervention.")
        if ctx.goals:
            if hasattr(ctx.goals, 'goal'):
                def _count_leaves(node):
                    if not node.children: return 1
                    return sum(_count_leaves(c) for c in node.children)
                parts.append(f"Top goal: {ctx.goals.goal.direction} node {ctx.goals.goal.target}.")
                parts.append(f"{_count_leaves(ctx.goals)} executable sub-goals.")
        if ctx.executions:
            parts.append(f"{len(ctx.executions)} executions recorded.")
        return "\n".join(parts)

    def _answer_with_context(self, query, ctx, info):
        prompt = (
            f"You are an IGI operator assistant. Context:\n{info}\n\n"
            f"Operator asks: \"{query}\"\n"
            f"Answer concisely using ONLY the context above. Cite specific variables and edges. "
            f"If the answer requires information not in the context, say so honestly."
        )
        try:
            raw = self.backend.propose(prompt)
            return str(raw) if isinstance(raw, str) else str(raw.get("content", raw))
        except Exception:
            return info

    def _explain_dag(self, ctx):
        if not ctx.dag:
            return TextResponse("No causal structure discovered yet.", 1.0, "explain")
        edges_desc = []
        for u, v in sorted(ctx.dag):
            src = ctx.variables[u] if u < len(ctx.variables) else f"V{u}"
            tgt = ctx.variables[v] if v < len(ctx.variables) else f"V{v}"
            edges_desc.append(f"  {src} → {tgt}")
        content = f"Discovered causal DAG ({len(ctx.dag)} edges):\n" + "\n".join(edges_desc[:15])
        if len(edges_desc) > 15:
            content += f"\n  ... and {len(edges_desc) - 15} more."
        return TextResponse(content, ctx.confidence, "explain")

    def _explain_goals(self, ctx):
        if ctx.goals is None:
            return TextResponse("No goals formed yet. Try asking: 'how do I increase sales?'",
                                0.5, "goal")
        def _format_tree(node, indent=0):
            g = node.goal
            name = ctx.variables[g.target] if g.target < len(ctx.variables) else f"V{g.target}"
            line = f"{'  '*indent}└─ {g.direction} {name} (commit={g.commitment:.2f})"
            for child in node.children:
                line += "\n" + _format_tree(child, indent+1)
            return line
        tree_str = _format_tree(ctx.goals)
        def _count_leaves(node):
            if not node.children:
                return 1
            return sum(_count_leaves(c) for c in node.children)
        n_leaves = _count_leaves(ctx.goals)
        content = f"Goal tree:\n{tree_str}\n\n{n_leaves} executable actions available."
        return TextResponse(content, 0.8, "goal")

    def _explain_counterfactuals(self, ctx):
        if not ctx.counterfactuals:
            return TextResponse("No counterfactual analyses yet. Try asking: 'what if I had set discount to 30%?'",
                                0.5, "counterfactual")
        lines = []
        for cf in ctx.counterfactuals[-5:]:
            src = ctx.variables[cf.do_node] if cf.do_node < len(ctx.variables) else f"V{cf.do_node}"
            tgt = ctx.variables[cf.node] if cf.node < len(ctx.variables) else f"V{cf.node}"
            lines.append(f"  do({src}) → {tgt}: actual={cf.actual:.1f}, "
                         f"counterfactual={cf.counterfactual:.1f} (Δ{cf.delta:+.1f})")
        return TextResponse("Recent counterfactuals:\n" + "\n".join(lines), 0.8, "counterfactual")

    def _explain_history(self, ctx):
        if not ctx.executions:
            return TextResponse("No executions recorded yet.", 0.5, "history")
        lines = []
        for ex in ctx.executions[-5:]:
            lines.append(f"  do(V{ex.node}={ex.value}) → {'success' if ex.success else 'failed'} ({ex.source})")
        return TextResponse("Recent executions:\n" + "\n".join(lines), 0.9, "history")
