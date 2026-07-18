from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    CredentialRef,
    RelevanceAssessment,
    RelevanceAssessorRef,
    RelevanceDisposition,
    RelevanceUrgency,
    SituatedAssessmentOutcomeKind,
    SituatedAssessmentRecord,
    content_digest,
)
from apps.api_server import __main__ as api_main
from apps.api_server.app import AgentOSApplication
from apps.api_server.data_agent_report_adapter import (
    DataAgentReportAdapter,
    DataAgentReportAdapterError,
    DataAgentReportHttpResponse,
    SQLiteDataAgentReportStateStore,
    _InMemoryDataAgentReportStateStore,
)
from apps.api_server.mandate_active_perception import (
    ActivePerceptionDisposition,
    ActivePerceptionLease,
    MandateActivePerceptionConfig,
    MandateActivePerceptionService,
    SQLiteMandateActivePerceptionStore,
)
from tests.product.test_data_agent_external_report_adapter import (
    NOW,
    _adapter,
    _config,
    _credential,
    _feed_bytes,
    _feed_event,
    _response,
    _Transport,
)
from tests.product.test_data_agent_report_dispatch_outbox import _outcome_record


class _CredentialBroker:
    def resolve(self, credential: CredentialRef) -> str:
        del credential
        return "secret-value-that-must-not-leak"


def _feed_adapter(
    database: Path,
    *,
    cursor: str = "cursor-1",
    transaction_now: datetime = NOW,
) -> DataAgentReportAdapter:
    feed = _feed_bytes([_feed_event(cursor)], next_cursor=cursor)
    adapter, _, _ = _adapter(
        response=_response(
            feed,
            final_url="http://127.0.0.1:8765/external/report-events?limit=1",
        ),
        config=_config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        state_store=SQLiteDataAgentReportStateStore(database),
        now=transaction_now,
    )
    return adapter


def test_poll_commits_pending_dispatch_and_cursor_atomically(tmp_path: Path) -> None:
    database = tmp_path / "reports.sqlite3"
    adapter = _feed_adapter(database)

    result = adapter.poll_once(limit=1)
    pending = adapter.pending_dispatches()

    assert adapter.feed_cursor == "cursor-1"
    assert len(result.bundles) == len(pending) == 1
    assert (
        pending[0].environment_event_id == result.bundles[0].event.environment_event_id
    )
    assert pending[0].projection_id == result.bundles[0].projection.projection_id
    assert pending[0].status == "PENDING"
    assert pending[0].activation_authorized is False
    assert pending[0].capability_grant_authorized is False
    assert pending[0].external_effects_authorized is False


