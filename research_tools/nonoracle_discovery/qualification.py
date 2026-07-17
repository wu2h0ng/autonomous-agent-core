from __future__ import annotations

from dataclasses import dataclass

from .baselines import (
    correlation_baseline,
    finite_screen_baseline,
    pooled_shift_baseline,
)
from .contracts import InterventionDataset, content_digest
from .mechanism import StabilityCalibration, discover


@dataclass(frozen=True, slots=True)
class SyntheticQualificationFixture:
    dataset: InterventionDataset
    true_relation: tuple[str, str]
    confounded_relation: tuple[str, str]
    unstable_artifact_relation: tuple[str, str]


@dataclass(frozen=True, slots=True)
class QualificationReceipt:
    mode: str
    public_view_digest: str
    calibration_digest: str
    mechanism_recovers_true_relation: bool
    correlation_selects_confounded_relation: bool
    pooled_shift_selects_unstable_artifact: bool
    mechanism_rejects_unstable_artifact: bool
    expected_hypotheses: tuple[tuple[str, str], ...]
    mechanism_hypotheses: tuple[tuple[str, str], ...]
    arm_scores: tuple[QualificationArmScore, ...]
    receipt_digest: str


@dataclass(frozen=True, slots=True)
class QualificationArmScore:
    arm_id: str
    hypotheses: tuple[tuple[str, str], ...]
    true_positives: int
    false_positives: int
    false_negatives: int
    f1_micros: int


@dataclass(frozen=True, slots=True)
class QualificationDisposition:
    status: str
    reasons: tuple[str, ...]
    freeze_authorized: bool = False
    run_authorized: bool = False


def adjudicate_qualification(
    *,
    mechanism_pairs: set[tuple[str, str]],
    expected: set[tuple[str, str]],
    matched_k: int,
    baseline_count: int,
    attack_gate_passed: bool,
    calibration_gate_passed: bool,
    binding_gate_passed: bool,
) -> QualificationDisposition:
    reasons: list[str] = []
    if mechanism_pairs != expected:
        reasons.append("MECHANISM_HYPOTHESES_NOT_EXACT")
    if baseline_count != matched_k:
        reasons.append("BASELINE_NOT_EXACT_K")
    if not attack_gate_passed:
        reasons.append("ATTACK_GATE_NOT_PASSED")
    if not calibration_gate_passed:
        reasons.append("CALIBRATION_GATE_NOT_PASSED")
    if not binding_gate_passed:
        reasons.append("BINDING_GATE_NOT_PASSED")
    return QualificationDisposition(
        "LOCAL_CONDITIONS_MET_NOT_FREEZE_AUTHORITY" if not reasons else "REJECT",
        tuple(reasons),
    )


def confounded_indirect_fixture() -> SyntheticQualificationFixture:
    source_keys = (0.0, 7.0, 1.0, 6.0, 2.0, 5.0, 3.0, 4.0)
    control = tuple(
        (source_keys[index], float(index), float(index)) for index in range(8)
    )
    stable = tuple(
        (float(index), float(index), 8.0 + 0.1 * (index % 2)) for index in range(8)
    )
    unstable = tuple(
        (
            source_keys[index],
            float(index),
            10.0 if index % 2 == 0 else float(index),
        )
        for index in range(8)
    )
    dataset = InterventionDataset.create(
        ("v0", "v1", "v2"),
        control,
        {"c0": stable, "c1": unstable},
        {"c0": "v0", "c1": "v1"},
    )
    return SyntheticQualificationFixture(
        dataset=dataset,
        true_relation=("v0", "v2"),
        confounded_relation=("v1", "v2"),
        unstable_artifact_relation=("v1", "v2"),
    )


def _pairs(values: tuple[object, ...]) -> set[tuple[str, str]]:
    return {(item.source, item.target) for item in values}  # type: ignore[attr-defined]


def _score_arm(
    arm_id: str,
    values: tuple[object, ...],
    expected: set[tuple[str, str]],
) -> QualificationArmScore:
    hypotheses = _pairs(values)
    true_positives = len(hypotheses & expected)
    false_positives = len(hypotheses - expected)
    false_negatives = len(expected - hypotheses)
    denominator = 2 * true_positives + false_positives + false_negatives
    f1_micros = (
        0 if denominator == 0 else round(2 * true_positives * 1_000_000 / denominator)
    )
    return QualificationArmScore(
        arm_id=arm_id,
        hypotheses=tuple(sorted(hypotheses)),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        f1_micros=f1_micros,
    )


def run_synthetic_qualification() -> QualificationReceipt:
    fixture = confounded_indirect_fixture()
    calibration = StabilityCalibration(
        exact_null_quantile_micros=950_000,
        max_exact_combinations=20_000,
        minimum_effect_micros=500_000,
    )
    mechanism = discover(fixture.dataset, calibration)
    matched_k = max(1, len(mechanism))
    correlation = correlation_baseline(fixture.dataset, k=matched_k)
    pooled = pooled_shift_baseline(fixture.dataset, threshold_micros=500_000)
    finite = finite_screen_baseline(fixture.dataset)
    mechanism_pairs = _pairs(mechanism)
    correlation_pairs = _pairs(correlation)
    pooled_pairs = _pairs(pooled)
    expected = {fixture.true_relation}
    arm_scores = (
        _score_arm("INTERVENTION_STABILITY", mechanism, expected),
        _score_arm("OBSERVATIONAL_ABS_CORRELATION_MATCHED_K", correlation, expected),
        _score_arm("FIXED_THRESHOLD_POOLED_MEAN_SHIFT", pooled, expected),
        _score_arm("FINITE_SCREEN_ALL_LEGAL_PAIRS", finite, expected),
    )
    values = {
        "mode": "SYNTHETIC_QUALIFICATION_NOT_EVIDENCE",
        "public_view_digest": fixture.dataset.public_view_digest,
        "calibration_digest": calibration.digest,
        "mechanism_recovers_true_relation": fixture.true_relation in mechanism_pairs,
        "correlation_selects_confounded_relation": fixture.confounded_relation
        in correlation_pairs,
        "pooled_shift_selects_unstable_artifact": fixture.unstable_artifact_relation
        in pooled_pairs,
        "mechanism_rejects_unstable_artifact": fixture.unstable_artifact_relation
        not in mechanism_pairs,
        "expected_hypotheses": tuple(sorted(expected)),
        "mechanism_hypotheses": tuple(sorted(mechanism_pairs)),
        "arm_scores": arm_scores,
    }
    digest_values = {
        **values,
        "arm_scores": [
            {
                "arm_id": arm.arm_id,
                "hypotheses": arm.hypotheses,
                "true_positives": arm.true_positives,
                "false_positives": arm.false_positives,
                "false_negatives": arm.false_negatives,
                "f1_micros": arm.f1_micros,
            }
            for arm in arm_scores
        ],
    }
    return QualificationReceipt(
        **values,
        receipt_digest=content_digest(
            "nonoracle-synthetic-qualification/v1", digest_values
        ),
    )
