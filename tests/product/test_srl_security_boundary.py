from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ast
import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest

from agent_os_contracts import (
    CredentialRef,
    CredentialAuthorizationSnapshot,
    CredentialStatus,
    EnvironmentEventAdmissionReceipt,
    LedgerAccessScope,
    PrincipalIdentity,
    PrincipalRole,
    SituatedEvaluationTrace,
    SituatedTraceReason,
    SituatedTraceStatus,
    canonical_json,
    content_digest,
)
from agent_os_core.srl_event_authority import (
    CanonicalCredentialAuthorizationReader,
    CredentialAuthorizationReader,
)
from agent_os_core.srl_event_store import (
    EventAdmissionPersistenceConflict,
    ScopedEventAdmissionReader,
    _create_event_admission_store,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore
from agent_os_core.srl_event_admission import EnvironmentEventAdmissionService
from agent_os_core.mandate_steward import MandateSteward
from agent_os_core import SituationalScopeMismatch
from apps.api_server.data_agent_situated_bootstrap import DataAgentSituatedRuntime
from apps.api_server import data_agent_situated_bootstrap as bootstrap_module
from tests.product.test_data_agent_situated_bootstrap import (
    _compose as _compose_data_agent_runtime,
)


NOW = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
SENTINEL = "resolver-key-MUST-NOT-LEAK-0A"


def _scope(
    *,
    principal_id: str = "principal-a",
    tenant_id: str = "tenant-a",
    workspace_id: str = "workspace-a",
) -> LedgerAccessScope:
    return LedgerAccessScope(
        principal_id=principal_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )


def _credential_snapshot(**updates: object) -> CredentialAuthorizationSnapshot:
    payload: dict[str, object] = {
        "credential_ref_id": "credential-a",
        "credential_ref_digest": "a" * 64,
        "owner_principal_id": "principal-a",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "provider_id": "source-adapter-a",
        "scopes": ("events:read", "situated:read"),
        "status": CredentialStatus.ACTIVE,
        "created_at": NOW - timedelta(days=1),
        "expires_at": NOW + timedelta(hours=1),
    }
    payload.update(updates)
    return CredentialAuthorizationSnapshot(**payload)  # type: ignore[arg-type]


def _receipt(scope: LedgerAccessScope, **updates: object) -> EnvironmentEventAdmissionReceipt:
    payload: dict[str, object] = {
        "schema_version": "1.1",
        "environment_event_id": "shared-event-id",
        "event_digest": "1" * 64,
        "event_origin_digest": "2" * 64,
        "credential_lease_digest": "3" * 64,
        "payload_attestation_digest": "4" * 64,
        "admission_policy_digest": "5" * 64,
        "mandate_id": f"mandate-{scope.tenant_id}",
        "environment_binding_id": "binding-1",
        "environment_binding_version": 1,
        "environment_binding_digest": "6" * 64,
        "correction_epoch": 1,
        "principal_id": scope.principal_id,
        "tenant_id": scope.tenant_id,
        "workspace_id": scope.workspace_id,
        "admitted_at": NOW,
        "issued_by": "event-admission-service/v1",
        "grants_authority": False,
        "authorizes_effects": False,
    }
    payload.update(updates)
    from agent_os_contracts import environment_event_admission_receipt_digest

    digest = environment_event_admission_receipt_digest(payload)
    return EnvironmentEventAdmissionReceipt.model_validate(
        {
            "receipt_id": f"event-admission:{digest}",
            "receipt_digest": digest,
            **payload,
        }
    )


def _trace(receipt: EnvironmentEventAdmissionReceipt) -> SituatedEvaluationTrace:
    return SituatedEvaluationTrace(
        trace_id=f"trace:{receipt.receipt_digest}",
        admission_receipt_digest=receipt.receipt_digest,
        event_id=receipt.environment_event_id,
        projection_id="projection-1",
        mandate_id=receipt.mandate_id,
        tenant_id=receipt.tenant_id,
        workspace_id=receipt.workspace_id,
        status=SituatedTraceStatus.PENDING,
        reason=SituatedTraceReason.ASSESSMENT_PENDING,
        result_binding_digest=None,
        delegation_attempt_count=0,
        committed_provider_call_attempted=None,
        input_tokens=None,
        output_tokens=None,
        duration_ms=0,
        recorded_at=NOW,
    )


def test_scope_and_credential_authorization_snapshot_are_closed_safe_contracts() -> None:
    scope = _scope()
    snapshot = _credential_snapshot()

    assert scope.model_dump() == {
        "schema_version": "1.0",
        "principal_id": "principal-a",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
    }
    assert snapshot.credential_ref_digest == "a" * 64
    assert "resolver_key" not in type(snapshot).model_fields
    assert "resolver_key" not in canonical_json(snapshot)
    assert SENTINEL not in repr(snapshot)
    assert content_digest(snapshot) == content_digest(
        CredentialAuthorizationSnapshot.model_validate_json(
            snapshot.model_dump_json(), strict=True
        )
    )


def test_credential_authorization_reader_never_returns_resolver_material() -> None:
    credential = CredentialRef(
        credential_ref_id="credential-a",
        owner_principal_id="principal-a",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        provider_id="source-adapter-a",
        resolver_key=SENTINEL,
        scopes=("events:read", "situated:read"),
        status=CredentialStatus.ACTIVE,
        created_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(hours=1),
    )
    reader: CredentialAuthorizationReader = CanonicalCredentialAuthorizationReader(
        (credential,)
    )

    resolved = reader.resolve_authorization("credential-a")

    assert resolved is not None
    assert resolved.credential_ref_digest == content_digest(credential)
    assert resolved.model_dump(exclude={"credential_ref_digest"}) == (
        _credential_snapshot().model_dump(exclude={"credential_ref_digest"})
    )
    assert SENTINEL not in repr(reader)
    assert SENTINEL not in repr(resolved)


def test_root_core_surface_does_not_export_full_credential_reader() -> None:
    import agent_os_core
    import agent_os_core.srl_event_authority as authority_module
    import agent_os_core.srl_event_store as store_module

    assert not hasattr(agent_os_core, "CanonicalCredentialRefReader")
    assert not hasattr(agent_os_core, "CredentialRefReader")
    assert not hasattr(authority_module, "CanonicalCredentialRefReader")
    assert not hasattr(authority_module, "CredentialRefReader")
    assert not hasattr(store_module, "SQLiteEventAdmissionStore")
    assert not hasattr(agent_os_core, "SituatedAssessmentStore")
    assert not hasattr(agent_os_core, "SQLiteSituatedAssessmentStore")
    assert agent_os_core.ScopedEventAdmissionReader is ScopedEventAdmissionReader

    from apps.api_server.app import AgentOSApplication

    assert "situational_control" not in inspect.signature(
        AgentOSApplication
    ).parameters
    assert "situated_proposal_service" not in inspect.signature(
        AgentOSApplication
    ).parameters


def test_application_has_no_direct_operational_proposal_bypass() -> None:
    from apps.api_server.app import AgentOSApplication

    source = inspect.getsource(AgentOSApplication)
    tree = ast.parse(source)
    assert "OperationalProposalService" not in source
    proposal_calls = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "propose"
    )
    assert proposal_calls
    assert all(
        ast.unparse(node.func) == "self._data_agent_situated_runtime.propose"
        for node in proposal_calls
    )
    assert tuple(
        inspect.signature(AgentOSApplication.propose_situated_work).parameters
    ) == (
        "self",
        "event_id",
        "projection_id",
        "admission_receipt_id",
    )


