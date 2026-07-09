"""STAGE-2 contract tests — stratified evidence, ConflictDetector, poisoning guard.

Formal model: docs/pre_spec/STAGE2-PROVENANCE-CONFLICT.FORMAL-MODEL-2026-07-03.md (4003c20).
Written BEFORE the mechanism files exist (Hard Boundary #17).

Locks: I7 stratification seal · I8 conflict privilege-stripping · I9 poisoning immunity +
standing detector · I10 convergence to the intervention-verified claim · the RR-0035 Stage-2
could-fail gates (A2 injected contradiction; stratification-bite on a high-stakes verdict;
1000-write poisoning falsifier).
"""

from __future__ import annotations

import unittest

from aac.belief_ledger import (
    BeliefLedger, FACT, HYPOTHESIS, REFUTED,
    VERIFIED_INTERVENTION, CORRELATIONAL, ORGAN_PRIOR, CAP_NV, W_NV,
)
from aac.conflict_detector import ConflictDetector
from aac.evidence_assembly import stratified_evidence, unstratified_evidence_CONTROL
from aac.governed_gate import GovernedDecisionGate, ALLOW, ESCALATE
from aac.governed_loop import VerifyResult
from aac.self_model import ActionRequest
from experiments.governed_loop_slice import _self_model

VR = VerifyResult(is_effective=True, confidence=0.9, evidence_count=1, interventions=6)


class StratificationSeal(unittest.TestCase):        # I7
    def test_only_fresh_vi_counts(self):
        led = BeliefLedger()
        led.record_verified("causal:0:1", evidence=3)
        led.record_correlational("causal:0:2", evidence=1_000_000, confidence=0.4, group="g0")
        led.record_organ_prior("causal:0:3", confidence=0.4, group="g0")
        self.assertEqual(stratified_evidence(VR, ("causal:0:1",), led), 1 + 3)
        self.assertEqual(stratified_evidence(VR, ("causal:0:2",), led), 1)   # 1e6 correlational -> 0
        self.assertEqual(stratified_evidence(VR, ("causal:0:3",), led), 1)
        self.assertEqual(stratified_evidence(VR, (), led), 1)

    def test_stale_and_unknown_vi_does_not_count(self):
        led = BeliefLedger()
        led.record_verified("causal:0:1", evidence=3)
        led.demote(("causal:0:1",))
        self.assertEqual(stratified_evidence(VR, ("causal:0:1",), led), 1)   # stale VI -> 0
        self.assertEqual(stratified_evidence(VR, ("causal:9:9",), led), 1)   # unknown -> 0

    def test_nonverified_confidence_monotone_cap(self):
        led = BeliefLedger()
        for _ in range(3):
            led.record_organ_prior("causal:0:4", confidence=0.49, group="g0")
        self.assertLessEqual(led.get("causal:0:4").confidence, CAP_NV)
        led.record_correlational("causal:0:4", evidence=5, confidence=0.49, group="g0")
        self.assertLessEqual(led.get("causal:0:4").confidence, CAP_NV)


class StratificationBite(unittest.TestCase):
    def test_correlational_changes_a_high_stakes_verdict_vs_control(self):
        # RR-0035 Stage-2 gate: stratification must BITE — same inputs, the unstratified
        # CONTROL assembly (counts all provenances) flips at least one high-stakes verdict.
        led = BeliefLedger()
        led.record_correlational("causal:0:5", evidence=9, confidence=0.4, group="g0")
        sm = _self_model()                      # tier 4: evidence>=1, conf>=0.6, approval
        gate = GovernedDecisionGate(sm)
        vr_thin = VerifyResult(True, 0.9, 0, 6)  # verified, confident, but ZERO evidence bound
        cited = ("causal:0:5",)

        def verdict(evidence_count):
            return gate.decide(ActionRequest(
                action="apply_lever:5", risk_tier=4, confidence=vr_thin.confidence,
                verified=True, evidence_count=evidence_count, approved=True)).verdict

        strat = verdict(stratified_evidence(vr_thin, cited, led))
        control = verdict(unstratified_evidence_CONTROL(vr_thin, cited, led))
        self.assertEqual(strat, ESCALATE)        # correlational junk cannot buy the evidence bar
        self.assertEqual(control, ALLOW)         # the control WOULD have allowed -> bite is real
        self.assertNotEqual(strat, control)


