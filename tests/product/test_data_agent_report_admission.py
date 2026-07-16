from __future__ import annotations

import json
import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    EnvironmentEvent,
    EventOriginRegistration,
    canonical_json,
    event_origin_registration_digest,
)
from agent_os_core import CanonicalCredentialAuthorizationReader
from apps.api_server.data_agent_report_adapter import (
    DataAgentReportAdapter,
    DataAgentReportAdapterError,
    DataAgentReportHttpRequest,
    DataAgentReportHttpResponse,
    DataAgentReportSourceConfig,
    SQLiteDataAgentReportStateStore,
)
from apps.api_server.data_agent_report_admission import (
    DataAgentReportAdmissionError,
    SQLiteDataAgentReportAdmissionMaterialStore,
    _DataAgentReportAdmissionRegistrar,
)


NOW = datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc)
ORIGIN = "http://127.0.0.1:8765"


def _credential(**updates: object) -> CredentialRef:
    values: dict[str, Any] = {
        "credential_ref_id": "credential:data-agent-report",
        "owner_principal_id": "principal:local",
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "provider_id": "data-agent-external-report",
        "resolver_key": "DATA_AGENT_EXTERNAL_REPORT_KEY",
        "scopes": (
            "reports:read",
            f"data-agent-origin:{ORIGIN}",
            "data-agent-tenant:source-tenant",
        ),
        "status": CredentialStatus.ACTIVE,
        "created_at": NOW - timedelta(days=1),
        "expires_at": NOW + timedelta(days=1),
    }
    values.update(updates)
    return CredentialRef(**values)


def _config(**updates: object) -> DataAgentReportSourceConfig:
    values: dict[str, Any] = {
        "source_id": "source:data-agent",
        "base_url": ORIGIN,
        "source_tenant_id": "source-tenant",
        "credential": _credential(),
        "principal_id": "principal:local",
        "target_tenant_id": "tenant:local",
        "target_workspace_id": "workspace:local",
        "mandate_id": "mandate:agent-os",
        "environment_binding_id": "binding:data-agent",
        "scope_ref": "mission:agent-os/product",
        "allow_loopback_http": True,
        "timeout_seconds": 3,
        "max_response_bytes": 16_384,
        "freshness_seconds": 300,
    }
    values.update(updates)
    return DataAgentReportSourceConfig(**values)


def _body(trace_id: str = "trace-1") -> bytes:
    return json.dumps(
        {
            "trace_id": trace_id,
            "audience": "external",
            "user_result": {
                "trace_id": trace_id,
                "audience": "external",
                "redaction": {"audience": "external", "applied": True},
                "business_action": {"trace_id": trace_id},
            },
        },
        separators=(",", ":"),
    ).encode()


class _Broker:
    def __init__(self, secret: str = "top-secret") -> None:
        self.secret = secret

    def resolve(self, credential: CredentialRef) -> str:
        del credential
        return self.secret


class _Transport:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def fetch(self, request: DataAgentReportHttpRequest) -> DataAgentReportHttpResponse:
        return DataAgentReportHttpResponse(
            status_code=200,
            headers={
                "Content-Type": "application/json",
                "Content-Encoding": "identity",
            },
            body=self.body,
            final_url=request.url,
        )


def _adapter(
    tmp_path: Path,
    *,
    config: DataAgentReportSourceConfig | None = None,
    clock=lambda: NOW,
) -> tuple[DataAgentReportAdapter, EnvironmentEvent]:
    config = config or _config()
    adapter = DataAgentReportAdapter(
        config,
        credential_broker=_Broker(),
        transport=_Transport(_body()),
        state_store=SQLiteDataAgentReportStateStore(tmp_path / "observations.sqlite3"),
        clock=clock,
    )
    return adapter, adapter.pull("trace-1").event


def _registrar(
    tmp_path: Path,
    adapter: DataAgentReportAdapter,
    *,
    credential: CredentialRef | None = None,
    store_scope: tuple[str, str, str] = (
        "principal:local",
        "tenant:local",
        "workspace:local",
    ),
    clock=lambda: NOW,
) -> _DataAgentReportAdmissionRegistrar:
    store = SQLiteDataAgentReportAdmissionMaterialStore(
        tmp_path / "admission.sqlite3",
        principal_id=store_scope[0],
        tenant_id=store_scope[1],
        workspace_id=store_scope[2],
    )
    return _DataAgentReportAdmissionRegistrar(
        adapter,
        store,
        CanonicalCredentialAuthorizationReader([credential or _credential()]),
        clock=clock,
    )


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("artifact", "tenant_id", "tenant:foreign"),
        ("artifact", "workspace_id", "workspace:foreign"),
        ("artifact", "location_ref", "data-agent-report://wrong/location"),
        ("event", "event_type_ref", "data-agent.external-report-tampered.v1"),
        ("event", "dedupe_key", "data-agent-report:wrong"),
        ("event", "occurred_at", NOW - timedelta(seconds=1)),
        ("evidence", "source_ref", "wrong:source:trace"),
        ("evidence", "relation", "untrusted-relation"),
    ],
)
def test_prepare_denies_any_event_envelope_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    field: str,
    value: object,
) -> None:
    adapter, event = _adapter(tmp_path)
    artifact = event.observation
    evidence = event.evidence[0]
    if target == "artifact":
        artifact = artifact.model_copy(update={field: value})
        event = event.model_copy(update={"observation": artifact})
    elif target == "evidence":
        evidence = evidence.model_copy(update={field: value})
        event = event.model_copy(update={"evidence": (evidence,)})
    else:
        event = event.model_copy(update={field: value})
    monkeypatch.setattr(adapter, "resolve_event", lambda event_id: event)

    with pytest.raises(DataAgentReportAdmissionError):
        _registrar(tmp_path, adapter).prepare(event.environment_event_id)