def test_application_public_surface_cannot_inject_situated_authority() -> None:
    from apps.api_server.app import AgentOSApplication

    public_parameters = set(inspect.signature(AgentOSApplication).parameters)
    assert public_parameters.isdisjoint(
        {
            "situated_runtime",
            "mandate_steward",
            "admission_writer",
            "origin_reader",
            "attestation_reader",
            "credential_reader",
        }
    )
    assert tuple(
        inspect.signature(
            AgentOSApplication.observe_admit_and_propose_data_agent_report
        ).parameters
    ) == ("self", "trace_id")
    combined_source = inspect.getsource(
        AgentOSApplication.observe_admit_and_propose_data_agent_report
    )
    assert "EnvironmentEventAdmissionReceipt" not in combined_source
    assert "OperationalProposalService" not in combined_source
    assert "self.tasks" not in combined_source
    assert "self.policy" not in combined_source
    assert "self.sandbox" not in combined_source


def test_uncomposed_combined_data_agent_operation_fails_before_task_state(
    tmp_path: Path,
) -> None:
    from apps.api_server.app import AgentOSApplication

    app = AgentOSApplication(database=tmp_path / "uncomposed.sqlite3")

    with pytest.raises(RuntimeError, match="situated runtime is not configured"):
        app.observe_admit_and_propose_data_agent_report("trace-1")

    assert app.store.list_task_ids() == ()


