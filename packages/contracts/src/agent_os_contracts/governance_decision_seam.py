"""Governed-decision injection seam — versioned RPC contract (RR-0032, OS side).

The typed request/response the OS Trusted Loop exchanges with the external governed-decision brain
(`autonomous-agent-core`) over an RPC/service boundary. This is the OS's NATIVE implementation of the
shared contract spec — it imports NO sibling-repo code (Hard Boundary #19; RR-0032 cast: RPC, not a
library import). Both sides implement the same versioned schema independently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict

SEAM_CONTRACT_VERSION = "1.0.0"  # semver; a contract change must bump this (RR-0032 cast #4)

# verdicts
ALLOW = "ALLOW"
VERIFY_MORE = "VERIFY_MORE"
ESCALATE = "ESCALATE"
DENY = "DENY"


@dataclass(frozen=True)
class GovernanceDecisionRequest:
    task_id: str
    risk_tier: str               # "R0".."R5" — shared vocabulary across the seam (RR-0032 cast #3)
    candidate_actions: tuple[str, ...]
    evidence_count: int = 0
    approved: bool = False
    contract_version: str = SEAM_CONTRACT_VERSION


@dataclass(frozen=True)
class GovernanceDecisionResponse:
    task_id: str
    verdict: str                 # ALLOW | VERIFY_MORE | ESCALATE | DENY
    chosen_action: str | None
    confidence: float
    reason: str
    audit_ref: str
    contract_version: str = SEAM_CONTRACT_VERSION


def request_to_json(req: GovernanceDecisionRequest) -> str:
    return json.dumps(asdict(req), sort_keys=True)


def response_to_json(resp: GovernanceDecisionResponse) -> str:
    return json.dumps(asdict(resp), sort_keys=True)


def request_from_json(s: str) -> GovernanceDecisionRequest:
    d = json.loads(s)
    d["candidate_actions"] = tuple(d.get("candidate_actions", ()))
    return GovernanceDecisionRequest(**d)


def response_from_json(s: str) -> GovernanceDecisionResponse:
    return GovernanceDecisionResponse(**json.loads(s))
