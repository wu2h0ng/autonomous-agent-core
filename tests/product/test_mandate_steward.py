from __future__ import annotations

import ast
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from agent_os_contracts import (
    ArtifactLocationClass,
    ArtifactRef,
    EnvironmentBindingAuthorization,
    EnvironmentEvent,
    EnvironmentEventAdmissionReceipt,
    EvidenceRef,
    EvidenceSourceKind,
    HelpRequest,
    LedgerAccessScope,
    OperationalProjectionRef,
    ProjectionEpistemicStatus,
    RatifiedMandateRef,
    RelevanceAssessment,
    RelevanceAssessorRef,
    RelevanceDisposition,
    RelevanceUrgency,
    SituatedTraceReason,
    SituatedTraceStatus,
    SituatedEvaluationTrace,
    TaskDraftProposal,
    content_digest,
    environment_event_admission_receipt_digest,
)
from agent_os_core import (
    InMemorySituationalTrustRegistry,
    MandateSteward,
    OperationalProposalService,
    SQLiteSituatedAssessmentStore,
    SituationalPersistenceConflict,
    SituationalTrustDenied,
    situated_input_binding_digest,
)
from agent_os_core.srl_event_store import _create_event_admission_store


NOW = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
SCOPE = LedgerAccessScope(
    principal_id="principal-1", tenant_id="tenant-1", workspace_id="workspace-1"
)
OBSERVATION = b'{"event":"observed"}'
PROJECTION = b'{"projection":"bounded"}'


def _artifact(name: str, raw: bytes) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=f"artifact:{name}",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        content_digest=hashlib.sha256(raw).hexdigest(),
        media_type="application/json",
        location_class=ArtifactLocationClass.OBJECT_STORE,
        location_ref=f"object://{name}",
        acl_scopes=("situated:read",),
        retention_policy="retain-30-days",
        created_by="test",
        created_at=NOW - timedelta(minutes=5),
    )


def _evidence(name: str, artifact: ArtifactRef) -> EvidenceRef:
    return EvidenceRef(
        evidence_id=f"evidence:{name}",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        source_kind=EvidenceSourceKind.ARTIFACT,
        source_ref=artifact.artifact_id,
        relation="supports",
        artifact_ids=(artifact.artifact_id,),
        created_by="test",
        created_at=NOW - timedelta(minutes=4),
    )


def _event() -> EnvironmentEvent:
    artifact = _artifact("event", OBSERVATION)
    return EnvironmentEvent(
        environment_event_id="event-1",
        environment_binding_id="binding-1",
        mandate_id="mandate-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        event_type_ref="test.event.v1",
        dedupe_key="event-1:v1",
        observation=artifact,
        evidence=(_evidence("event", artifact),),
        occurred_at=NOW - timedelta(minutes=4),
        recorded_at=NOW - timedelta(minutes=3),
    )


def _projection() -> OperationalProjectionRef:
    artifact = _artifact("projection", PROJECTION)
    return OperationalProjectionRef(
        projection_id="projection-1",
        environment_binding_id="binding-1",
        mandate_id="mandate-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        source_event_ids=("event-1",),
        projection_artifact=artifact,
        schema_uri="schema://projection/v1",
        version=1,
        scope_ref="mission:test",
        valid_from=NOW - timedelta(minutes=2),
        recorded_at=NOW - timedelta(minutes=2),
        fresh_until=NOW + timedelta(hours=1),
        evidence=(_evidence("projection", artifact),),
        epistemic_status=ProjectionEpistemicStatus.EVIDENCED,
        uncertainty_summary="bounded",
        compatibility_digest="d" * 64,
    )


def _mandate() -> RatifiedMandateRef:
    return RatifiedMandateRef(
        mandate_id="mandate-1",
        version=1,
        mandate_digest="a" * 64,
        ratification_receipt_id="ratification-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        owner_principal_id="principal-1",
        ratified_by="founder-1",
        ratified_at=NOW - timedelta(hours=1),
        valid_from=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=1),
        correction_epoch=3,
        authority_envelope_digest="b" * 64,
        allowed_environment_bindings=(
            EnvironmentBindingAuthorization(
                environment_binding_id="binding-1",
                version=4,
                binding_digest="c" * 64,
            ),
        ),
        relevance_assessor=RelevanceAssessorRef(
            assessor_id="assessor-1", version=1, policy_digest="e" * 64
        ),
    )


