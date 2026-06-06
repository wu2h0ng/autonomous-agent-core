from __future__ import annotations

import json
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
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    EvalCaseOutcome,
    EvalThresholdReporter,
    IntentParser,
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent

SAFE_SQL = (
    "select order_date, sum(paid_amount) as val "
    "from sales.orders "
    "where order_date >= :start_date and order_date < :end_date "
    "group by order_date "
    "limit :limit"
)

METRIC_NAMES = ("gmv", "roi", "conversion_rate", "revenue", "orders", "spend", "cac")


def _build_default_connector_registry() -> ActionConnectorRegistry:
    """Build a connector registry with ManualReviewConnector.

    Caller-side construction: OS Core never imports action connectors.
    """
    registry = ActionConnectorRegistry()
    connector = ManualReviewConnector()
    contract = ActionConnectorContract(
        connector_name="manual_review",
        display_name="Manual Review",
        supported_action_types=("propose", "execute"),
        supports_snapshot=False,
        supports_rollback=False,
        compensating_action_description=None,
        risk_ceiling="R5",
        owner="system",
    )
    registry.register(connector, contract)
    return registry


class GoldenQueryEvalTest(unittest.TestCase):
    def test_intent_parser_fallback(self) -> None:
        parser = IntentParser()
        golden = json.loads((EVAL_DIR / "golden_queries.json").read_text(encoding="utf-8"))
        passed = 0
        failed = 0
        failures: list[str] = []
        for c in golden:
            with self.subTest(case_id=c["id"]):
                intent = parser.parse(c["question"])
                if intent.metric_name == c["expected_metric"]:
                    passed += 1
                else:
                    failed += 1
                    failures.append(
                        f"{c['id']}: expected '{c['expected_metric']}' "
                        f"got '{intent.metric_name}' for '{c['question']}'"
                    )
        if failures:
            self.fail(f"Intent: {passed} passed, {failed} failed.\n" + "\n".join(failures))

    def test_golden_query_runs_trusted_loop(self) -> None:
        golden = json.loads((EVAL_DIR / "golden_queries.json").read_text(encoding="utf-8"))
        metrics = {
            metric_name: MetricContract(
                metric_name=metric_name,
                display_name=metric_name.upper(),
                definition=f"{metric_name} metric contract.",
                owner="content_commerce_ops",
                unit="CNY",
                allowed_schemas=("sales",),
            )
            for metric_name in METRIC_NAMES
        }
        provider = ProviderContract(
            provider_id="provider-sales",
            kind=ProviderKind.WAREHOUSE,
            name="sales warehouse",
            owner="data_platform",
            allowed_schemas=("sales",),
        )

        outcomes: list[EvalCaseOutcome] = []

        for c in golden:
            with self.subTest(case_id=c["id"]):
                t = SQLTemplate(
                    f"{c['expected_metric']}_daily",
                    c["expected_metric"],
                    SAFE_SQL,
                    ("start_date", "end_date", "limit"),
                )
                r = TrustedLoopRuntime(
                    metric_contract=metrics["gmv"],
                    sql_template=t,
                    query_executor=StaticQueryExecutor(
                        [{"order_date": "2026-05-31", "val": 100.0}]
                    ),
                    semantic_registry=SemanticRegistry(metric_contracts=tuple(metrics.values())),
                    provider_registry=ProviderRegistry((provider,)),
                    connector_registry=_build_default_connector_registry(),
                ).run(c["question"], dict(c["parameters"]))
                self.assertEqual(r.intent.metric_name, c["expected_metric"])
                self.assertEqual(r.evidence_chain.metric_contract.metric_name, c["expected_metric"])
                self.assertIsNotNone(r.provider_contract)
                self.assertEqual(r.provider_contract.provider_id, "provider-sales")
                self.assertIsNotNone(r.data_product_candidate)
                self.assertTrue(
                    r.evidence_chain.is_complete(),
                    f"EvidenceChain incomplete for {c['id']}",
                )
                self.assertGreaterEqual(len(r.trace_events), 8)
                outcomes.append(
                    EvalCaseOutcome(
                        case_id=c["id"],
                        checks={
                            "intent": r.intent.metric_name == c["expected_metric"],
                            "metric": (
                                r.evidence_chain.metric_contract.metric_name == c["expected_metric"]
                            ),
                            "sql_safety": r.evidence_chain.sql_safety.allowed,
                            "evidence": r.evidence_chain.is_complete(),
                            "action": r.action_proposal is not None,
                        },
                    )
                )

        report = EvalThresholdReporter(
            {
                "intent": 1.0,
                "metric": 1.0,
                "sql_safety": 1.0,
                "evidence": 1.0,
                "action": 1.0,
            }
        ).build(tuple(outcomes))

        self.assertTrue(report.passed, report.failures)
        self.assertEqual(report.case_count, len(golden))
        self.assertEqual(report.dimension("evidence").pass_rate, 1.0)


if __name__ == "__main__":
    unittest.main()
