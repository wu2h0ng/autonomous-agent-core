from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from agent_os_contracts import (
    MandateStatus,
    MandateWorkspaceRecord,
    PrincipalIdentity,
    PrincipalRole,
    content_digest,
)


def _payload(*, expires_at: datetime | None = None) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "mandate_id": "mandate:build-agent-os",
        "mission_statement": "持续构建真正的通用自主 Agent OS",
        "desired_outcomes": ["减少 Founder 隐藏认知劳动"],
        "permanent_constraints": ["C7 不可由系统写入或绕过"],
        "authority_envelope": {
            "allowed_task_classes": ["repository-research", "repository-development"],
            "allowed_effect_classes": ["workspace.read", "workspace.patch"],
            "allowed_resource_refs": ["workspace:local"],
            "capability_grant_rules": ["typed-capability-only"],
            "wake_budget_per_window": 16,
            "query_budget_per_window": 64,
            "help_budget": {
                "max_requests_per_window": 8,
                "max_operator_minutes_per_window": 30,
                "max_repeated_question_rate": 0.25,
                "max_unresolved_wait_seconds": 86400,
                "window_seconds": 3600,
            },
            "max_concurrent_tasks": 4,
            "max_duration_seconds": 86400,
            "evaluation_principles": [
                {
                    "principle_id": "principle:verified-outcome",
                    "statement": "结果必须由独立证据验证",
                    "weight": 1.0,
                }
            ],
            "escalation_conditions": ["权限扩张", "重大不可逆行动"],
        },
        "environment_binding_classes": ["git-workspace", "project-state"],
        "time_horizon": "ongoing",
        "review_cadence_seconds": 3600,
        "expires_at": (expires_at or now + timedelta(days=30)).isoformat(),
        "revocation_conditions": ["Founder revokes the Mandate"],
        "agent_instance_ref_id": "agent-instance:local-steward",
        "outcome_criteria_refs": ["criterion:founder-cognitive-load"],
        "principal_attestation": "local-founder-confirmation",
    }


def _request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, object]]:
    headers = {"Content-Type": "application/json"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_high_level_mandate_is_durable_without_activating_a_task(tmp_path) -> None:
    database = tmp_path / "agent-os.sqlite3"
    app = AgentOSApplication(database=database, workspace=tmp_path)
    handler = type("MandateWorkspaceHandler", (Handler,), {"application": app})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    payload = _payload()
    try:
        status, created = _request(
            base,
            "/v1/mandates",
            method="POST",
            body=payload,
        )
        assert status == 201
        record = MandateWorkspaceRecord.model_validate(created)
        assert record.mandate.status is MandateStatus.ACTIVE
        assert record.mandate.principal_id == "user:local"
        assert record.ratification_receipt.mandate_digest == content_digest(
            record.mandate
        )
        assert record.standing_mission.parent_mandate_digest == content_digest(
            record.mandate
        )
        assert record.standing_mission.ratification_receipt_digest == content_digest(
            record.ratification_receipt
        )
        assert record.task_activation_authorized is False
        assert record.capability_grant_authorized is False
        assert app.list_tasks() == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    restarted = AgentOSApplication(database=database, workspace=tmp_path)
    loaded = restarted.get_mandate_workspace_record("mandate:build-agent-os")
    loaded_record = MandateWorkspaceRecord.model_validate(loaded)
    assert loaded_record.mandate.mission_statement == _payload()["mission_statement"]
    assert restarted.list_tasks() == []


def test_http_lists_and_reads_only_the_bound_mandate_scope(tmp_path) -> None:
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    handler = type("MandateWorkspaceReadHandler", (Handler,), {"application": app})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    payload = _payload()
    try:
        create_status, created = _request(
            base,
            "/v1/mandates",
            method="POST",
            body=payload,
        )
        list_status, listed = _request(base, "/v1/mandates")
        detail_status, detail = _request(
            base, "/v1/mandates/mandate:build-agent-os"
        )

        assert create_status == 201
        assert list_status == 200
        assert listed == {"mandates": [created]}
        assert detail_status == 200
        assert detail == created
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_expired_mandate_is_rejected_without_persistence(tmp_path) -> None:
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    payload = _payload(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))

    try:
        app.create_mandate_workspace_record(payload)
    except ValueError as exc:
        assert "expired" in str(exc).lower()
    else:
        raise AssertionError("expired Mandate must fail closed")

    assert app.list_mandate_workspace_records() == []


