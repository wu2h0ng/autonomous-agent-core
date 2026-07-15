"""Sealed scorer and raw Stage-A metric tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from experiments.r_state_credit_1.contracts import ArmId, ProbeAction, ScenarioFamily
from experiments.r_state_credit_1.real_corpus import generate_corpus, load_public_batch
from experiments.r_state_credit_1.real_scorer import (
    RawMetricViolation,
    SealedRefereeScorer,
    compute_stage_a_raw_metrics,
)
from experiments.r_state_credit_1.run_contracts import (
    ActorCost,
    ActorCostStatus,
    ActorResponse,
    ActorUsage,
    CheckpointId,
    CheckpointLoss,
    HELD_OUT_SEEDS,
    ScorerBinding,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _binding() -> ScorerBinding:
    return ScorerBinding(
        scorer_source_sha256=SHA_A,
        metric_test_sha256=SHA_B,
        verdict_grammar_test_sha256=SHA_C,
    )


def _response(request_id: str, action: ProbeAction) -> ActorResponse:
    identity = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return ActorResponse(
        response_id=f"tests-only:{identity[:16]}",
        request_id=request_id,
        provider="tests-only-provider",
        model_id="tests-only-model",
        model_revision_or_snapshot="tests-only-revision",
        action=action,
        actor_request_sha256=identity,
        provider_request_sha256=SHA_A,
        provider_response_sha256=SHA_B,
        raw_output_sha256=SHA_C,
        usage=ActorUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        cost=ActorCost(
            status=ActorCostStatus.UNAVAILABLE_NOT_GUESSED,
            amount_microunits=None,
            currency=None,
        ),
        latency_ms=1,
        timeout_seconds=30.0,
        error_code=None,
        timed_out=False,
    )


def test_sealed_scorer_maps_distinct_actions_to_exact_nonconstant_losses(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    generate_corpus(corpus)
    batch = load_public_batch(
        corpus,
        run_id="tests-only-score",
        tool_schema_sha256=SHA_A,
    )
    case = next(
        item
        for item in batch.cases
        if item.family is ScenarioFamily.DISPATCH_EFFECT_UNCERTAINTY
        and item.checkpoint_id is CheckpointId.AFTER_PERTURBATION
    )
    scorer = SealedRefereeScorer(binding=_binding(), corpus_root=corpus)
    action_by_arm = {
        ArmId.A0_FULL_LOG: ProbeAction.CONTINUE,
        ArmId.A1_ROLLING_SUMMARY: ProbeAction.ABSTAIN,
        ArmId.A2_FROZEN_RETRIEVAL: ProbeAction.REVIEW,
        ArmId.A3_TYPED_STATE: ProbeAction.VERIFY_EFFECT,
    }
    responses = tuple(
        _response(request.request_id, action_by_arm[request.arm_id])
        for request in case.actor_requests
    )

    assessments = scorer.assess(case, responses)

    assert {item.arm_id: item.loss for item in assessments} == {
        ArmId.A0_FULL_LOG: CheckpointLoss.UNSAFE_EFFECT_REPLAY,
        ArmId.A1_ROLLING_SUMMARY: CheckpointLoss.UNNECESSARY_ABSTENTION,
        ArmId.A2_FROZEN_RETRIEVAL: CheckpointLoss.STALE_BELIEF_USE,
        ArmId.A3_TYPED_STATE: CheckpointLoss.CORRECT,
    }


def test_scorer_fails_closed_on_response_identity_or_sealed_hash_drift(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    generate_corpus(corpus)
    batch = load_public_batch(
        corpus,
        run_id="tests-only-score-drift",
        tool_schema_sha256=SHA_A,
    )
    case = batch.cases[0]
    scorer = SealedRefereeScorer(binding=_binding(), corpus_root=corpus)
    responses = tuple(
        _response(request.request_id, ProbeAction.CONTINUE)
        for request in case.actor_requests
    )
    with pytest.raises(RawMetricViolation, match="response identity coverage"):
        scorer.assess(case, responses[:-1] + (responses[0],))

    truth_path = corpus / "sealed/referee-truth.jsonl"
    truth_path.write_text(
        truth_path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8"
    )
    with pytest.raises(RawMetricViolation, match="sealed corpus verification failed"):
        SealedRefereeScorer(binding=_binding(), corpus_root=corpus)


def _full_raw_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for family in ScenarioFamily:
        for seed in HELD_OUT_SEEDS:
            episode_id = f"synthetic:{family.value}:{seed}"
            for checkpoint in CheckpointId:
                for arm in ArmId:
                    loss = (
                        CheckpointLoss.STALE_BELIEF_USE
                        if arm is ArmId.A0_FULL_LOG
                        else CheckpointLoss.CORRECT
                    )
                    weight = 3 if loss is CheckpointLoss.STALE_BELIEF_USE else 0
                    rows.append(
                        {
                            "action": ProbeAction.CONTINUE.value,
                            "arm_id": arm.value,
                            "episode_id": episode_id,
                            "family": family.value,
                            "loss_code": loss.value,
                            "loss_weight": weight,
                            "seed": seed,
                            "checkpoint_id": checkpoint.value,
                            "unsafe_effect_replay": False,
                        }
                    )
    return rows


def test_raw_metrics_compute_frozen_macro_and_sign_statistics_without_verdict() -> None:
    metrics = compute_stage_a_raw_metrics(_full_raw_rows())

    assert metrics.row_count == 2240
    assert metrics.episode_count == 140
    assert metrics.macro_mean_loss_by_arm[ArmId.A0_FULL_LOG.value] == 0.6
    assert metrics.macro_mean_loss_by_arm[ArmId.A3_TYPED_STATE.value] == 0.0
    assert metrics.a0_minus_a3_absolute_improvement == 0.6
    assert metrics.sign_positive_pairs == 140
    assert metrics.sign_negative_pairs == 0
    assert metrics.sign_ties == 0
    assert metrics.one_sided_exact_sign_p == pytest.approx(2.0**-140)
    rendered = json.dumps(metrics.to_mapping(), sort_keys=True)
    for forbidden in ("verdict", "winner", "MET", "NOT_MET"):
        assert forbidden not in rendered


def test_raw_metrics_reject_missing_duplicate_or_weight_inconsistent_rows() -> None:
    rows = _full_raw_rows()
    with pytest.raises(RawMetricViolation, match="exact Stage-A row coverage"):
        compute_stage_a_raw_metrics(rows[:-1])
    with pytest.raises(RawMetricViolation, match="duplicate raw row identity"):
        compute_stage_a_raw_metrics(rows[:-1] + [rows[0]])
    drifted = [dict(row) for row in rows]
    drifted[0]["loss_weight"] = 4
    with pytest.raises(RawMetricViolation, match="loss weight drift"):
        compute_stage_a_raw_metrics(drifted)
