"""Queryable run traces + auditable blocks + observability gate (AR-20260611).

Every run() persists its trace through TraceStorePort on BOTH exits: success
(status "ok") and business block (status "blocked", with a final `blocked` step,
and the block carries its trace_id). The gate test pins the required trace steps
and telemetry dimensions — removing a stage's emission turns CI red.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    MetricContract,
    ProviderContract,
    ProviderKind,
    RunTrace,
    SQLTemplate,
    TelemetryDimension,
    TraceEvent,
)
from agent_os_core import (  # noqa: E402
    InMemoryTraceStore,
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopBlocked,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}

# The observability gate: a successful run MUST emit these trace steps.
REQUIRED_OK_STEPS = {
    "intent",
    "semantic_resolution",
    "query_plan",
    "sql_safety",
    "query_result",
    "data_product_candidate",
    "evidence_chain",
    "action_proposal",
    "operation_contract",
    "knowledge_asset_candidate",
}


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


def _runtime(*, trace_store=None) -> TrustedLoopRuntime:
    metric = MetricContract(
        metric_name="gmv",
        display_name="GMV",
        definition="gmv metric.",
        owner="content_commerce_ops",
        unit="CNY",
        allowed_schemas=("sales",),
    )
    template = SQLTemplate(
        template_id="gmv_daily",
        metric_name="gmv",
        sql=(
            "select order_date, sum(paid_amount) as value from sales.orders "
            "where order_date >= :start_date and order_date < :end_date "
            "group by order_date limit :limit"
        ),
        required_parameters=("start_date", "end_date", "limit"),
    )
    return TrustedLoopRuntime(
        metric_contract=metric,
        sql_template=template,
        query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "value": 1.0}]),
        semantic_registry=SemanticRegistry(metric_contracts=(metric,)),
        provider_registry=ProviderRegistry(
            (
                ProviderContract(
                    provider_id="provider-sales",
                    kind=ProviderKind.WAREHOUSE,
                    name="sales",
                    owner="data_platform",
                    allowed_schemas=("sales",),
                ),
            )
        ),
        connector_registry=_connector_registry(),
        trace_store=trace_store,
    )


class InMemoryTraceStoreTest(unittest.TestCase):
    def test_round_trip_and_unknown(self) -> None:
        store = InMemoryTraceStore()
        run_trace = RunTrace(
            trace_id="trace-x",
            status="ok",
            events=(TraceEvent(trace_id="trace-x", step="intent", payload={"m": "gmv"}),),
            telemetry_events=(),
        )
        store.save(run_trace)
        self.assertEqual(store.get("trace-x"), run_trace)
        self.assertIsNone(store.get("trace-unknown"))


class RunTracePersistenceTest(unittest.TestCase):
    def test_successful_run_persists_queryable_trace(self) -> None:
        runtime = _runtime()  # default InMemoryTraceStore: persisted out of the box
        result = runtime.run("GMV", dict(PARAMS))
        trace_id = result.evidence_chain.trace_id

        stored = runtime.trace_store.get(trace_id)
        self.assertIsNotNone(stored, "run trace was not persisted")
        self.assertEqual(stored.status, "ok")
        self.assertEqual(stored.events, result.trace_events)
        self.assertEqual(stored.telemetry_events, result.telemetry_events)

    def test_blocked_run_persists_trace_and_block_carries_trace_id(self) -> None:
        runtime = _runtime()
        with self.assertRaises(TrustedLoopBlocked) as ctx:
            runtime.run("revenue", dict(PARAMS))  # metric the registry does not define
        block = ctx.exception.block
        self.assertIsNotNone(block.trace_id, "block must reference its persisted trace")

        stored = runtime.trace_store.get(block.trace_id)
        self.assertIsNotNone(stored, "blocked run trace was not persisted")
        self.assertEqual(stored.status, "blocked")
        last = stored.events[-1]
        self.assertEqual(last.step, "blocked")
        self.assertEqual(last.payload["code"], "unknown_metric")
        self.assertEqual(last.payload["stage"], "metric_resolution")

    def test_evaluate_blocked_outcome_exposes_trace_id(self) -> None:
        runtime = _runtime()
        outcome = runtime.evaluate("revenue", dict(PARAMS))
        self.assertEqual(outcome.status, "blocked")
        self.assertIsNotNone(outcome.block.trace_id)
        self.assertIsNotNone(runtime.trace_store.get(outcome.block.trace_id))


class ObservabilityGateTest(unittest.TestCase):
    """Pins the REQUIRED observability coverage; CI goes red if a stage goes silent."""

    def test_required_steps_and_dimensions_present_on_ok_run(self) -> None:
        runtime = _runtime()
        result = runtime.run("GMV", dict(PARAMS))
        stored = runtime.trace_store.get(result.evidence_chain.trace_id)

        steps = {e.step for e in stored.events}
        missing = REQUIRED_OK_STEPS - steps
        self.assertEqual(missing, set(), f"loop stages went silent in the trace: {missing}")

        dimensions = {t.dimension for t in stored.telemetry_events}
        required = {
            TelemetryDimension.BUSINESS,
            TelemetryDimension.QUALITY,
            TelemetryDimension.SYSTEM,
        }
        self.assertLessEqual(
            required, dimensions, f"telemetry dimensions went silent: {required - dimensions}"
        )


import importlib.util  # noqa: E402

_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None
sys.path.insert(0, str(ROOT / "packages" / "persistence" / "src"))


@unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed (install .[postgres])")
class SqlTraceStoreTest(unittest.TestCase):
    def test_round_trip_and_upsert(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        from agent_os_persistence import SqlTraceStore, create_all

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        create_all(engine)
        store = SqlTraceStore(engine)

        from agent_os_contracts import TelemetryEvent

        run_trace = RunTrace(
            trace_id="trace-sql",
            status="ok",
            events=(TraceEvent(trace_id="trace-sql", step="intent", payload={"m": "gmv"}),),
            telemetry_events=(
                TelemetryEvent(
                    trace_id="trace-sql",
                    dimension=TelemetryDimension.BUSINESS,
                    name="trusted_loop.run_started",
                    value=1.0,
                    unit="count",
                ),
            ),
        )
        store.save(run_trace)
        self.assertEqual(store.get("trace-sql"), run_trace)
        self.assertIsNone(store.get("trace-unknown"))

        # Upsert: saving the same trace_id replaces, not duplicates.
        store.save(RunTrace(trace_id="trace-sql", status="blocked", events=()))
        self.assertEqual(store.get("trace-sql").status, "blocked")


class CliTraceEntryPointTest(unittest.TestCase):
    def test_cli_trace_not_found_exits_nonzero_with_error_payload(self) -> None:
        import io
        import json

        sys.path.insert(0, str(ROOT / "apps" / "api_server" / "src"))
        from agent_os_api.cli import run_cli

        out = io.StringIO()
        rc = run_cli(["trace", "--trace-id", "trace-nope"], stdout=out)
        self.assertEqual(rc, 1)
        payload = json.loads(out.getvalue())
        self.assertIn("error", payload)


@unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed (install .[postgres])")
class FactoryTraceStoreWiringTest(unittest.TestCase):
    def test_trace_survives_runtime_restart_on_postgres_backend(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        sys.path.insert(0, str(ROOT / "apps" / "api_server" / "src"))
        from agent_os_api.runtime_factory import (
            STORE_POSTGRES,
            ContentCommerceRuntimeFactory,
            RuntimeFactoryConfig,
        )

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        config = RuntimeFactoryConfig(
            domain_pack_path=ROOT / "domain_packs" / "content_commerce",
            store_backend=STORE_POSTGRES,
            store_engine=engine,
        )
        result = ContentCommerceRuntimeFactory(config).build().run("GMV", dict(PARAMS))
        trace_id = result.evidence_chain.trace_id

        # A fresh runtime on the same engine (simulated restart) can audit the run.
        runtime2 = ContentCommerceRuntimeFactory(config).build()
        stored = runtime2.trace_store.get(trace_id)
        self.assertIsNotNone(stored, "run trace did not survive the restart")
        self.assertEqual(stored.status, "ok")

        # The factory's standalone trace store (CLI audit surface) sees it too.
        audit_store = ContentCommerceRuntimeFactory(config).build_trace_store()
        self.assertIsNotNone(audit_store.get(trace_id))


if __name__ == "__main__":
    unittest.main()
