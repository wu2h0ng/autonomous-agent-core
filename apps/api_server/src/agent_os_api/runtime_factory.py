from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_os_contracts import MetricContract, ProviderContract, ProviderKind, SQLTemplate
from agent_os_core import ProviderRegistry, SemanticRegistry, TrustedLoopRuntime
from agent_os_core.query_runtime import StaticQueryExecutor


@dataclass(frozen=True)
class RuntimeFactoryConfig:
    domain_pack_path: Path
    sample_rows: tuple[dict[str, Any], ...] = ({"order_date": "2026-05-31", "value": 128800.0},)


class ContentCommerceRuntimeFactory:
    """Builds a runnable Trusted Loop from content commerce domain-pack contracts."""

    def __init__(self, config: RuntimeFactoryConfig) -> None:
        self.config = config

    def build(self) -> TrustedLoopRuntime:
        metrics = self._load_metrics()
        providers = self._load_providers()
        template = self._load_sql_templates()[0]
        default_metric = metrics[template.metric_name]

        return TrustedLoopRuntime(
            metric_contract=default_metric,
            sql_template=template,
            query_executor=StaticQueryExecutor(list(self.config.sample_rows)),
            semantic_registry=SemanticRegistry(metric_contracts=tuple(metrics.values())),
            provider_registry=ProviderRegistry(tuple(providers.values())),
        )

    def _load_metrics(self) -> dict[str, MetricContract]:
        rows = self._read_json("metrics.json")
        metrics: dict[str, MetricContract] = {}
        for row in rows:
            metric = MetricContract(
                metric_name=row["metric_name"],
                display_name=row["display_name"],
                definition=row["definition"],
                owner=row["owner"],
                unit=row["unit"],
                allowed_schemas=tuple(row["allowed_schemas"]),
                dimensions=tuple(row.get("dimensions", ())),
            )
            metrics[metric.metric_name] = metric
        if not metrics:
            raise ValueError("Domain pack must define at least one metric.")
        return metrics

    def _load_providers(self) -> dict[str, ProviderContract]:
        rows = self._read_json("providers.json")
        providers: dict[str, ProviderContract] = {}
        for row in rows:
            provider = ProviderContract(
                provider_id=row["provider_id"],
                kind=ProviderKind(row["kind"]),
                name=row["name"],
                owner=row["owner"],
                allowed_schemas=tuple(row.get("allowed_schemas", ())),
                data_classification=row.get("data_classification", "internal"),
                supports_query=bool(row.get("supports_query", True)),
                supports_write=bool(row.get("supports_write", False)),
                cost_hint=row.get("cost_hint"),
                lineage_hint=row.get("lineage_hint"),
            )
            providers[provider.provider_id] = provider
        if not providers:
            raise ValueError("Domain pack must define at least one provider.")
        return providers

    def _load_sql_templates(self) -> tuple[SQLTemplate, ...]:
        rows = self._read_json("sql_templates.json")
        templates = tuple(
            SQLTemplate(
                template_id=row["template_id"],
                metric_name=row["metric_name"],
                sql=row["sql"],
                required_parameters=tuple(row.get("required_parameters", ())),
                required_time_parameters=tuple(
                    row.get("required_time_parameters", ("start_date", "end_date"))
                ),
                default_limit=int(row.get("default_limit", 100)),
                max_limit=int(row.get("max_limit", 1000)),
                allow_select_star=bool(row.get("allow_select_star", False)),
            )
            for row in rows
        )
        if not templates:
            raise ValueError("Domain pack must define at least one SQL template.")
        return templates

    def _read_json(self, filename: str) -> list[dict[str, Any]]:
        path = self.config.domain_pack_path / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing domain pack file: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"Domain pack file must contain a JSON list: {path}")
        return data
