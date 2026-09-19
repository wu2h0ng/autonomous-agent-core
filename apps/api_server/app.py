from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from dataclasses import replace
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import ValidationError

from agent_os_contracts import (
    AGENT_SPAWN_CAPABILITY_ID,
    EXPLORE_ALLOWED_CAPABILITY_IDS,
    STOP_REASON_STOPPED_BY_OPERATOR,
    ActionContract,
    ApprovalDecision,
    ApprovalDisposition,
    CapabilityGrant,
    CapabilityGrantStatus,
    ChildAgentContractError,
    ChildAgentFinished,
    ChildAgentSpawnCommand,
    ChildAgentSpawned,
    ChildAgentBurialRecord,
    ChildAgentOrphanProjection,
    ChildAgentStatus,
    ChildAgentType,
    ChildAgentSpawnResult,
    PermissionMode,
    derive_child_grants,
    CandidateEvaluationDraft,
    CandidateEvaluationReceipt,
    CandidatePromotionCommand,
    CandidatePromotionDecision,
    CandidatePromotionResult,
    Commitment,
    CreateMandateCommand,
    CredentialRef,
    CredentialStatus,
    DomainCandidate,
    DomainCandidateDraft,
    DomainPriorArtifact,
    ExpectedOutcome,
    EnvironmentEventAdmissionReceipt,
    ExternalSignal,
    Goal,
    HelpRequest,
    MandateObservationAuthorizationCommand,
    MandateTaskLinkCommand,
    MandateTaskLinkRevocationCommand,
    NodeKind,
    NodeSpec,
    ObservationBindingDescriptor,
    OutcomeStatus,
    PrincipalIdentity,
    PrincipalRole,
    ProviderProfile,
    ProviderFailure,
    ProviderInvocationBinding,
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
    ProtocolIngressReceipt,
    RecoveredUnknownTurn,
    ResourceBudget,
    RunStatus,
    TaskConfigurationSnapshot,
    TaskConfigurationSnapshotCommand,
    TaskEventType,
    TaskDraftProposal,
    TaskStatus,
    TrajectoryProjection,
    TurnTrace,
    WorkflowGraph,
    SessionRef,
    SURFACE_PROTOCOL_VERSION,
    SurfaceApprovalCommand,
    SurfaceChildAgentReconcileCommand,
    SurfaceChildAgentsResponse,
    SurfaceBeginTurnCommand,
    SurfaceBeginTurnResponse,
    SurfaceCorrectionCommand,
    SurfaceEventBatch,
    SurfaceOpenSessionCommand,
    SurfaceProviderClearCommand,
    SurfaceProviderConfigureCommand,
    SurfaceProviderStatus,
    SurfaceSessionListResponse,
    SurfaceSessionSnapshot,
    SurfaceSessionSummary,
    SurfaceSetPermissionModeCommand,
    SurfaceSessionStatus,
    SurfaceConflictProjection,
    SurfaceStreamFrameKind,
    SurfaceTurnCommand,
    SurfaceTurnRecoveryCommand,
    SurfaceTurnRecoveryResponse,
    SurfaceTurnResponse,
    TurnId,
    content_digest,
)
from agent_os_core import (
    CHILD_AGENT_RECONCILE_OUTCOME,
    CHILD_AGENT_RECONCILE_REASON_RUNTIME_GONE,
    CHILD_AGENT_RECONCILE_REASON_SPAWN_ABANDONED,
    CHILD_AGENT_STOP_REASON_AWAITING_APPROVAL,
    CHILD_AGENT_STOP_REASON_PARENT_CLOSED,
    CHILD_AGENT_STOP_REASON_UNKNOWN,
    CHILD_AGENT_STOP_REASON_WALL_CLOCK,
    ChildAgentBurial,
    ChildAgentBurialRefused,
    ChildAgentChild,
    ChildAgentDisabled,
    ChildAgentHaltCascade,
    ChildAgentIndex,
    ChildAgentLinkError,
    ChildAgentNotSpawnable,
    ChildAgentSpawnRequest,
    CapabilityEffectUnknown,
    child_agent_spawn_result,
    child_agent_status_for_stop_reason,
    child_agent_timeout_seconds,
    child_agents_enabled,
    chat_capability_ids,
    grants_digest,
    orphaned_children,
    spawn_prompt_digest,
    summary_digest,
    TurnResult,
)
from agent_os_core import (
    C7ReceiptIssuer,
    C7ReceiptVerifier,
    PlanRegistrationDenialReason,
    SQLitePermissionRuleStore,
    SQLiteSrlExecutionPlanStore,
    SrlExecutionPlan,
    SrlExecutionPlanRegistrationError,
    SrlExecutionPlanRegistry,
    SrlExecutionResult,
    SrlTaskExecutionBridge,
    plan_binds,
    SurfaceRuntime,
    SurfaceSessionNotFound,
    SessionStreamRegistry,
    SurfaceStreamGone,
    AgentLoop,
    AgentLoopConfig,
    apply_trusted_shell_profile,
    discover_agents_markdown_layers,
    layered_agents_markdown_system_section,
    CHAT_GRANT_MAX_RISK_TIERS,
    CandidateScopeMismatch,
    CapabilityBroker,
    ReplanRequired,
    WorkspaceWriteRejected,
    ChatSession,
    ConfirmationGateway,
    CandidateEvaluationScopeMismatch,
    CandidatePromotionScopeMismatch,
    Clock,
    ConcurrentWriteError,
    CorrectionAuthority,
    DeferredApprovalGateway,
    DeterministicProvider,
    PolicyKernel,
    MandateSteward,
    RunCoordinator,
    DomainCandidateSealer,
    DomainCandidateEvaluationRecorder,
    DomainCandidatePromotionService,
    EVALUATION_CAPABILITY,
    InvalidTransitionError,
    PROMOTION_CAPABILITY,
    SQLiteCandidateStore,
    SQLiteCandidateEvaluationStore,
    SQLiteCandidatePromotionStore,
    SQLiteTaskEventStore,
    SQLiteMandateWorkspaceStore,
    SQLiteMandateObservationAuthorizationStore,
    MandateResponsibilityProjector,
    SQLiteMandateOutcomePortfolioStore,
    SQLiteMandateResponsibilityStore,
    SessionProjectionError,
    SessionProjector,
    SituationalScopeMismatch,
    SituationalTrustDenied,
    SituationalTrustResolver,
    SurfaceTurnOwnedByLiveRuntime,
    TaskService,
    EnvCredentialBroker,
    AnthropicMessagesProvider,
    GeminiGenerativeProvider,
    OpenAICompatibleProvider,
    build_recovery_snapshot,
    dead_turn_recovery_notice,
    PromotionPolicyRegistry,
    split_correction_authority,
    PromotionPolicyV1,
    POLICY_KERNEL_V1_DIGEST,
    TASK_CONFIGURATION_CAPABILITY,
    TASK_CONFIGURATION_CAPABILITY_VERSION,
    TaskConfigurationNotBound,
    TaskConfigurationRuntime,
    TaskConfigurationSnapshotService,
)
from agent_os_core.action_pipeline import ActionPipeline
from agent_os_core.execution import EffectCustodyPort
from agent_os_core.session_projection import SessionLoopConfig
from agent_os_core.trajectory import TrajectoryProjector
from agent_os_core.turn_trace import build_turn_trace
from domain_packs.developer_agent import (
    EXECUTION_ISOLATION_TRUSTED_WORKSPACE,
    DeveloperRepositoryPatchProfile,
    DeveloperWorkspaceAdapter,
    SQLiteWorkspaceCommitFence,
    WorkspaceCollaborationPreflight,
    WorkspaceCommitFence,
    manifest as developer_agent_manifest,
)
from domain_packs.data_agent.contracts import (
    BusinessActionProposalRequest,
    DataAgentRequest,
)
from domain_packs.data_agent.runtime import (
    DATA_QUERY_CAPABILITY_ID,
    DataAgentRuntime,
    SQLiteDataQueryCapability,
)
from domain_packs.data_agent.report_adapter import (
    DataAgentReportAdapter,
    DataAgentReportPollResult,
    TrustedObservationBundle,
)
from domain_packs.data_agent.situated import DataAgentSituatedRuntime