def test_outbox_insert_failure_cannot_advance_cursor(tmp_path: Path) -> None:
    database = tmp_path / "reports.sqlite3"
    adapter = _feed_adapter(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_dispatch BEFORE INSERT
            ON data_agent_report_dispatch_outbox
            BEGIN SELECT RAISE(ABORT, 'reject dispatch'); END
            """
        )

    with pytest.raises(DataAgentReportAdapterError):
        adapter.poll_once(limit=1)

    assert adapter.feed_cursor is None
    assert adapter.pending_dispatches() == ()
    assert adapter.registry_counts == (0, 0, 0, 0)
    with sqlite3.connect(database) as connection:
        event_id = connection.execute(
            "SELECT event_id FROM data_agent_report_observations"
        ).fetchone()[0]
    assert adapter.resolve_event(event_id) is None
    restarted = _feed_adapter(database)
    assert restarted.resolve_event(event_id) is None


def test_pending_dispatch_survives_restart_and_completed_replay_is_not_pending(
    tmp_path: Path,
) -> None:
    database = tmp_path / "reports.sqlite3"
    first = _feed_adapter(database)
    first.poll_once(limit=1)
    pending = first.pending_dispatches()[0]

    restarted = _feed_adapter(database)
    assert restarted.pending_dispatches() == (pending,)

    restarted.complete_dispatch(
        pending,
        outcome_record=_outcome_record(restarted, pending),
        completed_at=NOW,
        consumer_id="worker-1",
        authority_snapshot_digest="a" * 64,
    )
    assert restarted.pending_dispatches() == ()

    second_restart = _feed_adapter(database)
    assert second_restart.pending_dispatches() == ()
    assert second_restart.completed_dispatch(pending.dispatch_id) is not None


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("tenant_id", "tenant:attacker"),
        ("projection_id", "projection:attacker"),
        ("dispatch_digest", "0" * 64),
    ],
)
def test_dispatch_scope_or_digest_tamper_fails_closed(
    tmp_path: Path, column: str, value: str
) -> None:
    database = tmp_path / "reports.sqlite3"
    adapter = _feed_adapter(database)
    adapter.poll_once(limit=1)
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE data_agent_report_dispatch_outbox SET {column} = ?", (value,)
        )

    with pytest.raises(DataAgentReportAdapterError, match="dispatch"):
        adapter.pending_dispatches()


def test_recomputed_dispatch_cannot_reference_nonexistent_projection(
    tmp_path: Path,
) -> None:
    database = tmp_path / "reports.sqlite3"
    adapter = _feed_adapter(database)
    adapter.poll_once(limit=1)
    original = adapter.pending_dispatches()[0]
    forged = replace(original, projection_id="projection:missing")
    forged_digest = content_digest(
        SQLiteDataAgentReportStateStore._dispatch_payload(forged)
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE data_agent_report_dispatch_outbox
            SET dispatch_id = ?, dispatch_digest = ?, projection_id = ?
            """,
            (
                f"data-agent-dispatch:{forged_digest}",
                forged_digest,
                forged.projection_id,
            ),
        )

    with pytest.raises(DataAgentReportAdapterError, match="dispatch"):
        adapter.pending_dispatches()


def test_completion_receipt_tamper_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "reports.sqlite3"
    adapter = _feed_adapter(database)
    adapter.poll_once(limit=1)
    dispatch = adapter.pending_dispatches()[0]
    completed = adapter.complete_dispatch(
        dispatch,
        outcome_record=_outcome_record(adapter, dispatch),
        completed_at=NOW,
        consumer_id="worker-1",
        authority_snapshot_digest="a" * 64,
    )
    assert completed.completion_digest is not None
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE data_agent_report_dispatch_outbox SET completion_digest = ?",
            ("0" * 64,),
        )

    with pytest.raises(DataAgentReportAdapterError, match="dispatch"):
        adapter.completed_dispatch(dispatch.dispatch_id)


def test_in_memory_completion_replay_is_exactly_idempotent() -> None:
    cursor = "cursor-memory-1"
    feed = _feed_bytes([_feed_event(cursor)], next_cursor=cursor)
    adapter, _, _ = _adapter(
        response=_response(
            feed,
            final_url="http://127.0.0.1:8765/external/report-events?limit=1",
        ),
        config=_config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        state_store=_InMemoryDataAgentReportStateStore(),
    )
    adapter.poll_once(limit=1)
    dispatch = adapter.pending_dispatches()[0]

    first = adapter.complete_dispatch(
        dispatch,
        outcome_record=_outcome_record(adapter, dispatch),
        completed_at=NOW,
        consumer_id="worker-1",
        authority_snapshot_digest="a" * 64,
    )
    replay = adapter.complete_dispatch(
        dispatch,
        outcome_record=_outcome_record(adapter, dispatch),
        completed_at=NOW,
        consumer_id="worker-1",
        authority_snapshot_digest="a" * 64,
    )

    assert replay == first


