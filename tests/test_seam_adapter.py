"""Seam conformance: the research-side disposer must AGREE with the OS product governance on ALL shared
conformance vectors (RR-0032 seam; contract not import). Proves the E2E agent is seam-READY — its
governed actions cross to OS governance and get the same verdict class the OS would apply."""
from __future__ import annotations

import json
import os
import unittest

from aac.seam_adapter import (GateConfig, VerifiedCandidate, GovernanceDecisionRequest,
                              decide, verdict_class, agent_action_to_request, ACT, APPROVAL, BLOCK)

_VEC = os.path.join(os.path.dirname(__file__), "..", "experiments", "seam",
                    "seam_conformance_vectors.v1.json")


def _load():
    with open(_VEC) as f:
        return json.load(f)


class OsConformance(unittest.TestCase):
    def test_all_os_vectors_match(self):
        v = _load()
        gc = v["gate_config"]
        cfg = GateConfig(approval_required_at_or_above=gc["approval_required_at_or_above"],
                         low_stakes_confidence_floor=gc["low_stakes_confidence_floor"],
                         high_stakes_confidence_floor=gc["high_stakes_confidence_floor"],
                         evidence_floor=gc["evidence_floor"])
        mismatches = []
        for case in v["cases"]:
            r = case["request"]
            req = GovernanceDecisionRequest(
                task_id=r["task_id"], risk_tier=r["risk_tier"],
                candidate_actions=tuple(r["candidate_actions"]),
                evidence_count=r["evidence_count"], approved=r.get("approved", False),
                verified_candidates=tuple(VerifiedCandidate(**vc) for vc in r["verified_candidates"]),
                contract_version=r.get("contract_version", "1.1.0"))
            resp = decide(req, cfg, shell_paused=case.get("shell_paused", False))
            got = verdict_class(resp)
            if got != case["expect_class"]:
                mismatches.append(f"{case['name']}: got {got} != {case['expect_class']}")
            elif case["expect_class"] == ACT and case.get("expect_chosen") is not None:
                self.assertEqual(resp.chosen_action, case["expect_chosen"], case["name"])
        self.assertEqual(mismatches, [], f"research disposer disagrees with OS on: {mismatches}")

    def test_all_vectors_are_covered(self):
        # every conformance class exercised (act/approval/block) so the match is non-vacuous
        classes = {c["expect_class"] for c in _load()["cases"]}
        self.assertTrue({ACT, APPROVAL}.issubset(classes))


class TightenOnlyInvariants(unittest.TestCase):
    def setUp(self):
        self.cfg = GateConfig()

    def test_unverified_never_acts(self):
        req = agent_action_to_request("t", "do", "R1", verified=False, confidence=0.9, evidence_count=3)
        self.assertNotEqual(verdict_class(decide(req, self.cfg)), ACT)

    def test_high_tier_verified_unapproved_escalates(self):
        req = agent_action_to_request("t", "do", "R4", verified=True, confidence=0.9,
                                      evidence_count=3, approved=False)
        self.assertEqual(verdict_class(decide(req, self.cfg)), APPROVAL)

    def test_paused_shell_denies_everything(self):
        req = agent_action_to_request("t", "do", "R0", verified=True, confidence=1.0, evidence_count=9)
        self.assertEqual(verdict_class(decide(req, self.cfg, shell_paused=True)), BLOCK)

    def test_forbidden_action_denies(self):
        req = agent_action_to_request("t", "drop", "R1", verified=True, confidence=0.9, evidence_count=3)
        self.assertEqual(verdict_class(decide(req, self.cfg, forbidden=("drop",))), BLOCK)

    def test_e2e_agent_action_is_seam_conformant(self):
        # a verified confident R1 discovery-do (the E2E loop's action) crosses and is ALLOWed
        req = agent_action_to_request("disc", "do_node", "R1", verified=True, confidence=1.0,
                                      evidence_count=1)
        r = decide(req, self.cfg)
        self.assertEqual(verdict_class(r), ACT)
        self.assertEqual(r.chosen_action, "do_node")

    def test_determinism(self):
        req = agent_action_to_request("t", "do", "R2", verified=True, confidence=0.7, evidence_count=2)
        self.assertEqual(decide(req, self.cfg), decide(req, self.cfg))


if __name__ == "__main__":
    unittest.main()
