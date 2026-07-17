from __future__ import annotations

from dataclasses import dataclass

from .baselines import correlation_baseline, pooled_shift_baseline
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
    receipt_digest: str


def confounded_indirect_fixture() -> SyntheticQualificationFixture:
    control = tuple(
        (
            -1.0 if index % 2 == 0 else 1.0,
            float(index),
            float(index),
        )
        for index in range(8)
    )
    stable = tuple(
        (float(index), float(index), 8.0 + 0.1 * (index % 2))
        for index in range(8)
    )
    unstable = tuple(
        (
            float(index),
            float(index),
            10.0 if index % 2 == 0 else float(index),
        )
        for index in range(8)
    )
    dataset = InterventionDataset.create(
        ("v0", "v1", "v2"),
        control,
        {"condition-v0": stable, "condition-v1": unstable},
        {"condition-v0": "v0", "condition-v1": "v1"},
    )
    return SyntheticQualificationFixture(
        dataset=dataset,
        true_relation=("v0", "v2"),
        confounded_relation=("v1", "v2"),
        unstable_artifact_relation=("v1", "v2"),
    )


def _pairs(values: tuple[object, ...]) -> set[tuple[str, str]]:
    return {(item.source, item.target) for item in values}  # type: ignore[attr-defined]


def run_synthetic_qualification() -> QualificationReceipt:
    fixture = confounded_indirect_fixture()
    calibration = StabilityCalibration(
        permutation_offsets=(1, 3, 5),
        minimum_effect_micros=500_000,
    )
    mechanism_pairs = _pairs(discover(fixture.dataset, calibration))
    correlation_pairs = _pairs(correlation_baseline(fixture.dataset, k=1))
    pooled_pairs = _pairs(
        pooled_shift_baseline(fixture.dataset, threshold_micros=500_000)
    )
    values = {
        "mode": "SYNTHETIC_QUALIFICATION_NOT_EVIDENCE",
        "public_view_digest": fixture.dataset.public_view_digest,
        "calibration_digest": calibration.digest,
        "mechanism_recovers_true_relation": fixture.true_relation in mechanism_pairs,
        "correlation_selects_confounded_relation": fixture.confounded_relation in correlation_pairs,
        "pooled_shift_selects_unstable_artifact": fixture.unstable_artifact_relation in pooled_pairs,
        "mechanism_rejects_unstable_artifact": fixture.unstable_artifact_relation not in mechanism_pairs,
    }
    return QualificationReceipt(
        **values,
        receipt_digest=content_digest("nonoracle-synthetic-qualification/v1", values),
    )
