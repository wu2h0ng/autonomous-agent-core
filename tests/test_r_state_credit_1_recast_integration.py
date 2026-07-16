"""Phase 1-3 integration tests for the R-STATE-CREDIT-1 recast.

These tests wire the interactive environment, episode generator, arm blinding,
actor interface, and authority verifier together end-to-end without any provider
calls, model inference, training, or external side effects.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from datetime import datetime, timezone

from experiments.r_state_credit_1.action_grammar import ActorAction
from experiments.r_state_credit_1.actor_interface import ActorRequest
from experiments.r_state_credit_1.arm_blinding import ArmBlinding, NEUTRAL_LABELS
from experiments.r_state_credit_1.arms import A3TypedStateArm
from experiments.r_state_credit_1.authority_artifacts import (
    ArchitectureAcceptanceArtifact,
    AuthorityArtifactBundle,
    C7AcceptanceArtifact,
    NativeFreezeLockArtifact,
    PreregAcceptanceArtifact,
    RunAuthorizationArtifact,
    compute_payload_digest,
)
from experiments.r_state_credit_1.authority_verifier import AuthorityVerifier
from experiments.r_state_credit_1.contracts import (
    ArmId,
    ArmInput,
    EventKind,
    ObservableEvent,
    ResourceBudget,
)
from experiments.r_state_credit_1.episode_generator import EpisodeGenerator
from experiments.r_state_credit_1.signature_backend import TestHmacBackend
from experiments.r_state_credit_1.trajectory_driver import (
    CheckpointRecord,
    run_checkpointed_episode as _run_checkpointed_episode,
)


FAMILY = "TEST_FAMILY"

# Same byte-level forbidden list as Phase 2 qualification tests.
_FORBIDDEN_SUBSTRINGS = (
    "A0",
    "A1",
    "A2",
    "A3",
    "full-log",
    "compressed",
    "typed-state",
    "full log",
    "rolling summary",
    "retrieval",
    "typed state",
)

# Directive hints that must not appear in actor request bytes or arm output notes (G6).
# These are the frozen G6 directive field names.  Environment vocabulary such as
# "rollback" or "retry" legitimately appears inside observation payloads (e.g. a
# recovery record or retry record) and is not a runner directive.
_DIRECTIVE_HINTS = (
    "recovery_directive",
    "action_hint",
    "recommended_action",
    "policy",  # arm-policy hints, not generic English
)

# Authority signer identities used for the integration bundle.
_BUILDER_IDENTITY = "builder:codex-1"
_PREREG_IDENTITY = "reviewer:prereg-1"
_ARCHITECTURE_IDENTITY = "reviewer:architecture-1"
_FREEZER_IDENTITY = "freezer:native-1"
_C7_IDENTITY = "c7-owner:security-1"
_AUTHORIZER_IDENTITY = "founder:cto-1"
_ALL_ALLOWED = {
    _PREREG_IDENTITY,
    _ARCHITECTURE_IDENTITY,
    _FREEZER_IDENTITY,
    _C7_IDENTITY,
    _AUTHORIZER_IDENTITY,
}

_SIGNED_AT = "2026-07-16T00:00:00+00:00"
_EXPIRES_AT = "2099-12-31T23:59:59+00:00"
_CANDIDATE_SHA = "a" * 40
_PREREG_SHA256 = "b" * 64


def test_end_to_end_no_provider(tmp_path: Path) -> None:
    """One family, three seeds: episode generator -> env -> blinding -> stub actor."""
    for seed_id in range(3):
        episode, records = _run_checkpointed_episode(
            FAMILY, seed_id, tmp_path / f"e2e-{seed_id}"
        )
        try:
            assert len(records) == 4
            blinding = ArmBlinding(episode._episode_seed)
            for record in records:
                # Every neutral label produced a request and response.
                assert set(record.requests.keys()) == set(NEUTRAL_LABELS)
                assert set(record.responses.keys()) == set(NEUTRAL_LABELS)

                # Reverse mapping resolves exactly the four real arms.
                assert set(record.resolved_actions.keys()) == set(ArmId)

                for label in NEUTRAL_LABELS:
                    request = record.requests[label]
                    response = record.responses[label]

                    # Action grammar is frozen and every response honors it.
                    assert isinstance(response.action, ActorAction)
                    assert response.action in tuple(ActorAction)

                    # Serialized request bytes must not contain real arm identity.
                    payload = request.to_canonical_json().encode("utf-8")
                    text = payload.decode("utf-8")
                    for substring in _FORBIDDEN_SUBSTRINGS:
                        assert substring not in text, (
                            f"seed={seed_id} checkpoint={record.checkpoint_ordinal} "
                            f"forbidden substring {substring!r} found in actor request"
                        )

                    # Reverse mapping matches the deterministic call order.
                    position = blinding.position_for_label(label)
                    expected_arm = blinding.arm_at_position(
                        record.checkpoint_ordinal, position
                    )
                    assert record.resolved_actions[expected_arm] == response.action
        finally:
            episode.cleanup()


def test_checkpoint_actions_are_recorded(tmp_path: Path) -> None:
    """After running an episode, exactly four checkpoints hold per-arm actions."""
    episode, records = _run_checkpointed_episode(FAMILY, 42, tmp_path / "recorded")
    try:
        assert len(records) == 4
        for index, record in enumerate(records):
            assert record.checkpoint_ordinal == index
            assert record.turn_index == episode.checkpoints[index]
            # One neutral request per position.
            assert len(record.requests) == 4
            assert all(isinstance(req, ActorRequest) for req in record.requests.values())
            # One resolved action per real arm.
            assert len(record.resolved_actions) == 4
            assert set(record.resolved_actions.keys()) == set(ArmId)
            for arm_id in ArmId:
                assert isinstance(
                    record.resolved_actions[arm_id], ActorAction
                ), f"missing action for {arm_id.value}"
    finally:
        episode.cleanup()


# ---------------------------------------------------------------------------
# Authority artifact helpers (self-contained for the integration test file)
# ---------------------------------------------------------------------------


def _fresh_backend() -> TestHmacBackend:
    return TestHmacBackend(master_secret=b"r-state-credit-1-integration-secret")


def _sign_artifact(
    artifact: Any,
    identity: str,
    backend: TestHmacBackend,
    witness_refs: tuple[str, ...] | None = None,
) -> None:
    principal, instance = identity.split(":", 1)
    if witness_refs is None:
        witness_refs = (f"reviews/R-STATE-CREDIT-1/{artifact.artifact_type}.json",)
    artifact.sign(
        backend,
        identity,
        principal_id=principal,
        instance_id=instance,
        signed_at=_SIGNED_AT,
        expires_at=_EXPIRES_AT,
        witness_refs=witness_refs,
    )


def _make_prereg(identity: str, backend: TestHmacBackend) -> PreregAcceptanceArtifact:
    artifact = PreregAcceptanceArtifact(
        artifact_id="prereg-1",
        artifact_type="prereg-acceptance",
        payload_digest="0" * 64,
        signer_principal_id="x",
        signer_instance_id="x",
        signature_bytes=b"",
        signed_at=_SIGNED_AT,
        expires_at=_EXPIRES_AT,
        witness_refs=("reviews/R-STATE-CREDIT-1/prereg-acceptance.json",),
        reviewer_id=identity.split(":", 1)[0],
        reviewed_at=_SIGNED_AT,
        candidate_repo="autonomous-agent-core",
        candidate_branch="codex/r-state-credit-1-real-bindings-20260715",
        candidate_commit_sha=_CANDIDATE_SHA,
        candidate_sha256=_PREREG_SHA256,
        prereg_path="docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.PREREG-CANDIDATE-2026-07-16.json",
        prereg_sha256=_PREREG_SHA256,
        acceptance=True,
        conditions=("INSTANCE_INDEPENDENCE_VALID",),
        notes="",
    )
    _sign_artifact(artifact, identity, backend)
    return artifact


def _make_architecture(
    identity: str, backend: TestHmacBackend
) -> ArchitectureAcceptanceArtifact:
    artifact = ArchitectureAcceptanceArtifact(
        artifact_id="arch-1",
        artifact_type="architecture-acceptance",
        payload_digest="0" * 64,
        signer_principal_id="x",
        signer_instance_id="x",
        signature_bytes=b"",
        signed_at=_SIGNED_AT,
        expires_at=_EXPIRES_AT,
        witness_refs=("reviews/R-STATE-CREDIT-1/architecture-acceptance.json",),
        reviewer_id=identity.split(":", 1)[0],
        reviewed_at=_SIGNED_AT,
        candidate_commit_sha=_CANDIDATE_SHA,
        candidate_sha256=_PREREG_SHA256,
        rr_0029_delta="docs/research/RR-0029-delta.md",
        rr_0031_delta="docs/research/RR-0031-delta.md",
        mechanism_file_hashes={
            "experiments/r_state_credit_1/interactive_env.py": "c" * 64,
            "experiments/r_state_credit_1/arm_blinding.py": "d" * 64,
            "experiments/r_state_credit_1/authority_verifier.py": "e" * 64,
        },
        acceptance=True,
        notes="",
    )
    _sign_artifact(artifact, identity, backend)
    return artifact


def _make_freeze(
    identity: str,
    backend: TestHmacBackend,
    prereg: PreregAcceptanceArtifact,
    architecture: ArchitectureAcceptanceArtifact,
) -> NativeFreezeLockArtifact:
    artifact = NativeFreezeLockArtifact(
        artifact_id="freeze-1",
        artifact_type="native-freeze-lock",
        payload_digest="0" * 64,
        signer_principal_id="x",
        signer_instance_id="x",
        signature_bytes=b"",
        signed_at=_SIGNED_AT,
        expires_at=_EXPIRES_AT,
        witness_refs=("reviews/R-STATE-CREDIT-1/native-freeze-lock.json",),
        freezer_id=identity.split(":", 1)[0],
        frozen_at=_SIGNED_AT,
        candidate_commit_sha=_CANDIDATE_SHA,
        candidate_sha256=_PREREG_SHA256,
        prereg_acceptance_digest=compute_payload_digest(prereg.content_mapping()),
        architecture_acceptance_digest=compute_payload_digest(
            architecture.content_mapping()
        ),
        review_record_digests=("f" * 64,),
        builder_id="builder",
        builder_id_included_for_audit_only=True,
    )
    _sign_artifact(artifact, identity, backend)
    return artifact


def _make_c7(
    identity: str, backend: TestHmacBackend, freeze: NativeFreezeLockArtifact
) -> C7AcceptanceArtifact:
    artifact = C7AcceptanceArtifact(
        artifact_id="c7-1",
        artifact_type="c7-acceptance",
        payload_digest="0" * 64,
        signer_principal_id="x",
        signer_instance_id="x",
        signature_bytes=b"",
        signed_at=_SIGNED_AT,
        expires_at=_EXPIRES_AT,
        witness_refs=("reviews/R-STATE-CREDIT-1/c7-acceptance.json",),
        owner_id=identity.split(":", 1)[0],
        epoch="epoch-1",
        capability_token_sha256="e" * 64,
        stop_path="reviews/R-STATE-CREDIT-1/stop.json",
        freeze_lock_digest=compute_payload_digest(freeze.content_mapping()),
        issued_at=_SIGNED_AT,
        acceptance=True,
    )
    _sign_artifact(artifact, identity, backend)
    return artifact


def _make_authorization(
    identity: str,
    backend: TestHmacBackend,
    freeze: NativeFreezeLockArtifact,
    c7: C7AcceptanceArtifact,
    run_id: str = "run-2026-07-16-001",
) -> RunAuthorizationArtifact:
    artifact = RunAuthorizationArtifact(
        artifact_id="authz-1",
        artifact_type="run-authorization",
        payload_digest="0" * 64,
        signer_principal_id="x",
        signer_instance_id="x",
        signature_bytes=b"",
        signed_at=_SIGNED_AT,
        expires_at=_EXPIRES_AT,
        witness_refs=("reviews/R-STATE-CREDIT-1/run-authorization.json",),
        authorizer_id=identity.split(":", 1)[0],
        authorized_at=_SIGNED_AT,
        freeze_lock_digest=compute_payload_digest(freeze.content_mapping()),
        c7_acceptance_digest=compute_payload_digest(c7.content_mapping()),
        run_id=run_id,
        max_runs=1,
        result_bearing=True,
        acceptance=True,
        notes="",
    )
    _sign_artifact(artifact, identity, backend)
    return artifact


def _make_bundle(
    backend: TestHmacBackend,
    witness_root: Path,
    identities: dict[str, str] | None = None,
) -> AuthorityArtifactBundle:
    ids: dict[str, str] = {
        "prereg": _PREREG_IDENTITY,
        "architecture": _ARCHITECTURE_IDENTITY,
        "freeze": _FREEZER_IDENTITY,
        "c7": _C7_IDENTITY,
        "authorization": _AUTHORIZER_IDENTITY,
    }
    if identities is not None:
        ids.update(identities)

    def _witness(artifact_type: str) -> tuple[str, ...]:
        ref = f"reviews/R-STATE-CREDIT-1/{artifact_type}.json"
        (witness_root / "reviews" / "R-STATE-CREDIT-1").mkdir(parents=True, exist_ok=True)
        (witness_root / ref).write_text("witness", encoding="utf-8")
        return (ref,)

    prereg = _make_prereg(ids["prereg"], backend)
    prereg.witness_refs = _witness("prereg-acceptance")
    architecture = _make_architecture(ids["architecture"], backend)
    architecture.witness_refs = _witness("architecture-acceptance")
    freeze = _make_freeze(ids["freeze"], backend, prereg, architecture)
    freeze.witness_refs = _witness("native-freeze-lock")
    c7 = _make_c7(ids["c7"], backend, freeze)
    c7.witness_refs = _witness("c7-acceptance")
    authorization = _make_authorization(ids["authorization"], backend, freeze, c7)
    authorization.witness_refs = _witness("run-authorization")

    # Re-sign after witness_refs are fixed so signatures match the bundle state.
    _sign_artifact(prereg, ids["prereg"], backend, prereg.witness_refs)
    _sign_artifact(architecture, ids["architecture"], backend, architecture.witness_refs)
    _sign_artifact(freeze, ids["freeze"], backend, freeze.witness_refs)
    _sign_artifact(c7, ids["c7"], backend, c7.witness_refs)
    _sign_artifact(authorization, ids["authorization"], backend, authorization.witness_refs)

    bundle = AuthorityArtifactBundle(
        prereg_acceptance=prereg,
        architecture_acceptance=architecture,
        native_freeze_lock=freeze,
        c7_acceptance=c7,
        run_authorization=authorization,
    )
    for artifact in bundle.all_artifacts():
        for ref in artifact.witness_refs:
            (witness_root / ref).write_text(artifact.payload_digest, encoding="utf-8")
    return bundle


def test_authority_bundle_accepted_for_valid_run(tmp_path: Path) -> None:
    """Five distinct signer identities produce an accepted authority bundle."""
    backend = _fresh_backend()
    witness_root = tmp_path / "witness"
    bundle = _make_bundle(backend, witness_root=witness_root)
    verifier = AuthorityVerifier(
        allowed_signers=_ALL_ALLOWED,
        builder_identities={_BUILDER_IDENTITY},
        backend=backend,
        witness_repository=witness_root,
        now="2026-07-16T12:00:00+00:00",
    )
    result = verifier.verify(bundle)
    assert result.accepted, result.rejection_reason
    assert result.rejection_reason is None
    assert set(result.verified_identities) == _ALL_ALLOWED


def test_authority_bundle_with_builder_signer_rejected(tmp_path: Path) -> None:
    """Replacing one signer with the builder identity causes rejection."""
    backend = _fresh_backend()
    witness_root = tmp_path / "witness"
    bundle = _make_bundle(
        backend,
        witness_root=witness_root,
        identities={"prereg": _BUILDER_IDENTITY},
    )
    verifier = AuthorityVerifier(
        allowed_signers=_ALL_ALLOWED,
        builder_identities={_BUILDER_IDENTITY},
        backend=backend,
        witness_repository=witness_root,
        now="2026-07-16T12:00:00+00:00",
    )
    result = verifier.verify(bundle)
    assert not result.accepted
    assert "builder" in (result.rejection_reason or "").lower()
    assert _BUILDER_IDENTITY in (result.rejection_reason or "")


def test_arm_scores_are_isolated_per_episode(tmp_path: Path) -> None:
    """Two seeds keep their checkpoint action histories in separate records."""
    seed_records: dict[int, list[CheckpointRecord]] = {}
    for seed_id in (7, 9):
        episode, records = _run_checkpointed_episode(
            FAMILY, seed_id, tmp_path / f"isolated-{seed_id}"
        )
        try:
            seed_records[seed_id] = records
        finally:
            episode.cleanup()

    for seed_id, records in seed_records.items():
        assert len(records) == 4
        # Each record belongs to exactly one seed.
        for record in records:
            for arm_id, action in record.resolved_actions.items():
                assert isinstance(action, ActorAction)
                # Reconstructing from the same seed should never mix arms.
                assert arm_id in set(ArmId)

    # Records are stored per seed; no shared mutable state.
    assert seed_records[7] is not seed_records[9]
    actions_7 = tuple(
        (record.checkpoint_ordinal, arm.value, action.value)
        for record in seed_records[7]
        for arm, action in record.resolved_actions.items()
    )
    actions_9 = tuple(
        (record.checkpoint_ordinal, arm.value, action.value)
        for record in seed_records[9]
        for arm, action in record.resolved_actions.items()
    )
    assert actions_7 != actions_9, "seeds produced identical arm action histories"


def _cohen_kappa(y_true: list[ActorAction], y_pred: list[ActorAction]) -> float:
    """Cohen's κ for a multi-class agreement."""
    n = len(y_true)
    if n == 0:
        return 0.0
    labels = sorted(set(y_true) | set(y_pred), key=lambda a: a.value)
    p_o = sum(1 for a, b in zip(y_true, y_pred) if a == b) / n
    true_counts = Counter(y_true)
    pred_counts = Counter(y_pred)
    p_e = sum(true_counts[label] * pred_counts[label] for label in labels) / (n * n)
    if p_e >= 1.0:
        return 1.0
    return (p_o - p_e) / (1 - p_e)


