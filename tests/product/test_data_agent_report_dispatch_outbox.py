from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from agent_os_contracts import (
    RelevanceAssessment,
    RelevanceAssessorRef,
    RelevanceDisposition,
    RelevanceUrgency,
    SituatedAssessmentOutcomeKind,
    SituatedAssessmentRecord,
    content_digest,
)
from apps.api_server.data_agent_report_adapter import (
    DataAgentReportAdapter,
    DataAgentReportAdapterError,
    DataAgentReportDispatch,
    DataAgentReportHttpResponse,
    SQLiteDataAgentReportStateStore,
    _InMemoryDataAgentReportStateStore,
)
from tests.product.test_data_agent_external_report_adapter import (
    NOW,
    _adapter,
    _Broker,
    _config,
    _credential,
    _feed_bytes,
    _feed_event,
    _response,
    _Transport,
)


def _feed_adapter(
    database: Path, *, cursor: str = "cursor-1"
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
    )
    return adapter


def _outcome_record(
    adapter: DataAgentReportAdapter,
    dispatch: DataAgentReportDispatch,
) -> SituatedAssessmentRecord:
    event = adapter.resolve_event(dispatch.environment_event_id)
    projection = adapter.resolve_projection(dispatch.projection_id)
    assert event is not None and projection is not None
    source_binding_digest = "b" * 64
    assessment = RelevanceAssessment(
        assessment_id=f"assessment:{dispatch.dispatch_id}",
        environment_event_id=event.environment_event_id,
        event_observation_digest=event.observation.content_digest,
        projection_id=projection.projection_id,
        projection_digest=projection.projection_artifact.content_digest,
        mandate_id=event.mandate_id,
        mandate_version=1,
        mandate_digest="c" * 64,
        environment_binding_id=event.environment_binding_id,
        environment_binding_version=1,
        environment_binding_digest="e" * 64,
        correction_epoch=0,
        assessor=RelevanceAssessorRef(
            assessor_id="assessor:test", version=1, policy_digest="d" * 64
        ),
        input_binding_digest="e" * 64,
        tenant_id=event.tenant_id,
        workspace_id=event.workspace_id,
        disposition=RelevanceDisposition.IGNORE,
        uncertainty_summary="bounded test assessment",
        urgency=RelevanceUrgency.LOW,
        expected_loss_of_delay="none",
        attention_budget_seconds=1,
        rationale="no proposal required",
        evidence_ids=(event.observation.artifact_id,),
        assessed_at=NOW,
    )
    return SituatedAssessmentRecord(
        assessment_record_id=f"situated-assessment:{source_binding_digest}",
        source_binding_digest=source_binding_digest,
        tenant_id=event.tenant_id,
        workspace_id=event.workspace_id,
        assessment=assessment,
        outcome_kind=SituatedAssessmentOutcomeKind.NO_PROPOSAL,
        recorded_at=NOW,
    )


def test_feed_page_commits_pending_dispatch_cursor_and_history_atomically(
    tmp_path: Path,
) -> None:
    database = tmp_path / "reports.sqlite3"
    adapter = _feed_adapter(database)

    result = adapter.poll_once(limit=1)
    pending = adapter.pending_dispatches()

    assert adapter.feed_cursor == "cursor-1"
    assert len(result.bundles) == len(pending) == 1
    assert (
        pending[0].environment_event_id == result.bundles[0].event.environment_event_id
    )
    assert pending[0].status == "PENDING"
    assert pending[0].activation_authorized is False
    assert pending[0].external_effects_authorized is False


def test_outbox_failure_leaves_feed_observation_inert_and_cursor_unadvanced(
    tmp_path: Path,
) -> None:
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
    assert _feed_adapter(database).resolve_event(event_id) is None


def test_self_consistent_isolated_outbox_row_cannot_unlock_inert_feed_observation(
    tmp_path: Path,
) -> None:
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

    reference = _feed_adapter(tmp_path / "reference.sqlite3")
    result = reference.poll_once(limit=1)
    forged = reference.pending_dispatches()[0]
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER reject_dispatch")
        connection.execute(
            """
            INSERT INTO data_agent_report_dispatch_outbox (
                dispatch_id, dispatch_digest, namespace_digest, source_id,
                source_tenant_id, principal_id, tenant_id, workspace_id,
                mandate_id, environment_binding_id, environment_event_id,
                projection_id, bundle_digest, status, outcome_kind,
                outcome_digest, completed_at, consumer_id,
                authority_snapshot_digest, completion_digest,
                activation_authorized, capability_grant_authorized,
                external_effects_authorized
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING',
                      NULL, NULL, NULL, NULL, NULL, NULL, 0, 0, 0)
            """,
            (
                forged.dispatch_id,
                forged.dispatch_digest,
                forged.namespace_digest,
                forged.source_id,
                forged.source_tenant_id,
                forged.principal_id,
                forged.tenant_id,
                forged.workspace_id,
                forged.mandate_id,
                forged.environment_binding_id,
                forged.environment_event_id,
                forged.projection_id,
                forged.bundle_digest,
            ),
        )

    restarted = _feed_adapter(database)
    event_id = result.bundles[0].event.environment_event_id
    with pytest.raises(DataAgentReportAdapterError, match="page"):
        restarted.resolve_event(event_id)
    with pytest.raises(DataAgentReportAdapterError, match="page"):
        restarted.pending_dispatches()


