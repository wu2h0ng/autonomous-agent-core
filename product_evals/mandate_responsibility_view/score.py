"""Deterministic scorer for the design-only responsibility-view falsifier.

This module validates already-frozen inputs. It does not freeze artifacts,
assign participants, run observations, write results, or authorize claims.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, cast


class ScoreInputError(ValueError):
    """Raised when an evaluation input violates the frozen scoring contract."""


_ARM_SEQUENCE = {
    ("BASELINE", "TREATMENT"),
    ("TREATMENT", "BASELINE"),
}
_ATTENTION_STATES = {"NEEDS_ATTENTION", "UNKNOWN"}
_ROW_STATES = _ATTENTION_STATES | {"TRACKED", "DONE_VERIFIED"}
_REASON_CLASSES = {"NONE", "SOURCE_GAP", "NON_SOURCE_GAP"}
_SOURCE_GAP_REASONS = {
    "MANDATE_AUTHORITY_MISSING",
    "MANDATE_AUTHORITY_MISMATCH",
    "MANDATE_CORRECTION_DRIFT",
    "SCHEDULE_SOURCE_MALFORMED",
    "TASK_IDENTITY_CHANGED",
    "TASK_SOURCE_MALFORMED",
    "TASK_SOURCE_MISSING",
    "UNHANDLED_TASK_RUN_STATE",
    "UNSUPPORTED_EVALUATOR",
    "WAIT_CONDITION_MALFORMED",
    "WAIT_CONDITION_MISSING",
}
_NON_SOURCE_GAP_REASONS = {
    "COMMITMENT_EXPIRED",
    "OUTCOME_INVALID",
    "OUTCOME_NOT_MET",
    "OUTCOME_UNRESOLVED",
    "TASK_CANCELLED",
    "TASK_FAILED",
    "TASK_PAUSED",
    "TERMINAL_WITHOUT_OUTCOME",
    "WAIT_DEADLINE_ARRIVED",
    "WAITING_APPROVAL",
}
_CANONICAL_REASONS = _SOURCE_GAP_REASONS | _NON_SOURCE_GAP_REASONS


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ScoreInputError(f"{label} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ScoreInputError(f"{label} keys must be strings")
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ScoreInputError(f"{label} must be an array")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ScoreInputError(f"{label} fields are invalid")


def canonical_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ScoreInputError("value is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def canonical_artifact_hashes(
    artifacts: Mapping[str, object],
) -> dict[str, str]:
    values = _mapping(artifacts, "artifacts")
    if any(not name for name in values):
        raise ScoreInputError("artifact names must be non-empty")
    return {name: canonical_sha256(values[name]) for name in sorted(values)}


def validate_artifact_hashes(
    artifacts: Mapping[str, object],
    expected_hashes: Mapping[str, object],
) -> None:
    expected = _mapping(expected_hashes, "expected artifact hashes")
    actual = canonical_artifact_hashes(artifacts)
    if set(expected) != set(actual) or any(
        expected[name] != actual[name] for name in actual
    ):
        raise ScoreInputError("artifact hash mismatch")


def _sha256_digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ScoreInputError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _normalize_assignments(value: object) -> list[dict[str, object]]:
    assignments: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in _sequence(value, "order assignments"):
        assignment = _mapping(raw, "order assignment")
        _exact_keys(assignment, {"pair_id", "sequence"}, "order assignment")
        pair_id = assignment["pair_id"]
        if not isinstance(pair_id, str) or not pair_id or pair_id in seen:
            raise ScoreInputError("order assignment pair ids must be unique")
        sequence = tuple(_sequence(assignment["sequence"], "arm sequence"))
        if sequence not in _ARM_SEQUENCE:
            raise ScoreInputError("arm sequence must contain baseline and treatment")
        seen.add(pair_id)
        assignments.append({"pair_id": pair_id, "sequence": list(sequence)})
    if not assignments:
        raise ScoreInputError("order assignments cannot be empty")
    return sorted(assignments, key=lambda item: str(item["pair_id"]))


def _order_body(
    method: object,
    assignments: object,
    *,
    randomization_seed_digest: object,
    counterbalance_key: object,
    randomization_seed_material: object,
) -> dict[str, object]:
    if method not in {"RANDOMIZED", "COUNTERBALANCED"}:
        raise ScoreInputError("order method must be randomized or counterbalanced")
    normalized = _normalize_assignments(assignments)
    if method == "RANDOMIZED":
        seed = _sha256_digest(
            randomization_seed_digest,
            "randomization seed digest",
        )
        if (
            not isinstance(randomization_seed_material, str)
            or not randomization_seed_material
        ):
            raise ScoreInputError(
                "randomized generation proof requires frozen seed material"
            )
        actual_seed_digest = hashlib.sha256(
            randomization_seed_material.encode("utf-8")
        ).hexdigest()
        if actual_seed_digest != seed:
            raise ScoreInputError("randomized generation proof seed digest mismatch")
        if counterbalance_key is not None:
            raise ScoreInputError("randomized order cannot use a counterbalance key")
        key = None
        expected_sequences = {
            str(assignment["pair_id"]): (
                ["TREATMENT", "BASELINE"]
                if hashlib.sha256(
                    f"{randomization_seed_material}\0{assignment['pair_id']}".encode(
                        "utf-8"
                    )
                ).digest()[0]
                & 1
                else ["BASELINE", "TREATMENT"]
            )
            for assignment in normalized
        }
    else:
        if randomization_seed_digest is not None:
            raise ScoreInputError("counterbalanced order cannot use a random seed")
        if randomization_seed_material is not None:
            raise ScoreInputError(
                "counterbalanced order cannot use random seed material"
            )
        if not isinstance(counterbalance_key, str) or not counterbalance_key:
            raise ScoreInputError("counterbalanced order requires a key")
        seed = None
        key = counterbalance_key
        pair_ids = [str(assignment["pair_id"]) for assignment in normalized]
        starts_with_treatment = (
            int(
                canonical_sha256(
                    {
                        "counterbalance_key": counterbalance_key,
                        "pair_ids": pair_ids,
                    }
                )[0],
                16,
            )
            % 2
            == 1
        )
        expected_sequences = {
            pair_id: (
                ["TREATMENT", "BASELINE"]
                if starts_with_treatment == (index % 2 == 0)
                else ["BASELINE", "TREATMENT"]
            )
            for index, pair_id in enumerate(pair_ids)
        }
    if any(
        assignment["sequence"] != expected_sequences[str(assignment["pair_id"])]
        for assignment in normalized
    ):
        raise ScoreInputError(
            f"{str(method).lower()} order differs from generation proof"
        )
    return {
        "schema_version": "1.0",
        "status": "FROZEN",
        "method": method,
        "randomization_seed_digest": seed,
        "counterbalance_key": key,
        "assignments": normalized,
    }


def validate_order_manifest(
    manifest: Mapping[str, object],
    *,
    expected_manifest_sha256: str,
    randomization_seed_material: str | None = None,
) -> tuple[dict[str, object], ...]:
    value = _mapping(manifest, "order manifest")
    _exact_keys(
        value,
        {
            "schema_version",
            "status",
            "method",
            "randomization_seed_digest",
            "counterbalance_key",
            "assignments",
            "manifest_digest",
        },
        "order manifest",
    )
    if value["schema_version"] != "1.0" or value["status"] != "FROZEN":
        raise ScoreInputError("order manifest is not frozen")
    expected_anchor = _sha256_digest(
        expected_manifest_sha256,
        "expected order manifest SHA-256",
    )
    if canonical_sha256(value) != expected_anchor:
        raise ScoreInputError("order manifest differs from external freeze anchor")
    body = _order_body(
        value["method"],
        value["assignments"],
        randomization_seed_digest=value["randomization_seed_digest"],
        counterbalance_key=value["counterbalance_key"],
        randomization_seed_material=randomization_seed_material,
    )
    if value["manifest_digest"] != canonical_sha256(body):
        raise ScoreInputError("order manifest digest mismatch")
    return tuple(body["assignments"])  # type: ignore[arg-type]


def _instant(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ScoreInputError(f"{label} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScoreInputError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ScoreInputError(f"{label} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def operator_seconds(observation: Mapping[str, object]) -> float:
    value = _mapping(observation, "observation")
    start = _instant(value.get("question_received_at"), "question_received_at")
    end = _instant(value.get("final_submission_at"), "final_submission_at")
    if end <= start:
        raise ScoreInputError("timing boundary is invalid")
    intervals: list[tuple[datetime, datetime]] = []
    for raw in _sequence(value.get("system_load_intervals"), "system load intervals"):
        interval = _mapping(raw, "system load interval")
        _exact_keys(interval, {"started_at", "ended_at"}, "system load interval")
        interval_start = _instant(interval["started_at"], "system load started_at")
        interval_end = _instant(interval["ended_at"], "system load ended_at")
        if (
            interval_start < start
            or interval_end > end
            or interval_end <= interval_start
        ):
            raise ScoreInputError("system load timing boundary is invalid")
        intervals.append((interval_start, interval_end))
    intervals.sort()
    for previous, current in zip(intervals, intervals[1:], strict=False):
        if current[0] < previous[1]:
            raise ScoreInputError("system load intervals overlap")
    excluded = sum(
        (interval_end - interval_start).total_seconds()
        for interval_start, interval_end in intervals
    )
    return (end - start).total_seconds() - excluded


def _normalize_rows(value: object) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in _sequence(value, "submission rows"):
        row = _mapping(raw, "submission row")
        _exact_keys(
            row,
            {"item_id", "state", "attention_reasons"},
            "submission row",
        )
        item_id = row["item_id"]
        state = row["state"]
        if not isinstance(item_id, str) or not item_id or item_id in seen:
            raise ScoreInputError("submission row item ids must be unique")
        if state not in _ROW_STATES:
            raise ScoreInputError("submission row state is invalid")
        raw_reasons = _sequence(row["attention_reasons"], "attention reasons")
        if any(not isinstance(reason, str) or not reason for reason in raw_reasons):
            raise ScoreInputError("attention reasons must be non-empty strings")
        reasons = sorted(set(raw_reasons))
        if len(reasons) != len(raw_reasons):
            raise ScoreInputError("attention reasons must be unique")
        if (state in _ATTENTION_STATES) != bool(reasons):
            raise ScoreInputError("attention state and reasons are inconsistent")
        seen.add(item_id)
        rows.append(
            {
                "item_id": item_id,
                "state": state,
                "attention_reasons": reasons,
            }
        )
    return sorted(rows, key=lambda item: str(item["item_id"]))


def operator_attention_set(rows: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    normalized = _normalize_rows(rows)
    return tuple(
        str(row["item_id"]) for row in normalized if row["state"] in _ATTENTION_STATES
    )


def _gold_items(
    manifest: Mapping[str, object],
    *,
    expected_manifest_sha256: str,
) -> list[dict[str, object]]:
    value = _mapping(manifest, "gold manifest")
    _exact_keys(
        value,
        {"schema_version", "status", "items", "manifest_digest"},
        "gold manifest",
    )
    if value["schema_version"] != "1.0" or value["status"] != "FROZEN":
        raise ScoreInputError("gold manifest is not frozen")
    expected_anchor = _sha256_digest(
        expected_manifest_sha256,
        "expected gold manifest SHA-256",
    )
    if canonical_sha256(value) != expected_anchor:
        raise ScoreInputError("gold manifest differs from external freeze anchor")
    body = {
        "schema_version": value["schema_version"],
        "status": value["status"],
        "items": value["items"],
    }
    if value["manifest_digest"] != canonical_sha256(body):
        raise ScoreInputError("gold manifest digest mismatch")
    items: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in _sequence(value["items"], "gold items"):
        item = _mapping(raw, "gold item")
        _exact_keys(
            item,
            {
                "item_id",
                "mandatory",
                "gold_reason",
                "reason_class",
                "done_verified_allowed",
            },
            "gold item",
        )
        item_id = item["item_id"]
        mandatory = item["mandatory"]
        reason = item["gold_reason"]
        reason_class = item["reason_class"]
        if not isinstance(item_id, str) or not item_id or item_id in seen:
            raise ScoreInputError("gold item ids must be unique")
        if not isinstance(mandatory, bool) or not isinstance(
            item["done_verified_allowed"], bool
        ):
            raise ScoreInputError("gold item flags must be boolean")
        if reason_class not in _REASON_CLASSES:
            raise ScoreInputError("gold reason class is invalid")
        if mandatory:
            if not isinstance(reason, str) or not reason or reason_class == "NONE":
                raise ScoreInputError("mandatory gold item requires an exact reason")
            expected_reason_class = (
                "SOURCE_GAP"
                if reason in _SOURCE_GAP_REASONS
                else "NON_SOURCE_GAP"
                if reason in _NON_SOURCE_GAP_REASONS
                else None
            )
            if (
                reason not in _CANONICAL_REASONS
                or reason_class != expected_reason_class
            ):
                raise ScoreInputError(
                    "gold reason differs from canonical reason taxonomy"
                )
        elif reason is not None or reason_class != "NONE":
            raise ScoreInputError("non-mandatory gold item cannot carry a reason")
        seen.add(item_id)
        items.append(dict(item))
    return sorted(items, key=lambda item: str(item["item_id"]))


def score_arm(
    observation: Mapping[str, object],
    gold_manifest: Mapping[str, object],
    *,
    expected_gold_manifest_sha256: str,
) -> dict[str, object]:
    value = _mapping(observation, "observation")
    _exact_keys(
        value,
        {
            "abandoned",
            "question_received_at",
            "final_submission_at",
            "system_load_intervals",
            "rows",
        },
        "observation",
    )
    if value["abandoned"] is not False:
        raise ScoreInputError("abandoned observation cannot be scored")
    gold = _gold_items(
        gold_manifest,
        expected_manifest_sha256=expected_gold_manifest_sha256,
    )
    rows = _normalize_rows(value["rows"])
    row_by_id = {str(row["item_id"]): row for row in rows}
    gold_by_id = {str(item["item_id"]): item for item in gold}
    if set(row_by_id) - set(gold_by_id):
        raise ScoreInputError("submission contains an item outside frozen gold")
    attention = operator_attention_set(rows)
    recalled: list[str] = []
    for item in gold:
        if not item["mandatory"]:
            continue
        item_id = str(item["item_id"])
        row = row_by_id.get(item_id)
        if row is None or list(
            _sequence(row["attention_reasons"], "attention reasons")
        ) != [item["gold_reason"]]:
            continue
        if row["state"] == "NEEDS_ATTENTION" or (
            row["state"] == "UNKNOWN" and item["reason_class"] == "SOURCE_GAP"
        ):
            recalled.append(item_id)
    mandatory_count = sum(bool(item["mandatory"]) for item in gold)
    non_gold = {str(item["item_id"]) for item in gold if not bool(item["mandatory"])}
    false_attention = sorted(non_gold.intersection(attention))
    false_done = sorted(
        item_id
        for item_id, row in row_by_id.items()
        if row["state"] == "DONE_VERIFIED"
        and not bool(gold_by_id[item_id]["done_verified_allowed"])
    )
    denominator = len(non_gold)
    return {
        "operator_seconds": operator_seconds(value),
        "operator_attention_set": list(attention),
        "mandatory_recalled_item_ids": sorted(recalled),
        "mandatory_recall_count": len(recalled),
        "mandatory_event_count": mandatory_count,
        "mandatory_recall": (
            len(recalled) / mandatory_count if mandatory_count else None
        ),
        "false_attention_item_ids": false_attention,
        "false_attention_count": len(false_attention),
        "false_attention_denominator": denominator,
        "false_attention_rate": (
            len(false_attention) / denominator if denominator else None
        ),
        "false_done_verified_item_ids": false_done,
        "false_done_verified_count": len(false_done),
    }


def score_pair(
    pair: Mapping[str, object],
    gold_manifest: Mapping[str, object],
    order_manifest: Mapping[str, object],
    *,
    expected_gold_manifest_sha256: str,
    expected_order_manifest_sha256: str,
    randomization_seed_material: str | None = None,
) -> dict[str, object]:
    value = _mapping(pair, "pair")
    _exact_keys(value, {"pair_id", "sequence", "arms"}, "pair")
    pair_id = value["pair_id"]
    if not isinstance(pair_id, str) or not pair_id:
        raise ScoreInputError("pair id must be non-empty")
    _gold_items(
        gold_manifest,
        expected_manifest_sha256=expected_gold_manifest_sha256,
    )
    assignments = validate_order_manifest(
        order_manifest,
        expected_manifest_sha256=expected_order_manifest_sha256,
        randomization_seed_material=randomization_seed_material,
    )
    assignment = next(
        (item for item in assignments if item["pair_id"] == pair_id),
        None,
    )
    if assignment is None:
        raise ScoreInputError("pair is absent from frozen order manifest")
    sequence = list(_sequence(value["sequence"], "pair sequence"))
    if sequence != assignment["sequence"]:
        raise ScoreInputError("pair sequence differs from frozen assignment")
    arms = _mapping(value["arms"], "pair arms")
    missing = {"BASELINE", "TREATMENT"} - set(arms)
    if missing:
        return {
            "pair_id": pair_id,
            "valid": False,
            "invalid_reasons": ["MISSING_PAIRED_OBSERVATION"],
            "metrics": None,
        }
    if set(arms) != {"BASELINE", "TREATMENT"}:
        raise ScoreInputError("pair arms contain an unsupported arm")
    if any(
        _mapping(arms[name], f"{name} observation").get("abandoned") is not False
        for name in ("BASELINE", "TREATMENT")
    ):
        return {
            "pair_id": pair_id,
            "valid": False,
            "invalid_reasons": ["ABANDONED_PAIRED_OBSERVATION"],
            "metrics": None,
        }
    baseline = score_arm(
        arms["BASELINE"],
        gold_manifest,
        expected_gold_manifest_sha256=expected_gold_manifest_sha256,
    )
    treatment = score_arm(
        arms["TREATMENT"],
        gold_manifest,
        expected_gold_manifest_sha256=expected_gold_manifest_sha256,
    )
    baseline_seconds = cast(float, baseline["operator_seconds"])
    treatment_seconds = cast(float, treatment["operator_seconds"])
    return {
        "pair_id": pair_id,
        "valid": True,
        "invalid_reasons": [],
        "metrics": {
            "BASELINE": baseline,
            "TREATMENT": treatment,
            "operator_seconds_reduction_fraction": (
                (baseline_seconds - treatment_seconds) / baseline_seconds
                if baseline_seconds > 0
                else None
            ),
        },
    }
