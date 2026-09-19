"""Surface protocol 1.1 -> 1.2: closing the additive-field compatibility lie.

The defect this pins down (already on `main`, not on a branch): P3a-2 added
``awaiting_approval`` to the session-listing projection while
``SURFACE_PROTOCOL_VERSION`` still declared ``1.1`` and no route negotiated a
version. A strict 1.1 reader — the published 1.1 field set behind
``extra="forbid"`` — therefore REJECTED a payload that claimed to be 1.1. The
version string and the payload shape disagreed, so the stated compatibility was
false.

These tests make the close-out observable rather than vague:

(a) 1.2 is the declared version and negotiation is an ordered ``MAJOR.MINOR``
    rule with a declared, closed range;
(b) what a strict 1.1 reader does with each shape is fixed and falsifiable:
    the current shape is rejected (``extra="forbid"`` is untouched), while the
    negotiated 1.1 projection is accepted — including over real HTTP;
(c) every version gate negotiates instead of comparing for equality, enforced
    structurally so a re-introduced equality check goes red.

Nothing here relaxes a contract: the projection removes only the fields the
additive registry declares, and an unsupported version is an error, never a
lenient fallback.
"""

from __future__ import annotations

import ast
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Generator, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_os_contracts import (
    SURFACE_PROTOCOL_ADDITIVE_MINORS,
    SURFACE_PROTOCOL_MIN_SUPPORTED,
    SURFACE_PROTOCOL_VERSION,
    SurfaceProtocolVersionError,
    SurfaceSessionListResponse,
    SurfaceSessionStatus,
    SurfaceSessionSummary,
    downgrade_surface_payload,
    negotiate_surface_protocol_version,
    parse_surface_protocol_version,
    surface_protocol_readable_versions,
    surface_protocol_supported_versions,
    surface_protocol_unknown_fields,
)
from agent_os_core import (
    DeferredApprovalGateway,
    DeterministicProvider,
    SurfaceProtocolError,
)
from agent_os_core.provider import ProviderToolProposal
from agent_os_core.surface_runtime import SurfaceRuntime

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from apps.api_server.surface_routes import SurfaceRoutes
from apps.cli.surface_client import SurfaceClient, SurfaceProtocolMismatch
from apps.runtime_daemon import (
    RuntimeConfig,
    _reject_live_descriptor,
    daemon_status,
    start_runtime,
)
from apps.runtime_daemon.descriptor import (
    RuntimeDescriptorError,
    RuntimeDescriptorProtocolError,
    load_runtime_descriptor,
)

NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)


class _Strict11Summary(BaseModel):
    """The session-summary shape that was PUBLISHED as protocol 1.1.

    ``extra="forbid"`` mirrors ``ContractModel`` exactly, so a payload carrying
    any field this model does not declare is refused — which is precisely the
    hazard a claimed-1.1 payload with 1.2 fields walks into. Its field set is
    asserted against the live contract below, so it cannot quietly grow into a
    more tolerant reader.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    session_id: str
    task_id: str
    status: SurfaceSessionStatus
    permission_mode: str = "ASK"
    message_count: int = Field(ge=0)
    updated_at: datetime


class _Strict11ListResponse(BaseModel):
    """The published 1.1 listing envelope, version pinned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    protocol_version: Literal["1.1"]
    sessions: tuple[_Strict11Summary, ...] = ()
    next_cursor: str | None = None


def _listing_payload(*, awaiting_approval: bool) -> dict[str, Any]:
    """The listing payload the runtime emits today, built from the real contract."""

    summary = SurfaceSessionSummary(
        session_id="session:1",
        task_id="task:1",
        status=SurfaceSessionStatus.WAITING_APPROVAL,
        permission_mode="ASK",
        message_count=2,
        updated_at=NOW,
        awaiting_approval=awaiting_approval,
    )
    response = SurfaceSessionListResponse(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        sessions=(summary,),
        next_cursor=None,
    )
    return json.loads(response.model_dump_json())


def test_strict_1_1_reader_really_is_the_published_1_1_shape() -> None:
    """The strict reader must not drift into tolerance for this to mean anything."""

    additive = frozenset(SURFACE_PROTOCOL_ADDITIVE_MINORS["1.2"])
    published = frozenset(SurfaceSessionSummary.model_fields) - additive
    assert frozenset(_Strict11Summary.model_fields) == published


