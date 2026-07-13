from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    ApprovalDecision,
    ApprovalDisposition,
    CapabilityGrant,
    CapabilityGrantStatus,
    Commitment,
    CredentialRef,
    CredentialStatus,
    ExpectedOutcome,
    ExternalSignal,
    Goal,
    PrincipalIdentity,
    PrincipalRole,
    ProviderProfile,
    ProviderFailure,
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
    ResourceBudget,
    RunStatus,
    TaskEventType,
    WorkflowGraph,
)
from agent_os_core import (
    CorrectionAuthority,
    DeterministicProvider,
    PolicyKernel,
    RunCoordinator,
    SQLiteTaskEventStore,
    TaskService,
    WorkspaceSandbox,
    EnvCredentialBroker,
    OpenAICompatibleProvider,
    build_recovery_snapshot,
)
from domain_packs.developer_agent import manifest as developer_agent_manifest


class AgentOSApplication:
    """Composition root used unchanged by the CLI, HTTP API and tests."""

    def __init__(
        self, *, database: str | Path = ":memory:", workspace: str | Path = "."
    ) -> None:
        self.store = SQLiteTaskEventStore(database)
        self.tasks = TaskService(self.store)
        self.sandbox = WorkspaceSandbox(workspace, idempotency_store=self.store)
        self.correction = CorrectionAuthority(self.store)
        self.policy = PolicyKernel(self.correction)
        now = datetime.now(timezone.utc)
        self.principal = PrincipalIdentity(
            principal_id="user:local",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            role=PrincipalRole.PRINCIPAL,
            authenticated_at=now,
        )
        live_base_url = os.environ.get("AGENT_OS_PROVIDER_BASE_URL")
        live_model = os.environ.get("AGENT_OS_PROVIDER_MODEL", "gpt-4o-mini")
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
        self.provider_profile = ProviderProfile(
            profile_id="provider-profile:default",
            provider_id="openai-compatible" if live_base_url else "deterministic",
            model_id=live_model if live_base_url else "deterministic-v1",
            endpoint_class="openai-compatible" if live_base_url else "test",
            credential_ref_id=credential_ref.credential_ref_id,
            capabilities=("chat",),
            max_context_tokens=16_000,
            request_timeout_seconds=60,
            created_at=now,
        )
        self.provider = (
            OpenAICompatibleProvider(
                base_url=live_base_url,
                model=live_model,
                credential=credential_ref,
                credentials=EnvCredentialBroker(),
                timeout_seconds=60,
            )
            if live_base_url
            else DeterministicProvider(text="provider proposal accepted")
        )
        self.provider_configured = bool(live_base_url)
        self.grants = self._build_grants(now)
        self.compensation_grant = self._build_compensation_grant(now)
        self.domain_manifest = developer_agent_manifest(now)

    def _build_grants(self, now: datetime | None = None) -> dict[str, CapabilityGrant]:
        issued = now or datetime.now(timezone.utc)
        return {
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

    def _build_compensation_grant(
        self,
        now: datetime | None = None,
    ) -> CapabilityGrant:
        issued = now or datetime.now(timezone.utc)
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
        self.sandbox = WorkspaceSandbox(root, idempotency_store=self.store)
        self.grants = self._build_grants()
        return self.workspace_status()

    def provider_status(self) -> dict[str, Any]:
        return {
            "configured": self.provider_configured,
            "provider_id": self.provider_profile.provider_id,
            "model_id": self.provider_profile.model_id,
            "endpoint_class": self.provider_profile.endpoint_class,
            "credential_ref_id": self.provider_profile.credential_ref_id,
        }

    def configure_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        base_url = str(payload.get("base_url", "")).rstrip("/")
        if base_url.endswith("/chat/completions"):
            base_url = base_url.removesuffix("/chat/completions")
        model = str(payload.get("model", "")).strip()
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
        self.provider = provider
        self.provider_profile = profile
        self.provider_configured = True
        return {**self.provider_status(), "connection_test": "PASS"}

    def create_task(self, payload: dict[str, Any]):
        return self.tasks.create_task(Goal.model_validate(payload))

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

    def start_run(self, task_id: str):
        return self.tasks.start_run(
            task_id, provider_profile_id=self.provider_profile.profile_id
        )

    def run_task(
        self,
        task_id: str,
        inputs: dict[str, Any] | None = None,
        *,
        stop_after_node: str | None = None,
        recover_stale_lease: bool = False,
    ):
        if not self.provider_configured:
            raise ConnectionError(
                "configure and verify a provider before running a task"
            )
        aggregate = self.tasks.get_task(task_id)
        if aggregate.run is None:
            aggregate = self.start_run(task_id)
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

    def correct_task(self, task_id: str, reason: str):
        epoch = self.correction.correct("task", task_id, reason)
        self.tasks.append_event(
            task_id,
            TaskEventType.CORRECTION_WRITTEN,
            {"scope": "TASK", "epoch": epoch, "reason": reason},
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
        actor = principal or self.principal
        if actor.role not in {PrincipalRole.PRINCIPAL, PrincipalRole.TENANT_ADMIN}:
            raise PermissionError("correction resume requires principal authority")
        task = self.tasks.get_task(task_id)
        if task.run is None or task.commitment is None:
            raise ValueError("correction resume requires an active committed run")
        if (
            actor.tenant_id != task.commitment.tenant_id
            or actor.workspace_id != task.commitment.workspace_id
        ):
            raise PermissionError("correction resume scope mismatch")
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("correction resume reason is required")
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
            "status": task.status.value if task.status else None,
            "goal": task.goal.model_dump(mode="json") if task.goal else None,
            "commitment": task.commitment.model_dump(mode="json")
            if task.commitment
            else None,
            "workflow": task.workflow.model_dump(mode="json")
            if task.workflow
            else None,
            "run": task.run.model_dump(mode="json") if task.run else None,
            "expected_outcome": task.expected_outcome.model_dump(mode="json")
            if task.expected_outcome
            else None,
            "observed_outcome": task.observed_outcome.model_dump(mode="json")
            if task.observed_outcome
            else None,
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
