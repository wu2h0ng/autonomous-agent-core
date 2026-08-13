from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_os_contracts import (
    CollaborationDisposition,
    ResourceScope,
    WorkspaceActorKind,
    WorkspaceEvent,
    WorkspaceEventImpact,
    WorkspaceEventKind,
)
from domain_packs.developer_agent.workspace_collaboration import (
    SQLiteWorkspaceCommitFence,
    WorkspaceCollaborationPreflight,
    WorkspaceCommitFence,
    WorkspaceEventSequenceConflict,
)

from tests.product.test_workspace_collaboration_fence import (
    _action,
    _claim,
    _lease,
    _now,
)


def _event(
    *,
    sequence: int,
    scopes: tuple[ResourceScope, ...],
    impact: WorkspaceEventImpact = WorkspaceEventImpact.WRITE_CONFLICT,
) -> WorkspaceEvent:
    return WorkspaceEvent(
        event_id=f"ev:{sequence}",
        workspace_id="workspace:local",
        sequence=sequence,
        actor_id="user:other",
        actor_kind=WorkspaceActorKind.HUMAN,
        kind=WorkspaceEventKind.MUTATION,
        impact=impact,
        affected_scopes=scopes,
        base_version=f"v{sequence - 1}",
        resulting_version=f"v{sequence}",
        provenance_refs=(f"p:{sequence}",),
        occurred_at=_now(),
    )


def test_fence_holds_no_effect_truth() -> None:
    fence = WorkspaceCommitFence()
    attrs = set(vars(fence).keys()) | set(dir(fence))
    assert not any("PREPARED" in str(a) or "COMMITTED" in str(a) or "UNKNOWN" in str(a) for a in attrs)
    assert not hasattr(fence, "dispatch")


def test_preflight_continue_when_no_relevant_events() -> None:
    fence = WorkspaceCommitFence()
    lease = _lease(event_cursor=0)
    fence.install_lease(lease)
    preflight = WorkspaceCollaborationPreflight(fence)
    action = _action()
    decision = preflight.preflight(action, _claim())
    assert decision.disposition is CollaborationDisposition.CONTINUE


def test_preflight_conflict_on_write_conflict_event() -> None:
    fence = WorkspaceCommitFence()
    lease = _lease(event_cursor=0)
    fence.install_lease(lease)
    fence.append_event(
        _event(sequence=1, scopes=(ResourceScope(resource_uri="file:///ws/a.txt"),))
    )
    preflight = WorkspaceCollaborationPreflight(fence)
    decision = preflight.preflight(_action(), _claim())
    assert decision.disposition is CollaborationDisposition.CONFLICT


def test_preflight_replan_on_context_change_event() -> None:
    fence = WorkspaceCommitFence()
    lease = _lease(event_cursor=0)
    fence.install_lease(lease)
    fence.append_event(
        _event(
            sequence=1,
            scopes=(ResourceScope(resource_uri="file:///ws/a.txt"),),
            impact=WorkspaceEventImpact.CONTEXT_CHANGED,
        )
    )
    preflight = WorkspaceCollaborationPreflight(fence)
    decision = preflight.preflight(_action(), _claim())
    assert decision.disposition is CollaborationDisposition.REPLAN


def test_preflight_cancel_on_expired_lease() -> None:
    fence = WorkspaceCommitFence()
    now = _now()
    lease = _lease(event_cursor=0)
    expired = lease.model_copy(
        update={"issued_at": now - timedelta(minutes=20), "expires_at": now - timedelta(minutes=10)}
    )
    fence.install_lease(expired)
    preflight = WorkspaceCollaborationPreflight(fence)
    decision = preflight.preflight(_action(), _claim())
    assert decision.disposition is CollaborationDisposition.CANCEL


def test_preflight_cancel_on_execution_claim_run_mismatch() -> None:
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    preflight = WorkspaceCollaborationPreflight(fence)
    decision = preflight.preflight(_action(), _claim(run_id="run:other"))
    assert decision.disposition is CollaborationDisposition.CANCEL


def test_preflight_continue_for_unrelated_scope() -> None:
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    fence.append_event(
        _event(sequence=1, scopes=(ResourceScope(resource_uri="file:///ws/other.txt"),))
    )
    preflight = WorkspaceCollaborationPreflight(fence)
    decision = preflight.preflight(_action(), _claim())
    assert decision.disposition is CollaborationDisposition.CONTINUE


