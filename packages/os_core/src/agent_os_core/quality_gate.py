"""Stage 3: Quality Gate — deterministic validation of proposed predicates.

Q1: Evidence binding validity (blocking rejection)
Q2: Non-vacuity (blocking rejection)
Q3: LLM_JUDGE isolation (blocking rejection)
Q4: Soundness/contradiction detection (warning, drop lower-confidence)
Q5: Coverage (warning)
Q6: Confidence routing (clarification vs confirmation)
Q7: Meta-template tagging validation
"""

from __future__ import annotations

from typing import Any

from agent_os_contracts import (
    CheckType,
    QualityGateResult,
    SuccessPredicate,
)

from .semantic_proposer import CLARIFICATION_THRESHOLD


def _has_required_params(predicate: SuccessPredicate) -> bool:
    """Check that check_params contains non-trivial constraints for the check_type."""
    params = predicate.check_params
    ct = predicate.check_type

    if ct is CheckType.TYPE:
        return isinstance(params.get("expected_type"), str)
    if ct is CheckType.RANGE:
        return (
            isinstance(params.get("min"), (int, float))
            or isinstance(params.get("max"), (int, float))
        )
    if ct is CheckType.ENUM:
        return isinstance(params.get("allowed_values"), list) and len(params["allowed_values"]) > 0
    if ct is CheckType.REGEX:
        return isinstance(params.get("pattern"), str) and len(params["pattern"]) > 0
    if ct is CheckType.CARDINALITY:
        return (
            isinstance(params.get("min_count"), int)
            or isinstance(params.get("max_count"), int)
            or isinstance(params.get("target"), str)
        )
    if ct is CheckType.FIELD_PRESENCE:
        return True  # presence itself is the constraint
    if ct is CheckType.STATE_DELTA:
        return isinstance(params.get("snapshot"), str)
    if ct is CheckType.TOOL_RESPONSE:
        return (
            isinstance(params.get("tool_name"), str)
            and isinstance(params.get("condition"), dict)
        )
    if ct is CheckType.ARTIFACT_EXISTS:
        return isinstance(params.get("path"), str)
    if ct is CheckType.ARTIFACT_CONTENT:
        return isinstance(params.get("path"), str)
    if ct is CheckType.CROSS_CONSISTENCY:
        return (
            isinstance(params.get("refs"), list)
            and isinstance(params.get("relation"), str)
        )
    if ct is CheckType.LLM_JUDGE:
        return isinstance(params.get("rubric"), str)
    return False


def _binding_references_available_source(
    predicate: SuccessPredicate,
    available_tool_names: set[str],
) -> bool:
    """Q1: every binding references an available tool or plausible artifact/env."""
    for binding in predicate.evidence_bindings:
        st = binding.source_type
        selector = binding.source_selector
        if st.value == "TOOL_RESPONSE":
            # selector may be "tool_name" or "tool_name:last" etc.
            tool_name = selector.split(":")[0].split(".")[-1]
            if tool_name not in available_tool_names:
                return False
        elif st.value == "ARTIFACT":
            if not selector or not isinstance(selector, str):
                return False
        elif st.value == "ENVIRONMENT_QUERY":
            if not selector or not isinstance(selector, str):
                return False
        elif st.value == "ACTION_RECEIPT":
            if not selector or not isinstance(selector, str):
                return False
    return True


def _is_duplicate_of_structural(
    predicate: SuccessPredicate,
    structural_predicates: list[SuccessPredicate],
) -> bool:
    """Q2: FIELD_PRESENCE is vacuous if a structural predicate already guarantees it."""
    if predicate.check_type is not CheckType.FIELD_PRESENCE:
        return False
    for sp in structural_predicates:
        if sp.check_type is CheckType.FIELD_PRESENCE:
            # Same binding path → duplicate
            if (
                sp.evidence_bindings
                and predicate.evidence_bindings
                and sp.evidence_bindings[0].extract_path
                == predicate.evidence_bindings[0].extract_path
                and sp.evidence_bindings[0].source_selector
                == predicate.evidence_bindings[0].source_selector
            ):
                return True
    return False