def test_full_gate_g1_dummy_classifier(tmp_path: Path) -> None:
    """A dummy classifier using only family+checkpoint cannot beat chance.

    For every canonical family, train a majority-vote dummy on the first half of
    development seeds and evaluate on the second half.  The feature is exactly
    ``(family, checkpoint_ordinal)``; no observation content is used.
    """
    from experiments.r_state_credit_1.contracts import ScenarioFamily

    train_seeds = list(range(0, 10))
    test_seeds = list(range(10, 20))
    families = [member.value for member in ScenarioFamily]

    # Train: majority action per (family, checkpoint).
    majority_by_feature: dict[tuple[str, int], ActorAction] = {}
    for family in families:
        counts: dict[tuple[str, int], Counter[ActorAction]] = {}
        for seed_id in train_seeds:
            episode, records = _run_checkpointed_episode(
                family, seed_id, tmp_path / f"g1-train-{family}-{seed_id}"
            )
            try:
                for record in records:
                    feature = (family, record.checkpoint_ordinal)
                    counts.setdefault(feature, Counter())
                    assert record.correct_action is not None
                    counts[feature][record.correct_action] += 1
            finally:
                episode.cleanup()
        for feature, counter in counts.items():
            majority_by_feature[feature] = counter.most_common(1)[0][0]

    # Test: predict majority action for (family, checkpoint); fallback to global majority.
    global_counts: Counter[ActorAction] = Counter()
    y_true: list[ActorAction] = []
    y_pred: list[ActorAction] = []
    for family in families:
        for seed_id in test_seeds:
            episode, records = _run_checkpointed_episode(
                family, seed_id, tmp_path / f"g1-test-{family}-{seed_id}"
            )
            try:
                for record in records:
                    assert record.correct_action is not None
                    y_true.append(record.correct_action)
                    global_counts[record.correct_action] += 1
                    feature = (family, record.checkpoint_ordinal)
                    y_pred.append(majority_by_feature.get(feature, ActorAction.CONTINUE))
            finally:
                episode.cleanup()

    total = len(y_true)
    assert total > 0
    majority_prior = max(global_counts.values()) / total
    accuracy = sum(1 for a, b in zip(y_true, y_pred) if a == b) / total
    kappa = _cohen_kappa(y_true, y_pred)

    assert accuracy <= majority_prior + 0.05, (
        f"family+checkpoint dummy accuracy {accuracy:.3f} exceeds "
        f"majority prior {majority_prior:.3f} + 0.05"
    )
    assert kappa <= 0.05, (
        f"family+checkpoint dummy Cohen's κ {kappa:.3f} exceeds 0.05"
    )