# --- (a) the declared version and the ordered negotiation rule ---------------


def test_declared_version_is_1_2_over_a_1_1_floor() -> None:
    # Compared through the parser on purpose: pinning the literal would be the
    # very defect this file exists to prevent.
    assert parse_surface_protocol_version(SURFACE_PROTOCOL_VERSION) == (1, 2)
    assert parse_surface_protocol_version(SURFACE_PROTOCOL_MIN_SUPPORTED) == (1, 1)
    assert surface_protocol_supported_versions() == ("1.1", "1.2")


def test_every_supported_version_negotiates_to_itself() -> None:
    for version in surface_protocol_supported_versions():
        assert negotiate_surface_protocol_version(version) == version


@pytest.mark.parametrize(
    "supplied",
    [
        "1.0",  # same MAJOR, below the supported floor
        "1.3",  # same MAJOR, above this build
        "0.9",  # lower MAJOR
        "2.0",  # higher MAJOR
        "1",  # not MAJOR.MINOR
        "1.x",
        "1.1.0",
        "01.2",
        " 1.2",
        "1.2 ",
        "",
        "one.two",
    ],
)
def test_negotiation_refuses_anything_outside_the_declared_range(supplied: str) -> None:
    with pytest.raises(SurfaceProtocolVersionError):
        negotiate_surface_protocol_version(supplied)


def test_readable_versions_are_bounded_by_the_reader_minor() -> None:
    assert surface_protocol_readable_versions("1.2") == ("1.1", "1.2")
    assert surface_protocol_readable_versions("1.1") == ("1.1",)
    # A foreign MAJOR reads nothing here, whatever its minor says.
    assert surface_protocol_readable_versions("2.0") == ()
    assert surface_protocol_readable_versions("0.9") == ()
    assert surface_protocol_readable_versions("nonsense") == ()


def test_unknown_fields_are_the_registered_additive_delta() -> None:
    assert SURFACE_PROTOCOL_ADDITIVE_MINORS["1.2"] == ("awaiting_approval",)
    assert surface_protocol_unknown_fields("1.1") == ("awaiting_approval",)
    assert surface_protocol_unknown_fields("1.2") == ()


# --- (b) what a strict 1.1 reader does with each shape -----------------------


def test_strict_1_1_reader_rejects_a_payload_claiming_1_1_with_1_2_fields() -> None:
    """The compatibility lie itself, reproduced as a permanent fact.

    This is the shape the pre-1.2 build put on the wire: the version string says
    ``1.1`` while the payload carries a field 1.1 never declared. An honest 1.1
    reader refuses it, which is why the version had to move.
    """

    payload = _listing_payload(awaiting_approval=True)
    payload["protocol_version"] = "1.1"  # the version the pre-1.2 build declared

    with pytest.raises(ValidationError) as rejected:
        _Strict11ListResponse.model_validate(payload)

    (error,) = rejected.value.errors()
    assert error["type"] == "extra_forbidden"
    assert error["loc"] == ("sessions", 0, "awaiting_approval")


def test_strict_1_1_reader_rejects_the_current_shape() -> None:
    """Authoritatively 1.2: refused on the version AND on the unknown field."""

    payload = _listing_payload(awaiting_approval=True)
    assert parse_surface_protocol_version(payload["protocol_version"]) == (1, 2)
    assert payload["sessions"][0]["awaiting_approval"] is True

    with pytest.raises(ValidationError) as rejected:
        _Strict11ListResponse.model_validate(payload)

    assert {tuple(error["loc"]) for error in rejected.value.errors()} == {
        ("protocol_version",),
        ("sessions", 0, "awaiting_approval"),
    }


def test_strict_1_1_reader_accepts_the_negotiated_1_1_projection() -> None:
    payload = _listing_payload(awaiting_approval=True)

    served = downgrade_surface_payload(payload, "1.1")
    parsed = _Strict11ListResponse.model_validate(served)

    assert parse_surface_protocol_version(parsed.protocol_version) == (1, 1)
    assert parsed.sessions[0].status is SurfaceSessionStatus.WAITING_APPROVAL
    assert "awaiting_approval" not in served["sessions"][0]


