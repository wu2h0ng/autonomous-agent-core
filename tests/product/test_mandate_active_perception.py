from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import content_digest
from apps.api_server.data_agent_report_adapter import (
    DataAgentReportAdapter,
    DataAgentReportAdapterError,
    DataAgentReportHttpResponse,
    SQLiteDataAgentReportStateStore,
)
from apps.api_server.mandate_active_perception import (
    ActivePerceptionDisposition,
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
)


def _feed_adapter(database: Path, *, cursor: str = "cursor-1") -> DataAgentReportAdapter:
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
    )
    return adapter


def test_poll_commits_pending_dispatch_and_cursor_atomically(tmp_path: Path) -> None:
    database = tmp_path / "reports.sqlite3"
    adapter = _feed_adapter(database)

    result = adapter.poll_once(limit=1)
    pending = adapter.pending_dispatches()

    assert adapter.feed_cursor == "cursor-1"
    assert len(result.bundles) == len(pending) == 1
    assert pending[0].environment_event_id == result.bundles[0].event.environment_event_id
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
        outcome_kind="TASK_DRAFT",
        outcome_digest="d" * 64,
        completed_at=NOW,
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


class _Runtime:
    def __init__(self) -> None:
        self.preflight_calls = 0
        self.admit_calls = 0
        self.propose_calls = 0
        self.revoked = False

    def assert_observation_authority(self) -> None:
        self.preflight_calls += 1
        if self.revoked:
            raise RuntimeError("observation authority revoked")

    def admit_event(self, event_id: str) -> Any:
        self.admit_calls += 1
        return type("Receipt", (), {"receipt_id": f"receipt:{event_id}"})()

    def propose(self, event_id: str, projection_id: str, receipt_id: str) -> None:
        del event_id, projection_id, receipt_id
        self.propose_calls += 1
        return None


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
    reports = adapter or _feed_adapter(tmp_path / "reports.sqlite3")
    situated = runtime or _Runtime()
    store = SQLiteMandateActivePerceptionStore(tmp_path / "perception.sqlite3")
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
    assert runtime.preflight_calls == runtime.admit_calls == runtime.propose_calls == 1


def test_not_due_and_held_lease_do_not_touch_network(tmp_path: Path) -> None:
    later = NOW + timedelta(seconds=1)
    service, runtime, adapter = _service(tmp_path, now=later)
    service.reschedule(next_wake_at=NOW + timedelta(minutes=5))

    not_due = service.run_due_once(worker_id="worker-1")
    assert not_due.disposition is ActivePerceptionDisposition.NOT_DUE
    assert runtime.preflight_calls == 0
    assert adapter.feed_cursor is None

    service.reschedule(next_wake_at=NOW)
    assert service.store.acquire_due_lease(
        service.config,
        worker_id="other-worker",
        now=later,
    ) is not None
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
    assert runtime.preflight_calls == 1


def test_restart_drains_pending_before_network_and_does_not_reassess_completed(
    tmp_path: Path,
) -> None:
    report_database = tmp_path / "reports.sqlite3"
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
    with sqlite3.connect(tmp_path / "perception.sqlite3") as connection:
        connection.execute(
            "UPDATE mandate_active_perception_schedule SET tenant_id = ?",
            ("tenant:attacker",),
        )

    with pytest.raises(RuntimeError, match="schedule"):
        service.run_due_once(worker_id="worker-1")

