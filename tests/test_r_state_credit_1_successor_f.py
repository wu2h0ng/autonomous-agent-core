from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from experiments.r_state_credit_1.action_grammar import ALL_ACTIONS, ActorAction
from experiments.r_state_credit_1.actor_interface import ActorRequest
from experiments.r_state_credit_1.contracts import ArmId, ProbeAction, ScenarioFamily
from experiments.r_state_credit_1.recast_freeze_contracts import (
    ExactSuccessorArtifacts,
    ExecutionBundle,
    ReceiptKind,
    SuccessorReadiness,
    VerifiedReceipt,
)
from experiments.r_state_credit_1.recast_provider_actor import (
    ProviderActor,
    ProviderBinding,
    ProviderNotReady,
)
from experiments.r_state_credit_1.recast_result_runner import (
    C7Interrupted,
    PublicResultRow,
    ResultRunner,
    RunNotReady,
)
from experiments.r_state_credit_1.recast_scorer import RawRecastScorer
from experiments.r_state_credit_1.run_contracts import CheckpointId, HELD_OUT_SEEDS


class _Transport:
    def complete(self, request: ActorRequest) -> dict[str, object]:
        return {
            "action": "CONTINUE",
            "notes": "bounded answer",
            "provider_receipt_id": "receipt-1",
            "model_revision": "revision-2026-07-17",
            "input_tokens": 10,
            "output_tokens": 2,
        }


class _C7:
    def __init__(self, values: list[bool]) -> None:
        self.values = values

    def abort_requested(self) -> bool:
        return self.values.pop(0)


class _ReceiptVerifier:
    def verify(self, receipt: VerifiedReceipt) -> bool:
        return receipt.signer_id.startswith("independent-")


def _binding(**changes: object) -> ProviderBinding:
    values: dict[str, object] = {
        "provider_id": "provider-1",
        "model_id": "model-1",
        "model_revision": "revision-2026-07-17",
        "revision_confirmed": True,
        "transport": "API_ONLY",
        "action_grammar_sha256": hashlib.sha256(
            json.dumps([a.value for a in ALL_ACTIONS], separators=(",", ":")).encode()
        ).hexdigest(),
    }
    values.update(changes)
    return ProviderBinding(**values)  # type: ignore[arg-type]


def _request() -> ActorRequest:
    return ActorRequest(
        representation='{"latest":{"event_class":"ENTITY_OBSERVED"}}',
        valid_actions=ALL_ACTIONS,
        session_label="session-1",
    )


def _bundle(**changes: object) -> ExecutionBundle:
    root = Path(__file__).resolve().parents[1]
    manifest = (
        root / "docs/pre_spec/R-STATE-CREDIT-1.SUCCESSOR-F-MANIFEST-2026-07-17.json"
    )

    def digest(relative: str) -> str:
        return hashlib.sha256((root / relative).read_bytes()).hexdigest()

    values: dict[str, object] = {
        "schema_version": "r-state-credit-1-successor-f-execution-v1",
        "reviewed_mechanism_head": "0ca38aa3491161fa115c0b58685cf408e5be106b",
        "provider_binding_sha256": digest(
            "experiments/r_state_credit_1/bindings/ark-agent-plan-actor-candidate.json"
        ),
        "runner_sha256": digest("experiments/r_state_credit_1/recast_result_runner.py"),
        "scorer_sha256": digest("experiments/r_state_credit_1/recast_scorer.py"),
        "c7_schema_sha256": digest(
            "experiments/r_state_credit_1/bindings/c7-signal-candidate.json"
        ),
        "prereg_sha256": digest(
            "docs/pre_spec/R-STATE-CREDIT-1.SUCCESSOR-F-CANDIDATE-2026-07-17.json"
        ),
        "future_freeze_receipt_sha256": None,
        "run_authorization_freeze_sha256": None,
        "artifact_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "expected_provider_calls": 2240,
        "max_total_input_tokens": 2_240_000,
        "max_total_output_tokens": 1_120_000,
    }
    values.update(changes)
    return ExecutionBundle(**values)  # type: ignore[arg-type]


