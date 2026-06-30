"""OS injection seam — versioned RPC contract + producer stub (RR-0032 PREPARE, scope=prepare).

The seam by which the enterprise OS calls the prototype's governed decision brain over an RPC/service
boundary (RR-0032 cast: RPC, not a library import — keeps the repos cleanly separate per Hard Boundary
#19). This module is the PRODUCER side, entirely within autonomous-agent-core: it imports NO OS code.
The OS would send a GovernedDecisionRequest (JSON) and receive a GovernedDecisionResponse (JSON).

It reuses the validated GovernedLoop (ADR-0048/0049) — it does NOT re-implement the governance logic.
The producer only DECIDES (verdict + chosen action); it never executes a business action (the OS does).
WIRE remains gated: this is a reference contract + stub for review, not a cross-repo integration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from typing import Any, Optional

from .governed_gate import ALLOW, VERIFY_MORE, ESCALATE, DENY
from .governed_loop import GovernedLoop, Candidate, TaskSpec
from .shell import CorrigibilityShell

SEAM_CONTRACT_VERSION = "1.0.0"   # semver; a core mechanism change must bump this (RR-0032 cast #4)


@dataclass(frozen=True)
class GovernedDecisionRequest:
    task_id: str
    risk_tier: int                     # R0..R5; shared vocabulary across the seam (RR-0032 cast #3)
    candidate_actions: list[str]       # OS-ranked candidate action ids (the confounded prior)
    evidence_count: int = 0            # evidence already bound by the OS EvidenceChain
    approved: bool = False             # OS Approval result (for high-stakes tiers)
    contract_version: str = SEAM_CONTRACT_VERSION


@dataclass(frozen=True)
class GovernedDecisionResponse:
    task_id: str
    verdict: str                       # ALLOW | VERIFY_MORE | ESCALATE | DENY
    chosen_action: Optional[str]
    confidence: float
    reason: str
    audit_ref: str                     # tamper-evident hash from the producer's AuditLog
    contract_version: str = SEAM_CONTRACT_VERSION


def to_json(obj: Any) -> str:
    return json.dumps(asdict(obj), sort_keys=True)


def request_from_json(s: str) -> GovernedDecisionRequest:
    return GovernedDecisionRequest(**json.loads(s))


def response_from_json(s: str) -> GovernedDecisionResponse:
    return GovernedDecisionResponse(**json.loads(s))


class _RecordActuator:
    """The producer DECIDES; it does not execute the business action (the OS does). This records the
    chosen action and returns a positive sentinel so the loop treats the decision as taken."""

    def __init__(self) -> None:
        self.chosen: Optional[Candidate] = None

    def apply(self, cand: Candidate) -> float:
        self.chosen = cand
        return 1.0


@dataclass
class SeamProducer:
    """Reference producer: GovernedDecisionRequest -> GovernedDecisionResponse, reusing GovernedLoop.

    gate: GovernedDecisionGate (the core's stakes-keyed trilemma). verifier: the interventional/CWM
    probe (injected; the OS supplies its measurement). shell: optional CorrigibilityShell (C7) so an
    operator pause/forbid can only tighten the verdict."""

    gate: Any
    verifier: Any
    shell: Optional[CorrigibilityShell] = None

    def handle(self, request: GovernedDecisionRequest) -> GovernedDecisionResponse:
        # contract versioning (RR-0032 cast #4): reject incompatible MAJOR versions, never silently adapt
        if request.contract_version.split(".")[0] != SEAM_CONTRACT_VERSION.split(".")[0]:
            return GovernedDecisionResponse(
                request.task_id, DENY, None, 0.0,
                f"incompatible contract major version {request.contract_version} != {SEAM_CONTRACT_VERSION}", "")

        shell = self.shell if self.shell is not None else CorrigibilityShell()
        actuator = _RecordActuator()
        index = {a: i for i, a in enumerate(request.candidate_actions)}
        producer = self

        class _Proposer:
            reliability = None

            def rank(self, _task):
                return [Candidate(action=a, target=index[a]) for a in request.candidate_actions]

        loop = GovernedLoop(
            gate=self.gate, proposer=_Proposer(), verifier=self.verifier, actuator=actuator,
            shell_view=shell.view(), verify_budget=max(1, len(request.candidate_actions)),
        )
        res = loop.run_task(TaskSpec(request.task_id, request.risk_tier, request.approved))

        entries = shell.audit.entries()
        audit_ref = entries[-1].entry_hash if entries else ""
        verdict = {"acted": ALLOW, "escalated": ESCALATE, "denied": DENY}[res.status]
        chosen = actuator.chosen.action if (res.status == "acted" and actuator.chosen) else None
        reason = res.steps[-1].reason if res.steps else "no candidates"
        confidence = 1.0 if verdict == ALLOW else 0.0   # coarse; per-step detail is in the audit chain
        return GovernedDecisionResponse(
            request.task_id, verdict, chosen, confidence, reason, audit_ref)
