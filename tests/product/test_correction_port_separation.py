from __future__ import annotations

import threading
import time
from threading import RLock

from apps.api_server.app import AgentOSApplication
from agent_os_core import (
    CapabilityBroker,
    CorrectionAuthority,
    DomainCandidateEvaluationRecorder,
    DomainCandidatePromotionService,
    DomainCandidateSealer,
    PolicyKernel,
    RunCoordinator,
    SQLiteTaskEventStore,
    TaskConfigurationSnapshotService,
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


class _SnapshotOnlyFake:
    """Reader-only fake: proves generic Runtime constructors need no mutation."""

    def __init__(self) -> None:
        self._authority = CorrectionAuthority()

    def snapshot(self, task_id: str, run_id: str, capability_id: str):
        return self._authority.snapshot(task_id, run_id, capability_id)

    def halted(self, task_id: str, run_id: str, capability_id: str) -> bool:
        return self._authority.halted(task_id, run_id, capability_id)

    def guard_unchanged(
        self,
        task_id: str,
        run_id: str,
        capability_id: str,
        observed_epochs,
    ):
        return self._authority.guard_unchanged(
            task_id, run_id, capability_id, observed_epochs
        )


def test_generic_runtime_constructs_with_reader_only_port(tmp_path) -> None:
    app = AgentOSApplication(workspace=tmp_path)
    reader = _SnapshotOnlyFake()

    assert not hasattr(reader, "correct")
    assert not hasattr(reader, "resume")

    policy = PolicyKernel(reader)
    broker = CapabilityBroker(app.sandbox, reader)
    coordinator = RunCoordinator(
        app.tasks,
        app.sandbox,
        app.execution_profile,
        app.provider,
        app.provider_profile,
        policy,
        reader,
        dict(app.grants),
        compensation_grant=app.compensation_grant,
    )
    sealer = DomainCandidateSealer(app.tasks, reader, app.candidates)
    recorder = DomainCandidateEvaluationRecorder(
        app.tasks,
        reader,
        app.candidates,
        app.evaluation_receipts,
        app.grants,
    )
    promotions = DomainCandidatePromotionService(
        app.tasks,
        reader,
        app.candidates,
        app.evaluation_receipts,
        app.candidate_promotions,
        app.grants,
        app.promotion_policies,
    )
    configurations = TaskConfigurationSnapshotService(
        app.tasks,
        reader,
        configuration_lock=RLock(),
        configuration_reader=app._task_configuration_runtime,
        candidates=app.candidates,
        evaluations=app.evaluation_receipts,
        promotions=app.candidate_promotions,
    )

    retained = (
        policy.correction,
        broker.correction,
        coordinator.correction,
        sealer._correction,
        recorder._correction,
        promotions._correction,
        configurations._correction,
    )
    for correction in retained:
        assert not hasattr(correction, "correct")
        assert not hasattr(correction, "resume")


def test_admin_writes_survive_authority_restart_through_views(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    _, first_admin = split_correction_authority(
        CorrectionAuthority(SQLiteTaskEventStore(path))
    )

    assert first_admin.correct("task", "task-1", "stop") == 1

    second_snapshot, _ = split_correction_authority(
        CorrectionAuthority(SQLiteTaskEventStore(path))
    )
    assert second_snapshot.halted("task-1", "run-1", "workspace.read")
    assert second_snapshot.snapshot("task-1", "run-1", "workspace.read").task_epoch == 1


def test_guard_unchanged_linearizes_admin_write() -> None:
    authority = CorrectionAuthority()
    snapshot, admin = split_correction_authority(authority)
    observed = snapshot.snapshot("task-1", "run-1", "capability-1")

    guard_entered = threading.Event()
    release_guard = threading.Event()
    write_completed = threading.Event()
    errors: list[BaseException] = []

    def hold_guard() -> None:
        try:
            with snapshot.guard_unchanged(
                "task-1", "run-1", "capability-1", observed
            ) as unchanged:
                assert unchanged
                guard_entered.set()
                release_guard.wait(timeout=10)
        except BaseException as exc:  # noqa: BLE001 - surfaced in main thread
            errors.append(exc)

    def write() -> None:
        try:
            guard_entered.wait(timeout=10)
            epoch = admin.correct("task", "task-1", "concurrent halt")
            assert epoch == 1
            write_completed.set()
        except BaseException as exc:  # noqa: BLE001 - surfaced in main thread
            errors.append(exc)

    guard_thread = threading.Thread(target=hold_guard)
    write_thread = threading.Thread(target=write)
    guard_thread.start()
    write_thread.start()

    assert guard_entered.wait(timeout=10)
    time.sleep(0.2)
    assert not write_completed.is_set(), (
        "admin write advanced while the guard held the authority lock"
    )

    release_guard.set()
    guard_thread.join(timeout=10)
    write_thread.join(timeout=10)

    assert not guard_thread.is_alive()
    assert not write_thread.is_alive()
    assert not errors
    assert write_completed.is_set()
    after = snapshot.snapshot("task-1", "run-1", "capability-1")
    assert after.task_epoch == observed.task_epoch + 1


def test_stale_observation_is_detected_through_views() -> None:
    authority = CorrectionAuthority()
    snapshot, admin = split_correction_authority(authority)
    initial = snapshot.snapshot("task-1", "run-1", "workspace.read")

    admin.correct("task", "task-1", "principal pause")

    assert snapshot.snapshot("task-1", "run-1", "workspace.read") != initial
    assert snapshot.halted("task-1", "run-1", "workspace.read")
    with snapshot.guard_unchanged(
        "task-1", "run-1", "workspace.read", initial
    ) as unchanged:
        assert not unchanged
