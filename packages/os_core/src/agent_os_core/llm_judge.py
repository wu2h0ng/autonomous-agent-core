"""LLM_JUDGE advisory checker (spec §4.4, §11.2).

Uses a cross-family judge model to evaluate rubric-based predicates.
Results are advisory: recorded as evidence but never block a verdict.
The judge model MUST be from a different family than the proposer (spec §16.6).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
    SuccessPredicate,
)

from .evidence_accessor import EvidenceAccessor
from .provider import ProviderFailure, ProviderPort

JUDGE_TIMEOUT_SECONDS = 30

JUDGE_SYSTEM_PROMPT = """You are an impartial judge evaluating whether task evidence satisfies a rubric.
You do NOT execute tasks. You only evaluate given evidence against a criterion.

You must respond with a single JSON object:
{"verdict": "pass" | "fail", "reasoning": "one sentence explanation", "confidence": 0.0-1.0}

Rules:
- "pass" only if the evidence clearly satisfies the rubric.
- "fail" if the evidence contradicts the rubric or is insufficient.
- Do not invent evidence not present in the provided content.
- Output ONLY the JSON object, no prose, no markdown fences."""


class LLMJudgeChecker:
    """Advisory LLM judge for LLM_JUDGE predicates.

    The judge provider should use a model from a different family than the
    proposer to avoid correlated errors (cross-family validation).
    """

    def __init__(
        self,
        judge_provider: ProviderPort,
        *,
        judge_model_id: str = "llm-judge",
        provider_profile_id: str = "contract-inferencer-judge",
    ) -> None:
        self._provider = judge_provider
        self._judge_model_id = judge_model_id
        self._provider_profile_id = provider_profile_id

    def check(
        self,
        predicate: SuccessPredicate,
        accessor: EvidenceAccessor,
    ) -> tuple[bool | None, tuple[str, ...], str]:
        """Evaluate an LLM_JUDGE predicate against evidence.

        Returns (passed, evidence_refs, detail).
        passed is None if the judge is unavailable or returns invalid output.
        Advisory: the caller must not use the result to block.
        """
        rubric = predicate.check_params.get("rubric", "")
        if not isinstance(rubric, str) or not rubric.strip():
            return None, (), "missing rubric"

        # Gather evidence content from bindings
        evidence_texts: list[str] = []
        refs: list[str] = []
        for binding in predicate.evidence_bindings:
            content = self._read_binding(binding, accessor)
            if content is not None:
                evidence_texts.append(
                    f"--- Evidence from {binding.source_selector} ---\n{content}"
                )
                refs.append(binding.source_selector)

        if not evidence_texts:
            return None, tuple(refs), "no evidence available for judgment"

        evidence_blob = "\n\n".join(evidence_texts)[:8000]  # cap context

        user_content = f"""## Rubric
{rubric}

## Evidence
{evidence_blob}

Evaluate whether the evidence satisfies the rubric. Return JSON only."""

        request = ProviderRequest(
            request_id=f"req-judge-{uuid4()}",
            task_id="assembly:llm-judge",
            run_id=f"run-judge-{uuid4()}",
            provider_profile_id=self._provider_profile_id,
            messages=(
                ProviderMessage(
                    role=ProviderMessageRole.SYSTEM,
                    content=JUDGE_SYSTEM_PROMPT,
                ),
                ProviderMessage(
                    role=ProviderMessageRole.USER,
                    content=user_content,
                ),
            ),
            timeout_seconds=JUDGE_TIMEOUT_SECONDS,
            created_at=datetime.now(timezone.utc),
        )

        response = self._provider.complete(request)
        if isinstance(response, ProviderFailure):
            return None, tuple(refs), f"judge unavailable: {response.safe_message}"

        try:
            result = self._parse_verdict(response.text)
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            return None, tuple(refs), f"judge returned invalid output: {exc}"

        verdict = result.get("verdict")
        reasoning = result.get("reasoning", "")
        if verdict == "pass":
            return True, tuple(refs), f"judge: {reasoning}"
        elif verdict == "fail":
            return False, tuple(refs), f"judge: {reasoning}"
        return None, tuple(refs), f"judge returned unknown verdict: {verdict}"

    @staticmethod
    def _parse_verdict(text: str) -> dict[str, Any]:
        """Parse judge JSON output, stripping fences."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("expected JSON object")
        if "verdict" not in parsed:
            raise ValueError("missing verdict field")
        return parsed

    @staticmethod
    def _read_binding(
        binding: Any, accessor: EvidenceAccessor
    ) -> str | None:
        """Read evidence content from a binding as text for the judge."""
        source_type = binding.source_type.value if hasattr(binding.source_type, "value") else str(binding.source_type)
        selector = binding.source_selector
        path = binding.extract_path

        if source_type == "ARTIFACT":
            raw = accessor.artifact_content(selector)
            if raw is None:
                return None
            try:
                text = raw.decode("utf-8", errors="replace")
            except (UnicodeDecodeError, AttributeError):
                return None
            if path:
                try:
                    data = json.loads(text)
                    from .predicate_checkers import _extract_path
                    value = _extract_path(data, path)
                    return json.dumps(value, indent=2, ensure_ascii=False, default=str)
                except json.JSONDecodeError:
                    pass
            return text[:4000]

        if source_type == "TOOL_RESPONSE":
            tool_name = selector.split(":")[0]
            result = accessor.tool_result(tool_name)
            if result is None:
                return None
            if path:
                from .predicate_checkers import _extract_path
                value = _extract_path(result, path)
                return json.dumps(value, indent=2, ensure_ascii=False, default=str)
            return json.dumps(result, indent=2, ensure_ascii=False, default=str)[:4000]

        return None