def _detect_contradictions(
    predicates: list[SuccessPredicate],
) -> tuple[list[SuccessPredicate], list[str]]:
    """Q4: detect contradictory predicates on the same path. Drop lower-confidence."""
    warnings: list[str] = []
    by_path: dict[str, list[SuccessPredicate]] = {}
    for p in predicates:
        for b in p.evidence_bindings:
            key = f"{b.source_selector}:{b.extract_path}"
            by_path.setdefault(key, []).append(p)

    drop_ids: set[str] = set()
    for path, preds in by_path.items():
        if len(preds) < 2:
            continue
        ranges = [
            p for p in preds
            if p.check_type is CheckType.RANGE and p.predicate_id not in drop_ids
        ]
        if len(ranges) >= 2:
            for i in range(len(ranges)):
                for j in range(i + 1, len(ranges)):
                    a, b = ranges[i], ranges[j]
                    a_max = a.check_params.get("max")
                    b_min = b.check_params.get("min")
                    a_min = a.check_params.get("min")
                    b_max = b.check_params.get("max")
                    if (
                        isinstance(a_max, (int, float))
                        and isinstance(b_min, (int, float))
                        and a_max < b_min
                    ):
                        loser = a if a.confidence <= b.confidence else b
                        drop_ids.add(loser.predicate_id)
                        warnings.append(
                            f"Q4 contradiction on {path}: "
                            f"max={a_max} < min={b_min}; dropped {loser.predicate_id}"
                        )
                    elif (
                        isinstance(b_max, (int, float))
                        and isinstance(a_min, (int, float))
                        and b_max < a_min
                    ):
                        loser = a if a.confidence <= b.confidence else b
                        drop_ids.add(loser.predicate_id)
                        warnings.append(
                            f"Q4 contradiction on {path}: "
                            f"max={b_max} < min={a_min}; dropped {loser.predicate_id}"
                        )

    survivors = [p for p in predicates if p.predicate_id not in drop_ids]
    return survivors, warnings


def run_quality_gate(
    semantic_predicates: list[SuccessPredicate],
    structural_predicates: list[SuccessPredicate],
    available_tool_names: set[str],
    deliverable_schema: dict[str, Any] | None = None,
) -> QualityGateResult:
    """Run Q1-Q7 over semantic predicates. Returns QualityGateResult."""
    accepted: list[SuccessPredicate] = []
    rejected: list[tuple[SuccessPredicate, str]] = []
    warnings: list[str] = []
    coverage_gaps: list[str] = []

    # Q1-Q3: blocking rejections
    for pred in semantic_predicates:
        # Q1: evidence binding validity
        if not pred.evidence_bindings:
            rejected.append((pred, "Q1: no evidence bindings"))
            continue
        if not _binding_references_available_source(pred, available_tool_names):
            rejected.append((pred, "Q1: binding references unknown source"))
            continue

        # Q2: non-vacuity
        if pred.check_type is not CheckType.LLM_JUDGE:
            if not _has_required_params(pred):
                rejected.append((pred, "Q2: missing required check_params"))
                continue
            if _is_duplicate_of_structural(pred, structural_predicates):
                rejected.append((pred, "Q2: duplicates structural predicate"))
                continue

        # Q3: LLM_JUDGE isolation
        if pred.check_type is CheckType.LLM_JUDGE and pred.blocking:
            rejected.append((pred, "Q3: LLM_JUDGE must be non-blocking"))
            continue

        # Q7: meta-template validation
        if pred.meta_template is not None:
            from agent_os_contracts.contract_inference import ALLOWED_META_TEMPLATES
            if pred.meta_template not in ALLOWED_META_TEMPLATES:
                rejected.append((pred, f"Q7: invalid meta_template {pred.meta_template}"))
                continue

        accepted.append(pred)

    # Q4: contradiction detection (warning, drops lower-confidence)
    accepted, contradiction_warnings = _detect_contradictions(accepted)
    warnings.extend(contradiction_warnings)

    # Q5: coverage
    if deliverable_schema and isinstance(deliverable_schema, dict):
        properties = deliverable_schema.get("properties", {})
        if isinstance(properties, dict):
            referenced_paths: set[str] = set()
            for pred in accepted + structural_predicates:
                for b in pred.evidence_bindings:
                    if b.extract_path:
                        referenced_paths.add(b.extract_path)
            for field_name in properties:
                if not any(f"$.{field_name}" in p for p in referenced_paths):
                    coverage_gaps.append(field_name)

    # Q6: confidence routing
    clarification_needed: list[SuccessPredicate] = []
    confirmation_needed: list[SuccessPredicate] = []
    for pred in accepted:
        if pred.check_type is CheckType.LLM_JUDGE:
            # LLM_JUDGE is advisory, no confirmation needed for blocking
            continue
        if pred.confidence < CLARIFICATION_THRESHOLD:
            clarification_needed.append(pred)
        else:
            confirmation_needed.append(pred)

    # Set falsifiable=True on accepted predicates
    accepted = [
        pred.model_copy(update={"falsifiable": True}) for pred in accepted
    ]
    clarification_needed = [
        pred.model_copy(update={"falsifiable": True}) for pred in clarification_needed
    ]
    confirmation_needed = [
        pred.model_copy(update={"falsifiable": True}) for pred in confirmation_needed
    ]

    return QualityGateResult(
        accepted=tuple(accepted),
        rejected=tuple((p, r) for p, r in rejected),
        clarification_needed=tuple(clarification_needed),
        confirmation_needed=tuple(confirmation_needed),
        warnings=tuple(warnings),
        coverage_gaps=tuple(coverage_gaps),
    )