@pytest.mark.parametrize(
    "credential",
    [
        _credential(status=CredentialStatus.REVOKED),
        _credential(
            created_at=NOW + timedelta(hours=1),
            expires_at=NOW + timedelta(hours=2),
        ),
        _credential(expires_at=NOW),
        _credential(provider_id="wrong-provider"),
        _credential(scopes=("reports:read",)),
    ],
)
def test_prepare_denies_invalid_live_credential(
    tmp_path: Path, credential: CredentialRef
) -> None:
    adapter, event = _adapter(tmp_path)
    with pytest.raises(DataAgentReportAdmissionError):
        _registrar(tmp_path, adapter, credential=credential).prepare(
            event.environment_event_id
        )


def test_prepare_persists_exact_restart_stable_material(tmp_path: Path) -> None:
    adapter, event = _adapter(tmp_path)
    first = _registrar(tmp_path, adapter).prepare(event.environment_event_id)
    restarted, _ = _adapter(tmp_path)
    second = _registrar(
        tmp_path,
        restarted,
        clock=lambda: NOW + timedelta(hours=1),
    ).prepare(event.environment_event_id)
    assert canonical_json(first.origin) == canonical_json(second.origin)
    assert canonical_json(first.attestation) == canonical_json(second.attestation)


@pytest.mark.parametrize(
    "config_update",
    [
        {"max_response_bytes": 32_768},
        {"freshness_seconds": 301},
        {"scope_ref": "mission:agent-os/research"},
    ],
)
def test_existing_material_is_never_returned_after_config_or_policy_drift(
    tmp_path: Path, config_update: dict[str, object]
) -> None:
    adapter, event = _adapter(tmp_path)
    _registrar(tmp_path, adapter).prepare(event.environment_event_id)
    changed_path = tmp_path / "changed"
    changed_path.mkdir()
    changed, _ = _adapter(changed_path, config=_config(**config_update))
    adapter._admission_policy._descriptor = changed.admission_policy_descriptor  # type: ignore[attr-defined]
    with pytest.raises(DataAgentReportAdmissionError):
        _registrar(tmp_path, adapter).prepare(event.environment_event_id)


def test_store_scope_must_equal_adapter_principal_scope(tmp_path: Path) -> None:
    adapter, _ = _adapter(tmp_path)
    with pytest.raises(DataAgentReportAdmissionError):
        _registrar(
            tmp_path,
            adapter,
            store_scope=("principal:foreign", "tenant:local", "workspace:local"),
        )


def test_registrar_rejects_fake_duck_adapter_and_authorization_reader(
    tmp_path: Path,
) -> None:
    adapter, _ = _adapter(tmp_path)
    store = SQLiteDataAgentReportAdmissionMaterialStore(
        tmp_path / "admission.sqlite3",
        principal_id="principal:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
    )

    class FakeAdapter:
        principal_scope = adapter.principal_scope

        def resolve_event(self, event_id: str) -> EnvironmentEvent | None:
            return adapter.resolve_event(event_id)

    class FakeReader:
        def resolve_authorization(self, credential_ref_id: str) -> object:
            return object()

    with pytest.raises(TypeError):
        _DataAgentReportAdmissionRegistrar(
            FakeAdapter(),  # type: ignore[arg-type]
            store,
            CanonicalCredentialAuthorizationReader([_credential()]),
            clock=lambda: NOW,
        )
    with pytest.raises(TypeError):
        _DataAgentReportAdmissionRegistrar(
            adapter,
            store,
            FakeReader(),  # type: ignore[arg-type]
            clock=lambda: NOW,
        )


def test_registrar_public_operation_accepts_only_event_id() -> None:
    assert tuple(
        inspect.signature(_DataAgentReportAdmissionRegistrar.prepare).parameters
    ) == (
        "self",
        "event_id",
    )


def test_prepare_fails_when_bound_credential_reflection_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, event = _adapter(tmp_path)
    monkeypatch.setattr(
        adapter,
        "_assert_current_credential_unreflected",
        lambda body, assessed_at: (_ for _ in ()).throw(
            DataAgentReportAdapterError("reflected")
        ),
    )
    with pytest.raises(DataAgentReportAdmissionError, match="reflected"):
        _registrar(tmp_path, adapter).prepare(event.environment_event_id)


