from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_os_contracts import (
    ActionCandidate,
    ActionConnectorContract,
    ConnectorExecutionSemantics,
    DataClassification,
    MetricContract,
    ProviderContract,
    ProviderKind,
    QualityContract,
    RiskLevel,
    SQLTemplate,
)
from agent_os_contracts import (
    LinkType,
    ObjectLink,
    ObjectProperty,
    SemanticObject,
)
from agent_os_core import (
    AdoptionIngest,
    AdoptionLedger,
    ApprovalRouter,
    CheckpointStorePort,
    ApprovalLiteRuntime,
    CorrigibilityShell,
    DashboardStorePort,
    InMemoryDashboardStore,
    InMemoryTenantStore,
    InMemoryUsageStore,
    ProviderRegistry,
    SemanticGraph,
    SemanticRegistry,
    TenantStorePort,
    TrustedLoopRuntime,
    UsageStorePort,
)
from agent_os_contracts import RuntimeFeatureFlags
from agent_os_core.policy_engine import (
    AutoExecutionPolicyStore,
    PolicyApprovalRecordStore,
    PolicyEngine,
)
from agent_os_core.workflow import WorkflowRuntime
from agent_os_core.mcp_gateway import McpGatewayRegistry, McpToolRouter
from agent_os_core.workflow_store import InMemoryWorkflowStore
from agent_os_core.agent_runtime import AgentTraceWriter, TrustedLoopAgentRuntimeAdapter
from agent_os_core.action_connectors import ActionConnectorRegistry
from agent_os_core.nl_query import NLQueryEngine
from agent_os_core.query_runtime import SQLiteQueryExecutor, StaticQueryExecutor

from .executor_factory import ExecutorFactory
from .staged_out_trace import build_staged_out_trace_sink
from .heavy_infra_adapters import HeavyInfrastructureAdapters, build_heavy_infrastructure_adapters

# Executor selection values accepted by RuntimeFactoryConfig.executor and --executor.
EXECUTOR_STATIC = "static"
EXECUTOR_SQLITE = "sqlite"
EXECUTOR_POSTGRES = "postgres"
EXECUTOR_PROVIDER = "provider"

# Store backend selection for the loop's stateful stores (feedback/knowledge/snapshot).
STORE_MEMORY = "memory"
STORE_POSTGRES = "postgres"


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("1", "true", "yes", "on")


