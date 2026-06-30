"""Tests for the seam HTTP service (RR-0032 #1 step 1): handle_raw purity + a real socket round-trip."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.request

from aac.seam_service import SeamService, serve
from aac.seam_contract import SeamProducer, GovernedDecisionRequest, to_json
from aac.governed_gate import GovernedDecisionGate, ALLOW, ESCALATE, DENY
from aac.governed_loop import VerifyResult, Candidate
from aac.self_model import AgentSelfModel

TRUE = "lever:true"


class _Verifier:
    def verify(self, cand: Candidate) -> VerifyResult:
        eff = cand.action == TRUE
        return VerifyResult(eff, 0.9 if eff else 0.0, 3 if eff else 0, 1)


def _producer() -> SeamProducer:
    sm = AgentSelfModel(
        allowed_tools=frozenset(), denied_tools=frozenset(), risk_ceiling=5,
        approval_required_at_or_above=4, evidence_requirements={}, confidence_thresholds={1: 0.2, 4: 0.6},
    )
    return SeamProducer(GovernedDecisionGate(sm), _Verifier())


def _req(**kw) -> str:
    base = dict(task_id="t", risk_tier=1, candidate_actions=["bad", TRUE], approved=False)
    base.update(kw)
    return to_json(GovernedDecisionRequest(**base))


class HandleRaw(unittest.TestCase):
    def test_verified_allows(self):
        out = json.loads(_producer_service().handle_raw(_req()))
        self.assertEqual(out["verdict"], ALLOW)
        self.assertEqual(out["chosen_action"], TRUE)

    def test_high_stakes_escalates(self):
        out = json.loads(_producer_service().handle_raw(_req(risk_tier=4, candidate_actions=[TRUE])))
        self.assertEqual(out["verdict"], ESCALATE)

    def test_malformed_request_denies(self):
        out = json.loads(_producer_service().handle_raw("{not json"))
        self.assertEqual(out["verdict"], DENY)
        out2 = json.loads(_producer_service().handle_raw("{}"))  # missing fields
        self.assertEqual(out2["verdict"], DENY)


class HttpRoundTrip(unittest.TestCase):
    def test_real_post_decide(self):
        server = serve(_producer(), port=0)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/decide", data=_req().encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            body = urllib.request.urlopen(req, timeout=5).read().decode("utf-8")
        finally:
            server.shutdown()
            server.server_close()
        out = json.loads(body)
        self.assertEqual(out["verdict"], ALLOW)
        self.assertEqual(out["chosen_action"], TRUE)
        self.assertTrue(out["audit_ref"])


def _producer_service() -> SeamService:
    return SeamService(_producer())


if __name__ == "__main__":
    unittest.main()
