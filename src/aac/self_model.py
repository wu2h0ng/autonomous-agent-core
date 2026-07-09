"""AgentSelfModel — the consolidated capability / risk / boundary self-knowledge (REF-ARCH-03 §1).

Today this knowledge is scattered across ViabilityCore (self-state), PolicySelector (choice),
and the CorrigibilityShell (risk boundary). REF-ARCH-01 §6 lists a consolidated AgentSelfModel as
the #1 missing piece for safety: it is what turns "can call a tool" into "knows when NOT to".

It is read by the GovernedDecisionGate (governed_gate.py) — it holds the boundary parameters;
the gate applies the ADR-0048 stakes-keyed trilemma. The self model never executes anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ActionRequest:
    """A proposed action presented to the gate for a verdict (REF-ARCH-04 §3)."""

    action: str          # tool/action id (e.g. "apply_lever:3")
    risk_tier: int       # R0..R5
    confidence: float    # the loop's own confidence in this action, [0, 1]
    verified: bool       # has the action's effect been VERIFIED (intervention / OutcomeJudge)?
    evidence_count: int  # number of bound evidence refs
    approved: bool = False  # has a human approved it (for tiers that require approval)?
    action_index: Optional[int] = None  # the action's integer index, checked against shell.forbidden


@dataclass
class AgentSelfModel:
    """What the agent may do, must not do, and when it must stop / escalate.

    - allowed_tools / denied_tools: the capability boundary. denied wins.
    - risk_ceiling: the highest risk tier the agent may EVER act on (above => never act, escalate).
    - approval_required_at_or_above: tiers at/above this are HIGH STAKES (need human approval).
    - evidence_requirements[tier]: minimum bound evidence to act at that tier.
    - confidence_thresholds[tier]: minimum confidence to act at that tier.
    """

    allowed_tools: frozenset[str]
    denied_tools: frozenset[str]
    risk_ceiling: int
    approval_required_at_or_above: int
    evidence_requirements: dict[int, int] = field(default_factory=dict)
    confidence_thresholds: dict[int, float] = field(default_factory=dict)

    def permits_tool(self, action: str) -> bool:
        """A tool is permitted iff it is not denied AND (allowed-set empty OR explicitly allowed).

        denied always wins; an explicit allowed-set is a whitelist (deny-by-default)."""
        if action in self.denied_tools:
            return False
        if self.allowed_tools and action not in self.allowed_tools:
            return False
        return True

    def is_high_stakes(self, risk_tier: int) -> bool:
        return risk_tier >= self.approval_required_at_or_above

    def above_ceiling(self, risk_tier: int) -> bool:
        return risk_tier > self.risk_ceiling

    def required_evidence(self, risk_tier: int) -> int:
        return self.evidence_requirements.get(risk_tier, 0)

    def required_confidence(self, risk_tier: int) -> float:
        return self.confidence_thresholds.get(risk_tier, 0.0)

    def apply_updates(self, deltas: dict) -> int:
        """Apply runtime calibration deltas from AgentSelfModelUpdater.

        Returns the number of fields changed. Only confidence_thresholds and
        evidence_requirements are updated — the capability boundary (allowed/
        denied tools) and authority boundary (risk_ceiling, approval tier)
        are NEVER modified by runtime updates. C7 authority remains operator-only.
        """
        changes = 0
        for tier, threshold in deltas.get("confidence_thresholds", {}).items():
            if isinstance(tier, int) and isinstance(threshold, (int, float)):
                if 0.0 <= threshold <= 1.0:
                    self.confidence_thresholds[tier] = float(threshold)
                    changes += 1
        for tier, delta in deltas.get("evidence_requirements", {}).items():
            if isinstance(tier, int) and isinstance(delta, int):
                current = self.evidence_requirements.get(tier, 0)
                new_value = max(0, current + delta)
                self.evidence_requirements[tier] = new_value
                changes += 1
        return changes
