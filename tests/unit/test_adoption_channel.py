"""Guard tests for the adoption value channel (P5.1a, ADR-0001).

The invariants under test:
  1. Self-report and external adoption are SCHEMA-separated (distinct ``source``
     tags AND distinct stores) and never co-aggregated.
  2. The OS-Core runtime code path CANNOT fabricate realized external value: its
     feedback builder is fixed to self-report, it holds only a read-only adoption
     view, and the ledger refuses anything that is not external-adoption.
  3. The operator-exclusive ingest is the only writer; the runtime reads realized
     value through a read-only port; the factory wires this as a real entry point.
"""

from __future__ import annotations

import inspect
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
    FeedbackSource,
    MetricContract,
    ProviderContract,
    ProviderKind,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    AdoptionIngest,
    AdoptionLedger,
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.feedback import FeedbackEventBuilder  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402


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


def _build_runtime(adoption_ledger_view=None) -> TrustedLoopRuntime:
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
        sql="select 1 from sales.orders where order_date >= :start_date "
        "and order_date < :end_date limit :limit",
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
        adoption_ledger_view=adoption_ledger_view,
    )


class TestFeedbackSourceTagging(unittest.TestCase):
    def test_default_builder_is_self_report(self) -> None:
        event = FeedbackEventBuilder().build(trace_id="t", outcome="adopted")
        self.assertEqual(event.source, FeedbackSource.RUNTIME_SELF_REPORT)

    def test_adoption_builder_is_external(self) -> None:
        builder = FeedbackEventBuilder(source=FeedbackSource.EXTERNAL_ADOPTION)
        self.assertEqual(
            builder.build(trace_id="t", outcome="adopted").source, FeedbackSource.EXTERNAL_ADOPTION
        )

    def test_build_cannot_override_source(self) -> None:
        # source is fixed at construction; build() exposes no way to set it.
        params = inspect.signature(FeedbackEventBuilder.build).parameters
        self.assertNotIn("source", params)

    def test_source_changes_feedback_id(self) -> None:
        self_report = FeedbackEventBuilder().build(trace_id="t", outcome="adopted")
        external = FeedbackEventBuilder(source=FeedbackSource.EXTERNAL_ADOPTION).build(
            trace_id="t", outcome="adopted"
        )
        self.assertNotEqual(self_report.feedback_id, external.feedback_id)


class TestAdoptionLedgerAndIngest(unittest.TestCase):
    def test_ingest_writes_external_adoption(self) -> None:
        ledger = AdoptionLedger()
        event = AdoptionIngest(ledger).submit(trace_id="t-1", outcome="adopted", reviewer="ops")
        self.assertEqual(event.source, FeedbackSource.EXTERNAL_ADOPTION)
        self.assertEqual(ledger.get_by_trace("t-1"), (event,))
        self.assertEqual(ledger.adoption_counts(), {"adopted": 1})

    def test_ledger_refuses_self_report(self) -> None:
        ledger = AdoptionLedger()
        self_report = FeedbackEventBuilder().build(trace_id="t", outcome="adopted")
        with self.assertRaises(ValueError):
            ledger.record(self_report)

    def test_read_only_view_has_no_write_surface(self) -> None:
        view = AdoptionLedger().view()
        self.assertFalse(hasattr(view, "record"))
        self.assertFalse(hasattr(view, "submit"))
        # but it can read
        self.assertEqual(view.get_by_trace("missing"), ())


class TestRuntimeChannelSeparation(unittest.TestCase):
    def test_runtime_builder_is_self_report(self) -> None:
        runtime = _build_runtime()
        self.assertEqual(runtime.feedback_builder.source, FeedbackSource.RUNTIME_SELF_REPORT)

    def test_record_outcome_is_self_report_not_adoption(self) -> None:
        ledger = AdoptionLedger()
        runtime = _build_runtime(adoption_ledger_view=ledger.view())
        feedback = runtime.record_outcome(trace_id="t-9", outcome="adopted")
        # self-report channel, NOT realized external value
        self.assertEqual(feedback.source, FeedbackSource.RUNTIME_SELF_REPORT)
        self.assertIn(feedback, runtime.feedback_store.get_by_trace("t-9"))
        # the self-report never leaks into the adoption value channel
        self.assertEqual(runtime.adoption_for_trace("t-9"), ())
        self.assertEqual(ledger.adoption_counts(), {})

    def test_operator_adoption_visible_to_runtime_read_port_only(self) -> None:
        ledger = AdoptionLedger()
        runtime = _build_runtime(adoption_ledger_view=ledger.view())
        ingest = AdoptionIngest(ledger)  # operator holds this; runtime does not
        event = ingest.submit(trace_id="t-7", outcome="adopted", reviewer="ops")
        # runtime can READ realized value through its view
        self.assertEqual(runtime.adoption_for_trace("t-7"), (event,))
        # but adoption never lands in the self-report feedback store
        self.assertEqual(runtime.feedback_store.get_by_trace("t-7"), ())

    def test_runtime_holds_no_adoption_writer(self) -> None:
        runtime = _build_runtime(adoption_ledger_view=AdoptionLedger().view())
        # the runtime's only adoption surface is the read-only view
        self.assertFalse(hasattr(runtime.adoption_ledger_view, "record"))
        self.assertFalse(hasattr(runtime.adoption_ledger_view, "submit"))
        # no attribute on the runtime is a writer
        for value in vars(runtime).values():
            self.assertNotIsInstance(value, (AdoptionIngest, AdoptionLedger))

    def test_no_view_wired_reads_empty(self) -> None:
        runtime = _build_runtime(adoption_ledger_view=None)
        self.assertEqual(runtime.adoption_for_trace("anything"), ())


class TestFactoryWiring(unittest.TestCase):
    def _factory(self):
        from agent_os_api.runtime_factory import (
            ContentCommerceRuntimeFactory,
            RuntimeFactoryConfig,
        )

        config = RuntimeFactoryConfig(
            domain_pack_path=ROOT / "domain_packs" / "content_commerce",
        )
        return ContentCommerceRuntimeFactory(config)

    def test_operator_ingest_and_runtime_share_one_ledger(self) -> None:
        factory = self._factory()
        runtime = factory.build()
        ingest = factory.adoption_ingest()
        event = ingest.submit(trace_id="t-1", outcome="adopted", reviewer="ops")
        # runtime reads what the operator wrote (same value channel)
        self.assertEqual(runtime.adoption_for_trace("t-1"), (event,))
        # unknown trace stays empty
        self.assertEqual(runtime.adoption_for_trace("nope"), ())


if __name__ == "__main__":
    unittest.main()
