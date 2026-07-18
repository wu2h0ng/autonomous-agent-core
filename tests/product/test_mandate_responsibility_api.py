from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from http.client import HTTPMessage
from http.server import ThreadingHTTPServer
from typing import Iterator

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler, _decode_path_segment
from agent_os_contracts import (
    Goal,
    MandateObservationAuthorizationCommand,
    MandateOperationalStatus,
    MandateTaskLinkCommand,
    MandateWorkspaceRecord,
    PrincipalRole,
    RatifiedMandateRef,
    canonical_json,
)
from agent_os_core import SQLiteMandateObservationAuthorizationStore
from tests.product.test_mandate_responsibility_store import NOW, _setup
from tests.product.test_mandate_observation_authorization import (
    _command,
    _descriptor,
    _principal,
)
from tests.product.test_mandate_workspace_api import _payload


MANDATE_ID = "mandate:build-agent-os"
ADMIN_TOKEN = "responsibility-admin"


@contextmanager
def _server(
    owner: AgentOSApplication,
    applications: dict[str, AgentOSApplication],
) -> Iterator[str]:
    handler = type(
        "MandateResponsibilityHandler",
        (Handler,),
        {"application": owner, "admin_applications": applications},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    token: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, object], HTTPMessage]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
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
            value = json.loads(response.read())
            return response.status, value, response.headers
    except urllib.error.HTTPError as exc:
        value = json.loads(exc.read())
        return exc.code, value, exc.headers


def _link_path() -> str:
    return f"/v1/mandates/{MANDATE_ID}/task-links"


def _view_path() -> str:
    return f"/v1/mandates/{MANDATE_ID}/responsibility-view"


def _install_operational_authority(
    app: AgentOSApplication,
    record: MandateWorkspaceRecord,
) -> None:
    admin = _principal("principal:security", role=PrincipalRole.TENANT_ADMIN)
    operational, _ = SQLiteMandateObservationAuthorizationStore._project(
        record,
        MandateObservationAuthorizationCommand.model_validate(_command()),
        _descriptor(),
        admin,
        NOW,
    )
    connection = app.store._db
    connection.execute(
        """
        CREATE TABLE situated_mandates (
            principal_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            mandate_id TEXT NOT NULL,
            mandate_version INTEGER NOT NULL,
            mandate_digest TEXT NOT NULL,
            status TEXT NOT NULL,
            correction_epoch INTEGER NOT NULL,
            mandate_json TEXT NOT NULL,
            PRIMARY KEY (principal_id, tenant_id, workspace_id, mandate_id)
        )
        """
    )
    connection.execute(
        "INSERT INTO situated_mandates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            operational.owner_principal_id,
            operational.tenant_id,
            operational.workspace_id,
            operational.mandate_id,
            operational.version,
            operational.mandate_digest,
            operational.status.value,
            operational.correction_epoch,
            canonical_json(operational),
        ),
    )
    connection.commit()


def test_default_memory_app_joins_canonical_stores_without_disk_or_cross_app_leak(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    first = AgentOSApplication(
        database=":memory:", workspace=tmp_path, clock=lambda: NOW
    )
    assert not (tmp_path / ":memory:").exists()

    record = MandateWorkspaceRecord.model_validate(
        first.create_mandate_workspace_record(
            _payload(expires_at=NOW.replace(year=2027))
        )
    )
    _install_operational_authority(first, record)
    task = first.create_task(
        Goal(
            goal_id="goal:memory-responsibility",
            tenant_id=first.principal.tenant_id,
            workspace_id=first.principal.workspace_id,
            created_by=first.principal.principal_id,
            created_at=NOW,
            statement="Prove canonical in-memory responsibility joins",
        ).model_dump(mode="json")
    )
    link = first.mandate_responsibility_store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        MANDATE_ID,
        _principal("principal:security", role=PrincipalRole.TENANT_ADMIN),
    )

    view = first.mandate_responsibility_view(MANDATE_ID)
    assert view["items"][0]["link"]["link_id"] == link.link_id
    assert view["items"][0]["link"]["task_id"] == task.task_id

    second = AgentOSApplication(
        database=":memory:", workspace=tmp_path, clock=lambda: NOW
    )
    assert second.list_tasks() == []
    assert second.list_mandate_workspace_records() == []
    second_link_count = second.store._db.execute(
        "SELECT COUNT(*) FROM mandate_responsibility_links"
    ).fetchone()
    assert second_link_count is not None
    assert second_link_count[0] == 0
    assert not (tmp_path / ":memory:").exists()


