from __future__ import annotations

import pytest

from research_tools.active_discovery.registry import (
    Hypothesis,
    HypothesisRegistry,
    HypothesisStatus,
    HypothesisUpdate,
    RegistryValidationError,
)


def test_registry_requires_nonzero_other_in_every_alternative_group() -> None:
    hypotheses = (
        Hypothesis("h-first", "repeat", 1_000_000, HypothesisStatus.OPEN, False),
        Hypothesis("h-other", "repeat", 0, HypothesisStatus.OPEN, True),
    )

    with pytest.raises(RegistryValidationError, match="OTHER.*non-zero"):
        HypothesisRegistry(hypotheses)


def test_stale_revision_appends_without_rewriting_prior_snapshot() -> None:
    registry = HypothesisRegistry(
        (
            Hypothesis(
                "h-rule", "precedence", 800_000, HypothesisStatus.SUPPORTED, False
            ),
            Hypothesis("h-other", "precedence", 200_000, HypothesisStatus.OPEN, True),
        )
    )
    initial = registry.current

    revised = registry.append_revision(
        updates=(
            HypothesisUpdate(
                hypothesis_id="h-rule",
                probability_micros=800_000,
                status=HypothesisStatus.STALE,
            ),
        ),
        evidence_refs=("observation:7",),
        expected_parent_digest=initial.snapshot_digest,
    )

    assert registry.history[0] == initial
    assert registry.history[0].hypotheses[0].status is HypothesisStatus.SUPPORTED
    assert revised.hypotheses[0].status is HypothesisStatus.STALE
    assert revised.prior_snapshot_digest == initial.snapshot_digest


def test_conflict_revision_requires_reciprocal_same_group_links() -> None:
    registry = HypothesisRegistry(
        (
            Hypothesis("h-first", "repeat", 400_000, HypothesisStatus.OPEN, False),
            Hypothesis("h-last", "repeat", 400_000, HypothesisStatus.OPEN, False),
            Hypothesis("h-other", "repeat", 200_000, HypothesisStatus.OPEN, True),
        )
    )

    with pytest.raises(RegistryValidationError, match="reciprocal"):
        registry.append_revision(
            updates=(
                HypothesisUpdate(
                    "h-first",
                    400_000,
                    HypothesisStatus.CONFLICT,
                    conflicts_with=("h-last",),
                ),
            ),
            evidence_refs=("observation:conflict",),
            expected_parent_digest=registry.current.snapshot_digest,
        )


def test_valid_conflict_revision_preserves_reciprocal_links_in_snapshot() -> None:
    registry = HypothesisRegistry(
        (
            Hypothesis("h-first", "repeat", 400_000, HypothesisStatus.OPEN, False),
            Hypothesis("h-last", "repeat", 400_000, HypothesisStatus.OPEN, False),
            Hypothesis("h-other", "repeat", 200_000, HypothesisStatus.OPEN, True),
        )
    )

    snapshot = registry.append_revision(
        updates=(
            HypothesisUpdate(
                "h-first",
                400_000,
                HypothesisStatus.CONFLICT,
                conflicts_with=("h-last",),
            ),
            HypothesisUpdate(
                "h-last",
                400_000,
                HypothesisStatus.CONFLICT,
                conflicts_with=("h-first",),
            ),
        ),
        evidence_refs=("observation:conflict",),
        expected_parent_digest=registry.current.snapshot_digest,
    )

    by_id = {item.hypothesis_id: item for item in snapshot.hypotheses}
    assert by_id["h-first"].conflicts_with == ("h-last",)
    assert by_id["h-last"].conflicts_with == ("h-first",)
