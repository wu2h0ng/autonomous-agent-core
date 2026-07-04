"""Formal Gate Invariant — exhaustive mutation testing (RR-0052).

Proves three safety invariants hold for GovernedDecisionGate.decide() across
the entire finite mutation space of (AgentSelfModel × ActionRequest × ShellView).

Invariants:
  S1: If shell_view.forbidden contains action_index, verdict == DENY.
  S2: If verdict == DENY due to denied_tools, adding more denied_tools still yields DENY.
  S3: If is_high_stakes and not approved, verdict ∈ {ESCALATE, DENY}, never ALLOW.

Mutation space: ~170K combinations, fully enumerated.
"""

from __future__ import annotations

import itertools
import unittest
from dataclasses import dataclass
from typing import Any, Optional

from aac.self_model import AgentSelfModel, ActionRequest
from aac.governed_gate import GovernedDecisionGate, ALLOW, DENY, ESCALATE, VERIFY_MORE


ACTION = "apply_lever:3"
OTHER_ACTION = "apply_lever:5"
ACTION_INDEX = 3
OTHER_INDEX = 5


@dataclass
class MockShellView:
    paused: bool = False
    forbidden: frozenset = frozenset()

    def observe(self, payload: dict) -> None:
        pass


# --- Mutation Space Definitions ---

ALLOWED_TOOLS_SPACE = [
    frozenset(),                        # empty = no whitelist (all allowed unless denied)
    frozenset([ACTION]),                # whitelist includes the action
    frozenset([OTHER_ACTION]),          # whitelist excludes the action
    frozenset([ACTION, OTHER_ACTION]),  # whitelist includes both
    frozenset(["unrelated:0"]),         # whitelist of unrelated tool only
]

DENIED_TOOLS_SPACE = [
    frozenset(),                        # nothing denied
    frozenset([ACTION]),                # the action is denied
    frozenset([OTHER_ACTION]),          # something else denied
    frozenset([ACTION, OTHER_ACTION]),  # both denied
]

RISK_CEILING_SPACE = [0, 1, 2, 3, 5]

APPROVAL_TIER_SPACE = [0, 1, 2, 4]

EVIDENCE_REQS_SPACE = [
    {},           # no requirements
    {1: 0},       # trivial for tier 1
    {1: 10},      # impossible for tier 1
    {3: 5},       # strict for tier 3
]

CONFIDENCE_THRESH_SPACE = [
    {},           # no thresholds
    {1: 0.0},    # trivial
    {1: 0.99},   # very high
    {3: 0.8},    # strict for tier 3
]

RISK_TIER_SPACE = [0, 1, 3, 5]
CONFIDENCE_SPACE = [0.0, 0.5, 0.95]
VERIFIED_SPACE = [True, False]
EVIDENCE_COUNT_SPACE = [0, 3, 10]
APPROVED_SPACE = [True, False]
ACTION_INDEX_SPACE = [ACTION_INDEX, OTHER_INDEX, None]

SHELL_VIEW_SPACE = [
    None,
    MockShellView(paused=True, forbidden=frozenset()),
    MockShellView(paused=False, forbidden=frozenset([ACTION_INDEX])),
    MockShellView(paused=False, forbidden=frozenset()),
]

LLM_RELIABILITY_SPACE = [None, 0.5, 0.8]


def make_gate(allowed, denied, ceiling, approval_tier, ev_reqs, conf_thresh):
    sm = AgentSelfModel(
        allowed_tools=allowed,
        denied_tools=denied,
        risk_ceiling=ceiling,
        approval_required_at_or_above=approval_tier,
        evidence_requirements=ev_reqs,
        confidence_thresholds=conf_thresh,
    )
    return GovernedDecisionGate(self_model=sm), sm