def test_1_2_reader_still_receives_the_additive_field() -> None:
    payload = _listing_payload(awaiting_approval=True)

    served = downgrade_surface_payload(payload, "1.2")
    parsed = SurfaceSessionListResponse.model_validate(served)

    assert parse_surface_protocol_version(parsed.protocol_version) == (1, 2)
    assert parsed.sessions[0].awaiting_approval is True


def test_downgrade_strips_only_registered_fields() -> None:
    """Not 'drop anything unknown' — an unregistered key is left for the reader."""

    payload = {
        "schema_version": "1.0",
        "protocol_version": "1.2",
        "sessions": [
            {"session_id": "session:1", "awaiting_approval": True, "custom": "kept"}
        ],
    }

    served = downgrade_surface_payload(payload, "1.1")

    assert served["protocol_version"] == "1.1"
    assert served["sessions"][0] == {"session_id": "session:1", "custom": "kept"}


def test_downgrade_never_upgrades_a_declared_version() -> None:
    payload = {"protocol_version": "1.1", "sessions": [{"awaiting_approval": True}]}

    served = downgrade_surface_payload(payload, "1.2")

    assert served["protocol_version"] == "1.1"
    assert served["sessions"][0]["awaiting_approval"] is True


def test_downgrade_leaves_an_undeclared_version_visible() -> None:
    """A version this build cannot parse is never relabelled into a valid one."""

    assert downgrade_surface_payload({"protocol_version": "2.0"}, "1.1") == {
        "protocol_version": "2.0"
    }


@pytest.mark.parametrize("unsupported", ["1.0", "1.3", "2.0", "1", "", "1.x"])
def test_downgrade_refuses_an_unsupported_target(unsupported: str) -> None:
    with pytest.raises(SurfaceProtocolVersionError):
        downgrade_surface_payload(_listing_payload(awaiting_approval=True), unsupported)


# --- (a)/(b) over real HTTP --------------------------------------------------


