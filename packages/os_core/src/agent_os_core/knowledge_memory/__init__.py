from __future__ import annotations

from agent_os_contracts import FeedbackEvent, KnowledgeAsset


class KnowledgeMemory:
    def draft_from_feedback(
        self,
        *,
        asset_id: str,
        feedback: FeedbackEvent,
        owner: str,
    ) -> KnowledgeAsset:
        return KnowledgeAsset(
            asset_id=asset_id,
            title=f"Learning from {feedback.trace_id}",
            asset_type="feedback_case",
            source_trace_id=feedback.trace_id,
            owner=owner,
        )
