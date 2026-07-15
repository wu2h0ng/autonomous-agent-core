"""External C7 stop-capability tests for R-STATE-CREDIT-1."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from experiments.r_state_credit_1.contracts import canonical_json
from experiments.r_state_credit_1.external_c7 import (
    AtomicStopFileC7,
    C7SignalViolation,
)


OWNER_ID = "tests-only-c7-owner"
EPOCH = "tests-only-c7-epoch-1"
TOKEN = "tests-only-stop-capability"


def _token_digest() -> str:
    return hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()


def _write_signal(
    path: Path,
    *,
    owner_id: str = OWNER_ID,
    epoch: str = EPOCH,
    token_digest: str | None = None,
    reason_code: str = "FOUNDER_STOP",
) -> None:
    payload = {
        "abort_requested": True,
        "capability_token_sha256": token_digest or _token_digest(),
        "epoch": epoch,
        "owner_id": owner_id,
        "reason_code": reason_code,
        "schema_version": "r-state-credit-1-c7-stop-v1",
    }
    encoded = (canonical_json(payload) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _adapter(path: Path) -> AtomicStopFileC7:
    return AtomicStopFileC7(
        owner_id=OWNER_ID,
        epoch=EPOCH,
        stop_path=path,
        capability_token=TOKEN,
    )


def test_absent_stop_file_is_not_an_abort_and_capability_is_digest_only(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path / "stop.json")

    assert adapter.abort_requested() is False
    assert adapter.capability_token_sha256 == _token_digest()
    assert TOKEN not in repr(adapter)


def test_exact_atomic_stop_file_requests_abort(tmp_path: Path) -> None:
    path = tmp_path / "stop.json"
    _write_signal(path)

    assert _adapter(path).abort_requested() is True


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"owner_id": "wrong-owner"}, "owner identity drift"),
        ({"epoch": "wrong-epoch"}, "epoch drift"),
        ({"token_digest": "a" * 64}, "capability token drift"),
    ],
)
def test_identity_epoch_or_capability_drift_fails_closed(
    tmp_path: Path, override: dict[str, str], message: str
) -> None:
    path = tmp_path / "stop.json"
    _write_signal(path, **override)

    with pytest.raises(C7SignalViolation, match=message):
        _adapter(path).abort_requested()


def test_stop_file_rejects_symlink_and_schema_drift(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    _write_signal(real)
    linked = tmp_path / "linked.json"
    linked.symlink_to(real.name)
    with pytest.raises(C7SignalViolation, match="symlink"):
        _adapter(linked).abort_requested()

    unknown = tmp_path / "unknown.json"
    payload = json.loads(real.read_text(encoding="utf-8"))
    payload["unreviewed_override"] = True
    unknown.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    with pytest.raises(C7SignalViolation, match="schema drift"):
        _adapter(unknown).abort_requested()