def _authorized_context() -> tuple[
    ExecutionBundle, ExactSuccessorArtifacts, tuple[VerifiedReceipt, ...]
]:
    root = Path(__file__).resolve().parents[1]
    artifacts = ExactSuccessorArtifacts.load(root)
    receipt_digests = {
        kind: hashlib.sha256(f"verified-{kind.value}".encode()).hexdigest()
        for kind in ReceiptKind
    }
    bundle = _bundle(
        future_freeze_receipt_sha256=receipt_digests[ReceiptKind.FREEZE],
        run_authorization_freeze_sha256=receipt_digests[ReceiptKind.RUN_AUTHORIZATION],
    )
    subjects = {
        ReceiptKind.PROVIDER_CANARY: bundle.provider_binding_sha256,
        ReceiptKind.C7: bundle.c7_schema_sha256,
        ReceiptKind.EXECUTOR: bundle.runner_sha256,
        ReceiptKind.INTEGRITY: artifacts.integrity_subject_sha256,
        ReceiptKind.FREEZE: artifacts.manifest_sha256,
        ReceiptKind.RUN_AUTHORIZATION: receipt_digests[ReceiptKind.FREEZE],
    }
    receipts = tuple(
        VerifiedReceipt(
            kind=kind,
            receipt_sha256=receipt_digests[kind],
            subject_sha256=subjects[kind],
            signer_id=f"independent-{kind.value}",
            signature_verified=True,
        )
        for kind in ReceiptKind
    )
    return bundle, artifacts, receipts


def _public_rows() -> tuple[PublicResultRow, ...]:
    return tuple(
        PublicResultRow(
            family=family,
            seed=seed,
            checkpoint_id=checkpoint,
            arm_id=arm,
        )
        for family in ScenarioFamily
        for seed in HELD_OUT_SEEDS
        for checkpoint in CheckpointId
        for arm in ArmId
    )


def test_provider_rejects_stub_legacy_grammar_and_floating_revision() -> None:
    with pytest.raises(ProviderNotReady, match="confirmed immutable model revision"):
        ProviderActor(_binding(revision_confirmed=False), _Transport())
    with pytest.raises(ProviderNotReady, match="alias"):
        ProviderActor(_binding(model_revision="latest"), _Transport())
    actor = ProviderActor(_binding(), _Transport())
    with pytest.raises(ProviderNotReady, match="six-action"):
        actor.act(
            ActorRequest(
                representation="x",
                valid_actions=tuple(ActorAction(item.value) for item in ProbeAction),
                session_label="legacy",
            )
        )
    with pytest.raises(ProviderNotReady, match="Stub"):
        ProviderActor(_binding(provider_id="StubActor"), _Transport())


def test_provider_emits_typed_revision_bound_receipt() -> None:
    response = ProviderActor(_binding(), _Transport()).act(_request())
    assert response.response.action is ActorAction.CONTINUE
    assert response.receipt.model_revision == "revision-2026-07-17"
    assert (
        response.receipt.request_sha256
        == hashlib.sha256(_request().to_canonical_json().encode()).hexdigest()
    )
    assert response.receipt.response_sha256


def test_runner_never_runs_without_future_freeze_bound_authorization() -> None:
    readiness = SuccessorReadiness.evaluate(_bundle())
    assert readiness.status == "NOT_READY"
    with pytest.raises(RunNotReady, match="verified custody"):
        ResultRunner(_bundle(), _C7([False])).run(())


def test_runner_checks_c7_before_and_after_and_lock_is_terminal() -> None:
    bundle, artifacts, receipts = _authorized_context()
    runner = ResultRunner(
        bundle,
        _C7([False, True]),
        artifacts=artifacts,
        receipts=receipts,
        receipt_verifier=_ReceiptVerifier(),
    )
    with pytest.raises(C7Interrupted):
        runner.run(_public_rows())
    with pytest.raises(RunNotReady, match="terminal"):
        runner.run(())


