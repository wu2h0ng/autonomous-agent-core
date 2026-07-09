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
    QualityContract,
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
from agent_os_core.evidence_chain import derive_confidence  # noqa: E402
from agent_os_core.nl_query import NLQueryEngine  # noqa: E402
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

# The stated recency bound (tau) for the golden metric contracts, so the DERIVED confidence
# (P2-C, ADR-0017) responds to how fresh each case's source data is.
GOLDEN_FRESHNESS_TAU = "24h"

# Per-case source-data age (seconds) cycled across the golden cases so the confidence
# DISTRIBUTION is genuinely non-constant: fresh (<=tau), borderline (within tolerance), and
# stale (past tau -> tau_inconsistency cap). If confidence ever regresses to a constant, the
# distribution collapses to one value and the confidence_derivation regression fails.
GOLDEN_SOURCE_AGES_SECONDS = (
    3600.0,  # 1h  — fresh
    43200.0,  # 12h — fresh
    82800.0,  # 23h — fresh (just inside tau)
    90000.0,  # 25h — borderline (within tolerance band)
    172800.0,  # 48h — stale (tau violated)
    259200.0,  # 72h — stale (tau violated)
)

DEFAULT_THRESHOLDS = {
    "intent": 1.0,
    "nl_intent": 1.0,
    "metric": 1.0,
    "provider": 1.0,
    "data_product": 1.0,
    "sql_safety": 1.0,
    "evidence": 1.0,
    "evidence_typed": 1.0,
    "action": 1.0,
    "trace": 1.0,
    "feedback": 1.0,
    # Bypass-detecting: each case's confidence must be RECOMPUTABLE from its recorded
    # inputs. A hard-coded constant carries no inputs (or an inconsistent score) and fails.
    "confidence_derivation": 1.0,
}


def _confidence_is_derived(evidence: object) -> bool:
    """True iff the evidence confidence is recomputable from its recorded inputs.

    This is the per-case bypass detector for the ``confidence_derivation`` eval dimension:
    a constant confidence divorced from inputs (no ``confidence_score.inputs`` or a score
    that does not match the rule recomputed from those inputs) fails.
    """
    score = getattr(evidence, "confidence_score", None)
    inputs = getattr(score, "inputs", None) if score is not None else None
    if inputs is None:
        return False
    recomputed = derive_confidence(
        source_age_seconds=inputs.source_age_seconds,
        tau_seconds=inputs.freshness_tau_seconds,
        row_count=inputs.row_count,
        template_verified=inputs.template_verified,
    )
    return abs(recomputed.score - evidence.confidence) < 1e-9


