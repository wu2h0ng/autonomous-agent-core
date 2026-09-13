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
        ),
        workflow_templates=("developer_agent.repository_patch.v1",),
        evaluator_types=("pytest",),
        credential_classes=("none", "provider-api-key"),
        created_at=now or datetime.now(timezone.utc),
    )