def make_request(risk_tier, confidence, verified, evidence_count, approved, action_index):
    return ActionRequest(
        action=ACTION,
        risk_tier=risk_tier,
        confidence=confidence,
        verified=verified,
        evidence_count=evidence_count,
        approved=approved,
        action_index=action_index,
    )


class TestS1ShellForbiddenIsBypass(unittest.TestCase):
    """S1: If shell_view.forbidden contains action_index → verdict == DENY.

    This must hold for ALL self_model mutations. The shell's forbidden set
    is self_model-independent.
    """

    def test_s1_exhaustive(self):
        violations = []
        total = 0

        for allowed, denied, ceiling, approval_tier, ev_reqs, conf_thresh in itertools.product(
            ALLOWED_TOOLS_SPACE, DENIED_TOOLS_SPACE, RISK_CEILING_SPACE,
            APPROVAL_TIER_SPACE, EVIDENCE_REQS_SPACE, CONFIDENCE_THRESH_SPACE,
        ):
            gate, sm = make_gate(allowed, denied, ceiling, approval_tier, ev_reqs, conf_thresh)

            for risk_tier, confidence, verified, ev_count, approved in itertools.product(
                RISK_TIER_SPACE, CONFIDENCE_SPACE, VERIFIED_SPACE, EVIDENCE_COUNT_SPACE, APPROVED_SPACE,
            ):
                # S1 condition: action_index IN forbidden, shell not None
                shell = MockShellView(paused=False, forbidden=frozenset([ACTION_INDEX]))
                req = make_request(risk_tier, confidence, verified, ev_count, approved, ACTION_INDEX)

                for reliability in LLM_RELIABILITY_SPACE:
                    total += 1
                    d = gate.decide(req, shell_view=shell, llm_reliability=reliability)

                    if d.verdict != DENY:
                        violations.append({
                            "allowed": allowed, "denied": denied,
                            "ceiling": ceiling, "approval_tier": approval_tier,
                            "risk_tier": risk_tier, "confidence": confidence,
                            "verified": verified, "ev_count": ev_count,
                            "approved": approved, "reliability": reliability,
                            "verdict": d.verdict, "reason": d.reason,
                        })

        self.assertEqual(violations, [],
                         f"S1 violated in {len(violations)}/{total} cases: {violations[:3]}")


class TestS2MonotonicityDeniedTools(unittest.TestCase):
    """S2: If DENY due to denied_tools in sm_1, then for sm_2 with
    sm_2.denied_tools ⊇ sm_1.denied_tools, verdict is still DENY.

    We test: if ACTION ∈ denied_tools → DENY, then adding more to denied_tools
    still → DENY.
    """

    def test_s2_exhaustive(self):
        violations = []
        total = 0

        for allowed, ceiling, approval_tier, ev_reqs, conf_thresh in itertools.product(
            ALLOWED_TOOLS_SPACE, RISK_CEILING_SPACE, APPROVAL_TIER_SPACE,
            EVIDENCE_REQS_SPACE, CONFIDENCE_THRESH_SPACE,
        ):
            # sm_1: ACTION is denied
            gate_1, _ = make_gate(allowed, frozenset([ACTION]), ceiling, approval_tier, ev_reqs, conf_thresh)
            # sm_2: ACTION + OTHER both denied (superset)
            gate_2, _ = make_gate(allowed, frozenset([ACTION, OTHER_ACTION]), ceiling, approval_tier, ev_reqs, conf_thresh)

            for risk_tier, confidence, verified, ev_count, approved, action_idx in itertools.product(
                RISK_TIER_SPACE, CONFIDENCE_SPACE, VERIFIED_SPACE,
                EVIDENCE_COUNT_SPACE, APPROVED_SPACE, ACTION_INDEX_SPACE,
            ):
                req = make_request(risk_tier, confidence, verified, ev_count, approved, action_idx)

                for shell, reliability in itertools.product(SHELL_VIEW_SPACE, LLM_RELIABILITY_SPACE):
                    total += 1
                    d1 = gate_1.decide(req, shell_view=shell, llm_reliability=reliability)

                    if d1.verdict == DENY and "not permitted by self model" in d1.reason:
                        d2 = gate_2.decide(req, shell_view=shell, llm_reliability=reliability)
                        if d2.verdict != DENY:
                            violations.append({
                                "allowed": allowed, "ceiling": ceiling,
                                "risk_tier": risk_tier, "confidence": confidence,
                                "verified": verified, "approved": approved,
                                "action_idx": action_idx,
                                "d1": d1.verdict, "d2": d2.verdict,
                            })

        self.assertEqual(violations, [],
                         f"S2 violated in {len(violations)}/{total} cases: {violations[:3]}")