def _contains_directive_hint(text: str, hint: str) -> bool:
    """Check for ``hint`` as a whole word, ignoring case."""
    pattern = re.compile(r"\b" + re.escape(hint) + r"\b", re.IGNORECASE)
    return bool(pattern.search(text))


def test_full_gate_g6_no_recovery_directive_in_arm_output(tmp_path: Path) -> None:
    """Actor requests and arm responses carry no directive hints in their bytes."""
    for seed_id in range(5):
        episode, records = _run_checkpointed_episode(
            FAMILY, seed_id, tmp_path / f"g6-{seed_id}"
        )
        try:
            for record in records:
                for label, request in record.requests.items():
                    text = request.to_canonical_json()
                    for hint in _DIRECTIVE_HINTS:
                        assert not _contains_directive_hint(text, hint), (
                            f"directive hint {hint!r} found in actor request bytes "
                            f"for {label} at checkpoint {record.checkpoint_ordinal}"
                        )
                for response in record.responses.values():
                    notes = response.notes or ""
                    for hint in _DIRECTIVE_HINTS:
                        assert not _contains_directive_hint(notes, hint), (
                            f"directive hint {hint!r} found in arm notes: {notes!r}"
                        )
        finally:
            episode.cleanup()


def test_reversibility_across_blinding(tmp_path: Path) -> None:
    """Replaying the same seed produces identical neutral labels and call order."""
    for seed_id in (3, 17):
        first_episode, _ = _run_checkpointed_episode(
            FAMILY, seed_id, tmp_path / f"rev-first-{seed_id}"
        )
        second_episode, _ = _run_checkpointed_episode(
            FAMILY, seed_id, tmp_path / f"rev-second-{seed_id}"
        )
        try:
            first_blinding = ArmBlinding(first_episode._episode_seed)
            second_blinding = ArmBlinding(second_episode._episode_seed)
            assert first_episode.checkpoints == second_episode.checkpoints
            for checkpoint_ordinal in range(4):
                assert first_blinding.call_order(checkpoint_ordinal) == (
                    second_blinding.call_order(checkpoint_ordinal)
                )
            for position in range(4):
                assert first_blinding.label_for_position(position) == (
                    second_blinding.label_for_position(position)
                )
        finally:
            first_episode.cleanup()
            second_episode.cleanup()


