"""Parse natural-language business questions into structured BusinessIntent.

Ported from the donor ``intent_parser``. The donor depended on ``model_gateway.ModelProviderAdapter``
(generic, superseded by Agent Core provider bindings); here the LLM path depends on a minimal typed
``StructuredModelProvider`` port that the caller injects, keeping the domain module free of any
concrete provider SDK.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from .domain_contracts import BusinessIntent


class StructuredModelProvider(Protocol):
    """Minimal typed port for the intent LLM path (caller-injected concrete adapter)."""

    def complete_structured(
        self,
        messages: list[dict[str, str]],
        output_schema: dict[str, Any],
    ) -> dict[str, Any]: ...


INTENT_PARSE_SYSTEM_PROMPT = """You are a business data analyst.
Given a natural language question in Chinese or English, extract the business intent as JSON.

Output must include:
- metric_name: the primary metric the user is asking about (lowercase, snake_case)
- question: the original question text

Available metrics: gmv, roi, revenue, conversion_rate, orders, customer_count, spend, cac

Examples:
Q: "GMV" -> {"metric_name": "gmv"}
Q: "ROI" -> {"metric_name": "roi"}
Q: "conversion rate" -> {"metric_name": "conversion_rate"}
Q: "ad spend top 5" -> {"metric_name": "spend"}
"""

INTENT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "metric_name": {"type": "string"},
        "question": {"type": "string"},
    },
    "required": ["metric_name", "question"],
    "additionalProperties": False,
}

_FALLBACK_METRICS = {
    "gmv": ["gmv"],
    "roi": ["roi"],
    "conversion_rate": ["conversion", "conversion_rate"],
    "revenue": ["revenue"],
    "orders": ["orders", "order"],
    "spend": ["spend"],
    "cac": ["cac"],
}


class IntentParser:
    """Parse natural-language business questions into structured BusinessIntent.

    Two modes: LLM (via an injected ``StructuredModelProvider``) and keyword fallback.
    """

    def __init__(self, model_provider: StructuredModelProvider | None = None) -> None:
        self._model = model_provider

    def parse(
        self,
        question: str,
        *,
        tenant_id: str = "default",
        workspace_id: str = "default",
    ) -> BusinessIntent:
        if self._model is not None:
            return self._parse_with_llm(question, tenant_id, workspace_id)
        return self._parse_with_fallback(question, tenant_id, workspace_id)

    def _parse_with_llm(self, question: str, tenant_id: str, workspace_id: str) -> BusinessIntent:
        model = self._model
        assert model is not None  # guarded by parse()
        messages = [
            {"role": "system", "content": INTENT_PARSE_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        result = model.complete_structured(messages, output_schema=INTENT_OUTPUT_SCHEMA)
        metric_name = result.get("metric_name", "unknown")
        return BusinessIntent(
            intent_id=f"intent-{uuid4().hex[:12]}",
            question=question,
            metric_name=metric_name,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    def _parse_with_fallback(
        self,
        question: str,
        tenant_id: str,
        workspace_id: str,
    ) -> BusinessIntent:
        question_lower = question.lower()
        for metric_name, keywords in _FALLBACK_METRICS.items():
            for kw in keywords:
                if kw in question_lower:
                    return BusinessIntent(
                        intent_id=f"intent-{uuid4().hex[:12]}",
                        question=question,
                        metric_name=metric_name,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                    )
        return BusinessIntent(
            intent_id=f"intent-{uuid4().hex[:12]}",
            question=question,
            metric_name="unknown",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
