"""C7 clearance-receipt fault-injection tests (P1-6, option A).

These exercise the digest-bound C7 manifest: issue/verify, epoch replay, halt,
authority unavailability, scope mismatch, write-tamper and an explicit
worker-compromise boundary test.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_os_contracts import C7ClearanceReceipt
from agent_os_core.c7_receipt import (
    C7AuthorityHalted,
    C7AuthorityUnavailable,
    C7EpochReplay,
    C7ReceiptIssuer,
    C7ReceiptScopeMismatch,
    C7ReceiptVerifier,
)
from agent_os_core.governance import CorrectionAuthority


def _issuer(authority: CorrectionAuthority) -> C7ReceiptIssuer:
    return C7ReceiptIssuer(
        authority,
        tenant_id="tenant:1",
        workspace_id="ws:1",
        issuer_id="c7:issuer",
        clock=lambda: datetime(2026, 9, 14, tzinfo=timezone.utc),
    )


def test_valid_receipt_verifies() -> None:
    authority = CorrectionAuthority()
    receipt = _issuer(authority).issue("task-1", "run-1", "cap.read")
    assert receipt.halted is False
    assert receipt.correction_epochs.task_epoch == 0
    C7ReceiptVerifier(authority).verify(
        receipt, expected_task_id="task-1", expected_run_id="run-1"
    )


def test_epoch_replay_does_not_reauthorize() -> None:
    authority = CorrectionAuthority()
    receipt = _issuer(authority).issue("task-1", "run-1", "cap.read")
    # Operator corrects then resumes the scope: the epoch advances but the scope
    # is not halted, so a stale receipt must be rejected specifically as replay.
    authority.correct("task", "task-1", "operator correction")
    authority.resume("task", "task-1")
    with pytest.raises(C7EpochReplay):
        C7ReceiptVerifier(authority).verify(receipt)


def test_halted_scope_fails_closed() -> None:
    authority = CorrectionAuthority()
    authority.correct("run", "run-1", "halt this run")
    with pytest.raises(C7AuthorityHalted):
        _issuer(authority).issue("task-1", "run-1", "cap.read")


def test_receipt_recording_pre_halt_rejects_post_halt_commit() -> None:
    authority = CorrectionAuthority()
    receipt = _issuer(authority).issue("task-1", "run-1", "cap.read")
    authority.correct("capability", "cap.read", "halt capability")
    with pytest.raises(C7AuthorityHalted):
        C7ReceiptVerifier(authority).verify(receipt)


def test_authority_unavailable_fails_closed() -> None:
    class _BrokenAuthority:
        def snapshot(self, task_id: str, run_id: str, capability_id: str):
            raise RuntimeError("c7 backend unreachable")

        def halted(self, task_id: str, run_id: str, capability_id: str) -> bool:
            return False

    receipt = _issuer(CorrectionAuthority()).issue("task-1", "run-1", "cap.read")
    with pytest.raises(C7AuthorityUnavailable):
        C7ReceiptVerifier(_BrokenAuthority()).verify(receipt)


def test_scope_mismatch_fails_closed() -> None:
    authority = CorrectionAuthority()
    receipt = _issuer(authority).issue("task-1", "run-1", "cap.read")
    with pytest.raises(C7ReceiptScopeMismatch):
        C7ReceiptVerifier(authority).verify(receipt, expected_task_id="task-2")


def test_write_tamper_is_rejected_on_load() -> None:
    authority = CorrectionAuthority()
    receipt = _issuer(authority).issue("task-1", "run-1", "cap.read")
    tampered = receipt.model_dump(mode="json")
    tampered["halted"] = not tampered["halted"]
    with pytest.raises(ValidationError):
        C7ClearanceReceipt.model_validate(tampered)


def test_digest_tamper_is_rejected() -> None:
    authority = CorrectionAuthority()
    receipt = _issuer(authority).issue("task-1", "run-1", "cap.read")
    forged = receipt.model_dump(mode="json")
    forged["receipt_digest"] = "0" * 64
    with pytest.raises(ValidationError):
        C7ClearanceReceipt.model_validate(forged)


def test_worker_compromise_is_not_isolated_by_this_slice() -> None:
    # HONEST BOUNDARY: the receipt is a pre-commit linearization token, not a
    # fault domain. A compromised caller that simply never calls verify() is not
    # stopped here; that requires an external signed attestation (C-lite),
    # which is explicitly out of scope for option A.
    authority = CorrectionAuthority()
    _issuer(authority).issue("task-1", "run-1", "cap.read")
    # No verifier call: nothing in this module prevents a caller from skipping it.
    assert C7ReceiptVerifier(authority) is not None