def _assessment(disposition: RelevanceDisposition) -> RelevanceAssessment:
    mandate = _mandate()
    binding = mandate.allowed_environment_bindings[0]
    return RelevanceAssessment(
        assessment_id=f"assessment:{disposition.value.lower()}",
        environment_event_id="event-1",
        event_observation_digest=_event().observation.content_digest,
        projection_id="projection-1",
        projection_digest=_projection().projection_artifact.content_digest,
        mandate_id="mandate-1",
        mandate_version=1,
        mandate_digest=mandate.mandate_digest,
        environment_binding_id="binding-1",
        environment_binding_version=4,
        environment_binding_digest=binding.binding_digest,
        correction_epoch=3,
        assessor=mandate.relevance_assessor,
        input_binding_digest=situated_input_binding_digest(
            mandate, binding, _event(), _projection(), mandate.relevance_assessor
        ),
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        disposition=disposition,
        uncertainty_summary="bounded",
        urgency=RelevanceUrgency.MEDIUM,
        expected_loss_of_delay="bounded",
        attention_budget_seconds=60,
        rationale="bounded",
        evidence_ids=("evidence:event", "evidence:projection"),
        proposed_goal_statement=(
            "Review without activation"
            if disposition
            in {RelevanceDisposition.INVESTIGATE, RelevanceDisposition.CREATE_TASK}
            else None
        ),
        known_facts=("event exists",),
        unknown_facts=("importance",),
        acquisition_attempts=("read projection",),
        bounded_options=("observe",),
        minimum_external_input=("choose" if disposition is RelevanceDisposition.HELP else None),
        continuable_work=("observe",),
        assessed_at=NOW,
    )


class _Assessor:
    def __init__(self, disposition: RelevanceDisposition, barrier: Barrier | None = None) -> None:
        self.assessment = _assessment(disposition)
        self.calls = 0
        self.barrier = barrier

    @property
    def ref(self) -> RelevanceAssessorRef:
        return self.assessment.assessor

    def assess(self, *args: Any, **kwargs: Any) -> RelevanceAssessment:
        self.calls += 1
        if self.barrier is not None:
            self.barrier.wait(timeout=3)
        return self.assessment


def _receipt() -> EnvironmentEventAdmissionReceipt:
    mandate = _mandate()
    binding = mandate.allowed_environment_bindings[0]
    payload: dict[str, Any] = {
        "schema_version": "1.1",
        "environment_event_id": "event-1",
        "event_digest": content_digest(_event()),
        "event_origin_digest": "1" * 64,
        "credential_lease_digest": "2" * 64,
        "payload_attestation_digest": "3" * 64,
        "admission_policy_digest": "4" * 64,
        "mandate_id": "mandate-1",
        "environment_binding_id": "binding-1",
        "environment_binding_version": 4,
        "environment_binding_digest": binding.binding_digest,
        "correction_epoch": 3,
        "principal_id": "principal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "admitted_at": NOW,
        "issued_by": "event-admission-service/v1",
        "grants_authority": False,
        "authorizes_effects": False,
    }
    digest = environment_event_admission_receipt_digest(payload)
    return EnvironmentEventAdmissionReceipt(
        receipt_id=f"event-admission:{digest}", receipt_digest=digest, **payload
    )


def _case(
    tmp_path: Path,
    disposition: RelevanceDisposition = RelevanceDisposition.CREATE_TASK,
) -> tuple[MandateSteward, Any, Any, _Assessor, SQLiteSituatedAssessmentStore]:
    event, projection, mandate = _event(), _projection(), _mandate()
    trust = InMemorySituationalTrustRegistry(
        bindings=(("principal-1", "tenant-1", "workspace-1", "mandate-1", "binding-1"),),
        artifacts=((event.observation, OBSERVATION), (projection.projection_artifact, PROJECTION)),
        evidence=(*event.evidence, *projection.evidence),
        events=(event,),
        projections=(projection,),
    )
    authority = SQLiteSituatedAssessmentStore(
        tmp_path / "authority.sqlite3", mandates=(mandate,)
    )
    assessor = _Assessor(disposition)
    proposal = OperationalProposalService(
        trust=trust, control=authority, assessor=assessor, principal_id="principal-1"
    )
    reader, writer = _create_event_admission_store(
        tmp_path / "admission.sqlite3", scope=SCOPE
    )
    writer.persist_receipt(_receipt())
    steward = MandateSteward(
        trust=trust,
        authority=authority.scoped_reader(SCOPE),
        proposal_service=proposal,
        admission_reader=reader,
        trace_writer=writer,
        principal_id="principal-1",
        clock=lambda: NOW,
    )
    return steward, reader, writer, assessor, authority


