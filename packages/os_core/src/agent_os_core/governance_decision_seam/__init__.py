"""Governed-decision injection seam — OS-side client (RR-0032, R0–R3 wire).

The OS Trusted Loop calls an injected GovernanceDecisionClient at the governance gate; the client can
only TIGHTEN the decision (DENY -> block; ESCALATE/VERIFY_MORE -> force approval), never loosen. This
keeps the OS the subject loop while consuming the external governed brain's verdict.

#19 / RR-0032: the production client is a thin RPC stub to the remote autonomous-agent-core service; it
imports NO core code. LocalGovernanceDecisionClient is a NATIVE reference implementation of the contract
(the five invariants) for dev + acceptance tests — it does not import the core either; both sides
implement the shared versioned spec independently.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from agent_os_contracts.governance_decision_seam import (
    GovernanceDecisionRequest, GovernanceDecisionResponse,
    SEAM_CONTRACT_VERSION, ALLOW, VERIFY_MORE, ESCALATE, DENY,
    request_to_json, response_from_json,
)

_RISK_ORDER = {f"R{i}": i for i in range(6)}


class CohortABVerifier(ABC):
    """Interventional verifier: did a bounded cohort A/B test confirm the action moves the metric?

    Returns (is_effective, confidence, evidence_count). The OS owns the test; the seam owns the
    verdict. Async tests surface as is_effective=False with confidence 0 -> VERIFY_MORE upstream."""

    @abstractmethod
    def verify(self, action: str) -> tuple[bool, float, int]:
        ...


class GovernanceDecisionClient(ABC):
    @abstractmethod
    def decide(self, request: GovernanceDecisionRequest) -> GovernanceDecisionResponse:
        ...


def _audit_ref(req: GovernanceDecisionRequest, verdict: str, chosen: Optional[str], reason: str) -> str:
    blob = f"{req.task_id}|{verdict}|{chosen}|{reason}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class LocalGovernanceDecisionClient(GovernanceDecisionClient):
    """Native reference implementation of the seam — the five invariants (RR-0032).

    1) act only on a VERIFIED candidate; 2) high-stakes (>= approval tier) never auto-allowed ->
    escalate; 3) C7: a paused shell_view can only DENY; 4) deterministic (no LLM in the control path);
    5) every response carries a resolving audit_ref."""

    def __init__(
        self,
        verifier: CohortABVerifier,
        *,
        approval_required_at_or_above: str = "R4",
        confidence_floor: float = 0.2,
        shell_view: Any | None = None,
    ) -> None:
        self.verifier = verifier
        self.approval_tier = _RISK_ORDER[approval_required_at_or_above]
        self.confidence_floor = confidence_floor
        self.shell_view = shell_view

    def _resp(self, req, verdict, chosen, conf, reason) -> GovernanceDecisionResponse:
        if self.shell_view is not None:
            self.shell_view.observe({"event": "governed_decision", "task_id": req.task_id, "verdict": verdict})
        return GovernanceDecisionResponse(
            req.task_id, verdict, chosen, conf, reason, _audit_ref(req, verdict, chosen, reason))

    def decide(self, req: GovernanceDecisionRequest) -> GovernanceDecisionResponse:
        # invariant: contract version
        if req.contract_version.split(".")[0] != SEAM_CONTRACT_VERSION.split(".")[0]:
            return self._resp(req, DENY, None, 0.0, f"incompatible contract version {req.contract_version}")
        # invariant 3: C7 supremacy — a paused operator shell can only tighten
        if self.shell_view is not None and getattr(self.shell_view, "paused", False):
            return self._resp(req, DENY, None, 0.0, "corrigibility shell paused")

        tier = _RISK_ORDER.get(req.risk_tier, 5)
        high_stakes = tier >= self.approval_tier

        for action in req.candidate_actions:
            effective, conf, _ev = self.verifier.verify(action)
            if not effective:
                continue                                   # invariant 1: never act on unverified
            # verified-effective candidate found
            if high_stakes:                                # invariant 2: high-stakes never auto-allowed
                if not req.approved:
                    return self._resp(req, ESCALATE, None, conf, "high-stakes action requires approval")
                if conf < self.confidence_floor:
                    return self._resp(req, ESCALATE, None, conf, "high-stakes confidence below floor")
                return self._resp(req, ALLOW, action, conf, "high-stakes: verified, confident, approved")
            if conf < self.confidence_floor:
                return self._resp(req, VERIFY_MORE, None, conf, "confidence below floor")
            return self._resp(req, ALLOW, action, conf, "low-stakes: verified and confident")

        return self._resp(req, ESCALATE, None, 0.0, "no verified-effective candidate")  # never silently act


class RemoteGovernanceDecisionClient(GovernanceDecisionClient):
    """RPC boundary stub: serialize the request for the remote autonomous-agent-core governed-decision
    service, parse the response. The transport is injected (e.g. an HTTP POST). #19: no core import.
    With no transport configured this raises — the remote service is not wired in this repo."""

    def __init__(self, transport: Optional[Callable[[str], str]] = None) -> None:
        self.transport = transport

    def decide(self, request: GovernanceDecisionRequest) -> GovernanceDecisionResponse:
        if self.transport is None:
            raise NotImplementedError(
                "remote governed-decision transport not configured (no autonomous-agent-core service wired)")
        return response_from_json(self.transport(request_to_json(request)))