def test_situated_runtime_binding_rejects_fake_or_wrong_principal_scope(
    tmp_path: Path,
) -> None:
    from apps.api_server.app import AgentOSApplication

    principal = PrincipalIdentity(
        principal_id="principal-a",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=NOW,
    )

    class _FakeRuntime:
        principal_scope = ("principal-a", "tenant-a", "workspace-a")

    with pytest.raises(TypeError, match="Data Agent situated runtime"):
        AgentOSApplication._with_data_agent_situated_runtime(
            situated_runtime=_FakeRuntime(),  # type: ignore[arg-type]
            principal=principal,
            database=tmp_path / "fake.sqlite3",
            workspace=tmp_path,
        )

    with pytest.raises(TypeError, match="composition"):
        DataAgentSituatedRuntime._from_composition(
            adapter=_FakeRuntime(),  # type: ignore[arg-type]
            admission=object(),  # type: ignore[arg-type]
            steward=object(),  # type: ignore[arg-type]
        )

    runtime, _, _, _ = _compose_data_agent_runtime(tmp_path)
    with pytest.raises(SituationalScopeMismatch, match="scope does not match"):
        AgentOSApplication._with_data_agent_situated_runtime(
            situated_runtime=runtime,
            principal=principal,
            database=tmp_path / "wrong-scope.sqlite3",
            workspace=tmp_path,
        )


@pytest.mark.parametrize("sensitive_option", ("data_agent_reports", "situational_trust"))
def test_situated_runtime_binding_rejects_second_trust_chain(
    tmp_path: Path,
    sensitive_option: str,
) -> None:
    from apps.api_server.app import AgentOSApplication

    runtime, _, _, _ = _compose_data_agent_runtime(tmp_path)
    principal = PrincipalIdentity(
        principal_id="principal:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=NOW,
    )

    with pytest.raises(ValueError, match="second situated trust chain"):
        cast(Any, AgentOSApplication._with_data_agent_situated_runtime)(
            situated_runtime=runtime,
            principal=principal,
            database=tmp_path / "application.sqlite3",
            workspace=tmp_path,
            **{sensitive_option: object()},
        )