def test_runner_rejects_hidden_truth_payload_before_provider() -> None:
    with pytest.raises(ValueError, match="closed public row schema"):
        PublicResultRow.from_mapping(
            {
                "family": next(iter(ScenarioFamily)).value,
                "seed": HELD_OUT_SEEDS[0],
                "checkpoint_id": next(iter(CheckpointId)).value,
                "arm_id": next(iter(ArmId)).value,
                "payload": {"correct_action": "REVIEW"},
            }
        )


def test_runner_rejects_nested_hidden_truth_and_untyped_rows() -> None:
    with pytest.raises(ValueError, match="closed public row schema"):
        PublicResultRow.from_mapping(
            {
                "family": next(iter(ScenarioFamily)).value,
                "seed": HELD_OUT_SEEDS[0],
                "checkpoint_id": next(iter(CheckpointId)).value,
                "arm_id": next(iter(ArmId)).value,
                "metadata": {"referee": {"correct_action": "REVIEW"}},
            }
        )
    bundle, artifacts, receipts = _authorized_context()
    untyped_rows = cast(
        tuple[PublicResultRow, ...],
        ({"family": "x", "payload": {"loss_by_action": {}}},),
    )
    with pytest.raises(RunNotReady, match="typed public rows"):
        ResultRunner(
            bundle,
            _C7([False]),
            artifacts=artifacts,
            receipts=receipts,
            receipt_verifier=_ReceiptVerifier(),
        ).run(untyped_rows)


def test_runner_rejects_missing_or_duplicate_exact_rows_and_budget_drift() -> None:
    bundle, artifacts, receipts = _authorized_context()
    rows = _public_rows()
    with pytest.raises(RunNotReady, match="coverage"):
        ResultRunner(
            bundle,
            _C7([False]),
            artifacts=artifacts,
            receipts=receipts,
            receipt_verifier=_ReceiptVerifier(),
        ).run(rows[:-1])
    with pytest.raises(RunNotReady, match="coverage"):
        ResultRunner(
            bundle,
            _C7([False]),
            artifacts=artifacts,
            receipts=receipts,
            receipt_verifier=_ReceiptVerifier(),
        ).run(rows[:-1] + (rows[0],))
    with pytest.raises(ValueError, match="provider call budget"):
        replace(bundle, expected_provider_calls=2239)


def test_raw_scorer_rejects_duplicate_missing_and_verdict_fields() -> None:
    scorer = RawRecastScorer()
    row = {
        "family": next(iter(ScenarioFamily)).value,
        "seed": 1,
        "checkpoint_id": 0,
        "arm_id": "A0_FULL_LOG",
        "action": "CONTINUE",
        "loss_code": "CORRECT",
        "loss_weight": 0,
        "unsafe_effect_replay": False,
        "episode_id": "episode-1",
    }
    with pytest.raises(ValueError, match="duplicate"):
        scorer.validate_identity_rows(
            (row, row), expected={(row["family"], 1, 0, "A0_FULL_LOG")}
        )
    with pytest.raises(ValueError, match="coverage"):
        scorer.validate_identity_rows(
            (row,), expected={(row["family"], 1, 1, "A0_FULL_LOG")}
        )
    with pytest.raises(ValueError, match="verdict"):
        scorer.assert_raw_only({"raw_metrics": {}, "verdict": "MET"})


