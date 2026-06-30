"""GovernedLoop — the vertical slice (REF-ARCH-03 §4): one governed closed loop.

    perceive/propose (organ) -> VERIFY (intervention/CWM) -> DECIDE (GovernedDecisionGate, stakes)
    -> act OR escalate -> record outcome ; the C7 CorrigibilityShell wraps it, AuditLog records.

This is the smallest thing that exercises the governance layers of REF-ARCH-01. Load-bearing
invariants (tested in test_governed_loop_slice.py):
  - the loop ONLY acts on a candidate the verifier confirmed effective AND the gate allowed
    -> with a correct verifier it never applies a confounded decoy the proposer ranked first;
    -> the value is CONTINGENT on the verifier being correct (garbage verifier -> garbage; this is
       why the bypass-verifier test exists — to prove the verify-before-decide STRUCTURE is real);
  - high-stakes actions are never auto-applied (the gate escalates for approval);
  - the C7 shell can only TIGHTEN (paused -> deny; a forbidden action index -> deny), never loosen;
  - if no verified-effective, gate-allowed action is found, the loop ESCALATES — it never silently acts.

HONESTY (adversarial review 2026-06-30): this slice covers Propose -> Verify -> Decide -> Act/Escalate
+ C7 + Audit. The feedback step is a minimal OUTCOME RECORD (`on_outcome`), NOT yet belief-update /
memory-driven re-ranking — that is the next increment. The verifier here is a deterministic free
intervention (toy env); noisy/expensive interventions and a hard wall-clock budget cap are not yet
handled (REF-ARCH-04 §4, 🟡).

The loop is organ-agnostic: proposer/verifier/actuator are injected (duck-typed). The proposer may be
a simulated ranker or the real LLMPriorOrgan; the verifier is the interventional/CWM probe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .self_model import ActionRequest
from .governed_gate import GovernedDecisionGate, ALLOW, VERIFY_MORE, ESCALATE, DENY


@dataclass(frozen=True)
class Candidate:
    action: str   # tool/action id, e.g. "apply_lever:3"
    target: int   # the lever/feature index this candidate acts on


@dataclass(frozen=True)
class VerifyResult:
    """Output of the interventional verifier (the CWM probe)."""
    is_effective: bool      # did intervention confirm this action achieves the goal (is causal)?
    confidence: float       # confidence in that verdict, [0, 1]
    evidence_count: int     # confirming interventions bound as evidence
    interventions: int      # interventions spent verifying this candidate


@dataclass(frozen=True)
class StepRecord:
    action: str
    verified_effective: bool
    verdict: str
    reason: str


@dataclass(frozen=True)
class TaskSpec:
    name: str
    risk_tier: int
    approved: bool = False


@dataclass
class TaskResult:
    status: str                      # "acted" | "escalated" | "denied"
    applied_target: Optional[int]    # lever applied (None if not)
    outcome: Optional[float]
    interventions: int
    steps: list[StepRecord] = field(default_factory=list)


@dataclass
class GovernedLoop:
    gate: GovernedDecisionGate
    proposer: Any                    # .rank(task) -> list[Candidate]; optional .reliability
    verifier: Any                    # .verify(candidate) -> VerifyResult
    actuator: Any                    # .apply(candidate) -> float (outcome)
    shell_view: Optional[Any] = None  # C7 capability view (paused/forbidden/observe)
    verify_budget: int = 4
    on_outcome: Optional[Any] = None  # feedback record hook: called (target, outcome) on act
    max_interventions: Optional[int] = None  # hard budget cap; exceeded -> escalate (REF-ARCH-04 §4)
    memory: Optional[Any] = None      # has .remember(action); written on act -> memory-driven re-ranking

    def run_task(self, task: TaskSpec) -> TaskResult:
        self._observe({"event": "task_start", "task": task.name, "risk_tier": task.risk_tier})
        steps: list[StepRecord] = []
        total_interv = 0
        ranked = self.proposer.rank(task)
        reliability = getattr(self.proposer, "reliability", None)

        for cand in ranked[: self.verify_budget]:
            # --- hard budget cap: never blow the intervention budget; escalate instead ---
            if self.max_interventions is not None and total_interv >= self.max_interventions:
                self._observe({"event": "escalate", "reason": "intervention budget exhausted"})
                return TaskResult("escalated", None, None, total_interv, steps)
            # --- VERIFY first: a candidate is only a decision once intervention confirms it ---
            vr: VerifyResult = self.verifier.verify(cand)
            total_interv += vr.interventions
            if not vr.is_effective:
                # eliminated by intervention (e.g. a confounded decoy) -> discard, never act on it
                steps.append(StepRecord(cand.action, False, "SKIP", "intervention: not effective"))
                self._observe({"event": "verify_reject", "action": cand.action})
                continue

            # --- DECIDE: now that it is verified-effective, apply stakes (the gate) ---
            req = ActionRequest(
                action=cand.action,
                risk_tier=task.risk_tier,
                confidence=vr.confidence,
                verified=True,
                evidence_count=vr.evidence_count,
                approved=task.approved,
                action_index=cand.target,  # checked against the C7 shell's forbidden set
            )
            d = self.gate.decide(req, shell_view=self.shell_view, llm_reliability=reliability)
            steps.append(StepRecord(cand.action, True, d.verdict, d.reason))
            self._observe({"event": "decide", "action": cand.action, "verdict": d.verdict})

            if d.verdict == ALLOW:
                outcome = self.actuator.apply(cand)
                self._observe({"event": "act", "action": cand.action, "outcome": outcome})
                if self.on_outcome is not None:        # feedback record hook
                    self.on_outcome(cand.target, outcome)
                if self.memory is not None and outcome and outcome > 0:  # belief update: remember what worked
                    self.memory.remember(cand.action)
                return TaskResult("acted", cand.target, outcome, total_interv, steps)
            if d.verdict == ESCALATE:
                self._observe({"event": "escalate", "action": cand.action, "reason": d.reason})
                return TaskResult("escalated", None, None, total_interv, steps)
            if d.verdict == DENY:
                self._observe({"event": "deny", "action": cand.action, "reason": d.reason})
                return TaskResult("denied", None, None, total_interv, steps)
            # VERIFY_MORE -> keep looking (try the next candidate)

        # no verified-effective, gate-approved action within budget -> ESCALATE (never silently act)
        self._observe({"event": "escalate", "reason": "no verified-effective action found"})
        return TaskResult("escalated", None, None, total_interv, steps)

    def _observe(self, payload: dict) -> None:
        if self.shell_view is not None:
            self.shell_view.observe(payload)


class ActionMemory:
    """Minimal belief store: which actions have verified as effective (REF-ARCH-03 'Learn').

    The loop writes here on a successful act; a MemoryReranker reads it to try known-good actions
    first next time -> fewer interventions on a repeat task. This is the real (if minimal) feedback
    loop: the outcome of acting CHANGES future behavior, not just a logged record."""

    def __init__(self) -> None:
        self._effective: dict[str, int] = {}

    def remember(self, action: str) -> None:
        self._effective[action] = self._effective.get(action, 0) + 1

    def known(self) -> set[str]:
        return set(self._effective)


@dataclass
class MemoryReranker:
    """Wraps a base proposer: moves memory-known-effective candidates to the front (belief-driven
    re-ranking). Falls back to the base order for everything else."""

    base: Any                     # the underlying proposer (.rank(task) -> list[Candidate])
    memory: ActionMemory
    reliability: Optional[float] = None

    def __post_init__(self) -> None:
        self.reliability = getattr(self.base, "reliability", None)

    def rank(self, task) -> list[Candidate]:
        cands = self.base.rank(task)
        known = self.memory.known()
        head = [c for c in cands if c.action in known]
        tail = [c for c in cands if c.action not in known]
        return head + tail
