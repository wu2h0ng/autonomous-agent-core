from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any


from agent_os_contracts import (
    MandateCommitmentContext,
    MandateOutcomeContext,
    MandateRelevanceContext,
    PrincipalIdentity,
    PrincipalRole,
    ProviderRelevancePolicy,
    RatifiedMandateRef,
    RelevanceDisposition,
    WorkloadIdentityRegistration,
    content_digest,
)
from agent_os_core import (
    DeterministicProvider,
    InMemoryMandateRelevanceContextRegistry,
    ProviderRelevanceAssessor,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore
from apps.api_server.app import AgentOSApplication
from apps.api_server.data_agent_report_adapter import (
    SQLiteDataAgentReportStateStore,
)
from apps.api_server.data_agent_report_admission import (
    SQLiteDataAgentReportAdmissionMaterialStore,
)
from apps.api_server.data_agent_situated_bootstrap import DataAgentSituatedBootstrap
from apps.api_server.server import Handler
from tests.product.test_data_agent_external_report_adapter import (
    _adapter as _external_adapter,
    _binding as _external_binding,
    _credential as _external_credential,
)
from tests.product.test_provider_relevance_assessor import (
    _draft as _provider_draft,
    _policy as _provider_policy,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
TRACE_ID = "trace-123"


def _context() -> MandateRelevanceContext:
    return MandateRelevanceContext(
        relevance_context_id="mandate-context:data-agent-reports-v1",
        version=1,
        mandate_id="mandate:build-agent-os",
        mandate_version=1,
        mandate_digest="a" * 64,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        mission_statement=(
            "Keep Agent OS product commitments truthful without activating work."
        ),
        desired_outcomes=(
            MandateOutcomeContext(
                outcome_id="outcome:truthful-product",
                statement="Review trusted Data Agent reports without hidden authority.",
            ),
        ),
        open_commitments=(
            MandateCommitmentContext(
                commitment_id="commitment:quality",
                statement="Protect the verified product quality boundary.",
                due_at=NOW + timedelta(hours=2),
            ),
        ),
        permanent_constraints=(
            "No task activation from relevance assessment.",
            "No external effect authority.",
            "C7 correction always wins.",
        ),
    )


def _mandate(policy: ProviderRelevancePolicy) -> RatifiedMandateRef:
    return RatifiedMandateRef(
        mandate_id="mandate:build-agent-os",
        version=1,
        mandate_digest="a" * 64,
        ratification_receipt_id="ratification:data-agent-provider-e2e",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        owner_principal_id="user:local",
        ratified_by="user:local",
        ratified_at=NOW - timedelta(hours=1),
        valid_from=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=30),
        correction_epoch=0,
        authority_envelope_digest="e" * 64,
        allowed_environment_bindings=(_external_binding(),),
        relevance_assessor=_provider_policy().assessor_ref(),
        relevance_context=(_context().ref()),
    )


def _situated_app(
    tmp_path: Path,
    disposition: RelevanceDisposition,
    *,
    workload_identities: tuple[WorkloadIdentityRegistration, ...] = (),
    external_state_adapters: tuple[Any, ...] = (),
    external_state_authorization_receipts: tuple[Any, ...] = (),
    provider_sink: list[DeterministicProvider] | None = None,
    control_sink: list[SQLiteSituatedAssessmentStore] | None = None,
) -> AgentOSApplication:
    report_database = tmp_path / "reports.sqlite3"
    situated_database = tmp_path / "situated.sqlite3"
    task_database = tmp_path / "agent-os.sqlite3"

    policy = _provider_policy()
    mandate = _mandate(policy)

    adapter, _broker, _transport = _external_adapter(
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    provider = DeterministicProvider(
        text=_provider_draft(disposition),
        invocation_binding=policy.provider_invocation,
    )
    control = SQLiteSituatedAssessmentStore(
        situated_database,
        mandates=(mandate,),
    )
    if provider_sink is not None:
        provider_sink.append(provider)
    if control_sink is not None:
        control_sink.append(control)
    credential = _external_credential()
    credentials = adapter._credential_authorization_reader_for_composition
    configured = credentials.resolve_authorization(credential.credential_ref_id)
    assert configured is not None
    assert configured.credential_ref_digest == content_digest(credential)
    assessor = ProviderRelevanceAssessor(
        provider=provider,
        provider_profile=policy.provider_invocation.provider_profile,
        policy=policy,
        trust=adapter,
        contexts=InMemoryMandateRelevanceContextRegistry((_context(),)),
    )
    compose_options: dict[str, Any] = {}
    if external_state_adapters:
        compose_options["external_state_adapters"] = external_state_adapters
        compose_options["external_state_authorization_receipts"] = (
            external_state_authorization_receipts
        )
    runtime = DataAgentSituatedBootstrap.compose(
        adapter=adapter,
        material_store=SQLiteDataAgentReportAdmissionMaterialStore(
            task_database.with_name(f"{task_database.name}.material.sqlite3"),
            principal_id=adapter.principal_scope[0],
            tenant_id=adapter.principal_scope[1],
            workspace_id=adapter.principal_scope[2],
        ),
        credentials=credentials,
        control=control,
        assessor=assessor,
        admission_database=task_database.with_name(
            f"{task_database.name}.admission.sqlite3"
        ),
        clock=lambda: NOW,
        workload_identities=workload_identities,
        **compose_options,
    )
    principal = PrincipalIdentity(
        principal_id=adapter.principal_scope[0],
        tenant_id=adapter.principal_scope[1],
        workspace_id=adapter.principal_scope[2],
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=NOW,
    )
    return AgentOSApplication._with_data_agent_situated_runtime(
        situated_runtime=runtime,
        database=task_database,
        workspace=tmp_path,
        principal=principal,
        clock=lambda: NOW,
    )


def _http_server(app: AgentOSApplication):
    handler = type("TestAgentOSHandler", (Handler,), {"application": app})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def _post(
    base: str,
    path: str,
    body: dict | None = None,
    idempotency_key: str | None = None,
) -> tuple[int, dict]:
    data = (
        json.dumps(body if body is not None else {}).encode()
        if body is not None
        else None
    )
    headers: dict[str, str] = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request(
        base + path,
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            status = response.status
            value = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        status = exc.code
        value = json.loads(exc.read())
    assert isinstance(value, dict)
    return status, value


class TestSituatedProposalRoute:
    def test_proposal_route_returns_task_draft_proposal(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.CREATE_TASK)
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/proposal",
                body={},
                idempotency_key="task-draft-test",
            )
            assert status == 200
            assert result["outcome_kind"] == "TASK_DRAFT"
            assert isinstance(result.get("task_draft"), dict)
            draft = result["task_draft"]
            assert draft["task_draft_id"].startswith("task-draft:")
            assert draft["activation_authorized"] is False
            assert draft["external_effects_authorized"] is False
            assert "evidence_ids" in draft
            assert len(draft["evidence_ids"]) >= 1
            assert "task_draft_id" not in result
            assert "activation_authorized" not in result
        finally:
            server.shutdown()
            server.server_close()

    def test_proposal_route_returns_help_request(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.HELP)
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/proposal",
                body={},
                idempotency_key="help-request-test",
            )
            assert status == 200
            assert result["outcome_kind"] == "HELP_REQUEST"
            assert isinstance(result.get("help_request"), dict)
            hr = result["help_request"]
            assert hr["help_request_id"].startswith("help:")
            assert hr["authority_granted"] is False
            assert hr["external_effects_authorized"] is False
            assert "evidence_ids" in hr
            assert len(hr["evidence_ids"]) >= 1
            assert "help_request_id" not in result
            assert "authority_granted" not in result
        finally:
            server.shutdown()
            server.server_close()

    def test_proposal_route_returns_no_proposal(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.ABSTAIN)
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/proposal",
                body={},
                idempotency_key="no-proposal-test",
            )
            assert status == 200
            assert result == {"outcome_kind": "NO_PROPOSAL"}
        finally:
            server.shutdown()
            server.server_close()

    def test_no_alternate_observe_or_admit_route(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.CREATE_TASK)
        server, thread, base = _http_server(app)
        try:
            status, _result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/observe",
                body={},
            )
            assert status == 404

            status, _result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/admit",
                body={},
            )
            assert status == 404

            status, _result = _post(
                base,
                "/api/situated/data-agent-reports/observe",
                body={},
            )
            assert status == 404

            status, _result = _post(
                base,
                "/api/situated/observe",
                body={},
            )
            assert status == 404
        finally:
            server.shutdown()
            server.server_close()

    def test_generic_idempotency_cache_bypass(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.ABSTAIN)
        server, thread, base = _http_server(app)
        try:
            path = f"/api/situated/data-agent-reports/{TRACE_ID}/proposal"
            key = "idempotency-bypass-test"

            status_1, result_1 = _post(base, path, body={}, idempotency_key=key)
            assert status_1 == 200
            assert result_1 == {"outcome_kind": "NO_PROPOSAL"}

            cached = app.store.get_idempotency(path, key)
            assert cached is None, (
                "situated proposal route must not write to idempotency cache"
            )

            status_2, result_2 = _post(base, path, body={}, idempotency_key=key)
            assert status_2 == 200
            assert result_2 == {"outcome_kind": "NO_PROPOSAL"}

            cached_after = app.store.get_idempotency(path, key)
            assert cached_after is None, (
                "situated proposal route must not write to idempotency cache"
            )
        finally:
            server.shutdown()
            server.server_close()

    def test_normal_route_still_uses_generic_cache(self, tmp_path: Path) -> None:
        app = AgentOSApplication(
            database=tmp_path / "cache.sqlite3", workspace=tmp_path
        )
        server, thread, base = _http_server(app)
        try:
            payload = {
                "goal_id": "goal:cache-test",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "created_by": "user:local",
                "created_at": NOW.isoformat(),
                "statement": "test cache behavior",
            }
            path = "/v1/tasks"
            key = "normal-cache-test"

            request = urllib.request.Request(
                base + path,
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Idempotency-Key": key,
                },
                method="POST",
            )
            with urllib.request.urlopen(request) as response:
                status_1 = response.status
                result_1 = json.loads(response.read())
            assert status_1 == 201

            cached = app.store.get_idempotency(path, key)
            assert cached is not None
            assert cached["task_id"] == result_1["task_id"]

            request = urllib.request.Request(
                base + path,
                data=json.dumps({}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Idempotency-Key": key,
                },
                method="POST",
            )
            with urllib.request.urlopen(request) as response:
                status_2 = response.status
                result_2 = json.loads(response.read())
            assert status_2 == 200
            assert result_2["task_id"] == result_1["task_id"]
        finally:
            server.shutdown()
            server.server_close()

    def test_valid_trace_zero_forwarded(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.ABSTAIN)
        called_with: list[str] = []

        def _record_call(trace_id: str):
            called_with.append(trace_id)
            return None

        app.observe_admit_and_propose_data_agent_report = _record_call  # type: ignore[method-assign]
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                "/api/situated/data-agent-reports/0/proposal",
                body={},
            )
            assert status == 200
            assert result == {"outcome_kind": "NO_PROPOSAL"}
            assert called_with == ["0"]
        finally:
            server.shutdown()
            server.server_close()

    def test_empty_trace_id_rejected(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.CREATE_TASK)
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                "/api/situated/data-agent-reports//proposal",
                body={},
            )
            assert status == 404
        finally:
            server.shutdown()
            server.server_close()

    def test_extra_trace_segments_rejected(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.CREATE_TASK)
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/extra/proposal",
                body={},
            )
            assert status == 404
        finally:
            server.shutdown()
            server.server_close()

    def test_encoded_slash_in_trace_rejected_before_application_call(
        self, tmp_path: Path
    ) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.CREATE_TASK)
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                "/api/situated/data-agent-reports/trace%2Fevil/proposal",
                body={},
            )
            assert status == 404
        finally:
            server.shutdown()
            server.server_close()

    def test_nonempty_body_rejected(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.CREATE_TASK)
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/proposal",
                body={"extra": "field"},
            )
            assert status == 400
            assert "empty" in result["message"].lower()
        finally:
            server.shutdown()
            server.server_close()

    def test_authority_shaped_body_rejected(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.CREATE_TASK)
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/proposal",
                body={"activation_authorized": True},
            )
            assert status == 400
            assert "empty" in result["message"].lower()
        finally:
            server.shutdown()
            server.server_close()

    def test_uncomposed_application_returns_error(self, tmp_path: Path) -> None:
        app = AgentOSApplication(
            database=tmp_path / "legacy.sqlite3", workspace=tmp_path
        )
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/proposal",
                body={},
            )
            assert status == 400
            assert "not configured" in result["message"].lower()
        finally:
            server.shutdown()
            server.server_close()

    def test_malformed_path_rejected(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.CREATE_TASK)
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                "/api/situated/data-agent-reports",
                body={},
            )
            assert status == 404
        finally:
            server.shutdown()
            server.server_close()

    def test_trailing_slash_rejected(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.CREATE_TASK)
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/proposal/",
                body={},
            )
            assert status == 404
        finally:
            server.shutdown()
            server.server_close()

    def test_query_rejected(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.CREATE_TASK)
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/proposal?foo=bar",
                body={},
            )
            assert status == 404
        finally:
            server.shutdown()
            server.server_close()

    def test_unknown_return_type_fails(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.CREATE_TASK)
        app.observe_admit_and_propose_data_agent_report = (  # type: ignore[method-assign]
            lambda trace_id: "not_a_proposal"
        )
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/proposal",
                body={},
            )
            assert status == 400
            assert "unexpected" in result["message"].lower()
        finally:
            server.shutdown()
            server.server_close()

    def test_exact_nested_keys_for_task_draft(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.CREATE_TASK)
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/proposal",
                body={},
                idempotency_key="nested-keys-draft",
            )
            assert status == 200
            assert set(result.keys()) == {"outcome_kind", "task_draft"}
            assert result["outcome_kind"] == "TASK_DRAFT"
            assert isinstance(result["task_draft"], dict)
            assert "task_draft_id" in result["task_draft"]
        finally:
            server.shutdown()
            server.server_close()

    def test_exact_nested_keys_for_help_request(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.HELP)
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/proposal",
                body={},
                idempotency_key="nested-keys-help",
            )
            assert status == 200
            assert set(result.keys()) == {"outcome_kind", "help_request"}
            assert result["outcome_kind"] == "HELP_REQUEST"
            assert isinstance(result["help_request"], dict)
            assert "help_request_id" in result["help_request"]
        finally:
            server.shutdown()
            server.server_close()

    def test_constant_serializer_cannot_pass(self, tmp_path: Path) -> None:
        app = _situated_app(tmp_path, RelevanceDisposition.ABSTAIN)
        app.observe_admit_and_propose_data_agent_report = (  # type: ignore[method-assign]
            lambda trace_id: 42
        )
        server, thread, base = _http_server(app)
        try:
            status, result = _post(
                base,
                f"/api/situated/data-agent-reports/{TRACE_ID}/proposal",
                body={},
            )
            assert status == 400
            assert "unexpected" in result["message"].lower()
        finally:
            server.shutdown()
            server.server_close()
