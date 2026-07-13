"""Fail-closed typed authority bindings for SPINE formal anchors.

Permission verification consumes the full request/approval JSONL ledgers and
returns an immutable :class:`AuthorityBinding`.  No founder-decision or goal
literal is embedded here; canonical row hashes are derived from the current
rows through the single :func:`canonical_sha256` source, and every scope,
identity, source, evidence, and timing property is checked before a binding is
returned.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from product_evals.common.artifacts import canonical_sha256

_REQUEST_LEDGER = "approval_requests.jsonl"
_APPROVAL_LEDGER = "approvals.jsonl"
_APPROVED_DECISION = "approved_session"
_SOURCE_FIELDS = ("source_decision_id", "source_goal_id", "source_decision_type")


class _AuthorityError(ValueError):
    """Internal marker; every failure surfaces as ``INVALID_AUTHORITY_BINDING``."""


def _reject_non_finite(token: str) -> Any:
    raise _AuthorityError("non-finite JSON constant")


@dataclass(frozen=True)
class AuthorityBinding:
    request_sha256: str
    approval_sha256: str
    request_id: str
    requester: str
    action: str
    affected_path: str
    decision: str
    decided_by: str
    source_decision_id: str
    source_goal_id: str
    source_decision_type: str
    evidence_refs: tuple[str, ...]
    request_ts: datetime
    approval_ts: datetime


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in pairs:
        if key in row:
            raise _AuthorityError("duplicate JSON key")
        row[key] = value
    return row


def _read_rows(path: Path) -> list[dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise _AuthorityError("unreadable ledger") from exc
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            raise _AuthorityError("blank ledger line")
        try:
            row = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_non_finite,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _AuthorityError("malformed ledger JSON") from exc
        if not isinstance(row, dict):
            raise _AuthorityError("non-object ledger row")
        rows.append(row)
    return rows


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _require_nonblank(value: object) -> str:
    if not _nonblank(value):
        raise _AuthorityError("blank field")
    return value  # type: ignore[return-value]


def _aware_instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise _AuthorityError("non-string timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _AuthorityError("invalid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _AuthorityError("naive timestamp")
    return parsed


def _evidence_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise _AuthorityError("invalid evidence_refs")
    for item in value:
        if not _nonblank(item):
            raise _AuthorityError("blank evidence ref")
    if len(set(value)) != len(value):
        raise _AuthorityError("duplicate evidence ref")
    return tuple(value)


def _bound_source(request: dict[str, Any], approval: dict[str, Any]) -> dict[str, str]:
    bound: dict[str, str] = {}
    for field in _SOURCE_FIELDS:
        request_value = _require_nonblank(request.get(field))
        approval_value = _require_nonblank(approval.get(field))
        if request_value != approval_value:
            raise _AuthorityError("source binding mismatch")
        bound[field] = request_value
    return bound


def verify_authority_binding(
    run_root: Path,
    *,
    run_id: str,
    action: str,
    affected_path: str,
) -> AuthorityBinding:
    """Verify the run-local permission ledgers and return a typed binding.

    Exactly one request and one approval must exist across the entire ledgers;
    every scope, identity, source, evidence, and monotonic-timing property is
    enforced fail-closed before an immutable binding is returned.
    """

    try:
        run_id = _require_nonblank(run_id)
        action = _require_nonblank(action)
        affected_path = _require_nonblank(affected_path)
        requests = _read_rows(run_root / _REQUEST_LEDGER)
        approvals = _read_rows(run_root / _APPROVAL_LEDGER)
        if len(requests) != 1 or len(approvals) != 1:
            raise _AuthorityError("ledger cardinality")
        request, approval = requests[0], approvals[0]

        request_id = _require_nonblank(request.get("request_id"))
        if approval.get("request_id") != request_id:
            raise _AuthorityError("orphan approval")

        if request.get("run_id") != run_id or approval.get("run_id") != run_id:
            raise _AuthorityError("run scope mismatch")
        if request.get("action") != action:
            raise _AuthorityError("action mismatch")
        if request.get("affected_paths") != [affected_path]:
            raise _AuthorityError("affected path mismatch")

        agent_id = _require_nonblank(request.get("agent_id"))
        if approval.get("decision") != _APPROVED_DECISION:
            raise _AuthorityError("unapproved decision")
        decided_by = _require_nonblank(approval.get("decided_by"))
        if decided_by == agent_id:
            raise _AuthorityError("self approval")

        source = _bound_source(request, approval)
        evidence_refs = _evidence_tuple(request.get("evidence_refs"))

        request_ts = _aware_instant(request.get("ts"))
        approval_ts = _aware_instant(approval.get("ts"))
        if approval_ts <= request_ts:
            raise _AuthorityError("non-monotonic timestamps")

        return AuthorityBinding(
            request_sha256=canonical_sha256(request),
            approval_sha256=canonical_sha256(approval),
            request_id=request_id,
            requester=agent_id,
            action=action,
            affected_path=affected_path,
            decision=approval["decision"],
            decided_by=decided_by,
            source_decision_id=source["source_decision_id"],
            source_goal_id=source["source_goal_id"],
            source_decision_type=source["source_decision_type"],
            evidence_refs=evidence_refs,
            request_ts=request_ts,
            approval_ts=approval_ts,
        )
    except _AuthorityError as exc:
        raise ValueError("INVALID_AUTHORITY_BINDING") from exc