def _verified_template(metric_name: str) -> SQLTemplate:
    return SQLTemplate(
        template_id=f"{metric_name}_daily",
        metric_name=metric_name,
        sql=SAFE_SQL,
        required_parameters=("start_date", "end_date", "limit"),
        required_time_parameters=("start_date", "end_date"),
    )


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
            verified_queries=(_verified_template(metric_name),),
            quality_contract=QualityContract(freshness=GOLDEN_FRESHNESS_TAU),
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

    semantic_registry = SemanticRegistry(metric_contracts=tuple(metrics.values()))
    nl_query_engine = NLQueryEngine(metric_registry=semantic_registry)
    outcomes: list[EvalCaseOutcome] = []
    for index, case in enumerate(golden):
        # Vary the source-data age per case so the DERIVED confidence distribution is
        # non-constant (fresh / borderline / stale). Row content is otherwise identical, so
        # the pre-existing dimensions (intent/metric/provider/...) are unaffected.
        source_age_seconds = GOLDEN_SOURCE_AGES_SECONDS[index % len(GOLDEN_SOURCE_AGES_SECONDS)]
        runtime = TrustedLoopRuntime(
            metric_contract=metrics["gmv"],
            query_executor=StaticQueryExecutor(
                [{"order_date": "2026-05-31", "val": 100.0}],
                source_age_seconds=source_age_seconds,
            ),
            semantic_registry=semantic_registry,
            provider_registry=ProviderRegistry((provider,)),
            connector_registry=_build_default_connector_registry(),
            nl_query_engine=nl_query_engine,
        )
        result = runtime.run(case["question"], dict(case["parameters"]))

        # NL→Query intent check: when only the non-time parameter (limit) is
        # supplied, the runtime must still extract start_date/end_date from the
        # natural-language question via NLQueryEngine.
        nl_only_parameters: dict[str, object] = {}
        if "limit" in case["parameters"]:
            nl_only_parameters["limit"] = case["parameters"]["limit"]
        nl_result = runtime.run(case["question"], nl_only_parameters)
        nl_parameters = nl_result.query_plan.parameters

        checks = {
            "intent": result.intent.metric_name == case["expected_metric"],
            "nl_intent": "start_date" in nl_parameters and "end_date" in nl_parameters,
            "metric": result.evidence_chain.metric_contract.metric_name == case["expected_metric"],
            "provider": result.provider_contract is not None
            and result.provider_contract.provider_id == "provider-sales",
            "data_product": result.data_product_candidate is not None,
            "sql_safety": result.evidence_chain.sql_safety.allowed,
            "evidence": result.evidence_chain.is_complete(),
            "evidence_typed": result.evidence_chain.is_typed_complete(),
            "action": result.action_proposal is not None,
            "trace": len(result.trace_events) >= 8,
            "feedback": result.feedback_event is not None
            and result.feedback_event.source == "runtime_self_report",
            # P2-C (ADR-0017): the confidence is DERIVED — recomputable from its recorded
            # inputs. A constant divorced from inputs fails this per-case bypass check.
            "confidence_derivation": _confidence_is_derived(result.evidence_chain),
        }
        reasons = tuple(f"{name} check failed" for name, passed in checks.items() if not passed)
        outcomes.append(EvalCaseOutcome(case_id=case["id"], checks=checks, reasons=reasons))

    return EvalThresholdReporter(thresholds or DEFAULT_THRESHOLDS).build(tuple(outcomes))


def build_golden_confidence_distribution(
    *,
    golden_queries_path: Path = DEFAULT_GOLDEN_QUERIES,
) -> tuple[float, ...]:
    """Return the DERIVED confidence for each golden case (regression / bypass evidence).

    Used by the eval to assert the distribution is non-constant: if EvidenceChain confidence
    ever regresses to a hard-coded constant, every value collapses to one and the regression
    test fails.
    """
    golden = json.loads(golden_queries_path.read_text(encoding="utf-8"))
    metrics = {
        metric_name: MetricContract(
            metric_name=metric_name,
            display_name=metric_name.upper(),
            definition=f"{metric_name} metric contract.",
            owner="content_commerce_ops",
            unit="CNY",
            allowed_schemas=("sales",),
            verified_queries=(_verified_template(metric_name),),
            quality_contract=QualityContract(freshness=GOLDEN_FRESHNESS_TAU),
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
    semantic_registry = SemanticRegistry(metric_contracts=tuple(metrics.values()))
    nl_query_engine = NLQueryEngine(metric_registry=semantic_registry)
    confidences: list[float] = []
    for index, case in enumerate(golden):
        source_age_seconds = GOLDEN_SOURCE_AGES_SECONDS[index % len(GOLDEN_SOURCE_AGES_SECONDS)]
        runtime = TrustedLoopRuntime(
            metric_contract=metrics["gmv"],
            query_executor=StaticQueryExecutor(
                [{"order_date": "2026-05-31", "val": 100.0}],
                source_age_seconds=source_age_seconds,
            ),
            semantic_registry=semantic_registry,
            provider_registry=ProviderRegistry((provider,)),
            connector_registry=_build_default_connector_registry(),
            nl_query_engine=nl_query_engine,
        )
        result = runtime.run(case["question"], dict(case["parameters"]))
        confidences.append(result.evidence_chain.confidence)
    return tuple(confidences)


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