class _Runtime:
    def __init__(self) -> None:
        self.preflight_calls = 0
        self.admit_calls = 0
        self.propose_calls = 0
        self.revoked = False
        self.authority_digest = "a" * 64
        self.change_after_admit = False
        self.change_after_propose = False

    def assert_observation_authority(self) -> str:
        self.preflight_calls += 1
        if self.revoked:
            raise RuntimeError("observation authority revoked")
        return self.authority_digest

    def admit_event(self, event_id: str) -> Any:
        self.admit_calls += 1
        if self.change_after_admit:
            self.authority_digest = "b" * 64
        return type("Receipt", (), {"receipt_id": f"receipt:{event_id}"})()

    def propose(self, event_id: str, projection_id: str, receipt_id: str) -> None:
        del event_id, projection_id, receipt_id
        self.propose_calls += 1
        if self.change_after_propose:
            self.authority_digest = "b" * 64
        return None

    def propose_record(
        self, event_id: str, projection_id: str, receipt_id: str
    ) -> SituatedAssessmentRecord:
        self.propose(event_id, projection_id, receipt_id)
        source_binding_digest = "b" * 64
        assessment = RelevanceAssessment(
            assessment_id=f"assessment:{event_id}",
            environment_event_id=event_id,
            event_observation_digest="a" * 64,
            projection_id=projection_id,
            projection_digest="b" * 64,
            mandate_id="mandate:build-agent-os",
            mandate_version=1,
            mandate_digest="c" * 64,
            environment_binding_id="binding:data-agent-reports",
            environment_binding_version=1,
            environment_binding_digest="e" * 64,
            correction_epoch=0,
            assessor=RelevanceAssessorRef(
                assessor_id="assessor:test", version=1, policy_digest="d" * 64
            ),
            input_binding_digest="e" * 64,
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            disposition=RelevanceDisposition.IGNORE,
            uncertainty_summary="bounded",
            urgency=RelevanceUrgency.LOW,
            expected_loss_of_delay="none",
            attention_budget_seconds=1,
            rationale="no proposal",
            evidence_ids=("evidence:test",),
            assessed_at=NOW,
        )
        return SituatedAssessmentRecord(
            assessment_record_id=f"situated-assessment:{source_binding_digest}",
            source_binding_digest=source_binding_digest,
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            assessment=assessment,
            outcome_kind=SituatedAssessmentOutcomeKind.NO_PROPOSAL,
            recorded_at=NOW,
        )


def _service(
    tmp_path: Path,
    *,
    now: datetime = NOW,
    adapter: DataAgentReportAdapter | None = None,
    runtime: _Runtime | None = None,
    interval_seconds: int = 60,
    wake_budget: int = 2,
    query_budget: int = 2,
) -> tuple[MandateActivePerceptionService, _Runtime, DataAgentReportAdapter]:
    runtime_database = tmp_path / "runtime.sqlite3"
    reports = adapter or _feed_adapter(runtime_database)
    situated = runtime or _Runtime()
    store = SQLiteMandateActivePerceptionStore(runtime_database)
    config = MandateActivePerceptionConfig(
        schedule_id="schedule:mandate-1",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        mandate_id="mandate:build-agent-os",
        environment_binding_id="binding:data-agent-reports",
        interval_seconds=interval_seconds,
        budget_window_seconds=3600,
        wake_budget_per_window=wake_budget,
        query_budget_per_window=query_budget,
        feed_limit=1,
        lease_seconds=30,
    )
    service = MandateActivePerceptionService(
        config=config,
        store=store,
        adapter=reports,
        runtime=situated,
        clock=lambda: now,
    )
    service.ensure_schedule(first_wake_at=NOW)
    return service, situated, reports


def test_service_rejects_separate_report_and_schedule_databases(
    tmp_path: Path,
) -> None:
    adapter = _feed_adapter(tmp_path / "reports.sqlite3")
    store = SQLiteMandateActivePerceptionStore(tmp_path / "perception.sqlite3")
    config = MandateActivePerceptionConfig(
        schedule_id="schedule:mandate-1",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        mandate_id="mandate:build-agent-os",
        environment_binding_id="binding:data-agent-reports",
        interval_seconds=60,
        budget_window_seconds=3600,
        wake_budget_per_window=2,
        query_budget_per_window=2,
        feed_limit=1,
        lease_seconds=30,
    )

    with pytest.raises(TypeError, match="database"):
        MandateActivePerceptionService(
            config=config,
            store=store,
            adapter=adapter,
            runtime=_Runtime(),
            clock=lambda: NOW,
        )


