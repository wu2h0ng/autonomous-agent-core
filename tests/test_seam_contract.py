"""Reference acceptance tests for the OS injection seam (RR-0032 PREPARE, invariant (b)).

These encode the FIVE invariants the seam must preserve. They run against the core's reference
SeamProducer; the OS side must pass the same invariants before any WIRE go (RR-0032 execution gate).
"""

from __future__ import annotations

import unittest

from aac.seam_contract import (
    SeamProducer, GovernedDecisionRequest, GovernedDecisionResponse, VerifiedCandidate,
    to_json, request_from_json, response_from_json, SEAM_CONTRACT_VERSION,
)
from aac.governed_gate import GovernedDecisionGate, ALLOW, ESCALATE, DENY
from aac.governed_loop import VerifyResult, Candidate
from aac.self_model import AgentSelfModel
from aac.shell import CorrigibilityShell

TRUE = "lever:true"
DECOY = "lever:decoy"


class _Verifier:
    """Verifies a candidate effective iff it is the true cause (the interventional probe stand-in)."""
    def verify(self, cand: Candidate) -> VerifyResult:
        eff = cand.action == TRUE
        return VerifyResult(eff, 0.9 if eff else 0.0, 3 if eff else 0, 1)


def _producer(shell=None) -> SeamProducer:
    sm = AgentSelfModel(
        allowed_tools=frozenset(), denied_tools=frozenset(), risk_ceiling=5,
        approval_required_at_or_above=4, evidence_requirements={}, confidence_thresholds={1: 0.2, 4: 0.6},
    )
    return SeamProducer(GovernedDecisionGate(sm), _Verifier(), shell=shell)


def _req(**kw) -> GovernedDecisionRequest:
    base = dict(task_id="t", risk_tier=1, candidate_actions=[DECOY, TRUE], approved=False)
    base.update(kw)
    return GovernedDecisionRequest(**base)


class Invariant1_ActOnlyOnVerified(unittest.TestCase):
    def test_verified_true_cause_allows_decoy_skipped(self):
        r = _producer().handle(_req(candidate_actions=[DECOY, TRUE]))
        self.assertEqual(r.verdict, ALLOW)
        self.assertEqual(r.chosen_action, TRUE)     # NOT the decoy ranked first

    def test_no_verifiable_candidate_does_not_allow(self):
        r = _producer().handle(_req(candidate_actions=[DECOY]))
        self.assertNotEqual(r.verdict, ALLOW)       # unverified -> never acted on


class Invariant2_StakesGated(unittest.TestCase):
    def test_high_stakes_unapproved_escalates(self):
        r = _producer().handle(_req(risk_tier=4, candidate_actions=[TRUE], approved=False))
        self.assertEqual(r.verdict, ESCALATE)
        self.assertIsNone(r.chosen_action)

    def test_high_stakes_approved_allows(self):
        r = _producer().handle(_req(risk_tier=4, candidate_actions=[TRUE], approved=True))
        self.assertEqual(r.verdict, ALLOW)


class Invariant3_C7Supremacy(unittest.TestCase):
    def test_paused_shell_denies(self):
        shell = CorrigibilityShell(); shell.op_pause()
        r = _producer(shell=shell).handle(_req(candidate_actions=[TRUE]))
        self.assertEqual(r.verdict, DENY)           # C7 can only tighten


class Invariant4_LLMisOrgan_Deterministic(unittest.TestCase):
    def test_same_request_same_verdict(self):
        a = _producer().handle(_req())
        b = _producer().handle(_req())
        self.assertEqual((a.verdict, a.chosen_action), (b.verdict, b.chosen_action))  # no LLM nondeterminism in the control path


