from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_os_contracts import (
    ActionConnectorContract,
    MetricContract,
    ProviderContract,
    ProviderKind,
    SQLTemplate,
)
from agent_os_core import ProviderRegistry, SemanticRegistry, TrustedLoopRuntime
from agent_os_core.action_connectors import ActionConnectorRegistry
from agent_os_core.query_runtime import SQLiteQueryExecutor, StaticQueryExecutor

# Executor selection values accepted by RuntimeFactoryConfig.executor and --executor.
EXECUTOR_STATIC = "static"
EXECUTOR_SQLITE = "sqlite"


@dataclass(frozen=True)
class RuntimeFactoryConfig:
    domain_pack_path: Path
    sample_rows: tuple[dict[str, Any], ...] = ({"order_date": "2026-05-31", "value": 128800.0},)
    # Which query executor to inject behind ProviderContract:
    #   "static" -> StaticQueryExecutor (deterministic fixture rows; default, unchanged)
    #   "sqlite" -> SQLiteQueryExecutor over the seeded Customer-0 data plane (real SQL)
    executor: str = EXECUTOR_STATIC


class ContentCommerceRuntimeFactory:
    """Builds a runnable Trusted Loop from content commerce domain-pack contracts."""

    def __init__(self, config: RuntimeFactoryConfig) -> None:
        self.config = config

    def build(self) -> TrustedLoopRuntime:
        metrics = self._load_metrics()
        providers = self._load_providers()
        template = self._load_sql_templates()[0]
        default_metric = metrics[template.metric_name]

        # API layer owns connector construction (OS Core must not import connectors)
        connector_registry = self._build_default_connector_registry()

        return TrustedLoopRuntime(
            metric_contract=default_metric,
            sql_template=template,
            query_executor=self._build_query_executor(providers),
            semantic_registry=SemanticRegistry(metric_contracts=tuple(metrics.values())),
            provider_registry=ProviderRegistry(tuple(providers.values())),
            connector_registry=connector_registry,
        )

    def _build_query_executor(
        self, providers: dict[str, ProviderContract]
    ) -> StaticQueryExecutor | SQLiteQueryExecutor:
        """Select and construct the injected query executor.

        The static path (default) keeps the deterministic fixture rows. The sqlite
        path "rides the data plane": the application layer owns the data source,
        seeds the Customer-0 reference data behind ProviderContract, and hands a
        generic SQLiteQueryExecutor a connection. OS Core never sees the data.
        """
        if self.config.executor == EXECUTOR_STATIC:
            return StaticQueryExecutor(list(self.config.sample_rows))
        if self.config.executor == EXECUTOR_SQLITE:
            connection = self._build_seeded_connection(providers)
            return SQLiteQueryExecutor(connection)
        raise ValueError(
            f"Unknown executor {self.config.executor!r}; "
            f"expected {EXECUTOR_STATIC!r} or {EXECUTOR_SQLITE!r}."
        )

    def _build_seeded_connection(
        self, providers: dict[str, ProviderContract]
    ) -> sqlite3.Connection:
        """Build an in-memory SQLite connection seeded with domain-pack reference data.

        SQL templates reference schema-qualified tables (e.g. ``sales.orders``). For
        each provider schema, an in-memory database is ATTACHed under that schema name
        and the matching seed file ``seed/<schema>_<table>.sql`` is loaded into it.
        This data lives in the domain pack, not in OS Core.
        """
        connection = sqlite3.connect(":memory:")
        seed_dir = self.config.domain_pack_path / "seed"
        schemas = {
            schema
            for provider in providers.values()
            for schema in provider.allowed_schemas
        }
        if not schemas:
            raise ValueError("sqlite executor requires at least one provider schema to seed.")
        for schema in sorted(schemas):
            if not schema.isidentifier():
                raise ValueError(f"Unsafe schema name for seeding: {schema!r}")
            connection.execute(f"attach database ':memory:' as {schema}")
            seed_path = seed_dir / f"{schema}_orders.sql"
            if not seed_path.exists():
                raise FileNotFoundError(f"Missing seed file for schema {schema!r}: {seed_path}")
            # The seed script uses a {schema} placeholder so tables land in the
            # attached schema and resolve the schema-qualified SQL templates.
            script = seed_path.read_text(encoding="utf-8").replace("{schema}", schema)
            connection.executescript(script)
        connection.commit()
        return connection

    @staticmethod
    def _build_default_connector_registry() -> ActionConnectorRegistry:
        """Build a default connector registry with ManualReviewConnector.

        This lives in the API layer, not in OS Core, to enforce the boundary
        rule: OS Core never imports concrete action connectors.
        """
        from manual_review import ManualReviewConnector

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