def test_situated_runtime_composition_rejects_mixed_reader_chain(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    first_path.mkdir()
    second_path.mkdir()
    first, _, _, _ = _compose_data_agent_runtime(first_path)
    second, _, _, _ = _compose_data_agent_runtime(second_path)

    with pytest.raises(TypeError, match="reader chain"):
        DataAgentSituatedRuntime._from_composition(
            adapter=first._adapter,
            admission=second._admission,
            steward=first._steward,
            envelope_adapter=first._envelope_adapter,
            workload_identity_adapter=first._workload_identity_adapter,
            composition_seal=bootstrap_module._RUNTIME_COMPOSITION_SEAL,
        )


def test_scoped_event_ledgers_allow_same_event_id_without_cross_scope_dos(
    tmp_path: Path,
) -> None:
    database = tmp_path / "scoped.sqlite3"
    scope_a = _scope()
    scope_b = _scope(
        principal_id="principal-b", tenant_id="tenant-b", workspace_id="workspace-b"
    )
    reader_a, writer_a = _create_event_admission_store(database, scope=scope_a)
    reader_b, writer_b = _create_event_admission_store(database, scope=scope_b)
    receipt_a, receipt_b = _receipt(scope_a), _receipt(scope_b)

    writer_a.persist_receipt(receipt_a)
    writer_b.persist_receipt(receipt_b)

    assert reader_a.by_event_id("shared-event-id") == receipt_a
    assert reader_b.by_event_id("shared-event-id") == receipt_b


def test_scoped_reader_hides_foreign_receipt_event_and_trace(
    tmp_path: Path,
) -> None:
    database = tmp_path / "scoped.sqlite3"
    scope_a = _scope()
    scope_b = _scope(
        principal_id="principal-b", tenant_id="tenant-b", workspace_id="workspace-b"
    )
    reader_a, writer_a = _create_event_admission_store(database, scope=scope_a)
    reader_b, _ = _create_event_admission_store(database, scope=scope_b)
    receipt = writer_a.persist_receipt(_receipt(scope_a))
    trace = writer_a.begin_trace(_trace(receipt))

    assert reader_b.by_receipt_id(receipt.receipt_id) is None
    assert reader_b.by_event_id(receipt.environment_event_id) is None
    assert reader_b.by_trace_id(trace.trace_id) is None
    assert reader_a.by_trace_id(trace.trace_id) == trace


def test_by_id_scope_filter_precedes_foreign_canonical_decode(tmp_path: Path) -> None:
    database = tmp_path / "scope-before-decode.sqlite3"
    owner_scope = _scope()
    foreign_scope = _scope(
        principal_id="principal-b", tenant_id="tenant-b", workspace_id="workspace-b"
    )
    owner_reader, _ = _create_event_admission_store(database, scope=owner_scope)
    _, foreign_writer = _create_event_admission_store(database, scope=foreign_scope)
    foreign_receipt = foreign_writer.persist_receipt(_receipt(foreign_scope))
    foreign_trace = foreign_writer.begin_trace(_trace(foreign_receipt))

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE srl_event_admission_receipts SET canonical_json = ? WHERE receipt_id = ?",
            (b"RAW-FOREIGN-RECEIPT-CORRUPTION", foreign_receipt.receipt_id),
        )
        connection.execute(
            "UPDATE srl_situated_evaluation_traces SET canonical_json = ? WHERE trace_id = ?",
            (b"RAW-FOREIGN-TRACE-CORRUPTION", foreign_trace.trace_id),
        )
        connection.commit()
        before = tuple(connection.iterdump())
    finally:
        connection.close()

    assert owner_reader.by_receipt_id("absent") is None
    assert owner_reader.by_receipt_id(foreign_receipt.receipt_id) is None
    assert owner_reader.by_trace_id("absent") is None
    assert owner_reader.by_trace_id(foreign_trace.trace_id) is None

    connection = sqlite3.connect(database)
    try:
        assert tuple(connection.iterdump()) == before
    finally:
        connection.close()


def test_scoped_writer_rejects_foreign_scope_and_reader_rejects_scope_column_tamper(
    tmp_path: Path,
) -> None:
    database = tmp_path / "scoped.sqlite3"
    scope = _scope()
    reader, writer = _create_event_admission_store(database, scope=scope)
    foreign = _scope(
        principal_id="principal-b", tenant_id="tenant-b", workspace_id="workspace-b"
    )
    with pytest.raises(EventAdmissionPersistenceConflict, match="scope"):
        writer.persist_receipt(_receipt(foreign))

    _, foreign_writer = _create_event_admission_store(database, scope=foreign)
    foreign_receipt = foreign_writer.persist_receipt(_receipt(foreign))
    forged_trace = _trace(foreign_receipt).model_copy(
        update={"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id}
    )
    with pytest.raises(EventAdmissionPersistenceConflict, match="scope"):
        writer.begin_trace(forged_trace)

    receipt = writer.persist_receipt(_receipt(scope))
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE srl_event_admission_receipts SET tenant_id = 'tampered' WHERE receipt_id = ?",
            (receipt.receipt_id,),
        )
        connection.commit()
    finally:
        connection.close()
    # Scope is applied in SQL before canonical bytes are decoded, so a row
    # whose scope index no longer belongs to this reader is indistinguishable
    # from absent or foreign state.
    assert reader.by_receipt_id(receipt.receipt_id) is None