@pytest.mark.parametrize(
    ("disposition", "result_type", "reason"),
    [
        (RelevanceDisposition.INVESTIGATE, TaskDraftProposal, SituatedTraceReason.TASK_DRAFT),
        (RelevanceDisposition.CREATE_TASK, TaskDraftProposal, SituatedTraceReason.TASK_DRAFT),
        (RelevanceDisposition.HELP, HelpRequest, SituatedTraceReason.HELP_REQUEST),
        (RelevanceDisposition.IGNORE, type(None), SituatedTraceReason.NO_PROPOSAL),
        (RelevanceDisposition.OBSERVE, type(None), SituatedTraceReason.NO_PROPOSAL),
        (RelevanceDisposition.ABSTAIN, type(None), SituatedTraceReason.NO_PROPOSAL),
    ],
)
def test_exact_disposition_matrix_and_terminal_replay(
    tmp_path: Path, disposition: RelevanceDisposition, result_type: type[Any], reason: SituatedTraceReason
) -> None:
    steward, reader, _, assessor, _ = _case(tmp_path, disposition)
    receipt = _receipt()
    result = steward.observe_event("event-1", "projection-1", receipt.receipt_id)
    assert isinstance(result, result_type)
    assert assessor.calls == 1
    result2 = steward.observe_event("event-1", "projection-1", receipt.receipt_id)
    assert result2 == result
    assert assessor.calls == 1
    traces = [
        reader.by_trace_id(f"situated-evaluation:{content_digest({'admission_receipt_digest': receipt.receipt_digest, 'projection_id': 'projection-1'})}")
    ]
    assert traces[0] is not None
    assert traces[0].status is SituatedTraceStatus.COMPLETED
    assert traces[0].reason is reason
    assert traces[0].input_tokens is None and traces[0].output_tokens is None


def test_missing_material_fails_before_assessment(tmp_path: Path) -> None:
    steward, _, _, assessor, _ = _case(tmp_path)
    with pytest.raises(SituationalTrustDenied):
        steward.observe_event("missing", "projection-1", _receipt().receipt_id)
    with pytest.raises(SituationalTrustDenied):
        steward.observe_event("event-1", "missing", _receipt().receipt_id)
    with pytest.raises(SituationalTrustDenied):
        steward.observe_event("event-1", "projection-1", "missing")
    assert assessor.calls == 0


