from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
    ROOT / "action_connectors",
):
    path_text = str(_path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    MetricContract,
    ProviderContract,
    ProviderKind,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    EvalCaseOutcome,
    EvalThresholdReport,
    EvalThresholdReporter,
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
    thresholds_from_json,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_GOLDEN_QUERIES = EVAL_DIR / "golden_queries.json"

SAFE_SQL = (
    "select order_date, sum(paid_amount) as val "
    "from sales.orders "
    "where order_date >= :start_date and order_date < :end_date "
    "group by order_date "
    "limit :limit"
)

METRIC_NAMES = ("gmv", "roi", "conversion_rate", "revenue", "orders", "spend", "cac")
DEFAULT_THRESHOLDS = {
    "intent": 1.0,
    "metric": 1.0,
    "provider": 1.0,
    "data_product": 1.0,
    "sql_safety": 1.0,
    "evidence": 1.0,
    "action": 1.0,
    "trace": 1.0,
}


def _build_default_connector_registry() -> ActionConnectorRegistry:
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


def build_golden_eval_threshold_report(
    *,
    golden_queries_path: Path = DEFAULT_GOLDEN_QUERIES,
    thresholds: dict[str, float] | None = None,
) -> EvalThresholdReport:
    golden = json.loads(golden_queries_path.read_text(encoding="utf-8"))
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
    for case in golden:
        template = SQLTemplate(
            f"{case['expected_metric']}_daily",
            case["expected_metric"],
            SAFE_SQL,
            ("start_date", "end_date", "limit"),
        )
        result = TrustedLoopRuntime(
            metric_contract=metrics["gmv"],
            sql_template=template,
            query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "val": 100.0}]),
            semantic_registry=SemanticRegistry(metric_contracts=tuple(metrics.values())),
            provider_registry=ProviderRegistry((provider,)),
            connector_registry=_build_default_connector_registry(),
        ).run(case["question"], dict(case["parameters"]))

        checks = {
            "intent": result.intent.metric_name == case["expected_metric"],
            "metric": result.evidence_chain.metric_contract.metric_name == case["expected_metric"],
            "provider": result.provider_contract is not None
            and result.provider_contract.provider_id == "provider-sales",
            "data_product": result.data_product_candidate is not None,
            "sql_safety": result.evidence_chain.sql_safety.allowed,
            "evidence": result.evidence_chain.is_complete(),
            "action": result.action_proposal is not None,
            "trace": len(result.trace_events) >= 8,
        }
        reasons = tuple(f"{name} check failed" for name, passed in checks.items() if not passed)
        outcomes.append(EvalCaseOutcome(case_id=case["id"], checks=checks, reasons=reasons))

    return EvalThresholdReporter(thresholds or DEFAULT_THRESHOLDS).build(tuple(outcomes))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run golden evals and emit a threshold report.")
    parser.add_argument("--golden-queries", type=Path, default=DEFAULT_GOLDEN_QUERIES)
    parser.add_argument("--thresholds-json")
    parser.add_argument("--thresholds-file", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    if args.thresholds_json and args.thresholds_file:
        parser.error("--thresholds-json and --thresholds-file are mutually exclusive")
    if args.thresholds_file:
        thresholds_payload = args.thresholds_file.read_text(encoding="utf-8")
        thresholds = thresholds_from_json(thresholds_payload)
    elif args.thresholds_json:
        thresholds = thresholds_from_json(args.thresholds_json)
    else:
        thresholds = None
    report = build_golden_eval_threshold_report(
        golden_queries_path=args.golden_queries,
        thresholds=thresholds,
    )
    report_json = report.to_json()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report_json + "\n", encoding="utf-8")
    print(report_json)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