def test_scoped_reader_restart_and_concurrency_preserve_isolation(tmp_path: Path) -> None:
    database = tmp_path / "scoped.sqlite3"
    scope_a = _scope()
    scope_b = _scope(
        principal_id="principal-b", tenant_id="tenant-b", workspace_id="workspace-b"
    )
    _, writer_a = _create_event_admission_store(database, scope=scope_a)
    _, writer_b = _create_event_admission_store(database, scope=scope_b)
    receipt_a, receipt_b = _receipt(scope_a), _receipt(scope_b)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tuple(pool.map(lambda item: item[0].persist_receipt(item[1]), ((writer_a, receipt_a), (writer_b, receipt_b))))

    restarted_a = ScopedEventAdmissionReader(database, scope=scope_a)
    restarted_b = ScopedEventAdmissionReader(database, scope=scope_b)
    assert restarted_a.by_event_id("shared-event-id") == receipt_a
    assert restarted_b.by_event_id("shared-event-id") == receipt_b
    assert restarted_a.by_receipt_id(receipt_b.receipt_id) is None
    assert restarted_b.by_receipt_id(receipt_a.receipt_id) is None


def test_situated_store_exposes_only_scope_bound_assessment_facade(tmp_path: Path) -> None:
    store = SQLiteSituatedAssessmentStore(tmp_path / "situated.sqlite3")

    reader = store.scoped_reader(_scope())

    assert reader.scope == _scope()
    assert reader.record_by_input_binding("f" * 64) is None
    assert not hasattr(reader, "pause")
    assert not hasattr(reader, "revoke")
    assert not hasattr(reader, "_emit_guarded")


def test_legacy_unscoped_assessment_schema_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "legacy-situated.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE situated_assessment_records (
                assessment_id TEXT PRIMARY KEY,
                assessment_record_id TEXT NOT NULL UNIQUE,
                source_binding_digest TEXT NOT NULL UNIQUE,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                record_json TEXT NOT NULL
            )
            """
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(Exception, match="schema is invalid"):
        SQLiteSituatedAssessmentStore(database)


def test_task4_and_task5_reject_mismatched_scoped_ports_before_work(
    tmp_path: Path,
) -> None:
    scope_a = _scope()
    scope_b = _scope(
        principal_id="principal-b", tenant_id="tenant-b", workspace_id="workspace-b"
    )
    admission_reader, writer = _create_event_admission_store(
        tmp_path / "events.sqlite3", scope=scope_a
    )
    assessment_reader = SQLiteSituatedAssessmentStore(
        tmp_path / "assessment.sqlite3"
    ).scoped_reader(scope_b)

    with pytest.raises(ValueError, match="scope"):
        EnvironmentEventAdmissionService(
            trust=object(),  # type: ignore[arg-type]
            authority=assessment_reader,
            origins=object(),  # type: ignore[arg-type]
            leases=object(),  # type: ignore[arg-type]
            credentials=object(),  # type: ignore[arg-type]
            attestations=object(),  # type: ignore[arg-type]
            admission_reader=admission_reader,
            admission_writer=writer,
            principal_id=scope_a.principal_id,
            required_credential_scopes=frozenset({"events:read"}),
        )

    with pytest.raises(ValueError, match="scope"):
        MandateSteward(
            trust=object(),  # type: ignore[arg-type]
            authority=assessment_reader,
            proposal_service=object(),  # type: ignore[arg-type]
            admission_reader=admission_reader,
            trace_writer=writer,
            principal_id=scope_a.principal_id,
            clock=lambda: NOW,
        )
