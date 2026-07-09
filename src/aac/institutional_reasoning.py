"""Institutional Reasoning — LLM governance context + correction history + pattern inference.

Gives the LLM organ deeper context about the system's governance history:
- C7 correction patterns over time (which nodes blocked, why)
- Execution outcomes (which interventions worked, which failed)
- Goal formation history (which goals were set, achieved, abandoned)
- Reward/penalty patterns from human corrections

This enables the LLM to reason about "institutional knowledge" — the accumulated
wisdom from the system's operating history — rather than just the current DAG state.

Architecture:
    CorrectionLog → compressed history → build_context_prompt()
    ExecutionLog → outcome patterns → infer_preferences()
    GoalHistory → achieved goals → guide proposal generation

All works with the existing TextInterface and LLM backends.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CorrectionRecord:
    round_num: int
    node: int
    value: float
    action: str  # "ALLOW" | "DENY" | "ESCALATE"
    reason: str = ""
    timestamp: float = 0.0


@dataclass
class ExecutionRecord:
    round_num: int
    node: int
    value: float
    outcome: list[float]
    success: bool
    source: str = "simulator"


@dataclass
class InstitutionalContext:
    """Rich context for LLM institutional reasoning.

    Assembles the full governance state for the LLM to reason about,
    including correction history, execution log, goal history, and
    the current DAG state. This gives the LLM the context it needs to
    understand WHY certain interventions are blocked and WHAT patterns
    the principal is enforcing.
    """

    corrections: list[CorrectionRecord] = field(default_factory=list)
    executions: list[ExecutionRecord] = field(default_factory=list)
    goal_history: list[dict] = field(default_factory=list)
    blocked_nodes: set[int] = field(default_factory=set)
    approved_nodes: set[int] = field(default_factory=set)
    dag_state: Any = None
    variable_names: list[str] = field(default_factory=list)
    uncertainty: Any = None

    def record_correction(self, node: int, action: str, reason: str = ""):
        import time
        self.corrections.append(CorrectionRecord(
            round_num=len(self.corrections),
            node=node, value=0.0, action=action, reason=reason,
            timestamp=time.time(),
        ))
        if action == "DENY" and node not in self.blocked_nodes:
            self.blocked_nodes.add(node)

    def record_execution(self, node: int, value: float, outcome: list[float],
                         success: bool, source: str = "simulator"):
        self.executions.append(ExecutionRecord(
            round_num=len(self.executions),
            node=node, value=value, outcome=outcome,
            success=success, source=source,
        ))

    def record_goal(self, target: int, direction: str, achieved: bool):
        self.goal_history.append({
            "target": target, "direction": direction, "achieved": achieved,
            "round": len(self.goal_history),
        })

    def correction_pattern_summary(self) -> str:
        """Summarize correction patterns for LLM consumption."""
        if not self.corrections:
            return "No corrections recorded yet."
        total = len(self.corrections)
        denied = sum(1 for c in self.corrections if c.action == "DENY")
        allowed = sum(1 for c in self.corrections if c.action == "ALLOW")
        names = self.variable_names
        blocked = set()
        for c in self.corrections:
            if c.action == "DENY":
                name = names[c.node] if c.node < len(names) else f"V{c.node}"
                blocked.add(name)
        lines = [
            f"Correction history ({total} total): {allowed} allowed, {denied} denied.",
            f"Pattern: principal tends to {'DENY' if denied > allowed else 'ALLOW'} interventions.",
        ]
        if blocked:
            lines.append(f"Blocked targets: {', '.join(sorted(blocked))}")
        if self.corrections[-1:]:
            last = self.corrections[-1]
            name = names[last.node] if last.node < len(names) else f"V{last.node}"
            lines.append(f"Last correction: {last.action} on {name} (reason: {last.reason})")
        return "\n".join(lines)

    def execution_pattern_summary(self) -> str:
        """Summarize execution outcomes for LLM consumption."""
        if not self.executions:
            return "No executions recorded yet."
        total = len(self.executions)
        success = sum(1 for e in self.executions if e.success)
        names = self.variable_names
        lines = [f"Execution history ({total} total): {success} successful, {total - success} failed."]
        recent = self.executions[-5:]
        if recent:
            lines.append("Recent executions:")
            for e in recent:
                name = names[e.node] if e.node < len(names) else f"V{e.node}"
                outcome_str = f"[{', '.join(f'{x:.1f}' for x in e.outcome[:3])}...]" if e.outcome else "[]"
                lines.append(f"  do({name}={e.value}) → {outcome_str} ({'OK' if e.success else 'FAIL'})")
        return "\n".join(lines)

    def build_prompt(self, query: str, extra_context: str = "") -> str:
        """Build a rich institutional context prompt for LLM reasoning.

        The LLM sees: correction history + execution outcomes + DAG state +
        goal history + uncertainty map + the operator's current query.
        """
        parts = [
            "You are an IGI institutional reasoning assistant. You have access to:",
            "",
            "=== CORRECTION PATTERNS ===",
            self.correction_pattern_summary(),
            "",
            "=== EXECUTION OUTCOMES ===",
            self.execution_pattern_summary(),
        ]
        if self.goal_history:
            achieved = sum(1 for g in self.goal_history if g["achieved"])
            parts.append(f"\n=== GOAL HISTORY ===")
            parts.append(f"{len(self.goal_history)} goals set, {achieved} achieved.")
            for g in self.goal_history[-3:]:
                name = self.variable_names[g["target"]] if g["target"] < len(self.variable_names) else f"V{g['target']}"
                parts.append(f"  {g['direction']} {name}: {'achieved' if g['achieved'] else 'not achieved'}")

        if self.blocked_nodes:
            blocked_names = [self.variable_names[n] if n < len(self.variable_names) else f"V{n}" for n in self.blocked_nodes]
            parts.append(f"\n=== BLOCKED TARGETS ===")
            parts.append(f"Principal has blocked: {', '.join(blocked_names)}")

        if extra_context:
            parts.append(f"\n=== ADDITIONAL CONTEXT ===")
            parts.append(extra_context)

        parts.append(f"\n=== OPERATOR QUERY ===")
        parts.append(query)
        parts.append(f"\nBased on this institutional knowledge, provide a concise, well-reasoned response.")

        return "\n".join(parts)

    def infer_principal_preferences(self) -> dict:
        """Infer principal's implicit preferences from correction patterns.

        Returns preferences dict: {node: preference_score} where >0 = preferred, <0 = avoided.
        """
        prefs = {}
        for c in self.corrections:
            score = 1.0 if c.action == "ALLOW" else -1.0
            prefs[c.node] = prefs.get(c.node, 0.0) + score
        return {k: round(v, 1) for k, v in sorted(prefs.items(), key=lambda x: x[1])}

    def get_bias_explanation(self) -> str:
        """Human-readable explanation of WHY each node is favored/avoided."""
        prefs = self.infer_principal_preferences()
        names = self.variable_names
        lines = ["=== Organ Decision Bias Report ===", ""]
        lines.append("The organ uses statistical patterns from correction history to prioritize proposals.")
        lines.append("This is normal environmental adaptation, NOT SD4-Shadow. The organ learns")
        lines.append("P(DENY|node) from OBSERVABLE history — the same as it learns P(success|intervention).")
        lines.append("")
        lines.append("Current bias per target:")
        for node, score in prefs.items():
            name = names[node] if node < len(names) else f"V{node}"
            deny_count = sum(1 for c in self.corrections if c.node == node and c.action == "DENY")
            allow_count = sum(1 for c in self.corrections if c.node == node and c.action == "ALLOW")
            status = "FAVORED" if score > 0 else ("AVOIDED" if score < 0 else "NEUTRAL")
            lines.append(f"  {name}: {status} (score={score:+.1f}, {allow_count}✓/{deny_count}✗)")
        lines.append("")
        lines.append("To override: use BiasOverride.reconsider(node) to mark a target for")
        lines.append("re-evaluation despite its historical DENY pattern.")
        return "\n".join(lines)


class BiasOverride:
    """Operator tool to override learned organ biases.

    If the organ learned (correctly) that the principal DENY's node X,
    but the operator believes node X SHOULD be reconsidered (perhaps with
    new evidence or a different context), this marks X for re-evaluation.

    The organ still proposes X, but the disposer C7 still has final say.
    The override only affects the organ's proposal PRIORITY, not the gate.
    """

    def __init__(self):
        self._reconsider: set[int] = set()
        self._override_reasons: dict[int, str] = {}

    def reconsider(self, node: int, reason: str = ""):
        """Mark a node for re-evaluation despite denial history."""
        self._reconsider.add(node)
        if reason:
            self._override_reasons[node] = reason

    def should_propose(self, node: int) -> tuple[bool, str]:
        """Check if node should be proposed despite bias."""
        if node in self._reconsider:
            return (True, self._override_reasons.get(node, "operator override"))
        return (True, "")

    def bias_adjusted_score(self, node: int, base_score: float,
                            denial_count: int, allow_count: int) -> float:
        """Compute bias-adjusted proposal score. Override boosts score by 50%."""
        if node in self._reconsider:
            return base_score * 1.5
        return base_score
