"""Pure public Stage 1 precedence; never an experiment runner or scorer."""

from __future__ import annotations

from .contracts import (
    ComparisonRelation,
    FeasibilityState,
    IntegrityState,
    NondominanceObservationV1,
    SafetyState,
    Stage1AdjudicationV1,
    Stage1Disposition,
)
from .public_custody import ValidatedStage1EvidenceV1


def adjudicate_stage1(evidence: ValidatedStage1EvidenceV1) -> Stage1AdjudicationV1:
    """Apply frozen fail-closed precedence to already validated public evidence."""

    if evidence.safety is SafetyState.REGRESSION:
        return Stage1AdjudicationV1(
            Stage1Disposition.KILL_CURRENT_IMPLEMENTATION, (), ()
        )
    if evidence.integrity is IntegrityState.FAIL:
        return Stage1AdjudicationV1(Stage1Disposition.INVALID, (), ())
    if evidence.feasibility is FeasibilityState.INSUFFICIENT:
        return Stage1AdjudicationV1(
            Stage1Disposition.PARK_INSUFFICIENT_FEASIBILITY, (), ()
        )

    observations = tuple(
        NondominanceObservationV1(block.block_id, relation.comparator_id)
        for block in evidence.blocks
        for relation in block.relations
        if relation.relation is ComparisonRelation.COMPARATOR_MATCH_OR_WIN
    )
    if observations:
        return Stage1AdjudicationV1(
            Stage1Disposition.PARK_STAGE1_NONDOMINANCE, observations, ()
        )
    return Stage1AdjudicationV1(
        Stage1Disposition.ADVANCE_TO_STAGE2_DESIGN,
        (),
        ("NO_MET", "NEW_PREREG_REQUIRED"),
    )


__all__ = ["adjudicate_stage1"]