def test_pending_survives_restart_and_completion_receipt_is_durable(
    tmp_path: Path,
) -> None:
    database = tmp_path / "reports.sqlite3"
    first = _feed_adapter(database)
    first.poll_once(limit=1)
    pending = first.pending_dispatches()[0]
    restarted = _feed_adapter(database)
    assert restarted.pending_dispatches() == (pending,)

    outcome_record = _outcome_record(restarted, pending)
    completed = restarted.complete_dispatch(
        pending,
        outcome_record=outcome_record,
        completed_at=NOW,
        consumer_id="worker-1",
        authority_snapshot_digest="a" * 64,
    )

    assert restarted.pending_dispatches() == ()
    assert completed.completion_digest is not None
    replay_adapter = _feed_adapter(database)
    with pytest.raises(DataAgentReportAdapterError, match="outcome record"):
        replay_adapter.completed_dispatch(pending.dispatch_id)
    assert (
        replay_adapter.completed_dispatch(
            pending.dispatch_id,
            outcome_resolver=lambda digest: (
                outcome_record if content_digest(outcome_record) == digest else None
            ),
        )
        == completed
    )


def test_completion_rejects_self_reported_outcome_without_durable_record(
    tmp_path: Path,
) -> None:
    database = tmp_path / "reports.sqlite3"
    adapter = _feed_adapter(database)
    adapter.poll_once(limit=1)
    dispatch = adapter.pending_dispatches()[0]

    with pytest.raises(DataAgentReportAdapterError, match="durable outcome"):
        adapter.complete_dispatch(
            dispatch,
            outcome_kind="NO_PROPOSAL",
            outcome_digest="d" * 64,
            completed_at=NOW,
            consumer_id="worker-1",
            authority_snapshot_digest="a" * 64,
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("tenant_id", "tenant:attacker"),
        ("projection_id", "projection:attacker"),
        ("dispatch_digest", "0" * 64),
    ],
)
def test_dispatch_tamper_fails_closed(tmp_path: Path, column: str, value: str) -> None:
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
    forged = replace(
        adapter.pending_dispatches()[0], projection_id="projection:missing"
    )
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


def test_recomputed_principal_tamper_cannot_unlock_pending_or_resolver(
    tmp_path: Path,
) -> None:
    database = tmp_path / "reports.sqlite3"
    adapter = _feed_adapter(database)
    result = adapter.poll_once(limit=1)
    forged = replace(adapter.pending_dispatches()[0], principal_id="principal:attacker")
    forged_digest = content_digest(
        SQLiteDataAgentReportStateStore._dispatch_payload(forged)
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE data_agent_report_dispatch_outbox
            SET dispatch_id = ?, dispatch_digest = ?, principal_id = ?
            """,
            (
                f"data-agent-dispatch:{forged_digest}",
                forged_digest,
                forged.principal_id,
            ),
        )

    with pytest.raises(DataAgentReportAdapterError, match="page|scope"):
        adapter.pending_dispatches()
    restarted = _feed_adapter(database)
    with pytest.raises(DataAgentReportAdapterError, match="page|scope"):
        restarted.resolve_event(result.bundles[0].event.environment_event_id)


def test_completion_receipt_tamper_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "reports.sqlite3"
    adapter = _feed_adapter(database)
    adapter.poll_once(limit=1)
    dispatch = adapter.pending_dispatches()[0]
    adapter.complete_dispatch(
        dispatch,
        outcome_record=_outcome_record(adapter, dispatch),
        completed_at=NOW,
        consumer_id="worker-1",
        authority_snapshot_digest="a" * 64,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE data_agent_report_dispatch_outbox SET completion_digest = ?",
            ("0" * 64,),
        )

    with pytest.raises(DataAgentReportAdapterError, match="dispatch"):
        adapter.completed_dispatch(dispatch.dispatch_id)


def test_in_memory_completion_replay_matches_sqlite_idempotency() -> None:
    cursor = "cursor-memory-1"
    adapter, _, _ = _adapter(
        response=_response(
            _feed_bytes([_feed_event(cursor)], next_cursor=cursor),
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
    kwargs = {
        "outcome_record": _outcome_record(adapter, dispatch),
        "completed_at": NOW,
        "consumer_id": "worker-1",
        "authority_snapshot_digest": "a" * 64,
    }

    first = adapter.complete_dispatch(dispatch, **kwargs)
    replay = adapter.complete_dispatch(dispatch, **kwargs)

    assert replay == first


def test_cross_tenant_same_ids_cannot_complete_foreign_dispatch(
    tmp_path: Path,
) -> None:
    database = tmp_path / "reports.sqlite3"
    owner = _feed_adapter(database)
    owner.poll_once(limit=1)
    credential = _credential(
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
            credential=credential,
            principal_id="user:other",
            target_tenant_id="tenant:other",
            target_workspace_id="workspace:other",
        ),
        credential_broker=_Broker(),
        transport=_Transport(_response()),
        state_store=SQLiteDataAgentReportStateStore(database),
        clock=lambda: NOW,
    )

    with pytest.raises(DataAgentReportAdapterError, match="scope"):
        foreign.complete_dispatch(
            owner.pending_dispatches()[0],
            outcome_record=_outcome_record(owner, owner.pending_dispatches()[0]),
            completed_at=NOW,
            consumer_id="worker-foreign",
            authority_snapshot_digest="a" * 64,
        )


def test_feed_rejects_cycle_through_non_tail_cursor_history(tmp_path: Path) -> None:
    database = tmp_path / "reports.sqlite3"
    first = _feed_event("cursor-1")
    second = _feed_event("cursor-2")
    pages = [
        _response(
            _feed_bytes([first, second], next_cursor="cursor-2"),
            final_url="http://127.0.0.1:8765/external/report-events?limit=2",
        ),
        _response(
            _feed_bytes([first], next_cursor="cursor-1"),
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