def test_admin_link_and_revoke_use_domain_replay_not_http_cache(tmp_path) -> None:
    _, owner, admin, task, _ = _setup(tmp_path)
    path = _link_path()
    poisoned = {"poisoned": True}
    owner.store.put_idempotency(path, "shared-http-key", poisoned, NOW.isoformat())

    with _server(owner, {ADMIN_TOKEN: admin}) as base:
        first_status, first, _ = _request(
            base,
            path,
            method="POST",
            body={"task_id": task.task_id, "reason": "visible responsibility"},
            token=ADMIN_TOKEN,
            idempotency_key="shared-http-key",
        )
        replay_status, replay, _ = _request(
            base,
            path,
            method="POST",
            body={"task_id": task.task_id, "reason": "visible responsibility"},
            token=ADMIN_TOKEN,
            idempotency_key="different-http-key",
        )

        assert (first_status, replay_status) == (201, 201)
        assert first == replay
        assert first != poisoned

        revoke_path = f"{path}/{first['link_id']}:revoke"
        owner.store.put_idempotency(
            revoke_path,
            "revoke-http-key",
            poisoned,
            NOW.isoformat(),
        )
        revoke_body = {
            "expected_link_digest": first["record_digest"],
            "reason": "responsibility moved",
        }
        revoked_status, revoked, _ = _request(
            base,
            revoke_path,
            method="POST",
            body=revoke_body,
            token=ADMIN_TOKEN,
            idempotency_key="revoke-http-key",
        )
        replay_revoke_status, replay_revoked, _ = _request(
            base,
            revoke_path,
            method="POST",
            body=revoke_body,
            token=ADMIN_TOKEN,
            idempotency_key="different-revoke-key",
        )

        assert (revoked_status, replay_revoke_status) == (201, 201)
        assert revoked == replay_revoked
        assert revoked != poisoned


def test_link_writes_require_authenticated_admin_and_reject_server_fields(
    tmp_path,
) -> None:
    _, owner, admin, task, _ = _setup(tmp_path)
    path = _link_path()
    with _server(owner, {ADMIN_TOKEN: admin, "owner-token": owner}) as base:
        missing_status, _, _ = _request(
            base, path, method="POST", body={"task_id": task.task_id}
        )
        invalid_status, _, _ = _request(
            base,
            path,
            method="POST",
            body={"task_id": task.task_id},
            token="invalid",
        )
        owner_status, owner_error, _ = _request(
            base,
            path,
            method="POST",
            body={"task_id": task.task_id},
            token="owner-token",
        )
        forged_status, forged_error, _ = _request(
            base,
            path,
            method="POST",
            body={"task_id": task.task_id, "principal_id": "principal:attacker"},
            token=ADMIN_TOKEN,
        )

    assert (missing_status, invalid_status) == (401, 401)
    assert owner_status == 403
    assert owner_error["error"] == "MandateResponsibilityDenied"
    assert forged_status == 400
    assert forged_error["error"] == "ValidationError"


def test_responsibility_error_types_map_to_400_403_404_409(tmp_path) -> None:
    _, owner, admin, task, _ = _setup(tmp_path)
    path = _link_path()
    with _server(owner, {ADMIN_TOKEN: admin, "owner-token": owner}) as base:
        bad_status, _, _ = _request(
            base,
            path,
            method="POST",
            body={"task_id": ""},
            token=ADMIN_TOKEN,
        )
        denied_status, _, _ = _request(
            base,
            path,
            method="POST",
            body={"task_id": task.task_id},
            token="owner-token",
        )
        missing_status, _, _ = _request(
            base,
            path,
            method="POST",
            body={"task_id": "task:missing"},
            token=ADMIN_TOKEN,
        )
        created_status, _, _ = _request(
            base,
            path,
            method="POST",
            body={"task_id": task.task_id, "reason": "first"},
            token=ADMIN_TOKEN,
        )
        conflict_status, conflict, _ = _request(
            base,
            path,
            method="POST",
            body={"task_id": task.task_id, "reason": "changed"},
            token=ADMIN_TOKEN,
        )

    assert (bad_status, denied_status, missing_status, created_status) == (
        400,
        403,
        404,
        201,
    )
    assert conflict_status == 409
    assert conflict["error"] == "MandateResponsibilityConflict"


def test_owner_and_admin_reads_are_scoped_and_no_store(tmp_path) -> None:
    _, owner, admin, task, _ = _setup(tmp_path)
    path = _link_path()
    with _server(owner, {ADMIN_TOKEN: admin}) as base:
        _, link, _ = _request(
            base,
            path,
            method="POST",
            body={"task_id": task.task_id},
            token=ADMIN_TOKEN,
        )
        owner_status, owner_links, owner_headers = _request(base, path)
        admin_status, admin_links, admin_headers = _request(
            base, path, token=ADMIN_TOKEN
        )
        view_status, view, view_headers = _request(base, _view_path())

    assert (owner_status, admin_status, view_status) == (200, 200, 200)
    assert owner_links == admin_links == {"task_links": [link]}
    assert view["mandate_id"] == MANDATE_ID
    assert view["items"][0]["link"] == link
    assert owner_headers["Cache-Control"] == "no-store"
    assert admin_headers["Cache-Control"] == "no-store"
    assert view_headers["Cache-Control"] == "no-store"


