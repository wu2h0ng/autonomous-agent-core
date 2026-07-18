from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    ApprovalDecision,
    ApprovalDisposition,
    CapabilityGrant,
    CapabilityGrantStatus,
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
    ObservationBindingDescriptor,
    OutcomeStatus,
    PrincipalIdentity,
    PrincipalRole,
    ProviderProfile,
    ProviderFailure,
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
    ProtocolIngressReceipt,
    ResourceBudget,
    RunStatus,
    TaskConfigurationSnapshot,
    TaskConfigurationSnapshotCommand,
    TaskEventType,
    TaskDraftProposal,
    TaskStatus,
    TrajectoryProjection,
    WorkflowGraph,
)
from agent_os_core import (
    CandidateScopeMismatch,
    CandidateEvaluationScopeMismatch,
    CandidatePromotionScopeMismatch,
    Clock,
    CorrectionAuthority,
    DeterministicProvider,
    PolicyKernel,
    MandateSteward,
    RunCoordinator,
    DomainCandidateSealer,
    DomainCandidateEvaluationRecorder,
    DomainCandidatePromotionService,
    EVALUATION_CAPABILITY,
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
    SituationalScopeMismatch,
    SituationalTrustDenied,
    SituationalTrustResolver,
    TaskService,
    WorkspaceSandbox,
    EnvCredentialBroker,
    OpenAICompatibleProvider,
    build_recovery_snapshot,
    PromotionPolicyRegistry,
    PromotionPolicyV1,
    POLICY_KERNEL_V1_DIGEST,
    TASK_CONFIGURATION_CAPABILITY,
    TASK_CONFIGURATION_CAPABILITY_VERSION,
    TaskConfigurationNotBound,
    TaskConfigurationRuntime,
    TaskConfigurationSnapshotService,
)
from agent_os_core.trajectory import TrajectoryProjector
from domain_packs.developer_agent import manifest as developer_agent_manifest