def test_instance_independence_across_canonical_families(tmp_path: Path) -> None:
    """No canonical family collapses into ≤7 structural equivalence classes.

    Each family must expose seed-dependent structural signatures and at least
    30% of checkpoints must have seed-dependent correct actions.
    """
    from experiments.r_state_credit_1.contracts import ScenarioFamily

    families = [member.value for member in ScenarioFamily]
    global_signatures: set[tuple[Any, ...]] = set()

    for family in families:
        family_signatures: set[tuple[Any, ...]] = set()
        checkpoint_actions: dict[int, set[ActorAction]] = {i: set() for i in range(4)}

        for seed_id in range(20):
            gen = EpisodeGenerator(family, seed_id)
            sig = gen.structural_signature()
            key = (
                sig["T"],
                sig["entity_count"],
                sig["alias_topology"],
                sig["checkpoint_positions"],
                sig["perturbation_schedule"],
            )
            family_signatures.add(key)
            global_signatures.add((family,) + key)

            episode, records = _run_checkpointed_episode(
                family, seed_id, tmp_path / f"ii-{family}-{seed_id}"
            )
            try:
                for record in records:
                    assert record.correct_action is not None
                    checkpoint_actions[record.checkpoint_ordinal].add(
                        record.correct_action
                    )
            finally:
                episode.cleanup()

        assert len(family_signatures) > 7, (
            f"family {family} clustered into {len(family_signatures)} "
            f"structural equivalence classes (≤7)"
        )

        varied_checkpoints = sum(
            1 for actions in checkpoint_actions.values() if len(actions) > 1
        )
        assert varied_checkpoints / 4 >= 0.30, (
            f"family {family} has only {varied_checkpoints}/4 seed-dependent "
            f"correct-action checkpoints (need ≥30%)"
        )

    assert len(global_signatures) == len(families) * 20, (
        "some (family, seed) pairs produced identical global structural signatures"
    )