def _env_flag_value(val: str | None) -> bool:
    return bool(val) and val.lower() in ("1", "true", "yes", "on")


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
    # PostgreSQL DSN for the postgres query executor (separate from the store DSN).
    # The query executor reads business data; the store backend persists runtime state.
    postgres_dsn: str | None = None
    # Staged-out capability flags (ADR-0013); all default off.
    r4_r5_auto_execution: bool = False
    full_bpm_workflow: bool = False
    mcp_gateway: bool = False
    temporal_orchestration: bool = False
    opa_external_policy: bool = False
    trino_federation: bool = False

    # 12-factor environment wiring (AR-20260611). Same DSN convention as Alembic's env.py.
    ENV_DOMAIN_PACK = "AGENT_OS_DOMAIN_PACK"
    ENV_EXECUTOR = "AGENT_OS_EXECUTOR"
    ENV_STORE_BACKEND = "AGENT_OS_STORE_BACKEND"
    ENV_DATABASE_URL = "AGENT_OS_DATABASE_URL"
    ENV_POSTGRES_DSN = "AGENT_OS_POSTGRES_DSN"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RuntimeFactoryConfig:
        """Build the config from environment variables (defaults preserve current behavior).

        Misconfiguration fails loudly here, at startup, not at first request:
        an unknown executor/backend or ``postgres`` without a DSN raises ValueError.
        """
        data: Mapping[str, str] = os.environ if env is None else env
        executor = data.get(cls.ENV_EXECUTOR, EXECUTOR_STATIC)
        if executor not in (EXECUTOR_STATIC, EXECUTOR_SQLITE, EXECUTOR_POSTGRES, EXECUTOR_PROVIDER):
            raise ValueError(
                f"{cls.ENV_EXECUTOR}={executor!r} is not one of "
                f"{EXECUTOR_STATIC!r}, {EXECUTOR_SQLITE!r}, {EXECUTOR_POSTGRES!r}, {EXECUTOR_PROVIDER!r}."
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
        postgres_dsn = data.get(cls.ENV_POSTGRES_DSN) or None
        if executor == EXECUTOR_POSTGRES and not postgres_dsn:
            raise ValueError(
                f"{cls.ENV_EXECUTOR}={EXECUTOR_POSTGRES!r} requires {cls.ENV_POSTGRES_DSN}."
            )
        return cls(
            domain_pack_path=Path(data.get(cls.ENV_DOMAIN_PACK, "domain_packs/content_commerce")),
            executor=executor,
            store_backend=backend,
            database_url=database_url,
            postgres_dsn=postgres_dsn,
            r4_r5_auto_execution=_env_flag_value(data.get("AGENT_OS_R4_R5_AUTO_EXECUTION")),
            full_bpm_workflow=_env_flag_value(data.get("AGENT_OS_FULL_BPM_WORKFLOW")),
            mcp_gateway=_env_flag_value(data.get("AGENT_OS_MCP_GATEWAY")),
            temporal_orchestration=_env_flag_value(data.get("AGENT_OS_TEMPORAL_ORCHESTRATION")),
            opa_external_policy=_env_flag_value(data.get("AGENT_OS_OPA_EXTERNAL_POLICY")),
            trino_federation=_env_flag_value(data.get("AGENT_OS_TRINO_FEDERATION")),
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
        # ONE corrigibility shell per factory (P5.2a, ADR-0001): the operator keeps
        # the shell/op_* surface; every runtime built by this factory gets only the
        # read-only ShellView. This mirrors the adoption-channel split.
        self._corrigibility_shell: CorrigibilityShell | None = None
        # ONE Agent Runtime checkpoint store per factory: request-scoped runtime
        # adapters can checkpoint/resume through the configured backend without
        # importing persistence into OS Core.
        self._agent_checkpoint_store: CheckpointStorePort | None = None
        # ONE MCP gateway registry per factory (workstream C): server/tool registrations
        # persist for the factory lifetime; concrete transports are injected as handlers.
        self._mcp_gateway_registry: McpGatewayRegistry | None = None
        # ONE policy-approval record store per factory (workstream E): shared across
        # every TrustedLoopRuntime built by this factory.
        self._policy_approval_record_store: Any | None = None
        self._workflow_store: Any | None = None
        self._auto_execution_policy_store: Any | None = None
        self._policy_engine: PolicyEngine | None = None
        self._workflow_runtime: WorkflowRuntime | None = None
        self._trace_store_port: Any | None = None
        self._heavy_infra: HeavyInfrastructureAdapters | None = None

    def build_heavy_infrastructure_adapters(self) -> HeavyInfrastructureAdapters:
        if self._heavy_infra is None:
            self._heavy_infra = build_heavy_infrastructure_adapters(self._runtime_feature_flags())
        return self._heavy_infra

    def _shared_trace_store(self) -> Any:
        """One trace store per factory — shared by TrustedLoop, CLI audit, and C/D sinks."""
        if self._trace_store_port is not None:
            return self._trace_store_port
        if self.config.store_backend == STORE_POSTGRES:
            from agent_os_persistence import SqlTraceStore, create_all

            engine = self._resolve_engine()
            create_all(engine)
            self._trace_store_port = SqlTraceStore(engine)
        else:
            from agent_os_core.trace import InMemoryTraceStore

            self._trace_store_port = InMemoryTraceStore()
        return self._trace_store_port

    def load_domain_pack_manifest(self) -> Any:
        """Load DomainPack metadata via the SDK loader (workstream B convergence)."""
        from agent_os_sdk.domain_pack import DomainPackLoader

        loader = DomainPackLoader()
        packs = loader.load_from_directory(str(self.config.domain_pack_path))
        if not packs:
            raise ValueError(f"No domain pack manifest under {self.config.domain_pack_path}")
        return packs[0]

    def _validate_metrics_against_manifest(self, metrics: dict[str, MetricContract]) -> None:
        manifest = self.load_domain_pack_manifest()
        declared = set(manifest.metric_contracts)
        loaded = set(metrics.keys())
        missing = declared - loaded
        if missing:
            raise ValueError(
                f"Domain pack manifest declares metrics not loaded from metrics.json: "
                f"{sorted(missing)}"
            )

    def _runtime_feature_flags(self) -> RuntimeFeatureFlags:
        return RuntimeFeatureFlags(
            r4_r5_auto_execution=self.config.r4_r5_auto_execution,
            full_bpm_workflow=self.config.full_bpm_workflow,
            mcp_gateway=self.config.mcp_gateway,
            temporal_orchestration=self.config.temporal_orchestration,
            opa_external_policy=self.config.opa_external_policy,
            trino_federation=self.config.trino_federation,
        )

    def build_policy_approval_record_store(self) -> Any:
        """Policy approval record store for workstream E (memory or postgres)."""
        if self._policy_approval_record_store is not None:
            return self._policy_approval_record_store
        if self.config.store_backend == STORE_POSTGRES:
            from agent_os_persistence import SqlPolicyApprovalRecordStore

            self._policy_approval_record_store = SqlPolicyApprovalRecordStore(
                self._resolve_engine()
            )
        else:
            self._policy_approval_record_store = PolicyApprovalRecordStore()
        return self._policy_approval_record_store

    def build_workflow_store(self) -> Any:
        if self._workflow_store is not None:
            return self._workflow_store
        if self.config.store_backend == STORE_POSTGRES:
            from agent_os_persistence import SqlWorkflowStore

            self._workflow_store = SqlWorkflowStore(self._resolve_engine())
        else:
            self._workflow_store = InMemoryWorkflowStore()
        return self._workflow_store

    def build_auto_execution_policy_store(self) -> Any:
        if self._auto_execution_policy_store is not None:
            return self._auto_execution_policy_store
        if self.config.store_backend == STORE_POSTGRES:
            from agent_os_persistence import SqlAutoExecutionPolicyStore

            self._auto_execution_policy_store = SqlAutoExecutionPolicyStore(self._resolve_engine())
        else:
            self._auto_execution_policy_store = AutoExecutionPolicyStore()
        return self._auto_execution_policy_store

    def build_policy_engine(self) -> PolicyEngine | None:
        flags = self._runtime_feature_flags()
        if not flags.r4_r5_auto_execution:
            return None
        if self._policy_engine is None:
            shell = self.corrigibility_shell().view()
            self._policy_engine = PolicyEngine(
                flags,
                record_store=self.build_policy_approval_record_store(),
                policy_store=self.build_auto_execution_policy_store(),
                shell=shell,
            )
        return self._policy_engine

    def build_workflow_runtime(self) -> WorkflowRuntime | None:
        flags = self._runtime_feature_flags()
        if not flags.full_bpm_workflow:
            return None
        if self._workflow_runtime is None:
            self._workflow_runtime = WorkflowRuntime(
                flags,
                workflow_store=self.build_workflow_store(),
                trace_sink=build_staged_out_trace_sink(self._shared_trace_store()),
            )
        return self._workflow_runtime

    def mcp_registry(self) -> McpGatewayRegistry | None:
        if not self._runtime_feature_flags().mcp_gateway:
            return None
        if self._mcp_gateway_registry is None:
            self._mcp_gateway_registry = McpGatewayRegistry()
        return self._mcp_gateway_registry

    def build(self) -> TrustedLoopRuntime:
        # Templates remain the source of truth for verified query text; they are
        # folded into MetricContract.verified_queries so the DataProductCompiler
        # can select and bind plans without a hard-coded runtime template registry.
        templates = self._load_sql_templates()
        metrics = self._load_metrics(templates)
        self._validate_metrics_against_manifest(metrics)
        providers = self._load_providers()
        default_metric = metrics[templates[0].metric_name]

        # API layer owns connector construction (OS Core must not import connectors)
        connector_registry = self._build_default_connector_registry()

        # API layer owns store backend selection (OS Core must not import persistence).
        (
            knowledge_store,
            feedback_store,
            snapshot_store,
            approval_runtime,
            approval_context_store,
            uow,
            trace_store,
        ) = self._build_stores()

        query_executor, executor_factory = self._build_query_executor(providers)
        semantic_graph = self._load_semantic_graph()
        semantic_registry = SemanticRegistry(
            metric_contracts=tuple(metrics.values()),
            semantic_graph=semantic_graph,
        )
        return TrustedLoopRuntime(
            metric_contract=default_metric,
            query_executor=query_executor,
            executor_factory=executor_factory,
            semantic_registry=semantic_registry,
            provider_registry=ProviderRegistry(tuple(providers.values())),
            nl_query_engine=NLQueryEngine(metric_registry=semantic_registry),
            connector_registry=connector_registry,
            knowledge_store=knowledge_store,
            feedback_store=feedback_store,
            snapshot_store=snapshot_store,
            approval_runtime=approval_runtime,
            feedback_knowledge_uow=uow,
            approval_context_store=approval_context_store,
            # Read-side of the learning loop: the runtime recalls prior knowledge
            # through the SAME retriever the search surfaces use.
            knowledge_retriever=self.build_knowledge_retriever(),
            trace_store=trace_store or self._shared_trace_store(),
            # Read-only port onto the external adoption value channel (P5.1a):
            # the runtime can read realized value, never write it.
            adoption_ledger_view=self._adoption_ledger_singleton().view(),
            # Read-only capability view: runtime can observe pause state and audit
            # refusal, but it cannot pause/resume itself.
            shell_view=self.corrigibility_shell().view(),
            approval_router=self.build_approval_router(),
        )

    def build_approval_router(self) -> ApprovalRouter | None:
        """Construct the runtime approval router (AR-20260707 / ADR-0013).

        Reachable from the real app build path. Reads the staged-out feature
        flags from the environment and wires PolicyEngine + WorkflowRuntime when
        their flags are on. Returns None when no D/E flag is on (current MVP path,
        unchanged). MCP (workstream C) uses a separate gateway path.
        """
        flags = self._runtime_feature_flags()
        if not (flags.r4_r5_auto_execution or flags.full_bpm_workflow):
            return None
        policy_engine = self.build_policy_engine()
        workflow_runtime = self.build_workflow_runtime()
        return ApprovalRouter(
            flags,
            policy_engine=policy_engine,
            workflow_runtime=workflow_runtime,
        )

    def build_mcp_gateway(self) -> McpToolRouter | None:
        """MCP tool router for workstream C (default off)."""
        flags = self._runtime_feature_flags()
        if not flags.mcp_gateway:
            return None
        registry = self.mcp_registry()
        assert registry is not None
        return McpToolRouter(
            registry,
            flags,
            shell=self.corrigibility_shell().view(),
            trace_sink=build_staged_out_trace_sink(self._shared_trace_store()),
        )

    def build_agent_runtime_adapter(
        self,
        trusted_loop: TrustedLoopRuntime,
        *,
        checkpoint_store: CheckpointStorePort | None = None,
        trace_writer: AgentTraceWriter | None = None,
        mcp_router: McpToolRouter | None = None,
    ) -> TrustedLoopAgentRuntimeAdapter:
        """Request-scoped Agent Runtime adapter with optional MCP tools attached."""
        return TrustedLoopAgentRuntimeAdapter(
            trusted_loop,
            checkpoint_store=checkpoint_store or self.build_agent_checkpoint_store(),
            shell_view=getattr(trusted_loop, "shell_view", None),
            trace_writer=trace_writer,
            mcp_router=mcp_router if mcp_router is not None else self.build_mcp_gateway(),
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

    def corrigibility_shell(self) -> CorrigibilityShell:
        """Operator-exclusive sovereignty shell for pause/resume (P5.2a).

        The factory is the composition boundary: callers that represent the operator
        may hold this object and call ``op_*``. The runtime built by this factory is
        handed only ``shell.view()`` and therefore has no operator surface.
        """
        if self._corrigibility_shell is None:
            self._corrigibility_shell = CorrigibilityShell()
        return self._corrigibility_shell

    def _build_stores(self) -> tuple[Any, Any, Any, Any, Any, Any, Any]:
        """Select the store backend for feedback/knowledge/snapshot/approval/trace.

        Returns ``(knowledge_store, feedback_store, snapshot_store, approval_runtime,
        approval_context_store, uow, trace_store)``. For the default ``"memory"``
        backend the unset members are ``None`` so the runtime uses its in-memory
        defaults. For ``"postgres"`` they are SQLAlchemy-Core stores from
        ``agent_os_persistence`` (imported lazily so the memory path needs no
        SQLAlchemy); approval decisions and approval-resume contexts are durable.
        OS Core never imports the persistence package — wiring lives in the
        composition layer.
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
            return knowledge_store, None, None, None, None, None, None
        if backend == STORE_POSTGRES:
            from agent_os_persistence import (
                EmbeddingKnowledgeStore,
                SqlApprovalContextStore,
                SqlApprovalStore,
                SqlFeedbackStore,
                SqlKnowledgeStore,
                SqlSnapshotStore,
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
                SqlApprovalContextStore(engine),
                uow,
                self._shared_trace_store(),
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

        Returns the same store instance used by ``build()`` and staged-out C/D sinks.
        """
        return self._shared_trace_store()

    def build_usage_store(self) -> UsageStorePort:
        """A standalone UsageStorePort for quota gating.

        ``memory`` returns a fresh per-process in-memory store; ``postgres``
        returns a SqlUsageStore over the shared engine so usage accumulates
        across app instances.
        """
        if self.config.store_backend == STORE_MEMORY:
            return InMemoryUsageStore()
        if self.config.store_backend == STORE_POSTGRES:
            from agent_os_persistence import SqlUsageStore, create_all

            engine = self._resolve_engine()
            create_all(engine)
            return SqlUsageStore(engine)
        raise ValueError(f"Unknown store_backend {self.config.store_backend!r}.")

    def build_tenant_store(self) -> TenantStorePort:
        """A standalone TenantStorePort for tenant provisioning.

        ``memory`` returns a fresh per-process in-memory store; ``postgres`` returns
        a SqlTenantStore over the shared engine so tenant metadata survives restarts.
        """
        if self.config.store_backend == STORE_MEMORY:
            return InMemoryTenantStore()
        if self.config.store_backend == STORE_POSTGRES:
            from agent_os_persistence import SqlTenantStore, create_all

            engine = self._resolve_engine()
            create_all(engine)
            return SqlTenantStore(engine)
        raise ValueError(f"Unknown store_backend {self.config.store_backend!r}.")

    def build_dashboard_store(self) -> DashboardStorePort:
        """A standalone DashboardStorePort for the NL Data Product Workspace.

        ``memory`` returns a fresh per-process in-memory store; ``postgres`` returns
        a SqlDashboardStore over the shared engine so dashboards survive restarts.
        """
        if self.config.store_backend == STORE_MEMORY:
            return InMemoryDashboardStore()
        if self.config.store_backend == STORE_POSTGRES:
            from agent_os_persistence import SqlDashboardStore, create_all

            engine = self._resolve_engine()
            create_all(engine)
            return SqlDashboardStore(engine)
        raise ValueError(f"Unknown store_backend {self.config.store_backend!r}.")

    def build_agent_checkpoint_store(self) -> CheckpointStorePort:
        """Build the Agent Runtime checkpoint store for the configured backend.

        ``memory`` returns a factory-scoped ``InMemoryCheckpointStore``. ``postgres``
        returns a SQLAlchemy-backed ``SqlAgentCheckpointStore`` over the shared
        engine, so a later runtime instance can resume a checkpointed Agent Runtime
        boundary by ``run_id``. The composition layer owns this choice; OS Core only
        sees the ``CheckpointStorePort``.
        """
        if self._agent_checkpoint_store is not None:
            return self._agent_checkpoint_store
        if self.config.store_backend == STORE_MEMORY:
            from agent_os_core.agent_runtime import InMemoryCheckpointStore

            self._agent_checkpoint_store = InMemoryCheckpointStore()
        elif self.config.store_backend == STORE_POSTGRES:
            from agent_os_persistence import SqlAgentCheckpointStore, create_all

            engine = self._resolve_engine()
            create_all(engine)
            self._agent_checkpoint_store = SqlAgentCheckpointStore(engine)
        else:
            raise ValueError(f"Unknown store_backend {self.config.store_backend!r}.")
        return self._agent_checkpoint_store

    def build_report_snapshot_store(self) -> Any:
        """Build the report-read projection store for the configured backend."""
        if self.config.store_backend == STORE_MEMORY:
            from .outcome_service import InMemoryReportSnapshotStore

            return InMemoryReportSnapshotStore()
        if self.config.store_backend == STORE_POSTGRES:
            from agent_os_persistence import SqlReportSnapshotStore, create_all

            engine = self._resolve_engine()
            create_all(engine)
            return SqlReportSnapshotStore(engine)
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
    ) -> tuple[StaticQueryExecutor | SQLiteQueryExecutor | Any | None, Any | None]:
        """Select and construct the injected query executor.

        The static path (default) keeps the deterministic fixture rows. The sqlite
        path "rides the data plane": the application layer owns the data source,
        seeds the Customer-0 reference data behind ProviderContract, and hands a
        generic SQLiteQueryExecutor a connection. The postgres path creates a
        PostgresQueryExecutor from the composition layer using the configured DSN.
        The provider path defers executor construction to the provider's
        ``ProviderContract.connection``: the runtime receives an ``executor_factory``
        that builds the right executor (CSV, SQLite, PostgreSQL, MySQL, ClickHouse,
        Feishu) at query time based on the selected provider.
        OS Core never sees the data or imports database drivers.
        """
        if self.config.executor == EXECUTOR_STATIC:
            return StaticQueryExecutor(list(self.config.sample_rows)), None
        if self.config.executor == EXECUTOR_SQLITE:
            connection = self._build_seeded_connection(providers)
            return SQLiteQueryExecutor(connection), None
        if self.config.executor == EXECUTOR_POSTGRES:
            from .postgres_executor import PostgresQueryExecutor

            # When a store_engine is injected, reuse it for the query executor
            # (same database, shared connection pool).  Otherwise use the DSN.
            if self.config.store_engine is not None:
                return PostgresQueryExecutor(engine=self.config.store_engine), None
            if not self.config.postgres_dsn:
                raise ValueError(
                    f"executor={EXECUTOR_POSTGRES!r} requires postgres_dsn or store_engine."
                )
            return PostgresQueryExecutor(self.config.postgres_dsn), None
        if self.config.executor == EXECUTOR_PROVIDER:
            return None, ExecutorFactory.from_provider_contract
        raise ValueError(
            f"Unknown executor {self.config.executor!r}; "
            f"expected {EXECUTOR_STATIC!r}, {EXECUTOR_SQLITE!r}, "
            f"{EXECUTOR_POSTGRES!r}, or {EXECUTOR_PROVIDER!r}."
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
        connection = sqlite3.connect(":memory:", check_same_thread=False)
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

    def _build_default_connector_registry(self) -> ActionConnectorRegistry:
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

        action_record_store: Any
        if self.config.store_backend == STORE_MEMORY:
            action_record_store = ActionRecordStore()
        elif self.config.store_backend == STORE_POSTGRES:
            from agent_os_persistence import SqlActionRecordStore, create_all

            engine = self._resolve_engine()
            create_all(engine)
            action_record_store = SqlActionRecordStore(engine)
        else:
            raise ValueError(
                f"Unknown store_backend {self.config.store_backend!r}; expected "
                f"{STORE_MEMORY!r} or {STORE_POSTGRES!r}."
            )

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
            ActionRecordConnector(store=action_record_store),
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
                execution_semantics=ConnectorExecutionSemantics(
                    durability_scope="connector_local_ledger",
                    external_ack_status="not_applicable",
                    ledger_status="recorded",
                    supports_idempotency=True,
                    supports_reconciliation=True,
                ),
            ),
        )
        return registry

    def _load_metrics(self, templates: tuple[SQLTemplate, ...]) -> dict[str, MetricContract]:
        rows = self._read_json("metrics.json")
        templates_by_metric: dict[str, list[SQLTemplate]] = {}
        for template in templates:
            templates_by_metric.setdefault(template.metric_name, []).append(template)

        metrics: dict[str, MetricContract] = {}
        for row in rows:
            metric_name = row["metric_name"]
            verified_queries = self._load_verified_queries(
                row.get("verified_queries"), templates_by_metric.get(metric_name, ())
            )
            quality_contract = self._load_quality_contract(row.get("quality_contract"))
            action_candidates = self._load_action_candidates(row.get("action_candidates"))
            metrics[metric_name] = MetricContract(
                metric_name=metric_name,
                display_name=row["display_name"],
                definition=row["definition"],
                owner=row["owner"],
                unit=row["unit"],
                allowed_schemas=tuple(row["allowed_schemas"]),
                version=row.get("version", "v1"),
                dimensions=tuple(row.get("dimensions", ())),
                data_classification=DataClassification(row.get("data_classification", "internal")),
                verified_queries=verified_queries,
                quality_contract=quality_contract,
                action_candidates=action_candidates,
                feedback_metric=row.get("feedback_metric"),
            )
        if not metrics:
            raise ValueError("Domain pack must define at least one metric.")
        return metrics

    def _load_verified_queries(
        self,
        query_rows: list[dict[str, Any]] | None,
        fallback_templates: tuple[SQLTemplate, ...],
    ) -> tuple[SQLTemplate, ...]:
        if not query_rows:
            return fallback_templates
        return tuple(
            SQLTemplate(
                template_id=q["template_id"],
                metric_name=q["metric_name"],
                sql=q["sql"],
                required_parameters=tuple(q.get("required_parameters", ())),
                required_time_parameters=tuple(
                    q.get("required_time_parameters", ("start_date", "end_date"))
                ),
                default_limit=int(q.get("default_limit", 100)),
                max_limit=int(q.get("max_limit", 1000)),
                allow_select_star=bool(q.get("allow_select_star", False)),
            )
            for q in query_rows
        )

    def _load_quality_contract(self, payload: dict[str, Any] | None) -> QualityContract | None:
        if not payload:
            return None
        return QualityContract(
            freshness=payload.get("freshness"),
            null_rate=payload.get("null_rate"),
            owner=payload.get("owner"),
        )

    def _load_action_candidates(
        self, payload: list[dict[str, Any]] | None
    ) -> tuple[ActionCandidate, ...]:
        if not payload:
            return ()
        return tuple(
            ActionCandidate(
                action_id=c["action_id"],
                trigger=c.get("trigger"),
                risk_level=RiskLevel(c.get("risk_level", "R2")),
                description=c.get("description", ""),
            )
            for c in payload
        )

    def _load_semantic_graph(self) -> SemanticGraph:
        """Load domain-pack semantic objects + link types + links into a graph.

        Returns an empty graph when the domain pack has no semantic_objects.json,
        so older packs remain backward compatible.
        """
        graph = SemanticGraph()
        path = self.config.domain_pack_path / "semantic_objects.json"
        if not path.exists():
            return graph
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("objects", []):
            props = tuple(
                ObjectProperty(
                    name=p["name"],
                    data_type=p["data_type"],
                    required=p.get("required", False),
                    description=p.get("description", ""),
                    bound_column=p.get("bound_column"),
                )
                for p in row.get("properties", [])
            )
            graph.register_object(
                SemanticObject(
                    object_id=row["object_id"],
                    name=row["name"],
                    object_type=row["object_type"],
                    description=row.get("description", ""),
                    owner=row.get("owner", ""),
                    aliases=tuple(row.get("aliases", [])),
                    related_metrics=tuple(row.get("related_metrics", [])),
                    properties=props,
                )
            )
        for row in data.get("link_types", []):
            graph.register_link_type(
                LinkType(
                    link_type_id=row["link_type_id"],
                    name=row["name"],
                    source_object_type=row["source_object_type"],
                    target_object_type=row["target_object_type"],
                    description=row.get("description", ""),
                )
            )
        for row in data.get("links", []):
            graph.register_link(
                ObjectLink(
                    link_id=row["link_id"],
                    link_type_id=row["link_type_id"],
                    source_object_id=row["source_object_id"],
                    target_object_id=row["target_object_id"],
                )
            )
        return graph

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
