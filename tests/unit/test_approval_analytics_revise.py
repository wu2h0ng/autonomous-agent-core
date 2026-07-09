"""P2-A (ADR-0015): approval rubber-stamp analytics + the ``revise`` outcome.

These tests make the ADR-0014 choice-set mechanism falsifiable in production
(RR-0050 §7): they prove that a ``revise`` (approving a NON-recommended, in-choice-set
alternative) is measured as ``approved_revised`` and moves ``modify_rate`` /
``selection_concentration``, that a revise outside the surfaced choice set is refused
with ``CHOICE_SET_VIOLATION``, that a consumed approval cannot be re-decided, that
analytics is tenant-isolated and derived from records (no parallel counter), and that
the analytics read is refused for the external_report scope.

Every test is written to FAIL if the logic were bypassed (e.g. a revise miscounted as a
rubber-stamp, a hard-coded concentration, or the tenant filter dropped).
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _pkg in ("contracts", "os_core", "persistence"):
    sys.path.insert(0, str(ROOT / "packages" / _pkg / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_contracts import (  # noqa: E402
    ActionAlternative,
    ActionConnectorContract,
    ApprovalDecision,
    BlockCode,
    MetricContract,
    ProviderContract,
    ProviderKind,
    RiskLevel,
    SQLTemplate,
)
from agent_os_core import ProviderRegistry, SemanticRegistry, TrustedLoopRuntime  # noqa: E402
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.approval_lite import ChoiceSetViolationError  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from agent_os_core.trusted_loop import TrustedLoopBlocked  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

_RECOMMENDED = "raise_budget"
_OTHER = "hold_budget"


def _connector_registry() -> ActionConnectorRegistry:
    registry = ActionConnectorRegistry()
    registry.register(
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
    return registry


def _build_runtime() -> TrustedLoopRuntime:
    """A runtime whose approval lifecycle + analytics we exercise directly.

    We seed pending approvals through ``approval_runtime.create_pending`` and decide
    them through ``record_approval_decision`` — the same entry points the HTTP surface
    uses — without running the full data loop.
    """
    metric = MetricContract(
        metric_name="gmv",
        display_name="GMV",
        definition="Gross merchandise value over paid orders.",
        owner="revenue_ops",
        unit="CNY",
        allowed_schemas=("sales",),
    )
    template = SQLTemplate(
        template_id="gmv_daily",
        metric_name="gmv",
        sql="select 1 as gmv from sales.orders limit :limit",
        required_parameters=("limit",),
        required_time_parameters=(),
    )
    return TrustedLoopRuntime(
        metric_contract=metric,
        sql_template=template,
        query_executor=StaticQueryExecutor([{"gmv": 1}]),
        semantic_registry=SemanticRegistry(metric_contracts=(metric,)),
        provider_registry=ProviderRegistry(
            (
                ProviderContract(
                    provider_id="provider-sales",
                    kind=ProviderKind.WAREHOUSE,
                    name="sales warehouse",
                    owner="revenue_ops",
                    allowed_schemas=("sales",),
                ),
            )
        ),
        connector_registry=_connector_registry(),
    )


def _alternatives() -> tuple[ActionAlternative, ...]:
    return (
        ActionAlternative(
            action=_RECOMMENDED,
            rationale="verified driver",
            risk_level=RiskLevel.R3,
            recommended=True,
        ),
        ActionAlternative(
            action=_OTHER,
            rationale="keep spend flat",
            risk_level=RiskLevel.R1,
        ),
    )


def _seed_pending(
    runtime: TrustedLoopRuntime,
    approval_id: str,
    *,
    tenant_id: str = "default",
    risk_level: str = "R3",
    recommended_action: str = _RECOMMENDED,
    created_at: str | None = None,
) -> None:
    runtime.approval_runtime.create_pending(
        approval_id=approval_id,
        proposal_id=f"proposal-{approval_id}",
        approver_role="Business Owner",
        alternatives=_alternatives(),
        recommended_action=recommended_action,
        risk_level=risk_level,
        created_at=created_at,
        tenant_id=tenant_id,
    )


class ApprovalDecisionDerivationTest(unittest.TestCase):
    """The rubber-stamp classification is DERIVED, never self-reported."""

    def test_rubber_stamp_workload_reports_full_concentration(self) -> None:
        # Test 1: N approvals all taking the recommended option -> pure rubber-stamp.
        runtime = _build_runtime()
        for i in range(5):
            _seed_pending(runtime, f"a{i}")
            record, _ = runtime.record_approval_decision(approval_id=f"a{i}", outcome="approve")
            self.assertEqual(record.decision, ApprovalDecision.APPROVED_RECOMMENDED.value)
            self.assertEqual(record.selected_action, _RECOMMENDED)
            self.assertEqual(record.status, "approved")

        analytics = runtime.approval_runtime.analytics()
        self.assertEqual(analytics.counts.approved_recommended, 5)
        self.assertEqual(analytics.counts.approved_revised, 0)
        self.assertEqual(analytics.total, 5)
        # FAILS if a revise were miscounted as approve, or concentration hard-coded.
        self.assertEqual(analytics.selection_concentration, 1.0)
        self.assertEqual(analytics.modify_rate, 0.0)

    def test_revise_lowers_concentration_and_raises_modify_rate(self) -> None:
        # Test 2: 3 recommended-approvals + 1 revise -> concentration 0.75, modify 0.25.
        runtime = _build_runtime()
        for i in range(3):
            _seed_pending(runtime, f"rec{i}")
            runtime.record_approval_decision(approval_id=f"rec{i}", outcome="approve")

        _seed_pending(runtime, "rev0")
        revised, _ = runtime.record_approval_decision(
            approval_id="rev0", outcome="approve", selected_action=_OTHER
        )
        # The revise is classified as approved_revised, NOT folded into recommended.
        self.assertEqual(revised.decision, ApprovalDecision.APPROVED_REVISED.value)
        self.assertEqual(revised.selected_action, _OTHER)

        analytics = runtime.approval_runtime.analytics()
        self.assertEqual(analytics.counts.approved_recommended, 3)
        self.assertEqual(analytics.counts.approved_revised, 1)
        # Exact fractions asserted: FAILS if approved_revised folded into recommended.
        self.assertEqual(analytics.modify_rate, 0.25)
        self.assertEqual(analytics.selection_concentration, 0.75)

    def test_revise_to_action_outside_choice_set_is_refused(self) -> None:
        # Test 3: a revise naming an action not in ``alternatives`` -> CHOICE_SET_VIOLATION.
        runtime = _build_runtime()
        _seed_pending(runtime, "x0")
        with self.assertRaises(TrustedLoopBlocked) as ctx:
            runtime.record_approval_decision(
                approval_id="x0", outcome="approve", selected_action="delete_everything"
            )
        block = ctx.exception.block
        self.assertEqual(block.code, BlockCode.CHOICE_SET_VIOLATION)
        self.assertEqual(block.stage, "approval_decision")
        self.assertIsNotNone(block.trace_id)
        # The refusal is auditable and the approval is NOT consumed by an invalid revise.
        run_trace = runtime.trace_store.get(block.trace_id)
        self.assertEqual(run_trace.status, "blocked")
        still_pending = runtime.approval_runtime.get("x0")
        self.assertEqual(still_pending.status, "pending")
        self.assertIsNone(still_pending.decision)

    def test_revise_outside_choice_set_raises_typed_error_at_lifecycle_layer(self) -> None:
        # The domain-independent lifecycle carries the block code without importing
        # the runtime (guards against the circular-import regression).
        runtime = _build_runtime()
        _seed_pending(runtime, "x1")
        with self.assertRaises(ChoiceSetViolationError) as ctx:
            runtime.approval_runtime.decide("x1", outcome="approve", selected_action="not_surfaced")
        self.assertEqual(ctx.exception.block_code, BlockCode.CHOICE_SET_VIOLATION)

    def test_decision_on_consumed_approval_refused(self) -> None:
        # Test 4: a second decision on an already-decided approval is refused (typed).
        runtime = _build_runtime()
        _seed_pending(runtime, "c0")
        runtime.record_approval_decision(approval_id="c0", outcome="approve")
        with self.assertRaises(ValueError):
            runtime.record_approval_decision(approval_id="c0", outcome="approve")

    def test_decision_writes_audit_trace_event(self) -> None:
        # Trace: each decision writes a queryable event (outcome + selected + revised).
        runtime = _build_runtime()
        _seed_pending(runtime, "t0")
        _record, trace_id = runtime.record_approval_decision(
            approval_id="t0", outcome="approve", selected_action=_OTHER
        )
        run_trace = runtime.trace_store.get(trace_id)
        self.assertIsNotNone(run_trace)
        event = next(e for e in run_trace.events if e.step == "approval_decision")
        self.assertEqual(event.payload["decision"], ApprovalDecision.APPROVED_REVISED.value)
        self.assertEqual(event.payload["selected_action"], _OTHER)
        self.assertTrue(event.payload["revised"])

    def test_reject_and_escalate_are_counted_but_do_not_move_rates(self) -> None:
        runtime = _build_runtime()
        _seed_pending(runtime, "r0")
        rejected, _ = runtime.record_approval_decision(approval_id="r0", outcome="reject")
        self.assertEqual(rejected.decision, ApprovalDecision.REJECTED.value)
        self.assertEqual(rejected.status, "rejected")

        _seed_pending(runtime, "e0")
        escalated, _ = runtime.record_approval_decision(approval_id="e0", outcome="escalate")
        self.assertEqual(escalated.decision, ApprovalDecision.ESCALATED.value)
        # Escalation punts: it stays pending and can be re-decided.
        self.assertEqual(escalated.status, "pending")
        re_decided, _ = runtime.record_approval_decision(approval_id="e0", outcome="approve")
        self.assertEqual(re_decided.decision, ApprovalDecision.APPROVED_RECOMMENDED.value)

        analytics = runtime.approval_runtime.analytics()
        self.assertEqual(analytics.counts.rejected, 1)
        self.assertEqual(analytics.counts.escalated, 0)  # overwritten by the later approve
        # With one approved_recommended and no revise, rates reflect only approvals.
        self.assertEqual(analytics.selection_concentration, 1.0)
        self.assertEqual(analytics.modify_rate, 0.0)


class ApprovalAnalyticsScopingTest(unittest.TestCase):
    """Analytics is tenant-isolated, risk-sliceable, and window-bounded."""

    def test_analytics_is_tenant_isolated(self) -> None:
        # Test 5: a query for tenant A never counts tenant B's records.
        runtime = _build_runtime()
        for i in range(2):
            _seed_pending(runtime, f"A{i}", tenant_id="tenant-a")
            runtime.record_approval_decision(
                approval_id=f"A{i}", outcome="approve", tenant_id="tenant-a"
            )
        # tenant B: a revise, which would skew A's rates if it leaked across tenants.
        _seed_pending(runtime, "B0", tenant_id="tenant-b")
        runtime.record_approval_decision(
            approval_id="B0", outcome="approve", selected_action=_OTHER, tenant_id="tenant-b"
        )

        a = runtime.approval_runtime.analytics(tenant_id="tenant-a")
        self.assertEqual(a.total, 2)
        self.assertEqual(a.counts.approved_revised, 0)
        self.assertEqual(a.selection_concentration, 1.0)

        b = runtime.approval_runtime.analytics(tenant_id="tenant-b")
        self.assertEqual(b.total, 1)
        self.assertEqual(b.counts.approved_revised, 1)
        self.assertEqual(b.modify_rate, 1.0)

    def test_analytics_filters_by_risk_tier(self) -> None:
        runtime = _build_runtime()
        _seed_pending(runtime, "hi", risk_level="R3")
        runtime.record_approval_decision(
            approval_id="hi", outcome="approve", selected_action=_OTHER
        )
        _seed_pending(runtime, "lo", risk_level="R1")
        runtime.record_approval_decision(approval_id="lo", outcome="approve")

        r3 = runtime.approval_runtime.analytics(risk="R3")
        self.assertEqual(r3.total, 1)
        self.assertEqual(r3.counts.approved_revised, 1)
        self.assertEqual(r3.modify_rate, 1.0)

        r1 = runtime.approval_runtime.analytics(risk="R1")
        self.assertEqual(r1.total, 1)
        self.assertEqual(r1.counts.approved_recommended, 1)
        self.assertEqual(r1.modify_rate, 0.0)

    def test_analytics_window_excludes_old_records(self) -> None:
        runtime = _build_runtime()
        _seed_pending(runtime, "old", created_at="2020-01-01T00:00:00+00:00")
        runtime.record_approval_decision(approval_id="old", outcome="approve")
        _seed_pending(runtime, "new")  # created_at defaults to now
        runtime.record_approval_decision(
            approval_id="new", outcome="approve", selected_action=_OTHER
        )

        all_time = runtime.approval_runtime.analytics(window="all")
        self.assertEqual(all_time.total, 2)
        recent = runtime.approval_runtime.analytics(window="7d")
        self.assertEqual(recent.total, 1)
        self.assertEqual(recent.counts.approved_revised, 1)

    def test_analytics_rejects_unsupported_window(self) -> None:
        runtime = _build_runtime()
        with self.assertRaises(ValueError):
            runtime.approval_runtime.analytics(window="fortnight")

    def test_empty_tenant_reports_zero_rates_without_dividing_by_zero(self) -> None:
        runtime = _build_runtime()
        analytics = runtime.approval_runtime.analytics(tenant_id="nobody")
        self.assertEqual(analytics.total, 0)
        self.assertEqual(analytics.modify_rate, 0.0)
        self.assertEqual(analytics.selection_concentration, 0.0)


class ApprovalAnalyticsPersistenceTest(unittest.TestCase):
    """The decision fields survive the persistence round-trip (bypass guard)."""

    def test_decision_fields_round_trip_through_mappers(self) -> None:
        from agent_os_persistence import mappers

        runtime = _build_runtime()
        _seed_pending(runtime, "p0")
        record, _ = runtime.record_approval_decision(
            approval_id="p0", outcome="approve", selected_action=_OTHER, approved_by="ops@x"
        )
        restored = mappers.approval_from_payload(mappers.approval_to_payload(record))
        self.assertEqual(restored.decision, ApprovalDecision.APPROVED_REVISED.value)
        self.assertEqual(restored.selected_action, _OTHER)
        self.assertEqual(restored.recommended_action, _RECOMMENDED)
        self.assertEqual(restored.risk_level, "R3")
        self.assertEqual(restored.created_at, record.created_at)


_HTTP_AVAILABLE = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
)

_API_KEY = "secret-analytics-key"
_EXTERNAL_KEY = "secret-analytics-external-key"
_RUN_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


def _make_client(*, external_api_key: str | None = None):
    from starlette.testclient import TestClient

    from agent_os_api.http_app import create_app
    from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

    factory = ContentCommerceRuntimeFactory(
        RuntimeFactoryConfig(domain_pack_path=Path("domain_packs/content_commerce"))
    )
    runtime = factory.build()
    app = create_app(
        runtime,
        retriever=factory.build_knowledge_retriever(),
        api_key=_API_KEY,
        external_api_key=external_api_key,
        operator_api_key="secret-analytics-operator-key",
        agent_checkpoint_store=factory.build_agent_checkpoint_store(),
    )
    return TestClient(app)


@unittest.skipUnless(_HTTP_AVAILABLE, "fastapi/httpx not installed")
class ApprovalAnalyticsHttpTest(unittest.TestCase):
    def test_analytics_read_denied_for_external_scope(self) -> None:
        # Test 6: the external_report scope cannot read analytics (no deliberation leak).
        client = _make_client(external_api_key=_EXTERNAL_KEY)
        denied = client.get("/analytics/approvals", headers={"X-API-Key": _EXTERNAL_KEY})
        self.assertEqual(denied.status_code, 403, denied.text)
        # Positive control: the internal (admin) principal can read it.
        allowed = client.get("/analytics/approvals", headers={"X-API-Key": _API_KEY})
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(allowed.json()["total"], 0)

    def test_decision_then_analytics_end_to_end(self) -> None:
        client = _make_client()
        headers = {"X-API-Key": _API_KEY}
        run_resp = client.post(
            "/runs",
            json={"question": "GMV 记录行动", "parameters": _RUN_PARAMS},
            headers=headers,
        )
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        approval_id = run_resp.json()["user_result"]["business_action"]["approval_id"]

        decision = client.post(
            f"/approvals/{approval_id}/decision",
            json={"outcome": "approve", "approved_by": "ops@example.com"},
            headers=headers,
        )
        self.assertEqual(decision.status_code, 200, decision.text)
        payload = decision.json()
        self.assertEqual(payload["decision"], ApprovalDecision.APPROVED_RECOMMENDED.value)
        self.assertFalse(payload["revised"])

        analytics = client.get("/analytics/approvals", headers=headers)
        self.assertEqual(analytics.status_code, 200, analytics.text)
        body = analytics.json()
        self.assertEqual(body["counts"]["approved_recommended"], 1)
        self.assertEqual(body["selection_concentration"], 1.0)
        self.assertEqual(body["modify_rate"], 0.0)

    def test_http_revise_outside_choice_set_returns_choice_set_violation(self) -> None:
        client = _make_client()
        headers = {"X-API-Key": _API_KEY}
        run_resp = client.post(
            "/runs",
            json={"question": "GMV 记录行动", "parameters": _RUN_PARAMS},
            headers=headers,
        )
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        approval_id = run_resp.json()["user_result"]["business_action"]["approval_id"]

        resp = client.post(
            f"/approvals/{approval_id}/decision",
            json={"outcome": "approve", "selected_action": "not_a_surfaced_action"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], BlockCode.CHOICE_SET_VIOLATION.value)


if __name__ == "__main__":
    unittest.main()