class Invariant5_NoSilentBypass(unittest.TestCase):
    def test_response_carries_resolving_audit_ref(self):
        shell = CorrigibilityShell()
        r = _producer(shell=shell).handle(_req())
        self.assertTrue(r.audit_ref)                # non-empty
        self.assertTrue(shell.audit.verify())       # the chain it points into is intact

    def test_version_reject_response_also_carries_resolving_audit_ref(self):
        # Regression guard for b9c51ae: the incompatible-major-version DENY is a RESPONSE too, so
        # invariant 5 binds it — it must carry a resolving audit_ref, never "". This was caught LIVE
        # by the OS-side response validator during the M4 deployment rehearsal (2026-07-03); without
        # this assertion a revert to audit_ref="" passes every other seam test unnoticed.
        shell = CorrigibilityShell()
        r = _producer(shell=shell).handle(_req(contract_version="2.0.0"))
        self.assertEqual(r.verdict, DENY)
        self.assertTrue(r.audit_ref)                                       # NOT "" (invariant 5 for ALL responses)
        self.assertTrue(shell.audit.verify())                             # the chain is intact
        self.assertEqual(r.audit_ref, shell.audit.entries()[-1].entry_hash)  # the ref RESOLVES into that chain


class ContractVersioning(unittest.TestCase):
    def test_incompatible_major_version_denied(self):
        r = _producer().handle(_req(contract_version="2.0.0"))
        self.assertEqual(r.verdict, DENY)
        self.assertIn("contract", r.reason.lower())

    def test_json_round_trip(self):
        req = _req()
        self.assertEqual(request_from_json(to_json(req)), req)
        resp = _producer().handle(req)
        self.assertEqual(response_from_json(to_json(resp)), resp)


class V11_OSVerifiesCoreGoverns(unittest.TestCase):
    """v1.1: the OS supplies verification; the core GOVERNS it (does not re-verify)."""

    def _vreq(self, vcs, **kw):
        base = dict(task_id="t", risk_tier=1, candidate_actions=[vc.action for vc in vcs],
                    approved=False, verified_candidates=tuple(vcs))
        base.update(kw)
        return GovernedDecisionRequest(**base)

    def test_governs_supplied_verification_allow(self):
        vcs = [VerifiedCandidate(DECOY, False, 0.0, 0), VerifiedCandidate(TRUE, True, 0.9, 3)]
        r = _producer().handle(self._vreq(vcs))
        self.assertEqual(r.verdict, ALLOW)
        self.assertEqual(r.chosen_action, TRUE)     # skips the unverified decoy, governs the verified one

    def test_all_unverified_escalates(self):
        vcs = [VerifiedCandidate(DECOY, False, 0.0, 0)]
        self.assertEqual(_producer().handle(self._vreq(vcs)).verdict, ESCALATE)

    def test_high_stakes_supplied_verification_escalates_unapproved(self):
        vcs = [VerifiedCandidate(TRUE, True, 0.9, 3)]
        self.assertEqual(_producer().handle(self._vreq(vcs, risk_tier=4, approved=False)).verdict, ESCALATE)

    def test_paused_shell_denies_supplied_verification(self):
        shell = CorrigibilityShell(); shell.op_pause()
        vcs = [VerifiedCandidate(TRUE, True, 0.9, 3)]
        self.assertEqual(_producer(shell=shell).handle(self._vreq(vcs)).verdict, DENY)

    def test_core_does_not_reverify(self):
        # the core trusts the OS verification: a candidate the OS marked verified is governed even
        # though this producer's own _Verifier would call it ineffective (proves no core re-verify).
        vcs = [VerifiedCandidate(DECOY, True, 0.9, 3)]   # OS says the "decoy" IS verified-effective
        r = _producer().handle(self._vreq(vcs))
        self.assertEqual(r.verdict, ALLOW)
        self.assertEqual(r.chosen_action, DECOY)

    def test_v11_json_round_trip(self):
        req = self._vreq([VerifiedCandidate(TRUE, True, 0.9, 3)])
        self.assertEqual(request_from_json(to_json(req)), req)

    def test_version_is_1_1(self):
        self.assertTrue(SEAM_CONTRACT_VERSION.startswith("1.1"))


if __name__ == "__main__":
    unittest.main()
