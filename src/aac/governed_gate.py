"""GovernedDecisionGate — the ADR-0048 verify-or-escalate trilemma as a first-class component.

PolicySelector chooses WHICH action; this gate decides WHETHER to act on it / verify more /
escalate / deny — keyed by STAKES (REF-ARCH-04 §3). It is the operational form of the session's
load-bearing result: {correctness, autonomy, efficiency} cannot all be maxed, so the operating
point is set by risk tier.

- High stakes (>= approval tier, R4/R5-like): NEVER act on unverified output (ADR-0047 hole).
  Verified-but-unapproved -> escalate for approval. Below-threshold confidence -> escalate.
- Low stakes: calibrated trust — act when verified or (confident AND the LLM organ has earned
  trust); otherwise verify more / escalate. Never silently trust unverified output (the broken
  FIXED policy from ADR-0048).

It reads the AgentSelfModel (boundary) and, when given, respects the CorrigibilityShell view (C7):
a paused shell or a forbidden action can only tighten the verdict, never loosen it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .self_model import AgentSelfModel, ActionRequest

ALLOW = "ALLOW"
VERIFY_MORE = "VERIFY_MORE"
ESCALATE = "ESCALATE"
DENY = "DENY"

# Below this calibrated LLM reliability, an unverified low-stakes action cannot be trusted
# (ADR-0048: trusting an unreliable organ's unverified output is the failure mode).
_RELIABILITY_TRUST_FLOOR = 0.7


@dataclass(frozen=True)
class GateDecision:
    verdict: str
    reason: str


@dataclass
class GovernedDecisionGate:
    self_model: AgentSelfModel

    def decide(
        self,
        request: ActionRequest,
        shell_view: Optional[Any] = None,
        llm_reliability: Optional[float] = None,
    ) -> GateDecision:
        sm = self.self_model

        # --- 1. hard capability boundary (denied / not-allowed) -> DENY ---
        if not sm.permits_tool(request.action):
            return GateDecision(DENY, f"tool '{request.action}' not permitted by self model")

        # --- 2. corrigibility shell (C7) can only TIGHTEN ---
        if shell_view is not None:
            if getattr(shell_view, "paused", False):
                return GateDecision(DENY, "corrigibility shell is paused")
            # the shell forbids by integer action index; honor it if the request carries one
            forbidden = getattr(shell_view, "forbidden", frozenset())
            if request.risk_tier in forbidden:  # defensive: never loosen on shell signal
                return GateDecision(DENY, "action forbidden by corrigibility shell")

        # --- 3. above the risk ceiling -> never act ---
        if sm.above_ceiling(request.risk_tier):
            return GateDecision(ESCALATE, f"risk tier {request.risk_tier} above ceiling {sm.risk_ceiling}")

        # --- 4. insufficient evidence -> verify more (or escalate at high stakes) ---
        if request.evidence_count < sm.required_evidence(request.risk_tier):
            if sm.is_high_stakes(request.risk_tier):
                return GateDecision(ESCALATE, "high-stakes action lacks required evidence")
            return GateDecision(VERIFY_MORE, "evidence below requirement for tier")

        # --- 5. HIGH STAKES: never trust unverified; require approval ---
        if sm.is_high_stakes(request.risk_tier):
            if not request.verified:
                return GateDecision(ESCALATE, "high-stakes action is unverified (never trust unverified)")
            if request.confidence < sm.required_confidence(request.risk_tier):
                return GateDecision(ESCALATE, "high-stakes confidence below threshold")
            if not request.approved:
                return GateDecision(ESCALATE, "high-stakes action requires human approval")
            return GateDecision(ALLOW, "high-stakes: verified, confident, approved")

        # --- 6. LOW STAKES: calibrated trust ---
        meets_conf = request.confidence >= sm.required_confidence(request.risk_tier)
        if request.verified and meets_conf:
            return GateDecision(ALLOW, "low-stakes: verified and confident")
        if not meets_conf:
            return GateDecision(VERIFY_MORE, "low-stakes: confidence below threshold")
        # confident but UNVERIFIED -> only trust if the LLM organ has earned it
        if llm_reliability is not None and llm_reliability >= _RELIABILITY_TRUST_FLOOR:
            return GateDecision(ALLOW, "low-stakes: confident + calibrated-reliable organ")
        return GateDecision(ESCALATE, "low-stakes: confident but unverified and organ not calibrated-reliable")