def test_preflight_cancel_when_no_lease_installed() -> None:
    fence = WorkspaceCommitFence()
    preflight = WorkspaceCollaborationPreflight(fence)
    decision = preflight.preflight(_action(), _claim())
    assert decision.disposition is CollaborationDisposition.CANCEL


def test_sqlite_fence_persists_lease_and_events(tmp_path: Path) -> None:
    db = tmp_path / "coord.sqlite3"
    fence = SQLiteWorkspaceCommitFence(db)
    lease = _lease(event_cursor=0)
    fence.install_lease(lease)
    fence.append_event(
        _event(sequence=1, scopes=(ResourceScope(resource_uri="file:///ws/a.txt"),))
    )
    reloaded = SQLiteWorkspaceCommitFence(db)
    preflight = WorkspaceCollaborationPreflight(reloaded)
    decision = preflight.preflight(_action(), _claim())
    assert decision.disposition is CollaborationDisposition.CONFLICT


def test_append_duplicate_sequence_rejected(tmp_path: Path) -> None:
    fence = SQLiteWorkspaceCommitFence(tmp_path / "coord.sqlite3")
    fence.install_lease(_lease(event_cursor=0))
    fence.append_event(_event(sequence=1, scopes=(ResourceScope(resource_uri="file:///ws/a.txt"),)))
    with pytest.raises(WorkspaceEventSequenceConflict):
        fence.append_event(
            _event(sequence=1, scopes=(ResourceScope(resource_uri="file:///ws/other.txt"),))
        )


def test_in_memory_append_duplicate_sequence_rejected() -> None:
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    fence.append_event(_event(sequence=1, scopes=(ResourceScope(resource_uri="file:///ws/a.txt"),)))
    with pytest.raises(WorkspaceEventSequenceConflict):
        fence.append_event(
            _event(sequence=1, scopes=(ResourceScope(resource_uri="file:///ws/other.txt"),))
        )


def test_gap_in_event_sequence_fails_closed() -> None:
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    fence.append_event(_event(sequence=1, scopes=(ResourceScope(resource_uri="file:///ws/a.txt"),)))
    fence.append_event(_event(sequence=3, scopes=(ResourceScope(resource_uri="file:///ws/a.txt"),)))
    preflight = WorkspaceCollaborationPreflight(fence)
    decision = preflight.preflight(_action(), _claim())
    assert decision.disposition is CollaborationDisposition.CANCEL


def test_sqlite_gap_in_event_sequence_fails_closed(tmp_path: Path) -> None:
    fence = SQLiteWorkspaceCommitFence(tmp_path / "coord.sqlite3")
    fence.install_lease(_lease(event_cursor=0))
    fence.append_event(_event(sequence=1, scopes=(ResourceScope(resource_uri="file:///ws/a.txt"),)))
    fence.append_event(_event(sequence=3, scopes=(ResourceScope(resource_uri="file:///ws/a.txt"),)))
    preflight = WorkspaceCollaborationPreflight(fence)
    decision = preflight.preflight(_action(), _claim())
    assert decision.disposition is CollaborationDisposition.CANCEL


def test_task_id_mismatch_fails_closed() -> None:
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    preflight = WorkspaceCollaborationPreflight(fence)
    decision = preflight.preflight(_action(), _claim())
    # _action uses task_id="task:long"; lease uses "task:long" so this is CONTINUE;
    # build a mismatched action.

    mismatched = _action().model_copy(update={"task_id": "task:other"})
    decision = preflight.preflight(mismatched, _claim())
    assert decision.disposition is CollaborationDisposition.CANCEL


def test_tenant_id_mismatch_fails_closed() -> None:
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    preflight = WorkspaceCollaborationPreflight(fence)
    mismatched = _action().model_copy(update={"tenant_id": "tenant:other"})
    decision = preflight.preflight(mismatched, _claim())
    assert decision.disposition is CollaborationDisposition.CANCEL


def test_unresolvable_write_scope_fails_closed() -> None:
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    preflight = WorkspaceCollaborationPreflight(fence)
    import json

    no_path = _action().model_copy(
        update={"arguments_json": json.dumps({"content": "no path"})}
    )
    decision = preflight.preflight(no_path, _claim())
    assert decision.disposition is CollaborationDisposition.CANCEL