def test_stale_lease_holder_cannot_complete_after_takeover(tmp_path: Path) -> None:
    service, runtime, adapter = _service(tmp_path)
    service.ensure_schedule(first_wake_at=NOW)
    adapter.poll_once(limit=1)
    dispatch = adapter.pending_dispatches()[0]
    stale = service.store.acquire_due_lease(
        service.config,
        worker_id="worker-stale",
        now=NOW,
        force_pending=True,
    )
    assert isinstance(stale, ActivePerceptionLease)
    completed_at = NOW + timedelta(seconds=service.config.lease_seconds + 1)
    current = service.store.acquire_due_lease(
        service.config,
        worker_id="worker-current",
        now=completed_at,
        force_pending=True,
    )
    assert isinstance(current, ActivePerceptionLease)

    with pytest.raises(
        (DataAgentReportAdapterError, RuntimeError), match="lease fence"
    ):
        adapter.complete_active_perception_dispatch(
            dispatch,
            outcome_record=runtime.propose_record(
                dispatch.environment_event_id,
                dispatch.projection_id,
                f"receipt:{dispatch.environment_event_id}",
            ),
            schedule_id=service.config.schedule_id,
            config_digest=service.config.config_digest,
            worker_id=stale.worker_id,
            lease_fence=stale.fence,
            completed_at=completed_at,
            authority_snapshot_digest=runtime.authority_digest,
        )
    assert adapter.pending_dispatches() == (dispatch,)