class _PlainReader:
    """A reader with no protocol helpers: it can only send a raw header value."""

    def __init__(self, base: str, token: str) -> None:
        self.base = base
        self.token = token

    def get(self, path: str, *, protocol: str | None) -> tuple[int, dict]:
        return self._send("GET", path, protocol=protocol)

    def post(self, path: str, body: dict, *, protocol: str | None) -> tuple[int, dict]:
        return self._send("POST", path, protocol=protocol, body=body)

    def sse(self, path: str, *, protocol: str | None) -> tuple[int, str]:
        """Raw SSE body: the frame ``data:`` lines carry no JSON envelope to unwrap."""

        status, raw = self._raw("GET", path, protocol=protocol)
        return status, raw.decode("utf-8")

    def _send(
        self,
        method: str,
        path: str,
        *,
        protocol: str | None,
        body: dict | None = None,
    ) -> tuple[int, dict]:
        status, raw = self._raw(method, path, protocol=protocol, body=body)
        return status, json.loads(raw)

    def _raw(
        self,
        method: str,
        path: str,
        *,
        protocol: str | None,
        body: dict | None = None,
    ) -> tuple[int, bytes]:
        headers = {"Authorization": f"Bearer {self.token}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if protocol is not None:
            headers["X-Agent-OS-Protocol"] = protocol
        request = urllib.request.Request(
            self.base + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


def _proposal(call_id: str, capability_id: str, arguments: dict[str, Any]) -> Any:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


@pytest.fixture
def listing_server(tmp_path: Path) -> Generator[tuple[AgentOSApplication, _PlainReader], None, None]:
    """A real HTTP Surface server over a temp database/workspace.

    The app is driven in-process only to reach a genuinely pending approval, so
    the listing route has a session worth projecting.
    """

    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = AgentOSApplication(
        database=tmp_path / "surface-protocol-1-2.sqlite3", workspace=tmp_path
    )
    app.provider = DeterministicProvider(
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-edit",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable\n",
                            "new_string": "fixed\n",
                        },
                    ),
                ),
            ),
            ("edited reply", ()),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    session, loop = app.open_chat_session("edit", DeferredApprovalGateway())
    assert loop.run_turn(session, "edit fixture").stop_reason == "approval_required"

    token = "test-local-token"
    handler = type(
        "TestProtocolHandler",
        (Handler,),
        {
            "application": app,
            "local_token": token,
            "surface_routes": SurfaceRoutes(app.surface, token),
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield app, _PlainReader(f"http://127.0.0.1:{server.server_address[1]}", token)
    finally:
        server.shutdown()
        server.server_close()


def test_http_listing_serves_a_1_2_client_the_additive_field(
    listing_server: tuple[AgentOSApplication, _PlainReader],
) -> None:
    _, reader = listing_server

    status, payload = reader.get("/v1/surface/sessions?limit=20", protocol="1.2")

    assert status == 200, payload
    assert payload["protocol_version"] == "1.2"
    assert payload["sessions"][0]["awaiting_approval"] is True


def test_http_listing_serves_a_strict_1_1_reader_a_1_1_payload(
    listing_server: tuple[AgentOSApplication, _PlainReader],
) -> None:
    """The whole point: a 1.1 client gets a body its own contract accepts."""

    _, reader = listing_server

    status, payload = reader.get("/v1/surface/sessions?limit=20", protocol="1.1")

    assert status == 200, payload
    assert payload["protocol_version"] == "1.1"
    assert "awaiting_approval" not in payload["sessions"][0]
    parsed = _Strict11ListResponse.model_validate(payload)
    assert parsed.sessions[0].status is SurfaceSessionStatus.WAITING_APPROVAL


def test_http_listing_without_the_header_serves_the_oldest_minor(
    listing_server: tuple[AgentOSApplication, _PlainReader],
) -> None:
    """A client that predates the header cannot know 1.2 fields, so it never gets one."""

    _, reader = listing_server

    status, payload = reader.get("/v1/surface/sessions?limit=20", protocol=None)

    assert status == 200, payload
    assert payload["protocol_version"] == SURFACE_PROTOCOL_MIN_SUPPORTED
    assert "awaiting_approval" not in payload["sessions"][0]


@pytest.mark.parametrize("supplied", ["1.0", "1.3", "2.0", "nonsense", ""])
def test_http_listing_refuses_an_unnegotiable_header(
    listing_server: tuple[AgentOSApplication, _PlainReader], supplied: str
) -> None:
    _, reader = listing_server

    status, payload = reader.get("/v1/surface/sessions?limit=20", protocol=supplied)

    assert status == 422, payload
    # Reported in the surface protocol's own vocabulary, and the message says
    # which kind of problem it is instead of failing opaquely.
    assert payload["error"] == "SurfaceProtocolError"
    assert "MAJOR.MINOR" in payload["message"] or "negotiates" in payload["message"]


@pytest.mark.parametrize("version", surface_protocol_supported_versions())
def test_http_listing_matches_every_declared_minor(
    listing_server: tuple[AgentOSApplication, _PlainReader], version: str
) -> None:
    """The PROPERTY the equality gate is only a heuristic for, asserted per version.

    This is the coverage that actually holds against a distribution-dependent
    branch on the read path. The syntactic gate below cannot see a branch on an
    arbitrarily named variable — it was reproduced that adding
    ``if server_version != "1.2": ...`` leaves that gate green — so the guarantee
    is measured here instead: every declared minor is requested over real HTTP and
    the body it receives must be the body its own contract declares.
    """

    _, reader = listing_server

    status, payload = reader.get("/v1/surface/sessions?limit=20", protocol=version)

    assert status == 200, payload
    assert payload["protocol_version"] == version
    summary = payload["sessions"][0]
    if "awaiting_approval" in surface_protocol_unknown_fields(version):
        assert "awaiting_approval" not in summary
    else:
        assert summary["awaiting_approval"] is True


# --- (e) reverse skew: an older build meeting a newer descriptor -------------


def _skewed_descriptor_bytes(version: str) -> str:
    """A descriptor exactly as the OTHER build would write it.

    Written as raw JSON on purpose: this build cannot construct a
    ``RuntimeDescriptor`` at a version it does not declare, and that is the whole
    point — the file on disk is produced by a build whose version union differs.
    """

    return json.dumps(
        {
            "schema_version": "1.0",
            "protocol_version": version,
            "pid": 4242,
            "boot_id": "boot:protocol-1-2:skew",
            "host": "127.0.0.1",
            "port": 18787,
            "bearer_token": "0" * 43,
            "database_path": "/tmp/agent-os.sqlite3",
            "workspace_path": "/tmp/agent-os-workspace",
            "created_at": "2026-09-18T00:00:00+00:00",
        }
    )


def test_a_descriptor_from_the_older_minor_still_loads(tmp_path: Path) -> None:
    """The reverse direction that must keep working: this build reads 1.1."""

    path = tmp_path / "runtime.json"
    path.write_text(_skewed_descriptor_bytes(SURFACE_PROTOCOL_MIN_SUPPORTED))

    # Compared through the parser, like every other version assertion in this
    # file: pinning the literal would be the very defect these tests prevent.
    loaded = load_runtime_descriptor(path)
    assert parse_surface_protocol_version(loaded.protocol_version) == (1, 1)


@pytest.mark.parametrize("version", ["1.0", "1.3", "2.0"])
def test_an_unreadable_descriptor_version_fails_typed_not_as_a_schema_dump(
    tmp_path: Path, version: str
) -> None:
    """The skew is named, instead of a bare "invalid schema" the operator must guess at."""

    path = tmp_path / "runtime.json"
    path.write_text(_skewed_descriptor_bytes(version))

    with pytest.raises(RuntimeDescriptorProtocolError) as rejected:
        load_runtime_descriptor(path)

    # Still a RuntimeDescriptorError for every existing handler, plus the detail
    # an operator needs: which version, which side is behind, what to do.
    assert isinstance(rejected.value, RuntimeDescriptorError)
    assert version in str(rejected.value)
    assert "skew" in str(rejected.value)
    assert SURFACE_PROTOCOL_VERSION in str(rejected.value)


def test_a_descriptor_that_is_not_a_version_at_all_is_still_a_schema_error(
    tmp_path: Path,
) -> None:
    """The skew report is narrow: only a well-formed MAJOR.MINOR earns it."""

    path = tmp_path / "runtime.json"
    path.write_text(_skewed_descriptor_bytes("nonsense"))

    with pytest.raises(RuntimeDescriptorError) as rejected:
        load_runtime_descriptor(path)

    assert not isinstance(rejected.value, RuntimeDescriptorProtocolError)


def test_daemon_status_names_the_skew_instead_of_crashing(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(_skewed_descriptor_bytes("1.3"))

    status = daemon_status(path)

    assert status["status"] == "invalid"
    assert "1.3" in status["error"]
    assert "skew" in status["error"]


def test_starting_a_daemon_never_clobbers_a_skewed_descriptor(
    tmp_path: Path,
) -> None:
    """A skewed descriptor may belong to a RUNNING daemon: refusing beats replacing.

    Before this, an unreadable descriptor was silently treated as "no daemon
    here", so a second daemon started over the same identity and rewrote the file
    — stranding the first daemon by removing the only handle to it.
    """

    config = RuntimeConfig(
        database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        descriptor_path=tmp_path / "runtime.json",
        port=0,
    )
    config.descriptor_path.write_text(_skewed_descriptor_bytes("1.3"))
    before = config.descriptor_path.read_text(encoding="utf-8")

    with pytest.raises(RuntimeDescriptorProtocolError):
        start_runtime(config)

    assert config.descriptor_path.read_text(encoding="utf-8") == before


def test_an_unreadable_not_json_descriptor_is_still_replaceable(
    tmp_path: Path,
) -> None:
    """The refusal is narrow: only a version skew blocks a start, junk does not."""

    path = tmp_path / "runtime.json"
    path.write_text("not json", encoding="utf-8")

    # Returns instead of raising: this path is replaceable, as before.
    assert _reject_live_descriptor(path) is None


# --- (c)/(d) the structural checks -------------------------------------------


def _open_command(app: AgentOSApplication, key: str, *, version: str = SURFACE_PROTOCOL_VERSION) -> dict:
    return {
        "protocol_version": version,
        "client": {
            "client_id": "client:protocol-1-2:1",
            "client_type": "TEST",
            "principal_id": app.principal.principal_id,
            "tenant_id": app.principal.tenant_id,
            "workspace_id": app.principal.workspace_id,
            "device_id": "device:protocol-1-2:1",
        },
        "statement": "protocol negotiation probe",
        "idempotency_key": key,
        "requested_at": "2026-09-18T00:00:00+00:00",
    }


def test_http_state_change_still_requires_the_header(
    listing_server: tuple[AgentOSApplication, _PlainReader],
) -> None:
    """Negotiation must not soften the state-change contract."""

    app, reader = listing_server

    status, payload = reader.post(
        "/v1/surface/sessions",
        _open_command(app, "idem:protocol-1-2:no-header"),
        protocol=None,
    )

    assert status == 422, payload
    assert payload["error"] == "SurfaceProtocolError"


def test_http_state_change_negotiates_an_older_minor(
    listing_server: tuple[AgentOSApplication, _PlainReader],
) -> None:
    """A 1.1 client can still change state, and its response declares 1.1."""

    app, reader = listing_server

    status, payload = reader.post(
        "/v1/surface/sessions",
        _open_command(app, "idem:protocol-1-2:header-1-1"),
        protocol="1.1",
    )

    assert status == 200, payload
    snapshot = payload["snapshot"]
    assert parse_surface_protocol_version(snapshot["protocol_version"]) == (1, 1)


def test_runtime_gate_negotiates_instead_of_comparing() -> None:
    runtime = object.__new__(SurfaceRuntime)

    assert runtime._require_protocol("1.1") == "1.1"
    assert runtime._require_protocol("1.2") == "1.2"

    for refused in ("1.0", "1.3", "2.0", "1", "", "1.x"):
        with pytest.raises(SurfaceProtocolError):
            runtime._require_protocol(refused)


def test_cli_client_reads_an_older_runtime_but_not_a_foreign_one() -> None:
    client = object.__new__(SurfaceClient)

    for readable in ("1.1", "1.2"):
        client._check_protocol({"protocol_version": readable})

    for refused in ("1.0", "1.3", "2.0", "nonsense", ""):
        with pytest.raises(SurfaceProtocolMismatch):
            client._check_protocol({"protocol_version": refused})
    with pytest.raises(SurfaceProtocolMismatch):
        client._check_protocol({})
    with pytest.raises(SurfaceProtocolMismatch):
        client._check_protocol("not-a-mapping")


# --- (c) no equality gate may survive ---------------------------------------


def _is_version_operand(operand: ast.expr) -> bool:
    """Whether an expression IS a surface protocol version (not a payload key).

    Name-based on purpose, and therefore a heuristic with two known blind spots,
    both measured rather than assumed:

    * an arbitrarily named variable (``server_version``) holding a version is not
      recognised, so a gate written against one is invisible here — reproduced by
      injecting ``if server_version != "1.2": raise ...``, which leaves this check
      green;
    * the mirror image, a benign assertion about a version read out of data
      (``descriptor.protocol_version == "1.1"``) IS reported, so such assertions
      compare through ``parse_surface_protocol_version`` instead.

    That is why the per-version HTTP property test above exists: it is behavioral,
    so no naming choice hides a branch from it.
    """

    if isinstance(operand, ast.Name):
        return "protocol_version" in operand.id.lower()
    if isinstance(operand, ast.Attribute):
        return "protocol_version" in operand.attr.lower()
    return False


def _in_decision_context(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    """Whether ``node`` is used as a decision, not merely observed.

    Two decisions matter: a *gate* branches — it is the test of an
    ``if``/``while``/conditional expression — and a *pin* asserts one version
    outright. Both are reported, optionally through ``not`` and
    ``and``/``or``. A comparison that only inspects a value (reading a key out
    of a serialized payload) is neither, so this runs over the whole tree with
    no allowlist.
    """

    current: ast.AST = node
    while True:
        parent = parents.get(id(current))
        if parent is None:
            return False
        if isinstance(parent, ast.BoolOp):
            current = parent
            continue
        if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
            current = parent
            continue
        if isinstance(parent, (ast.If, ast.While, ast.IfExp)):
            return parent.test is current
        if isinstance(parent, ast.Assert):
            # A pinned equality assertion is the same defect as a gate: it locks
            # one version, so a later additive minor turns it red. `main` carried
            # exactly that (`assert SURFACE_PROTOCOL_VERSION == "1.1"`).
            return parent.test is current
        return False


def _version_equality_gates(path: Path) -> list[str]:
    """Version gates/pins that compare a surface protocol version by equality."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
        return []

    parents = {
        id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
    }
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
            continue
        if not any(_is_version_operand(operand) for operand in (node.left, *node.comparators)):
            continue
        if _in_decision_context(node, parents):
            offenders.append(f"{path}:{node.lineno}: {ast.unparse(node)}")
    return offenders


def test_no_protocol_version_equality_gate_survives() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    # Matched against the path RELATIVE to the repo root: the checkout itself may
    # live under a `.worktrees` directory, which must not skip the whole walk.
    skipped_parts = {".venv", "__pycache__", "node_modules", ".git", ".worktrees"}

    offenders: list[str] = []
    scanned = 0
    for source_root in ("apps", "packages", "tests"):
        for path in sorted((repo_root / source_root).rglob("*.py")):
            if skipped_parts & set(path.relative_to(repo_root).parts):
                continue
            scanned += 1
            offenders.extend(_version_equality_gates(path))

    assert scanned > 200, (
        f"only {scanned} files scanned — the walk is broken, so a green result "
        "would mean nothing"
    )
    assert offenders == [], (
        "a surface protocol version is compared for equality instead of "
        "negotiated; an equality gate silently rejects every other declared "
        "minor:\n" + "\n".join(offenders)
    )


# --- (d) no response body bypasses the projection ----------------------------


def _routes_class_methods(path: Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SurfaceRoutes":
            return {
                item.name: item
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    raise AssertionError(f"SurfaceRoutes not found in {path}")


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        if isinstance(item.func, ast.Name):
            names.add(item.func.id)
        elif isinstance(item.func, ast.Attribute):
            names.add(item.func.attr)
    return names


def _writes_a_body(node: ast.AST) -> bool:
    """Whether this method puts response bytes/JSON on the wire itself."""

    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        func = item.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr in {"send_response", "_json"}:
            return True
        # `handler.wfile.write(...)` — the raw socket write, which is what the
        # SSE writers use instead of `_json`.
        if func.attr == "write" and isinstance(func.value, ast.Attribute):
            return True
    return False


def _reaches_projection(
    name: str,
    methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    seen: frozenset[str],
) -> bool:
    """Whether this method (or a sibling it calls) projects the payload."""

    if name in seen:
        return False
    called = _called_names(methods[name])
    if "downgrade_surface_payload" in called:
        return True
    return any(
        call in methods and _reaches_projection(call, methods, seen | {name})
        for call in called
    )


def test_every_surface_response_writer_reaches_the_projection() -> None:
    """Every method that writes a body must project it, directly or via a sibling.

    This is the structural half of the coverage for the seam: the SSE writers do
    not go through ``_respond``, so what has to hold is that no response-writing
    method exists whose call graph skips ``downgrade_surface_payload``. It is a
    structural check, not a proof — a body could still be written through a helper
    on a different class (``Handler._json``) — so the per-version HTTP tests above
    remain the behavioral guarantee.
    """

    routes_path = (
        Path(__file__).resolve().parents[2] / "apps" / "api_server" / "surface_routes.py"
    )
    methods = _routes_class_methods(routes_path)

    writers = {name for name, node in methods.items() if _writes_a_body(node)}
    assert writers == {"_respond", "_write_sse", "_write_frame_sse"}, (
        "the set of Surface response writers changed; every one of them must "
        f"project the payload at the negotiated version: {sorted(writers)}"
    )

    gaps = sorted(
        name for name in writers if not _reaches_projection(name, methods, frozenset())
    )
    assert gaps == [], (
        "these Surface response writers bypass the negotiated projection, so a "
        f"field added by a later minor leaks to an older reader: {gaps}"
    )
