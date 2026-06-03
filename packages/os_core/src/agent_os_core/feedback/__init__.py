from __future__ import annotations

from uuid import uuid4

from agent_os_contracts import FeedbackEvent


class FeedbackRuntime:
    def capture(
        self,
        *,
        trace_id: str,
        outcome: str,
        metrics: dict[str, object] | None = None,
    ) -> FeedbackEvent:
        return FeedbackEvent(
            feedback_id=f"feedback-{uuid4().hex[:12]}",
            trace_id=trace_id,
            outcome=outcome,
            metrics=metrics or {},
        )
