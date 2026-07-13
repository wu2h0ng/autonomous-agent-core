"""Product-side machine brake for E2E4 before generic prereg freeze."""

from __future__ import annotations

from pathlib import Path

import pytest

from product_evals.common.authority_binding import AuthorityBinding
from product_evals.spine_e2e_4 import prefreeze


def _authority() -> AuthorityBinding:
    return AuthorityBinding(
        request_sha256="1" * 64,
        approval_sha256="2" * 64,
        request_id="permission-e2e4",
        requester="codex-cto",
        action="team.event.record",
        affected_path=".agent_runs/spine-e2e-4-20260713/agent_events.jsonl",
        decision="approved_session",
        decided_by="founder",
        source_decision_id="decision-e2e4",
        source_goal_id="SPINE-E2E-4",
        source_decision_type="founder_authorization",
        evidence_refs=("evaluation/anchor_requests/prepare.json",),
        request_ts=prefreeze.datetime.fromisoformat("2026-07-13T00:00:00+00:00"),
        approval_ts=prefreeze.datetime.fromisoformat("2026-07-13T00:00:01+00:00"),
    )


def _permission(authority: AuthorityBinding) -> dict[str, object]:
    return {
        "action": authority.action,
        "request_id": authority.request_id,
        "requester": authority.requester,
        "affected_path": authority.affected_path,
        "evidence_refs": list(authority.evidence_refs),
        "request_row_sha256": authority.request_sha256,
        "approval_row_sha256": authority.approval_sha256,
        "request_timestamp": authority.request_ts.isoformat(),
        "approval_timestamp": authority.approval_ts.isoformat(),
        "decision": authority.decision,
        "decided_by": authority.decided_by,
        "source_decision_id": authority.source_decision_id,
        "source_goal_id": authority.source_goal_id,
        "source_decision_type": authority.source_decision_type,
    }


def test_prefreeze_rejects_unbound_permission_sentinel() -> None:
    authority = _authority()
    permission = _permission(authority)
    permission["request_id"] = prefreeze.PERMISSION_SENTINEL

    with pytest.raises(ValueError, match="PREFREEZE_PERMISSION_UNBOUND"):
        prefreeze.validate_prefreeze_permission(permission, authority)


def test_prefreeze_accepts_only_exact_materialized_permission() -> None:
    authority = _authority()

    prefreeze.validate_prefreeze_permission(_permission(authority), authority)


def test_prefreeze_cli_validates_yaml_and_current_ledgers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authority = _authority()
    spec = tmp_path / "spec.yaml"
    spec.write_text("permission_binding: {}\n", encoding="utf-8")
    observed: list[tuple[Path, Path]] = []
    monkeypatch.setattr(
        prefreeze,
        "_load_yaml",
        lambda path: {"permission_binding": _permission(authority)},
    )
    monkeypatch.setattr(
        prefreeze,
        "verify_authority_binding",
        lambda run_root, **kwargs: (
            observed.append((run_root, spec)),
            authority,
        )[1],
    )

    assert prefreeze.main(["--spec", str(spec), "--run-root", str(tmp_path)]) == 0
    assert observed == [(tmp_path, spec)]


def test_prefreeze_cli_rejects_sentinel_before_reading_permission_ledgers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text("permission_binding: {}\n", encoding="utf-8")
    monkeypatch.setattr(
        prefreeze,
        "_load_yaml",
        lambda path: {
            "permission_binding": {"request_id": prefreeze.PERMISSION_SENTINEL}
        },
    )
    monkeypatch.setattr(
        prefreeze,
        "verify_authority_binding",
        lambda *args, **kwargs: pytest.fail("sentinel must stop before ledger read"),
    )

    with pytest.raises(ValueError, match="PREFREEZE_PERMISSION_UNBOUND"):
        prefreeze.main(["--spec", str(spec), "--run-root", str(tmp_path)])
