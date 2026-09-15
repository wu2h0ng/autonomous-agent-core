"""Admin HTTP endpoints for mandate bootstrap/attach (Stage 2f-prep).

Admin HTTP endpoints for mandate setup (Stage 2f-prep). The terminal does not
implement governance/admin surfaces (founder option B); the Python CLI
`mandate-bootstrap` / `mandate-attach` are removed in Stage 2f.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest
from agent_os_contracts import (
    EnvironmentBindingAuthorization,
    RatifiedMandateRef,
    RelevanceAssessorRef,
)
from agent_os_core import DeterministicProvider
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler

def _now() -> datetime:
    return datetime.now(timezone.utc)
ADMIN_TOKEN = "mandate-admin"


def _mandate() -> RatifiedMandateRef:
    return RatifiedMandateRef(
        mandate_id="mandate:agent-os",
        version=1,
        mandate_digest="a" * 64,
        ratification_receipt_id="ratification:founder-1",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        owner_principal_id="user:local",
        ratified_by="user:local",
        ratified_at=_now() - timedelta(hours=1),
        valid_from=_now() - timedelta(hours=1),
        expires_at=_now() + timedelta(days=30),
        correction_epoch=0,
        authority_envelope_digest="b" * 64,
        allowed_environment_bindings=(
            EnvironmentBindingAuthorization(
                environment_binding_id="binding:local",
                version=1,
                binding_digest="c" * 64,
            ),
        ),
        relevance_assessor=RelevanceAssessorRef(
            assessor_id="assessor:bounded-v0",
            version=1,
            policy_digest="d" * 64,
        ),
    )


def _app(root: Path, database: Path) -> AgentOSApplication:
    app = AgentOSApplication(database=database, workspace=root)
    app.provider = DeterministicProvider(
        scripted=(("hi", ()),), invocation_binding=app.provider.invocation_binding
    )
    app.provider_configured = True
    return app


@pytest.fixture
def admin_server(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    owner_root = tmp_path / "owner"
    owner_root.mkdir()
    admin_root = tmp_path / "admin"
    admin_root.mkdir()
    admin_database = admin_root / "admin.sqlite3"
    owner = _app(owner_root, owner_root / "owner.sqlite3")
    admin = _app(admin_root, admin_database)
    handler = type(
        "MandateBootstrapHandler",
        (Handler,),
        {"application": owner, "admin_applications": {ADMIN_TOKEN: admin}},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", admin_database
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(
    base: str, path: str, *, body: dict[str, object], token: str | None
) -> tuple[int, dict[str, object]]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        base + path, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_bootstrap_then_attach(admin_server: tuple[str, Path]) -> None:
    base, admin_database = admin_server
    mandates = _mandate()
    status, boot = _request(
        base,
        "/v1/mandates:bootstrap",
        body=mandates.model_dump(mode="json"),
        token=ADMIN_TOKEN,
    )
    assert status == 201, boot
    assert boot["mandate_id"] == "mandate:agent-os"
    assert boot["status"] == "ACTIVE"

    # The mandate must land in the ADMIN database (not the owner's).
    store = SQLiteSituatedAssessmentStore(admin_database)
    resolved, _ = store.resolve_active(
        "mandate:agent-os",
        "binding:local",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluated_at=_now(),
    )
    assert resolved.mandate_id == "mandate:agent-os"

    status, attached = _request(
        base,
        "/v1/mandates:attach",
        body={
            "mandate_id": "mandate:agent-os",
            "environment_binding_id": "binding:local",
            "principal_id": "user:local",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
        },
        token=ADMIN_TOKEN,
    )
    assert status == 200, attached
    assert attached["mandate_id"] == "mandate:agent-os"
    assert attached["environment_binding_id"] == "binding:local"


def test_bootstrap_requires_admin_token(admin_server: tuple[str, Path]) -> None:
    base, _ = admin_server
    status, payload = _request(
        base,
        "/v1/mandates:bootstrap",
        body=_mandate().model_dump(mode="json"),
        token=None,
    )
    assert status == 401
    assert payload["error"] == "admin_authentication_required"


def test_bootstrap_rejects_unknown_admin_token(
    admin_server: tuple[str, Path],
) -> None:
    base, _ = admin_server
    status, payload = _request(
        base,
        "/v1/mandates:bootstrap",
        body=_mandate().model_dump(mode="json"),
        token="wrong",
    )
    assert status == 401
    assert payload["error"] == "admin_authentication_failed"


def test_attach_requires_admin_token(admin_server: tuple[str, Path]) -> None:
    base, _ = admin_server
    status, payload = _request(
        base,
        "/v1/mandates:attach",
        body={
            "mandate_id": "mandate:agent-os",
            "environment_binding_id": "binding:local",
            "principal_id": "user:local",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
        },
        token=None,
    )
    assert status == 401
    assert payload["error"] == "admin_authentication_required"


def test_bootstrap_rejects_in_memory_database(tmp_path: Path) -> None:
    admin = AgentOSApplication(database=":memory:", workspace=tmp_path)
    owner = AgentOSApplication(
        database=tmp_path / "owner.sqlite3", workspace=tmp_path
    )
    handler = type(
        "InMemoryAdminHandler",
        (Handler,),
        {"application": owner, "admin_applications": {ADMIN_TOKEN: admin}},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        status, payload = _request(
            base,
            "/v1/mandates:bootstrap",
            body=_mandate().model_dump(mode="json"),
            token=ADMIN_TOKEN,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert status == 400
    assert payload["error"] == "mandate bootstrap requires a file database"