def test_client_cannot_supply_principal_or_scope(tmp_path) -> None:
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)

    for field, value in (
        ("principal_id", "user:attacker"),
        ("tenant_id", "tenant:attacker"),
        ("workspace_id", "workspace:attacker"),
    ):
        payload = _payload()
        payload[field] = value
        try:
            app.create_mandate_workspace_record(payload)
        except ValueError:
            pass
        else:
            raise AssertionError(f"client-supplied {field} must be rejected")

    assert app.list_mandate_workspace_records() == []


def test_exact_replay_is_idempotent_and_conflicting_same_id_is_rejected(tmp_path) -> None:
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    payload = _payload()

    first = app.create_mandate_workspace_record(payload)
    replay = app.create_mandate_workspace_record(payload)
    assert replay == first
    assert app.list_mandate_workspace_records() == [first]

    conflicting = _payload()
    conflicting["mission_statement"] = "替换权威使命"
    try:
        app.create_mandate_workspace_record(conflicting)
    except Exception as exc:
        assert type(exc).__name__ == "MandateWorkspaceConflict"
    else:
        raise AssertionError("same Mandate id with different content must conflict")

    assert app.get_mandate_workspace_record("mandate:build-agent-os") == first


def test_http_idempotency_cache_cannot_hide_a_conflicting_mandate(tmp_path) -> None:
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    handler = type("MandateWorkspaceConflictHandler", (Handler,), {"application": app})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    payload = _payload()
    try:
        first_status, first = _request(
            base,
            "/v1/mandates",
            method="POST",
            body=payload,
            idempotency_key="same-http-key",
        )
        replay_status, replay = _request(
            base,
            "/v1/mandates",
            method="POST",
            body=payload,
            idempotency_key="same-http-key",
        )
        conflicting = dict(payload)
        conflicting["mission_statement"] = "替换权威使命"
        conflict_status, conflict = _request(
            base,
            "/v1/mandates",
            method="POST",
            body=conflicting,
            idempotency_key="same-http-key",
        )

        assert first_status == 201
        assert replay_status == 201
        assert replay == first
        assert conflict_status == 409
        assert conflict["error"] == "MandateWorkspaceConflict"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mandate_workspace_is_tenant_and_workspace_isolated(tmp_path) -> None:
    database = tmp_path / "agent-os.sqlite3"
    now = datetime.now(timezone.utc)
    owner = AgentOSApplication(database=database, workspace=tmp_path)
    other = AgentOSApplication(
        database=database,
        workspace=tmp_path,
        principal=PrincipalIdentity(
            principal_id="user:other",
            tenant_id="tenant:other",
            workspace_id="workspace:other",
            role=PrincipalRole.PRINCIPAL,
            authenticated_at=now,
        ),
    )
    owner_record = owner.create_mandate_workspace_record(_payload())

    assert other.list_mandate_workspace_records() == []
    try:
        other.get_mandate_workspace_record("mandate:build-agent-os")
    except Exception as exc:
        assert type(exc).__name__ == "MandateWorkspaceNotFound"
    else:
        raise AssertionError("cross-tenant read must not reveal Mandate existence")

    other_record = other.create_mandate_workspace_record(_payload())
    assert (
        MandateWorkspaceRecord.model_validate(other_record).mandate.tenant_id
        == "tenant:other"
    )
    assert owner.get_mandate_workspace_record("mandate:build-agent-os") == owner_record


def test_durable_mandate_tampering_fails_closed(tmp_path) -> None:
    database = tmp_path / "agent-os.sqlite3"
    app = AgentOSApplication(database=database, workspace=tmp_path)
    record = app.create_mandate_workspace_record(_payload())
    tampered = json.loads(json.dumps(record))
    tampered["mandate"]["mission_statement"] = "attacker supplied mission"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE mandate_workspace_records SET record_json = ?
            WHERE tenant_id = ? AND workspace_id = ? AND mandate_id = ?
            """,
            (
                json.dumps(tampered),
                "tenant:local",
                "workspace:local",
                "mandate:build-agent-os",
            ),
        )

    restarted = AgentOSApplication(database=database, workspace=tmp_path)
    try:
        restarted.get_mandate_workspace_record("mandate:build-agent-os")
    except Exception as exc:
        assert type(exc).__name__ == "MandateWorkspacePersistenceConflict"
    else:
        raise AssertionError("tampered durable Mandate must fail closed")
