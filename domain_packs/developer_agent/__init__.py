from __future__ import annotations

from datetime import datetime, timezone

from agent_os_contracts import DomainPackManifest

from .repository_patch_profile import DeveloperRepositoryPatchProfile
from .workspace_capability import (
    EXECUTION_ISOLATION_SANDBOXED,
    EXECUTION_ISOLATION_TRUSTED_WORKSPACE,
    DeveloperWorkspaceAdapter,
)
from .workspace_collaboration import (
    SQLiteWorkspaceCommitFence,
    WorkspaceCollaborationPreflight,
    WorkspaceCommitFence,
    WorkspaceCommitFencePort,
    WorkspaceCoordinationSnapshot,
    WorkspaceEventProducer,
    WorkspaceEventSequenceConflict,
    WorkspaceFenceUnavailable,
    build_batch,
)

WorkspaceSandbox = DeveloperWorkspaceAdapter

__all__ = [
    "EXECUTION_ISOLATION_SANDBOXED",
    "EXECUTION_ISOLATION_TRUSTED_WORKSPACE",
    "DeveloperRepositoryPatchProfile",
    "DeveloperWorkspaceAdapter",
    "SQLiteWorkspaceCommitFence",
    "WorkspaceCollaborationPreflight",
    "WorkspaceCommitFence",
    "WorkspaceCommitFencePort",
    "WorkspaceCoordinationSnapshot",
    "WorkspaceEventProducer",
    "WorkspaceEventSequenceConflict",
    "WorkspaceFenceUnavailable",
    "WorkspaceSandbox",
    "build_batch",
    "manifest",
]


def manifest(now: datetime | None = None) -> DomainPackManifest:
    return DomainPackManifest(
        pack_id="developer-agent",
        version="1.0",
        namespace="developer_agent",
        capabilities=(
            "workspace.read",
            "workspace.apply_patch",
            "workspace.run_tests",
            "artifact.write",
            # Form B (ADR-0061 §5.1/§5.8): `agent.spawn` is declared by this
            # domain pack, not by the kernel, which stays domain-free. Its risk
            # tier is pinned at 2 in `permission_gate.ACTION_RISK_TIERS`,
            # `agent_loop.CHAT_GRANT_MAX_RISK_TIERS` and its `CapabilitySpec`
            # (`workspace_capability.DeveloperWorkspaceAdapter.specs`): deriving
            # a session/task/run is consequential but reversible, while tier 3
            # would make every spawn a human approval.
            #
            # Listing it here is the registration of record and grants nothing:
            # the runtime spec exists only when the composition root enables
            # child agents (`AGENT_OS_CHILD_AGENTS`, default off), so the
            # capability stays unreachable without that switch AND a grant, and
            # an unregistered capability is fail-closed in every permission mode
            # (`evaluate_permission_gate` -> DENY_OUT_OF_ALLOWLIST).
            "agent.spawn",
        ),
        workflow_templates=("developer_agent.repository_patch.v1",),
        evaluator_types=("pytest",),
        credential_classes=("none", "provider-api-key"),
        created_at=now or datetime.now(timezone.utc),
    )
