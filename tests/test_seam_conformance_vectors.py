"""Cross-repo seam conformance vectors — nested (reference brain) side (RR-0037 O1).

The SAME vector file is duplicated in the OS repo; each side pins its copy's sha256.
Editing vectors = consciously updating both copies + both pins. Class-level parity
(act / approval / block) is the contract; verdict labels may differ (VERIFY_MORE vs
ESCALATE both force approval upstream). This mechanically prevents the drift class
caught in the M4 review (Local diverging from the brain on R4-approved).
"""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from aac.governed_gate import GovernedDecisionGate, ALLOW, DENY
from aac.self_model import AgentSelfModel
from aac.seam_contract import SeamProducer, GovernedDecisionRequest, VerifiedCandidate, SEAM_CONTRACT_VERSION
from aac.shell import CorrigibilityShell

VECTORS = Path(__file__).parent / "seam_conformance_vectors.v1.json"
VECTORS_SHA256 = "dfd15e6b727bcc296708444f7e9e0271f35c4ed7f3aa640e295891ea5bd648a2"

_CLASS = {ALLOW: "act", "VERIFY_MORE": "approval", "ESCALATE": "approval", DENY: "block"}


def _producer(cfg, paused: bool) -> SeamProducer:
    sm = AgentSelfModel(
        allowed_tools=frozenset(), denied_tools=frozenset(), risk_ceiling=5,
        approval_required_at_or_above=int(cfg["approval_required_at_or_above"][1]),
        evidence_requirements={t: (0 if t == 0 else cfg["evidence_floor"]) for t in range(6)},
        confidence_thresholds={t: (cfg["high_stakes_confidence_floor"] if t >= 4
                                   else (0.0 if t == 0 else cfg["low_stakes_confidence_floor"]))
                               for t in range(6)},
    )
    shell = CorrigibilityShell()
    if paused:
        shell.op_pause()
    class _NoVerifier:
        def verify(self, cand):
            raise AssertionError("vectors are all OS-verified; self-verify path must not run")
    return SeamProducer(GovernedDecisionGate(sm), _NoVerifier(), shell=shell)


class ConformanceVectors(unittest.TestCase):
    def test_pinned_sha(self):
        self.assertEqual(hashlib.sha256(VECTORS.read_bytes()).hexdigest(), VECTORS_SHA256,
                         "vectors drifted: update BOTH repos' copies + pins consciously")

    def test_brain_matches_every_vector(self):
        spec = json.loads(VECTORS.read_text())
        for case in spec["cases"]:
            req = dict(case["request"])
            req.setdefault("contract_version", spec["contract_version"])
            req["verified_candidates"] = tuple(VerifiedCandidate(**vc) for vc in req["verified_candidates"])
            resp = _producer(spec["gate_config"], case.get("shell_paused", False)).handle(
                GovernedDecisionRequest(**req))
            self.assertEqual(_CLASS[resp.verdict], case["expect_class"], case["name"])
            if case["expect_class"] == "act":
                self.assertEqual(resp.chosen_action, case["expect_chosen"], case["name"])


if __name__ == "__main__":
    unittest.main()