def test_corrupt_or_conflicting_row_fails_closed(tmp_path: Path) -> None:
    adapter, event = _adapter(tmp_path)
    _registrar(tmp_path, adapter).prepare(event.environment_event_id)
    with sqlite3.connect(tmp_path / "admission.sqlite3") as connection:
        connection.execute(
            "UPDATE data_agent_report_admission_material SET origin_blob = ?",
            (b"{}",),
        )
    with pytest.raises(DataAgentReportAdmissionError):
        _registrar(tmp_path, adapter).prepare(event.environment_event_id)


def test_valid_but_rebound_origin_row_fails_closed(tmp_path: Path) -> None:
    adapter, event = _adapter(tmp_path)
    _registrar(tmp_path, adapter).prepare(event.environment_event_id)
    with sqlite3.connect(tmp_path / "admission.sqlite3") as connection:
        row = connection.execute(
            "SELECT origin_blob FROM data_agent_report_admission_material"
        ).fetchone()
        assert row is not None
        payload = json.loads(bytes(row[0]))
        payload["source_id"] = "source:attacker"
        unsigned = {
            key: value
            for key, value in payload.items()
            if key not in {"registration_id", "registration_digest"}
        }
        digest = event_origin_registration_digest(unsigned)
        payload["registration_id"] = f"event-origin:{digest}"
        payload["registration_digest"] = digest
        rebound = EventOriginRegistration.model_validate(payload)
        connection.execute(
            "UPDATE data_agent_report_admission_material SET origin_blob = ?",
            (canonical_json(rebound).encode(),),
        )
    with pytest.raises(DataAgentReportAdmissionError, match="binding"):
        _registrar(tmp_path, adapter).prepare(event.environment_event_id)


def test_policy_descriptor_changes_for_every_acceptance_semantic(
    tmp_path: Path,
) -> None:
    adapter, _ = _adapter(tmp_path)
    baseline = adapter.admission_policy_descriptor
    changes = (
        {"source_id": "source:data-agent-v2"},
        {
            "base_url": "https://reports.example.test",
            "allow_loopback_http": False,
            "credential": _credential(
                scopes=(
                    "reports:read",
                    "data-agent-origin:https://reports.example.test",
                    "data-agent-tenant:source-tenant",
                )
            ),
        },
        {"max_response_bytes": 32_768},
        {"timeout_seconds": 4},
        {"freshness_seconds": 301},
        {
            "source_tenant_id": "other-source-tenant",
            "credential": _credential(
                scopes=(
                    "reports:read",
                    f"data-agent-origin:{ORIGIN}",
                    "data-agent-tenant:other-source-tenant",
                )
            ),
        },
        {"credential": _credential(resolver_key="ROTATED_REPORT_KEY")},
        {
            "principal_id": "principal:other",
            "credential": _credential(owner_principal_id="principal:other"),
        },
        {
            "target_tenant_id": "tenant:other",
            "credential": _credential(tenant_id="tenant:other"),
        },
        {
            "target_workspace_id": "workspace:other",
            "credential": _credential(workspace_id="workspace:other"),
        },
        {"mandate_id": "mandate:other"},
        {"environment_binding_id": "binding:other"},
        {"scope_ref": "mission:agent-os/research"},
    )
    for index, update in enumerate(changes):
        child = tmp_path / str(index)
        child.mkdir()
        changed, _ = _adapter(child, config=_config(**update))
        assert (
            changed.admission_policy_descriptor.config_digest != baseline.config_digest
        )


def test_existing_material_is_denied_after_adapter_version_drift(
    tmp_path: Path,
) -> None:
    adapter, event = _adapter(tmp_path)
    _registrar(tmp_path, adapter).prepare(event.environment_event_id)
    descriptor = adapter.admission_policy_descriptor
    adapter._admission_policy._descriptor = replace(  # type: ignore[attr-defined]
        descriptor, adapter_version="data-agent-external-report-adapter:v2"
    )
    with pytest.raises(DataAgentReportAdmissionError):
        _registrar(tmp_path, adapter).prepare(event.environment_event_id)


def test_single_row_is_atomic_and_idempotent(tmp_path: Path) -> None:
    adapter, event = _adapter(tmp_path)
    registrar = _registrar(tmp_path, adapter)
    assert registrar.prepare(event.environment_event_id) == registrar.prepare(
        event.environment_event_id
    )
    with sqlite3.connect(tmp_path / "admission.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM data_agent_report_admission_material"
        ).fetchone() == (1,)


def test_concurrent_prepare_commits_one_canonical_row(tmp_path: Path) -> None:
    adapter, event = _adapter(tmp_path)
    registrars = (
        _registrar(tmp_path, adapter, clock=lambda: NOW),
        _registrar(tmp_path, adapter, clock=lambda: NOW + timedelta(seconds=1)),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda registrar: registrar.prepare(event.environment_event_id),
                registrars,
            )
        )
    assert results[0] == results[1]
    with sqlite3.connect(tmp_path / "admission.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM data_agent_report_admission_material"
        ).fetchone() == (1,)
