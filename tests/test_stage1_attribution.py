"""STAGE-1 contract tests — FailureAttributor + belief invalidation (formal model bcd02bd).

Written BEFORE the mechanism files exist (Hard Boundary #17): these fail with ImportError
against the pre-Stage-1 substrate, and each failure is tied to the absence of the target
implementation, not to fixture constants.

Locks (formal model section 2/3):
  A3    mechanism-flip: after demotion, NO acted step cites the demoted claim (retry-same is
        structurally impossible); the attributor arm recovers on the new cause; the knockout
        arm (attributor disconnected) MUST fail this — else attribution is not load-bearing.
  A6-2  frozen-ledger ablation: freezing demotion loses the recovery improvement.
  CC    cheap-control: precise demotion beats decay-all-and-reverify on intervention cost at
        equal safety (the I2 precision property doing real work across two task families).
  I2/I3/I6  demote-precision, one-way lattice, UNIDENTIFIED protection.
"""

from __future__ import annotations

import unittest

from aac.belief_ledger import BeliefLedger, FACT, HYPOTHESIS, REFUTED, UNIDENTIFIED
from aac.failure_attributor import attribute, AttributionVerdict
from experiments.stage1_attribution_slice import run_episode, SEEDS_SMOKE


class LedgerInvariants(unittest.TestCase):
    def test_lattice_is_one_way(self):        # I3
        led = BeliefLedger()
        led.record_verified("causal:0:3", evidence=3)
        self.assertEqual(led.get("causal:0:3").kind, FACT)
        led.demote(("causal:0:3",))
        self.assertEqual(led.get("causal:0:3").kind, HYPOTHESIS)
        self.assertTrue(led.get("causal:0:3").stale)
        led.demote(("causal:0:3",))
        self.assertEqual(led.get("causal:0:3").kind, REFUTED)
        led.demote(("causal:0:3",))            # idempotent floor, never re-raises
        self.assertEqual(led.get("causal:0:3").kind, REFUTED)
        led.record_verified("causal:0:3", evidence=3)   # re-verification = fresh FACT via verify path
        self.assertEqual(led.get("causal:0:3").kind, FACT)
        self.assertFalse(led.get("causal:0:3").stale)

    def test_unidentified_protected_from_demotion(self):   # I6
        led = BeliefLedger()
        led.record_unidentified("causal:0:5")
        led.demote(("causal:0:5",))
        e = led.get("causal:0:5")
        self.assertEqual(e.provenance, UNIDENTIFIED)
        self.assertNotEqual(e.kind, REFUTED)   # "not measured" must never become "refuted"

    def test_demotion_is_precise(self):        # I2
        led = BeliefLedger()
        led.record_verified("causal:0:1", evidence=3)
        led.record_verified("causal:1:4", evidence=3)
        led.demote(("causal:0:1",))
        self.assertTrue(led.get("causal:0:1").stale)
        self.assertEqual(led.get("causal:1:4").kind, FACT)      # untouched family
        self.assertFalse(led.get("causal:1:4").stale)


class AttributionTree(unittest.TestCase):
    def test_no_fault_when_outcome_meets_expectation(self):
        led = BeliefLedger()
        led.record_verified("causal:0:2", evidence=3)
        v = attribute(cited=("causal:0:2",), observed=1.0, expected=1.0, ledger=led)
        self.assertEqual(v.faulty, "NO_FAULT")
        self.assertEqual(v.demote_ids, ())

    def test_stale_belief_names_exactly_the_cited_claims(self):
        led = BeliefLedger()
        led.record_verified("causal:0:2", evidence=3)
        led.record_verified("causal:1:4", evidence=3)
        v = attribute(cited=("causal:0:2",), observed=0.0, expected=1.0, ledger=led)
        self.assertEqual(v.faulty, "STALE_BELIEF")
        self.assertEqual(v.demote_ids, ("causal:0:2",))          # I2: never the uncited claim

    def test_uncited_failure_is_shifted_mechanism_no_demotion(self):
        led = BeliefLedger()
        v = attribute(cited=(), observed=0.0, expected=1.0, ledger=led)
        self.assertEqual(v.faulty, "SHIFTED_MECHANISM")
        self.assertEqual(v.demote_ids, ())

    def test_unknown_claim_is_unattributable_never_silent(self):
        led = BeliefLedger()
        v = attribute(cited=("causal:9:9",), observed=0.0, expected=1.0, ledger=led)
        self.assertEqual(v.faulty, "UNATTRIBUTABLE")
        self.assertTrue(v.escalate)

    def test_deterministic(self):              # I4
        led = BeliefLedger()
        led.record_verified("causal:0:2", evidence=3)
        a = attribute(cited=("causal:0:2",), observed=0.0, expected=1.0, ledger=led)
        b = attribute(cited=("causal:0:2",), observed=0.0, expected=1.0, ledger=led)
        self.assertEqual(a, b)


class A3MechanismFlip(unittest.TestCase):
    def test_attributor_arm_never_reacts_on_demoted_claim(self):
        # A3 structural core: once causal:<g>:<c> is demoted, no later acted step cites it.
        for seed in SEEDS_SMOKE:
            ep = run_episode(seed, arm="attributor")
            for act in ep["acts_after_demotion"]:
                self.assertNotIn(ep["demoted_claim"], act["cited"],
                                 f"seed {seed}: retry-same on a demoted claim")

    def test_attributor_recovers_knockout_fails_a3(self):
        # load-bearing check: the knockout arm (attributor disconnected) must violate the A3
        # property somewhere in the batch — identical arms would mean attribution is cosmetic.
        rec_att = sum(run_episode(s, arm="attributor")["recovered"] for s in SEEDS_SMOKE)
        ko_violations = sum(
            1 for s in SEEDS_SMOKE
            for act in run_episode(s, arm="knockout")["acts_after_demotion"]
            if run_episode(s, arm="knockout")["demoted_claim"] in act["cited"]
        )
        self.assertGreater(rec_att, 0)
        self.assertGreater(ko_violations, 0,
                           "knockout arm never retried the stale claim: attribution is not load-bearing")


class A6FrozenLedger(unittest.TestCase):
    def test_frozen_ledger_loses_recovery_improvement(self):
        rec_live = sum(run_episode(s, arm="attributor")["recovered"] for s in SEEDS_SMOKE)
        rec_frozen = sum(run_episode(s, arm="frozen_ledger")["recovered"] for s in SEEDS_SMOKE)
        self.assertGreater(rec_live, rec_frozen,
                           "improvement survives a frozen ledger: hidden channel")


class CheapControlGate(unittest.TestCase):
    def test_precise_demotion_beats_decay_all_on_cost(self):
        # Stage-1 could-fail gate: across the batch, the attributor must recover at least as
        # often as decay-all while spending strictly fewer interventions on the UNAFFECTED
        # task family (decay-all wipes family-B knowledge; precise demotion does not).
        att_cost, dec_cost, att_rec, dec_rec = 0, 0, 0, 0
        for s in SEEDS_SMOKE:
            a = run_episode(s, arm="attributor")
            d = run_episode(s, arm="decay_all")
            att_cost += a["family_b_interventions_after_flip"]
            dec_cost += d["family_b_interventions_after_flip"]
            att_rec += a["recovered"]
            dec_rec += d["recovered"]
        self.assertGreaterEqual(att_rec, dec_rec)
        self.assertLess(att_cost, dec_cost,
                        "precise demotion no cheaper than decay-all: PARK per formal model section 3")


if __name__ == "__main__":
    unittest.main()
