from __future__ import annotations

from pathlib import Path

import pytest

from agent_os_contracts import (
    CollaborationDisposition,
    ResourceScope,
    WorkspaceActorKind,
    WorkspaceEvent,
    WorkspaceEventImpact,
    WorkspaceEventKind,
    WorkspaceWriteDecision,
)
from domain_packs.developer_agent.workspace_collaboration import (
    SQLiteWorkspaceCommitFence,
    WorkspaceCollaborationPreflight,
    WorkspaceCommitFence,
    WorkspaceEventProducer,
)

from tests.product.test_workspace_collaboration_fence import (
    _action,
    _claim,
    _lease,
    _now,
)


def _producer_scope(path: str) -> ResourceScope:
    return ResourceScope(resource_uri=f"file:///ws/{path}")


def test_producer_records_external_write_as_mutation_event() -> None:
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    producer = WorkspaceEventProducer(fence)
    producer.record_external_write(
        workspace_id="workspace:local",
        path="a.txt",
        actor_id="user:external",
        actor_kind=WorkspaceActorKind.HUMAN,
    )
    snapshot = fence.read_coordination("workspace:local")
    assert len(snapshot.batch.events) == 1
    event = snapshot.batch.events[0]
    assert event.impact is WorkspaceEventImpact.WRITE_CONFLICT
    assert event.kind is WorkspaceEventKind.MUTATION
    assert _producer_scope("a.txt") in event.affected_scopes


def test_producer_event_forces_conflict_on_overlapping_scope() -> None:
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    producer = WorkspaceEventProducer(fence)
    producer.record_external_write(
        workspace_id="workspace:local",
        path="a.txt",
        actor_id="user:external",
        actor_kind=WorkspaceActorKind.HUMAN,
    )
    preflight = WorkspaceCollaborationPreflight(fence)
    decision = preflight.preflight(_action(), _claim())
    assert decision.disposition is CollaborationDisposition.CONFLICT


def test_producer_sequences_are_monotonic() -> None:
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    producer = WorkspaceEventProducer(fence)
    producer.record_external_write(workspace_id="workspace:local", path="a.txt", actor_id="u1", actor_kind=WorkspaceActorKind.HUMAN)
    producer.record_external_write(workspace_id="workspace:local", path="b.txt", actor_id="u2", actor_kind=WorkspaceActorKind.HUMAN)
    snapshot = fence.read_coordination("workspace:local")
    sequences = [event.sequence for event in snapshot.batch.events]
    assert sequences == [1, 2]


def test_producer_event_advances_version() -> None:
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    producer = WorkspaceEventProducer(fence)
    producer.record_external_write(workspace_id="workspace:local", path="a.txt", actor_id="u1", actor_kind=WorkspaceActorKind.HUMAN)
    event = fence.read_coordination("workspace:local").batch.events[0]
    assert event.base_version != event.resulting_version


def test_producer_excludes_unrelated_scope_from_decision() -> None:
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    producer = WorkspaceEventProducer(fence)
    producer.record_external_write(workspace_id="workspace:local", path="other.txt", actor_id="u1", actor_kind=WorkspaceActorKind.HUMAN)
    preflight = WorkspaceCollaborationPreflight(fence)
    decision = preflight.preflight(_action(), _claim())
    assert decision.disposition is CollaborationDisposition.CONTINUE


def test_sqlite_producer_persists_and_reads_back(tmp_path: Path) -> None:
    fence = SQLiteWorkspaceCommitFence(tmp_path / "coord.sqlite3")
    fence.install_lease(_lease(event_cursor=0))
    producer = WorkspaceEventProducer(fence)
    producer.record_external_write(workspace_id="workspace:local", path="a.txt", actor_id="u1", actor_kind=WorkspaceActorKind.HUMAN)
    reloaded = SQLiteWorkspaceCommitFence(tmp_path / "coord.sqlite3")
    preflight = WorkspaceCollaborationPreflight(reloaded)
    decision = preflight.preflight(_action(), _claim())
    assert decision.disposition is CollaborationDisposition.CONFLICT


def test_new_lease_cursor_starts_at_high_water_unblocks_after_conflict() -> None:
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    producer = WorkspaceEventProducer(fence)
    producer.record_external_write(workspace_id="workspace:local", path="a.txt", actor_id="u1", actor_kind=WorkspaceActorKind.HUMAN)
    preflight = WorkspaceCollaborationPreflight(fence)
    assert preflight.preflight(_action(), _claim()).disposition is CollaborationDisposition.CONFLICT

    # Replan: install a new lease whose cursor is the fence high-water.
    snapshot = fence.read_coordination("workspace:local")
    replanned = _lease(event_cursor=snapshot.batch.through_cursor)
    fence.install_lease(replanned)
    decision = preflight.preflight(_action(), _claim())
    assert decision.disposition is CollaborationDisposition.CONTINUE


