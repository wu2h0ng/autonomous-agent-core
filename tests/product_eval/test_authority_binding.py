"""Fail-closed contracts for typed SPINE authority bindings."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from product_evals.common.artifacts import canonical_sha256
from product_evals.common.authority_binding import (
    AuthorityBinding,
    verify_authority_binding,
)


RUN_ID = "spine-e2e-4-authority-test"
ACTION = "team.event.record"
AFFECTED_PATH = "messages.jsonl"


def _permission_rows() -> tuple[dict[str, Any], dict[str, Any]]:
    request = {
        "action": ACTION,
        "affected_paths": [AFFECTED_PATH],
        "agent_id": "codex-cto",
        "evidence_refs": [
            "docs/research/SPINE-E2E-4-preregistration-spec.yaml",
            "product_evals/spine_e2e_4/runner_team_event_schema.json",
        ],
        "hard_gated": False,
        "note": "isolated authority binding test",
        "request_id": "perm_spine_e2e_4_authority_test",
        "risk_level": "medium",
        "run_id": RUN_ID,
        "source_decision_id": "founder-decision-spine-e2e-4",
        "source_decision_type": "founder_authorization",
        "source_goal_id": "SPINE-E2E-4",
        "status": "pending",
        "ts": "2026-07-13T10:00:00+00:00",
    }
    approval = {
        "decided_by": "founder",
        "decision": "approved_session",
        "note": "isolated authority approval",
        "request_id": request["request_id"],
        "run_id": RUN_ID,
        "source_decision_id": request["source_decision_id"],
        "source_decision_type": request["source_decision_type"],
        "source_goal_id": request["source_goal_id"],
        "ts": "2026-07-13T10:00:01+00:00",
    }
    return request, approval


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _write_ledgers(
    run_root: Path,
    *,
    requests: list[dict[str, Any]] | None = None,
    approvals: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request, approval = _permission_rows()
    _write_jsonl(
        run_root / "approval_requests.jsonl",
        [request] if requests is None else requests,
    )
    _write_jsonl(
        run_root / "approvals.jsonl",
        [approval] if approvals is None else approvals,
    )
    return request, approval


def _verify(run_root: Path) -> AuthorityBinding:
    return verify_authority_binding(
        run_root,
        run_id=RUN_ID,
        action=ACTION,
        affected_path=AFFECTED_PATH,
    )


def test_returns_frozen_typed_binding_with_derived_hashes_and_source_evidence(
    tmp_path: Path,
) -> None:
    request, approval = _write_ledgers(tmp_path)

    binding = _verify(tmp_path)

    assert isinstance(binding, AuthorityBinding)
    assert is_dataclass(binding)
    assert not isinstance(binding, dict)
    assert binding.request_sha256 == canonical_sha256(request)
    assert binding.approval_sha256 == canonical_sha256(approval)
    assert binding.request_id == request["request_id"]
    assert binding.action == ACTION
    assert binding.affected_path == AFFECTED_PATH
    assert binding.decision == "approved_session"
    assert binding.decided_by == "founder"
    assert binding.source_decision_id == request["source_decision_id"]
    assert binding.source_goal_id == request["source_goal_id"]
    assert binding.source_decision_type == request["source_decision_type"]
    assert binding.evidence_refs == tuple(request["evidence_refs"])
    assert binding.request_ts == datetime.fromisoformat(request["ts"])
    assert binding.approval_ts == datetime.fromisoformat(approval["ts"])
    with pytest.raises(FrozenInstanceError):
        binding.request_id = "tampered"  # type: ignore[misc]


def test_hashes_are_derived_from_current_rows_not_stale_constants(
    tmp_path: Path,
) -> None:
    request, approval = _permission_rows()
    request["note"] = "freshly changed note"
    approval["note"] = "freshly changed approval note"
    _write_ledgers(tmp_path, requests=[request], approvals=[approval])

    binding = _verify(tmp_path)

    assert binding.request_sha256 == canonical_sha256(request)
    assert binding.approval_sha256 == canonical_sha256(approval)


@pytest.mark.parametrize("ledger", ["requests", "approvals"])
def test_rejects_missing_or_empty_ledger(tmp_path: Path, ledger: str) -> None:
    request, approval = _permission_rows()
    requests = [] if ledger == "requests" else [request]
    approvals = [] if ledger == "approvals" else [approval]
    _write_ledgers(tmp_path, requests=requests, approvals=approvals)

    with pytest.raises(ValueError, match="INVALID_AUTHORITY_BINDING"):
        _verify(tmp_path)


@pytest.mark.parametrize("ledger", ["requests", "approvals"])
def test_full_ledger_scan_rejects_duplicate_or_unrelated_rows(
    tmp_path: Path, ledger: str
) -> None:
    request, approval = _permission_rows()
    if ledger == "requests":
        extra = {
            **request,
            "request_id": "perm_unrelated",
            "run_id": "another-run",
            "ts": "2026-07-13T09:59:59+00:00",
        }
        requests, approvals = [extra, request], [approval]
    else:
        extra = {
            **approval,
            "request_id": "perm_orphan",
            "run_id": "another-run",
            "ts": "2026-07-13T10:00:02+00:00",
        }
        requests, approvals = [request], [approval, extra]
    _write_ledgers(tmp_path, requests=requests, approvals=approvals)

    with pytest.raises(ValueError, match="INVALID_AUTHORITY_BINDING"):
        _verify(tmp_path)


@pytest.mark.parametrize("ledger", ["requests", "approvals"])
def test_full_ledger_scan_rejects_duplicate_bound_row(
    tmp_path: Path, ledger: str
) -> None:
    request, approval = _permission_rows()
    requests = [request, dict(request)] if ledger == "requests" else [request]
    approvals = [approval, dict(approval)] if ledger == "approvals" else [approval]
    _write_ledgers(tmp_path, requests=requests, approvals=approvals)

    with pytest.raises(ValueError, match="INVALID_AUTHORITY_BINDING"):
        _verify(tmp_path)


def test_rejects_orphan_approval_request_id(tmp_path: Path) -> None:
    request, approval = _permission_rows()
    approval["request_id"] = "perm_orphan"
    _write_ledgers(tmp_path, requests=[request], approvals=[approval])

    with pytest.raises(ValueError, match="INVALID_AUTHORITY_BINDING"):
        _verify(tmp_path)


@pytest.mark.parametrize(
    ("row_name", "field", "value"),
    [
        ("request", "run_id", "wrong-run"),
        ("approval", "run_id", "wrong-run"),
        ("request", "action", "wrong.action"),
        ("request", "affected_paths", ["wrong/path"]),
        ("request", "affected_paths", [AFFECTED_PATH, "extra/path"]),
        ("request", "request_id", ""),
        ("request", "agent_id", ""),
        ("approval", "decision", "denied"),
        ("approval", "decided_by", ""),
    ],
)
def test_rejects_wrong_scope_identity_or_decision(
    tmp_path: Path, row_name: str, field: str, value: object
) -> None:
    request, approval = _permission_rows()
    row = request if row_name == "request" else approval
    row[field] = value
    _write_ledgers(tmp_path, requests=[request], approvals=[approval])

    with pytest.raises(ValueError, match="INVALID_AUTHORITY_BINDING"):
        _verify(tmp_path)


def test_rejects_self_approval(tmp_path: Path) -> None:
    request, approval = _permission_rows()
    approval["decided_by"] = request["agent_id"]
    _write_ledgers(tmp_path, requests=[request], approvals=[approval])

    with pytest.raises(ValueError, match="INVALID_AUTHORITY_BINDING"):
        _verify(tmp_path)


@pytest.mark.parametrize(
    ("row_name", "field", "value"),
    [
        ("request", "source_decision_id", None),
        ("request", "source_goal_id", ""),
        ("request", "source_decision_type", "   "),
        ("approval", "source_decision_id", None),
        ("approval", "source_goal_id", ""),
        ("approval", "source_decision_type", "   "),
    ],
)
def test_rejects_missing_or_blank_source_binding(
    tmp_path: Path, row_name: str, field: str, value: object
) -> None:
    request, approval = _permission_rows()
    row = request if row_name == "request" else approval
    if value is None:
        row.pop(field)
    else:
        row[field] = value
    _write_ledgers(tmp_path, requests=[request], approvals=[approval])

    with pytest.raises(ValueError, match="INVALID_AUTHORITY_BINDING"):
        _verify(tmp_path)


@pytest.mark.parametrize(
    "field", ["source_decision_id", "source_goal_id", "source_decision_type"]
)
def test_rejects_source_tampering_between_request_and_approval(
    tmp_path: Path, field: str
) -> None:
    request, approval = _permission_rows()
    approval[field] = f"tampered-{field}"
    _write_ledgers(tmp_path, requests=[request], approvals=[approval])

    with pytest.raises(ValueError, match="INVALID_AUTHORITY_BINDING"):
        _verify(tmp_path)


@pytest.mark.parametrize(
    "evidence_refs",
    [
        [],
        [""],
        ["valid", "   "],
        ["valid", 1],
        ["duplicate", "duplicate"],
        "not-a-list",
    ],
)
def test_rejects_invalid_or_ambiguous_evidence_refs(
    tmp_path: Path, evidence_refs: object
) -> None:
    request, approval = _permission_rows()
    request["evidence_refs"] = evidence_refs
    _write_ledgers(tmp_path, requests=[request], approvals=[approval])

    with pytest.raises(ValueError, match="INVALID_AUTHORITY_BINDING"):
        _verify(tmp_path)


@pytest.mark.parametrize(
    ("request_ts", "approval_ts"),
    [
        ("2026-07-13T10:00:00", "2026-07-13T10:00:01+00:00"),
        ("2026-07-13T10:00:00+00:00", "2026-07-13T10:00:01"),
        ("not-a-timestamp", "2026-07-13T10:00:01+00:00"),
        ("2026-07-13T10:00:01+00:00", "2026-07-13T10:00:01+00:00"),
        ("2026-07-13T10:00:02+00:00", "2026-07-13T10:00:01+00:00"),
    ],
)
def test_rejects_naive_invalid_or_non_monotonic_timestamps(
    tmp_path: Path, request_ts: str, approval_ts: str
) -> None:
    request, approval = _permission_rows()
    request["ts"] = request_ts
    approval["ts"] = approval_ts
    _write_ledgers(tmp_path, requests=[request], approvals=[approval])

    with pytest.raises(ValueError, match="INVALID_AUTHORITY_BINDING"):
        _verify(tmp_path)


def test_timestamp_order_uses_instants_not_lexical_offsets(tmp_path: Path) -> None:
    request, approval = _permission_rows()
    request["ts"] = "2026-07-13T12:00:00+02:00"
    approval["ts"] = "2026-07-13T10:00:01+00:00"
    _write_ledgers(tmp_path, requests=[request], approvals=[approval])

    binding = _verify(tmp_path)

    assert binding.approval_ts > binding.request_ts


@pytest.mark.parametrize("ledger", ["approval_requests.jsonl", "approvals.jsonl"])
def test_full_ledger_scan_rejects_malformed_json(tmp_path: Path, ledger: str) -> None:
    _write_ledgers(tmp_path)
    with (tmp_path / ledger).open("a", encoding="utf-8") as stream:
        stream.write("{not-json}\n")

    with pytest.raises(ValueError, match="INVALID_AUTHORITY_BINDING"):
        _verify(tmp_path)


def test_full_ledger_scan_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    _write_ledgers(tmp_path)
    request_path = tmp_path / "approval_requests.jsonl"
    raw = request_path.read_text(encoding="utf-8").rstrip()
    duplicate_key_row = raw[:-1] + ',"request_id":"shadowed-request"}'
    request_path.write_text(duplicate_key_row + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="INVALID_AUTHORITY_BINDING"):
        _verify(tmp_path)
