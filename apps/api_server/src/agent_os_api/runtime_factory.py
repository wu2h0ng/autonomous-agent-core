from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping
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
from agent_os_core import (
    AdoptionIngest,
    AdoptionLedger,
    ApprovalLiteRuntime,
    ProviderRegistry,
    SemanticRegistry,
    TemplateRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry
from agent_os_core.query_runtime import SQLiteQueryExecutor, StaticQueryExecutor

# Executor selection values accepted by RuntimeFactoryConfig.executor and --executor.
EXECUTOR_STATIC = "static"
EXECUTOR_SQLITE = "sqlite"

# Store backend selection for the loop's stateful stores (feedback/knowledge/snapshot).
STORE_MEMORY = "memory"
STORE_POSTGRES = "postgres"


@dataclass(frozen=True)
class RuntimeFactoryConfig:
    domain_pack_path: Path
    sample_rows: tuple[dict[str, Any], ...] = ({"order_date": "2026-05-31", "value": 128800.0},)
    # Which query executor to inject behind ProviderContract:
    #   "static" -> StaticQueryExecutor (deterministic fixture rows; default, unchanged)
    #   "sqlite" -> SQLiteQueryExecutor over the seeded Customer-0 data plane (real SQL)
    executor: str = EXECUTOR_STATIC
    # Which backend persists the loop's feedback/knowledge/snapshot stores:
    #   "memory" -> in-memory (default; per-process, lost on restart)
    #   "postgres" -> SQLAlchemy-Core stores from agent_os_persistence (durable, cross-session)
    store_backend: str = STORE_MEMORY
    # For "postgres": either an injected SQLAlchemy Engine (e.g. for tests) or a database_url.
    store_engine: Any = None
    database_url: str | None = None
    # Embedding dimensions for the default HashingEmbedder used by retrieval. MUST match
    # agent_os_persistence.schema.DEFAULT_EMBEDDING_DIMENSIONS (the pgvector 0004 column);
    # changing it requires regenerating that migration.
    embedding_dimensions: int = 64

    # 12-factor environment wiring (AR-20260611). Same DSN convention as Alembic's env.py.
    ENV_DOMAIN_PACK = "AGENT_OS_DOMAIN_PACK"
    ENV_EXECUTOR = "AGENT_OS_EXECUTOR"
    ENV_STORE_BACKEND = "AGENT_OS_STORE_BACKEND"
    ENV_DATABASE_URL = "AGENT_OS_DATABASE_URL"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RuntimeFactoryConfig:
        """Build the config from environment variables (defaults preserve current behavior).

        Misconfiguration fails loudly here, at startup, not at first request:
        an unknown executor/backend or ``postgres`` without a DSN raises ValueError.
        """
        data: Mapping[str, str] = os.environ if env is None else env
        executor = data.get(cls.ENV_EXECUTOR, EXECUTOR_STATIC)
        if executor not in (EXECUTOR_STATIC, EXECUTOR_SQLITE):
            raise ValueError(
                f"{cls.ENV_EXECUTOR}={executor!r} is not one of "
                f"{EXECUTOR_STATIC!r}, {EXECUTOR_SQLITE!r}."
            )
        backend = data.get(cls.ENV_STORE_BACKEND, STORE_MEMORY)
        if backend not in (STORE_MEMORY, STORE_POSTGRES):
            raise ValueError(
                f"{cls.ENV_STORE_BACKEND}={backend!r} is not one of "
                f"{STORE_MEMORY!r}, {STORE_POSTGRES!r}."
            )
        database_url = data.get(cls.ENV_DATABASE_URL) or None
        if backend == STORE_POSTGRES and not database_url:
            raise ValueError(
                f"{cls.ENV_STORE_BACKEND}={STORE_POSTGRES!r} requires {cls.ENV_DATABASE_URL}."
            )
        return cls(
            domain_pack_path=Path(data.get(cls.ENV_DOMAIN_PACK, "domain_packs/content_commerce")),
            executor=executor,
            store_backend=backend,
            database_url=database_url,
        )


class ContentCommerceRuntimeFactory:
    """Builds a runnable Trusted Loop from content commerce domain-pack contracts."""

    def __init__(self, config: RuntimeFactoryConfig) -> None:
        self.config = config
        # ONE retriever (and one engine) per factory: the runtime's recall and the
        # search surfaces must observe the same knowledge state (AR-20260611).
        self._retriever: Any = None
        self._engine: Any = None
        # ONE adoption ledger per factory (P5.1a, ADR-0001): the runtime's
        # read-only view and the operator's ingest must share the same value
        # channel. The runtime gets the view; only adoption_ingest() yields a writer.
        self._adoption_ledger: AdoptionLedger | None = None

    def build(self) -> TrustedLoopRuntime:
        metrics = self._load_metrics()
        providers = self._load_providers()
        templates = self._load_sql_templates()
        default_metric = metrics[templates[0].metric_name]
        # Strict registry: every metric the runtime serves must have its own template;
        # a metric without one fails loudly instead of running the wrong SQL.
        template_registry = TemplateRegistry(templates)

        # API layer owns connector construction (OS Core must not import connectors)
        connector_registry = self._build_default_connector_registry()

        # API layer owns store backend selection (OS Core must not import persistence).
        knowledge_store, feedback_store, snapshot_store, approval_runtime, uow, trace_store = (
            self._build_stores()
        )

        return TrustedLoopRuntime(
            metric_contract=default_metric,
            template_registry=template_registry,
            query_executor=self._build_query_executor(providers),
            semantic_registry=SemanticRegistry(metric_contracts=tuple(metrics.values())),
            provider_registry=ProviderRegistry(tuple(providers.values())),
            connector_registry=connector_registry,
            knowledge_store=knowledge_store,
            feedback_store=feedback_store,
            snapshot_store=snapshot_store,
            approval_runtime=approval_runtime,
            feedback_knowledge_uow=uow,
            # Read-side of the learning loop: the runtime recalls prior knowledge
            # through the SAME retriever the search surfaces use.
            knowledge_retriever=self.build_knowledge_retriever(),
            trace_store=trace_store,
            # Read-only port onto the external adoption value channel (P5.1a):
            # the runtime can read realized value, never write it.
            adoption_ledger_view=self._adoption_ledger_singleton().view(),
        )

    def _adoption_ledger_singleton(self) -> AdoptionLedger:
        if self._adoption_ledger is None:
            self._adoption_ledger = AdoptionLedger()
        return self._adoption_ledger

    def adoption_ingest(self) -> AdoptionIngest:
        """Operator-exclusive writer for realized external value (P5.1a).

        Returns an ``AdoptionIngest`` over the SAME ledger the runtime reads. The
        composition/operator layer holds this; the runtime is never given one, so
        OS Core code cannot mint realized value. The real entry point for the
        external value channel.
        """
        return AdoptionIngest(self._adoption_ledger_singleton())

    def _build_stores(self) -> tuple[Any, Any, Any, Any, Any, Any]:
        """Select the store backend for feedback/knowledge/snapshot/approval/trace.

        Returns ``(knowledge_store, feedback_store, snapshot_store, approval_runtime,
        uow, trace_store)``. For the default ``"memory"`` backend the unset members are
        ``None`` so the runtime uses its in-memory defaults. For ``"postgres"`` they are
        SQLAlchemy-Core stores from ``agent_os_persistence`` (imported lazily so the
        memory path needs no SQLAlchemy); the approval runtime is an
        ``ApprovalLiteRuntime`` over a durable approval store. OS Core never imports
        the persistence package — wiring lives in the composition layer.
        """
        backend = self.config.store_backend
        if backend == STORE_MEMORY:
            from agent_os_core import IndexingKnowledgeStore, KnowledgeStore

            # Wrap the in-memory store so runtime writes index into the shared
            # retriever — otherwise the memory backend's search/recall would run
            # against a permanently-empty fresh index (AR-20260611).
            knowledge_store = IndexingKnowledgeStore(
                KnowledgeStore(), self.build_knowledge_retriever()
            )
            return knowledge_store, None, None, None, None, None
        if backend == STORE_POSTGRES:
            from agent_os_persistence import (
                EmbeddingKnowledgeStore,
                SqlApprovalStore,
                SqlFeedbackStore,
                SqlKnowledgeStore,
                SqlSnapshotStore,
                SqlTraceStore,
                SqlUnitOfWork,
                create_all,
            )

            engine = self._resolve_engine()
            # Convenience for dev/first-run; production schema is owned by Alembic
            # migrations (create_all is a no-op when tables already exist).
            create_all(engine)
            embedder = self._embedder()
            # Write-side embedding cascade: maintain the knowledge_index on every
            # knowledge write (decorator lives here, NOT in OS Core).
            knowledge_store = EmbeddingKnowledgeStore(SqlKnowledgeStore(engine), embedder, engine)
            # The unit of work used by promote_from_adoption binds an embedding-aware
            # knowledge store to its connection, so the knowledge version bump AND the
            # index re-embed commit/roll back atomically (P5.1b: knowledge promotion is
            # driven by realized adoption, not self-report).
            uow = SqlUnitOfWork(
                engine,
                knowledge_store_factory=lambda conn: EmbeddingKnowledgeStore(
                    SqlKnowledgeStore(conn), embedder, conn
                ),
            )
            return (
                knowledge_store,
                SqlFeedbackStore(engine),
                SqlSnapshotStore(engine),
                ApprovalLiteRuntime(store=SqlApprovalStore(engine)),
                uow,
                SqlTraceStore(engine),
            )
        raise ValueError(
            f"Unknown store_backend {backend!r}; expected {STORE_MEMORY!r} or {STORE_POSTGRES!r}."
        )

    def build_knowledge_retriever(self) -> Any:
        """The factory's ONE KnowledgeRetriever for the configured backend (cached).

        The same instance serves the runtime's recall (build()) and the search
        surfaces (CLI/HTTP), so they observe the same knowledge state: ``memory``
        shares the in-memory index the IndexingKnowledgeStore writes to; ``postgres``
        shares state through the database (same engine).
        """
        if self._retriever is not None:
            return self._retriever
        from agent_os_core import HybridScorer, InMemoryKnowledgeRetriever

        if self.config.store_backend == STORE_MEMORY:
            self._retriever = InMemoryKnowledgeRetriever(self._embedder())
        elif self.config.store_backend == STORE_POSTGRES:
            from agent_os_persistence import SqlKnowledgeRetriever, create_all

            engine = self._resolve_engine()
            create_all(engine)
            self._retriever = SqlKnowledgeRetriever(engine, HybridScorer(self._embedder()))
        else:
            raise ValueError(f"Unknown store_backend {self.config.store_backend!r}.")
        return self._retriever

    def build_trace_store(self) -> Any:
        """A standalone TraceStorePort for audit surfaces (CLI ``trace``).

        ``memory`` returns a fresh per-process store (a separate CLI invocation
        cannot see a prior process's runs); ``postgres`` returns a SqlTraceStore
        over the shared engine, so any past run is auditable cross-process.
        """
        if self.config.store_backend == STORE_MEMORY:
            from agent_os_core import InMemoryTraceStore

            return InMemoryTraceStore()
        if self.config.store_backend == STORE_POSTGRES:
            from agent_os_persistence import SqlTraceStore, create_all

            engine = self._resolve_engine()
            create_all(engine)
            return SqlTraceStore(engine)
        raise ValueError(f"Unknown store_backend {self.config.store_backend!r}.")

    def _embedder(self) -> Any:
        from agent_os_core import HashingEmbedder

        return HashingEmbedder(dimensions=self.config.embedding_dimensions)

    def _resolve_engine(self) -> Any:
        """ONE engine per factory: build() and the retriever share the connection pool."""
        if self._engine is not None:
            return self._engine
        engine = self.config.store_engine
        if engine is None:
            if not self.config.database_url:
                raise ValueError(
                    "store_backend='postgres' requires either store_engine or database_url."
                )
            from sqlalchemy import create_engine

            engine = create_engine(self.config.database_url)
        self._engine = engine
        return engine

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
        schemas = {schema for provider in providers.values() for schema in provider.allowed_schemas}
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
        """Build a default connector registry.

        This lives in the API layer, not in OS Core, to enforce the boundary
        rule: OS Core never imports concrete action connectors. Two connectors
        are registered:

        - ``manual_review`` (no side effects): the safe default for proposals.
        - ``action_record`` (real, reversible write): the first connector that
          actually exercises the governance gate, pre-execution snapshot, and
          rollback. Proposals only route to it when they name it, so existing
          flows are unchanged.
        """
        from action_record import ActionRecordConnector, ActionRecordStore
        from manual_review import ManualReviewConnector

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
        registry.register(
            ActionRecordConnector(store=ActionRecordStore()),
            ActionConnectorContract(
                connector_name="action_record",
                display_name="Action Record",
                supported_action_types=("execute",),
                supports_snapshot=True,
                supports_rollback=True,
                compensating_action_description=(
                    "Restore the action record store to the pre-execution snapshot state"
                ),
                risk_ceiling="R3",
                owner="system",
            ),
        )
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
