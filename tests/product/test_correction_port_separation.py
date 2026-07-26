from __future__ import annotations

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
