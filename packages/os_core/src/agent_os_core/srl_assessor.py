from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from agent_os_contracts import (
    SrlEnvironmentEvent,
    SrlRelevanceAssessment,
    SrlRelevanceDisposition,
    StandingMission,
)

from .srl_ports import AssessorPort


class FixedAssessor(AssessorPort):
    """Deterministic assessor stub for M0 tests; returns a fixed assessment."""

    def __init__(
        self,
        *,
        instance_id: str,
        policy_digest: str,
        factory: Callable[
            [SrlEnvironmentEvent, StandingMission], SrlRelevanceAssessment
        ]
        | None = None,
    ) -> None:
        self.instance_id = instance_id
        self.policy_digest = policy_digest
        self._factory = factory or self._default_factory

    def assess(
        self, event: SrlEnvironmentEvent, mission: StandingMission
    ) -> SrlRelevanceAssessment:
        assessment = self._factory(event, mission)
        # Bind the assessor instance identity into the assessment so that
        # authority separation (I-23) can be enforced downstream.
        return assessment.model_copy(update={"assessor_version": self.instance_id})

    @staticmethod
    def _default_factory(
        event: SrlEnvironmentEvent, mission: StandingMission
    ) -> SrlRelevanceAssessment:
        now = datetime.now(timezone.utc)
        return SrlRelevanceAssessment(
            assessment_id=f"assessment:{event.event_id}",
            mandate_id=event.mandate_id,
            standing_mission_id=mission.standing_mission_id,
            trigger_event_id=event.event_id,
            evidence_refs=("evidence://event",),
            uncertainty_summary="default fixed assessment",
            urgency="MEDIUM",
            proposed_attention_budget_seconds=60,
            disposition=SrlRelevanceDisposition.OBSERVE,
            confidence=0.5,
            assessor_version="fixed-assessor:v1",
            assessor_policy_digest="sha256:assessor-policy",
            assessed_at=now,
        )
