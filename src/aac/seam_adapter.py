"""SeamAdapter — the research-side half of the RR-0032 governance seam (CONTRACT, not import).

Boundary #19: no cross-repo imports. This replicates the OS seam CONTRACT SHAPE by value (field names
matching agent_os_contracts.governance_decision_seam v1.1.0) and a tighten-only reference verdict that
must AGREE with the OS product brain on the shared conformance vectors. It lets the E2E discovery agent's
governed action cross to OS governance over JSON — proving seam-READINESS on the research side. The actual
OS-runtime execution of a real R0-R3 lever + any push/release remains founder-keyed.

Tighten-only invariants (RR-0032 cast; the seam may only tighten, never loosen the OS's own decision):
  1. verified-only: an unverified candidate can never ACT (-> approval).
  2. >= approval tier (R4/R5): never act on unverified; verified-but-unapproved -> ESCALATE.
  3. C7 paused / forbidden action -> DENY (block), overrides everything.
  4. deterministic + contentless: verdict is a pure function of (tier, verified, confidence, evidence).
  5. floors: below confidence floor (stakes-keyed) or below evidence floor -> approval.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict

# verdict vocabulary (shared across the seam)
ALLOW = "ALLOW"
VERIFY_MORE = "VERIFY_MORE"
ESCALATE = "ESCALATE"
DENY = "DENY"

# decision CLASS (what the OS does with the verdict) — the conformance oracle groups by this
ACT = "act"
APPROVAL = "approval"
BLOCK = "block"


@dataclass(frozen=True)
class VerifiedCandidate:
    action: str
    verified: bool
    confidence: float
    evidence_count: int


EXPECTED_CONTRACT_VERSION = "1.1.0"


@dataclass(frozen=True)
class GovernanceDecisionRequest:
    task_id: str
    risk_tier: str                       # "R0".."R5"
    candidate_actions: tuple
    evidence_count: int
    approved: bool = False
    verified_candidates: tuple = field(default_factory=tuple)
    contract_version: str = EXPECTED_CONTRACT_VERSION


@dataclass(frozen=True)
class GovernanceDecisionResponse:
    verdict: str
    chosen_action: str | None
    reason: str


@dataclass(frozen=True)
class GateConfig:
    approval_required_at_or_above: str = "R4"
    low_stakes_confidence_floor: float = 0.2
    high_stakes_confidence_floor: float = 0.6
    evidence_floor: int = 1


def _tier_num(t: str) -> int:
    return int(t[1:]) if t and t[0] == "R" else 0


def decide(req: GovernanceDecisionRequest, cfg: GateConfig,
           shell_paused: bool = False, forbidden: tuple = ()) -> GovernanceDecisionResponse:
    """Tighten-only reference verdict. Deterministic, contentless. Must match the OS product brain."""
    # invariant 0 (fail-closed): contract version drift -> DENY (never act across an unknown contract)
    if req.contract_version != EXPECTED_CONTRACT_VERSION:
        return GovernanceDecisionResponse(DENY, None,
                                          f"contract version {req.contract_version} != {EXPECTED_CONTRACT_VERSION}")
    # invariant 3: C7 paused / forbidden -> DENY (block), overrides all
    if shell_paused:
        return GovernanceDecisionResponse(DENY, None, "corrigibility shell paused")
    high = _tier_num(req.risk_tier) >= _tier_num(cfg.approval_required_at_or_above)
    floor = cfg.high_stakes_confidence_floor if high else cfg.low_stakes_confidence_floor
    # choose the best VERIFIED candidate clearing floors
    best = None
    for c in req.verified_candidates:
        if c.action in forbidden:
            return GovernanceDecisionResponse(DENY, None, f"action '{c.action}' forbidden")
        if c.verified and c.confidence >= floor and c.evidence_count >= cfg.evidence_floor:
            if best is None or c.confidence > best.confidence:
                best = c
    if best is None:
        # nothing act-able: verified-but-unapproved/high -> escalate; else approval-needed
        return GovernanceDecisionResponse(ESCALATE if high else VERIFY_MORE, None,
                                          "no verified candidate clears the floors")
    # a verified, confident, evidenced candidate exists
    if high and not req.approved:
        return GovernanceDecisionResponse(ESCALATE, None, "high stakes: verified but unapproved")
    return GovernanceDecisionResponse(ALLOW, best.action, "verified, confident, evidenced")


def verdict_class(resp: GovernanceDecisionResponse) -> str:
    if resp.verdict == ALLOW:
        return ACT
    if resp.verdict == DENY:
        return BLOCK
    return APPROVAL   # VERIFY_MORE / ESCALATE both route to approval


def request_to_json(req: GovernanceDecisionRequest) -> str:
    return json.dumps(asdict(req), sort_keys=True)


def agent_action_to_request(task_id: str, action: str, risk_tier: str, verified: bool,
                            confidence: float, evidence_count: int,
                            approved: bool = False) -> GovernanceDecisionRequest:
    """Map an E2E discovery-agent action into a seam GovernanceDecisionRequest (the crossing point)."""
    return GovernanceDecisionRequest(
        task_id=task_id, risk_tier=risk_tier, candidate_actions=(action,),
        evidence_count=evidence_count, approved=approved,
        verified_candidates=(VerifiedCandidate(action, verified, confidence, evidence_count),))