class ConflictA2(unittest.TestCase):             # I8 + I10
    def _conflicted(self):
        led = BeliefLedger()
        det = ConflictDetector(led)
        led.record_verified("causal:0:1", evidence=3, group="g0")
        led.record_organ_prior("causal:0:4", confidence=0.4, group="g0")   # contradiction injected
        return led, det, det.scan()

    def test_conflict_detected_and_privileges_stripped(self):
        led, det, conflicts = self._conflicted()
        self.assertEqual(conflicts, ("g0",))
        self.assertTrue(led.in_conflict("causal:0:1"))
        self.assertTrue(led.in_conflict("causal:0:4"))
        # I8: while in conflict, NEITHER claim contributes evidence — even the verified one
        self.assertEqual(stratified_evidence(VR, ("causal:0:1",), led), 1)
        self.assertEqual(stratified_evidence(VR, ("causal:0:4",), led), 1)
        self.assertFalse(led.known_fresh("causal:0:1"))   # not rankable as fresh either

    def test_fresh_verification_converges_to_intervention_verified(self):
        led, det, _ = self._conflicted()
        led.record_verified("causal:0:1", evidence=4, group="g0")   # re-verification event
        det.resolve()
        self.assertFalse(led.in_conflict("causal:0:1"))
        self.assertEqual(led.get("causal:0:1").kind, FACT)          # converged winner
        self.assertNotEqual(led.get("causal:0:4").kind, FACT)       # loser demoted
        self.assertTrue(led.get("causal:0:4").stale)
        self.assertEqual(stratified_evidence(VR, ("causal:0:1",), led), 1 + 4)

    def test_vi_vs_vi_double_stales_never_silent_preference(self):
        led = BeliefLedger()
        det = ConflictDetector(led)
        led.record_verified("causal:0:1", evidence=3, group="g0")   # pre-flip truth
        led.record_verified("causal:0:3", evidence=3, group="g0")   # post-flip truth
        det.scan()
        v = det.resolve()
        self.assertTrue(led.get("causal:0:1").stale)                # BOTH stale
        self.assertTrue(led.get("causal:0:3").stale)
        self.assertTrue(v["reverify_required"])                     # escalate-grade, not silent

    def test_conflict_events_audited(self):
        events = []
        led = BeliefLedger(observe=events.append)
        det = ConflictDetector(led)
        led.record_verified("causal:0:1", evidence=3, group="g0")
        led.record_organ_prior("causal:0:4", confidence=0.4, group="g0")
        det.scan()
        self.assertIn("belief_conflict", [e.get("event") for e in events])


class PoisoningFalsifier(unittest.TestCase):     # I9
    def test_thousand_inbounds_writes_cannot_move_high_stakes_verdict(self):
        sm = _self_model()
        gate = GovernedDecisionGate(sm)
        vr_thin = VerifyResult(True, 0.9, 0, 6)

        def verdict(led, cited):
            return gate.decide(ActionRequest(
                action="apply_lever:5", risk_tier=4, confidence=vr_thin.confidence,
                verified=True, evidence_count=stratified_evidence(vr_thin, cited, led),
                approved=True)).verdict

        clean = BeliefLedger()
        poisoned = BeliefLedger()
        for _ in range(1000):                    # adversarial organ: many in-bounds writes
            poisoned.record_organ_prior("causal:0:5", confidence=0.49, group="g0")
            poisoned.record_correlational("causal:0:5", evidence=7, confidence=0.49, group="g0")
        self.assertEqual(verdict(poisoned, ("causal:0:5",)), verdict(clean, ("causal:0:5",)))
        self.assertLessEqual(poisoned.get("causal:0:5").confidence, CAP_NV)

    def test_detector_fires_and_refuses_after_budget(self):
        events = []
        led = BeliefLedger(observe=events.append)
        for _ in range(W_NV + 3):
            led.record_organ_prior("causal:0:5", confidence=0.3, group="g0")
        names = [e.get("event") for e in events]
        self.assertIn("belief_poisoning_suspect", names)             # standing detector fired
        count_at_freeze = led.nonverified_writes("causal:0:5")
        led.record_organ_prior("causal:0:5", confidence=0.3, group="g0")
        self.assertEqual(led.nonverified_writes("causal:0:5"), count_at_freeze)  # write refused
        led.record_verified("causal:0:5", evidence=3, group="g0")
        self.assertEqual(led.get("causal:0:5").kind, FACT)           # verify path unaffected


if __name__ == "__main__":
    unittest.main()


class LoopWiring(unittest.TestCase):
    def test_evidence_fn_is_consumed_by_both_selection_paths(self):
        # a stub assembly returning 0 must flip a low-stakes verdict from acted to
        # VERIFY_MORE-starve (tier 1 requires evidence>=1) in BOTH selection modes —
        # proving the wiring is real, not decorative (Hard Boundary #16).
        import random as _r
        from aac.governed_loop import GovernedLoop, TaskSpec
        from aac.shell import CorrigibilityShell
        from experiments.governed_loop_slice import (
            CausalLeverEnv, SimulatedProposer, InterventionVerifier, LeverActuator,
        )
        for mode in ("first_passer", "argmax"):
            for ev_fn, expect_acted in ((None, True), (lambda c, v, t: 0, False)):
                env = CausalLeverEnv(_r.Random(5))
                loop = GovernedLoop(
                    gate=GovernedDecisionGate(_self_model()),
                    proposer=SimulatedProposer(env, 1.0, _r.Random(12)),
                    verifier=InterventionVerifier(env, _r.Random(18)),
                    actuator=LeverActuator(env), shell_view=CorrigibilityShell().view(),
                    verify_budget=6, evidence_fn=ev_fn, selection=mode,
                )
                res = loop.run_task(TaskSpec("t", risk_tier=1))
                self.assertEqual(res.status == "acted", expect_acted, f"{mode} ev_fn={ev_fn}")
