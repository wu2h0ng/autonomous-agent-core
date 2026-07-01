"""RR-0032 governed-decision seam — OS-side acceptance + Trusted Loop integration (R0–R3 wire).

The five invariants on the native reference client, the RPC-stub boundary, and the additive wire into
TrustedLoopRuntime (DENY blocks; ALLOW/None unchanged; ESCALATE forces approval). No sibling-repo import.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
    ROOT / "action_connectors",
    ROOT / "apps" / "api_server" / "src",
):
    sys.path.insert(0, str(_p))

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    BlockCode,
    MetricContract,
    ProviderContract,
    ProviderKind,
    SQLTemplate,
)
from agent_os_contracts.governance_decision_seam import (  # noqa: E402
    GovernanceDecisionRequest,
    GovernanceDecisionResponse,
    VerifiedCandidate,
    SEAM_CONTRACT_VERSION,
    ALLOW,
    ESCALATE,
    DENY,
    VERIFY_MORE,
    request_to_json,
    request_from_json,
    response_to_json,
    response_from_json,
)
from agent_os_core import (  # noqa: E402
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.governance_decision_seam import (  # noqa: E402
    CohortABVerifier,
    GovernanceDecisionClient,
    LocalGovernanceDecisionClient,
    RemoteGovernanceDecisionClient,
    verify_candidates,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402


class _Verifier(CohortABVerifier):
    def __init__(self, effective: set[str]) -> None:
        self.eff = effective

    def verify(self, action: str):
        e = action in self.eff
        return (e, 0.9 if e else 0.0, 3 if e else 0)


class _FakeShell:
    def __init__(self, paused: bool = False) -> None:
        self.paused = paused
        self.events: list = []

    def observe(self, payload) -> None:
        self.events.append(payload)


def _client(effective=("good",), **kw) -> LocalGovernanceDecisionClient:
    return LocalGovernanceDecisionClient(_Verifier(set(effective)), **kw)


def _req(**kw) -> GovernanceDecisionRequest:
    base = dict(task_id="t", risk_tier="R1", candidate_actions=("bad", "good"), approved=False)
    base.update(kw)
    return GovernanceDecisionRequest(**base)


class LocalClientInvariants(unittest.TestCase):
    def test_1_act_only_on_verified(self):
        r = _client().decide(_req(candidate_actions=("bad", "good")))
        self.assertEqual(r.verdict, ALLOW)
        self.assertEqual(r.chosen_action, "good")
        r2 = _client().decide(_req(candidate_actions=("bad",)))
        self.assertNotEqual(r2.verdict, ALLOW)

    def test_2_high_stakes_gated(self):
        self.assertEqual(
            _client()
            .decide(_req(risk_tier="R4", candidate_actions=("good",), approved=False))
            .verdict,
            ESCALATE,
        )
        self.assertEqual(
            _client()
            .decide(_req(risk_tier="R4", candidate_actions=("good",), approved=True))
            .verdict,
            ALLOW,
        )

    def test_3_c7_paused_denies(self):
        c = _client(shell_view=_FakeShell(paused=True))
        self.assertEqual(c.decide(_req(candidate_actions=("good",))).verdict, DENY)

    def test_4_deterministic(self):
        a = _client().decide(_req())
        b = _client().decide(_req())
        self.assertEqual((a.verdict, a.chosen_action), (b.verdict, b.chosen_action))

    def test_5_audit_ref_present(self):
        self.assertTrue(_client().decide(_req()).audit_ref)

    def test_contract_version_rejected(self):
        r = _client().decide(_req(contract_version="2.0.0"))
        self.assertEqual(r.verdict, DENY)

    def test_json_round_trip(self):
        req = _req()
        self.assertEqual(request_from_json(request_to_json(req)), req)
        resp = _client().decide(req)
        self.assertEqual(response_from_json(response_to_json(resp)), resp)


class RemoteClientStub(unittest.TestCase):
    def test_no_transport_raises(self):
        with self.assertRaises(NotImplementedError):
            RemoteGovernanceDecisionClient().decide(_req())

    def test_transport_round_trips_contract(self):
        # a fake transport that echoes a fixed JSON response proves the client speaks the wire contract
        def transport(req_json: str) -> str:
            return response_to_json(
                GovernanceDecisionResponse("t", ALLOW, "good", 0.9, "ok", "ref")
            )

        r = RemoteGovernanceDecisionClient(transport).decide(_req())
        self.assertEqual(r.verdict, ALLOW)
        self.assertEqual(r.chosen_action, "good")

    def test_rejects_invalid_verdict_from_transport(self):
        def transport(req_json: str) -> str:
            return response_to_json(
                GovernanceDecisionResponse("t", "AUTO_EXECUTE", None, 0.9, "ok", "ref")
            )

        with self.assertRaisesRegex(ValueError, "invalid governance decision verdict"):
            RemoteGovernanceDecisionClient(transport).decide(_req())

    def test_rejects_mismatched_task_id_from_transport(self):
        def transport(req_json: str) -> str:
            return response_to_json(
                GovernanceDecisionResponse("other-task", ALLOW, "good", 0.9, "ok", "ref")
            )

        with self.assertRaisesRegex(ValueError, "governance decision task mismatch"):
            RemoteGovernanceDecisionClient(transport).decide(_req())

    def test_rejects_incompatible_contract_version_from_transport(self):
        def transport(req_json: str) -> str:
            return response_to_json(
                GovernanceDecisionResponse(
                    "t", DENY, None, 0.0, "old", "ref", contract_version="2.0.0"
                )
            )

        with self.assertRaisesRegex(ValueError, "incompatible governance decision contract"):
            RemoteGovernanceDecisionClient(transport).decide(_req())

    def test_rejects_missing_audit_ref_from_transport(self):
        def transport(req_json: str) -> str:
            return response_to_json(GovernanceDecisionResponse("t", ALLOW, "good", 0.9, "ok", ""))

        with self.assertRaisesRegex(ValueError, "governance decision audit_ref required"):
            RemoteGovernanceDecisionClient(transport).decide(_req())


# ---- integration: additive wire into the real TrustedLoopRuntime ----


def _connector_registry() -> ActionConnectorRegistry:
    reg = ActionConnectorRegistry()
    reg.register(
        ManualReviewConnector(),
        ActionConnectorContract(
            connector_name="manual_review",
            display_name="Manual Review",
            supported_action_types=("propose", "execute"),
            supports_snapshot=False,
            supports_rollback=False,
            compensating_action_description=None,
            risk_ceiling="R5",
            owner="system",
        ),
    )
    return reg


def _runtime(client=None) -> TrustedLoopRuntime:
    metric = MetricContract(
        metric_name="gmv",
        display_name="GMV",
        definition="Gross merchandise value.",
        owner="revenue_ops",
        unit="CNY",
        allowed_schemas=("sales",),
    )
    template = SQLTemplate(
        template_id="gmv_daily",
        metric_name="gmv",
        sql="select 1 from sales.orders where order_date >= :start_date and order_date < :end_date limit :limit",
        required_parameters=("start_date", "end_date", "limit"),
    )
    return TrustedLoopRuntime(
        metric_contract=metric,
        sql_template=template,
        query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "gmv": 1.0}]),
        semantic_registry=SemanticRegistry(metric_contracts=(metric,)),
        provider_registry=ProviderRegistry(
            (
                ProviderContract(
                    provider_id="provider-sales",
                    kind=ProviderKind.WAREHOUSE,
                    name="sales",
                    owner="revenue_ops",
                    allowed_schemas=("sales",),
                ),
            )
        ),
        connector_registry=_connector_registry(),
        governance_decision_client=client,
    )


class _FixedClient(GovernanceDecisionClient):
    def __init__(self, verdict: str) -> None:
        self.verdict = verdict

    def decide(self, req: GovernanceDecisionRequest) -> GovernanceDecisionResponse:
        chosen = "act" if self.verdict == ALLOW else None
        return GovernanceDecisionResponse(
            req.task_id, self.verdict, chosen, 0.9, f"fixed:{self.verdict}", "ref-int"
        )


class _RemoteInvalidVerdictClient(RemoteGovernanceDecisionClient):
    def __init__(self) -> None:
        super().__init__(
            lambda _body: response_to_json(
                GovernanceDecisionResponse(
                    task_id="t",
                    verdict="AUTO_EXECUTE",
                    chosen_action=None,
                    confidence=0.9,
                    reason="bad remote verdict secret-token",
                    audit_ref="ref-bad",
                )
            )
        )


class _RemoteSecretReasonClient(RemoteGovernanceDecisionClient):
    def __init__(self, verdict: str) -> None:
        def _transport(body: str) -> str:
            req = request_from_json(body)
            return response_to_json(
                GovernanceDecisionResponse(
                    task_id=req.task_id,
                    verdict=verdict,
                    chosen_action=None,
                    confidence=0.8,
                    reason="operator note contains secret-token and raw vendor payload",
                    audit_ref="remote-audit-ref-safe",
                )
            )

        super().__init__(_transport)


_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


class TrustedLoopSeamWire(unittest.TestCase):
    def test_deny_blocks_the_loop(self):
        outcome = _runtime(_FixedClient(DENY)).evaluate("GMV", _PARAMS)
        self.assertTrue(outcome.blocked)
        self.assertEqual(outcome.block.code, BlockCode.GOVERNANCE_DENIED)
        self.assertEqual(outcome.block.stage, "governed_decision")

    def test_allow_does_not_block(self):
        outcome = _runtime(_FixedClient(ALLOW)).evaluate("GMV", _PARAMS)
        self.assertFalse(outcome.blocked)

    def test_no_client_is_unchanged(self):
        # default None -> the seam is skipped; the loop is not governance-blocked
        outcome = _runtime(None).evaluate("GMV", _PARAMS)
        self.assertFalse(outcome.blocked)

    def test_escalate_records_governed_decision(self):
        # ESCALATE -> the loop tightens (forces approval); the decision is recorded, loop not denied
        outcome = _runtime(_FixedClient(ESCALATE)).evaluate("GMV", _PARAMS)
        self.assertFalse(outcome.blocked)

    def test_unknown_verdict_forces_approval_without_raw_verdict_leak(self):
        outcome = _runtime(_FixedClient("AUTO_EXECUTE")).evaluate("GMV", _PARAMS)

        self.assertFalse(outcome.blocked)
        result = outcome.result
        self.assertIsNotNone(result)
        self.assertEqual(result.action_result["status"], "awaiting_approval")
        self.assertTrue(result.action_proposal.approval_required)
        trace_steps = [event.step for event in result.trace_events]
        self.assertIn("governed_decision", trace_steps)
        self.assertIn("awaiting_approval", trace_steps)
        self.assertNotIn("connector_execute", trace_steps)
        governed_payload = next(
            event.payload for event in result.trace_events if event.step == "governed_decision"
        )
        self.assertEqual(governed_payload["verdict"], VERIFY_MORE)
        self.assertEqual(governed_payload["reason"], "governance decision invalid verdict")
        trace_blob = repr(result.trace_events)
        self.assertNotIn("AUTO_EXECUTE", trace_blob)

    def test_invalid_remote_response_forces_approval_without_raw_response_leak(self):
        outcome = _runtime(_RemoteInvalidVerdictClient()).evaluate("GMV", _PARAMS)

        self.assertFalse(outcome.blocked)
        result = outcome.result
        self.assertIsNotNone(result)
        self.assertEqual(result.action_result["status"], "awaiting_approval")
        self.assertTrue(result.action_proposal.approval_required)
        trace_steps = [event.step for event in result.trace_events]
        self.assertIn("governed_decision", trace_steps)
        self.assertIn("awaiting_approval", trace_steps)
        self.assertNotIn("connector_execute", trace_steps)
        governed_payload = next(
            event.payload for event in result.trace_events if event.step == "governed_decision"
        )
        self.assertEqual(governed_payload["verdict"], VERIFY_MORE)
        self.assertEqual(governed_payload["reason"], "governance decision client unavailable")
        self.assertEqual(governed_payload["client_error_code"], "ValueError")
        trace_blob = repr(result.trace_events)
        self.assertNotIn("AUTO_EXECUTE", trace_blob)
        self.assertNotIn("bad remote verdict", trace_blob)
        self.assertNotIn("secret-token", trace_blob)

    def test_remote_escalate_records_safe_reason_projection_without_raw_reason(self):
        outcome = _runtime(_RemoteSecretReasonClient(ESCALATE)).evaluate("GMV", _PARAMS)

        self.assertFalse(outcome.blocked)
        result = outcome.result
        self.assertIsNotNone(result)
        self.assertTrue(result.action_proposal.approval_required)
        governed_payload = next(
            event.payload for event in result.trace_events if event.step == "governed_decision"
        )
        self.assertEqual(governed_payload["verdict"], ESCALATE)
        self.assertEqual(governed_payload["reason"], "governance decision reason withheld")
        self.assertEqual(governed_payload["audit_ref"], "remote-audit-ref-safe")
        self.assertEqual(governed_payload["trace_id"], result.evidence_chain.trace_id)
        self.assertEqual(
            governed_payload["evidence_chain_id"], result.evidence_chain.evidence_chain_id
        )
        trace_blob = repr(result.trace_events)
        self.assertNotIn("operator note", trace_blob)
        self.assertNotIn("raw vendor payload", trace_blob)
        self.assertNotIn("secret-token", trace_blob)

    def test_remote_deny_blocks_with_safe_reason_projection_in_trace_and_block(self):
        runtime = _runtime(_RemoteSecretReasonClient(DENY))
        outcome = runtime.evaluate("GMV", _PARAMS)

        self.assertTrue(outcome.blocked)
        self.assertEqual(outcome.block.code, BlockCode.GOVERNANCE_DENIED)
        self.assertEqual(outcome.block.details, ("governance decision reason withheld",))
        block_blob = repr(outcome.block)
        self.assertNotIn("operator note", block_blob)
        self.assertNotIn("raw vendor payload", block_blob)
        self.assertNotIn("secret-token", block_blob)
        stored = runtime.trace_store.get(outcome.block.trace_id)
        self.assertIsNotNone(stored)
        governed_payload = next(
            event.payload for event in stored.events if event.step == "governed_decision"
        )
        evidence_payload = next(
            event.payload for event in stored.events if event.step == "evidence_chain"
        )
        self.assertEqual(governed_payload["verdict"], DENY)
        self.assertEqual(governed_payload["reason"], "governance decision reason withheld")
        self.assertEqual(governed_payload["audit_ref"], "remote-audit-ref-safe")
        self.assertEqual(governed_payload["trace_id"], outcome.block.trace_id)
        self.assertEqual(
            governed_payload["evidence_chain_id"], evidence_payload["evidence_chain_id"]
        )
        trace_blob = repr(stored.events)
        self.assertNotIn("operator note", trace_blob)
        self.assertNotIn("raw vendor payload", trace_blob)
        self.assertNotIn("secret-token", trace_blob)


class TransportAndFallback(unittest.TestCase):
    """RR-0032 #1 steps 4-5: HTTP transport + never-block fallback (ADR-0047)."""

    def test_fallback_used_when_primary_fails(self):
        from agent_os_core.governance_decision_seam import FallbackGovernanceDecisionClient

        class _Raising(GovernanceDecisionClient):
            def decide(self, req):
                raise TimeoutError("remote brain slow")

        client = FallbackGovernanceDecisionClient(_Raising(), _client(effective=("good",)))
        r = client.decide(_req(candidate_actions=("bad", "good")))
        self.assertEqual(r.verdict, ALLOW)  # degraded to local governance, did NOT crash/block

    def test_primary_used_when_it_succeeds(self):
        from agent_os_core.governance_decision_seam import FallbackGovernanceDecisionClient

        client = FallbackGovernanceDecisionClient(_FixedClient(DENY), _client(effective=("good",)))
        self.assertEqual(client.decide(_req()).verdict, DENY)  # primary wins when healthy

    def test_http_transport_round_trip(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        from agent_os_core.governance_decision_seam import (
            http_transport,
            RemoteGovernanceDecisionClient,
        )

        fixed = response_to_json(GovernanceDecisionResponse("t", ALLOW, "good", 0.9, "ok", "ref"))

        class _Fake(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                out = fixed.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client = RemoteGovernanceDecisionClient(
                http_transport(f"http://127.0.0.1:{port}/decide", 5.0)
            )
            r = client.decide(_req())
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(r.verdict, ALLOW)
        self.assertEqual(r.chosen_action, "good")

    def test_dead_endpoint_falls_back(self):
        from agent_os_core.governance_decision_seam import (
            http_transport,
            RemoteGovernanceDecisionClient,
            FallbackGovernanceDecisionClient,
        )

        # nothing listening on this port -> connection refused -> fallback (never blocks the loop)
        remote = RemoteGovernanceDecisionClient(http_transport("http://127.0.0.1:9/decide", 0.5))
        client = FallbackGovernanceDecisionClient(remote, _client(effective=("good",)))
        r = client.decide(_req(candidate_actions=("bad", "good")))
        self.assertEqual(r.verdict, ALLOW)  # degraded to local, did not raise


class V11_OSVerifiesBeforeSending(unittest.TestCase):
    """v1.1 (RR-0032 "OS verifies -> core governs"): the OS verifies locally, the remote only governs."""

    def test_verify_candidates_helper(self):
        vcs = verify_candidates(_Verifier({"good"}), ("bad", "good"))
        self.assertEqual(len(vcs), 2)
        self.assertEqual((vcs[0].action, vcs[0].verified), ("bad", False))
        self.assertEqual((vcs[1].action, vcs[1].verified), ("good", True))

    def test_remote_client_verifies_os_side_before_wire(self):
        # capture what crosses the wire: it MUST already carry the OS verification
        captured = {}

        def transport(req_json: str) -> str:
            captured["req"] = request_from_json(req_json)
            return response_to_json(
                GovernanceDecisionResponse("t", ALLOW, "good", 0.9, "ok", "ref")
            )

        client = RemoteGovernanceDecisionClient(transport, verifier=_Verifier({"good"}))
        client.decide(_req(candidate_actions=("bad", "good")))
        sent = captured["req"]
        self.assertEqual(len(sent.verified_candidates), 2)  # OS verified before sending
        self.assertTrue(any(vc.verified and vc.action == "good" for vc in sent.verified_candidates))
        self.assertTrue(
            all(not vc.verified for vc in sent.verified_candidates if vc.action == "bad")
        )

    def test_contract_v11_json_round_trip(self):
        req = GovernanceDecisionRequest(
            task_id="t",
            risk_tier="R1",
            candidate_actions=("good",),
            verified_candidates=(VerifiedCandidate("good", True, 0.9, 3),),
        )
        self.assertEqual(request_from_json(request_to_json(req)), req)

    def test_version_is_1_1(self):
        self.assertTrue(SEAM_CONTRACT_VERSION.startswith("1.1"))


if __name__ == "__main__":
    unittest.main()
