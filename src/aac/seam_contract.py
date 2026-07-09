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
from .self_model import ActionRequest
from .shell import CorrigibilityShell

SEAM_CONTRACT_VERSION = "1.1.0"   # semver; v1.1 adds OS-supplied verification (RR-0032 "OS verifies")

# Wire risk vocabulary is the string "R0".."R5" (RR-0032 cast #3; matches the OS RiskLevel). The core
# governs with integer tiers internally, so it converts at the boundary.
_TIER = {f"R{i}": i for i in range(6)}


def _tier_int(risk_tier: Any) -> int:
    if isinstance(risk_tier, int):
        return risk_tier                       # tolerate an int for back-compat/local callers
    return _TIER.get(str(risk_tier), 5)        # unknown -> treat as highest stakes (safe)


@dataclass(frozen=True)
class VerifiedCandidate:
    """A candidate the OS has already VERIFIED (RR-0032 "OS verifies -> core governs"): the OS ran the
    interventional cohort A/B test (it owns the data); the core only governs this supplied result."""
    action: str
    verified: bool
    confidence: float
    evidence_count: int


@dataclass(frozen=True)
class GovernedDecisionRequest:
    task_id: str
    risk_tier: str                     # "R0".."R5" wire vocabulary (RR-0032 cast #3); core converts to int
    candidate_actions: list[str]       # OS-ranked candidate action ids (the confounded prior)
    evidence_count: int = 0            # evidence already bound by the OS EvidenceChain
    approved: bool = False             # OS Approval result (for high-stakes tiers)
    # v1.1: the OS's own verification of the candidates ("OS verifies -> core governs"). When present,
    # the core governs these instead of running its own verifier (it has no access to OS data).
    verified_candidates: tuple[VerifiedCandidate, ...] = field(default_factory=tuple)
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
    d = json.loads(s)
    d["verified_candidates"] = tuple(
        VerifiedCandidate(**vc) for vc in d.get("verified_candidates", ())
    )
    return GovernedDecisionRequest(**d)


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
        # contract versioning (RR-0032 cast #4): reject incompatible MAJOR versions, never silently adapt.
        # The rejection itself is AUDITED (invariant 5: EVERY response carries a resolving audit_ref —
        # caught live by the OS-side validator in the M4 deployment rehearsal, 2026-07-03).
        if request.contract_version.split(".")[0] != SEAM_CONTRACT_VERSION.split(".")[0]:
            reject_shell = self.shell if self.shell is not None else CorrigibilityShell()
            reason = (f"incompatible contract major version "
                      f"{request.contract_version} != {SEAM_CONTRACT_VERSION}")
            reject_shell.view().observe(
                {"event": "seam_version_reject", "task": request.task_id, "reason": reason})
            entries = reject_shell.audit.entries()
            audit_ref = entries[-1].entry_hash if entries else ""
            return GovernedDecisionResponse(request.task_id, DENY, None, 0.0, reason, audit_ref)

        shell = self.shell if self.shell is not None else CorrigibilityShell()

        # v1.1 primary path: the OS already verified (it owns the data) -> the core only GOVERNS the
        # supplied verification via the gate. The core does NOT re-verify (RR-0032 "OS verifies").
        if request.verified_candidates:
            return self._govern(request, shell)

        # v1.0 back-compat path: no OS verification supplied -> self-verify via the injected verifier.
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
        res = loop.run_task(TaskSpec(request.task_id, _tier_int(request.risk_tier), request.approved))

        entries = shell.audit.entries()
        audit_ref = entries[-1].entry_hash if entries else ""
        verdict = {"acted": ALLOW, "escalated": ESCALATE, "denied": DENY}[res.status]
        chosen = actuator.chosen.action if (res.status == "acted" and actuator.chosen) else None
        reason = res.steps[-1].reason if res.steps else "no candidates"
        confidence = 1.0 if verdict == ALLOW else 0.0   # coarse; per-step detail is in the audit chain
        return GovernedDecisionResponse(
            request.task_id, verdict, chosen, confidence, reason, audit_ref)

    def _govern(self, request: GovernedDecisionRequest, shell: CorrigibilityShell) -> GovernedDecisionResponse:
        """Governance-only over OS-supplied verification (v1.1): apply the gate to each verified
        candidate in order; act only on verified; C7/paused/forbidden tighten via the gate."""
        shell_view = shell.view()

        def _resp(verdict, chosen, conf, reason):
            shell_view.observe({"event": "governed_decision", "verdict": verdict, "chosen": chosen})
            entries = shell.audit.entries()
            return GovernedDecisionResponse(
                request.task_id, verdict, chosen, conf, reason,
                entries[-1].entry_hash if entries else "")

        for i, vc in enumerate(request.verified_candidates):
            if not vc.verified:
                continue                                  # act only on VERIFIED (invariant 1)
            decision = self.gate.decide(
                ActionRequest(
                    action=vc.action, risk_tier=_tier_int(request.risk_tier), confidence=vc.confidence,
                    verified=True, evidence_count=vc.evidence_count, approved=request.approved,
                    action_index=i,
                ),
                shell_view=shell_view,
            )
            if decision.verdict == ALLOW:
                return _resp(ALLOW, vc.action, vc.confidence, decision.reason)
            if decision.verdict in (ESCALATE, DENY):
                return _resp(decision.verdict, None, 0.0, decision.reason)
            # VERIFY_MORE -> try the next verified candidate
        return _resp(ESCALATE, None, 0.0, "no governable verified candidate")