from .data_agent_report_adapter import (
    DataAgentReportAdapter,
    DataAgentReportPollResult,
    TrustedObservationBundle,
)
from .data_agent_situated_bootstrap import DataAgentSituatedRuntime
from .mandate_active_perception import (
    ActivePerceptionReceipt,
    MandateActivePerceptionService,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
        observation_binding_descriptors: tuple[ObservationBindingDescriptor, ...] = (),
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
        self.sandbox = WorkspaceSandbox(workspace, idempotency_store=self.store)
        self.tasks.bind_artifact_reader(self.sandbox.read_artifact_bytes)
        self.correction = CorrectionAuthority(
            self.store,
            tenant_id=self.principal.tenant_id,
            workspace_id=self.principal.workspace_id,
            written_by=self.principal.principal_id,
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
        live_base_url = os.environ.get("AGENT_OS_PROVIDER_BASE_URL")
        live_model = os.environ.get("AGENT_OS_PROVIDER_MODEL", "gpt-4o-mini")
        live_model_revision_digest = os.environ.get(
            "AGENT_OS_PROVIDER_MODEL_REVISION_DIGEST"
        )
        credential_key = os.environ.get(
            "AGENT_OS_PROVIDER_API_KEY_ENV", "OPENAI_API_KEY"
        )
        credential_ref = CredentialRef(
            credential_ref_id="credential:default",
            owner_principal_id=self.principal.principal_id,
            tenant_id=self.principal.tenant_id,
            workspace_id=self.principal.workspace_id,
            provider_id="openai-compatible",
            resolver_key=credential_key,
            scopes=("chat",),
            status=CredentialStatus.ACTIVE,
            created_at=now,
            expires_at=now + timedelta(days=30),
        )
        built_in_profile_created_at = datetime(1970, 1, 1, tzinfo=timezone.utc)
        self.provider_profile = ProviderProfile(
            profile_id="provider-profile:default",
            provider_id="openai-compatible" if live_base_url else "deterministic",
            model_id=live_model if live_base_url else "deterministic-v1",
            model_revision_digest=live_model_revision_digest,
            endpoint_class="openai-compatible" if live_base_url else "test",
            credential_ref_id=credential_ref.credential_ref_id,
            capabilities=("chat",),
            max_context_tokens=16_000,
            request_timeout_seconds=60,
            created_at=built_in_profile_created_at,
        )
        self.provider = (
            OpenAICompatibleProvider(
                base_url=live_base_url,
                model=live_model,
                credential=credential_ref,
                credentials=EnvCredentialBroker(),
                timeout_seconds=60,
                provider_profile=self.provider_profile,
            )
            if live_base_url
            else DeterministicProvider(text="provider proposal accepted")
        )
        self.provider_configured = bool(live_base_url)
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

    def _build_grants(self, now: datetime | None = None) -> dict[str, CapabilityGrant]:
        issued = now or self._clock()
        grants = {
            capability_id: CapabilityGrant(
                grant_id=f"grant:{capability_id}",
                principal_id=self.principal.principal_id,
                tenant_id=self.principal.tenant_id,
                workspace_id=self.principal.workspace_id,
                capability_id=capability_id,
                capability_version="1",
                max_risk_tier=1,
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
            for capability_id in self.sandbox.specs(issued)
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
            policy_version="policy-1",
            policy_digest=POLICY_KERNEL_V1_DIGEST,
            provider_profile=self.provider_profile,
            grants=dict(self.grants),
            capability_versions=capability_versions,
        )

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
            self.sandbox = WorkspaceSandbox(root, idempotency_store=self.store)
            self.tasks.bind_artifact_reader(self.sandbox.read_artifact_bytes)
            rebuilt_grants = self._build_grants()
            self.grants.clear()
            self.grants.update(rebuilt_grants)
        return self.workspace_status()

    def provider_status(self) -> dict[str, Any]:
        return {
            "configured": self.provider_configured,
            "provider_id": self.provider_profile.provider_id,
            "model_id": self.provider_profile.model_id,
            "model_revision_digest": self.provider_profile.model_revision_digest,
            "endpoint_class": self.provider_profile.endpoint_class,
            "credential_ref_id": self.provider_profile.credential_ref_id,
        }

    def configure_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        base_url = str(payload.get("base_url", "")).rstrip("/")
        if base_url.endswith("/chat/completions"):
            base_url = base_url.removesuffix("/chat/completions")
        model = str(payload.get("model", "")).strip()
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
        parsed = urlparse(base_url)
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "localhost",
        }
        if (parsed.scheme != "https" and not local_http) or not parsed.netloc:
            raise ValueError("provider endpoint must use HTTPS or local HTTP")
        if not model or not isinstance(api_key, str) or not api_key:
            raise ValueError("provider model and API key are required")
        resolver_key = "AGENT_OS_RUNTIME_PROVIDER_KEY"
        os.environ[resolver_key] = api_key
        now = datetime.now(timezone.utc)
        credential = CredentialRef(
            credential_ref_id=f"credential:local:{uuid4()}",
            owner_principal_id=self.principal.principal_id,
            tenant_id=self.principal.tenant_id,
            workspace_id=self.principal.workspace_id,
            provider_id="openai-compatible",
            resolver_key=resolver_key,
            scopes=("chat",),
            status=CredentialStatus.ACTIVE,
            created_at=now,
            expires_at=now + timedelta(days=30),
        )
        profile = ProviderProfile(
            profile_id=f"provider-profile:{uuid4()}",
            provider_id="openai-compatible",
            model_id=model,
            model_revision_digest=model_revision_digest,
            endpoint_class="openai-compatible",
            credential_ref_id=credential.credential_ref_id,
            capabilities=("chat", "tool-calls"),
            max_context_tokens=16_000,
            request_timeout_seconds=60,
            created_at=now,
        )
        provider = OpenAICompatibleProvider(
            base_url=base_url,
            model=model,
            credential=credential,
            credentials=EnvCredentialBroker(),
            timeout_seconds=60,
            temperature=temperature,
            provider_profile=profile,
        )
        smoke = provider.complete(
            ProviderRequest(
                request_id=f"provider-check:{uuid4()}",
                task_id="task:provider-check",
                run_id="run:provider-check",
                provider_profile_id=profile.profile_id,
                messages=(
                    ProviderMessage(
                        role=ProviderMessageRole.USER, content="Reply with OK."
                    ),
                ),
                timeout_seconds=30,
                created_at=now,
            )
        )
        if isinstance(smoke, ProviderFailure):
            os.environ.pop(resolver_key, None)
            raise ConnectionError(f"{smoke.code.value}: {smoke.safe_message}")
        with self._configuration_lock:
            self.provider = provider
            self.provider_profile = profile
            self.provider_configured = True
        return {**self.provider_status(), "connection_test": "PASS"}

    def create_task(self, payload: dict[str, Any]):
        return self.tasks.create_task(Goal.model_validate(payload))

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
        workflow = WorkflowGraph.model_validate(payload)
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
            return self.task_configurations.start_run(
                self.principal,
                task_id,
                configuration_snapshot_id,
            )
        if configuration_snapshot_id is not None:
            raise TaskConfigurationNotBound(
                "configuration snapshot id was supplied for an unsealed Task"
            )
        with self._configuration_lock:
            return self.tasks.start_run(
                task_id,
                provider_profile_id=self.provider_profile.profile_id,
            )

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
                    self.provider,
                    snapshot.provider_profile,
                    self.policy,
                    self.correction,
                    dict(self.grants),
                    compensation_grant=self.compensation_grant,
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
                    self.provider,
                    self.provider_profile,
                    self.policy,
                    self.correction,
                    dict(self.grants),
                    compensation_grant=self.compensation_grant,
                )
        return runner.run(
            task_id,
            self.principal,
            inputs,
            stop_after_node=stop_after_node,
            recover_stale_lease=recover_stale_lease,
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
        epoch = self.correction.correct("task", task_id, normalized_reason)
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
        return self.tasks.replan_task(
            task_id,
            workflow,
            requested_by=self.principal.principal_id,
            reason=reason,
        )

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
        epoch = self.correction.resume("task", task_id, normalized_reason)
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

    def compensate_task(self, task_id: str):
        runner = RunCoordinator(
            self.tasks,
            self.sandbox,
            self.provider,
            self.provider_profile,
            self.policy,
            self.correction,
            self.grants,
            compensation_grant=self.compensation_grant,
        )
        return runner.compensate_task(task_id, self.principal)

    def record_approval(self, task_id: str, payload: dict[str, Any]):
        task = self.tasks.get_task(task_id)
        if task.commitment is None or task.run is None:
            raise ValueError("approval requires an active committed task")
        action: ActionContract | None = None
        for event in reversed(self.store.read(task_id)):
            if event.event_type is TaskEventType.RUN_PLAN_REBOUND:
                break
            if event.event_type is not TaskEventType.ACTION_PROPOSED:
                continue
            candidate = event.decoded_payload().get("action")
            if isinstance(candidate, dict):
                action = ActionContract.model_validate(candidate)
                break
        if action is None:
            raise ValueError("no pending provider action is available for review")
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
