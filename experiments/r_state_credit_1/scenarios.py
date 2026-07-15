"""Deterministic NOT_EVIDENCE fixtures for R-STATE-CREDIT-1 Stage A."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from experiments.r_state_credit_1.contracts import (
    EventKind,
    EvidenceStatus,
    ObservableEvent,
    ScenarioFamily,
    ScenarioFixture,
)


BASE_TIME = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)


def _event(
    scenario_id: str,
    sequence: int,
    kind: EventKind,
    subject_ref: str,
    *,
    related_ref: str | None = None,
    object_version: str | None = None,
    predicate: str | None = None,
    value: str | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    depends_on_event_ids: tuple[str, ...] = (),
    target_event_ids: tuple[str, ...] = (),
    supersedes_event_id: str | None = None,
    action_ref: str | None = None,
    receipt_ref: str | None = None,
) -> ObservableEvent:
    return ObservableEvent(
        scenario_id=scenario_id,
        sequence=sequence,
        event_id=f"{scenario_id}:event:{sequence:02d}",
        observed_at=BASE_TIME + timedelta(minutes=sequence),
        kind=kind,
        subject_ref=subject_ref,
        related_ref=related_ref,
        object_version=object_version,
        predicate=predicate,
        value=value,
        valid_from=valid_from,
        valid_to=valid_to,
        depends_on_event_ids=depends_on_event_ids,
        target_event_ids=target_event_ids,
        supersedes_event_id=supersedes_event_id,
        action_ref=action_ref,
        receipt_ref=receipt_ref,
        evidence_refs=(f"visible:evidence:{scenario_id}:{sequence:02d}",),
    )


def _fixture(
    family: ScenarioFamily,
    events: tuple[ObservableEvent, ...],
    *,
    expected_outcome: str,
) -> ScenarioFixture:
    slug = family.value.lower().replace("_", "-")
    return ScenarioFixture(
        scenario_id=f"rsc1:{slug}",
        family=family,
        evidence_status=EvidenceStatus.NOT_EVIDENCE,
        observable_events=events,
        hidden_entity_key=f"hidden:rsc1:{slug}:canonical-entity",
        oracle_label=f"HIDDEN_{family.value}_EXPECTED",
        oracle_reason=f"referee-only reason for {slug}",
        expected_outcome=expected_outcome,
    )


def build_development_fixtures() -> tuple[ScenarioFixture, ...]:
    """Build seven deterministic development fixtures; never a result battery."""
    fixtures = (
        _alias_object_version_fixture(),
        _valid_transaction_time_fixture(),
        _contradiction_fixture(),
        _supersession_refutation_fixture(),
        _commitment_blockage_fixture(),
        _dispatch_effect_uncertainty_fixture(),
        _bounded_overflow_recovery_fixture(),
    )
    return tuple(sorted(fixtures, key=lambda fixture: fixture.family.value))


def _alias_object_version_fixture() -> ScenarioFixture:
    family = ScenarioFamily.ALIAS_OBJECT_VERSION_DRIFT
    scenario_id = "rsc1:alias-object-version-drift"
    events = (
        _event(
            scenario_id,
            1,
            EventKind.ENTITY_OBSERVED,
            "visible:client-handle",
            object_version="v1",
        ),
        _event(
            scenario_id,
            2,
            EventKind.ALIAS_OBSERVED,
            "visible:client-handle",
            related_ref="visible:ApiClient",
        ),
        _event(
            scenario_id,
            3,
            EventKind.ENTITY_OBSERVED,
            "visible:ApiClient",
            object_version="v2",
        ),
    )
    return _fixture(
        family,
        events,
        expected_outcome="track visible aliases while updating object version",
    )


def _valid_transaction_time_fixture() -> ScenarioFixture:
    family = ScenarioFamily.VALID_TRANSACTION_TIME
    scenario_id = "rsc1:valid-transaction-time"
    events = (
        _event(
            scenario_id,
            1,
            EventKind.ENTITY_OBSERVED,
            "visible:service-window",
            object_version="v1",
        ),
        _event(
            scenario_id,
            2,
            EventKind.ASSERTION_OBSERVED,
            "visible:service-window",
            object_version="v1",
            predicate="availability",
            value="scheduled",
            valid_from=BASE_TIME - timedelta(days=1),
            valid_to=BASE_TIME + timedelta(days=1),
        ),
    )
    return _fixture(
        family,
        events,
        expected_outcome="preserve distinct observed and valid timestamps",
    )


def _contradiction_fixture() -> ScenarioFixture:
    family = ScenarioFamily.CONTRADICTION
    scenario_id = "rsc1:contradiction"
    events = (
        _event(
            scenario_id,
            1,
            EventKind.ENTITY_OBSERVED,
            "visible:api",
            object_version="v1",
        ),
        _event(
            scenario_id,
            2,
            EventKind.ASSERTION_OBSERVED,
            "visible:api",
            object_version="v1",
            predicate="schema",
            value="v1",
            valid_from=BASE_TIME,
        ),
        _event(
            scenario_id,
            3,
            EventKind.ASSERTION_OBSERVED,
            "visible:api",
            object_version="v1",
            predicate="schema",
            value="v2",
            valid_from=BASE_TIME,
        ),
    )
    return _fixture(
        family,
        events,
        expected_outcome="retain both overlapping contradictory assertions",
    )


def _supersession_refutation_fixture() -> ScenarioFixture:
    family = ScenarioFamily.SUPERSESSION_REFUTATION_CASCADE
    scenario_id = "rsc1:supersession-refutation-cascade"
    first_id = f"{scenario_id}:event:02"
    replacement_id = f"{scenario_id}:event:04"
    events = (
        _event(
            scenario_id,
            1,
            EventKind.ENTITY_OBSERVED,
            "visible:api",
            object_version="v1",
        ),
        _event(
            scenario_id,
            2,
            EventKind.ASSERTION_OBSERVED,
            "visible:api",
            object_version="v1",
            predicate="schema",
            value="v1",
            valid_from=BASE_TIME,
        ),
        _event(
            scenario_id,
            3,
            EventKind.ASSERTION_OBSERVED,
            "visible:api",
            object_version="v1",
            predicate="client-compatible",
            value="yes",
            valid_from=BASE_TIME,
            depends_on_event_ids=(first_id,),
        ),
        _event(
            scenario_id,
            4,
            EventKind.ASSERTION_OBSERVED,
            "visible:api",
            object_version="v1",
            predicate="schema",
            value="v2",
            valid_from=BASE_TIME,
            supersedes_event_id=first_id,
        ),
        _event(
            scenario_id,
            5,
            EventKind.ASSERTION_REFUTED,
            "visible:api",
            target_event_ids=(replacement_id,),
        ),
    )
    return _fixture(
        family,
        events,
        expected_outcome="cascade invalidation after supersession and refutation",
    )


def _commitment_blockage_fixture() -> ScenarioFixture:
    family = ScenarioFamily.COMMITMENT_BLOCKAGE
    scenario_id = "rsc1:commitment-blockage"
    assertion_id = f"{scenario_id}:event:02"
    events = (
        _event(
            scenario_id,
            1,
            EventKind.ENTITY_OBSERVED,
            "visible:release",
            object_version="v1",
        ),
        _event(
            scenario_id,
            2,
            EventKind.ASSERTION_OBSERVED,
            "visible:release",
            object_version="v1",
            predicate="tests",
            value="passing",
            valid_from=BASE_TIME,
        ),
        _event(
            scenario_id,
            3,
            EventKind.COMMITMENT_OBSERVED,
            "visible:ship-release",
            value="ship only after tests pass",
            target_event_ids=(assertion_id,),
        ),
        _event(
            scenario_id,
            4,
            EventKind.ASSERTION_REFUTED,
            "visible:release",
            target_event_ids=(assertion_id,),
        ),
    )
    return _fixture(
        family,
        events,
        expected_outcome="block commitment after its visible precondition is refuted",
    )


def _dispatch_effect_uncertainty_fixture() -> ScenarioFixture:
    family = ScenarioFamily.DISPATCH_EFFECT_UNCERTAINTY
    scenario_id = "rsc1:dispatch-effect-uncertainty"
    events = (
        _event(
            scenario_id,
            1,
            EventKind.ENTITY_OBSERVED,
            "visible:deployment",
            object_version="v1",
        ),
        _event(
            scenario_id,
            2,
            EventKind.ACTION_DISPATCHED,
            "visible:deployment",
            action_ref="visible:deploy-v1",
            value="deployment may have started",
        ),
        _event(
            scenario_id,
            3,
            EventKind.INTERRUPTION_OBSERVED,
            "visible:deployment",
            action_ref="visible:deploy-v1",
            value="connection lost before receipt",
        ),
        _event(
            scenario_id,
            4,
            EventKind.RECOVERY_REQUESTED,
            "visible:deployment",
            action_ref="visible:deploy-v1",
            value="verify effect before any retry",
        ),
    )
    return _fixture(
        family,
        events,
        expected_outcome="verify ambiguous effect or abstain without replay",
    )


def _bounded_overflow_recovery_fixture() -> ScenarioFixture:
    family = ScenarioFamily.BOUNDED_OVERFLOW_RECOVERY
    scenario_id = "rsc1:bounded-overflow-recovery"
    events = tuple(
        _event(
            scenario_id,
            index,
            EventKind.ENTITY_OBSERVED,
            f"visible:resource:{index:02d}",
            object_version="v1",
        )
        for index in range(1, 17)
    ) + (
        _event(
            scenario_id,
            17,
            EventKind.RECOVERY_REQUESTED,
            "visible:state-projection",
            value="fail closed if protected state exceeds budget",
        ),
    )
    return _fixture(
        family,
        events,
        expected_outcome="surface overflow instead of silently dropping active state",
    )
