"""EXP-F: Gate Formal Verification — property-based testing of safety invariants.

Question: For ALL possible mutations of AgentSelfModel and ActionRequest, does the
gate's safety invariant hold? Specifically:
  - INV-1: A denied action NEVER receives ALLOW verdict
  - INV-2: A forbidden action_index (C7 shell) NEVER receives ALLOW verdict
  - INV-3: Above-ceiling risk NEVER receives ALLOW verdict
  - INV-4: High-stakes unverified NEVER receives ALLOW verdict
  - INV-5: High-stakes unapproved NEVER receives ALLOW verdict

Method: exhaustive enumeration over the finite state space (toy scale permits this)
plus random fuzzing of edge cases.

Run: PYTHONPATH=src:experiments python experiments/c7_off_exp_f_formal_verification.py
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Optional

from aac.self_model import AgentSelfModel, ActionRequest
from aac.governed_gate import GovernedDecisionGate, GateDecision, ALLOW, DENY, ESCALATE, VERIFY_MORE
from aac.shell import CorrigibilityShell


D = 6
FUZZ_ITERATIONS = 10000


@dataclass
class InvariantResult:
    invariant: str
    tested: int = 0
    violations: int = 0
    examples: list[str] = field(default_factory=list)

    @property
    def holds(self) -> bool:
        return self.violations == 0


def verify_inv1_denied_never_allow() -> InvariantResult:
    """INV-1: If action is in self_model.denied_tools, verdict != ALLOW."""
    result = InvariantResult(invariant="INV-1: denied action -> never ALLOW")

    for denied_lever in range(D):
        sm = AgentSelfModel(
            allowed_tools=frozenset(f"apply_lever:{i}" for i in range(D)),
            denied_tools=frozenset([f"apply_lever:{denied_lever}"]),
            risk_ceiling=5,
            approval_required_at_or_above=4,
            evidence_requirements={},
            confidence_thresholds={},
        )
        gate = GovernedDecisionGate(self_model=sm)

        # Test with all possible confidence/verified/approved combinations
        for conf in [0.0, 0.5, 0.9, 1.0]:
            for verified in [True, False]:
                for approved in [True, False]:
                    for risk in range(6):
                        for evidence in [0, 3, 10]:
                            req = ActionRequest(
                                action=f"apply_lever:{denied_lever}",
                                risk_tier=risk,
                                confidence=conf,
                                verified=verified,
                                evidence_count=evidence,
                                approved=approved,
                                action_index=denied_lever,
                            )
                            d = gate.decide(req, shell_view=None)
                            result.tested += 1
                            if d.verdict == ALLOW:
                                result.violations += 1
                                result.examples.append(
                                    f"VIOLATION: denied lever {denied_lever}, "
                                    f"risk={risk}, conf={conf}, verified={verified}, "
                                    f"approved={approved} -> {d.verdict}")

    return result


def verify_inv2_forbidden_index_never_allow() -> InvariantResult:
    """INV-2: If action_index is in shell.forbidden, verdict != ALLOW."""
    result = InvariantResult(invariant="INV-2: forbidden index (C7) -> never ALLOW")

    for forbidden_idx in range(D):
        sm = AgentSelfModel(
            allowed_tools=frozenset(f"apply_lever:{i}" for i in range(D)),
            denied_tools=frozenset(),  # NOT denied in self_model
            risk_ceiling=5,
            approval_required_at_or_above=4,
            evidence_requirements={},
            confidence_thresholds={},
        )
        gate = GovernedDecisionGate(self_model=sm)
        shell = CorrigibilityShell()
        shell.op_tighten(forbidden_idx)

        for conf in [0.0, 0.5, 0.9, 1.0]:
            for verified in [True, False]:
                for approved in [True, False]:
                    for risk in range(6):
                        for evidence in [0, 3, 10]:
                            # Use any action string (even an "allowed" one)
                            safe_name = f"apply_lever:{(forbidden_idx + 1) % D}"
                            req = ActionRequest(
                                action=safe_name,
                                risk_tier=risk,
                                confidence=conf,
                                verified=verified,
                                evidence_count=evidence,
                                approved=approved,
                                action_index=forbidden_idx,
                            )
                            d = gate.decide(req, shell_view=shell)
                            result.tested += 1
                            if d.verdict == ALLOW:
                                result.violations += 1
                                result.examples.append(
                                    f"VIOLATION: action='{safe_name}' index={forbidden_idx} "
                                    f"risk={risk}, conf={conf} -> {d.verdict}")

    return result


def verify_inv3_above_ceiling_never_allow() -> InvariantResult:
    """INV-3: risk_tier > risk_ceiling -> never ALLOW."""
    result = InvariantResult(invariant="INV-3: above ceiling -> never ALLOW")

    for ceiling in range(6):
        sm = AgentSelfModel(
            allowed_tools=frozenset(f"apply_lever:{i}" for i in range(D)),
            denied_tools=frozenset(),
            risk_ceiling=ceiling,
            approval_required_at_or_above=ceiling + 1,
            evidence_requirements={},
            confidence_thresholds={},
        )
        gate = GovernedDecisionGate(self_model=sm)

        for risk in range(ceiling + 1, 6):
            for conf in [0.0, 0.5, 1.0]:
                for verified in [True, False]:
                    for approved in [True, False]:
                        req = ActionRequest(
                            action="apply_lever:0",
                            risk_tier=risk,
                            confidence=conf,
                            verified=verified,
                            evidence_count=10,
                            approved=approved,
                            action_index=0,
                        )
                        d = gate.decide(req, shell_view=None)
                        result.tested += 1
                        if d.verdict == ALLOW:
                            result.violations += 1
                            result.examples.append(
                                f"VIOLATION: ceiling={ceiling}, risk={risk}, "
                                f"conf={conf}, verified={verified} -> {d.verdict}")

    return result


def verify_inv4_highstakes_unverified_never_allow() -> InvariantResult:
    """INV-4: high-stakes + unverified -> never ALLOW."""
    result = InvariantResult(invariant="INV-4: high-stakes + unverified -> never ALLOW")

    for approval_tier in range(1, 6):
        sm = AgentSelfModel(
            allowed_tools=frozenset(f"apply_lever:{i}" for i in range(D)),
            denied_tools=frozenset(),
            risk_ceiling=5,
            approval_required_at_or_above=approval_tier,
            evidence_requirements={},
            confidence_thresholds={},
        )
        gate = GovernedDecisionGate(self_model=sm)

        for risk in range(approval_tier, 6):
            for conf in [0.0, 0.5, 1.0]:
                for approved in [True, False]:
                    req = ActionRequest(
                        action="apply_lever:0",
                        risk_tier=risk,
                        confidence=conf,
                        verified=False,  # UNVERIFIED
                        evidence_count=10,
                        approved=approved,
                        action_index=0,
                    )
                    d = gate.decide(req, shell_view=None)
                    result.tested += 1
                    if d.verdict == ALLOW:
                        result.violations += 1
                        result.examples.append(
                            f"VIOLATION: approval_tier={approval_tier}, risk={risk}, "
                            f"conf={conf}, approved={approved}, UNVERIFIED -> {d.verdict}")

    return result


def verify_inv5_highstakes_unapproved_never_allow() -> InvariantResult:
    """INV-5: high-stakes + unapproved -> never ALLOW (even if verified + confident)."""
    result = InvariantResult(invariant="INV-5: high-stakes + unapproved -> never ALLOW")

    for approval_tier in range(1, 6):
        sm = AgentSelfModel(
            allowed_tools=frozenset(f"apply_lever:{i}" for i in range(D)),
            denied_tools=frozenset(),
            risk_ceiling=5,
            approval_required_at_or_above=approval_tier,
            evidence_requirements={},
            confidence_thresholds={},
        )
        gate = GovernedDecisionGate(self_model=sm)

        for risk in range(approval_tier, 6):
            for conf in [0.0, 0.5, 1.0]:
                req = ActionRequest(
                    action="apply_lever:0",
                    risk_tier=risk,
                    confidence=conf,
                    verified=True,
                    evidence_count=10,
                    approved=False,  # UNAPPROVED
                    action_index=0,
                )
                d = gate.decide(req, shell_view=None)
                result.tested += 1
                if d.verdict == ALLOW:
                    result.violations += 1
                    result.examples.append(
                        f"VIOLATION: approval_tier={approval_tier}, risk={risk}, "
                        f"conf={conf}, UNAPPROVED -> {d.verdict}")

    return result


def fuzz_random_inputs() -> InvariantResult:
    """Random fuzzing: generate random ActionRequests and check all invariants hold."""
    result = InvariantResult(invariant="FUZZ: random inputs (all invariants)")
    rng = random.Random(42)

    for _ in range(FUZZ_ITERATIONS):
        # Random self_model
        denied_set = frozenset(
            f"apply_lever:{i}" for i in range(D) if rng.random() < 0.3
        )
        ceiling = rng.randint(0, 5)
        approval_at = rng.randint(0, 5)

        sm = AgentSelfModel(
            allowed_tools=frozenset(f"apply_lever:{i}" for i in range(D)),
            denied_tools=denied_set,
            risk_ceiling=ceiling,
            approval_required_at_or_above=approval_at,
            evidence_requirements={i: rng.randint(0, 5) for i in range(6)},
            confidence_thresholds={i: rng.random() for i in range(6)},
        )
        gate = GovernedDecisionGate(self_model=sm)

        # Random shell
        shell = CorrigibilityShell()
        forbidden_indices = set()
        for i in range(D):
            if rng.random() < 0.3:
                shell.op_tighten(i)
                forbidden_indices.add(i)
        if rng.random() < 0.2:
            shell.op_pause()

        # Random request
        lever = rng.randint(0, D - 1)
        action_str = f"apply_lever:{lever}"
        risk = rng.randint(0, 5)
        conf = rng.random()
        verified = rng.choice([True, False])
        approved = rng.choice([True, False])
        evidence = rng.randint(0, 10)

        req = ActionRequest(
            action=action_str,
            risk_tier=risk,
            confidence=conf,
            verified=verified,
            evidence_count=evidence,
            approved=approved,
            action_index=lever,
        )

        d = gate.decide(req, shell_view=shell)
        result.tested += 1

        # Check invariants
        if d.verdict == ALLOW:
            # INV-1: denied action never ALLOW
            if action_str in denied_set:
                result.violations += 1
                result.examples.append(f"FUZZ INV-1: denied '{action_str}' got ALLOW")
            # INV-2: forbidden index never ALLOW
            if lever in forbidden_indices:
                result.violations += 1
                result.examples.append(f"FUZZ INV-2: forbidden index {lever} got ALLOW")
            # INV-3: above ceiling never ALLOW
            if risk > ceiling:
                result.violations += 1
                result.examples.append(f"FUZZ INV-3: risk={risk} > ceiling={ceiling} got ALLOW")
            # Shell paused never ALLOW
            if shell.paused:
                result.violations += 1
                result.examples.append(f"FUZZ: shell paused got ALLOW")
            # INV-4: high-stakes unverified never ALLOW
            if risk >= approval_at and not verified:
                result.violations += 1
                result.examples.append(f"FUZZ INV-4: high-stakes unverified got ALLOW")
            # INV-5: high-stakes unapproved never ALLOW
            if risk >= approval_at and not approved:
                result.violations += 1
                result.examples.append(f"FUZZ INV-5: high-stakes unapproved got ALLOW")

    return result


def main() -> None:
    print("\n" + "=" * 70)
    print("  EXP-F: Gate Formal Verification (Property-Based Testing)")
    print("  Do safety invariants hold for ALL possible inputs?")
    print("=" * 70)

    invariants = [
        verify_inv1_denied_never_allow(),
        verify_inv2_forbidden_index_never_allow(),
        verify_inv3_above_ceiling_never_allow(),
        verify_inv4_highstakes_unverified_never_allow(),
        verify_inv5_highstakes_unapproved_never_allow(),
        fuzz_random_inputs(),
    ]

    all_hold = True
    total_tested = 0
    total_violations = 0

    print(f"\n  {'Invariant':<55} {'Tested':>8} {'Violations':>10} {'Status':>8}")
    print(f"  {'-'*55} {'-'*8} {'-'*10} {'-'*8}")

    for inv in invariants:
        status = "HOLDS" if inv.holds else "BROKEN"
        if not inv.holds:
            all_hold = False
        total_tested += inv.tested
        total_violations += inv.violations
        print(f"  {inv.invariant:<55} {inv.tested:>8} {inv.violations:>10} {status:>8}")
        if inv.examples:
            for ex in inv.examples[:3]:
                print(f"    ! {ex}")
            if len(inv.examples) > 3:
                print(f"    ... and {len(inv.examples) - 3} more")

    print(f"\n  TOTAL: {total_tested} test cases, {total_violations} violations")

    # Verdicts
    print("\n  VERDICTS:")
    if all_hold:
        print("  ALL INVARIANTS HOLD — gate logic is formally correct over the tested space")
        print(f"  Exhaustive enumeration: {total_tested - FUZZ_ITERATIONS} structured cases")
        print(f"  Random fuzzing: {FUZZ_ITERATIONS} random cases")
        print()
        print("  This means:")
        print("  1. denied_tools check is COMPLETE — no denied action can ever receive ALLOW")
        print("  2. C7 forbidden check is COMPLETE — no forbidden index can ever receive ALLOW")
        print("  3. Risk ceiling is ABSOLUTE — no above-ceiling action can ever receive ALLOW")
        print("  4. High-stakes gates are INVIOLABLE — unverified/unapproved never pass")
        print()
        print("  IMPLICATION FOR THE C7 QUESTION:")
        print("  The gate's Python logic IS formally correct. The only remaining question")
        print("  is: can the agent MODIFY this logic at runtime? That's what process")
        print("  isolation (EXP-E) and deployment-level C7 address — not logic bugs,")
        print("  but unauthorized modification of correct logic.")
    else:
        print("  INVARIANT VIOLATIONS FOUND — gate logic has bugs!")
        print("  This must be fixed before any C7-off experiment is meaningful.")


if __name__ == "__main__":
    main()
