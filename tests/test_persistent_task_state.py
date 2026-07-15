"""Stage-A contracts for persistent semantic task state.

These tests intentionally target the Research Track mechanism only.  They do
not exercise or make claims about the Product Runtime.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from aac.persistent_task_state import (
    Assertion,
    AssertionStatus,
    CommitmentState,
    CommitmentStatus,
    ConcurrentStateWrite,
    DecisionRecord,
    EntityState,
    EntityStatus,
    EpistemicClass,
    RecoveryDirective,
    StatePatchCandidate,
    StateOverflowError,
    TaskStateProjection,
    StateValidationError,
    TaskStateReducer,
    UnknownFieldError,
)


NOW = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)


def test_entity_schema_is_closed_and_immutable() -> None:
    entity = EntityState(
        entity_id="entity:api",
        kind="api_contract",
        object_version="v1",
        revision=1,
        observed_keys=("src/api.py:Client",),
        aliases=("Client",),
        status=EntityStatus.ACTIVE,
        evidence_refs=("artifact:api-v1",),
    )

    with pytest.raises(FrozenInstanceError):
        entity.object_version = "v2"  # type: ignore[misc]
    with pytest.raises(UnknownFieldError, match="hidden_truth"):
        EntityState.from_mapping(
            {
                "entity_id": "entity:api",
                "kind": "api_contract",
                "object_version": "v1",
                "revision": 1,
                "observed_keys": ("src/api.py:Client",),
                "aliases": (),
                "status": EntityStatus.ACTIVE,
                "evidence_refs": (),
                "hidden_truth": "v2",
            }
        )


def test_empty_snapshot_digest_is_stable() -> None:
    first = TaskStateReducer.empty("task:state-a")
    second = TaskStateReducer.empty("task:state-a")

    assert first.version == 0
    assert first.digest() == second.digest()
    assert len(first.digest()) == 64


def test_all_stage_a_records_require_typed_closed_values() -> None:
    assertion = Assertion(
        assertion_id="assertion:api-version",
        entity_id="entity:api",
        entity_version="v1",
        predicate="accepts_payload",
        value="schema-v1",
        epistemic_class=EpistemicClass.FACT,
        confidence=1.0,
        status=AssertionStatus.ACTIVE,
        valid_from=NOW,
        valid_to=None,
        transaction_time=NOW,
        transaction_version=0,
        evidence_refs=("artifact:api-v1",),
        provenance_refs=("source:runtime",),
    )
    commitment = CommitmentState(
        commitment_id="commitment:migrate",
        revision=1,
        deliverable="migrate client",
        status=CommitmentStatus.PENDING,
        precondition_assertion_ids=(assertion.assertion_id,),
        postconditions=("hidden tests pass",),
        evidence_requirements=("artifact:test-report",),
    )
    decision = DecisionRecord(
        decision_id="decision:update-client",
        revision=1,
        state_snapshot_digest="0" * 64,
        alternatives=("update", "ask"),
        selected_action="update",
        relied_on_assertion_ids=(assertion.assertion_id,),
        predicted_postconditions=("client speaks schema-v1",),
    )
    patch = StatePatchCandidate(
        patch_id="patch:1",
        task_id="task:state-a",
        base_version=0,
        base_digest="0" * 64,
        transaction_time=NOW,
        entities=(),
        assertions=(assertion,),
        commitments=(commitment,),
        decisions=(decision,),
    )

    assert patch.assertions == (assertion,)
    with pytest.raises(UnknownFieldError, match="oracle_label"):
        StatePatchCandidate.from_mapping(
            {
                "patch_id": "patch:1",
                "task_id": "task:state-a",
                "base_version": 0,
                "base_digest": "0" * 64,
                "transaction_time": NOW,
                "oracle_label": "assertion:api-version",
            }
        )


def test_untyped_collection_and_forged_status_cannot_bypass_reducer() -> None:
    with pytest.raises(StateValidationError, match="observed_keys must be a tuple"):
        EntityState(
            entity_id="entity:api",
            kind="api_contract",
            object_version="v1",
            revision=1,
            observed_keys=["src/api.py:Client"],  # type: ignore[arg-type]
        )

    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    forged = _assertion(
        "assertion:forged-terminal",
        "schema-v1",
        status=AssertionStatus.STALE,
    )

    with pytest.raises(StateValidationError, match="must enter as ACTIVE"):
        TaskStateReducer.apply(
            state,
            _patch(state, "patch:forged-terminal", assertions=(forged,)),
        )


def _entity(*, version: str = "v1", revision: int = 1) -> EntityState:
    return EntityState(
        entity_id="entity:api",
        kind="api_contract",
        object_version=version,
        revision=revision,
        observed_keys=(f"src/api.py:Client@{version}",),
        aliases=("Client",),
        evidence_refs=(f"artifact:api-{version}",),
    )


def _patch(
    snapshot,
    patch_id: str,
    *,
    entities: tuple[EntityState, ...] = (),
    assertions: tuple[Assertion, ...] = (),
    commitments: tuple[CommitmentState, ...] = (),
    decisions: tuple[DecisionRecord, ...] = (),
    refute_assertion_ids: tuple[str, ...] = (),
    tombstone_entity_ids: tuple[str, ...] = (),
    transaction_time: datetime = NOW,
) -> StatePatchCandidate:
    return StatePatchCandidate(
        patch_id=patch_id,
        task_id=snapshot.task_id,
        base_version=snapshot.version,
        base_digest=snapshot.digest(),
        transaction_time=transaction_time,
        entities=entities,
        assertions=assertions,
        commitments=commitments,
        decisions=decisions,
        refute_assertion_ids=refute_assertion_ids,
        tombstone_entity_ids=tombstone_entity_ids,
    )


def _assertion(
    assertion_id: str,
    value: str,
    *,
    entity_version: str = "v1",
    predicate: str = "accepts_payload",
    status: AssertionStatus = AssertionStatus.ACTIVE,
    depends_on: tuple[str, ...] = (),
    supersedes: str | None = None,
    transaction_time: datetime = NOW,
    valid_from: datetime = NOW,
    valid_to: datetime | None = None,
) -> Assertion:
    return Assertion(
        assertion_id=assertion_id,
        entity_id="entity:api",
        entity_version=entity_version,
        predicate=predicate,
        value=value,
        epistemic_class=EpistemicClass.FACT,
        confidence=1.0,
        status=status,
        valid_from=valid_from,
        valid_to=valid_to,
        transaction_time=transaction_time,
        transaction_version=0,
        evidence_refs=(f"artifact:{assertion_id}",),
        provenance_refs=("source:runtime",),
        depends_on_assertion_ids=depends_on,
        supersedes_assertion_id=supersedes,
    )


def _commitment(
    *,
    commitment_id: str = "commitment:migrate",
    status: CommitmentStatus = CommitmentStatus.PENDING,
    revision: int = 1,
    preconditions: tuple[str, ...] = (),
    depends_on: tuple[str, ...] = (),
) -> CommitmentState:
    return CommitmentState(
        commitment_id=commitment_id,
        revision=revision,
        deliverable="migrate client",
        status=status,
        precondition_assertion_ids=preconditions,
        postconditions=("hidden tests pass",),
        evidence_requirements=("artifact:test-report",),
        depends_on_commitment_ids=depends_on,
    )


def _decision(
    snapshot,
    *,
    decision_id: str = "decision:update-client",
    revision: int = 1,
    relied_on: tuple[str, ...] = (),
    predicted_postconditions: tuple[str, ...] = ("client speaks schema-v1",),
    dispatched: bool = False,
    receipt_ref: str | None = None,
    effect_verified: bool = False,
) -> DecisionRecord:
    return DecisionRecord(
        decision_id=decision_id,
        revision=revision,
        state_snapshot_digest=snapshot.digest(),
        alternatives=("update", "ask"),
        selected_action="update",
        relied_on_assertion_ids=relied_on,
        predicted_postconditions=predicted_postconditions,
        dispatched=dispatched,
        receipt_ref=receipt_ref,
        effect_verified=effect_verified,
    )


def test_reducer_uses_cas_and_preserves_append_only_patch_history() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    patch = _patch(empty, "patch:entity-v1", entities=(_entity(),))

    current = TaskStateReducer.apply(empty, patch)

    assert empty.version == 0
    assert current.version == 1
    assert current.head_patch_id == patch.patch_id
    assert current.applied_patch_ids == (patch.patch_id,)
    assert current.patch_digests == (patch.digest(),)
    assert current.entities == (_entity(),)

    stale = StatePatchCandidate(
        patch_id="patch:stale",
        task_id=empty.task_id,
        base_version=empty.version,
        base_digest=empty.digest(),
        transaction_time=NOW,
        entities=(_entity(version="v2", revision=2),),
    )
    with pytest.raises(ConcurrentStateWrite, match="CAS"):
        TaskStateReducer.apply(current, stale)


def test_patch_rejects_duplicate_entity_ids_without_multi_revision() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    duplicate_entity_patch = _patch(
        empty,
        "patch:duplicate-entity",
        entities=(
            _entity(version="v1", revision=1),
            _entity(version="v2", revision=2),
        ),
    )

    with pytest.raises(StateValidationError, match="duplicate entity ids"):
        TaskStateReducer.apply(empty, duplicate_entity_patch)

    assert empty.version == 0
    assert empty.entities == ()


def test_entity_revision_keeps_identity_keys_and_rehydrates_to_same_digest() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    first_patch = _patch(empty, "patch:entity-v1", entities=(_entity(),))
    first = TaskStateReducer.apply(empty, first_patch)
    second_patch = _patch(
        first,
        "patch:entity-v2",
        entities=(
            EntityState(
                entity_id="entity:api",
                kind="api_contract",
                object_version="v2",
                revision=2,
                observed_keys=("src/api_v2.py:ApiClient",),
                aliases=("ApiClient",),
                evidence_refs=("artifact:api-v2",),
            ),
        ),
    )

    final = TaskStateReducer.apply(first, second_patch)
    entity = final.entities[0]

    assert entity.object_version == "v2"
    assert entity.observed_keys == (
        "src/api.py:Client@v1",
        "src/api_v2.py:ApiClient",
    )
    assert entity.aliases == ("ApiClient", "Client")
    assert TaskStateReducer.rehydrate(
        "task:state-a", (first_patch, second_patch)
    ).digest() == final.digest()


def test_reducer_rejects_duplicate_patch_id_even_with_a_fresh_base() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    first = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    duplicate_id = _patch(
        first,
        "patch:entity",
        entities=(_entity(version="v2", revision=2),),
    )

    with pytest.raises(StateValidationError, match="duplicate patch_id"):
        TaskStateReducer.apply(first, duplicate_id)


def test_assertion_binds_transaction_time_and_current_entity_version() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    with_entity = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    assertion = _assertion("assertion:v1", "schema-v1")

    current = TaskStateReducer.apply(
        with_entity,
        _patch(with_entity, "patch:assertion", assertions=(assertion,)),
    )

    assert current.assertions[0].transaction_version == current.version

    wrong_time = _assertion(
        "assertion:backdated",
        "schema-v1",
        predicate="backdated",
        transaction_time=NOW - timedelta(seconds=1),
    )
    with pytest.raises(StateValidationError, match="transaction_time"):
        TaskStateReducer.apply(
            current,
            _patch(current, "patch:backdated", assertions=(wrong_time,)),
        )
    wrong_version = _assertion(
        "assertion:v2",
        "schema-v2",
        entity_version="v2",
        predicate="future-version",
    )
    with pytest.raises(StateValidationError, match="entity version"):
        TaskStateReducer.apply(
            current,
            _patch(current, "patch:future", assertions=(wrong_version,)),
        )


def test_valid_time_query_is_aware_half_open_and_non_mutating() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    boundary = NOW + timedelta(hours=1)
    state = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:valid-time",
            assertions=(
                _assertion(
                    "assertion:bounded",
                    "bounded",
                    predicate="bounded",
                    valid_from=NOW,
                    valid_to=boundary,
                ),
                _assertion(
                    "assertion:later",
                    "later",
                    predicate="later",
                    valid_from=boundary,
                ),
            ),
        ),
    )
    before_digest = state.digest()

    at_start = TaskStateReducer.assertions_valid_at(state, valid_time=NOW)
    at_boundary = TaskStateReducer.assertions_valid_at(
        state, valid_time=boundary
    )

    assert tuple(item.assertion_id for item in at_start) == (
        "assertion:bounded",
    )
    assert tuple(item.assertion_id for item in at_boundary) == (
        "assertion:later",
    )
    assert state.digest() == before_digest
    with pytest.raises(StateValidationError, match="timezone-aware"):
        TaskStateReducer.assertions_valid_at(
            state,
            valid_time=datetime(2026, 7, 15, 9, 0),
        )


def test_touching_valid_intervals_do_not_conflict_but_overlaps_do() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    boundary = NOW + timedelta(hours=1)
    touching = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:touching",
            assertions=(
                _assertion(
                    "assertion:before",
                    "schema-v1",
                    valid_from=NOW,
                    valid_to=boundary,
                ),
                _assertion(
                    "assertion:after",
                    "schema-v2",
                    valid_from=boundary,
                    valid_to=boundary + timedelta(hours=1),
                ),
            ),
        ),
    )
    assert {item.status for item in touching.assertions} == {
        AssertionStatus.ACTIVE
    }

    overlapping = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:overlapping",
            assertions=(
                _assertion(
                    "assertion:wide",
                    "schema-v1",
                    valid_from=NOW,
                    valid_to=boundary + timedelta(hours=1),
                ),
                _assertion(
                    "assertion:inside",
                    "schema-v2",
                    valid_from=boundary,
                    valid_to=boundary + timedelta(hours=2),
                ),
            ),
        ),
    )
    assert {item.status for item in overlapping.assertions} == {
        AssertionStatus.CONFLICTED
    }


def test_valid_time_query_respects_selected_transaction_snapshot() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    old = _assertion("assertion:old", "schema-v1")
    before_supersession = TaskStateReducer.apply(
        state, _patch(state, "patch:old", assertions=(old,))
    )
    after_supersession = TaskStateReducer.apply(
        before_supersession,
        _patch(
            before_supersession,
            "patch:new",
            assertions=(
                _assertion(
                    "assertion:new",
                    "schema-v2",
                    supersedes=old.assertion_id,
                ),
            ),
        ),
    )

    assert tuple(
        item.assertion_id
        for item in TaskStateReducer.assertions_valid_at(
            before_supersession, valid_time=NOW
        )
    ) == ("assertion:old",)
    assert tuple(
        item.assertion_id
        for item in TaskStateReducer.assertions_valid_at(
            after_supersession, valid_time=NOW
        )
    ) == ("assertion:new",)


def test_contradiction_is_explicit_conflict_not_latest_write_wins() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    state = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:schema-v1",
            assertions=(_assertion("assertion:v1", "schema-v1"),),
        ),
    )

    conflicted = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:schema-v2",
            assertions=(_assertion("assertion:v2", "schema-v2"),),
        ),
    )

    assert {item.status for item in conflicted.assertions} == {
        AssertionStatus.CONFLICTED
    }
    assert {item.value for item in conflicted.assertions} == {"schema-v1", "schema-v2"}


def test_supersession_cascades_stale_and_blocks_dependent_commitment() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    upstream = _assertion("assertion:upstream", "schema-v1")
    downstream = _assertion(
        "assertion:downstream",
        "client-compatible",
        predicate="client_compatibility",
        depends_on=(upstream.assertion_id,),
    )
    state = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:initial-model",
            assertions=(upstream, downstream),
            commitments=(_commitment(preconditions=(downstream.assertion_id,)),),
        ),
    )

    revised = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:supersede",
            assertions=(
                _assertion(
                    "assertion:upstream-v2",
                    "schema-v2",
                    supersedes=upstream.assertion_id,
                ),
            ),
        ),
    )
    by_id = {item.assertion_id: item for item in revised.assertions}

    assert by_id[upstream.assertion_id].status is AssertionStatus.SUPERSEDED
    assert by_id[downstream.assertion_id].status is AssertionStatus.STALE
    assert by_id["assertion:upstream-v2"].status is AssertionStatus.ACTIVE
    assert revised.commitments[0].status is CommitmentStatus.BLOCKED


def test_assertion_dependency_graph_rejects_cycles() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    first = _assertion(
        "assertion:first",
        "first",
        predicate="first",
        depends_on=("assertion:second",),
    )
    second = _assertion(
        "assertion:second",
        "second",
        predicate="second",
        depends_on=("assertion:first",),
    )

    with pytest.raises(StateValidationError, match="dependency cycle"):
        TaskStateReducer.apply(
            state,
            _patch(
                state,
                "patch:cyclic-assertions",
                assertions=(first, second),
            ),
        )


def test_refute_and_entity_tombstone_never_delete_history() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    assertion = _assertion("assertion:live", "schema-v1")
    state = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:claim",
            assertions=(assertion,),
            commitments=(_commitment(preconditions=(assertion.assertion_id,)),),
        ),
    )
    refuted = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:refute",
            refute_assertion_ids=(assertion.assertion_id,),
        ),
    )
    tombstoned = TaskStateReducer.apply(
        refuted,
        _patch(
            refuted,
            "patch:tombstone",
            tombstone_entity_ids=("entity:api",),
        ),
    )

    assert tombstoned.entities[0].status is EntityStatus.TOMBSTONED
    assert tombstoned.assertions[0].status is AssertionStatus.REFUTED
    assert tombstoned.commitments[0].status is CommitmentStatus.BLOCKED
    assert tombstoned.applied_patch_ids == (
        "patch:entity",
        "patch:claim",
        "patch:refute",
        "patch:tombstone",
    )


def test_entity_version_change_stales_old_assertions_and_blocks_commitment() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity-v1", entities=(_entity(),))
    )
    assertion = _assertion("assertion:v1", "schema-v1")
    state = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:model",
            assertions=(assertion,),
            commitments=(_commitment(preconditions=(assertion.assertion_id,)),),
        ),
    )

    updated = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:entity-v2",
            entities=(_entity(version="v2", revision=2),),
        ),
    )

    assert updated.assertions[0].status is AssertionStatus.STALE
    assert updated.commitments[0].status is CommitmentStatus.BLOCKED


def test_commitment_revision_can_advance_status_but_not_rewrite_contract() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    assertion = _assertion("assertion:ready", "yes", predicate="ready")
    state = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:model",
            assertions=(assertion,),
            commitments=(_commitment(preconditions=(assertion.assertion_id,)),),
        ),
    )

    advanced = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:commitment-progress",
            commitments=(
                _commitment(
                    status=CommitmentStatus.IN_PROGRESS,
                    revision=2,
                    preconditions=(assertion.assertion_id,),
                ),
            ),
        ),
    )
    assert advanced.commitments[0].status is CommitmentStatus.IN_PROGRESS

    rewritten = CommitmentState(
        commitment_id="commitment:migrate",
        revision=3,
        deliverable="silently changed deliverable",
        status=CommitmentStatus.IN_PROGRESS,
        precondition_assertion_ids=(assertion.assertion_id,),
        postconditions=("hidden tests pass",),
        evidence_requirements=("artifact:test-report",),
    )
    with pytest.raises(StateValidationError, match="status only"):
        TaskStateReducer.apply(
            advanced,
            _patch(
                advanced,
                "patch:rewrite-contract",
                commitments=(rewritten,),
            ),
        )


def test_commitment_dependency_blocking_cascades_transitively() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    assertion = _assertion("assertion:upstream-ready", "yes", predicate="ready")
    upstream = _commitment(
        commitment_id="commitment:upstream",
        preconditions=(assertion.assertion_id,),
    )
    middle = _commitment(
        commitment_id="commitment:middle",
        depends_on=(upstream.commitment_id,),
    )
    downstream = _commitment(
        commitment_id="commitment:downstream",
        depends_on=(middle.commitment_id,),
    )
    state = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:commitment-chain",
            assertions=(assertion,),
            commitments=(upstream, middle, downstream),
        ),
    )

    blocked = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:invalidate-upstream",
            refute_assertion_ids=(assertion.assertion_id,),
        ),
    )

    assert {item.status for item in blocked.commitments} == {
        CommitmentStatus.BLOCKED
    }


def test_projection_evicts_only_terminal_leaf_history() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    old = _assertion("assertion:old", "schema-v1")
    state = TaskStateReducer.apply(
        state, _patch(state, "patch:old", assertions=(old,))
    )
    state = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:new",
            assertions=(
                _assertion(
                    "assertion:new",
                    "schema-v2",
                    supersedes=old.assertion_id,
                ),
            ),
        ),
    )

    projection = TaskStateReducer.project(
        state, max_records=2, max_bytes=10_000
    )

    assert isinstance(projection, TaskStateProjection)
    assert projection.source_digest == state.digest()
    assert tuple(item.assertion_id for item in projection.assertions) == (
        "assertion:new",
    )
    assert projection.omitted_record_ids == ("assertion:old",)


def test_projection_fails_closed_when_protected_state_exceeds_budget() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    state = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:claims",
            assertions=(
                _assertion("assertion:one", "one", predicate="p1"),
                _assertion("assertion:two", "two", predicate="p2"),
            ),
        ),
    )

    with pytest.raises(StateOverflowError, match="STATE_OVERFLOW"):
        TaskStateReducer.project(state, max_records=2, max_bytes=10_000)
    with pytest.raises(StateOverflowError, match="STATE_OVERFLOW"):
        TaskStateReducer.project(state, max_records=10, max_bytes=32)


def test_projection_preserves_entity_needed_by_protected_stale_state() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    assertion = _assertion("assertion:required", "schema-v1")
    state = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:model",
            assertions=(assertion,),
            commitments=(_commitment(preconditions=(assertion.assertion_id,)),),
        ),
    )
    state = TaskStateReducer.apply(
        state,
        _patch(
            state,
            "patch:tombstone",
            tombstone_entity_ids=("entity:api",),
        ),
    )

    with pytest.raises(StateOverflowError, match="STATE_OVERFLOW"):
        TaskStateReducer.project(state, max_records=2, max_bytes=10_000)


def test_decision_binds_exact_snapshot_and_only_active_assertions() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    assertion = _assertion("assertion:ready", "yes", predicate="ready")
    state = TaskStateReducer.apply(
        state, _patch(state, "patch:assertion", assertions=(assertion,))
    )
    decision = _decision(state, relied_on=(assertion.assertion_id,))

    recorded = TaskStateReducer.apply(
        state, _patch(state, "patch:decision", decisions=(decision,))
    )

    assert recorded.decisions == (decision,)
    wrong_digest = DecisionRecord(
        decision_id="decision:wrong-snapshot",
        revision=1,
        state_snapshot_digest="0" * 64,
        alternatives=("update", "ask"),
        selected_action="update",
        relied_on_assertion_ids=(assertion.assertion_id,),
        predicted_postconditions=("client speaks schema-v1",),
    )
    with pytest.raises(StateValidationError, match="snapshot digest"):
        TaskStateReducer.apply(
            recorded,
            _patch(recorded, "patch:wrong-snapshot", decisions=(wrong_digest,)),
        )

    conflicted = TaskStateReducer.apply(
        recorded,
        _patch(
            recorded,
            "patch:conflict",
            assertions=(
                _assertion("assertion:not-ready", "no", predicate="ready"),
            ),
        ),
    )
    with pytest.raises(StateValidationError, match="ACTIVE assertion"):
        TaskStateReducer.apply(
            conflicted,
            _patch(
                conflicted,
                "patch:decision-on-conflict",
                decisions=(
                    _decision(
                        conflicted,
                        decision_id="decision:on-conflict",
                        relied_on=(assertion.assertion_id,),
                    ),
                ),
            ),
        )


def test_decision_revision_is_monotonic_and_cannot_rewrite_rationale() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    initial = _decision(state)
    state = TaskStateReducer.apply(
        state, _patch(state, "patch:decision", decisions=(initial,))
    )
    dispatched = replace(initial, revision=2, dispatched=True)
    state = TaskStateReducer.apply(
        state, _patch(state, "patch:dispatch", decisions=(dispatched,))
    )
    receipted = replace(
        dispatched,
        revision=3,
        receipt_ref="receipt:update-client",
    )
    state = TaskStateReducer.apply(
        state, _patch(state, "patch:receipt", decisions=(receipted,))
    )
    verified = replace(
        receipted,
        revision=4,
        effect_verified=True,
    )
    state = TaskStateReducer.apply(
        state, _patch(state, "patch:verified", decisions=(verified,))
    )

    assert state.decisions == (verified,)
    rewritten = DecisionRecord(
        decision_id=verified.decision_id,
        revision=5,
        state_snapshot_digest=verified.state_snapshot_digest,
        alternatives=verified.alternatives,
        selected_action="ask",
        relied_on_assertion_ids=verified.relied_on_assertion_ids,
        predicted_postconditions=verified.predicted_postconditions,
        dispatched=True,
        receipt_ref=verified.receipt_ref,
        effect_verified=True,
    )
    with pytest.raises(StateValidationError, match="execution state only"):
        TaskStateReducer.apply(
            state, _patch(state, "patch:rewrite-decision", decisions=(rewritten,))
        )


def test_recovery_never_blindly_replays_ambiguous_dispatched_effect() -> None:
    empty = TaskStateReducer.empty("task:state-a")
    state = TaskStateReducer.apply(
        empty, _patch(empty, "patch:entity", entities=(_entity(),))
    )
    initial = _decision(state)
    state = TaskStateReducer.apply(
        state, _patch(state, "patch:decision", decisions=(initial,))
    )
    dispatched = DecisionRecord(
        decision_id=initial.decision_id,
        revision=2,
        state_snapshot_digest=initial.state_snapshot_digest,
        alternatives=initial.alternatives,
        selected_action=initial.selected_action,
        relied_on_assertion_ids=initial.relied_on_assertion_ids,
        predicted_postconditions=initial.predicted_postconditions,
        dispatched=True,
    )
    state = TaskStateReducer.apply(
        state, _patch(state, "patch:dispatch", decisions=(dispatched,))
    )

    assert TaskStateReducer.recovery_directive(state) is RecoveryDirective.VERIFY_EFFECT

    second = _decision(
        state,
        decision_id="decision:second",
        predicted_postconditions=(),
    )
    state = TaskStateReducer.apply(
        state, _patch(state, "patch:second", decisions=(second,))
    )
    second_dispatched = DecisionRecord(
        decision_id=second.decision_id,
        revision=2,
        state_snapshot_digest=second.state_snapshot_digest,
        alternatives=second.alternatives,
        selected_action=second.selected_action,
        relied_on_assertion_ids=second.relied_on_assertion_ids,
        predicted_postconditions=(),
        dispatched=True,
    )
    state = TaskStateReducer.apply(
        state,
        _patch(state, "patch:second-dispatch", decisions=(second_dispatched,)),
    )

    assert TaskStateReducer.recovery_directive(state) is RecoveryDirective.ABSTAIN