from .provider_settings import (
    DEFAULT_CREDENTIAL_ENV,
    clear_provider_config,
    default_credential_store,
    load_provider_config,
    resolve_provider_key,
    save_provider_config,
)
from .mandate_active_perception import (
    ActivePerceptionReceipt,
    MandateActivePerceptionService,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _static_grant_ceiling(
    grants: Mapping[str, CapabilityGrant],
) -> ResourceBudget:
    """The parent's **static** grant ceiling (never a running remaining budget).

    This repository has no consumption ledger, so there is no measured "parent
    remaining budget" to subtract from. What ``derive_child_grants`` receives
    here is the widest static ceiling the parent holds, which is enough to prove
    the non-widening property (the child's own per-capability ceiling is checked
    separately against its parent grant) and is explicitly *not* a claim that
    the parent has that much budget left.
    """

    if not grants:
        raise ChildAgentNotSpawnable(
            "child agent derivation requires the parent's grants"
        )
    limits = [grant.budget_limit for grant in grants.values()]
    return ResourceBudget(
        max_cost_usd=max(limit.max_cost_usd for limit in limits),
        max_duration_seconds=max(limit.max_duration_seconds for limit in limits),
        max_provider_tokens=max(limit.max_provider_tokens for limit in limits),
        max_tool_calls=max(limit.max_tool_calls for limit in limits),
    )


def _child_agent_block(
    request: ChildAgentSpawnRequest,
    session: ChatSession,
    grants: Mapping[str, CapabilityGrant],
) -> dict[str, object]:
    """The durable child link written into the child session's ``SESSION_OPENED``.

    It carries the frozen link triple (``parent_session_id``/``parent_turn_id``/
    ``spawn_id``), the durable parent task/run the halt cascade walks, the
    narrowed grant block the restore path rebuilds (so a restart cannot widen a
    child), the owning runtime generation (so a crash is detectable), and the
    prompt **digest** - never the prompt.
    """

    dumped = {cid: grant.model_dump(mode="json") for cid, grant in grants.items()}
    return {
        "spawn_id": request.spawn_id,
        "parent_session_id": request.parent_session_id,
        "parent_task_id": request.parent_task_id,
        "parent_run_id": request.parent_run_id,
        "parent_turn_id": request.parent_turn_id,
        "child_session_id": session.session_id,
        "child_task_id": session.task_id,
        "agent_type": request.agent_type.value,
        "description": request.description,
        "prompt_digest": spawn_prompt_digest(request.prompt),
        "spawn_runtime_boot_id": request.runtime_boot_id,
        "spawn_runtime_pid": request.runtime_pid,
        "grants": dumped,
        "grant_plan_digest": grants_digest(dumped),
    }


def _loop_config_with_agents(config: AgentLoopConfig, workspace: Path) -> AgentLoopConfig:
    """Attach bounded, layered workspace AGENTS.md/CLAUDE.md context (S3).

    Fail-closed, bounded discovery (symlink / out-of-workspace / oversized skipped)
    is enforced by `discover_agents_markdown_layers`; this only injects prompt
    context and never widens authority. No instruction files is a no-op.
    """
    layers = discover_agents_markdown_layers(workspace)
    if not layers:
        return config
    return replace(
        config,
        system_prompt=config.system_prompt
        + layered_agents_markdown_system_section(layers),
    )


class AgentOSApplication:
    """Composition root used unchanged by the CLI, HTTP API and tests."""

    @classmethod
    def _with_data_agent_situated_runtime(
        cls,
        *,
        situated_runtime: DataAgentSituatedRuntime,
        principal: PrincipalIdentity,
        active_perception_service: MandateActivePerceptionService | None = None,
        database: str | Path = ":memory:",
        workspace: str | Path = ".",
        clock: Clock = _utc_now,
        **application_options: Any,
    ) -> AgentOSApplication:
        """Bind an already-composed Data Agent runtime to one authenticated scope."""
        if (
            type(situated_runtime) is not DataAgentSituatedRuntime
            or not situated_runtime._is_bootstrap_composed()
        ):
            raise TypeError("binding requires the concrete Data Agent situated runtime")
        forbidden_options = {"data_agent_reports", "situational_trust"}.intersection(
            application_options
        )
        if forbidden_options:
            raise ValueError(
                "Data Agent situated runtime cannot bind a second situated trust chain"
            )
        expected_scope = (
            principal.principal_id,
            principal.tenant_id,
            principal.workspace_id,
        )
        if situated_runtime.principal_scope != expected_scope:
            raise SituationalScopeMismatch(
                "Data Agent situated runtime scope does not match application principal"
            )
        application = cls(
            database=database,
            workspace=workspace,
            principal=principal,
            clock=clock,
            **application_options,
        )
        application._data_agent_situated_runtime = situated_runtime
        if active_perception_service is not None:
            if active_perception_service._runtime is not situated_runtime:
                raise TypeError("active perception must use the bound situated runtime")
            application._mandate_active_perception_service = active_perception_service
        return application

    @classmethod
    def _with_mandate_steward(
        cls,
        *,
        mandate_steward: MandateSteward,
        database: str | Path = ":memory:",
        workspace: str | Path = ".",
        principal: PrincipalIdentity,
        clock: Clock = _utc_now,
        situational_trust: SituationalTrustResolver | None = None,
        data_agent_reports: DataAgentReportAdapter | None = None,
        observation_binding_descriptors: tuple[ObservationBindingDescriptor, ...] = (),
        **application_options: Any,
    ) -> AgentOSApplication:
        """Bind one pre-composed, scope-authenticated steward to the application."""
        expected_scope = (
            principal.principal_id,
            principal.tenant_id,
            principal.workspace_id,
        )
        actual_scope = mandate_steward.scope
        if (
            actual_scope.principal_id,
            actual_scope.tenant_id,
            actual_scope.workspace_id,
        ) != expected_scope:
            raise SituationalScopeMismatch(
                "MandateSteward scope does not match application principal"
            )
        application = cls(
            database=database,
            workspace=workspace,
            principal=principal,
            clock=clock,
            situational_trust=situational_trust,
            data_agent_reports=data_agent_reports,
            observation_binding_descriptors=observation_binding_descriptors,
            **application_options,
        )
        application._mandate_steward = mandate_steward
        return application

    def __init__(
        self,
        *,
        database: str | Path = ":memory:",
        workspace: str | Path = ".",
        principal: PrincipalIdentity | None = None,
        evaluation_grant: CapabilityGrant | None = None,
        promotion_grant: CapabilityGrant | None = None,
        clock: Clock = _utc_now,
        situational_trust: SituationalTrustResolver | None = None,
        data_agent_reports: DataAgentReportAdapter | None = None,
        data_agent_query_database: str | Path | None = None,
        data_agent_query_grant: CapabilityGrant | None = None,
        observation_binding_descriptors: tuple[ObservationBindingDescriptor, ...] = (),
        trusted_shell_profile: bool | None = None,
        execution_isolation: str | None = None,
        child_agents: bool | None = None,
        nested_child_agents: bool | None = None,
    ) -> None:
        self._clock = clock
        now = self._clock()
        self.principal = principal or PrincipalIdentity(
            principal_id="user:local",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            role=PrincipalRole.PRINCIPAL,
            authenticated_at=now,
        )
        self._evaluation_grant_override = evaluation_grant
        self._promotion_grant_override = promotion_grant
        self._configuration_lock = RLock()
        canonical_database: str | Path = database
        canonical_database_uri = False
        if str(database) == ":memory:":
            canonical_database = f"file:agent-os-{uuid4().hex}?mode=memory&cache=shared"
            canonical_database_uri = True
        self.store = SQLiteTaskEventStore(
            canonical_database,
            uri=canonical_database_uri,
        )
        self.mandate_workspace = SQLiteMandateWorkspaceStore(
            canonical_database,
            uri=canonical_database_uri,
        )
        self.observation_binding_descriptors = observation_binding_descriptors
        self.mandate_observation_authorizations = (
            SQLiteMandateObservationAuthorizationStore(
                database,
                mandate_workspace=self.mandate_workspace,
                descriptors=observation_binding_descriptors,
            )
            if str(database) != ":memory:" and observation_binding_descriptors
            else None
        )
        self.tasks = TaskService(self.store, clock=self._clock)
        # S2: durable, operator-authored, DENY-only permission rules (fail-closed;
        # consulted after the frozen E2 gate, can only restrict).
        self.permission_rule_store = SQLitePermissionRuleStore(
            canonical_database,
            uri=canonical_database_uri,
        )
        self.mandate_responsibility_store = SQLiteMandateResponsibilityStore(
            canonical_database,
            clock=self._clock,
            uri=canonical_database_uri,
        )
        self.mandate_responsibility = MandateResponsibilityProjector(
            self.mandate_responsibility_store,
            self.tasks,
            clock=self._clock,
        )
        self.mandate_outcome_portfolio_store = SQLiteMandateOutcomePortfolioStore(
            canonical_database,
            clock=self._clock,
            uri=canonical_database_uri,
            task_reader=self.tasks,
        )
        if (
            situational_trust is not None
            and data_agent_reports is not None
            and situational_trust is not data_agent_reports
        ):
            raise ValueError(
                "data_agent_reports must be the configured situational trust resolver"
            )
        if data_agent_reports is not None and data_agent_reports.principal_scope != (
            self.principal.principal_id,
            self.principal.tenant_id,
            self.principal.workspace_id,
        ):
            raise SituationalScopeMismatch(
                "Data Agent report source scope does not match application principal"
            )
        if data_agent_reports is not None and not data_agent_reports.has_durable_state:
            raise ValueError(
                "Data Agent report source requires durable first-seen state"
            )
        self.data_agent_reports = data_agent_reports
        self._data_agent_situated_runtime: DataAgentSituatedRuntime | None = None
        self._mandate_active_perception_service: (
            MandateActivePerceptionService | None
        ) = None
        self._mandate_steward: MandateSteward | None = None
        self.workspace_root = Path(workspace).resolve()
        # OS-SANDBOX-0 (opt-in): OS filesystem isolation sits below the
        # permit/approval spine; default is the prior trusted-workspace
        # behaviour. Never implicit, never a gate input.
        self.execution_isolation = (
            execution_isolation
            if execution_isolation is not None
            else os.environ.get("AGENT_OS_EXECUTION_ISOLATION")
            or EXECUTION_ISOLATION_TRUSTED_WORKSPACE
        )
        # Form B (ADR-0061): child agents are OFF unless this composition root
        # is explicitly told to enable them (constructor flag or
        # AGENT_OS_CHILD_AGENTS=on). Off means agent.spawn is not registered in
        # the connector's trusted registry and not granted, so the capability is
        # refused with a typed reason in every mode - not silently ignored.
        self.child_agents_enabled = (
            child_agents
            if child_agents is not None
            else child_agents_enabled(os.environ)
        )
        # Nested spawn stays OFF by default and is independent of the above.
        self.nested_child_agents_enabled = (
            nested_child_agents
            if nested_child_agents is not None
            else _env_truthy("AGENT_OS_NESTED_CHILD_AGENTS")
        )
        self._live_child_spawns: set[str] = set()
        self._live_child_lock = RLock()
        self.sandbox = DeveloperWorkspaceAdapter(
            workspace,
            idempotency_store=self.store,
            execution_isolation=self.execution_isolation,
        )
        self.sandbox.bind_child_agent_spawner(
            self, enabled=self.child_agents_enabled
        )
        # M2 (opt-in, mainstream-aligned): the trusted shell profile broadens
        # the shell allowlist, so it is OFF unless explicitly requested (ctor
        # flag) or opted in via env. Never implicit.
        if trusted_shell_profile if trusted_shell_profile is not None else _env_truthy(
            "AGENT_OS_TRUSTED_SHELL_PROFILE"
        ):
            apply_trusted_shell_profile(self.sandbox)
        self.workspace_fence = (
            WorkspaceCommitFence()
            if str(database) == ":memory:"
            else SQLiteWorkspaceCommitFence(f"{canonical_database}.collaboration")
        )
        self.collaboration_preflight = WorkspaceCollaborationPreflight(
            self.workspace_fence
        )
        self._surface_conflicts: dict[str, SurfaceConflictProjection] = {}
        # Turn ownership for THIS runtime generation only: session -> token of
        # the begin-turn/synchronous turn this process is executing. In-memory
        # by construction - a live owner is a process-local fact - and the only
        # sound liveness test a dead-turn declaration can be checked against.
        self._surface_turns_in_flight: dict[str, str] = {}
        self._surface_turns_guard = RLock()
        self.execution_profile = DeveloperRepositoryPatchProfile()
        self.tasks.bind_artifact_reader(self.sandbox.read_artifact_bytes)
        self._correction_authority = CorrectionAuthority(
            self.store,
            tenant_id=self.principal.tenant_id,
            workspace_id=self.principal.workspace_id,
            written_by=self.principal.principal_id,
        )
        self.correction, self.correction_admin = split_correction_authority(
            self._correction_authority
        )
        self.tasks.bind_correction_reader(self.correction)
        self.candidates = SQLiteCandidateStore(database)
        self.evaluation_receipts = SQLiteCandidateEvaluationStore(database)
        self.promotion_policies = PromotionPolicyRegistry((PromotionPolicyV1(),))
        self.candidate_promotions = SQLiteCandidatePromotionStore(
            self.evaluation_receipts.ledger,
            self.promotion_policies,
        )
        self.domain_candidates = DomainCandidateSealer(
            self.tasks,
            self.correction,
            self.candidates,
            clock=self._clock,
        )
        self.policy = PolicyKernel(self.correction)
        if (data_agent_query_database is None) != (data_agent_query_grant is None):
            raise ValueError(
                "Data Agent query database and capability grant must be configured together"
            )
        self.data_agent_runtime: DataAgentRuntime | None = None
        if data_agent_query_database is not None and data_agent_query_grant is not None:
            if (
                data_agent_query_grant.principal_id != self.principal.principal_id
                or data_agent_query_grant.tenant_id != self.principal.tenant_id
                or data_agent_query_grant.workspace_id != self.principal.workspace_id
                or data_agent_query_grant.capability_id != DATA_QUERY_CAPABILITY_ID
            ):
                raise ValueError(
                    "Data Agent query grant must match the application principal scope"
                )
            connector = SQLiteDataQueryCapability(data_agent_query_database)
            connector.bind_idempotency_store(self.tasks._event_store)
            pipeline = ActionPipeline(
                self.tasks,
                CapabilityBroker(connector, self.correction),
                self.policy,
                self.correction,
                data_agent_query_grant,
            )
            self.data_agent_runtime = DataAgentRuntime(
                tasks=self.tasks,
                pipeline=pipeline,
                capability_spec=connector.specs()[DATA_QUERY_CAPABILITY_ID],
            )
        live_base_url, live_model, credential_key, live_endpoint_class = (
            self._resolve_live_provider_env()
        )
        live_model_revision_digest = os.environ.get(
            "AGENT_OS_PROVIDER_MODEL_REVISION_DIGEST"
        )
        credential_ref = CredentialRef(
            credential_ref_id="credential:default",
            owner_principal_id=self.principal.principal_id,
            tenant_id=self.principal.tenant_id,
            workspace_id=self.principal.workspace_id,
            provider_id=live_endpoint_class,
            resolver_key=credential_key,
            scopes=("chat",),
            status=CredentialStatus.ACTIVE,
            created_at=now,
            expires_at=now + timedelta(days=30),
        )
        built_in_profile_created_at = datetime(1970, 1, 1, tzinfo=timezone.utc)
        self.provider_profile = ProviderProfile(
            profile_id="provider-profile:default",
            provider_id=live_endpoint_class if live_base_url else "deterministic",
            model_id=live_model if live_base_url else "deterministic-v1",
            model_revision_digest=live_model_revision_digest,
            endpoint_class=live_endpoint_class if live_base_url else "test",
            credential_ref_id=credential_ref.credential_ref_id,
            capabilities=("chat",),
            max_context_tokens=16_000,
            request_timeout_seconds=60,
            created_at=built_in_profile_created_at,
        )
        deterministic_binding = ProviderInvocationBinding(
            provider_profile=self.provider_profile,
            provider_id=self.provider_profile.provider_id,
            endpoint_class=self.provider_profile.endpoint_class,
            credential_ref_id=self.provider_profile.credential_ref_id,
            credential_ref_digest=content_digest(credential_ref),
            max_context_tokens=self.provider_profile.max_context_tokens,
            adapter_kind="deterministic",
            transport="in-process",
            base_url="in-process:deterministic",
            endpoint_path="/complete",
            model_id=self.provider_profile.model_id,
            request_timeout_seconds=self.provider_profile.request_timeout_seconds,
            temperature=Decimal("0"),
        )
        provider_class = self._provider_class_for(live_endpoint_class)
        self.provider = (
            provider_class(
                base_url=live_base_url,
                model=live_model,
                credential=credential_ref,
                credentials=EnvCredentialBroker(),
                timeout_seconds=60,
                provider_profile=self.provider_profile,
            )
            if live_base_url
            else DeterministicProvider(
                text="provider proposal accepted",
                invocation_binding=deterministic_binding,
            )
        )
        self.provider_configured = bool(live_base_url)
        # The managed resolver key for the active runtime-configured provider
        # (None when the built-in/env provider is in use; only keys created by
        # configure_provider are ever purged).
        self._active_provider_resolver_key: str | None = None
        if not self.provider_configured:
            # Re-install a previously configured provider (non-secret config
            # from disk + key from the OS keychain or environment).
            self._try_load_persisted_provider()
        self.grants = self._build_grants(now)
        self.task_configurations = TaskConfigurationSnapshotService(
            self.tasks,
            self.correction,
            configuration_lock=self._configuration_lock,
            configuration_reader=self._task_configuration_runtime,
            candidates=self.candidates,
            evaluations=self.evaluation_receipts,
            promotions=self.candidate_promotions,
            clock=self._clock,
        )
        # P0-3 Increment 1 production wiring: the SRL execution bridge is composed
        # here. Its plan source is a composition-root-owned trusted registry that a
        # trusted organ populates; no HTTP/CLI path accepts a caller-supplied plan.
        # N7: the registry is backed by the canonical SQLite DB so registered plans
        # survive a process restart (memory-only DBs keep the same in-process cache).
        self.srl_execution_plan_store = SQLiteSrlExecutionPlanStore(
            canonical_database,
            uri=canonical_database_uri,
        )
        self.srl_execution_plans = SrlExecutionPlanRegistry(
            store=self.srl_execution_plan_store
        )
        self.srl_execution = SrlTaskExecutionBridge(
            task_service=self.tasks,
            plan_port=self.srl_execution_plans,
            task_snapshots=self.task_configurations,
            principal=self.principal,
            correction=self.correction,
            c7_issuer=C7ReceiptIssuer(
                self.correction,
                tenant_id=self.principal.tenant_id,
                workspace_id=self.principal.workspace_id,
                issuer_id=self.principal.principal_id,
            ),
            c7_verifier=C7ReceiptVerifier(self.correction),
        )
        self.domain_candidate_evaluations = DomainCandidateEvaluationRecorder(
            self.tasks,
            self.correction,
            self.candidates,
            self.evaluation_receipts,
            self.grants,
            clock=self._clock,
        )
        self.domain_candidate_promotions = DomainCandidatePromotionService(
            self.tasks,
            self.correction,
            self.candidates,
            self.evaluation_receipts,
            self.candidate_promotions,
            self.grants,
            self.promotion_policies,
            clock=self._clock,
        )
        self.compensation_grant = self._build_compensation_grant(now)
        self.domain_manifest = developer_agent_manifest(now)
        self._runtime_boot_id = uuid4().hex
        self._stream_registry = SessionStreamRegistry(
            runtime_boot_id=self._runtime_boot_id
        )
        self.surface = SurfaceRuntime(self, stream_registry=self._stream_registry)

    def _build_grants(self, now: datetime | None = None) -> dict[str, CapabilityGrant]:
        issued = now or self._clock()
        specs = self.sandbox.specs(issued)
        grants = {
            capability_id: CapabilityGrant(
                grant_id=f"grant:{capability_id}",
                principal_id=self.principal.principal_id,
                tenant_id=self.principal.tenant_id,
                workspace_id=self.principal.workspace_id,
                capability_id=capability_id,
                capability_version="1",
                max_risk_tier=spec.risk_tier,
                budget_limit=ResourceBudget(
                    max_cost_usd=Decimal("10"),
                    max_duration_seconds=3600,
                    max_provider_tokens=100_000,
                    max_tool_calls=100,
                ),
                status=CapabilityGrantStatus.ACTIVE,
                granted_by="system",
                granted_at=issued,
                expires_at=issued + timedelta(days=30),
            )
            for capability_id, spec in specs.items()
        }
        self.evaluation_grant = (
            self._evaluation_grant_override or self._build_evaluation_grant(issued)
        )
        grants[EVALUATION_CAPABILITY] = self.evaluation_grant
        self.promotion_grant = (
            self._promotion_grant_override or self._build_promotion_grant(issued)
        )
        grants[PROMOTION_CAPABILITY] = self.promotion_grant
        grants[TASK_CONFIGURATION_CAPABILITY] = self._build_task_configuration_grant(
            issued
        )
        return grants

    def _task_configuration_runtime(self) -> TaskConfigurationRuntime:
        capability_versions = {
            capability_id: spec.version
            for capability_id, spec in self.sandbox.specs().items()
        }
        capability_versions[TASK_CONFIGURATION_CAPABILITY] = (
            TASK_CONFIGURATION_CAPABILITY_VERSION
        )
        return TaskConfigurationRuntime(
            policy_version=self.policy.policy_version,
            policy_digest=POLICY_KERNEL_V1_DIGEST,
            provider_profile=self.provider_profile,
            grants=dict(self.grants),
            capability_versions=capability_versions,
        )

    @contextmanager
    def selfdev_admission_configuration_lease(
        self,
    ) -> Iterator[tuple[bool, TaskConfigurationRuntime]]:
        """Freeze the existing authoritative Runtime configuration for admission."""
        with self._configuration_lock:
            yield self.provider_configured, self._task_configuration_runtime()

    @contextmanager
    def _selfdev_configuration_write(self) -> Iterator[None]:
        """Lock-aware mutation seam used by bounded admission drift tests."""
        with self._configuration_lock:
            yield

    def _build_task_configuration_grant(
        self,
        now: datetime | None = None,
    ) -> CapabilityGrant:
        issued = now or self._clock()
        return CapabilityGrant(
            grant_id="grant:internal:task.configuration.snapshot",
            principal_id=self.principal.principal_id,
            tenant_id=self.principal.tenant_id,
            workspace_id=self.principal.workspace_id,
            capability_id=TASK_CONFIGURATION_CAPABILITY,
            capability_version="1",
            max_risk_tier=1,
            budget_limit=ResourceBudget(
                max_cost_usd=Decimal("1"),
                max_duration_seconds=300,
                max_provider_tokens=0,
                max_tool_calls=0,
            ),
            status=CapabilityGrantStatus.ACTIVE,
            granted_by="system:composition-root",
            granted_at=issued,
            expires_at=issued + timedelta(days=30),
        )

    def _build_evaluation_grant(
        self,
        now: datetime | None = None,
    ) -> CapabilityGrant:
        issued = now or self._clock()
        return CapabilityGrant(
            grant_id="grant:internal:domain.candidate.evaluate",
            principal_id=self.principal.principal_id,
            tenant_id=self.principal.tenant_id,
            workspace_id=self.principal.workspace_id,
            capability_id=EVALUATION_CAPABILITY,
            capability_version="1",
            max_risk_tier=1,
            budget_limit=ResourceBudget(
                max_cost_usd=Decimal("1"),
                max_duration_seconds=300,
                max_provider_tokens=0,
                max_tool_calls=0,
            ),
            status=CapabilityGrantStatus.ACTIVE,
            granted_by="system:composition-root",
            granted_at=issued,
            expires_at=issued + timedelta(days=30),
        )

    def _build_compensation_grant(
        self,
        now: datetime | None = None,
    ) -> CapabilityGrant:
        issued = now or self._clock()
        return CapabilityGrant(
            grant_id="grant:internal:workspace.compensate_patch",
            principal_id=self.principal.principal_id,
            tenant_id=self.principal.tenant_id,
            workspace_id=self.principal.workspace_id,
            capability_id="workspace.compensate_patch",
            capability_version="1",
            max_risk_tier=1,
            budget_limit=ResourceBudget(
                max_cost_usd=Decimal("10"),
                max_duration_seconds=3600,
                max_provider_tokens=0,
                max_tool_calls=100,
            ),
            status=CapabilityGrantStatus.ACTIVE,
            granted_by="system:coordinator",
            granted_at=issued,
            expires_at=issued + timedelta(days=30),
        )

    def _build_promotion_grant(
        self,
        now: datetime | None = None,
    ) -> CapabilityGrant:
        issued = now or self._clock()
        return CapabilityGrant(
            grant_id="grant:internal:domain.candidate.promote",
            principal_id=self.principal.principal_id,
            tenant_id=self.principal.tenant_id,
            workspace_id=self.principal.workspace_id,
            capability_id=PROMOTION_CAPABILITY,
            capability_version="1",
            max_risk_tier=1,
            budget_limit=ResourceBudget(
                max_cost_usd=Decimal("1"),
                max_duration_seconds=300,
                max_provider_tokens=0,
                max_tool_calls=0,
            ),
            status=CapabilityGrantStatus.ACTIVE,
            granted_by="system:composition-root",
            granted_at=issued,
            expires_at=issued + timedelta(days=30),
        )

    def list_tasks(self) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for task_id in self.store.list_task_ids():
            task = self.tasks.get_task(task_id)
            tasks.append(
                {
                    "task_id": task_id,
                    "status": task.status.value if task.status else None,
                    "statement": task.goal.statement if task.goal else "",
                    "run_status": task.run.status.value if task.run else None,
                    "sequence": task.sequence,
                }
            )
        return tasks

    def workspace_status(self) -> dict[str, Any]:
        root = self.sandbox.root
        entries = sorted(
            path.name for path in root.iterdir() if path.name != ".agent-os-artifacts"
        )[:50]
        return {
            "attached": root.is_dir(),
            "root": str(root),
            "is_git_repository": (root / ".git").exists(),
            "entries": entries,
        }

    def attach_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = Path(str(payload.get("path", ""))).expanduser()
        if not raw.is_absolute() or raw.is_symlink():
            raise ValueError("workspace path must be an absolute non-symlink directory")
        root = raw.resolve()
        if not root.is_dir():
            raise FileNotFoundError(str(root))
        allowed_roots = [Path.home().resolve(), Path(tempfile.gettempdir()).resolve()]
        configured = os.environ.get("AGENT_OS_ALLOWED_WORKSPACE_ROOTS")
        if configured:
            allowed_roots = [
                Path(value).expanduser().resolve()
                for value in configured.split(os.pathsep)
                if value
            ]
        if not any(
            root == allowed or allowed in root.parents for allowed in allowed_roots
        ):
            raise PermissionError("workspace path is outside the local allowlist")
        with self._configuration_lock:
            self.sandbox = DeveloperWorkspaceAdapter(
                root,
                idempotency_store=self.store,
                execution_isolation=self.execution_isolation,
            )
            self.tasks.bind_artifact_reader(self.sandbox.read_artifact_bytes)
            rebuilt_grants = self._build_grants()
            self.grants.clear()
            self.grants.update(rebuilt_grants)
        return self.workspace_status()

    @staticmethod
    def _provider_class_for(endpoint_class: str):
        if endpoint_class == "anthropic-messages":
            return AnthropicMessagesProvider
        if endpoint_class == "google-generative":
            return GeminiGenerativeProvider
        return OpenAICompatibleProvider

    @staticmethod
    def _normalize_provider_base_url(value: str | None) -> str | None:
        if value is None:
            return None
        base = value.strip().rstrip("/")
        if not base:
            return None
        for suffix in ("/chat/completions", "/v1/messages"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        gemini_marker = "/v1beta/models/"
        if gemini_marker in base:
            base = base[: base.index(gemini_marker)]
        return base or None

    @classmethod
    def _resolve_live_provider_env(cls) -> tuple[str | None, str, str, str]:
        """Resolve live provider base_url, model, and credential env var name.

        Precedence:
        1. Explicit AGENT_OS_PROVIDER_* overrides
        2. AGENT_OS_PROVIDER_PROFILE=<kimi|openai|anthropic|deepseek>
        3. Legacy OPENAI_API_URL / OPENAI_BASE_URL / OPENAI_MODEL / OPENAI_API_KEY
        """
        profile = os.environ.get("AGENT_OS_PROVIDER_PROFILE", "").strip().lower()
        explicit_base = cls._normalize_provider_base_url(
            os.environ.get("AGENT_OS_PROVIDER_BASE_URL")
        )
        explicit_model = (os.environ.get("AGENT_OS_PROVIDER_MODEL") or "").strip()
        explicit_key_env = (
            os.environ.get("AGENT_OS_PROVIDER_API_KEY_ENV") or ""
        ).strip()

        profile_prefix = {
            "kimi": "KIMI",
            "openai": "OPENAI",
            "anthropic": "ANTHROPIC",
            "deepseek": "DEEPSEEK",
            "gemini": "GEMINI",
        }.get(profile)
        profile_endpoint_class = {
            "anthropic": "anthropic-messages",
            "gemini": "google-generative",
        }.get(profile, "openai-compatible" if profile_prefix is not None else None)

        profile_base = None
        profile_model = ""
        profile_key_env = ""
        if profile_prefix is not None:
            profile_base = cls._normalize_provider_base_url(
                os.environ.get(f"{profile_prefix}_BASE_URL")
                or os.environ.get(f"{profile_prefix}_API_URL")
            )
            profile_model = (os.environ.get(f"{profile_prefix}_MODEL") or "").strip()
            profile_key_env = f"{profile_prefix}_API_KEY"
            profile_temp = os.environ.get(f"{profile_prefix}_TEMPERATURE")
            if profile_temp and not os.environ.get("AGENT_OS_PROVIDER_TEMPERATURE"):
                os.environ["AGENT_OS_PROVIDER_TEMPERATURE"] = profile_temp

        legacy_base = cls._normalize_provider_base_url(
            os.environ.get("OPENAI_API_URL") or os.environ.get("OPENAI_BASE_URL")
        )
        legacy_model = (os.environ.get("OPENAI_MODEL") or "").strip()

        live_base_url = explicit_base or profile_base or legacy_base
        live_model = explicit_model or profile_model or legacy_model or "gpt-4o-mini"
        explicit_endpoint_class = (
            os.environ.get("AGENT_OS_PROVIDER_ENDPOINT_CLASS") or ""
        ).strip()
        live_endpoint_class = (
            explicit_endpoint_class
            or profile_endpoint_class
            or "openai-compatible"
        )
        default_key_env = {
            "anthropic-messages": "ANTHROPIC_API_KEY",
            "google-generative": "GEMINI_API_KEY",
        }.get(live_endpoint_class, "OPENAI_API_KEY")
        credential_key = explicit_key_env or profile_key_env or default_key_env
        if live_endpoint_class not in {
            "openai-compatible",
            "anthropic-messages",
            "google-generative",
        }:
            raise ValueError(
                "unsupported endpoint_class: expected openai-compatible, "
                "anthropic-messages or google-generative"
            )
        return live_base_url, live_model, credential_key, live_endpoint_class

    def provider_status(self) -> dict[str, Any]:
        return {
            "configured": self.provider_configured,
            "provider_id": self.provider_profile.provider_id,
            "model_id": self.provider_profile.model_id,
            "model_revision_digest": self.provider_profile.model_revision_digest,
            "endpoint_class": self.provider_profile.endpoint_class,
            "credential_ref_id": self.provider_profile.credential_ref_id,
        }

    def configure_provider(
        self,
        payload: dict[str, Any],
        *,
        verify: bool = True,
        persist: bool = True,
    ) -> dict[str, Any]:
        base_url = str(payload.get("base_url", "")).rstrip("/")
        for suffix in ("/chat/completions", "/v1/messages"):
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)]
        gemini_marker = "/v1beta/models/"
        if gemini_marker in base_url:
            base_url = base_url[: base_url.index(gemini_marker)]
        model = str(payload.get("model", "")).strip()
        endpoint_class = str(
            payload.get("endpoint_class", "openai-compatible")
        ).strip()
        if endpoint_class not in {
            "openai-compatible",
            "anthropic-messages",
            "google-generative",
        }:
            raise ValueError(
                "unsupported endpoint_class: expected openai-compatible, "
                "anthropic-messages or google-generative"
            )
        model_revision_digest = payload.get("model_revision_digest")
        if model_revision_digest is not None and (
            not isinstance(model_revision_digest, str)
            or len(model_revision_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in model_revision_digest
            )
        ):
            raise ValueError("model_revision_digest must be a lowercase SHA-256 digest")
        api_key = payload.get("api_key")
        temperature = float(payload.get("temperature", 1.0))
        raw_max_tokens = payload.get("max_tokens")
        max_tokens = (
            int(raw_max_tokens) if raw_max_tokens not in (None, "") else None
        )
        if max_tokens is not None and max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")
        parsed = urlparse(base_url)
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "localhost",
        }
        if (parsed.scheme != "https" and not local_http) or not parsed.netloc:
            raise ValueError("provider endpoint must use HTTPS or local HTTP")
        if parsed.username or parsed.password:
            raise ValueError("provider endpoint must not embed credentials in the URL")
        if not model or not isinstance(api_key, str) or not api_key:
            raise ValueError("provider model and API key are required")
        now = datetime.now(timezone.utc)
        # A per-attempt managed resolver key: a failed reconfigure can never
        # clobber the credential of the currently-active provider, and the whole
        # set -> smoke -> commit runs under the configuration lock so a
        # concurrent turn never sees an unverified key bound to the old
        # endpoint. The key is env-resident (in-memory) and never persisted.
        resolver_key = f"AGENT_OS_RUNTIME_PROVIDER_KEY_{uuid4().hex}"
        with self._configuration_lock:
            previous_resolver_key = self._active_provider_resolver_key
            os.environ[resolver_key] = api_key
            try:
                credential = CredentialRef(
                    credential_ref_id=f"credential:local:{uuid4()}",
                    owner_principal_id=self.principal.principal_id,
                    tenant_id=self.principal.tenant_id,
                    workspace_id=self.principal.workspace_id,
                    provider_id=endpoint_class,
                    resolver_key=resolver_key,
                    scopes=("chat",),
                    status=CredentialStatus.ACTIVE,
                    created_at=now,
                    expires_at=now + timedelta(days=30),
                )
                profile = ProviderProfile(
                    profile_id=f"provider-profile:{uuid4()}",
                    provider_id=endpoint_class,
                    model_id=model,
                    model_revision_digest=model_revision_digest,
                    endpoint_class=endpoint_class,
                    credential_ref_id=credential.credential_ref_id,
                    capabilities=("chat", "tool-calls"),
                    max_context_tokens=16_000,
                    request_timeout_seconds=60,
                    created_at=now,
                )
                provider_class = self._provider_class_for(endpoint_class)
                provider = provider_class(
                    base_url=base_url,
                    model=model,
                    credential=credential,
                    credentials=EnvCredentialBroker(),
                    timeout_seconds=60,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    provider_profile=profile,
                )
                if verify:
                    smoke = provider.complete(
                        ProviderRequest(
                            request_id=f"provider-check:{uuid4()}",
                            task_id="task:provider-check",
                            run_id="run:provider-check",
                            provider_profile_id=profile.profile_id,
                            messages=(
                                ProviderMessage(
                                    role=ProviderMessageRole.USER,
                                    content="Reply with OK.",
                                ),
                            ),
                            timeout_seconds=30,
                            created_at=now,
                        )
                    )
                    if isinstance(smoke, ProviderFailure):
                        raise ConnectionError(
                            f"{smoke.code.value}: {smoke.safe_message}"
                        )
                self.provider = provider
                self.provider_profile = profile
                self.provider_configured = True
                self._active_provider_resolver_key = resolver_key
            except Exception:
                os.environ.pop(resolver_key, None)
                raise
            if (
                previous_resolver_key
                and previous_resolver_key != resolver_key
                and previous_resolver_key.startswith(
                    "AGENT_OS_RUNTIME_PROVIDER_KEY_"
                )
            ):
                os.environ.pop(previous_resolver_key, None)
        # Persist the non-secret config and remember the key in the OS keychain
        # (best effort). The key is never written to provider.json.
        credential_env = (
            str(payload.get("credential_env") or "").strip()
            or DEFAULT_CREDENTIAL_ENV
        )
        if persist:
            try:
                save_provider_config(
                    {
                        "base_url": base_url,
                        "model": model,
                        "endpoint_class": endpoint_class,
                        "credential_env": credential_env,
                        "max_tokens": (
                            str(max_tokens) if max_tokens is not None else ""
                        ),
                    }
                )
                default_credential_store().store(DEFAULT_CREDENTIAL_ENV, api_key)
            except Exception:
                # Persistence is convenience only; the live provider is already
                # committed. Never fail the configure on a store error.
                pass
        return {**self.provider_status(), "connection_test": "PASS"}

    def _try_load_persisted_provider(self) -> None:
        """Best-effort: re-install a previously configured provider at startup.

        Uses the persisted non-secret config plus a key from the OS keychain or
        the environment. If the key is unavailable or the connection test fails,
        the runtime stays on the built-in/env provider path.
        """

        config = load_provider_config()
        if config is None:
            return
        credential_env = config.get("credential_env", DEFAULT_CREDENTIAL_ENV)
        api_key, _source = resolve_provider_key(credential_env)
        if not api_key:
            return
        try:
            self.configure_provider(
                {
                    "base_url": config["base_url"],
                    "model": config["model"],
                    "endpoint_class": config.get(
                        "endpoint_class", "openai-compatible"
                    ),
                    "api_key": api_key,
                    "credential_env": credential_env,
                    **(
                        {"max_tokens": int(config["max_tokens"])}
                        if config.get("max_tokens")
                        else {}
                    ),
                },
                verify=False,
                persist=False,
            )
        except Exception:
            # Persisted config could not be validated (offline/bad key); stay
            # unconfigured rather than failing startup.
            pass

    def create_task(self, payload: dict[str, Any]):
        return self.tasks.create_task(Goal.model_validate(payload))

    def run_data_agent_query(
        self,
        task_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self.data_agent_runtime is None:
            raise ValueError("Data Agent query capability is not configured")
        allowed_fields = {"request_id", "safe_query", "data_product"}
        forbidden_fields = set(payload) - allowed_fields
        if forbidden_fields:
            raise ValueError(
                "Data Agent query accepts only request_id, safe_query, and data_product"
            )
        aggregate = self.tasks.get_task(task_id)
        if aggregate.run is None or aggregate.expected_outcome is None:
            raise ValueError("Data Agent query requires an active committed Task run")
        request = DataAgentRequest.model_validate(
            {
                **payload,
                "principal": self.principal.model_dump(mode="json"),
                "tenant_id": self.principal.tenant_id,
                "workspace_id": self.principal.workspace_id,
                "task_id": task_id,
                "run_id": aggregate.run.run_id,
                "expected_outcome_id": aggregate.expected_outcome.expected_outcome_id,
            }
        )
        return self.data_agent_runtime.execute(request).model_dump(mode="json")

    def propose_data_agent_action(
        self,
        task_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self.data_agent_runtime is None:
            raise ValueError("Data Agent action proposal capability is not configured")
        allowed_fields = {
            "request_id",
            "target_capability_id",
            "payload_json",
            "consequence_preview",
            "alternatives",
            "risk_tier",
        }
        if set(payload) - allowed_fields:
            raise ValueError("Data Agent action proposal contains forbidden fields")
        aggregate = self.tasks.get_task(task_id)
        if aggregate.run is None or aggregate.expected_outcome is None:
            raise ValueError("Data Agent action proposal requires an active Task run")
        request = BusinessActionProposalRequest.model_validate(
            {
                **payload,
                "principal": self.principal.model_dump(mode="json"),
                "tenant_id": self.principal.tenant_id,
                "workspace_id": self.principal.workspace_id,
                "task_id": task_id,
                "run_id": aggregate.run.run_id,
                "expected_outcome_id": aggregate.expected_outcome.expected_outcome_id,
            }
        )
        return self.data_agent_runtime.propose_action(request).model_dump(mode="json")

    def create_mandate_workspace_record(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        command = CreateMandateCommand.model_validate(payload)
        record = self.mandate_workspace.create(command, self.principal, self._clock())
        return record.model_dump(mode="json")

    def get_mandate_workspace_record(self, mandate_id: str) -> dict[str, Any]:
        record = self.mandate_workspace.get(mandate_id, self.principal)
        return record.model_dump(mode="json")

    def list_mandate_workspace_records(self) -> list[dict[str, Any]]:
        return [
            record.model_dump(mode="json")
            for record in self.mandate_workspace.list(self.principal)
        ]

    def create_mandate_task_link(
        self,
        mandate_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        command = MandateTaskLinkCommand.model_validate(payload)
        link = self.mandate_responsibility_store.create_link(
            command,
            mandate_id,
            self.principal,
        )
        return link.model_dump(mode="json")

    def list_mandate_task_links(self, mandate_id: str) -> list[dict[str, Any]]:
        return [
            link.model_dump(mode="json")
            for link in self.mandate_responsibility_store.list_links(
                mandate_id,
                self.principal,
            )
        ]

    def revoke_mandate_task_link(
        self,
        mandate_id: str,
        link_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        command = MandateTaskLinkRevocationCommand.model_validate(payload)
        revocation = self.mandate_responsibility_store.revoke_link(
            command,
            mandate_id,
            link_id,
            self.principal,
        )
        return revocation.model_dump(mode="json")

    def mandate_responsibility_view(self, mandate_id: str) -> dict[str, Any]:
        view = self.mandate_responsibility.project(mandate_id, self.principal)
        return view.model_dump(mode="json")

    def create_outcome_portfolio(
        self,
        mandate_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from agent_os_contracts import OutcomePortfolioCreateCommand

        command = OutcomePortfolioCreateCommand.model_validate(payload or {})
        portfolio = self.mandate_outcome_portfolio_store.create_portfolio(
            command,
            mandate_id,
            self.principal,
        )
        return portfolio.model_dump(mode="json")

    def get_outcome_portfolio(self, mandate_id: str) -> dict[str, Any]:
        view = self.mandate_outcome_portfolio_store.get_view(
            mandate_id,
            self.principal,
        )
        return view.model_dump(mode="json")

    def list_outcome_portfolio_help_requests(
        self,
        mandate_id: str,
        *,
        include_resolved: bool = False,
    ) -> list[dict[str, Any]]:
        return [
            record.model_dump(mode="json")
            for record in self.mandate_outcome_portfolio_store.list_help_requests(
                mandate_id,
                self.principal,
                include_resolved=include_resolved,
            )
        ]

    def respond_outcome_portfolio_help_request(
        self,
        mandate_id: str,
        help_request_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from agent_os_contracts import OutcomePortfolioHelpRespondCommand

        command = OutcomePortfolioHelpRespondCommand.model_validate(payload)
        record = self.mandate_outcome_portfolio_store.respond_help_request(
            command,
            mandate_id,
            help_request_id,
            self.principal,
        )
        return record.model_dump(mode="json")

    def attach_persistent_commitment(
        self,
        mandate_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from agent_os_contracts import PersistentCommitmentAttachCommand

        command = PersistentCommitmentAttachCommand.model_validate(payload)
        record = self.mandate_outcome_portfolio_store.attach_commitment(
            command,
            mandate_id,
            self.principal,
        )
        return record.model_dump(mode="json")

    def settle_persistent_commitment(
        self,
        mandate_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from agent_os_contracts import SettlementCommand

        command = SettlementCommand.model_validate(payload)
        record = self.mandate_outcome_portfolio_store.settle(
            command,
            mandate_id,
            self.principal,
        )
        return record.model_dump(mode="json")

    def authorize_mandate_observation_binding(
        self,
        mandate_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self.mandate_observation_authorizations is None:
            raise RuntimeError(
                "Mandate observation authorization requires durable storage"
            )
        command = MandateObservationAuthorizationCommand.model_validate(payload)
        receipt = self.mandate_observation_authorizations.authorize(
            mandate_id,
            command,
            self.principal,
            self._clock(),
        )
        return receipt.model_dump(mode="json")

    def list_mandate_observation_authorizations(
        self,
        mandate_id: str,
    ) -> list[dict[str, Any]]:
        if self.mandate_observation_authorizations is None:
            raise RuntimeError(
                "Mandate observation authorization requires durable storage"
            )
        return [
            receipt.model_dump(mode="json")
            for receipt in self.mandate_observation_authorizations.list(
                mandate_id, self.principal
            )
        ]

    def project_task_trajectory(
        self,
        task_id: str,
        run_id: str,
    ) -> TrajectoryProjection:
        """Project safe, read-only task/run provenance from durable events."""

        projection = TrajectoryProjector().project(self.store, task_id, run_id)
        manifest = projection.manifest
        if (
            manifest.tenant_id != self.principal.tenant_id
            or manifest.workspace_id != self.principal.workspace_id
        ):
            raise PermissionError("trajectory principal scope mismatch")
        return projection

    def observe_data_agent_report(self, trace_id: str) -> TrustedObservationBundle:
        if self._data_agent_situated_runtime is not None:
            return self._data_agent_situated_runtime.observe_report(trace_id)
        if self.data_agent_reports is None:
            raise RuntimeError("Data Agent external report source is not configured")
        return self.data_agent_reports.pull(trace_id)

    def admit_data_agent_event(self, event_id: str) -> EnvironmentEventAdmissionReceipt:
        if self._data_agent_situated_runtime is None:
            raise RuntimeError("Data Agent situated runtime is not configured")
        return self._data_agent_situated_runtime.admit_event(event_id)

    def poll_data_agent_reports_once(
        self,
        *,
        limit: int = 50,
    ) -> DataAgentReportPollResult:
        if self.data_agent_reports is None:
            raise RuntimeError("Data Agent external report source is not configured")
        return self.data_agent_reports.poll_once(limit=limit)

    def run_active_perception_once(
        self,
        *,
        worker_id: str,
    ) -> ActivePerceptionReceipt:
        if self._mandate_active_perception_service is None:
            raise RuntimeError("Mandate active perception is not configured")
        return self._mandate_active_perception_service.run_due_once(worker_id=worker_id)

    def propose_situated_work(
        self,
        event_id: str,
        projection_id: str,
        admission_receipt_id: str,
    ) -> TaskDraftProposal | HelpRequest | None:
        if self._data_agent_situated_runtime is not None:
            if (
                type(admission_receipt_id) is not str
                or not admission_receipt_id.strip()
            ):
                raise SituationalTrustDenied("admission receipt is unavailable")
            return self._data_agent_situated_runtime.propose(
                event_id, projection_id, admission_receipt_id
            )
        if self._mandate_steward is None:
            raise RuntimeError("MandateSteward is not configured")
        return self._mandate_steward.observe_event(
            event_id, projection_id, admission_receipt_id
        )

    def observe_admit_and_propose_data_agent_report(
        self,
        trace_id: str,
    ) -> TaskDraftProposal | HelpRequest | None:
        if self._data_agent_situated_runtime is None:
            raise RuntimeError("Data Agent situated runtime is not configured")
        bundle = self._data_agent_situated_runtime.observe_report(trace_id)
        receipt = self._data_agent_situated_runtime.admit_event(
            bundle.event.environment_event_id
        )
        return self._data_agent_situated_runtime.propose(
            bundle.event.environment_event_id,
            bundle.projection.projection_id,
            receipt.receipt_id,
        )

    def propose_authenticated_protocol_envelope(
        self,
        raw_envelope: dict[str, Any],
        workload_assertion: str,
    ) -> ProtocolIngressReceipt:
        """Public ingress with transport parsing separated from workload authority."""
        if self._data_agent_situated_runtime is None:
            raise RuntimeError("Data Agent situated runtime is not configured")
        return (
            self._data_agent_situated_runtime.propose_authenticated_protocol_envelope(
                raw_envelope,
                workload_assertion,
            )
        )

    def commit_task(self, task_id: str, payload: dict[str, Any]):
        commitment = Commitment.model_validate(payload["commitment"])
        workflow = WorkflowGraph.model_validate(payload["workflow"])
        expected = ExpectedOutcome.model_validate(payload["expected_outcome"])
        return self.tasks.commit_task(task_id, commitment, workflow, expected)

    def validate_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            workflow = WorkflowGraph.model_validate(payload)
        except ValidationError as exc:
            return {
                "valid": False,
                "errors": json.loads(exc.json()),
            }
        return {
            "valid": True,
            "workflow": workflow.model_dump(mode="json"),
            "workflow_digest": workflow.canonical_digest(),
        }

    def seal_task_configuration(
        self,
        task_id: str,
        payload: dict[str, Any],
    ) -> TaskConfigurationSnapshot:
        command = TaskConfigurationSnapshotCommand.model_validate(payload)
        return self.task_configurations.seal(self.principal, task_id, command)

    def register_srl_execution_plan(
        self,
        plan: SrlExecutionPlan,
        *,
        registered_by: str,
    ) -> None:
        """Trusted-organ entry: register the execution contracts for an SRL task.

        This is a composition-root method, not an HTTP/CLI surface, so a caller
        cannot inject an execution plan. Hardening (N6): registration is bound to
        an explicit registrant and validated against the live task before it is
        accepted — the task must exist and still be DRAFT, and the plan must bind
        coherently to it (tenant/workspace/goal/workflow/expected outcome). A
        duplicate registration for the same task is refused (no silent overwrite).
        """

        if not registered_by:
            raise SrlExecutionPlanRegistrationError(
                PlanRegistrationDenialReason.MISSING_REGISTRANT
            )
        try:
            aggregate = self.tasks.get_task(plan.task_id)
        except Exception as exc:
            raise SrlExecutionPlanRegistrationError(
                PlanRegistrationDenialReason.TASK_UNAVAILABLE, type(exc).__name__
            ) from exc
        if aggregate.status is not TaskStatus.DRAFT:
            raise SrlExecutionPlanRegistrationError(
                PlanRegistrationDenialReason.TASK_NOT_DRAFT
            )
        if not plan_binds(aggregate, plan, self.principal):
            raise SrlExecutionPlanRegistrationError(
                PlanRegistrationDenialReason.BINDING_MISMATCH
            )
        self.srl_execution_plans.register(plan, registered_by=registered_by)

    def commit_and_start_srl_task(
        self,
        task_id: str,
        *,
        snapshot_command: TaskConfigurationSnapshotCommand | None = None,
    ) -> SrlExecutionResult:
        """Commit and C7-guarded-start an activated SRL task via the trusted plan."""

        return self.srl_execution.commit_and_start(
            task_id, snapshot_command=snapshot_command
        )

    def get_task_configuration(
        self,
        task_id: str,
        snapshot_id: str,
    ) -> TaskConfigurationSnapshot:
        return self.task_configurations.get(
            self.principal,
            task_id,
            snapshot_id,
        )

    def list_task_configurations(
        self,
        task_id: str,
    ) -> tuple[TaskConfigurationSnapshot, ...]:
        return self.task_configurations.list_for_task(self.principal, task_id)

    def _install_run_work_lease(self, aggregate) -> None:
        """Install an authoritative work lease for a started run.

        The lease binds the run/task/tenant/workspace/principal and covers the
        workspace root (`file:///ws`) so that single-operator file-level writes
        authorized by the run can dispatch; a conflicting event on any covered
        scope still forces CONFLICT/REPLAN/CANCEL.
        """
        run = aggregate.run
        if run is None:
            return
        now = self._clock()
        principal = self.principal
        from agent_os_contracts import (
            CoordinationAuthorityContext,
            ResourceScope,
            WorkLease,
        )

        workspace_scope = ResourceScope(resource_uri="file:///ws")
        # A new run's lease cursor starts at the fence's current high-water so
        # that replanning after a conflict does not re-block on already-seen
        # events (M1b, closes P2 #3: cursor advances instead of hard-coding 0).
        try:
            snapshot = self.workspace_fence.read_coordination(principal.workspace_id)
            event_cursor = snapshot.batch.through_cursor
        except Exception:
            event_cursor = 0
        lease = WorkLease(
            lease_id=f"lease:{run.run_id}",
            lease_version=1,
            fence_token=1,
            task_id=run.task_id,
            run_id=run.run_id,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            holder_id=principal.principal_id,
            plan_version=1,
            event_cursor=event_cursor,
            scopes=(workspace_scope,),
            authority_context=CoordinationAuthorityContext(
                authorization_id=f"auth:{run.run_id}",
                principal_id=principal.principal_id,
                tenant_id=principal.tenant_id,
                workspace_id=principal.workspace_id,
                authorized_scopes=(workspace_scope,),
                evidence_refs=(run.run_id,),
                issued_at=now,
                expires_at=now + timedelta(hours=24),
            ),
            issued_at=now,
            expires_at=now + timedelta(hours=24),
        )
        self.workspace_fence.install_lease(lease)

    def start_run(
        self,
        task_id: str,
        configuration_snapshot_id: str | None = None,
    ):
        aggregate = self.tasks.get_task(task_id)
        if aggregate.configuration_snapshot is not None:
            if configuration_snapshot_id is None:
                raise TaskConfigurationNotBound(
                    "exact configuration snapshot id is required before Run start"
                )
            aggregate = self.task_configurations.start_run(
                self.principal,
                task_id,
                configuration_snapshot_id,
            )
        elif configuration_snapshot_id is not None:
            raise TaskConfigurationNotBound(
                "configuration snapshot id was supplied for an unsealed Task"
            )
        else:
            with self._configuration_lock:
                aggregate = self.tasks.start_run(
                    task_id,
                    provider_profile_id=self.provider_profile.profile_id,
                )
        self._install_run_work_lease(aggregate)
        return aggregate

    def seal_domain_candidate(
        self,
        task_id: str,
        payload: dict[str, Any],
    ) -> DomainCandidate:
        values = dict(payload)
        supplied_task_id = values.get("task_id")
        if supplied_task_id is not None and supplied_task_id != task_id:
            raise CandidateScopeMismatch("path task does not match candidate task")
        values["task_id"] = task_id
        values.setdefault("tenant_id", self.principal.tenant_id)
        values.setdefault("workspace_id", self.principal.workspace_id)
        values.setdefault("submitted_by", self.principal.principal_id)
        draft = DomainCandidateDraft.model_validate(values)
        return self.domain_candidates.seal(self.principal, draft)

    def list_domain_candidates(
        self,
        task_id: str,
    ) -> tuple[DomainCandidate, ...]:
        return self.domain_candidates.list_for_task(self.principal, task_id)

    def record_domain_candidate_evaluation(
        self,
        candidate_task_id: str,
        candidate_digest: str,
        payload: dict[str, Any],
    ) -> CandidateEvaluationReceipt:
        values = dict(payload)
        supplied_task_id = values.get("candidate_task_id")
        if supplied_task_id is not None and supplied_task_id != candidate_task_id:
            raise CandidateEvaluationScopeMismatch(
                "path candidate task does not match evaluation body"
            )
        supplied_digest = values.get("candidate_digest")
        if supplied_digest is not None and supplied_digest != candidate_digest:
            raise CandidateEvaluationScopeMismatch(
                "path candidate digest does not match evaluation body"
            )
        values["candidate_task_id"] = candidate_task_id
        values["candidate_digest"] = candidate_digest
        values.setdefault("tenant_id", self.principal.tenant_id)
        values.setdefault("workspace_id", self.principal.workspace_id)
        draft = CandidateEvaluationDraft.model_validate(values)
        return self.domain_candidate_evaluations.record(
            self.principal,
            candidate_task_id,
            candidate_digest,
            draft,
        )

    def list_domain_candidate_evaluations(
        self,
        candidate_task_id: str,
        candidate_digest: str,
    ) -> tuple[CandidateEvaluationReceipt, ...]:
        return self.domain_candidate_evaluations.list_for_candidate(
            self.principal,
            candidate_task_id,
            candidate_digest,
        )

    def decide_domain_candidate_promotion(
        self,
        candidate_task_id: str,
        candidate_digest: str,
        payload: dict[str, Any],
    ) -> CandidatePromotionResult:
        values = dict(payload)
        supplied_task_id = values.get("candidate_task_id")
        if supplied_task_id is not None and supplied_task_id != candidate_task_id:
            raise CandidatePromotionScopeMismatch(
                "path candidate task does not match promotion body"
            )
        supplied_digest = values.get("candidate_digest")
        if supplied_digest is not None and supplied_digest != candidate_digest:
            raise CandidatePromotionScopeMismatch(
                "path candidate digest does not match promotion body"
            )
        values["candidate_task_id"] = candidate_task_id
        values["candidate_digest"] = candidate_digest
        values.setdefault("tenant_id", self.principal.tenant_id)
        values.setdefault("workspace_id", self.principal.workspace_id)
        command = CandidatePromotionCommand.model_validate(values)
        return self.domain_candidate_promotions.decide(
            self.principal,
            candidate_task_id,
            candidate_digest,
            command,
        )

    def list_domain_candidate_promotions(
        self,
        candidate_task_id: str,
        candidate_digest: str,
    ) -> tuple[CandidatePromotionDecision, ...]:
        return self.domain_candidate_promotions.list_decisions(
            self.principal,
            candidate_task_id,
            candidate_digest,
        )

    def list_domain_candidate_priors(
        self,
        candidate_task_id: str,
        candidate_digest: str,
    ) -> tuple[DomainPriorArtifact, ...]:
        return self.domain_candidate_promotions.list_priors(
            self.principal,
            candidate_task_id,
            candidate_digest,
        )

    def run_task(
        self,
        task_id: str,
        inputs: dict[str, Any] | None = None,
        *,
        configuration_snapshot_id: str | None = None,
        stop_after_node: str | None = None,
        recover_stale_lease: bool = False,
        execution_fence: Callable[[str], None] | None = None,
        effect_custody: EffectCustodyPort | None = None,
    ):
        forbidden_configuration_inputs = {
            "configuration_snapshot",
            "configuration_snapshot_digest",
            "optional_prior",
            "prior_binding",
            "prior_artifact_id",
            "prior_digest",
            "prior_provenance",
            "promotion_digest",
            "receipt_chain_digest",
            "evaluation_receipt_digests",
            "representation_patch_digest",
            "source_activation_authority",
            "prior_consumption_mode",
        }
        if inputs is not None and forbidden_configuration_inputs.intersection(inputs):
            raise ValueError(
                "configuration and prior content is forbidden in runtime inputs"
            )
        if not self.provider_configured:
            raise ConnectionError(
                "configure and verify a provider before running a task"
            )
        aggregate = self.tasks.get_task(task_id)
        if aggregate.run is None:
            aggregate = self.start_run(task_id, configuration_snapshot_id)
        if aggregate.configuration_snapshot is not None:
            if configuration_snapshot_id is None:
                raise TaskConfigurationNotBound(
                    "exact configuration snapshot id is required before Run execution"
                )
            with self._configuration_lock:
                aggregate = self.task_configurations.assert_runtime_binding(
                    self.principal,
                    task_id,
                    configuration_snapshot_id,
                )
                snapshot = aggregate.configuration_snapshot
                assert snapshot is not None
                runner = RunCoordinator(
                    self.tasks,
                    self.sandbox,
                    self.execution_profile,
                    self.provider,
                    snapshot.provider_profile,
                    self.policy,
                    self.correction,
                    dict(self.grants),
                    compensation_grant=self.compensation_grant,
                    collaboration_preflight=self.collaboration_preflight,
                )
        else:
            if configuration_snapshot_id is not None:
                raise TaskConfigurationNotBound(
                    "configuration snapshot id was supplied for an unsealed Task"
                )
            with self._configuration_lock:
                runner = RunCoordinator(
                    self.tasks,
                    self.sandbox,
                    self.execution_profile,
                    self.provider,
                    self.provider_profile,
                    self.policy,
                    self.correction,
                    dict(self.grants),
                    compensation_grant=self.compensation_grant,
                    collaboration_preflight=self.collaboration_preflight,
                )
        return runner.run(
            task_id,
            self.principal,
            inputs,
            stop_after_node=stop_after_node,
            recover_stale_lease=recover_stale_lease,
            execution_fence=execution_fence,
            effect_custody=effect_custody,
        )

    def open_chat_session(
        self,
        statement: str,
        gateway: ConfirmationGateway,
        *,
        loop_config: AgentLoopConfig | None = None,
    ) -> tuple[ChatSession, AgentLoop]:
        """Open a governed terminal chat session (task + run) and its loop."""
        config = loop_config or _loop_config_with_agents(
            AgentLoopConfig(), self.workspace_root
        )
        return self._open_session_and_loop(
            statement=statement,
            gateway=gateway,
            loop_config=config,
            grants=self._chat_grants(),
            correction=self.correction,
            capability_ids=self.chat_capability_ids,
            permission_mode=None,
        )

    def _open_session_and_loop(
        self,
        *,
        statement: str,
        gateway: ConfirmationGateway,
        loop_config: AgentLoopConfig,
        grants: dict[str, CapabilityGrant],
        correction: Any,
        capability_ids: tuple[str, ...],
        permission_mode: PermissionMode | None,
        child_agent_builder: Callable[[ChatSession], Mapping[str, object]]
        | None = None,
    ) -> tuple[ChatSession, AgentLoop]:
        """The single session-creation path (parent and child sessions).

        A child session differs only in the four things the caller passes: the
        statement, the already-derived (narrowed) grants, the correction port
        (the halt cascade), and the advertised capability set. Everything else -
        task/run/commitment/expected-outcome construction, the durable
        SESSION_OPENED record, the single leading frozen system prompt - is
        identical, so a child cannot acquire session-level state the parent
        path does not have.
        """
        if not self.provider_configured:
            raise ConnectionError(
                "configure and verify a provider before opening a chat session"
            )
        now = self._clock()
        goal_id = f"goal:chat:{uuid4().hex[:12]}"
        task = self.create_task(
            {
                "goal_id": goal_id,
                "tenant_id": self.principal.tenant_id,
                "workspace_id": self.principal.workspace_id,
                "created_by": self.principal.principal_id,
                "created_at": now,
                "statement": statement,
            }
        )
        workflow = WorkflowGraph(
            workflow_id=f"workflow:chat:{task.task_id}",
            version=1,
            tenant_id=self.principal.tenant_id,
            workspace_id=self.principal.workspace_id,
            created_by=self.principal.principal_id,
            created_at=now,
            policy_version=self.policy.policy_version,
            evaluator_refs=("evaluator:pytest:1",),
            nodes=(NodeSpec(node_id="done", kind=NodeKind.TERMINAL),),
            edges=(),
        )
        self.commit_task(
            task.task_id,
            {
                "commitment": {
                    "commitment_id": f"commitment:chat:{task.task_id}",
                    "task_id": task.task_id,
                    "goal_id": goal_id,
                    "tenant_id": self.principal.tenant_id,
                    "workspace_id": self.principal.workspace_id,
                    "accepted_by": self.principal.principal_id,
                    "accepted_at": now,
                    "deliverables": ["interactive chat session outcome"],
                    "acceptance_criteria": ["user request addressed"],
                    "authority_scopes": [
                        "workspace:read",
                        "workspace:write",
                        TASK_CONFIGURATION_CAPABILITY,
                    ],
                    "budget": {
                        "max_cost_usd": "10",
                        "max_duration_seconds": 28800,
                        "max_provider_tokens": 500000,
                        "max_tool_calls": 500,
                    },
                    "risk_tier": 1,
                    "exit_conditions": ["session closed"],
                    "expires_at": now + timedelta(hours=8),
                },
                "workflow": workflow.model_dump(mode="json"),
                "expected_outcome": {
                    "expected_outcome_id": f"expected:chat:{task.task_id}",
                    "task_id": task.task_id,
                    "tenant_id": self.principal.tenant_id,
                    "workspace_id": self.principal.workspace_id,
                    "evaluator_type": "pytest",
                    "evaluator_version": "1",
                    "evidence_requirements": ["test-report"],
                    "failure_semantics": ["non-zero exit"],
                    "threshold": 1,
                    "observation_window_seconds": 28800,
                    "frozen_at": now,
                },
            },
        )
        snapshot = self.seal_task_configuration(task.task_id, {})
        aggregate = self.start_run(task.task_id, snapshot.snapshot_id)
        if (
            aggregate.run is None
            or aggregate.expected_outcome is None
            or aggregate.commitment is None
        ):
            raise RuntimeError("chat session run failed to start")
        session = ChatSession(
            ref=SessionRef(
                session_id=f"session-{uuid4()}",
                task_id=task.task_id,
                run_id=aggregate.run.run_id,
                tenant_id=self.principal.tenant_id,
                workspace_id=self.principal.workspace_id,
            ),
            envelope_id=f"envelope-{uuid4()}",
            expected=aggregate.expected_outcome,
        )
        config = loop_config
        self.tasks.open_session(
            session.ref,
            session.envelope_id,
            session.expected.expected_outcome_id,
            loop_config=SessionLoopConfig(
                max_steps_per_turn=config.max_steps_per_turn,
                max_provider_retries=config.max_provider_retries,
                max_turn_tokens=config.max_turn_tokens,
                max_context_chars=config.max_context_chars,
                loop_detection_threshold=config.loop_detection_threshold,
                system_prompt=config.system_prompt,
            ),
            child_agent=(
                child_agent_builder(session)
                if child_agent_builder is not None
                else None
            ),
        )
        system_message = ProviderMessage(
            role=ProviderMessageRole.SYSTEM,
            content=config.system_prompt,
        )
        self.tasks.record_session_message(
            session.task_id,
            session.session_id,
            0,
            system_message,
            turn_id=None,
        )
        loop = AgentLoop(
            tasks=self.tasks,
            provider=self.provider,
            provider_profile=self.provider_profile,
            policy=self.policy,
            correction=correction,
            connector=self.sandbox,
            grants=grants,
            principal=self.principal,
            gateway=gateway,
            session=session,
            config=config,
            initial_history=(system_message,),
            message_sink=self._record_chat_message,
            runtime_generation=(self._runtime_boot_id, os.getpid()),
            collaboration_preflight=self.collaboration_preflight,
            deny_rules=self.permission_rule_store.list_active(
                tenant_id=self.principal.tenant_id,
                workspace_id=self.principal.workspace_id,
            ),
            capability_ids=capability_ids,
            permission_mode=permission_mode or "ASK",
        )
        self.tasks.append_event(
            task.task_id,
            TaskEventType.CANDIDATES_GENERATED,
            {
                "envelope": {
                    "envelope_id": session.envelope_id,
                    "generator_id": "terminal-chat-loop",
                    "generator_version": "1",
                    "allowed_capability_ids": sorted(capability_ids),
                }
            },
            correlation_id=session.run_id,
        )
        return session, loop

    def restore_chat_session(
        self,
        session_id: str,
        gateway: ConfirmationGateway,
        text_delta_sink: Callable[[str], None] | None = None,
        reasoning_delta_sink: Callable[[str], None] | None = None,
    ) -> tuple[ChatSession, AgentLoop]:
        """Restore one exact durable chat session without replaying prior turns."""
        if not self.provider_configured:
            raise ConnectionError(
                "configure and verify a provider before restoring a chat session"
            )
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        matches: list[str] = []
        for task_id in self.store.list_task_ids():
            for event in self.store.read(task_id):
                if event.event_type is not TaskEventType.SESSION_OPENED:
                    continue
                try:
                    payload = event.decoded_payload()
                except (TypeError, ValueError) as exc:
                    raise SessionProjectionError(
                        "invalid durable session open record"
                    ) from exc
                if payload.get("session_id") == session_id:
                    matches.append(task_id)
        if not matches:
            raise SessionProjectionError("session not found")
        if len(matches) != 1:
            raise SessionProjectionError("duplicate durable session identity")

        projected = SessionProjector(self.store).project(matches[0], session_id)
        if projected.closed:
            raise ValueError("cannot restore a closed chat session")
        if (
            projected.ref.tenant_id != self.principal.tenant_id
            or projected.ref.workspace_id != self.principal.workspace_id
        ):
            raise PermissionError("chat session principal scope mismatch")

        aggregate = self.tasks.get_task(projected.ref.task_id)
        run = aggregate.run
        expected = aggregate.expected_outcome
        snapshot = aggregate.configuration_snapshot
        if (
            run is None
            or expected is None
            or snapshot is None
            or projected.ref.run_id != run.run_id
            or projected.expected_outcome_id != expected.expected_outcome_id
        ):
            raise ValueError("chat session durable scope mismatch")
        if run.status in {RunStatus.SUCCEEDED, RunStatus.CANCELLED}:
            raise ValueError("cannot restore a terminal chat Run")
        self.task_configurations.assert_runtime_binding(
            self.principal,
            aggregate.task_id,
            snapshot.snapshot_id,
        )
        try:
            invocation_profile = self.provider.invocation_binding.provider_profile
        except RuntimeError as exc:
            raise ConnectionError("chat provider binding is unavailable") from exc
        if invocation_profile != self.provider_profile:
            raise ValueError("chat provider profile binding mismatch")
        config = AgentLoopConfig(
            max_steps_per_turn=projected.loop_config.max_steps_per_turn,
            max_provider_retries=projected.loop_config.max_provider_retries,
            max_turn_tokens=projected.loop_config.max_turn_tokens,
            max_context_chars=projected.loop_config.max_context_chars,
            loop_detection_threshold=projected.loop_config.loop_detection_threshold,
            system_prompt=projected.loop_config.system_prompt,
        )
        resumable_turn_ids = (
            (projected.resumable_turn_id,)
            if projected.resumable_turn_id is not None
            else ()
        )

        session = ChatSession(
            ref=projected.ref,
            envelope_id=projected.envelope_id,
            expected=expected,
        )
        loop = AgentLoop(
            tasks=self.tasks,
            provider=self.provider,
            provider_profile=self.provider_profile,
            policy=self.policy,
            correction=self.session_correction(projected.ref.task_id),
            connector=self.sandbox,
            grants=self.session_grants(projected.ref.task_id),
            principal=self.principal,
            gateway=gateway,
            session=session,
            config=config,
            initial_history=projected.history,
            message_sink=self._record_chat_message,
            resumable_turn_ids=resumable_turn_ids,
            runtime_generation=(self._runtime_boot_id, os.getpid()),
            collaboration_preflight=self.collaboration_preflight,
            text_delta_sink=text_delta_sink,
            reasoning_delta_sink=reasoning_delta_sink,
            permission_mode=self.session_permission_mode(
                projected.ref.task_id, projected.permission_mode
            ),
            permission_mode_event_id=projected.permission_mode_event_id,
            deny_rules=self.permission_rule_store.list_active(
                tenant_id=self.principal.tenant_id,
                workspace_id=self.principal.workspace_id,
            ),
            capability_ids=self._session_capability_ids(
                projected.ref.task_id, self._child_agent_link(projected.ref.task_id)
            ),
        )
        return session, loop

    def decide_session_approval(
        self,
        session_id: str,
        action_digest: str,
        disposition: ApprovalDisposition,
        reason: str,
    ) -> TurnResult:
        """Resolve one exact durable approval and continue its open turn."""

        if not action_digest.strip():
            raise ValueError("action_digest must be non-empty")
        if not reason.strip():
            raise ValueError("approval reason must be non-empty")
        if disposition not in {
            ApprovalDisposition.APPROVE,
            ApprovalDisposition.REJECT,
        }:
            raise ValueError("session approval must be APPROVE or REJECT")
        session, loop = self.restore_chat_session(
            session_id,
            DeferredApprovalGateway(),
        )
        projected = self.tasks.project_session(session.task_id, session_id)
        pending = projected.pending_continuation
        if pending is None:
            resolved = projected.resolved_continuation
            if resolved is None:
                raise InvalidTransitionError("session has no pending approval")
            recorded = self.tasks.resolved_session_approval(
                session.task_id,
                resolved,
            )
            if (
                action_digest != resolved.source_action_digest
                or disposition is not recorded.disposition
                or reason != recorded.reason
                or recorded.actor_id != self.principal.principal_id
                or recorded.actor_role is not self.principal.role
            ):
                raise InvalidTransitionError(
                    "approval retry does not match the exact durable decision"
                )
            result = loop.resume_resolved_continuation(
                session,
                action_digest=action_digest,
                disposition=disposition,
            )
            self._record_child_agent_continuation(session, result)
            return result
        if action_digest != pending.action.action_digest():
            raise InvalidTransitionError(
                "approval digest does not match the pending action"
            )
        now = self._clock()
        approval = ApprovalDecision(
            approval_id=f"approval-{uuid4()}",
            tenant_id=pending.action.tenant_id,
            workspace_id=pending.action.workspace_id,
            action_digest=action_digest,
            actor_id=self.principal.principal_id,
            actor_role=self.principal.role,
            disposition=disposition,
            reason=reason,
            decided_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        result = loop.resume_pending_approval(session, approval)
        self._record_child_agent_continuation(session, result)
        return result

    def surface_open_session(
        self, command: SurfaceOpenSessionCommand
    ) -> SurfaceSessionSnapshot:
        session, _ = self.open_chat_session(
            command.statement, DeferredApprovalGateway()
        )
        return self.surface_session_snapshot(session.session_id)

    def surface_run_turn(self, command: SurfaceTurnCommand) -> SurfaceTurnResponse:
        session, loop = self.restore_chat_session(
            command.session_id, DeferredApprovalGateway()
        )
        history_before = len(loop.history)
        ownership = self._claim_surface_turn(command.session_id)
        try:
            result = loop.run_turn(session, command.text)
        except (WorkspaceWriteRejected, ReplanRequired) as exc:
            decision = getattr(exc, "decision", None)
            if decision is not None:
                self._surface_conflicts[command.session_id] = (
                    SurfaceConflictProjection.from_decision(decision)
                )
            raise
        finally:
            self._release_surface_turn(command.session_id, ownership)
        return self._surface_turn_response(
            session.session_id,
            result,
            loop.history[history_before:],
        )

    @property
    def runtime_boot_id(self) -> str:
        """Daemon process generation id; changes on every restart so a dead
        generation's transient cursors fail typed STREAM_GONE."""
        return self._runtime_boot_id

    @property
    def stream_registry(self) -> SessionStreamRegistry:
        """Transient frame registry; dies with the process (a new generation
        carries a new runtime_boot_id)."""
        return self._stream_registry

    def subscribe_stream(self, session_id: str) -> str:
        """Mint a new transient stream for the session (subscription-first,
        frozen): the TUI subscribes before issuing its begin-turn."""
        self.surface_task_for_session(session_id)
        return self.surface.subscribe_stream(session_id)

    def surface_has_uncommitted_turn(self, session_id: str) -> bool:
        """Durable truth: a SESSION_TURN_STARTED without its
        SESSION_TURN_COMPLETED for this session's task."""
        task_id = self.surface_task_for_session(session_id)
        started: set[str] = set()
        completed: set[str] = set()
        for event in self.store.read(task_id):
            if event.event_type not in {
                TaskEventType.SESSION_TURN_STARTED,
                TaskEventType.SESSION_TURN_COMPLETED,
            }:
                continue
            payload = json.loads(event.payload_json)
            turn_id = payload.get("turn_id")
            if not isinstance(turn_id, str) or not turn_id:
                continue
            if event.event_type is TaskEventType.SESSION_TURN_STARTED:
                started.add(turn_id)
            else:
                completed.add(turn_id)
        return bool(started - completed)

    def surface_open_turn_id(self, session_id: str) -> str | None:
        """The session's one open durable turn id, or None.

        Same durable truth as `surface_has_uncommitted_turn`, named so an
        operator notice can bind the exact turn it is talking about.
        """
        task_id = self.surface_task_for_session(session_id)
        started: dict[str, int] = {}
        completed: set[str] = set()
        for event in self.store.read(task_id):
            if event.event_type not in {
                TaskEventType.SESSION_TURN_STARTED,
                TaskEventType.SESSION_TURN_COMPLETED,
            }:
                continue
            payload = json.loads(event.payload_json)
            turn_id = payload.get("turn_id")
            if not isinstance(turn_id, str) or not turn_id:
                continue
            if event.event_type is TaskEventType.SESSION_TURN_STARTED:
                started.setdefault(turn_id, event.sequence)
            else:
                completed.add(turn_id)
        open_turns = sorted(
            (sequence, turn_id)
            for turn_id, sequence in started.items()
            if turn_id not in completed
        )
        return open_turns[-1][1] if open_turns else None

    def _claim_surface_turn(self, session_id: str) -> str:
        """Record that THIS generation owns the session's turn in flight."""
        token = uuid4().hex
        with self._surface_turns_guard:
            self._surface_turns_in_flight[session_id] = token
        return token

    def _release_surface_turn(self, session_id: str, token: str) -> None:
        with self._surface_turns_guard:
            if self._surface_turns_in_flight.get(session_id) == token:
                del self._surface_turns_in_flight[session_id]

    def surface_turn_in_flight(self, session_id: str) -> bool:
        """Whether this runtime generation is executing a turn for the session."""
        with self._surface_turns_guard:
            return session_id in self._surface_turns_in_flight

    def surface_begin_turn(
        self, command: SurfaceBeginTurnCommand
    ) -> SurfaceBeginTurnResponse:
        """E1 reserve/begin-turn: durably record turn-start, return the
        authoritative ids, then execute asynchronously.

        The provider stream runs on a worker thread; this method returns as
        soon as the durable SESSION_TURN_STARTED event is observable. Failures
        raised before turn-start propagate to the caller synchronously; the
        transient stream binding is recorded in the session-stream registry.
        """
        failures: list[BaseException] = []
        turn_holder: list[str] = []
        turn_ready = threading.Event()

        def _publish(kind: SurfaceStreamFrameKind, payload: dict[str, object]) -> None:
            try:
                self._stream_registry.publish(
                    command.session_id,
                    command.stream.stream_id,
                    kind,
                    turn_holder[0] if turn_holder else None,
                    payload,
                )
            except SurfaceStreamGone:
                return  # stream terminated mid-turn; display path only

        def _sink(delta: str) -> None:
            # Chunks only exist after the durable turn-start record; block
            # briefly until the authoritative turn_id is observed.
            if not turn_ready.wait(timeout=5.0) or not turn_holder:
                return
            _publish(SurfaceStreamFrameKind.CHUNK, {"delta": delta})

        def _reasoning_sink(delta: str) -> None:
            # Transient reasoning (display-only, never durable) for providers
            # that expose it; the same turn-start barrier applies.
            if not turn_ready.wait(timeout=5.0) or not turn_holder:
                return
            _publish(SurfaceStreamFrameKind.REASONING, {"delta": delta})

        session, loop = self.restore_chat_session(
            command.session_id,
            DeferredApprovalGateway(),
            text_delta_sink=_sink,
            reasoning_delta_sink=_reasoning_sink,
        )
        # Ownership of this turn for THIS generation, claimed before the worker
        # can start: a dead-turn declaration must never close a turn this
        # process is executing, and the claim must hold for the whole window in
        # which the worker could be running.
        ownership = self._claim_surface_turn(command.session_id)

        def _execute() -> None:
            try:
                loop.run_turn(session, command.text)
            except (WorkspaceWriteRejected, ReplanRequired) as exc:
                decision = getattr(exc, "decision", None)
                if decision is not None:
                    self._surface_conflicts[command.session_id] = (
                        SurfaceConflictProjection.from_decision(decision)
                    )
                failures.append(exc)
            except BaseException as exc:  # surfaced to the caller below
                failures.append(exc)
            finally:
                self._release_surface_turn(command.session_id, ownership)
                # stream_end (transient): the provider stream closed; the
                # durable turn commit remains authoritative. Wait briefly for
                # the authoritative turn_id — a fast provider can finish the
                # whole turn before the caller observes turn-start.
                turn_ready.wait(timeout=5.0)
                if turn_holder:
                    _publish(SurfaceStreamFrameKind.STREAM_END, {})

        # Snapshot the pre-existing turn ids before the worker can append its
        # own SESSION_TURN_STARTED: the worker only appends, so it can win the
        # race against this scan and would otherwise be mistaken for replay.
        task_id = self.surface_task_for_session(command.session_id)
        known = {
            json.loads(event.payload_json)["turn_id"]
            for event in self.store.read(task_id)
            if event.event_type is TaskEventType.SESSION_TURN_STARTED
        }
        worker = threading.Thread(
            target=_execute,
            daemon=True,
            name=f"surface-begin-turn-{command.session_id}",
        )
        worker.start()
        turn_id = self._await_turn_start(
            command.session_id, worker, task_id=task_id, known=known
        )
        if turn_id is None:
            # Release the worker's display-path wait; no turn was started so
            # no stream_end may be published.
            turn_ready.set()
            if failures:
                raise failures[0]
            raise RuntimeError(
                "turn execution finished without a durable turn-start event"
            )
        turn_holder.append(turn_id)
        turn_ready.set()
        return SurfaceBeginTurnResponse(
            turn_id=turn_id, stream_id=command.stream.stream_id
        )

    def _await_turn_start(
        self,
        session_id: str,
        worker: threading.Thread,
        *,
        task_id: str,
        known: set[str],
        timeout: float = 5.0,
    ) -> str | None:
        """Return the new turn's id as soon as its durable turn-start event is
        observable, without waiting for the turn to finish.

        `task_id`/`known` must be captured before the worker starts; otherwise a
        worker that appends its own turn-start event first is read as replay.
        """
        deadline = time.monotonic() + timeout

        def _new_turn_id() -> str | None:
            for event in self.store.read(task_id):
                if event.event_type is not TaskEventType.SESSION_TURN_STARTED:
                    continue
                turn_id = json.loads(event.payload_json).get("turn_id")
                if isinstance(turn_id, str) and turn_id not in known:
                    return turn_id
            return None

        while time.monotonic() < deadline:
            fresh = _new_turn_id()
            if fresh is not None:
                return fresh
            if not worker.is_alive():
                return _new_turn_id()
            time.sleep(0.005)
        return None

    def surface_conflict_projection(
        self, session_id: str
    ) -> SurfaceConflictProjection | None:
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        return self._surface_conflicts.get(session_id)

    def surface_decide_approval(
        self, command: SurfaceApprovalCommand
    ) -> SurfaceTurnResponse:
        _, loop_before = self.restore_chat_session(
            command.session_id, DeferredApprovalGateway()
        )
        history_before = len(loop_before.history)
        result = self.decide_session_approval(
            command.session_id,
            command.action_digest,
            command.disposition,
            command.reason,
        )
        _, loop_after = self.restore_chat_session(
            command.session_id, DeferredApprovalGateway()
        )
        return self._surface_turn_response(
            command.session_id,
            result,
            loop_after.history[history_before:],
        )

    def surface_recover_unknown_turn(
        self, command: SurfaceTurnRecoveryCommand
    ) -> SurfaceTurnRecoveryResponse:
        """Operator declaration that this session's open turn is dead.

        The turn is closed as an unknown outcome (never a success) with a typed,
        durable record naming the turn, its owning runtime generation, the
        generation that closed it, and the operator's reason. This is a
        bookkeeping decision about an outcome that already happened, not an
        approval: nothing here permits a capability, consumes or grants an
        approval, or touches policy, evidence or C7.

        Refused when this generation is still executing the session's turn:
        only a runtime that no longer owns the turn may declare it dead.
        """

        actor = self.principal
        if actor.role not in {PrincipalRole.PRINCIPAL, PrincipalRole.TENANT_ADMIN}:
            raise PermissionError("dead turn recovery requires principal authority")
        if self.surface_turn_in_flight(command.session_id):
            raise SurfaceTurnOwnedByLiveRuntime(
                "this runtime generation is still executing this session's turn; "
                "a live turn is never closed from under itself"
            )
        task_id = self.surface_task_for_session(command.session_id)
        now = self._clock()
        block = self.tasks.close_dead_session_turn(
            task_id,
            command.session_id,
            turn_id=command.turn_id,
            declared_by=actor.principal_id,
            declared_at=now,
            reason=command.reason,
            runtime_boot_id=self._runtime_boot_id,
            runtime_pid=os.getpid(),
        )
        return SurfaceTurnRecoveryResponse(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            snapshot=self.surface_session_snapshot(command.session_id),
            recovery=RecoveredUnknownTurn.model_validate(block),
            notice=dead_turn_recovery_notice(block),
        )

    def surface_pause_session(
        self, command: SurfaceCorrectionCommand
    ) -> SurfaceSessionSnapshot:
        task_id = self.surface_task_for_session(command.session_id)
        self._pause_task_with_conflict_retry(task_id)
        return self.surface_session_snapshot(command.session_id)

    def _pause_task_with_conflict_retry(self, task_id: str) -> None:
        """Pause the Run, absorbing a bounded optimistic-append conflict.

        The in-flight turn this command is stopping appends to the same
        optimistic event stream, so the pause can lose a sequence race against
        the very turn it must stop. Each attempt re-reads durable truth, so a
        retry only re-applies the same idempotent target state; every other
        rejection (already PAUSED, terminal Run, authority) propagates
        unchanged.
        """
        attempts = 5
        for attempt in range(attempts):
            try:
                self.pause_task(task_id)
                return
            except ConcurrentWriteError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.02)

    def surface_resume_session(
        self, command: SurfaceCorrectionCommand
    ) -> SurfaceSessionSnapshot:
        task_id = self.surface_task_for_session(command.session_id)
        self.resume_task(task_id)
        return self.surface_session_snapshot(command.session_id)

    def surface_correct_session(
        self, command: SurfaceCorrectionCommand
    ) -> SurfaceSessionSnapshot:
        task_id = self.surface_task_for_session(command.session_id)
        self.correct_task(task_id, command.reason)
        return self.surface_session_snapshot(command.session_id)

    def surface_set_permission_mode(
        self, command: SurfaceSetPermissionModeCommand
    ) -> SurfaceSessionSnapshot:
        """E2 operator-only mode change, recorded once per change as a durable
        SESSION_PERMISSION_MODE_SET event with a provenance chain (who set it,
        prior event digest)."""
        task_id = self.surface_task_for_session(command.session_id)
        actor = self.principal
        if actor.role not in {PrincipalRole.PRINCIPAL, PrincipalRole.TENANT_ADMIN}:
            raise PermissionError("permission mode requires principal authority")
        prior_digest: str | None = None
        for event in self.store.read(task_id):
            if event.event_type is not TaskEventType.SESSION_PERMISSION_MODE_SET:
                continue
            prior_digest = content_digest(event.decoded_payload())
        self.tasks.append_event(
            task_id,
            TaskEventType.SESSION_PERMISSION_MODE_SET,
            {
                "session_id": command.session_id,
                "mode": command.mode,
                "set_by": actor.principal_id,
                "prior_digest": prior_digest,
            },
        )
        return self.surface_session_snapshot(command.session_id)

    def surface_provider_status(self) -> SurfaceProviderStatus:
        """Redacted live provider configuration (never the credential value)."""

        config = load_provider_config()
        credential_env = (config or {}).get(
            "credential_env", DEFAULT_CREDENTIAL_ENV
        )
        _key, key_source = resolve_provider_key(credential_env)
        persisted = config is not None
        if not self.provider_configured:
            return SurfaceProviderStatus(
                configured=False,
                persisted=persisted,
                key_source=key_source,
            )
        status = self.provider_status()
        provider = self.provider
        base_url = (
            provider.base_url
            if isinstance(provider, OpenAICompatibleProvider)
            else None
        )
        return SurfaceProviderStatus(
            configured=True,
            provider_id=str(status["provider_id"]),
            model_id=str(status["model_id"]),
            endpoint_class=str(status["endpoint_class"]),
            credential_ref_id=str(status["credential_ref_id"]),
            base_url=base_url,
            persisted=persisted,
            key_source=key_source,
        )

    def surface_clear_provider(
        self, command: SurfaceProviderClearCommand
    ) -> SurfaceProviderStatus:
        """Remove the persisted non-secret config + stored key.

        The running process keeps its current provider until restart; the
        provider is simply no longer auto-loaded.
        """

        clear_provider_config()
        try:
            default_credential_store().delete(DEFAULT_CREDENTIAL_ENV)
        except Exception:
            pass
        return self.surface_provider_status()

    def surface_configure_provider(
        self, command: SurfaceProviderConfigureCommand
    ) -> SurfaceProviderStatus:
        """Operator-issued live provider configuration (surface protocol).

        Delegates to the existing ``configure_provider`` connection test. The
        credential is transient (in-memory env resolver, never persisted) and
        this path does not alter any capability's permit/approval or C7.
        """

        self.configure_provider(
            {
                "base_url": command.base_url,
                "model": command.model,
                "api_key": command.api_key,
                "endpoint_class": command.endpoint_class,
                "temperature": command.temperature
                if command.temperature is not None
                else 1.0,
                "max_tokens": command.max_tokens,
            }
        )
        return self.surface_provider_status()

    def surface_session_snapshot(self, session_id: str) -> SurfaceSessionSnapshot:
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        task_id = self.surface_task_for_session(session_id)
        projected = self.tasks.project_session(task_id, session_id)
        aggregate = self.tasks.get_task(task_id)
        run = aggregate.run
        if run is None:
            raise InvalidTransitionError("surface session requires an active Run")
        return SurfaceSessionSnapshot(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            session=projected.ref,
            envelope_id=projected.envelope_id,
            expected_outcome_id=projected.expected_outcome_id,
            status=self._surface_session_status(task_id, run, projected.closed),
            event_sequence=aggregate.sequence,
            message_count=projected.next_message_index,
            pending_approval=projected.pending_approval,
            permission_mode=projected.permission_mode,
            updated_at=self._clock(),
        )

    def _surface_session_status(
        self,
        task_id: str,
        run: Any,
        closed: bool,
    ) -> SurfaceSessionStatus:
        if closed:
            return SurfaceSessionStatus.CLOSED
        if self.correction.halted(task_id, run.run_id, "provider"):
            return SurfaceSessionStatus.CORRECTION_HALTED
        if run.status is RunStatus.WAITING_APPROVAL:
            return SurfaceSessionStatus.WAITING_APPROVAL
        if run.status is RunStatus.PAUSED:
            return SurfaceSessionStatus.PAUSED
        if run.status in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }:
            return SurfaceSessionStatus.CLOSED
        return SurfaceSessionStatus.ACTIVE

    def surface_sessions_listing(
        self, limit: int, cursor: str | None
    ) -> SurfaceSessionListResponse:
        """Read-only session listing: minimal fields, tenant/workspace scoped.

        Uses only existing durable records (`list_task_ids` + `SESSION_OPENED`);
        `updated_at` is the last durable event's `occurred_at` (not wall-clock).
        Unprojectable sessions are omitted (fail-closed), never fabricated.
        """
        entries: list[SurfaceSessionSummary] = []
        seen_sessions: set[str] = set()
        for task_id in self.store.list_task_ids():
            events = tuple(self.store.read(task_id))
            opened: dict[str, Any] | None = None
            for event in events:
                if event.event_type is not TaskEventType.SESSION_OPENED:
                    continue
                try:
                    opened = event.decoded_payload()
                except (TypeError, ValueError):
                    opened = None
                    break
            if not isinstance(opened, dict) or not events:
                continue
            if opened.get("tenant_id") != self.principal.tenant_id:
                continue
            if opened.get("workspace_id") != self.principal.workspace_id:
                continue
            session_id = opened.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                continue
            if session_id in seen_sessions:
                continue
            try:
                projected = self.tasks.project_session(task_id, session_id)
                aggregate = self.tasks.get_task(task_id)
                run = aggregate.run
                if run is None:
                    continue  # no Run -> not a live enumerable session (fail-closed)
                status = self._surface_session_status(task_id, run, projected.closed)
            except Exception:
                continue  # fail-closed: omit rather than fabricate
            seen_sessions.add(session_id)
            entries.append(
                SurfaceSessionSummary(
                    session_id=session_id,
                    task_id=task_id,
                    status=status,
                    permission_mode=projected.permission_mode,
                    message_count=projected.next_message_index,
                    updated_at=events[-1].occurred_at,
                    awaiting_approval=projected.pending_approval is not None,
                )
            )
        entries.sort(key=lambda summary: summary.session_id)
        if cursor is not None:
            entries = [summary for summary in entries if summary.session_id > cursor]
        page = tuple(entries[:limit])
        next_cursor = page[-1].session_id if len(entries) > limit and page else None
        return SurfaceSessionListResponse(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            sessions=page,
            next_cursor=next_cursor,
        )

    def _surface_turn_response(
        self,
        session_id: str,
        result: TurnResult,
        steps: tuple[ProviderMessage, ...],
    ) -> SurfaceTurnResponse:
        return SurfaceTurnResponse(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            snapshot=self.surface_session_snapshot(session_id),
            turn_id=result.turn_id.turn_id,
            text=result.text or f"turn stopped: {result.stop_reason}",
            steps=tuple(steps),
            stop_reason=result.stop_reason,
            total_tokens=result.total_tokens,
        )

    def surface_event_batch(
        self, task_id: str, after_sequence: int
    ) -> SurfaceEventBatch:
        if not task_id.strip():
            raise ValueError("task_id must be non-empty")
        self.tasks.get_task(task_id)
        events = tuple(
            event
            for event in self.store.read(task_id)
            if event.sequence > after_sequence
        )
        next_sequence = events[-1].sequence if events else after_sequence
        return SurfaceEventBatch(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            task_id=task_id,
            after_sequence=after_sequence,
            next_sequence=next_sequence,
            events=events,
        )

    def surface_task_for_session(self, session_id: str) -> str:
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        matches: list[str] = []
        for task_id in self.store.list_task_ids():
            for event in self.store.read(task_id):
                if event.event_type is not TaskEventType.SESSION_OPENED:
                    continue
                try:
                    payload = event.decoded_payload()
                except (TypeError, ValueError) as exc:
                    raise SessionProjectionError(
                        "invalid durable session open record"
                    ) from exc
                if payload.get("session_id") == session_id:
                    matches.append(task_id)
                    break
        if not matches:
            raise SurfaceSessionNotFound(f"session {session_id} not found")
        if len(matches) != 1:
            raise SurfaceSessionNotFound("duplicate durable session identity")
        return matches[0]

    def surface_turn_trace(
        self,
        session_id: str,
        turn_id: str | None = None,
    ) -> TurnTrace:
        """Read-only trace of one governed turn, projected from durable records.

        The whole read path is a pure function over the task's own event stream
        (``agent_os_core.turn_trace.build_turn_trace``): nothing is appended, no
        authority is consulted and no state changes, so asking for a trace can
        never alter what happened. The session resolves to its task through the
        same durable ``SESSION_OPENED`` lookup every other session route uses.
        """

        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        task_id = self.surface_task_for_session(session_id)
        self.tasks.get_task(task_id)
        return build_turn_trace(
            tuple(self.store.read(task_id)),
            session_id=session_id,
            turn_id=turn_id,
            task_id=task_id,
        )

    def surface_task_overview(self, task_id: str) -> dict[str, object]:
        """Closed read-only task projection for the Plan and Tasks panel."""

        if not task_id.strip():
            raise ValueError("task_id must be non-empty")
        aggregate = self.tasks.get_task(task_id)
        run = aggregate.run
        session_id: str | None = None
        for event in self.store.read(task_id):
            if event.event_type is TaskEventType.SESSION_OPENED:
                payload = event.decoded_payload()
                if isinstance(payload, dict) and isinstance(
                    payload.get("session_id"), str
                ):
                    session_id = payload["session_id"]
                break
        receipts = sum(
            event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
            for event in self.store.read(task_id)
        )
        run_status = "NONE"
        run_id = ""
        if run is not None:
            run_status = run.status.value
            run_id = run.run_id
        return {
            "task_id": task_id,
            "task_status": (
                aggregate.status.value if aggregate.status is not None else "NONE"
            ),
            "run_status": run_status,
            "run_id": run_id,
            "expected_outcome_id": (
                aggregate.expected_outcome.expected_outcome_id
                if aggregate.expected_outcome is not None
                else ""
            ),
            "receipt_count": receipts,
            "session_id": session_id or "",
        }

    def surface_files_listing(self, task_id: str) -> list[dict[str, object]]:
        """Bounded read-only workspace listing for the Files panel (Wave 2a).

        Returns path/size/mtime only, depth-bounded, skipping noise and
        artifact directories. No file content is exposed without a task
        capability; task ownership is enforced by get_task.
        """

        if not task_id.strip():
            raise ValueError("task_id must be non-empty")
        self.tasks.get_task(task_id)
        root = self.sandbox.root
        noise = {
            ".git",
            ".venv",
            "node_modules",
            "target",
            ".agent-os-artifacts",
            ".agent_runs",
            ".worktrees",
        }
        entries: list[dict[str, object]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in noise for part in path.relative_to(root).parts):
                continue
            if len(path.relative_to(root).parts) > 3:
                continue
            try:
                stat_result = path.stat()
            except OSError:
                continue
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": stat_result.st_size,
                    "mtime": datetime.fromtimestamp(
                        stat_result.st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
            )
        return entries

    def surface_current_sequence(self, task_id: str) -> int:
        if not task_id.strip():
            raise ValueError("task_id must be non-empty")
        return self.tasks.get_task(task_id).sequence

    def surface_idempotency_record(self, scope: str, key: str) -> dict[str, Any] | None:
        if not scope.strip() or not key.strip():
            raise ValueError("idempotency scope and key must be non-empty")
        return self.store.get_idempotency(scope, key)

    def surface_store_idempotency(
        self, scope: str, key: str, record: dict[str, Any]
    ) -> bool:
        if not scope.strip() or not key.strip():
            raise ValueError("idempotency scope and key must be non-empty")
        return self.store.put_idempotency(
            scope, key, record, datetime.now(timezone.utc).isoformat()
        )

    @property
    def chat_capability_ids(self) -> tuple[str, ...]:
        """The capability ids this composition root advertises to chat loops.

        With child agents off, ``agent.spawn`` is not advertised and not
        granted: a model proposal for it is refused as an out-of-allowlist
        denial with a durable POLICY_VERDICT_RECORDED, never executed.
        """

        return chat_capability_ids(child_agents_enabled=self.child_agents_enabled)

    def _chat_grants(self) -> dict[str, CapabilityGrant]:
        grants = dict(self.grants)
        capability_ids = self.chat_capability_ids
        for capability_id, max_tier in CHAT_GRANT_MAX_RISK_TIERS.items():
            if capability_id not in capability_ids:
                continue
            grant = grants.get(capability_id)
            if grant is None:
                raise RuntimeError(f"chat capability is not granted: {capability_id}")
            if grant.max_risk_tier < max_tier:
                # Elevate only the chat-scoped grant copies; the shared
                # composition-root envelope stays at its declared ceiling.
                grants[capability_id] = grant.model_copy(
                    update={"max_risk_tier": max_tier}
                )
        return {
            capability_id: grants[capability_id]
            for capability_id in capability_ids
        }

    def child_agent_index(self) -> ChildAgentIndex:
        return ChildAgentIndex(self.store)

    def _child_agent_link(self, task_id: str) -> Mapping[str, object] | None:
        return self.child_agent_index().child_link(task_id)

    def session_grants(self, task_id: str) -> dict[str, CapabilityGrant]:
        """The grants a session's loop must run with, durable record first.

        A child session rebuilds its grants from the durable block written at
        spawn time (the derivation output), so the narrowing survives a
        restart. A child session whose block is missing or malformed fails
        closed - it never falls back to the composition root's full chat
        grant set.
        """

        link = self._child_agent_link(task_id)
        if link is None:
            return self._chat_grants()
        raw_grants = link.get("grants")
        if not isinstance(raw_grants, dict) or not raw_grants:
            raise ChildAgentLinkError(
                f"child session task {task_id} has no durable grant block"
            )
        digest = link.get("grant_plan_digest")
        grants: dict[str, CapabilityGrant] = {}
        for capability_id, payload in raw_grants.items():
            if not isinstance(payload, dict):
                raise ChildAgentLinkError(
                    f"child session task {task_id} has a malformed grant block"
                )
            grant = CapabilityGrant.model_validate(payload)
            if (
                grant.principal_id != self.principal.principal_id
                or grant.tenant_id != self.principal.tenant_id
                or grant.workspace_id != self.principal.workspace_id
            ):
                raise ChildAgentLinkError(
                    "durable child grant scope does not match the runtime principal"
                )
            grants[str(capability_id)] = grant
        if digest != grants_digest(
            {cid: grant.model_dump(mode="json") for cid, grant in grants.items()}
        ):
            raise ChildAgentLinkError(
                f"child session task {task_id} grant block digest mismatch"
            )
        return grants

    def _session_capability_ids(
        self, task_id: str, link: Mapping[str, object] | None
    ) -> tuple[str, ...]:
        ids = self.chat_capability_ids
        if link is None:
            return ids
        grants = self.session_grants(task_id)
        return tuple(cid for cid in ids if cid in grants)

    def session_correction(self, task_id: str) -> Any:
        """The correction read port a session's loop must use.

        A child session gets the halt cascade: an operator's correction on the
        parent (or any ancestor) halts the child at the next check, durably and
        across restarts, without the child writing anything.
        """

        if self._child_agent_link(task_id) is None:
            return self.correction
        return ChildAgentHaltCascade(self.correction, self.child_agent_index())

    def session_permission_mode(self, task_id: str, projected: Any) -> PermissionMode:
        """A child session always runs in ASK.

        A child never auto-allows a write on the strength of the parent's
        permission mode: at most, its tier-2 actions park on the operator-visible
        prompt the child session already exposes.
        """

        if self._child_agent_link(task_id) is not None:
            return "ASK"
        return projected

    # ------------------------------------------------------------------
    # Form B: the spawner (composition-root half of agent.spawn)
    # ------------------------------------------------------------------

    def spawn_child_agent(
        self, action: ActionContract, command: ChildAgentSpawnCommand
    ) -> ChildAgentSpawnResult:
        """Create and drive one child session for a governed ``agent.spawn``.

        Called only from the connector's dispatch (inside
        ``CapabilityBroker.invoke``), so the spawn itself is already admitted by
        policy/permit/C7 and this method's own failures surface as typed
        outcomes of that one action.
        """

        if not self.child_agents_enabled:
            raise ChildAgentDisabled(
                "child agents are disabled in this runtime "
                "(AGENT_OS_CHILD_AGENTS)"
            )
        if not self.provider_configured:
            raise ConnectionError(
                "configure and verify a provider before spawning a child agent"
            )
        index = self.child_agent_index()
        parent_session_id = index.session_id_for_task(action.task_id)
        if parent_session_id is None:
            raise ChildAgentNotSpawnable(
                "agent.spawn requires the parent session that owns this task"
            )
        parent_turn_id = index.open_turn_id(action.task_id)
        if parent_turn_id is None:
            raise ChildAgentNotSpawnable(
                "agent.spawn requires an open parent turn; this action is not "
                "inside one"
            )
        if index.child_link(action.task_id) is not None and not (
            self.nested_child_agents_enabled
        ):
            raise ChildAgentNotSpawnable(
                "nested child agents are disabled in this runtime "
                "(AGENT_OS_NESTED_CHILD_AGENTS)"
            )
        self._clock()
        spawn_id = action.action_id
        request = ChildAgentSpawnRequest(
            spawn_id=spawn_id,
            prompt=command.prompt,
            description=command.description,
            agent_type=command.agent_type,
            max_steps=command.max_steps,
            parent_task_id=action.task_id,
            parent_run_id=action.run_id,
            parent_session_id=parent_session_id,
            parent_turn_id=parent_turn_id,
            runtime_boot_id=self._runtime_boot_id,
            runtime_pid=os.getpid(),
        )
        child_grants = self.derive_child_agent_grants(request)
        loop_config = self._child_agent_loop_config(command, request)
        child_session, child_loop = self._open_session_and_loop(
            statement=f"child agent task: {command.description}",
            gateway=DeferredApprovalGateway(),
            loop_config=loop_config,
            grants=child_grants,
            correction=ChildAgentHaltCascade(self.correction, index),
            capability_ids=tuple(
                cid for cid in self.chat_capability_ids if cid in child_grants
            ),
            permission_mode="ASK",
            child_agent_builder=lambda session: _child_agent_block(
                request, session, child_grants
            ),
        )
        self.tasks.record_child_agent_spawned(
            action.task_id,
            ChildAgentSpawned(
                spawn_id=spawn_id,
                parent_session_id=parent_session_id,
                parent_turn_id=parent_turn_id,
                child_session_id=child_session.session_id,
                child_task_id=child_session.task_id,
                agent_type=command.agent_type,
                description=command.description,
                prompt_digest=spawn_prompt_digest(command.prompt),
            ),
            parent_run_id=action.run_id,
        )
        with self._live_child_lock:
            self._live_child_spawns.add(spawn_id)
        try:
            outcome = self._drive_child_turn(
                child_loop, child_session, command.prompt
            )
        finally:
            with self._live_child_lock:
                self._live_child_spawns.discard(spawn_id)
        stop_reason = self._child_stop_reason(child_session.task_id, outcome)
        result = child_agent_spawn_result(
            child_session_id=child_session.session_id,
            child_task_id=child_session.task_id,
            stop_reason=stop_reason,
            text=outcome.text,
            steps=outcome.steps,
            tokens=outcome.total_tokens,
        )
        self.tasks.record_child_agent_finished(
            action.task_id,
            ChildAgentFinished(
                spawn_id=spawn_id,
                status=result.status,
                steps=result.steps,
                tokens=result.tokens,
                stop_reason=result.stop_reason,
                summary_digest=summary_digest(result.text),
            ),
            parent_run_id=action.run_id,
        )
        return result

    def _child_agent_loop_config(
        self, command: ChildAgentSpawnCommand, request: ChildAgentSpawnRequest
    ) -> AgentLoopConfig:
        config = _loop_config_with_agents(AgentLoopConfig(), self.workspace_root)
        if command.max_steps is None:
            return config
        return replace(config, max_steps_per_turn=command.max_steps)

    def _drive_child_turn(
        self, child_loop: AgentLoop, child_session: ChatSession, prompt: str
    ) -> TurnResult:
        """Drive the child's one turn on **this** thread, inside a wall-clock bound.

        Same thread on purpose: the broker's C7 linearization holds the
        correction authority's lock for the duration of an effect, so a child
        run on a worker thread would deadlock against the parent's own
        ``guard_unchanged``. Driving it inline also means the parent's turn
        holds no orphaned worker: the child turn is bounded by the loop's own
        wall-clock deadline (checked at every step boundary) and by
        ``max_steps_per_turn``, and the provider call inside a step is itself
        bounded by the provider's request timeout.

        An exception from the child turn is reported as a failure - never as a
        completion - and an unknown effect keeps its unknown outcome. A turn
        that hits the deadline is reported as ``timeout``: the record says the
        bound was reached, not that the child produced a result.
        """

        deadline = time.monotonic() + child_agent_timeout_seconds(os.environ)
        child_loop.set_wall_clock_deadline(deadline)
        try:
            outcome = child_loop.run_turn(child_session, prompt)
        except BaseException as exc:  # reported as a typed child failure
            return TurnResult(
                turn_id=TurnId(
                    turn_id=f"turn-child-error-{child_session.session_id}",
                    session_id=child_session.session_id,
                ),
                text="",
                steps=0,
                stop_reason=(
                    CHILD_AGENT_STOP_REASON_UNKNOWN
                    if isinstance(exc, CapabilityEffectUnknown)
                    else f"child_error:{type(exc).__name__}"
                ),
                total_tokens=0,
            )
        if outcome.stop_reason == "wall_clock_exceeded":
            return TurnResult(
                turn_id=outcome.turn_id,
                text="",
                steps=outcome.steps,
                stop_reason=CHILD_AGENT_STOP_REASON_WALL_CLOCK,
                total_tokens=outcome.total_tokens,
            )
        return outcome

    def _record_child_agent_continuation(
        self, session: ChatSession, result: TurnResult
    ) -> None:
        """Update the parent's roll-up when an operator finishes a parked child.

        A child that parked (``awaiting_approval``) has a durable finish record
        already, because the spawn call returned. When the operator resolves the
        parked approval and the child's turn really ends, the parent's roll-up
        must say so - otherwise it would keep reporting a stopped child as if it
        were still waiting. The write is append-only and digest-only; a child
        that parks again simply writes another record, and readers take the
        latest.
        """

        link = self._child_agent_link(session.task_id)
        if link is None:
            return
        if result.stop_reason == "approval_required":
            # Still parked: the existing record is the truth.
            return
        parent_task_id = link.get("parent_task_id")
        parent_run_id = link.get("parent_run_id")
        spawn_id = link.get("spawn_id")
        if not all(
            isinstance(value, str) and value
            for value in (parent_task_id, parent_run_id, spawn_id)
        ):
            raise ChildAgentLinkError(
                "durable child link is missing the parent/spawn binding"
            )
        stop_reason = self._child_stop_reason(session.task_id, result)
        status = child_agent_status_for_stop_reason(stop_reason)
        self.tasks.record_child_agent_finished(
            str(parent_task_id),
            ChildAgentFinished(
                spawn_id=str(spawn_id),
                status=status,
                steps=result.steps,
                tokens=result.total_tokens,
                stop_reason=stop_reason,
                summary_digest=summary_digest(result.text),
            ),
            parent_run_id=str(parent_run_id),
        )

    def _child_stop_reason(self, child_task_id: str, outcome: TurnResult) -> str:
        """The durable stop reason, with an honest stop attribution.

        A child that ended because the operator corrected it (or any ancestor)
        is reported with the frozen ``stopped_by_operator`` reason; a child that
        parked on a permission prompt keeps ``awaiting_approval`` so the parent
        turn and the operator both see that the child needs a human.
        """

        if outcome.stop_reason == "correction_halted":
            return STOP_REASON_STOPPED_BY_OPERATOR
        if outcome.stop_reason == "approval_required":
            return CHILD_AGENT_STOP_REASON_AWAITING_APPROVAL
        return outcome.stop_reason

    def derive_child_agent_grants(
        self, request: ChildAgentSpawnRequest
    ) -> dict[str, CapabilityGrant]:
        """Call ``derive_child_grants`` for real and return its output.

        The proposed child grants are the parent's own grants (copied with a
        child-scoped grant id and ``granted_by``) minus the child agent type's
        denied capabilities, and the contract function refuses any widening. The
        ``parent_remaining_budget`` argument is the parent's **static** grant
        ceiling: this repository has no consumption ledger, so nothing here may
        be described as the parent's "remaining" budget.
        """

        parent_grants = self.session_grants(request.parent_task_id)
        nested = self.nested_child_agents_enabled
        explore_allowed = set(EXPLORE_ALLOWED_CAPABILITY_IDS)
        now = self._clock()
        proposed: list[CapabilityGrant] = []
        for capability_id, grant in parent_grants.items():
            if capability_id == AGENT_SPAWN_CAPABILITY_ID and not nested:
                continue
            if (
                request.agent_type is ChildAgentType.EXPLORE
                and capability_id not in explore_allowed
            ):
                continue
            proposed.append(
                grant.model_copy(
                    update={
                        "grant_id": f"grant:child:{request.spawn_id}:{capability_id}",
                        "granted_by": f"agent.spawn:{request.spawn_id}",
                        "granted_at": now,
                    }
                )
            )
        try:
            derived = derive_child_grants(
                parent_grants=tuple(parent_grants.values()),
                proposed_child_grants=tuple(proposed),
                parent_remaining_budget=_static_grant_ceiling(parent_grants),
                agent_type=request.agent_type,
                nested_spawn_enabled=nested,
                task_grants=tuple(parent_grants.values()),
            )
        except ChildAgentContractError as exc:
            raise ChildAgentNotSpawnable(
                f"child agent grant derivation refused the spawn: {exc}"
            ) from exc
        return {grant.capability_id: grant for grant in derived}

    # ------------------------------------------------------------------
    # Attribution, burial and stop propagation
    # ------------------------------------------------------------------

    def surface_child_agents(self, session_id: str) -> SurfaceChildAgentsResponse:
        task_id = self.surface_task_for_session(session_id)
        return self._child_agents_response(session_id, task_id, buried=())

    def surface_reconcile_child_agents(
        self, command: SurfaceChildAgentReconcileCommand
    ) -> SurfaceChildAgentsResponse:
        """Operator-declared burial of children whose runtime generation is gone.

        The owner of this decision is the authenticated operator, exactly as for
        the single-session dead-turn recovery: no component fabricates a child's
        outcome. A child owned by this live runtime generation is never buried
        (the request is refused), and every burial is one durable
        ``CHILD_AGENT_FINISHED`` (status ``failed``, reason
        ``unknown_requires_review``) plus one ``CHILD_AGENT_RECONCILED`` block
        naming the reason code, the declaring operator and this generation.
        """

        actor = self.principal
        if actor.role not in {PrincipalRole.PRINCIPAL, PrincipalRole.TENANT_ADMIN}:
            raise PermissionError("child agent reconciliation requires principal authority")
        reason = command.reason.strip()
        if not reason:
            raise ValueError("child agent reconciliation requires a reason")
        task_id = self.surface_task_for_session(command.session_id)
        index = self.child_agent_index()
        with self._live_child_lock:
            live = tuple(self._live_child_spawns)
        orphans = self._buriable_children(
            index, task_id, in_memory_spawn_ids=live
        )
        if not orphans and index.in_flight_children(task_id):
            raise ChildAgentBurialRefused(
                "every in-flight child of this session is owned by this live "
                "runtime generation; nothing is buried"
            )
        now = self._clock()
        buried: list[ChildAgentBurial] = []
        for orphan in orphans:
            child = orphan.child
            self.tasks.record_child_agent_finished(
                task_id,
                ChildAgentFinished(
                    spawn_id=child.spawn_id,
                    status=ChildAgentStatus.FAILED,
                    steps=0,
                    tokens=0,
                    stop_reason=CHILD_AGENT_STOP_REASON_UNKNOWN,
                    summary_digest=summary_digest(""),
                ),
                parent_run_id=child.parent_run_id,
            )
            burial = ChildAgentBurial(
                spawn_id=child.spawn_id,
                child_session_id=child.child_session_id,
                child_task_id=child.child_task_id,
                reason_code=(
                    CHILD_AGENT_RECONCILE_REASON_RUNTIME_GONE
                    if orphan.spawn_runtime_boot_id != self._runtime_boot_id
                    else CHILD_AGENT_RECONCILE_REASON_SPAWN_ABANDONED
                ),
                outcome=CHILD_AGENT_RECONCILE_OUTCOME,
                declared_by=actor.principal_id,
                declared_at=now,
                runtime_boot_id=self._runtime_boot_id,
                runtime_pid=os.getpid(),
                reason=reason,
                child_open_turn_id=index.open_turn_id(child.child_task_id),
            )
            self.tasks.record_child_agent_reconciled(
                task_id, burial.payload(), parent_run_id=child.parent_run_id
            )
            buried.append(burial)
        return self._child_agents_response(command.session_id, task_id, buried=tuple(buried))

    def _buriable_children(
        self,
        index: ChildAgentIndex,
        task_id: str,
        *,
        in_memory_spawn_ids: Sequence[str],
    ) -> tuple[Any, ...]:
        """In-flight children that no live worker owns and no human is deciding.

        A child parked on its own permission prompt is **not** buriable: its
        session carries a pending approval and only the operator's
        APPROVE/REJECT may resolve that. Every other ownerless in-flight child
        is - a crashed generation's child, or one whose spawn call died without
        writing a finish record inside this generation.
        """

        orphans = orphaned_children(
            index, task_id, in_memory_spawn_ids=in_memory_spawn_ids
        )
        buriable: list[Any] = []
        for orphan in orphans:
            projected = self.tasks.project_session(
                orphan.child.child_task_id, orphan.child.child_session_id
            )
            if projected.pending_approval is not None:
                continue
            buriable.append(orphan)
        return tuple(buriable)

    def stop_child_agent(
        self,
        session_id: str,
        *,
        reason: str,
        stop_reason: str = STOP_REASON_STOPPED_BY_OPERATOR,
    ) -> ChildAgentChild:
        """Stop one in-flight child through the existing C7 correction path.

        This is the *operator's* stop, expressed with the operator's own tool:
        the same task-scope correction ``surface_correct_session`` writes. The
        child's next dispatch is denied by the broker and its loop stops at the
        next step boundary; the durable finish record then says what happened.
        Nothing here approves, widens or clears anything.
        """

        actor = self.principal
        if actor.role not in {PrincipalRole.PRINCIPAL, PrincipalRole.TENANT_ADMIN}:
            raise PermissionError("stopping a child agent requires principal authority")
        index = self.child_agent_index()
        task_id = self.surface_task_for_session(session_id)
        link = index.link_for_child_task(task_id)
        parent_task_id = str(link["parent_task_id"])
        spawn_id = str(link["spawn_id"])
        child = next(
            (
                candidate
                for candidate in index.children(parent_task_id)
                if candidate.spawn_id == spawn_id
            ),
            None,
        )
        if child is None:
            raise ChildAgentLinkError(
                f"child {spawn_id} has no durable spawn record"
            )
        if not index.is_in_flight(child):
            # The child already ended; stopping is idempotent, not a rewrite.
            return child
        epoch = self.correction_admin.correct("task", task_id, reason)
        self.tasks.append_event(
            task_id,
            TaskEventType.CORRECTION_WRITTEN,
            {
                "scope": "TASK",
                "epoch": epoch,
                "halted": True,
                "reason": reason,
                "written_by": actor.principal_id,
            },
        )
        self.tasks.record_child_agent_finished(
            parent_task_id,
            ChildAgentFinished(
                spawn_id=spawn_id,
                status=child_agent_status_for_stop_reason(stop_reason),
                steps=0,
                tokens=0,
                stop_reason=stop_reason,
                summary_digest=summary_digest(""),
            ),
            parent_run_id=child.parent_run_id,
        )
        return child

    def close_session_and_stop_children(self, session_id: str) -> None:
        """Close a session and make sure no child outlives that closure.

        Every in-flight child is stopped first (the operator's own C7
        correction on the child's task, which the broker and the child's loop
        both honour), recorded as ``parent_session_closed``, and its child
        session closed when it has no pending approval. The parent session is
        closed last, so the closure never leaves a running child behind it.
        """

        actor = self.principal
        if actor.role not in {PrincipalRole.PRINCIPAL, PrincipalRole.TENANT_ADMIN}:
            raise PermissionError("closing a session requires principal authority")
        task_id = self.surface_task_for_session(session_id)
        index = self.child_agent_index()
        for child in index.in_flight_children(task_id):
            self.stop_child_agent(
                child.child_session_id,
                reason=f"parent session {session_id} was closed",
                stop_reason=CHILD_AGENT_STOP_REASON_PARENT_CLOSED,
            )
            try:
                self.tasks.close_session(child.child_task_id, child.child_session_id)
            except InvalidTransitionError:
                # A parked approval keeps the child session open on purpose:
                # only a human APPROVE/REJECT may resolve it.
                pass
        self.tasks.close_session(task_id, session_id)

    def _child_agents_response(
        self,
        session_id: str,
        task_id: str,
        *,
        buried: tuple[ChildAgentBurial, ...],
    ) -> SurfaceChildAgentsResponse:
        index = self.child_agent_index()
        by_turn: dict[str, list[ChildAgentChild]] = {}
        for child in index.children(task_id):
            by_turn.setdefault(child.spawned.parent_turn_id, []).append(child)
        open_turn = index.open_turn_id(task_id)
        if open_turn is not None:
            by_turn.setdefault(open_turn, [])
        own_steps: dict[str, tuple[int, int]] = {}
        for event in self.store.read(task_id):
            if event.event_type is not TaskEventType.SESSION_TURN_COMPLETED:
                continue
            payload = event.decoded_payload()
            turn_id = payload.get("turn_id")
            steps = payload.get("steps")
            tokens = payload.get("total_tokens")
            if (
                isinstance(turn_id, str)
                and isinstance(steps, int)
                and isinstance(tokens, int)
            ):
                own_steps[turn_id] = (steps, tokens)
        attribution = tuple(
            index.attribution(
                task_id,
                session_id,
                turn_id,
                parent_own_steps=own_steps.get(turn_id, (0, 0))[0],
                parent_own_tokens=own_steps.get(turn_id, (0, 0))[1],
            )
            for turn_id in sorted(by_turn)
        )
        with self._live_child_lock:
            live = tuple(sorted(self._live_child_spawns))
        orphans = self._buriable_children(
            index, task_id, in_memory_spawn_ids=live
        )
        return SurfaceChildAgentsResponse(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            session_id=session_id,
            children_included_in_totals=True,
            turns=attribution,
            orphaned=tuple(
                ChildAgentOrphanProjection(
                    spawn_id=orphan.child.spawn_id,
                    child_session_id=orphan.child.child_session_id,
                    child_task_id=orphan.child.child_task_id,
                    description=orphan.child.spawned.description,
                    agent_type=orphan.child.spawned.agent_type,
                    spawn_runtime_boot_id=orphan.spawn_runtime_boot_id,
                    spawned_by_current_generation=(
                        orphan.spawn_runtime_boot_id == self._runtime_boot_id
                    ),
                )
                for orphan in orphans
            ),
            buried=tuple(
                ChildAgentBurialRecord.model_validate(record.payload())
                for record in buried
            ),
        )

    def _record_chat_message(
        self,
        session: ChatSession,
        message_index: int,
        message: ProviderMessage,
        turn_id: str | None,
    ) -> None:
        self.tasks.record_session_message(
            session.task_id,
            session.session_id,
            message_index,
            message,
            turn_id=turn_id,
        )

    def pause_task(self, task_id: str):
        return self.tasks.update_run_status(
            task_id, RunStatus.PAUSED, event_type=TaskEventType.RUN_PAUSED
        )

    def resume_task(self, task_id: str):
        return self.tasks.update_run_status(
            task_id, RunStatus.RUNNING, event_type=TaskEventType.RUN_RESUMED
        )

    def cancel_task(self, task_id: str):
        return self.tasks.update_run_status(
            task_id, RunStatus.CANCELLED, event_type=TaskEventType.RUN_CANCELLED
        )

    def _validated_correction_command(
        self,
        task_id: str,
        reason: str,
        principal: PrincipalIdentity | None,
    ) -> tuple[PrincipalIdentity, Any, str]:
        actor = principal or self.principal
        if actor.role not in {PrincipalRole.PRINCIPAL, PrincipalRole.TENANT_ADMIN}:
            raise PermissionError("correction requires principal authority")
        task = self.tasks.get_task(task_id)
        if task.run is None or task.commitment is None:
            raise ValueError("correction requires an active committed run")
        if (
            actor.tenant_id != task.commitment.tenant_id
            or actor.workspace_id != task.commitment.workspace_id
        ):
            raise PermissionError("correction scope mismatch")
        if task.run.status in {RunStatus.SUCCEEDED, RunStatus.CANCELLED}:
            raise ValueError("correction is unavailable for a terminal run")
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("correction reason is required")
        return actor, task, normalized_reason

    def correct_task(
        self,
        task_id: str,
        reason: str,
        *,
        principal: PrincipalIdentity | None = None,
    ):
        actor, task, normalized_reason = self._validated_correction_command(
            task_id,
            reason,
            principal,
        )
        epoch = self.correction_admin.correct("task", task_id, normalized_reason)
        self.tasks.append_event(
            task_id,
            TaskEventType.CORRECTION_WRITTEN,
            {
                "scope": "TASK",
                "epoch": epoch,
                "halted": True,
                "reason": normalized_reason,
                "written_by": actor.principal_id,
            },
            correlation_id=task.run.run_id,
        )
        return self.tasks.get_task(task_id)

    def signal_task(self, task_id: str, payload: dict[str, Any]):
        task = self.tasks.get_task(task_id)
        if task.run is None or task.commitment is None:
            raise ValueError("signal requires an active committed run")
        values = dict(payload)
        values.setdefault("task_id", task_id)
        values.setdefault("run_id", task.run.run_id)
        values.setdefault("tenant_id", task.commitment.tenant_id)
        values.setdefault("workspace_id", task.commitment.workspace_id)
        values.setdefault("occurred_at", datetime.now(timezone.utc))
        signal = ExternalSignal.model_validate(values)
        return self.tasks.record_signal(task_id, signal)

    def replan_task(self, task_id: str, payload: dict[str, Any]):
        workflow_payload = payload.get("workflow")
        if not isinstance(workflow_payload, dict):
            raise ValueError("replan requires a workflow object")
        reason = str(payload.get("reason", "")).strip()
        if not reason:
            raise ValueError("replan reason is required")
        workflow = WorkflowGraph.model_validate(workflow_payload)
        aggregate = self.tasks.replan_task(
            task_id,
            workflow,
            requested_by=self.principal.principal_id,
            reason=reason,
        )
        # Explicit replan acknowledges the conflicting events: advance the work
        # lease cursor to the fence high-water so the next dispatch re-evaluates
        # from the acknowledged state instead of silently overriding.
        self._install_run_work_lease(aggregate)
        return aggregate

    def resume_correction(
        self,
        task_id: str,
        reason: str,
        *,
        principal: PrincipalIdentity | None = None,
    ):
        actor, task, normalized_reason = self._validated_correction_command(
            task_id,
            reason,
            principal,
        )
        epoch = self.correction_admin.resume("task", task_id, normalized_reason)
        self.tasks.append_event(
            task_id,
            TaskEventType.CORRECTION_WRITTEN,
            {
                "scope": "TASK",
                "epoch": epoch,
                "halted": False,
                "reason": normalized_reason,
                "written_by": actor.principal_id,
            },
            correlation_id=task.run.run_id,
        )
        return self.tasks.get_task(task_id)

    def compensate_task(self, task_id: str, *, effect_custody=None):
        runner = RunCoordinator(
            self.tasks,
            self.sandbox,
            self.execution_profile,
            self.provider,
            self.provider_profile,
            self.policy,
            self.correction,
            self.grants,
            compensation_grant=self.compensation_grant,
            collaboration_preflight=self.collaboration_preflight,
        )
        return runner.compensate_task(
            task_id,
            self.principal,
            effect_custody=effect_custody,
        )

    def record_approval(self, task_id: str, payload: dict[str, Any]):
        task = self.tasks.get_task(task_id)
        if task.commitment is None or task.run is None:
            raise ValueError("approval requires an active committed task")
        action = self.tasks.pending_action(task_id)
        if action is None:
            raise ValueError("no pending provider action is available for review")
        expected_action_digest = payload.get("action_digest")
        if (
            expected_action_digest is not None
            and expected_action_digest != action.action_digest()
        ):
            raise ValueError("approval payload does not bind the pending action")
        disposition = ApprovalDisposition(str(payload.get("disposition", "APPROVE")))
        reason = str(
            payload.get("reason", "Reviewed in Agent OS Task Workspace")
        ).strip()
        if not reason:
            raise ValueError("approval reason is required")
        now = datetime.now(timezone.utc)
        approval = ApprovalDecision(
            approval_id=f"approval:{uuid4()}",
            tenant_id=task.commitment.tenant_id,
            workspace_id=task.commitment.workspace_id,
            action_digest=action.action_digest(),
            actor_id=self.principal.principal_id,
            actor_role=self.principal.role,
            disposition=disposition,
            reason=reason,
            decided_at=now,
            expires_at=now + timedelta(minutes=10),
        )
        return self.tasks.record_approval(task_id, approval)

    def read_artifact(self, artifact_id: str) -> bytes:
        if not artifact_id.startswith("artifact:"):
            raise ValueError("invalid artifact id")
        digest = artifact_id.removeprefix("artifact:")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("invalid artifact digest")
        path = self.sandbox.artifacts / digest
        if not path.is_file():
            raise FileNotFoundError(artifact_id)
        return path.read_bytes()

    def evidence_json(self, task_id: str) -> list[dict[str, Any]]:
        return [
            {
                "event_id": event.event_id,
                "sequence": event.sequence,
                "event_type": event.event_type.value,
                "payload": event.decoded_payload(),
            }
            for event in self.store.read(task_id)
            if event.event_type
            in {
                TaskEventType.ACTION_RECEIPT_RECORDED,
                TaskEventType.ARTIFACT_RECORDED,
                TaskEventType.OUTCOME_OBSERVED,
            }
        ]

    def recovery_json(self, task_id: str) -> dict[str, Any]:
        return build_recovery_snapshot(self.store.read(task_id)).model_dump(mode="json")

    def task_json(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get_task(task_id)
        current_outcome = self.tasks.current_outcome(task_id)
        historical_outcome = task.observed_outcome
        evidence_valid = (
            current_outcome is not None
            and current_outcome.status is OutcomeStatus.VERIFIED
            if historical_outcome is not None
            and historical_outcome.status is OutcomeStatus.VERIFIED
            else None
        )
        stale_verified = evidence_valid is False
        current_status = TaskStatus.FAILED if stale_verified else task.status
        current_run = (
            task.run.model_copy(update={"status": RunStatus.FAILED})
            if stale_verified and task.run is not None
            else task.run
        )
        events = self.store.read(task_id)
        proposed_action: dict[str, Any] | None = None
        provider_usage: dict[str, Any] | None = None
        for event in reversed(events):
            payload = event.decoded_payload()
            if (
                proposed_action is None
                and event.event_type is TaskEventType.ACTION_PROPOSED
            ):
                action_payload = payload.get("action")
                if isinstance(action_payload, dict):
                    action = ActionContract.model_validate(action_payload)
                    proposed_action = {
                        **action.model_dump(mode="json"),
                        "arguments": json.loads(action.arguments_json),
                        "action_digest": action.action_digest(),
                    }
            if (
                provider_usage is None
                and event.event_type is TaskEventType.PROVIDER_RESPONDED
            ):
                provider_output = payload.get("provider_output")
                if isinstance(provider_output, dict) and isinstance(
                    provider_output.get("usage"), dict
                ):
                    provider_usage = provider_output["usage"]
            if proposed_action is not None and provider_usage is not None:
                break
        return {
            "task_id": task.task_id,
            "sequence": task.sequence,
            "status": current_status.value if current_status else None,
            "goal": task.goal.model_dump(mode="json") if task.goal else None,
            "commitment": task.commitment.model_dump(mode="json")
            if task.commitment
            else None,
            "workflow": task.workflow.model_dump(mode="json")
            if task.workflow
            else None,
            "run": current_run.model_dump(mode="json") if current_run else None,
            "expected_outcome": task.expected_outcome.model_dump(mode="json")
            if task.expected_outcome
            else None,
            "configuration_snapshot": task.configuration_snapshot.model_dump(
                mode="json"
            )
            if task.configuration_snapshot
            else None,
            "observed_outcome": current_outcome.model_dump(mode="json")
            if current_outcome
            else None,
            "historical_observed_outcome": historical_outcome.model_dump(mode="json")
            if stale_verified and historical_outcome
            else None,
            "outcome_evidence_valid": evidence_valid,
            "approval": task.approval.model_dump(mode="json")
            if task.approval
            else None,
            "proposed_action": proposed_action,
            "provider": {**self.provider_status(), "usage": provider_usage},
            "workspace": self.workspace_status(),
            "artifacts": task.artifacts,
            "events": [
                {
                    **event.model_dump(mode="json"),
                    "payload": event.decoded_payload(),
                }
                for event in events
            ],
            "domain_pack": self.domain_manifest.model_dump(mode="json"),
        }
