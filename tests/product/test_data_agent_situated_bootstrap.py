from __future__ import annotations

import inspect
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from agent_os_contracts import (
    CredentialAuthorizationSnapshot,
    CredentialStatus,
    EnvironmentBindingAuthorization,
    LedgerAccessScope,
    MandateRelevanceContextRef,
    RatifiedMandateRef,
    RelevanceAssessment,
    RelevanceAssessorRef,
    RelevanceDisposition,
    RelevanceUrgency,
    TaskDraftProposal,
    canonical_json,
    content_digest,
)
from agent_os_core import (
    CanonicalCredentialAuthorizationReader,
    SituationalTrustDenied,
    situated_input_binding_digest,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore
from apps.api_server.data_agent_report_admission import (
    DataAgentReportAdmissionError,
    SQLiteDataAgentReportAdmissionMaterialStore,
)
from apps.api_server.data_agent_report_adapter import (
    DataAgentReportAdapter,
    SQLiteDataAgentReportStateStore,
)
from apps.api_server import data_agent_situated_bootstrap as bootstrap_module
from apps.api_server.data_agent_situated_bootstrap import (
    DataAgentAdmissionFacade,
    DataAgentSituatedBootstrap,
    DataAgentSituatedRuntime,
)
from tests.product.test_data_agent_report_admission import (
    NOW,
    _adapter,
    _body,
    _Broker,
    _config,
    _credential,
    _Transport,
)
from tests.product.mandate_observation_support import (
    authorize_workspace_observation,
    create_workspace_record,
)


class _LiveCredentialReader:
    def __init__(self) -> None:
        self.value = CanonicalCredentialAuthorizationReader(
            [_credential()]
        ).resolve_authorization("credential:data-agent-report")
        self.calls = 0

    def resolve_authorization(
        self, credential_ref_id: str
    ) -> CredentialAuthorizationSnapshot | None:
        self.calls += 1
        assert credential_ref_id == "credential:data-agent-report"
        return self.value


class _SequenceCredentialReader:
    def __init__(self, values: list[CredentialAuthorizationSnapshot | None]) -> None:
        self._values = iter(values)
        self.calls = 0

    def resolve_authorization(
        self, credential_ref_id: str
    ) -> CredentialAuthorizationSnapshot | None:
        del credential_ref_id
        self.calls += 1
        return next(self._values)


def _adapter_with_credentials(
    tmp_path: Path,
    credentials: _LiveCredentialReader | _SequenceCredentialReader,
) -> DataAgentReportAdapter:
    return DataAgentReportAdapter(
        _config(),
        credential_broker=_Broker(),
        credential_authorizations=credentials,
        transport=_Transport(_body()),
        state_store=SQLiteDataAgentReportStateStore(tmp_path / "observations.sqlite3"),
        clock=lambda: NOW,
    )


def _mandate() -> RatifiedMandateRef:
    return RatifiedMandateRef(
        mandate_id="mandate:agent-os",
        version=1,
        mandate_digest="a" * 64,
        ratification_receipt_id="ratification:data-agent",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        owner_principal_id="principal:local",
        ratified_by="founder:local",
        ratified_at=NOW - timedelta(days=2),
        valid_from=NOW - timedelta(days=2),
        expires_at=NOW + timedelta(days=2),
        correction_epoch=7,
        authority_envelope_digest="b" * 64,
        allowed_environment_bindings=(
            EnvironmentBindingAuthorization(
                environment_binding_id="binding:data-agent",
                version=3,
                binding_digest="c" * 64,
            ),
        ),
        relevance_assessor=RelevanceAssessorRef(
            assessor_id="assessor:data-agent",
            version=1,
            policy_digest="d" * 64,
        ),
    )


class _Assessor:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def ref(self) -> RelevanceAssessorRef:
        return RelevanceAssessorRef(
            assessor_id="assessor:data-agent",
            version=1,
            policy_digest="d" * 64,
        )

    def assess(
        self,
        mandate: RatifiedMandateRef,
        binding: EnvironmentBindingAuthorization,
        event: Any,
        projection: Any,
        *,
        assessed_at: Any,
        working_set: Any = None,
    ) -> RelevanceAssessment:
        self.calls += 1
        return RelevanceAssessment(
            assessment_id=f"assessment:{event.environment_event_id}",
            environment_event_id=event.environment_event_id,
            event_observation_digest=event.observation.content_digest,
            projection_id=projection.projection_id,
            projection_digest=projection.projection_artifact.content_digest,
            mandate_id=mandate.mandate_id,
            mandate_version=mandate.version,
            mandate_digest=mandate.mandate_digest,
            environment_binding_id=binding.environment_binding_id,
            environment_binding_version=binding.version,
            environment_binding_digest=binding.binding_digest,
            correction_epoch=mandate.correction_epoch,
            assessor=mandate.relevance_assessor,
            input_binding_digest=situated_input_binding_digest(
                mandate,
                binding,
                event,
                projection,
                mandate.relevance_assessor,
                working_set,
            ),
            tenant_id=event.tenant_id,
            workspace_id=event.workspace_id,
            disposition=RelevanceDisposition.CREATE_TASK,
            uncertainty_summary="bounded",
            urgency=RelevanceUrgency.MEDIUM,
            expected_loss_of_delay="bounded",
            attention_budget_seconds=30,
            rationale="bounded test assessment",
            evidence_ids=tuple(item.evidence_id for item in event.evidence)
            + tuple(item.evidence_id for item in projection.evidence),
            proposed_goal_statement="Review the admitted report",
            known_facts=("report admitted",),
            unknown_facts=("business priority",),
            acquisition_attempts=("read projection",),
            bounded_options=("review",),
            minimum_external_input=None,
            continuable_work=("prepare draft",),
            assessed_at=assessed_at,
        )


def _authorized_control(
    tmp_path: Path,
    adapter: DataAgentReportAdapter,
    assessor: _Assessor,
) -> SQLiteSituatedAssessmentStore:
    authority_database = tmp_path / "authority.sqlite3"
    create_workspace_record(authority_database, tmp_path, adapter=adapter, now=NOW)
    authorize_workspace_observation(
        authority_database,
        tmp_path,
        adapter=adapter,
        assessor=assessor.ref,
        context=MandateRelevanceContextRef(
            relevance_context_id="context:test-data-agent",
            version=1,
            content_digest="f" * 64,
        ),
        now=NOW,
    )
    return SQLiteSituatedAssessmentStore(authority_database)


def _compose(
    tmp_path: Path,
) -> tuple[
    DataAgentSituatedRuntime,
    _LiveCredentialReader,
    _Assessor,
    SQLiteSituatedAssessmentStore,
]:
    credentials = _LiveCredentialReader()
    adapter = _adapter_with_credentials(tmp_path, credentials)
    assessor = _Assessor()
    control = _authorized_control(tmp_path, adapter, assessor)
    material_store = SQLiteDataAgentReportAdmissionMaterialStore(
        tmp_path / "material.sqlite3",
        principal_id="principal:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
    )
    runtime = DataAgentSituatedBootstrap.compose(
        adapter=adapter,
        material_store=material_store,
        credentials=credentials,
        control=control,
        assessor=assessor,
        admission_database=tmp_path / "receipts.sqlite3",
        clock=lambda: NOW,
    )
    return runtime, credentials, assessor, control


def test_compose_returns_narrow_runtime_and_real_receipt_required_proposal(
    tmp_path: Path,
) -> None:
    runtime, credentials, assessor, _ = _compose(tmp_path)

    bundle = runtime.observe_report("trace-1")
    receipt = runtime.admit_event(bundle.event.environment_event_id)
    proposal = runtime.propose(
        bundle.event.environment_event_id,
        bundle.projection.projection_id,
        receipt.receipt_id,
    )
    record = runtime.propose_record(
        bundle.event.environment_event_id,
        bundle.projection.projection_id,
        receipt.receipt_id,
    )

    assert type(runtime) is DataAgentSituatedRuntime
    assert isinstance(proposal, TaskDraftProposal)
    assert runtime.resolve_assessment_record(content_digest(record)) == record
    assert runtime.resolve_assessment_record("0" * 64) is None
    assert receipt.environment_event_id == bundle.event.environment_event_id
    assert credentials.calls == 4
    assert assessor.calls == 1
    assert tuple(
        inspect.signature(DataAgentAdmissionFacade.admit_event).parameters
    ) == (
        "self",
        "event_id",
    )
    assert set(name for name in dir(runtime) if not name.startswith("_")) == {
        "admit_event",
        "assert_observation_authority",
        "observe_report",
        "principal_scope",
        "propose",
        "propose_record",
        "resolve_assessment_record",
        "propose_authenticated_protocol_envelope",
    }


def test_active_perception_authority_snapshot_fails_after_live_pause(
    tmp_path: Path,
) -> None:
    runtime, _, _, control = _compose(tmp_path)
    before = runtime.assert_observation_authority()
    assert len(before) == 64

    control.pause(
        "mandate:agent-os",
        expected_epoch=0,
        principal_id="principal:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
    )

    with pytest.raises(SituationalTrustDenied):
        runtime.assert_observation_authority()
    assert runtime.principal_scope == (
        "principal:local",
        "tenant:local",
        "workspace:local",
    )
    assert type(runtime.principal_scope) is tuple
    with pytest.raises(AttributeError):
        setattr(runtime, "principal_scope", ("forged", "forged", "forged"))


def test_restart_replays_exact_receipt_bytes(tmp_path: Path) -> None:
    runtime, _, _, _ = _compose(tmp_path)
    bundle = runtime.observe_report("trace-1")
    first = runtime.admit_event(bundle.event.environment_event_id)

    restarted, _, _, _ = _compose(tmp_path)
    second = restarted.admit_event(bundle.event.environment_event_id)

    assert canonical_json(second).encode() == canonical_json(first).encode()
    assert second.credential_lease_digest == first.credential_lease_digest


def test_propose_rejects_missing_receipt(tmp_path: Path) -> None:
    runtime, _, assessor, _ = _compose(tmp_path)
    bundle = runtime.observe_report("trace-1")

    try:
        runtime.propose(
            bundle.event.environment_event_id,
            bundle.projection.projection_id,
            "event-admission:missing",
        )
    except SituationalTrustDenied:
        pass
    else:
        raise AssertionError("proposal must require a durable admission receipt")

    assert assessor.calls == 0


def test_composition_scope_is_derived_from_adapter(tmp_path: Path) -> None:
    runtime, _, _, _ = _compose(tmp_path)
    assert not hasattr(runtime, "principal")
    assert not hasattr(runtime, "control")
    assert set(LedgerAccessScope.model_fields) == {
        "schema_version",
        "principal_id",
        "tenant_id",
        "workspace_id",
    }


def test_public_facade_constructor_has_no_authority_injection_parameters() -> None:
    forbidden = {
        "authority",
        "credentials",
        "admission_reader",
        "admission_writer",
        "registrar",
        "trust",
    }
    assert forbidden.isdisjoint(inspect.signature(DataAgentAdmissionFacade).parameters)


def test_public_constructors_cannot_inject_authority_or_steward() -> None:
    forged = bootstrap_module._AdmissionState(
        registrar=None,  # type: ignore[arg-type]
        trust=None,  # type: ignore[arg-type]
        authority=None,  # type: ignore[arg-type]
        credentials=None,  # type: ignore[arg-type]
        reader=None,  # type: ignore[arg-type]
        writer=None,
        required_scopes=frozenset({"forged"}),
        clock=lambda: NOW,
    )
    with pytest.raises(TypeError):
        cast(Any, DataAgentAdmissionFacade)(forged)
    with pytest.raises(TypeError):
        cast(Any, DataAgentSituatedRuntime)(
            adapter=None,  # type: ignore[arg-type]
            admission=None,  # type: ignore[arg-type]
            steward=None,  # type: ignore[arg-type]
        )


def test_composition_rejects_distinct_adapter_and_admission_credential_readers(
    tmp_path: Path,
) -> None:
    adapter, _ = _adapter(tmp_path)

    with pytest.raises(TypeError, match="credential.*reader"):
        DataAgentSituatedBootstrap.compose(
            adapter=adapter,
            material_store=SQLiteDataAgentReportAdmissionMaterialStore(
                tmp_path / "material.sqlite3",
                principal_id="principal:local",
                tenant_id="tenant:local",
                workspace_id="workspace:local",
            ),
            credentials=_LiveCredentialReader(),
            control=SQLiteSituatedAssessmentStore(
                tmp_path / "authority.sqlite3", mandates=(_mandate(),)
            ),
            assessor=_Assessor(),
            admission_database=tmp_path / "receipts.sqlite3",
            clock=lambda: NOW,
        )


@pytest.mark.parametrize(
    "mandate",
    [
        _mandate(),
        _mandate().model_copy(
            update={"ratification_receipt_id": "mandate-ratification:forged"}
        ),
    ],
)
def test_product_composition_rejects_unverified_and_prefix_forged_mandates(
    tmp_path: Path, mandate: RatifiedMandateRef
) -> None:
    credentials = _LiveCredentialReader()
    adapter = _adapter_with_credentials(tmp_path, credentials)
    with pytest.raises(SituationalTrustDenied, match="observation authorization"):
        DataAgentSituatedBootstrap.compose(
            adapter=adapter,
            material_store=SQLiteDataAgentReportAdmissionMaterialStore(
                tmp_path / "material.sqlite3",
                principal_id="principal:local",
                tenant_id="tenant:local",
                workspace_id="workspace:local",
            ),
            credentials=credentials,
            control=SQLiteSituatedAssessmentStore(
                tmp_path / "unverified.sqlite3", mandates=(mandate,)
            ),
            assessor=_Assessor(),
            admission_database=tmp_path / "receipts.sqlite3",
            clock=lambda: NOW,
        )


def test_live_credential_drift_during_admission_denies_without_receipt(
    tmp_path: Path,
) -> None:
    active = CanonicalCredentialAuthorizationReader(
        [_credential()]
    ).resolve_authorization("credential:data-agent-report")
    revoked = CanonicalCredentialAuthorizationReader(
        [_credential(status=CredentialStatus.REVOKED)]
    ).resolve_authorization("credential:data-agent-report")
    assert active is not None and revoked is not None
    credentials = _SequenceCredentialReader([active, active, revoked])
    adapter = _adapter_with_credentials(tmp_path, credentials)
    event = adapter.pull("trace-1").event
    assessor = _Assessor()
    control = _authorized_control(tmp_path, adapter, assessor)
    runtime = DataAgentSituatedBootstrap.compose(
        adapter=adapter,
        material_store=SQLiteDataAgentReportAdmissionMaterialStore(
            tmp_path / "material.sqlite3",
            principal_id="principal:local",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
        ),
        credentials=credentials,
        control=control,
        assessor=assessor,
        admission_database=tmp_path / "receipts.sqlite3",
        clock=lambda: NOW,
    )

    try:
        runtime.admit_event(event.environment_event_id)
    except SituationalTrustDenied:
        pass
    else:
        raise AssertionError("credential drift must fail closed")

    assert credentials.calls == 4
    with sqlite3.connect(tmp_path / "receipts.sqlite3") as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM srl_event_admission_receipts"
        ).fetchone()
    assert count == (0,)


def test_paused_mandate_denies_admission_before_receipt_or_assessment(
    tmp_path: Path,
) -> None:
    runtime, _, assessor, control = _compose(tmp_path)
    bundle = runtime.observe_report("trace-1")
    control.pause(
        "mandate:agent-os",
        expected_epoch=0,
        principal_id="principal:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
    )

    with pytest.raises((DataAgentReportAdmissionError, SituationalTrustDenied)):
        runtime.admit_event(bundle.event.environment_event_id)

    with sqlite3.connect(tmp_path / "receipts.sqlite3") as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM srl_event_admission_receipts"
        ).fetchone()
    assert count == (0,)
    assert assessor.calls == 0
