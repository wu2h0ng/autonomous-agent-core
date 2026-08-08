from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from agent_os_contracts import (
    CandidateEvaluationReceipt,
    CandidatePromotionDecision,
    CandidatePromotionDisposition,
    CapabilityGrant,
    CapabilityGrantStatus,
    CorrectionEpochVector,
    DomainCandidate,
    DomainPriorArtifact,
    DomainPriorBinding,
    DomainPriorSelector,
    ExpectedOutcome,
    NodeKind,
    PrincipalIdentity,
    PrincipalRole,
    PriorEvaluationSource,
    ProviderProfile,
    TaskConfigurationSnapshot,
    TaskConfigurationSnapshotCommand,
    TaskStatus,
    WorkflowGraph,
    candidate_evaluation_receipt_digest,
    candidate_promotion_decision_digest,
    content_digest,
    domain_candidate_digest,
    domain_prior_artifact_digest,
    domain_prior_provenance_digest,
    task_configuration_grants_digest,
    task_configuration_seal_request_digest,
    task_configuration_snapshot_digest,
)

from .errors import (
    ConcurrentWriteError,
    TaskConfigurationConflict,
    TaskConfigurationDenied,
    TaskConfigurationDrift,
    TaskConfigurationNotBound,
    TaskConfigurationNotFound,
    TaskConfigurationScopeMismatch,
)
from .governance import (
    POLICY_KERNEL_V1_DIGEST,
    CorrectionReadPort,
)
from .materialization_promotion_persistence import candidate_receipt_chain_digest
from .task_aggregate import TaskAggregate
from .task_service import Clock, IdFactory, TaskService


TASK_CONFIGURATION_CAPABILITY = "task.configuration.snapshot"
TASK_CONFIGURATION_CAPABILITY_VERSION = "1"
TASK_CONFIGURATION_SEALER_ID = "system:task-configuration-sealer:v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_id_factory(kind: str) -> str:
    return f"{kind}:{uuid4()}"


class ReentrantConfigurationLock(Protocol):
    def acquire(self) -> bool: ...

    def release(self) -> None: ...


@contextmanager
def _locked(lock: ReentrantConfigurationLock) -> Iterator[None]:
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


