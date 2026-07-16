from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tests.research.r_srl_1.scorer import (
    EventOutcome,
    OutcomeVerdict,
    RsrlHiddenEvaluator,
)


class RsrlOutcomeEvaluator:
    """Deterministic, fail-closed validator for R-SRL-1 hidden scorer drafts.

    Recomputes each draft ``EventOutcome`` by inspecting only the durable
    artifact records.  It never uses model narration.  Any structural
    inconsistency, missing evidence, or contradiction downgrades the verdict
    to ``INVALID``.
    """

    KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
        RsrlHiddenEvaluator.DEFAULT_PLUGINS.keys()
    )

    def validate(
        self,
        expected_outcome: dict[str, Any],
        draft: EventOutcome,
        arm_run_artifact: dict[str, Any],
    ) -> EventOutcome:
        event_id = draft.event_id
        event_type = str(expected_outcome.get("type", ""))

        # Unknown event type is an immediate fail-closed INVALID.
        if event_type not in self.KNOWN_EVENT_TYPES:
            return EventOutcome(
                event_id=event_id,
                verdict=OutcomeVerdict.INVALID,
                score=0.0,
                evidence_refs=draft.evidence_refs,
                gaps=(f"unknown expected outcome type: {event_type}",),
            )

        # INVALID drafts stay INVALID; do not let a downstream rule rehabilitate.
        if draft.verdict is OutcomeVerdict.INVALID:
            return EventOutcome(
                event_id=event_id,
                verdict=OutcomeVerdict.INVALID,
                score=0.0,
                evidence_refs=draft.evidence_refs,
                gaps=draft.gaps
                if draft.gaps
                else ("draft verdict was already INVALID",),
            )

        # Structural validation by verdict class.
        structural_gaps = self._structural_gaps(draft)
        if structural_gaps:
            return EventOutcome(
                event_id=event_id,
                verdict=OutcomeVerdict.INVALID,
                score=0.0,
                evidence_refs=draft.evidence_refs,
                gaps=structural_gaps,
            )

        # Evidence refs must point to artifacts present in the artifact bundle.
        evidence_gaps = self._evidence_gaps(draft, arm_run_artifact)
        if evidence_gaps:
            return EventOutcome(
                event_id=event_id,
                verdict=OutcomeVerdict.INVALID,
                score=0.0,
                evidence_refs=draft.evidence_refs,
                gaps=evidence_gaps,
            )

        # Recompute the outcome from artifact facts and reject contradictions.
        recomputed = self._recompute(expected_outcome, draft, arm_run_artifact)
        if recomputed.verdict != draft.verdict:
            return EventOutcome(
                event_id=event_id,
                verdict=OutcomeVerdict.INVALID,
                score=0.0,
                evidence_refs=draft.evidence_refs,
                gaps=(
                    f"draft {draft.verdict.value} contradicts recomputed {recomputed.verdict.value}",
                ),
            )

        # Draft is internally consistent and matches artifact facts.
        return draft

    def _structural_gaps(self, draft: EventOutcome) -> tuple[str, ...]:
        """Return gaps if the draft violates its own verdict's structural rules."""
        if draft.verdict is OutcomeVerdict.VERIFIED:
            if draft.score != 1.0:
                return ("VERIFIED draft requires score == 1.0",)
            if not draft.evidence_refs:
                return ("VERIFIED draft requires non-empty evidence_refs",)
            if draft.gaps:
                return ("VERIFIED draft requires empty gaps",)
        elif draft.verdict is OutcomeVerdict.NOT_MET:
            if draft.score != 0.0:
                return ("NOT_MET draft requires score == 0.0",)
            if not draft.gaps:
                return ("NOT_MET draft requires non-empty gaps",)
        elif draft.verdict is OutcomeVerdict.UNRESOLVED:
            if not draft.gaps:
                return ("UNRESOLVED draft requires non-empty gaps",)
        return ()

    def _evidence_gaps(
        self,
        draft: EventOutcome,
        artifact: dict[str, Any],
    ) -> tuple[str, ...]:
        """Return gaps if any evidence ref does not resolve to a present artifact."""
        bundle = artifact.get("artifact_bundle", {})
        if not isinstance(bundle, dict):
            bundle = {}
        missing: list[str] = []
        for ref in draft.evidence_refs:
            if not ref.startswith("artifact:"):
                missing.append(f"evidence ref {ref!r} is not an artifact: URI")
                continue
            key = ref[len("artifact:") :]
            if not isinstance(
                bundle.get(key), (str, bytes, dict, list, int, float, bool)
            ):
                missing.append(
                    f"evidence ref {ref!r} does not resolve to a present artifact"
                )
        return tuple(missing)

    def _recompute(
        self,
        expected_outcome: dict[str, Any],
        draft: EventOutcome,
        artifact: dict[str, Any],
    ) -> EventOutcome:
        """Re-run the scorer plugin for the event type from artifact facts only."""
        from agent_os_contracts import SrlEnvironmentEvent

        now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
        event = SrlEnvironmentEvent(
            event_id=draft.event_id,
            binding_id="binding-validator",
            mandate_id="mandate-validator",
            tenant_id="tenant-validator",
            workspace_id="workspace-validator",
            source_cursor="cursor-validator",
            occurred_at=now,
            received_at=now,
            event_class=str(expected_outcome.get("type", "")),
            payload_digest="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            dedupe_key=f"dedupe-{draft.event_id}",
        )

        event_type = str(expected_outcome.get("type", ""))
        plugin = RsrlHiddenEvaluator.DEFAULT_PLUGINS.get(event_type)
        if plugin is None:
            return EventOutcome(
                event_id=draft.event_id,
                verdict=OutcomeVerdict.INVALID,
                score=0.0,
                evidence_refs=draft.evidence_refs,
                gaps=(f"cannot recompute unknown event type: {event_type}",),
            )
        return plugin(event, expected_outcome, artifact)