def test_bad_linked_task_stays_visible_as_partial_unknown(tmp_path) -> None:
    database, owner, admin, task, _ = _setup(tmp_path)
    with _server(owner, {ADMIN_TOKEN: admin}) as base:
        _, link, _ = _request(
            base,
            _link_path(),
            method="POST",
            body={"task_id": task.task_id},
            token=ADMIN_TOKEN,
        )
        with sqlite3.connect(database) as connection:
            connection.execute("DELETE FROM task_events WHERE task_id = ?", (task.task_id,))
        status, view, headers = _request(base, _view_path())

    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert view["status"] == "PARTIAL_UNKNOWN"
    assert view["items"][0]["link"]["link_id"] == link["link_id"]
    assert view["items"][0]["state"] == "UNKNOWN"
    assert "TASK_SOURCE_MISSING" in view["items"][0]["attention_reasons"]


def test_revoked_mandate_returns_read_only_banner_state(tmp_path) -> None:
    database, owner, admin, task, _ = _setup(tmp_path)
    with _server(owner, {ADMIN_TOKEN: admin}) as base:
        _request(
            base,
            _link_path(),
            method="POST",
            body={"task_id": task.task_id},
            token=ADMIN_TOKEN,
        )
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                "SELECT mandate_json FROM situated_mandates"
            ).fetchone()
            assert row is not None
            operational = RatifiedMandateRef.model_validate_json(row[0])
            revoked = operational.model_copy(
                update={"status": MandateOperationalStatus.REVOKED}
            )
            connection.execute(
                "UPDATE situated_mandates SET status = ?, mandate_json = ?",
                (revoked.status.value, canonical_json(revoked)),
            )
        status, view, _ = _request(base, _view_path())

    assert status == 200
    assert view["mandate_status"] == "REVOKED"
    assert view["status"] == "REVOKED"


def test_percent_encoded_space_and_at_mandate_id_round_trips_all_routes(
    tmp_path,
) -> None:
    _, owner, admin, task, _ = _setup(tmp_path)
    mandate_id = "mandate:Ops @ 2026"
    payload = _payload(expires_at=NOW.replace(year=2027))
    payload["mandate_id"] = mandate_id
    owner.create_mandate_workspace_record(payload)
    admin.authorize_mandate_observation_binding(
        mandate_id,
        _command(authorization_id="observation-auth:ops-at-2026"),
    )
    encoded = urllib.parse.quote(mandate_id, safe="")
    path = f"/v1/mandates/{encoded}/task-links"

    with _server(owner, {ADMIN_TOKEN: admin}) as base:
        create_status, link, _ = _request(
            base,
            path,
            method="POST",
            body={"task_id": task.task_id},
            token=ADMIN_TOKEN,
        )
        list_status, listed, _ = _request(base, path)
        view_status, view, _ = _request(
            base,
            f"/v1/mandates/{encoded}/responsibility-view",
        )
        revoke_status, revoked, _ = _request(
            base,
            f"{path}/{urllib.parse.quote(str(link['link_id']), safe='')}:revoke",
            method="POST",
            body={
                "expected_link_digest": link["record_digest"],
                "reason": "done",
            },
            token=ADMIN_TOKEN,
        )

    assert (create_status, list_status, view_status, revoke_status) == (
        201,
        200,
        200,
        201,
    )
    assert listed == {"task_links": [link]}
    assert view["mandate_id"] == mandate_id
    assert revoked["link_id"] == link["link_id"]


def test_mandate_routes_reject_unsafe_or_ambiguous_encoded_segments(
    tmp_path,
) -> None:
    _, owner, admin, _, _ = _setup(tmp_path)
    unsafe_segments = (
        "",
        "mandate%2Fescape",
        "mandate%5Cescape",
        "mandate\\escape",
        "mandate%00escape",
        "mandate%1Fescape",
        "mandate%7Fescape",
        "mandate%C2%80escape",
        "mandate%2",
        "mandate%GG",
        "mandate%252Fescape",
        "mandate%255Cescape",
    )

    with _server(owner, {ADMIN_TOKEN: admin}) as base:
        statuses = [
            _request(
                base,
                f"/v1/mandates/{segment}/responsibility-view",
            )[0]
            for segment in unsafe_segments
        ]

    assert all(_decode_path_segment(segment) is None for segment in unsafe_segments)
    assert statuses == [404] * len(unsafe_segments)