class CandidateReader(Protocol):
    def get_by_digest(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> DomainCandidate | None: ...


class CandidateEvaluationReader(Protocol):
    def list_for_candidate(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> tuple[CandidateEvaluationReceipt, ...]: ...


class CandidatePromotionReader(Protocol):
    def list_decisions(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> tuple[CandidatePromotionDecision, ...]: ...

    def list_priors(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> tuple[DomainPriorArtifact, ...]: ...


@dataclass(frozen=True, slots=True)
class TaskConfigurationRuntime:
    policy_version: str
    policy_digest: str
    provider_profile: ProviderProfile
    grants: Mapping[str, CapabilityGrant]
    capability_versions: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _DerivedBindings:
    task_sequence: int
    workflow: WorkflowGraph
    expected_outcome: ExpectedOutcome
    policy_version: str
    policy_digest: str
    provider_profile: ProviderProfile
    execution_grants: tuple[CapabilityGrant, ...]
    seal_grant: CapabilityGrant
    optional_prior: DomainPriorBinding | None


class TaskConfigurationSnapshotService:
    def __init__(
        self,
        tasks: TaskService,
        correction: CorrectionReadPort,
        *,
        configuration_lock: ReentrantConfigurationLock,
        configuration_reader: Callable[[], TaskConfigurationRuntime],
        id_factory: IdFactory = _default_id_factory,
        clock: Clock = _utc_now,
        candidates: CandidateReader | None = None,
        evaluations: CandidateEvaluationReader | None = None,
        promotions: CandidatePromotionReader | None = None,
    ) -> None:
        self._tasks = tasks
        self._correction = correction
        self._configuration_lock = configuration_lock
        self._configuration_reader = configuration_reader
        self._id_factory = id_factory
        self._clock = clock
        self._candidates = candidates
        self._evaluations = evaluations
        self._promotions = promotions

    def seal(
        self,
        principal: PrincipalIdentity,
        task_id: str,
        command: TaskConfigurationSnapshotCommand,
    ) -> TaskConfigurationSnapshot:
        request_digest = task_configuration_seal_request_digest(task_id, command)
        with _locked(self._configuration_lock):
            task = self._tasks.get_task(task_id)
            self._validate_read_scope(task, principal)
            if task.configuration_snapshot is not None:
                return self._replay_or_conflict(
                    task.configuration_snapshot,
                    request_digest,
                )

            now = self._clock()
            reserved_run_id = self._id_factory("run")
            runtime = self._configuration_reader()
            bindings = self._derive_bindings(
                task,
                principal,
                runtime,
                now,
                prior_selector=command.prior_selector,
                reserved_run_id=reserved_run_id,
            )
            if self._correction.halted(
                task_id,
                reserved_run_id,
                TASK_CONFIGURATION_CAPABILITY,
            ):
                raise TaskConfigurationDenied(
                    "configuration sealing is halted by correction authority"
                )
            observed_epochs = self._correction.snapshot(
                task_id,
                reserved_run_id,
                TASK_CONFIGURATION_CAPABILITY,
            )
            with self._correction.guard_unchanged(
                task_id,
                reserved_run_id,
                TASK_CONFIGURATION_CAPABILITY,
                observed_epochs,
            ) as unchanged:
                if not unchanged:
                    raise TaskConfigurationDenied(
                        "correction epoch changed before configuration append"
                    )
                linearization_now = self._clock()
                current_task = self._tasks.get_task(task_id)
                current_runtime = self._configuration_reader()
                current_bindings = self._derive_bindings(
                    current_task,
                    principal,
                    current_runtime,
                    linearization_now,
                    prior_selector=command.prior_selector,
                    reserved_run_id=reserved_run_id,
                )
                if current_bindings != bindings:
                    raise TaskConfigurationDrift(
                        "Product configuration changed before snapshot append"
                    )
                snapshot = self._build_snapshot(
                    current_task,
                    principal,
                    current_bindings,
                    snapshot_id=self._id_factory("task-configuration"),
                    request_digest=request_digest,
                    reserved_run_id=reserved_run_id,
                    observed_epochs=observed_epochs,
                    sealed_at=linearization_now,
                )
                try:
                    sealed_task = self._tasks.seal_configuration_snapshot(
                        task_id,
                        snapshot,
                    )
                except ConcurrentWriteError:
                    winner = self._tasks.get_task(task_id).configuration_snapshot
                    if winner is None:
                        raise TaskConfigurationConflict(
                            "Task changed concurrently before snapshot append"
                        )
                    return self._replay_or_conflict(winner, request_digest)

            sealed = sealed_task.configuration_snapshot
            if sealed is None:
                raise TaskConfigurationDrift(
                    "snapshot append did not project a configuration"
                )
            return sealed

    def get(
        self,
        principal: PrincipalIdentity,
        task_id: str,
        snapshot_id: str,
    ) -> TaskConfigurationSnapshot:
        task = self._tasks.get_task(task_id)
        self._validate_read_scope(task, principal)
        snapshot = task.configuration_snapshot
        if snapshot is None or snapshot.snapshot_id != snapshot_id:
            raise TaskConfigurationNotFound("configuration snapshot was not found")
        return snapshot

    def list_for_task(
        self,
        principal: PrincipalIdentity,
        task_id: str,
    ) -> tuple[TaskConfigurationSnapshot, ...]:
        task = self._tasks.get_task(task_id)
        self._validate_read_scope(task, principal)
        return (
            (task.configuration_snapshot,)
            if task.configuration_snapshot is not None
            else ()
        )

    def start_run(
        self,
        principal: PrincipalIdentity,
        task_id: str,
        snapshot_id: str,
    ) -> TaskAggregate:
        with _locked(self._configuration_lock):
            task = self._tasks.get_task(task_id)
            snapshot = self._require_snapshot(task, principal, snapshot_id)
            self._require_original_correction_epochs(snapshot)
            now = self._clock()
            bindings = self._derive_bindings(
                task,
                principal,
                self._configuration_reader(),
                now,
                prior_selector=self._selector_for_snapshot(snapshot),
                reserved_run_id=snapshot.reserved_run_id,
            )
            self._assert_snapshot_matches_bindings(snapshot, bindings)
            with self._correction.guard_unchanged(
                task_id,
                snapshot.reserved_run_id,
                TASK_CONFIGURATION_CAPABILITY,
                snapshot.observed_correction_epochs,
            ) as unchanged:
                if not unchanged:
                    raise TaskConfigurationDenied(
                        "correction epoch changed before bound Run start"
                    )
                linearization_now = self._clock()
                current_task = self._tasks.get_task(task_id)
                current_snapshot = self._require_snapshot(
                    current_task,
                    principal,
                    snapshot_id,
                )
                current_bindings = self._derive_bindings(
                    current_task,
                    principal,
                    self._configuration_reader(),
                    linearization_now,
                    prior_selector=self._selector_for_snapshot(current_snapshot),
                    reserved_run_id=current_snapshot.reserved_run_id,
                )
                self._assert_snapshot_matches_bindings(
                    current_snapshot,
                    current_bindings,
                )
                try:
                    return self._tasks.start_run(
                        task_id,
                        configuration_snapshot_id=snapshot_id,
                    )
                except ConcurrentWriteError as exc:
                    raise TaskConfigurationConflict(
                        "Task changed concurrently before bound Run start"
                    ) from exc

    def assert_runtime_binding(
        self,
        principal: PrincipalIdentity,
        task_id: str,
        snapshot_id: str,
    ) -> TaskAggregate:
        """Fail closed before coordinator construction or any provider/tool call."""

        with _locked(self._configuration_lock):
            task = self._tasks.get_task(task_id)
            snapshot = self._require_snapshot(task, principal, snapshot_id)
            if (
                task.run is None
                or task.run.configuration_snapshot_id != snapshot.snapshot_id
                or task.run.configuration_snapshot_digest != snapshot.snapshot_digest
                or task.run.run_id != snapshot.reserved_run_id
            ):
                raise TaskConfigurationNotBound(
                    "Run is not bound to the exact configuration snapshot"
                )
            self._require_original_correction_epochs(snapshot)
            bindings = self._derive_bindings(
                task,
                principal,
                self._configuration_reader(),
                self._clock(),
                prior_selector=self._selector_for_snapshot(snapshot),
                reserved_run_id=snapshot.reserved_run_id,
                require_unstarted=False,
            )
            self._assert_snapshot_matches_bindings(snapshot, bindings)
            return task

    def _derive_bindings(
        self,
        task: TaskAggregate,
        principal: PrincipalIdentity,
        runtime: TaskConfigurationRuntime,
        now: datetime,
        *,
        prior_selector: DomainPriorSelector | None,
        reserved_run_id: str,
        require_unstarted: bool = True,
    ) -> _DerivedBindings:
        self._validate_task_and_identity(
            task,
            principal,
            now,
            require_unstarted=require_unstarted,
        )
        assert task.workflow is not None
        assert task.expected_outcome is not None
        seal_grant = self._require_grant(
            runtime.grants,
            TASK_CONFIGURATION_CAPABILITY,
            principal,
            now,
            required_version=TASK_CONFIGURATION_CAPABILITY_VERSION,
        )
        required_capabilities = sorted(
            {
                node.capability
                for node in task.workflow.nodes
                if node.kind is NodeKind.TOOL and node.capability is not None
            }
        )
        execution_grants = tuple(
            self._require_grant(
                runtime.grants,
                capability_id,
                principal,
                now,
                required_version=self._require_capability_version(
                    runtime.capability_versions,
                    capability_id,
                ),
            )
            for capability_id in required_capabilities
        )
        if (
            runtime.policy_version != task.workflow.policy_version
            or runtime.policy_version != "policy-1"
            or runtime.policy_digest != POLICY_KERNEL_V1_DIGEST
        ):
            raise TaskConfigurationDenied(
                "registered Product policy version or digest is unsupported"
            )
        optional_prior = (
            self._resolve_prior(
                principal,
                task.task_id,
                reserved_run_id,
                prior_selector,
            )
            if prior_selector is not None
            else None
        )
        return _DerivedBindings(
            task_sequence=task.sequence,
            workflow=task.workflow,
            expected_outcome=task.expected_outcome,
            policy_version=runtime.policy_version,
            policy_digest=runtime.policy_digest,
            provider_profile=runtime.provider_profile,
            execution_grants=execution_grants,
            seal_grant=seal_grant,
            optional_prior=optional_prior,
        )

    @staticmethod
    def _require_grant(
        grants: Mapping[str, CapabilityGrant],
        capability_id: str,
        principal: PrincipalIdentity,
        now: datetime,
        *,
        required_version: str,
    ) -> CapabilityGrant:
        grant = grants.get(capability_id)
        if grant is None:
            raise TaskConfigurationDenied(
                f"required capability grant is missing: {capability_id}"
            )
        if (
            grant.status is not CapabilityGrantStatus.ACTIVE
            or grant.expires_at <= now
            or grant.capability_id != capability_id
            or grant.capability_version != required_version
            or grant.principal_id != principal.principal_id
            or grant.tenant_id != principal.tenant_id
            or grant.workspace_id != principal.workspace_id
        ):
            raise TaskConfigurationDenied(
                f"required capability grant is inactive, expired, wrong version or "
                f"out of scope: {capability_id}"
            )
        return grant

    @staticmethod
    def _require_capability_version(
        capability_versions: Mapping[str, str],
        capability_id: str,
    ) -> str:
        version = capability_versions.get(capability_id)
        if version is None or not version:
            raise TaskConfigurationDenied(
                f"required capability spec version is missing: {capability_id}"
            )
        return version

    @staticmethod
    def _validate_read_scope(
        task: TaskAggregate,
        principal: PrincipalIdentity,
    ) -> None:
        commitment = task.commitment
        if commitment is None:
            raise TaskConfigurationNotFound(
                "configuration snapshot requires a committed Task"
            )
        if (
            principal.tenant_id != commitment.tenant_id
            or principal.workspace_id != commitment.workspace_id
        ):
            raise TaskConfigurationScopeMismatch(
                "configuration snapshot principal scope mismatch"
            )

    def _validate_task_and_identity(
        self,
        task: TaskAggregate,
        principal: PrincipalIdentity,
        now: datetime,
        *,
        require_unstarted: bool,
    ) -> None:
        self._validate_read_scope(task, principal)
        if require_unstarted:
            if task.status is not TaskStatus.COMMITTED or task.run is not None:
                raise TaskConfigurationDenied(
                    "configuration snapshot requires a committed Task before Run start"
                )
        elif task.run is None or task.configuration_snapshot is None:
            raise TaskConfigurationNotBound(
                "runtime preflight requires a snapshot-bound Run"
            )
        if (
            task.goal is None
            or task.commitment is None
            or task.workflow is None
            or task.expected_outcome is None
        ):
            raise TaskConfigurationDenied("Task is missing committed contracts")
        if task.commitment.expires_at <= now:
            raise TaskConfigurationDenied("Task commitment expired before sealing")
        if principal.role not in {
            PrincipalRole.PRINCIPAL,
            PrincipalRole.TENANT_ADMIN,
        }:
            raise TaskConfigurationDenied(
                "configuration sealing requires principal authority"
            )
        if (
            task.goal.created_by != principal.principal_id
            or task.commitment.accepted_by != principal.principal_id
        ):
            raise TaskConfigurationDenied(
                "configuration Goal creator and Commitment acceptor must be sealer"
            )
        if TASK_CONFIGURATION_CAPABILITY not in task.commitment.authority_scopes:
            raise TaskConfigurationDenied(
                "configuration Commitment lacks required authority scope"
            )

    def _require_snapshot(
        self,
        task: TaskAggregate,
        principal: PrincipalIdentity,
        snapshot_id: str,
    ) -> TaskConfigurationSnapshot:
        self._validate_read_scope(task, principal)
        snapshot = task.configuration_snapshot
        if snapshot is None or snapshot.snapshot_id != snapshot_id:
            raise TaskConfigurationNotFound(
                "exact configuration snapshot was not found"
            )
        if snapshot.principal_id != principal.principal_id:
            raise TaskConfigurationDenied(
                "configuration snapshot principal binding mismatch"
            )
        return snapshot

    def _require_original_correction_epochs(
        self,
        snapshot: TaskConfigurationSnapshot,
    ) -> None:
        current = self._correction.snapshot(
            snapshot.consumer_task_id,
            snapshot.reserved_run_id,
            TASK_CONFIGURATION_CAPABILITY,
        )
        if (
            current != snapshot.observed_correction_epochs
            or self._correction.halted(
                snapshot.consumer_task_id,
                snapshot.reserved_run_id,
                TASK_CONFIGURATION_CAPABILITY,
            )
        ):
            raise TaskConfigurationDenied(
                "configuration correction epochs changed after seal"
            )

    @staticmethod
    def _selector_for_snapshot(
        snapshot: TaskConfigurationSnapshot,
    ) -> DomainPriorSelector | None:
        prior = snapshot.optional_prior
        if prior is None:
            return None
        return DomainPriorSelector(
            candidate_task_id=prior.candidate_task_id,
            candidate_digest=prior.candidate_digest,
            prior_artifact_id=prior.prior_artifact_id,
        )

    @staticmethod
    def _assert_snapshot_matches_bindings(
        snapshot: TaskConfigurationSnapshot,
        bindings: _DerivedBindings,
    ) -> None:
        if (
            snapshot.workflow != bindings.workflow
            or snapshot.workflow_digest != bindings.workflow.canonical_digest()
            or snapshot.policy_version != bindings.policy_version
            or snapshot.policy_digest != bindings.policy_digest
            or snapshot.provider_profile != bindings.provider_profile
            or snapshot.provider_profile_digest
            != content_digest(bindings.provider_profile)
            or snapshot.execution_grants != bindings.execution_grants
            or snapshot.execution_grants_digest
            != task_configuration_grants_digest(bindings.execution_grants)
            or snapshot.expected_outcome != bindings.expected_outcome
            or snapshot.expected_outcome_digest
            != content_digest(bindings.expected_outcome)
            or snapshot.optional_prior != bindings.optional_prior
        ):
            raise TaskConfigurationDrift(
                "Product configuration changed after snapshot seal"
            )

    def _resolve_prior(
        self,
        principal: PrincipalIdentity,
        consumer_task_id: str,
        reserved_run_id: str,
        selector: DomainPriorSelector,
    ) -> DomainPriorBinding:
        if (
            self._candidates is None
            or self._evaluations is None
            or self._promotions is None
        ):
            raise TaskConfigurationNotFound(
                "selected prior was not found in Product adaptation stores"
            )
        candidate = self._candidates.get_by_digest(
            principal.tenant_id,
            principal.workspace_id,
            selector.candidate_digest,
        )
        if (
            candidate is None
            or candidate.draft.task_id != selector.candidate_task_id
            or candidate.candidate_digest != selector.candidate_digest
        ):
            raise TaskConfigurationNotFound(
                "selected prior candidate was not found in route scope"
            )
        self._validate_candidate_bytes(candidate, principal)

        receipts = self._evaluations.list_for_candidate(
            principal.tenant_id,
            principal.workspace_id,
            candidate.candidate_digest,
        )
        self._validate_receipt_chain(candidate, receipts, principal)

        decisions = tuple(
            decision
            for decision in self._promotions.list_decisions(
                principal.tenant_id,
                principal.workspace_id,
                candidate.candidate_digest,
            )
            if decision.prior_artifact_id == selector.prior_artifact_id
        )
        priors = tuple(
            prior
            for prior in self._promotions.list_priors(
                principal.tenant_id,
                principal.workspace_id,
                candidate.candidate_digest,
            )
            if prior.prior_artifact_id == selector.prior_artifact_id
        )
        if len(decisions) != 1 or len(priors) != 1:
            raise TaskConfigurationNotFound(
                "selected prior does not have one immutable promotion lineage"
            )
        decision = decisions[0]
        prior = priors[0]
        selected_receipt_count = len(prior.evaluation_receipt_digests)
        if selected_receipt_count < 1 or len(receipts) < selected_receipt_count:
            raise TaskConfigurationDrift(
                "selected prior evaluation receipt lineage is incomplete"
            )
        selected_receipts = receipts[:selected_receipt_count]
        receipt_digests = tuple(
            receipt.evaluation_digest for receipt in selected_receipts
        )
        chain_digest = candidate_receipt_chain_digest(
            candidate.candidate_digest,
            selected_receipts,
        )
        self._validate_promotion_and_prior(
            candidate,
            selected_receipts,
            receipt_digests,
            chain_digest,
            decision,
            prior,
            principal,
        )
        self._validate_source_separation(
            consumer_task_id,
            reserved_run_id,
            candidate,
            selected_receipts,
            decision,
        )

        patch = candidate.draft.representation_patch
        assert patch is not None
        return DomainPriorBinding(
            prior_artifact_id=prior.prior_artifact_id,
            prior_version=prior.prior_version,
            prior_digest=prior.prior_digest,
            tenant_id=prior.tenant_id,
            workspace_id=prior.workspace_id,
            candidate_id=candidate.candidate_id,
            candidate_task_id=candidate.draft.task_id,
            materialization_run_id=candidate.draft.materialization_run_id,
            candidate_digest=candidate.candidate_digest,
            candidate_payload_digest=candidate.payload_digest,
            promotion_id=decision.promotion_id,
            promotion_task_id=decision.promotion_task_id,
            promotion_run_id=decision.promotion_run_id,
            promotion_digest=decision.promotion_digest,
            evaluation_head_digest=receipt_digests[-1],
            evaluation_receipt_digests=receipt_digests,
            receipt_chain_digest=chain_digest,
            evaluation_sources=tuple(
                PriorEvaluationSource(
                    evaluation_task_id=receipt.draft.evaluation_task_id,
                    evaluation_run_id=receipt.draft.evaluation_run_id,
                    evaluation_digest=receipt.evaluation_digest,
                    evaluator_id=receipt.draft.evaluator.evaluator_id,
                    recorded_by=receipt.recorded_by,
                )
                for receipt in selected_receipts
            ),
            representation_patch_digest=patch.patch_digest(),
            provenance=candidate.draft.provenance,
            provenance_digest=domain_prior_provenance_digest(
                candidate.draft.provenance
            ),
            policy_digest=decision.policy_digest,
        )

    @staticmethod
    def _validate_candidate_bytes(
        candidate: DomainCandidate,
        principal: PrincipalIdentity,
    ) -> None:
        draft = candidate.draft
        if (
            draft.tenant_id != principal.tenant_id
            or draft.workspace_id != principal.workspace_id
        ):
            raise TaskConfigurationScopeMismatch(
                "selected prior candidate scope mismatch"
            )
        if (
            draft.outcome.value != "CANDIDATE"
            or draft.requested_channel.value != "R"
            or draft.representation_patch is None
            or not draft.provenance
        ):
            raise TaskConfigurationDrift(
                "selected prior candidate is not a complete inert R candidate"
            )
        candidate_payload = candidate.model_dump(
            mode="json",
            exclude={"candidate_digest"},
        )
        if candidate.candidate_digest != domain_candidate_digest(candidate_payload):
            raise TaskConfigurationDrift("selected prior candidate digest drift")
        if candidate.payload_digest != content_digest(draft):
            raise TaskConfigurationDrift("selected prior candidate payload drift")
        patch_digest = draft.representation_patch.patch_digest()
        if any(
            item.output_patch_digest != patch_digest for item in draft.provenance
        ):
            raise TaskConfigurationDrift("selected prior provenance patch drift")

    @staticmethod
    def _validate_receipt_chain(
        candidate: DomainCandidate,
        receipts: tuple[CandidateEvaluationReceipt, ...],
        principal: PrincipalIdentity,
    ) -> None:
        if not receipts:
            raise TaskConfigurationDrift(
                "selected prior evaluation receipt chain is missing"
            )
        parent: str | None = None
        source_pairs: set[tuple[str, str]] = set()
        for expected_version, receipt in enumerate(receipts, start=1):
            draft = receipt.draft
            pair = (draft.evaluation_task_id, draft.evaluation_run_id)
            if (
                receipt.evaluation_version != expected_version
                or draft.parent_evaluation_digest != parent
                or draft.candidate_digest != candidate.candidate_digest
                or draft.candidate_task_id != candidate.draft.task_id
                or draft.tenant_id != principal.tenant_id
                or draft.workspace_id != principal.workspace_id
                or pair in source_pairs
            ):
                raise TaskConfigurationDrift(
                    "selected prior evaluation receipt chain is gapped or changed"
                )
            receipt_payload = receipt.model_dump(
                mode="json",
                exclude={"evaluation_digest"},
            )
            if receipt.evaluation_digest != candidate_evaluation_receipt_digest(
                receipt_payload
            ):
                raise TaskConfigurationDrift(
                    "selected prior evaluation receipt digest drift"
                )
            source_pairs.add(pair)
            parent = receipt.evaluation_digest

    @staticmethod
    def _validate_promotion_and_prior(
        candidate: DomainCandidate,
        receipts: tuple[CandidateEvaluationReceipt, ...],
        receipt_digests: tuple[str, ...],
        chain_digest: str,
        decision: CandidatePromotionDecision,
        prior: DomainPriorArtifact,
        principal: PrincipalIdentity,
    ) -> None:
        decision_payload = decision.model_dump(
            mode="json",
            exclude={"promotion_digest"},
        )
        prior_payload = prior.model_dump(mode="json", exclude={"prior_digest"})
        if decision.promotion_digest != candidate_promotion_decision_digest(
            decision_payload
        ):
            raise TaskConfigurationDrift("selected prior promotion digest drift")
        if prior.prior_digest != domain_prior_artifact_digest(prior_payload):
            raise TaskConfigurationDrift("selected prior artifact digest drift")
        if (
            decision.disposition is not CandidatePromotionDisposition.PROMOTE
            or decision.candidate_digest != candidate.candidate_digest
            or decision.candidate_task_id != candidate.draft.task_id
            or decision.tenant_id != principal.tenant_id
            or decision.workspace_id != principal.workspace_id
            or decision.evaluation_head_digest != receipt_digests[-1]
            or decision.evaluation_receipt_digests != receipt_digests
            or decision.receipt_chain_digest != chain_digest
            or decision.prior_artifact_id != prior.prior_artifact_id
        ):
            raise TaskConfigurationDrift(
                "selected prior promotion decision does not bind the full chain"
            )
        patch = candidate.draft.representation_patch
        assert patch is not None
        if (
            prior.state != "INERT"
            or prior.activation_authority != "NONE"
            or prior.tenant_id != principal.tenant_id
            or prior.workspace_id != principal.workspace_id
            or prior.candidate_digest != candidate.candidate_digest
            or prior.candidate_payload_digest != candidate.payload_digest
            or prior.promotion_digest != decision.promotion_digest
            or prior.evaluation_head_digest != receipt_digests[-1]
            or prior.evaluation_receipt_digests != receipt_digests
            or prior.receipt_chain_digest != chain_digest
            or prior.representation_patch != patch
            or prior.provenance != candidate.draft.provenance
            or prior.policy_digest != decision.policy_digest
        ):
            raise TaskConfigurationDrift(
                "selected prior artifact does not bind the immutable source lineage"
            )
        if candidate_receipt_chain_digest(candidate.candidate_digest, receipts) != (
            prior.receipt_chain_digest
        ):
            raise TaskConfigurationDrift("selected prior receipt chain digest drift")

    @staticmethod
    def _validate_source_separation(
        consumer_task_id: str,
        reserved_run_id: str,
        candidate: DomainCandidate,
        receipts: tuple[CandidateEvaluationReceipt, ...],
        decision: CandidatePromotionDecision,
    ) -> None:
        source_task_ids = {
            candidate.draft.task_id,
            decision.promotion_task_id,
            *(receipt.draft.evaluation_task_id for receipt in receipts),
        }
        source_run_ids = {
            candidate.draft.materialization_run_id,
            decision.promotion_run_id,
            *(receipt.draft.evaluation_run_id for receipt in receipts),
        }
        if consumer_task_id in source_task_ids or reserved_run_id in source_run_ids:
            raise TaskConfigurationDenied(
                "consumer Task/Run must differ from every prior source Task/Run"
            )

    @staticmethod
    def _build_snapshot(
        task: TaskAggregate,
        principal: PrincipalIdentity,
        bindings: _DerivedBindings,
        *,
        snapshot_id: str,
        request_digest: str,
        reserved_run_id: str,
        observed_epochs: CorrectionEpochVector,
        sealed_at: datetime,
    ) -> TaskConfigurationSnapshot:
        assert task.commitment is not None
        assert task.workflow is not None
        assert task.expected_outcome is not None
        payload = {
            "snapshot_id": snapshot_id,
            "snapshot_version": 1,
            "seal_request_digest": request_digest,
            "consumer_task_id": task.task_id,
            "reserved_run_id": reserved_run_id,
            "commitment_id": task.commitment.commitment_id,
            "tenant_id": task.commitment.tenant_id,
            "workspace_id": task.commitment.workspace_id,
            "principal_id": principal.principal_id,
            "workflow": task.workflow,
            "workflow_digest": task.workflow.canonical_digest(),
            "policy_version": bindings.policy_version,
            "policy_digest": bindings.policy_digest,
            "provider_profile": bindings.provider_profile,
            "provider_profile_digest": content_digest(bindings.provider_profile),
            "execution_grants": bindings.execution_grants,
            "execution_grants_digest": task_configuration_grants_digest(
                bindings.execution_grants
            ),
            "expected_outcome": task.expected_outcome,
            "expected_outcome_digest": content_digest(task.expected_outcome),
            "observed_correction_epochs": observed_epochs,
            "optional_prior": bindings.optional_prior,
            "sealed_by": TASK_CONFIGURATION_SEALER_ID,
            "sealed_at": sealed_at,
            "state": "SEALED",
            "prior_consumption_mode": "REFERENCE_ONLY",
        }
        return TaskConfigurationSnapshot(
            **payload,
            snapshot_digest=task_configuration_snapshot_digest(payload),
        )

    @staticmethod
    def _replay_or_conflict(
        snapshot: TaskConfigurationSnapshot,
        request_digest: str,
    ) -> TaskConfigurationSnapshot:
        if snapshot.seal_request_digest != request_digest:
            raise TaskConfigurationConflict(
                "configuration snapshot is already sealed for a different request"
            )
        return snapshot
