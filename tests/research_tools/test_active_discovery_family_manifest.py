from __future__ import annotations

from dataclasses import replace

import pytest

from research_tools.active_discovery.canonical import canonical_json
from research_tools.active_discovery.catalogue import (
    CatalogueValidationError,
    VisibleProbeCandidate,
    VisibleProbeCatalogue,
)
from research_tools.active_discovery.families.manifest import (
    FAMILY_MANIFEST_SCHEMA,
    FamilyCode,
    FamilyManifest,
    ManifestValidationError,
)
from research_tools.active_discovery.selector import (
    HypothesisPrediction,
    HypothesisWeight,
    OutcomeLikelihood,
)


def _predictions(
    zero_label: str = "opaque-zero", nonzero_label: str = "opaque-nonzero"
) -> tuple[HypothesisPrediction, ...]:
    return (
        HypothesisPrediction(
            "hypothesis-a",
            (
                OutcomeLikelihood(zero_label, 900_000),
                OutcomeLikelihood(nonzero_label, 100_000),
            ),
        ),
        HypothesisPrediction(
            "hypothesis-b",
            (
                OutcomeLikelihood(zero_label, 100_000),
                OutcomeLikelihood(nonzero_label, 900_000),
            ),
        ),
    )


def _candidate(
    *,
    probe_id: str = "probe-1",
    stable_order: int = 0,
    payload_json: str = '{"opaque":1}',
    cost_units: int = 1,
    zero_label: str = "opaque-zero",
    nonzero_label: str = "opaque-nonzero",
) -> VisibleProbeCandidate:
    return VisibleProbeCandidate(
        probe_id=probe_id,
        stable_order=stable_order,
        payload_json=payload_json,
        cost_units=cost_units,
        zero_status_label=zero_label,
        nonzero_status_label=nonzero_label,
        predictions=_predictions(zero_label, nonzero_label),
    )


def _catalogue() -> VisibleProbeCatalogue:
    return VisibleProbeCatalogue(
        candidates=(
            _candidate(),
            _candidate(
                probe_id="probe-2",
                stable_order=1,
                payload_json='{"opaque":2}',
            ),
        ),
        initial_weights=(
            HypothesisWeight("hypothesis-a", 500_000),
            HypothesisWeight("hypothesis-b", 500_000),
        ),
    )


def _manifest_mapping() -> dict[str, object]:
    return {
        "schema_version": FAMILY_MANIFEST_SCHEMA,
        "mode": "NOT_EVIDENCE",
        "family_code": "F2",
        "seed": 17,
        "probe_budget_units": 2,
        "descriptor_digest": "1" * 64,
        "catalogue_digest": "2" * 64,
        "hidden_configuration_digest": "3" * 64,
    }


def test_family_manifest_is_closed_and_not_evidence_only() -> None:
    unknown = _manifest_mapping()
    unknown["hidden_rules"] = {"ttl": 2}

    with pytest.raises(ManifestValidationError, match="unknown fields"):
        FamilyManifest.from_mapping(unknown)

    wrong_mode = _manifest_mapping()
    wrong_mode["mode"] = "EVIDENCE"
    with pytest.raises(ManifestValidationError, match="NOT_EVIDENCE"):
        FamilyManifest.from_mapping(wrong_mode)


def test_family_manifest_digest_is_stable_and_binds_every_field() -> None:
    baseline = FamilyManifest.from_mapping(_manifest_mapping())
    equivalent = FamilyManifest.from_mapping(
        dict(reversed(_manifest_mapping().items()))
    )
    variants = (
        replace(baseline, family_code=FamilyCode.F3),
        replace(baseline, seed=18),
        replace(baseline, probe_budget_units=1),
        replace(baseline, descriptor_digest="4" * 64),
        replace(baseline, catalogue_digest="5" * 64),
        replace(baseline, hidden_configuration_digest="6" * 64),
    )

    assert equivalent.manifest_digest == baseline.manifest_digest
    assert all(item.manifest_digest != baseline.manifest_digest for item in variants)


def test_visible_catalogue_requires_unit_cost_and_exact_likelihood_domain() -> None:
    with pytest.raises(CatalogueValidationError, match="unit cost"):
        _candidate(cost_units=2)

    with pytest.raises(CatalogueValidationError, match="outcome labels"):
        VisibleProbeCandidate(
            probe_id="probe-bad-labels",
            stable_order=0,
            payload_json="{}",
            cost_units=1,
            zero_status_label="opaque-zero",
            nonzero_status_label="opaque-nonzero",
            predictions=_predictions("different-zero", "different-nonzero"),
        )


def test_visible_catalogue_digest_is_stable_and_content_sensitive() -> None:
    baseline = _catalogue()
    equivalent = _catalogue()
    changed_payload = VisibleProbeCatalogue(
        candidates=(
            replace(
                baseline.candidates[0],
                payload_json=canonical_json({"opaque": 99}),
            ),
            baseline.candidates[1],
        ),
        initial_weights=baseline.initial_weights,
    )

    assert equivalent.catalogue_digest == baseline.catalogue_digest
    assert changed_payload.catalogue_digest != baseline.catalogue_digest