def _sample_arm_input() -> ArmInput:
    """Minimal ArmInput exercising A3 typed-state projection."""
    now = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
    event = ObservableEvent(
        scenario_id="scenario:test",
        sequence=1,
        event_id="event:1",
        observed_at=now,
        kind=EventKind.ENTITY_OBSERVED,
        subject_ref="visible:client",
        object_version="v1",
        evidence_refs=("visible:evidence:1",),
    )
    return ArmInput(
        scenario_id="scenario:test",
        observable_events=(event,),
        visible_through_sequence=1,
        budget=ResourceBudget(
            max_observable_bytes=100_000,
            max_representation_bytes=100_000,
            max_steps=256,
            max_tool_calls=8,
            max_wall_clock_units=512,
        ),
    )


def test_legacy_a3_confound_is_excluded_from_frozen_contract() -> None:
    """Legacy A3TypedStateArm still contains the recovery_directive confound,
    but the recast frozen source manifest excludes the legacy arm file."""
    from experiments.r_state_credit_1 import prereg_candidate

    arm_input = _sample_arm_input()
    output = A3TypedStateArm().consume(arm_input)
    assert "recovery_directive" in output.representation
    assert "experiments/r_state_credit_1/arms.py" not in prereg_candidate._SOURCE_PATHS


def test_source_manifest_covers_recast_mechanism_files() -> None:
    """The prereg candidate source manifest includes every recast mechanism file
    and excludes the legacy arm file."""
    from experiments.r_state_credit_1 import prereg_candidate

    expected = {
        "experiments/r_state_credit_1/interactive_env.py",
        "experiments/r_state_credit_1/episode_generator.py",
        "experiments/r_state_credit_1/observation.py",
        "experiments/r_state_credit_1/arm_blinding.py",
        "experiments/r_state_credit_1/actor_interface.py",
        "experiments/r_state_credit_1/action_grammar.py",
        "experiments/r_state_credit_1/authority_artifacts.py",
        "experiments/r_state_credit_1/signature_backend.py",
        "experiments/r_state_credit_1/authority_verifier.py",
    }
    assert expected.issubset(set(prereg_candidate._SOURCE_PATHS))
    assert "experiments/r_state_credit_1/arms.py" not in prereg_candidate._SOURCE_PATHS
