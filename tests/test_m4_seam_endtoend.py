"""M4 end-to-end conformance — governed_loop causal brain behind the seam at the WIRE.

Formal model: docs/pre_spec/M4-SEAM-ENDTOEND.FORMAL-MODEL-2026-07-03.md (b5f5083).

Stands up the REAL SeamService over HTTP and drives it with OS-contract-shaped JSON (the OS
field vocabulary: task_id / risk_tier "R0".."R5" / verified_candidates / contract_version),
WITHOUT importing any OS code (#19). Proves the 5 tighten-only invariants + version/fallback/
determinism at the wire, and in-process vs HTTP verdict parity (G-M4-1). This is the nested-
side M4-readiness evidence; the OS product wiring + real lever is the task-packet Codex scope.
"""
from __future__ import annotations

import json
import threading
import unittest
import urllib.request

from aac.governed_gate import GovernedDecisionGate, ALLOW, ESCALATE, DENY
from aac.self_model import AgentSelfModel
from aac.seam_contract import (
    SeamProducer, GovernedDecisionRequest, VerifiedCandidate, SEAM_CONTRACT_VERSION,
    to_json, response_from_json, request_from_json,
)
from aac.seam_service import SeamService, serve
from aac.shell import CorrigibilityShell


def _sm() -> AgentSelfModel:
    return AgentSelfModel(
        allowed_tools=frozenset(), denied_tools=frozenset(),
        risk_ceiling=5, approval_required_at_or_above=4,
        evidence_requirements={0: 0, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1},
        confidence_thresholds={0: 0.0, 1: 0.2, 2: 0.2, 3: 0.3, 4: 0.6, 5: 0.6})


class _NeverVerifier:
    def verify(self, cand):
        from aac.governed_loop import VerifyResult
        return VerifyResult(False, 0.0, 0, 1)


def _producer(shell=None) -> SeamProducer:
    return SeamProducer(GovernedDecisionGate(_sm()), _NeverVerifier(), shell=shell)


def _req(risk="R1", approved=False, verified=True, conf=0.9, ev=3, version=None):
    # OS-contract-shaped request: OS already verified the candidate ("OS verifies -> core governs")
    return GovernedDecisionRequest(
        task_id="lever-x", risk_tier=risk, candidate_actions=["apply_lever:2"],
        evidence_count=ev, approved=approved,
        verified_candidates=(VerifiedCandidate("apply_lever:2", verified, conf, ev),),
        contract_version=version or SEAM_CONTRACT_VERSION)


def _over_http(producer, request_json: str) -> str:
    server = serve(producer, port=0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        r = urllib.request.Request(f"http://127.0.0.1:{port}/decide",
                                   data=request_json.encode("utf-8"),
                                   headers={"Content-Type": "application/json"}, method="POST")
        return urllib.request.urlopen(r, timeout=5).read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()


class FiveInvariantsAtTheWire(unittest.TestCase):
    def test_inv1_acts_only_on_verified(self):
        # an UNVERIFIED candidate must never come back ALLOW
        resp = _producer().handle(_req(verified=False))
        self.assertNotEqual(resp.verdict, ALLOW)

    def test_inv2_high_stakes_never_auto_allowed(self):
        for tier in ("R4", "R5"):
            resp = _producer().handle(_req(risk=tier, approved=False, conf=0.9))
            self.assertEqual(resp.verdict, ESCALATE)      # >=R4 unapproved -> escalate, never ALLOW

    def test_inv3_c7_paused_only_denies(self):
        shell = CorrigibilityShell(); shell.op_pause()
        resp = _producer(shell=shell).handle(_req(risk="R1"))
        self.assertEqual(resp.verdict, DENY)              # paused shell can only tighten to DENY

    def test_inv4_deterministic(self):
        a = _producer().handle(_req())
        b = _producer().handle(_req())
        self.assertEqual((a.verdict, a.chosen_action), (b.verdict, b.chosen_action))

    def test_inv5_response_carries_audit_ref(self):
        resp = _producer().handle(_req())
        self.assertTrue(resp.audit_ref)                   # resolving audit ref present

    def test_version_mismatch_fail_closed(self):
        resp = _producer().handle(_req(version="99.0.0"))
        self.assertEqual(resp.verdict, DENY)              # incompatible major -> DENY, never adapt

    def test_low_stakes_verified_allows_and_acts(self):
        resp = _producer().handle(_req(risk="R1", conf=0.9, ev=3))
        self.assertEqual(resp.verdict, ALLOW)
        self.assertEqual(resp.chosen_action, "apply_lever:2")


class WireParityAndFallback(unittest.TestCase):
    def test_inprocess_vs_http_verdict_parity(self):    # G-M4-1
        for r in (_req(risk="R1"), _req(risk="R4"), _req(verified=False)):
            local = _producer().handle(r)
            wire = response_from_json(_over_http(_producer(), to_json(r)))
            self.assertEqual((local.verdict, local.chosen_action),
                             (wire.verdict, wire.chosen_action))

    def test_malformed_request_denies_never_crashes(self):
        out = response_from_json(_over_http(_producer(), "{not valid json"))
        self.assertEqual(out.verdict, DENY)               # never-block / fail-closed at the wire

    def test_json_round_trip_is_faithful(self):
        r = _req(risk="R2")
        self.assertEqual(request_from_json(to_json(r)).task_id, r.task_id)


if __name__ == "__main__":
    unittest.main()