def test_foreign_principal_cannot_read_or_poison_pending_trace(tmp_path: Path) -> None:
    steward, reader, writer, assessor, _ = _case(tmp_path)
    receipt = _receipt()
    trace_id = f"situated-evaluation:{content_digest({'admission_receipt_digest': receipt.receipt_digest, 'projection_id': 'projection-1'})}"
    pending = writer.begin_trace(
        SituatedEvaluationTrace(
            trace_id=trace_id,
            admission_receipt_digest=receipt.receipt_digest,
            event_id="event-1",
            projection_id="projection-1",
            mandate_id="mandate-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
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
    )
    foreign_scope = LedgerAccessScope(
        principal_id="principal-foreign",
        tenant_id="tenant-foreign",
        workspace_id="workspace-foreign",
    )
    foreign_reader, foreign_writer = _create_event_admission_store(
        tmp_path / "admission.sqlite3", scope=foreign_scope
    )
    foreign_authority = SQLiteSituatedAssessmentStore(
        tmp_path / "foreign-authority.sqlite3"
    )
    attacker = MandateSteward(
        trust=steward._trust,  # type: ignore[attr-defined]
        authority=foreign_authority.scoped_reader(foreign_scope),
        proposal_service=steward._proposal_service,  # type: ignore[attr-defined]
        admission_reader=foreign_reader,
        trace_writer=foreign_writer,
        principal_id=foreign_scope.principal_id,
        clock=lambda: NOW,
    )

    with pytest.raises(SituationalTrustDenied):
        attacker.observe_event("event-1", "projection-1", receipt.receipt_id)

    assert foreign_reader.by_receipt_id(receipt.receipt_id) is None
    assert foreign_reader.by_trace_id(trace_id) is None
    assert reader.by_trace_id(trace_id) == pending
    assert assessor.calls == 0


def test_two_facades_share_process_single_flight(tmp_path: Path) -> None:
    steward, _, _, assessor, authority = _case(tmp_path)
    # A second facade over the same durable ports must coordinate with the first.
    second = MandateSteward(
        trust=steward._trust,  # type: ignore[attr-defined]
        authority=authority.scoped_reader(SCOPE),
        proposal_service=steward._proposal_service,  # type: ignore[attr-defined]
        admission_reader=steward._admission_reader,  # type: ignore[attr-defined]
        trace_writer=steward._trace_writer,  # type: ignore[attr-defined]
        principal_id="principal-1",
        clock=lambda: NOW,
    )
    receipt = _receipt()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(
                lambda facade: facade.observe_event("event-1", "projection-1", receipt.receipt_id),
                (steward, second),
            )
        )
    assert results[0] == results[1]
    assert assessor.calls == 1
    trace_id = f"situated-evaluation:{content_digest({'admission_receipt_digest': receipt.receipt_digest, 'projection_id': 'projection-1'})}"
    assert steward._admission_reader.by_trace_id(trace_id).delegation_attempt_count == 1  # type: ignore[union-attr,attr-defined]


def test_return_without_persisted_record_is_rejected_and_restart_reconciles(
    tmp_path: Path,
) -> None:
    steward, reader, _, _, authority = _case(tmp_path)

    class _Constant:
        def propose(self, *args: Any, **kwargs: Any) -> None:
            return None

    steward._proposal_service = _Constant()  # type: ignore[assignment,attr-defined]
    with pytest.raises(SituationalPersistenceConflict, match="without a persisted"):
        steward.observe_event("event-1", "projection-1", _receipt().receipt_id)
    trace_id = f"situated-evaluation:{content_digest({'admission_receipt_digest': _receipt().receipt_digest, 'projection_id': 'projection-1'})}"
    pending = reader.by_trace_id(trace_id)
    assert pending is not None and pending.status is SituatedTraceStatus.PENDING
    assert pending.delegation_attempt_count == 1

    assessor = _Assessor(RelevanceDisposition.CREATE_TASK)
    real = OperationalProposalService(
        trust=steward._trust,  # type: ignore[attr-defined]
        control=authority,
        assessor=assessor,
        principal_id="principal-1",
    )
    expected = real.propose("event-1", "projection-1", evaluated_at=NOW)
    steward._proposal_service = real  # type: ignore[attr-defined]
    assert steward.observe_event("event-1", "projection-1", _receipt().receipt_id) == expected
    assert assessor.calls == 1
    assert reader.by_trace_id(trace_id).delegation_attempt_count == 1  # type: ignore[union-attr]


def test_constant_return_after_persistence_is_rejected(tmp_path: Path) -> None:
    steward, reader, _, _, _ = _case(tmp_path)
    real = steward._proposal_service  # type: ignore[attr-defined]

    class _Mismatch:
        def propose(self, *args: Any, **kwargs: Any) -> None:
            real.propose(*args, **kwargs)
            return None

    steward._proposal_service = _Mismatch()  # type: ignore[assignment,attr-defined]
    with pytest.raises(SituationalPersistenceConflict, match="does not match"):
        steward.observe_event("event-1", "projection-1", _receipt().receipt_id)
    trace_id = f"situated-evaluation:{content_digest({'admission_receipt_digest': _receipt().receipt_digest, 'projection_id': 'projection-1'})}"
    assert reader.by_trace_id(trace_id).status is SituatedTraceStatus.PENDING  # type: ignore[union-attr]