def test_expired_lease_cannot_complete_with_backdated_receipt_time(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    transaction_now = NOW + timedelta(seconds=31)
    adapter = _feed_adapter(database, transaction_now=transaction_now)
    service, runtime, _ = _service(tmp_path, adapter=adapter)
    adapter.poll_once(limit=1)
    dispatch = adapter.pending_dispatches()[0]
    lease = service.store.acquire_due_lease(
        service.config,
        worker_id="worker-expired",
        now=NOW,
        force_pending=True,
    )
    assert isinstance(lease, ActivePerceptionLease)
    assert lease.expires_at < transaction_now

    with pytest.raises(DataAgentReportAdapterError, match="lease fence"):
        adapter.complete_active_perception_dispatch(
            dispatch,
            outcome_record=runtime.propose_record(
                dispatch.environment_event_id,
                dispatch.projection_id,
                f"receipt:{dispatch.environment_event_id}",
            ),
            schedule_id=service.config.schedule_id,
            config_digest=service.config.config_digest,
            worker_id=lease.worker_id,
            lease_fence=lease.fence,
            completed_at=NOW + timedelta(seconds=1),
            authority_snapshot_digest=runtime.authority_digest,
        )
    assert adapter.pending_dispatches() == (dispatch,)


def test_due_run_polls_admits_proposes_and_records_no_effect_receipt(
    tmp_path: Path,
) -> None:
    service, runtime, adapter = _service(tmp_path)

    receipt = service.run_due_once(worker_id="worker-1")

    assert receipt.disposition is ActivePerceptionDisposition.COMPLETED
    assert receipt.observed_count == 1
    assert receipt.proposal_count == 1
    assert receipt.activation_authorized is False
    assert receipt.capability_grant_authorized is False
    assert receipt.external_effects_authorized is False
    assert adapter.pending_dispatches() == ()
    assert runtime.preflight_calls == 5
    assert runtime.admit_calls == runtime.propose_calls == 1


def test_not_due_and_held_lease_do_not_touch_network(tmp_path: Path) -> None:
    later = NOW + timedelta(seconds=1)
    service, runtime, adapter = _service(tmp_path, now=later)
    service.reschedule(next_wake_at=NOW + timedelta(minutes=5))

    not_due = service.run_due_once(worker_id="worker-1")
    assert not_due.disposition is ActivePerceptionDisposition.NOT_DUE
    assert runtime.preflight_calls == 0
    assert adapter.feed_cursor is None

    service.reschedule(next_wake_at=NOW)
    assert (
        service.store.acquire_due_lease(
            service.config,
            worker_id="other-worker",
            now=later,
        )
        is not None
    )
    held = service.run_due_once(worker_id="worker-1")
    assert held.disposition is ActivePerceptionDisposition.LEASE_HELD
    assert runtime.preflight_calls == 0
    assert adapter.feed_cursor is None


def test_revocation_is_checked_before_network(tmp_path: Path) -> None:
    runtime = _Runtime()
    runtime.revoked = True
    service, _, adapter = _service(tmp_path, runtime=runtime)

    with pytest.raises(RuntimeError, match="revoked"):
        service.run_due_once(worker_id="worker-1")

    assert adapter.feed_cursor is None
    assert runtime.admit_calls == runtime.propose_calls == 0


def test_wake_and_query_budgets_fail_closed_until_next_window(tmp_path: Path) -> None:
    service, runtime, _ = _service(tmp_path, wake_budget=1, query_budget=1)
    first = service.run_due_once(worker_id="worker-1")
    assert first.disposition is ActivePerceptionDisposition.COMPLETED
    service.reschedule(next_wake_at=NOW)

    second = service.run_due_once(worker_id="worker-2")

    assert second.disposition is ActivePerceptionDisposition.BUDGET_EXHAUSTED
    assert runtime.preflight_calls == 5


def test_restart_drains_pending_before_network_and_does_not_reassess_completed(
    tmp_path: Path,
) -> None:
    report_database = tmp_path / "runtime.sqlite3"
    first_adapter = _feed_adapter(report_database)
    first_adapter.poll_once(limit=1)
    runtime = _Runtime()
    service, _, _ = _service(tmp_path, adapter=first_adapter, runtime=runtime)

    drained = service.run_due_once(worker_id="worker-1")
    assert drained.proposal_count == 1
    assert runtime.propose_calls == 1

    restarted_adapter = _feed_adapter(report_database)
    restarted_service, _, _ = _service(
        tmp_path,
        now=NOW + timedelta(minutes=1),
        adapter=restarted_adapter,
        runtime=runtime,
    )
    restarted_service.reschedule(next_wake_at=NOW + timedelta(hours=1))
    replay = restarted_service.run_due_once(worker_id="worker-2")

    assert replay.disposition is ActivePerceptionDisposition.NOT_DUE
    assert runtime.propose_calls == 1


def test_schedule_row_tamper_fails_closed(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    with sqlite3.connect(tmp_path / "runtime.sqlite3") as connection:
        connection.execute(
            "UPDATE mandate_active_perception_schedule SET tenant_id = ?",
            ("tenant:attacker",),
        )

    with pytest.raises(RuntimeError, match="schedule"):
        service.run_due_once(worker_id="worker-1")


def test_stale_worker_fence_cannot_finish_after_takeover(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    first = service.store.acquire_due_lease(
        service.config,
        worker_id="worker-1",
        now=NOW,
    )
    assert not isinstance(first, ActivePerceptionDisposition)
    second = service.store.acquire_due_lease(
        service.config,
        worker_id="worker-2",
        now=NOW + timedelta(seconds=31),
    )
    assert not isinstance(second, ActivePerceptionDisposition)

    with pytest.raises(RuntimeError, match="fence"):
        service.store.finish(
            service.config,
            first,
            next_wake_at=NOW + timedelta(minutes=5),
        )


def test_query_budget_is_debited_before_transport_and_not_refunded(
    tmp_path: Path,
) -> None:
    schedule_database = tmp_path / "runtime.sqlite3"

    def fail_after_debit(_: object) -> DataAgentReportHttpResponse:
        with sqlite3.connect(schedule_database) as connection:
            query_used = connection.execute(
                "SELECT query_used FROM mandate_active_perception_schedule"
            ).fetchone()
        assert query_used == (1,)
        raise RuntimeError("network failed")

    config = _config(
        credential=_credential(
            scopes=(
                "reports:read",
                "report-events:read",
                "data-agent-origin:http://127.0.0.1:8765",
                "data-agent-tenant:data-tenant-1",
            )
        )
    )
    adapter = DataAgentReportAdapter(
        config,
        credential_broker=_CredentialBroker(),
        transport=_Transport(fail_after_debit),
        state_store=SQLiteDataAgentReportStateStore(schedule_database),
        clock=lambda: NOW,
    )
    service, _, _ = _service(tmp_path, adapter=adapter)

    with pytest.raises(DataAgentReportAdapterError):
        service.run_due_once(worker_id="worker-1")

    with sqlite3.connect(schedule_database) as connection:
        row = connection.execute(
            "SELECT wake_used, query_used FROM mandate_active_perception_schedule"
        ).fetchone()
    assert row == (1, 1)


def test_authority_change_after_fetch_fails_before_admit(tmp_path: Path) -> None:
    runtime = _Runtime()
    cursor = "cursor-1"
    response = _response(
        _feed_bytes([_feed_event(cursor)], next_cursor=cursor),
        final_url="http://127.0.0.1:8765/external/report-events?limit=1",
    )

    def change_authority(_: object) -> DataAgentReportHttpResponse:
        runtime.authority_digest = "b" * 64
        return response

    adapter = DataAgentReportAdapter(
        _config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        credential_broker=_CredentialBroker(),
        transport=_Transport(change_authority),
        state_store=SQLiteDataAgentReportStateStore(tmp_path / "runtime.sqlite3"),
        clock=lambda: NOW,
    )
    service, _, _ = _service(tmp_path, adapter=adapter, runtime=runtime)

    with pytest.raises(RuntimeError, match="changed"):
        service.run_due_once(worker_id="worker-1")

    assert runtime.admit_calls == runtime.propose_calls == 0
    assert len(adapter.pending_dispatches()) == 1


def test_authority_change_after_admit_fails_before_propose(tmp_path: Path) -> None:
    runtime = _Runtime()
    runtime.change_after_admit = True
    service, _, adapter = _service(tmp_path, runtime=runtime)

    with pytest.raises(RuntimeError, match="changed"):
        service.run_due_once(worker_id="worker-1")

    assert runtime.admit_calls == 1
    assert runtime.propose_calls == 0
    assert len(adapter.pending_dispatches()) == 1


def test_authority_change_after_propose_fails_before_dispatch_completion(
    tmp_path: Path,
) -> None:
    service, runtime, adapter = _service(tmp_path)
    runtime.change_after_propose = True

    with pytest.raises(RuntimeError, match="authority changed"):
        service.run_due_once(worker_id="worker-1")

    assert runtime.propose_calls == 1
    assert len(adapter.pending_dispatches()) == 1
    assert adapter.completed_dispatch(adapter.pending_dispatches()[0].dispatch_id) is None


def test_pending_outbox_drains_when_next_wake_is_future_without_network(
    tmp_path: Path,
) -> None:
    report_database = tmp_path / "runtime.sqlite3"
    adapter = _feed_adapter(report_database)
    adapter.poll_once(limit=1)
    restarted, _, transport = _adapter(
        config=_config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    service, runtime, _ = _service(tmp_path, adapter=restarted)
    service.reschedule(next_wake_at=NOW + timedelta(hours=1))

    receipt = service.run_due_once(worker_id="worker-1")

    assert receipt.disposition is ActivePerceptionDisposition.COMPLETED
    assert receipt.observed_count == 0
    assert receipt.proposal_count == 1
    assert transport.requests == []
    assert runtime.propose_calls == 1
    with sqlite3.connect(tmp_path / "runtime.sqlite3") as connection:
        assert connection.execute(
            "SELECT query_used FROM mandate_active_perception_schedule"
        ).fetchone() == (0,)


def test_cross_tenant_same_ids_cannot_complete_foreign_dispatch(tmp_path: Path) -> None:
    database = tmp_path / "reports.sqlite3"
    owner = _feed_adapter(database)
    owner.poll_once(limit=1)
    foreign_credential = _credential(
        owner_principal_id="user:other",
        tenant_id="tenant:other",
        workspace_id="workspace:other",
        scopes=(
            "reports:read",
            "report-events:read",
            "data-agent-origin:http://127.0.0.1:8765",
            "data-agent-tenant:data-tenant-1",
        ),
    )
    foreign = DataAgentReportAdapter(
        _config(
            credential=foreign_credential,
            principal_id="user:other",
            target_tenant_id="tenant:other",
            target_workspace_id="workspace:other",
        ),
        credential_broker=_CredentialBroker(),
        transport=_Transport(_response()),
        state_store=SQLiteDataAgentReportStateStore(database),
        clock=lambda: NOW,
    )
    dispatch = owner.pending_dispatches()[0]

    with pytest.raises(DataAgentReportAdapterError, match="scope"):
        foreign.complete_dispatch(
            dispatch,
            outcome_record=_outcome_record(owner, dispatch),
            completed_at=NOW,
            consumer_id="worker-foreign",
            authority_snapshot_digest="a" * 64,
        )


def test_feed_rejects_cycle_through_non_tail_cursor_history(tmp_path: Path) -> None:
    database = tmp_path / "reports.sqlite3"
    first_report = _feed_event("cursor-1")
    second_report = _feed_event("cursor-2")
    pages = [
        _response(
            _feed_bytes([first_report, second_report], next_cursor="cursor-2"),
            final_url="http://127.0.0.1:8765/external/report-events?limit=2",
        ),
        _response(
            _feed_bytes([first_report], next_cursor="cursor-1"),
            final_url=(
                "http://127.0.0.1:8765/external/report-events?after=cursor-2&limit=2"
            ),
        ),
    ]

    def next_page(_: object) -> DataAgentReportHttpResponse:
        return pages.pop(0)

    adapter, _, _ = _adapter(
        response=pages[0],
        config=_config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        state_store=SQLiteDataAgentReportStateStore(database),
    )
    adapter._transport = _Transport(next_page)
    adapter.poll_once(limit=2)

    with pytest.raises(DataAgentReportAdapterError, match="cursor"):
        adapter.poll_once(limit=2)


def test_application_entrypoint_creates_no_task_or_effect(tmp_path: Path) -> None:
    service, runtime, _ = _service(tmp_path)
    application = AgentOSApplication(
        database=tmp_path / "application.sqlite3",
        workspace=tmp_path,
    )
    application._mandate_active_perception_service = service
    before = application.store.list_task_ids()

    receipt = application.run_active_perception_once(worker_id="worker-1")

    assert receipt.disposition is ActivePerceptionDisposition.COMPLETED
    assert application.store.list_task_ids() == before == ()
    assert runtime.propose_calls == 1
    assert receipt.activation_authorized is False
    assert receipt.capability_grant_authorized is False
    assert receipt.external_effects_authorized is False
    application.store.close()


def test_cli_perception_once_runs_once_and_exits_without_serve(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path)
    application = AgentOSApplication(
        database=tmp_path / "application.sqlite3",
        workspace=tmp_path,
    )
    application._mandate_active_perception_service = service
    monkeypatch.setattr(
        api_main.situated_startup,
        "_build_data_agent_situated_application",
        lambda **kwargs: application,
    )
    monkeypatch.setattr(
        api_main,
        "serve",
        lambda *args, **kwargs: pytest.fail("one-shot CLI must not serve"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os-api",
            "--data-agent-situated-config",
            str(tmp_path / "config.json"),
            "--perception-once",
            "--perception-worker-id",
            "worker-cli",
        ],
    )

    api_main.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["disposition"] == "COMPLETED"
    assert payload["worker_id"] == "worker-cli"
    assert payload["activation_authorized"] is False
