from __future__ import annotations

from apps.api_server.app import AgentOSApplication
from agent_os_core import (
    CorrectionAuthority,
    split_correction_authority,
)


def test_snapshot_view_has_no_mutation_capability() -> None:
    authority = CorrectionAuthority()
    snapshot, admin = split_correction_authority(authority)

    assert hasattr(snapshot, "snapshot")
    assert hasattr(snapshot, "halted")
    assert hasattr(snapshot, "guard_unchanged")
    assert not hasattr(snapshot, "correct")
    assert not hasattr(snapshot, "resume")
    assert hasattr(admin, "correct")
    assert hasattr(admin, "resume")
    assert not hasattr(admin, "snapshot")


def test_admin_write_is_observed_only_through_snapshot_view() -> None:
    authority = CorrectionAuthority()
    snapshot, admin = split_correction_authority(authority)
    before = snapshot.snapshot("task-1", "run-1", "capability-1")

    assert admin.correct("task", "task-1", "operator halt") == 1

    after = snapshot.snapshot("task-1", "run-1", "capability-1")
    assert after.task_epoch == before.task_epoch + 1
    assert snapshot.halted("task-1", "run-1", "capability-1")


def test_composition_injects_only_the_read_only_view(tmp_path) -> None:
    app = AgentOSApplication(workspace=tmp_path)

    assert hasattr(app.correction, "snapshot")
    assert hasattr(app.correction, "halted")
    assert hasattr(app.correction, "guard_unchanged")
    assert not hasattr(app.correction, "correct")
    assert not hasattr(app.correction, "resume")

    assert hasattr(app.correction_admin, "correct")
    assert hasattr(app.correction_admin, "resume")

    assert not hasattr(app.policy.correction, "correct")
    assert not hasattr(app.policy.correction, "resume")