def test_retry_without_replan_keeps_original_cursor_and_keeps_conflict() -> None:
    """Regression for review P2 #1: an explicit replan advances the cursor, but a
    plain retry (re-installing the SAME lease, not a high-water lease) must not
    silently acknowledge the conflict."""
    fence = WorkspaceCommitFence()
    fence.install_lease(_lease(event_cursor=0))
    producer = WorkspaceEventProducer(fence)
    producer.record_external_write(workspace_id="workspace:local", path="a.txt", actor_id="u1", actor_kind=WorkspaceActorKind.HUMAN)
    preflight = WorkspaceCollaborationPreflight(fence)

    # Simulate retry: re-install the same lease (cursor unchanged at 0).
    fence.install_lease(_lease(event_cursor=0))
    assert preflight.preflight(_action(), _claim()).disposition is CollaborationDisposition.CONFLICT


def test_producer_retries_on_sequence_conflict() -> None:
    """Review P2 #2: a concurrent append claiming the same sequence is retried
    against a fresh high-water instead of dropping the legitimate write."""
    from domain_packs.developer_agent.workspace_collaboration import (
        WorkspaceEventSequenceConflict,
    )

    class ConflictOnceFence(WorkspaceCommitFence):
        def __init__(self) -> None:
            super().__init__()
            self._conflict_once = True

        def append_event(self, event: WorkspaceEvent) -> None:
            if self._conflict_once:
                self._conflict_once = False
                raise WorkspaceEventSequenceConflict("concurrent claim")
            super().append_event(event)

    fence = ConflictOnceFence()
    fence.install_lease(_lease(event_cursor=0))
    producer = WorkspaceEventProducer(fence)
    producer.record_external_write(workspace_id="workspace:local", path="a.txt", actor_id="u1", actor_kind=WorkspaceActorKind.HUMAN)
    snapshot = fence.read_coordination("workspace:local")
    assert len(snapshot.batch.events) == 1


def test_conflict_projection_rejects_continue_decision() -> None:
    from agent_os_contracts.surface import SurfaceConflictProjection

    decision = WorkspaceWriteDecision(
        lease_id="lease:1",
        action_id="action:edit",
        plan_version=1,
        disposition=CollaborationDisposition.CONTINUE,
        checked_event_cursor=0,
        relevant_event_ids=(),
        event_batch_provenance_ref="coordination-store",
        write_scopes=(_producer_scope("a.txt"),),
        reason="no relevant events",
        decided_at=_now(),
    )
    with pytest.raises(ValueError, match="denial-only"):
        SurfaceConflictProjection.from_decision(decision)


def test_conflict_projection_suggested_action_for_replan() -> None:
    from agent_os_contracts.surface import SurfaceConflictProjection

    decision = WorkspaceWriteDecision(
        lease_id="lease:1",
        action_id="action:edit",
        plan_version=1,
        disposition=CollaborationDisposition.REPLAN,
        checked_event_cursor=0,
        relevant_event_ids=("ev:1",),
        event_batch_provenance_ref="coordination-store",
        write_scopes=(_producer_scope("a.txt"),),
        reason="relevant events",
        decided_at=_now(),
    )
    projection = SurfaceConflictProjection.from_decision(decision)
    assert projection.disposition == "REPLAN"
    assert projection.suggested_action == "REPLAN"
    assert projection.relevant_event_ids == ("ev:1",)


def test_conflict_projection_suggested_action_for_conflict() -> None:
    from agent_os_contracts.surface import SurfaceConflictProjection

    decision = WorkspaceWriteDecision(
        lease_id="lease:1",
        action_id="action:edit",
        plan_version=1,
        disposition=CollaborationDisposition.CONFLICT,
        checked_event_cursor=0,
        relevant_event_ids=("ev:1",),
        event_batch_provenance_ref="coordination-store",
        write_scopes=(_producer_scope("a.txt"),),
        reason="write conflict",
        decided_at=_now(),
    )
    projection = SurfaceConflictProjection.from_decision(decision)
    assert projection.disposition == "CONFLICT"
    assert projection.suggested_action == "REVIEW_DIFF"