def test_raw_scorer_emits_measurements_without_route_verdict() -> None:
    scorer = RawRecastScorer()
    rows = (
        {"action": "RECOVER_ROLLBACK", "loss_code": "CORRECT", "loss_weight": 0},
        {
            "action": "RECOVER_ROLL_FORWARD",
            "loss_code": "STALE_BELIEF_USE",
            "loss_weight": 3,
        },
    )
    output = scorer.score_raw(rows)
    assert output == {
        "schema_version": "r-state-credit-1-successor-f-raw-metrics-v1",
        "row_count": 2,
        "mean_loss_weight": 1.5,
        "loss_counts": {"CORRECT": 1, "STALE_BELIEF_USE": 1},
        "action_counts": {"RECOVER_ROLLBACK": 1, "RECOVER_ROLL_FORWARD": 1},
    }
    scorer.assert_raw_only(output)


def test_successor_contract_closes_family_overclaim_and_integrity_umbrella() -> None:
    bundle = _bundle()
    assert bundle.required_family_strata == tuple(item.value for item in ScenarioFamily)
    assert bundle.required_perturbations == "GENERATED_PER_FAMILY_NOT_EVERY_INSTANCE"
    assert bundle.integrity_umbrella == "INTEGRITY_VALID"
    drifted = replace(bundle, run_authorization_freeze_sha256="c" * 64)
    assert SuccessorReadiness.evaluate(drifted).status == "NOT_READY"


def test_placeholder_digests_budgets_and_same_receipt_never_become_ready() -> None:
    with pytest.raises(ValueError, match="token budgets"):
        _bundle(
            provider_binding_sha256="a" * 64,
            runner_sha256="a" * 64,
            scorer_sha256="a" * 64,
            c7_schema_sha256="a" * 64,
            prereg_sha256="a" * 64,
            max_total_input_tokens=1,
            max_total_output_tokens=1,
        )
    bundle = _bundle()
    root = Path(__file__).resolve().parents[1]
    artifacts = ExactSuccessorArtifacts.load(root)
    receipts = tuple(
        VerifiedReceipt(
            kind=kind,
            receipt_sha256="b" * 64,
            subject_sha256=artifacts.manifest_sha256,
            signer_id=f"signer-{kind.value}",
            signature_verified=True,
        )
        for kind in ReceiptKind
    )
    readiness = SuccessorReadiness.evaluate(
        bundle, artifacts=artifacts, receipts=receipts
    )
    assert readiness.status == "NOT_READY"
    assert "receipt digests must be distinct" in readiness.blockers


def test_provider_self_claim_cannot_close_readiness_without_verified_canary() -> None:
    bundle = _bundle()
    root = Path(__file__).resolve().parents[1]
    artifacts = ExactSuccessorArtifacts.load(root)
    readiness = SuccessorReadiness.evaluate(bundle, artifacts=artifacts, receipts=())
    assert readiness.status == "NOT_READY"
    assert "verified PROVIDER_CANARY receipt absent" in readiness.blockers


def test_successor_candidate_is_separate_not_ready_and_exactly_manifested() -> None:
    root = Path(__file__).resolve().parents[1]
    candidate_path = (
        root / "docs/pre_spec/R-STATE-CREDIT-1.SUCCESSOR-F-CANDIDATE-2026-07-17.json"
    )
    manifest_path = (
        root / "docs/pre_spec/R-STATE-CREDIT-1.SUCCESSOR-F-MANIFEST-2026-07-17.json"
    )
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert candidate["status"] == "NOT_READY_NOT_FROZEN_NOT_RUN"
    assert candidate["active_freeze_input"] is False
    assert (
        candidate["reviewed_mechanism_base"]
        == "0ca38aa3491161fa115c0b58685cf408e5be106b"
    )
    assert candidate["historical_candidate_mutated"] is False
    assert (
        candidate["family_perturbation_contract"]
        == "GENERATED_PER_FAMILY_NOT_EVERY_INSTANCE"
    )
    assert candidate["integrity_umbrella"] == "INTEGRITY_VALID"
    assert candidate["run_authorization"]["must_reference_future_freeze"] is True
    assert candidate["run_authorization"]["receipt_sha256"] is None
    hashes = manifest["artifact_sha256"]
    for relative, expected in hashes.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected
