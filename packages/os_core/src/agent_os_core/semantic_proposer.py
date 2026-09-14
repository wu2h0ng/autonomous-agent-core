"""SemanticProposer: Stage 2 of contract inference.

One LLM call to propose semantic predicates from mandate text + tool schemas.
Defensive JSON parsing, one retry on invalid output, fatal REJECTED on failure.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    PredicateKind,
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
    SuccessPredicate,
    derive_predicate_id,
)
from pydantic import ValidationError

from .provider import ProviderFailure, ProviderPort

MAX_SEMANTIC_PREDICATES = 15
LLM_TIMEOUT_SECONDS = 30
CLARIFICATION_THRESHOLD = 0.7

SYSTEM_INSTRUCTION = """You are a contract drafter, not a task executor. Your job is to propose machine-checkable success predicates for a task mandate.

Output ONLY a JSON array of SuccessPredicate objects. No prose. No markdown fences. No explanation.

Each SuccessPredicate has:
- predicate_id: string (derive from content, e.g. "pred:sem:001")
- kind: "SEMANTIC"
- description: string, positive specific language stating what "done" looks like
- check_type: one of TYPE, RANGE, ENUM, REGEX, CARDINALITY, FIELD_PRESENCE, STATE_DELTA, TOOL_RESPONSE, ARTIFACT_EXISTS, ARTIFACT_CONTENT, CROSS_CONSISTENCY, LLM_JUDGE
- check_params: object with parameters appropriate to check_type
- evidence_bindings: array of EvidenceBinding objects, each with binding_id, source_type, source_selector, extract_path (optional), relation
- confidence: float 0-1
- falsifiable: false (set by quality gate)
- blocking: false (set by confirmation)
- source: string identifying the model
- meta_template: one of "schema", "cardinality", "consistency", "evidence_anchor", "version_conflict", "coverage", "scope", or null
- scope_tags: [] (must be empty)

EvidenceBinding.source_type is one of TOOL_RESPONSE, ARTIFACT, ENVIRONMENT_QUERY, ACTION_RECEIPT.
EvidenceBinding.source_selector is a tool name (for TOOL_RESPONSE), artifact path (for ARTIFACT), or query descriptor (for ENVIRONMENT_QUERY).
EvidenceBinding.extract_path is a JSONPath like "$.field" or null.
EvidenceBinding.relation is a human-readable string stating what this evidence proves.
"""

META_TEMPLATE_DESCRIPTIONS = """Meta-template primitives:
- schema: type/format constraints on deliverable fields
- cardinality: how many of something (exact count, min, max)
- consistency: values across artifacts/fields agree
- evidence_anchor: a specific artifact/state that proves completion
- version_conflict: concurrent modification / stale state detection
- coverage: all items in scope were processed (no silent skips)
- scope: no unauthorized actions or out-of-scope effects"""

HARD_RULES = """Hard rules:
R1: Every predicate MUST bind to at least one EvidenceBinding with a concrete source_selector referencing an available tool response, a named artifact, or an environment query.
R2: Every predicate MUST be falsifiable: there must exist a concrete outcome state that would fail it. Do not propose tautologies.
R3: Do NOT propose predicates about the agent's reasoning, effort, or process. Only observable outcomes, artifacts, and environment state.
R4: Prefer deterministic check types. Use LLM_JUDGE only when no deterministic check can capture the condition, and mark it blocking=false.
R5: Each predicate's description must state the condition in positive, specific language.
R6: Assign confidence honestly: 0.9+ if explicitly stated; 0.7-0.9 if strongly implied; below 0.7 if inferred.
R7: Do not duplicate structural predicates listed below.
R8: Set meta_template to one of the 7 primitives if applicable, else null.
R9: scope_tags MUST be []."""

GOOD_EXAMPLE = """Good predicate example:
{"predicate_id":"pred:sem:001","kind":"SEMANTIC","description":"The selected supplier has the lowest landed cost among all qualified suppliers","check_type":"ARTIFACT_CONTENT","check_params":{"path":"comparison.json","content_assertions":[{"kind":"CARDINALITY","field":"$.qualified_suppliers","min_count":1},{"kind":"FIELD_PRESENCE","field":"$.selected_supplier.landed_cost"}]},"evidence_bindings":[{"binding_id":"bind:comp","source_type":"ARTIFACT","source_selector":"comparison.json","extract_path":"$.selected_supplier","relation":"proves the selection was recorded with cost data"}],"confidence":0.95,"falsifiable":false,"blocking":false,"source":"llm:model","meta_template":"evidence_anchor","scope_tags":[]}"""

BAD_EXAMPLE = """Bad predicate example (rejected: vague, no evidence, non-falsifiable):
{"predicate_id":"pred:bad","kind":"SEMANTIC","description":"The report looks good","check_type":"LLM_JUDGE","check_params":{"rubric":"looks good"},"evidence_bindings":[],"confidence":0.5,"falsifiable":false,"blocking":false,"source":"llm:model","meta_template":null,"scope_tags":[]}
Reason: no evidence binding, "looks good" is not falsifiable, LLM_JUDGE used when a deterministic check could work."""


class SemanticProposalError(Exception):
    """Fatal semantic proposal failure (pipeline must REJECT)."""


def build_prompt(
    mandate_text: str,
    tool_schemas_json: str,
    structural_predicates_json: str,
    deliverable_schema_json: str,
    model_id: str,
) -> tuple[ProviderMessage, ProviderMessage]:
    """Build (system, user) messages per spec §7.1."""
    system = ProviderMessage(
        role=ProviderMessageRole.SYSTEM,
        content=SYSTEM_INSTRUCTION,
    )
    user_content = f"""## Mandate
{mandate_text}

## Available tools (full JSON Schema)
{tool_schemas_json}

## Already-extracted structural predicates (do NOT duplicate these)
{structural_predicates_json}

## Deliverable schema seed
{deliverable_schema_json}

{META_TEMPLATE_DESCRIPTIONS}

{HARD_RULES}

{GOOD_EXAMPLE}

{BAD_EXAMPLE}

Return a JSON array of up to {MAX_SEMANTIC_PREDICATES} SuccessPredicate objects. Prioritize the most important conditions. Each predicate's source field must be "llm:{model_id}"."""
    user = ProviderMessage(
        role=ProviderMessageRole.USER,
        content=user_content,
    )
    return system, user


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```)
        lines = lines[1:]
        # Remove last line if it's ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_predicate_array(text: str) -> list[dict[str, Any]]:
    """Defensively parse LLM output into a list of dicts."""
    cleaned = _strip_markdown_fences(text)
    # Try direct parse
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find a JSON array in the response
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            parsed = json.loads(cleaned[start : end + 1])
        else:
            raise
    if not isinstance(parsed, list):
        raise ValueError(f"expected JSON array, got {type(parsed).__name__}")
    return parsed


def _validate_predicates(
    items: list[dict[str, Any]], model_id: str
) -> list[SuccessPredicate]:
    """Validate raw dicts into SuccessPredicate objects.

    Enforces: kind=SEMANTIC, source="llm:<model_id>", falsifiable=False,
    blocking=False, scope_tags=(), max count.
    Raises SemanticProposalError if no valid predicates.
    """
    predicates: list[SuccessPredicate] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    for i, item in enumerate(items[:MAX_SEMANTIC_PREDICATES]):
        if not isinstance(item, dict):
            errors.append(f"item {i}: not an object")
            continue
        try:
            # Force correct provenance fields.
            item["kind"] = PredicateKind.SEMANTIC.value
            item["source"] = f"llm:{model_id}"
            item["falsifiable"] = False
            item["blocking"] = False
            item["scope_tags"] = []
            # A model may never assert full confidence: only an operator
            # confirmation/clarification can make a predicate blocking.
            item["check_params"] = dict(item.get("check_params") or {})
            item["confidence"] = min(
                float(item.get("confidence", 0.0) or 0.0), 0.99
            )
            # The id is recomputed from content below; a placeholder satisfies
            # the required field during validation.
            if not item.get("predicate_id"):
                item["predicate_id"] = f"pred:sem:{i+1:03d}"
            parsed = SuccessPredicate.model_validate(item)
        except (ValidationError, TypeError, ValueError) as exc:
            errors.append(f"item {i}: invalid predicate ({type(exc).__name__})")
            continue
        # Content-derived id: a model cannot choose or collide predicate ids.
        predicate_id = derive_predicate_id(
            parsed.kind,
            parsed.check_type,
            parsed.check_params,
            parsed.evidence_bindings,
        )
        if predicate_id in seen_ids:
            continue
        seen_ids.add(predicate_id)
        predicates.append(parsed.model_copy(update={"predicate_id": predicate_id}))
    if not predicates:
        raise SemanticProposalError(
            f"semantic_proposal_failed: no valid predicates parsed; errors: {'; '.join(errors[:5])}"
        )
    return predicates


class SemanticProposer:
    """Calls the LLM once (plus one retry) to propose semantic predicates."""

    def __init__(
        self,
        provider: ProviderPort,
        model_id: str,
        *,
        provider_profile_id: str = "contract-inferencer",
    ) -> None:
        self._provider = provider
        self._model_id = model_id
        self._provider_profile_id = provider_profile_id

    def propose(
        self,
        mandate_text: str,
        tool_schemas: list[dict[str, Any]],
        structural_predicates: list[SuccessPredicate],
        deliverable_schema: dict[str, Any] | None = None,
    ) -> list[SuccessPredicate]:
        """Execute Stage 2: one LLM call, one retry, defensive parse.

        Raises SemanticProposalError on fatal failure.
        """
        tool_schemas_json = json.dumps(tool_schemas, indent=2, ensure_ascii=False)
        structural_json = json.dumps(
            [
                p.model_dump(mode="json") if hasattr(p, "model_dump") else p
                for p in structural_predicates
            ],
            indent=2,
            ensure_ascii=False,
            default=str,
        )
        deliverable_json = json.dumps(
            deliverable_schema or {}, indent=2, ensure_ascii=False
        )

        system_msg, user_msg = build_prompt(
            mandate_text, tool_schemas_json, structural_json,
            deliverable_json, self._model_id,
        )

        # First attempt
        raw_text = self._call_llm(system_msg, user_msg)
        try:
            items = _parse_predicate_array(raw_text)
            return _validate_predicates(items, self._model_id)
        except (json.JSONDecodeError, ValueError, ValidationError) as exc:
            # One retry with error feedback
            retry_msg = ProviderMessage(
                role=ProviderMessageRole.USER,
                content=f"Your previous response was invalid JSON: {exc}. Return ONLY a valid JSON array of SuccessPredicate objects. No prose, no fences.",
            )
            raw_text = self._call_llm(system_msg, user_msg, retry_msg)
            try:
                items = _parse_predicate_array(raw_text)
                return _validate_predicates(items, self._model_id)
            except (json.JSONDecodeError, ValueError, ValidationError) as exc2:
                raise SemanticProposalError(
                    f"semantic_proposal_failed: {exc2}"
                ) from exc2

    def _call_llm(
        self,
        system_msg: ProviderMessage,
        user_msg: ProviderMessage,
        extra_msg: ProviderMessage | None = None,
    ) -> str:
        """Make one LLM call, return response text."""
        messages = [system_msg, user_msg]
        if extra_msg is not None:
            messages.append(extra_msg)

        request = ProviderRequest(
            request_id=f"req-infer-{uuid4()}",
            task_id="assembly:contract-inference",
            run_id=f"run-infer-{uuid4()}",
            provider_profile_id=self._provider_profile_id,
            messages=tuple(messages),
            timeout_seconds=LLM_TIMEOUT_SECONDS,
            created_at=datetime.now(timezone.utc),
        )
        response = self._provider.complete(request)
        if isinstance(response, ProviderFailure):
            raise SemanticProposalError(
                f"semantic_proposal_failed: provider failure: {response}"
            )
        return response.text