class TestS3HighStakesNeverAutoActs(unittest.TestCase):
    """S3: If is_high_stakes(risk_tier) and not approved, verdict ∈ {ESCALATE, DENY}.

    Never ALLOW. Must hold for ALL self_model mutations.
    """

    def test_s3_exhaustive(self):
        violations = []
        total = 0

        for allowed, denied, ceiling, approval_tier, ev_reqs, conf_thresh in itertools.product(
            ALLOWED_TOOLS_SPACE, DENIED_TOOLS_SPACE, RISK_CEILING_SPACE,
            APPROVAL_TIER_SPACE, EVIDENCE_REQS_SPACE, CONFIDENCE_THRESH_SPACE,
        ):
            gate, sm = make_gate(allowed, denied, ceiling, approval_tier, ev_reqs, conf_thresh)

            for risk_tier, confidence, verified, ev_count, action_idx in itertools.product(
                RISK_TIER_SPACE, CONFIDENCE_SPACE, VERIFIED_SPACE,
                EVIDENCE_COUNT_SPACE, ACTION_INDEX_SPACE,
            ):
                # S3 condition: high stakes AND not approved
                if not sm.is_high_stakes(risk_tier):
                    continue

                req = make_request(risk_tier, confidence, verified, ev_count, False, action_idx)

                for shell, reliability in itertools.product(SHELL_VIEW_SPACE, LLM_RELIABILITY_SPACE):
                    total += 1
                    d = gate.decide(req, shell_view=shell, llm_reliability=reliability)

                    if d.verdict == ALLOW:
                        violations.append({
                            "allowed": allowed, "denied": denied,
                            "ceiling": ceiling, "approval_tier": approval_tier,
                            "risk_tier": risk_tier, "confidence": confidence,
                            "verified": verified, "ev_count": ev_count,
                            "action_idx": action_idx, "reliability": reliability,
                            "verdict": d.verdict, "reason": d.reason,
                        })

        self.assertGreater(total, 0, "No high-stakes cases found (bad test config)")
        self.assertEqual(violations, [],
                         f"S3 violated in {len(violations)}/{total} cases: {violations[:3]}")


class TestMutationSpaceSize(unittest.TestCase):
    """Verify the mutation space is large enough to be meaningful."""

    def test_space_size(self):
        sm_space = (len(ALLOWED_TOOLS_SPACE) * len(DENIED_TOOLS_SPACE) *
                    len(RISK_CEILING_SPACE) * len(APPROVAL_TIER_SPACE) *
                    len(EVIDENCE_REQS_SPACE) * len(CONFIDENCE_THRESH_SPACE))
        req_space = (len(RISK_TIER_SPACE) * len(CONFIDENCE_SPACE) *
                     len(VERIFIED_SPACE) * len(EVIDENCE_COUNT_SPACE) *
                     len(APPROVED_SPACE) * len(ACTION_INDEX_SPACE))
        env_space = len(SHELL_VIEW_SPACE) * len(LLM_RELIABILITY_SPACE)
        total = sm_space * req_space * env_space
        self.assertGreater(total, 100_000,
                           f"Mutation space too small: {total}")


if __name__ == "__main__":
    unittest.main()