def test_trace_completion_failure_reconciles_after_restart(tmp_path: Path) -> None:
    steward, reader, writer, assessor, _ = _case(tmp_path)

    class _FailFirstTransition:
        def __init__(self) -> None:
            self.failed = False

        def begin_trace(self, trace: Any) -> Any:
            return writer.begin_trace(trace)

        def increment_delegation_attempt(self, trace_id: str, **kwargs: Any) -> Any:
            return writer.increment_delegation_attempt(trace_id, **kwargs)

        def transition_trace(self, terminal: Any) -> Any:
            if not self.failed:
                self.failed = True
                raise SituationalPersistenceConflict("injected terminal write failure")
            return writer.transition_trace(terminal)

    steward._trace_writer = _FailFirstTransition()  # type: ignore[assignment,attr-defined]
    with pytest.raises(SituationalPersistenceConflict, match="injected"):
        steward.observe_event("event-1", "projection-1", _receipt().receipt_id)
    trace_id = f"situated-evaluation:{content_digest({'admission_receipt_digest': _receipt().receipt_digest, 'projection_id': 'projection-1'})}"
    pending = reader.by_trace_id(trace_id)
    assert pending is not None and pending.status is SituatedTraceStatus.PENDING
    assert pending.delegation_attempt_count == 1
    steward._trace_writer = writer  # type: ignore[attr-defined]
    assert isinstance(
        steward.observe_event("event-1", "projection-1", _receipt().receipt_id),
        TaskDraftProposal,
    )
    assert assessor.calls == 1
    assert reader.by_trace_id(trace_id).delegation_attempt_count == 1  # type: ignore[union-attr]


def test_completed_trace_rejects_current_authority_drift_without_mutation(
    tmp_path: Path,
) -> None:
    steward, reader, _, _, authority = _case(tmp_path)
    receipt = _receipt()
    steward.observe_event("event-1", "projection-1", receipt.receipt_id)
    trace_id = f"situated-evaluation:{content_digest({'admission_receipt_digest': receipt.receipt_digest, 'projection_id': 'projection-1'})}"
    before = reader.by_trace_id(trace_id)
    authority.pause("mandate-1", expected_epoch=3)
    with pytest.raises(SituationalTrustDenied):
        steward.observe_event("event-1", "projection-1", receipt.receipt_id)
    assert reader.by_trace_id(trace_id) == before


def test_terminal_replay_rejects_persisted_record_mutation(tmp_path: Path) -> None:
    steward, _, _, _, authority = _case(tmp_path)
    receipt = _receipt()
    steward.observe_event("event-1", "projection-1", receipt.receipt_id)

    scoped_authority = authority.scoped_reader(SCOPE)

    class _MutatingRead:
        scope = SCOPE

        def __getattr__(self, name: str) -> Any:
            return getattr(scoped_authority, name)

        def record_by_input_binding(self, digest: str) -> Any:
            record = scoped_authority.record_by_input_binding(digest)
            assert record is not None
            return record.model_copy(
                update={"recorded_at": record.recorded_at + timedelta(seconds=1)}
            )

    steward._authority = _MutatingRead()  # type: ignore[assignment,attr-defined]
    with pytest.raises(SituationalPersistenceConflict, match="result binding"):
        steward.observe_event("event-1", "projection-1", receipt.receipt_id)


def test_delegate_exception_leaves_incremented_pending_trace(tmp_path: Path) -> None:
    steward, reader, _, _, _ = _case(tmp_path)
    class _Boom:
        def propose(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("PROVIDER-RAW-EXCEPTION-MUST-NOT-LEAK-0A")
    steward._proposal_service = _Boom()  # type: ignore[assignment,attr-defined]
    with pytest.raises(SituationalPersistenceConflict) as captured:
        steward.observe_event("event-1", "projection-1", _receipt().receipt_id)
    assert "PROVIDER-RAW-EXCEPTION-MUST-NOT-LEAK-0A" not in str(captured.value)
    trace_id = f"situated-evaluation:{content_digest({'admission_receipt_digest': _receipt().receipt_digest, 'projection_id': 'projection-1'})}"
    trace = reader.by_trace_id(trace_id)
    assert trace is not None
    assert trace.status is SituatedTraceStatus.PENDING
    assert trace.delegation_attempt_count == 1
    assert trace.committed_provider_call_attempted is None


def test_module_has_no_effect_provider_or_capability_imports() -> None:
    path = Path(__file__).parents[2] / "packages/os_core/src/agent_os_core/mandate_steward.py"
    tree = ast.parse(path.read_text())
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any(
        token in name.lower()
        for name in imported
        for token in ("provider", "capability", "connector", "task_service", "execution")
    )
