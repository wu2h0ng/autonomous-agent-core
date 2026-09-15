"""Admin HTTP endpoints for mandate bootstrap/attach (Stage 2f-prep).

These replace the former Python CLI `mandate-bootstrap` / `mandate-attach`; the
terminal does not implement governance/admin surfaces (founder option B).
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
def admin_server(tmp_path: Path) -> Iterator[str]:
    database = tmp_path / "agent-os.sqlite3"
    owner = _app(tmp_path, database)
    admin = _app(tmp_path, database)
    handler = type(
        "MandateBootstrapHandler",
        (Handler,),
        {"application": owner, "admin_applications": {ADMIN_TOKEN: admin}},
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


def test_bootstrap_then_attach(admin_server: str) -> None:
    mandates = _mandate()
    status, boot = _request(
        admin_server,
        "/v1/mandates:bootstrap",
        body=mandates.model_dump(mode="json"),
        token=ADMIN_TOKEN,
    )
    assert status == 201, boot
    assert boot["mandate_id"] == "mandate:agent-os"
    assert boot["status"] == "ACTIVE"

    status, attached = _request(
        admin_server,
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


def test_bootstrap_requires_admin_token(admin_server: str) -> None:
    status, payload = _request(
        admin_server,
        "/v1/mandates:bootstrap",
        body=_mandate().model_dump(mode="json"),
        token=None,
    )
    assert status == 401
    assert payload["error"] == "admin_authentication_required"


def test_bootstrap_rejects_unknown_admin_token(admin_server: str) -> None:
    status, payload = _request(
        admin_server,
        "/v1/mandates:bootstrap",
        body=_mandate().model_dump(mode="json"),
        token="wrong",
    )
    assert status == 401
    assert payload["error"] == "admin_authentication_failed"
