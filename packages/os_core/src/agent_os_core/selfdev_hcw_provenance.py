"""Count-only HCW provenance for the atomic admit-selfdev slice.

This module owns the P/E (product/engineering) ledger artifact required by
``docs/IMPLEMENTATION-ROADMAP-NEXT-SLICES-2026-08-14.md`` decision A5: after a
complete admit-selfdev live chain, write a count-only HCW provenance record to
``.agent_runs/admit-selfdev-live-*/`` and support an independent read-only
verification that recomputes the counts from the real persisted events.

Scope and boundaries
--------------------

- The record is **count-only**. It never asserts HCW superiority, autonomy,
  self-improvement, or any ``Autonomy(S,E,O,V,T)`` claim. Its status is the
  honest ``HCW_INSUFFICIENT_DATA`` ceiling.
- Counts are **derived, never caller-supplied**. The recorder reads the
  canonical ``hcw_measurement_receipts`` rows (which ``measure_hcw`` produced
  from real operator work events and accepted-outcome settlements) and sums
  them. There is no parameter a caller can use to inject a count.
- The verifier is **read-only and independent**: it re-opens the same store,
  recomputes the sums, re-checks the record content digest, and fails closed on
  any mismatch (forged counts, reordered receipts, digest drift).

Field mapping (A5)
------------------

- ``intervention_count``  -> operator intervention count
- ``operator_minutes``    -> operator minutes (``None`` = not captured by the
                             current event schema; honest INSUFFICIENT_DATA)
- ``outcome_event_count`` -> accepted outcome event count
- ``help_event_count``    -> Help response event count
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_os_contracts import canonical_json, content_digest

from .responsibility_loop import (
    HcwMeasurementReceipt,
    HcwMeasurementStatus,
    ResponsibilityLoopBindingDrift,
    SQLiteResponsibilityLoopStore,
)

SCHEMA_VERSION = "1.0"
PROVENANCE_FILENAME = "hcw_provenance.json"
CLAIM_CEILING = (
    "COUNT_ONLY_HCW_PROVENANCE / REAL_EVENT_DERIVED / "
    "NO_HCW_SUPERIORITY / NO_AUTONOMY / NO_SELF_IMPROVEMENT"
)


class CountOnlyHcwProvenanceError(ValueError):
    """Fail-closed count-only HCW provenance error."""


_SLICE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _validate_slice_id(slice_id: str) -> str:
    value = str(slice_id)
    if (
        not value.strip()
        or value != value.strip()
        or value.startswith((".", "/"))
        or ".." in value
        or "/" in value
        or "\\" in value
        or _SLICE_ID_PATTERN.fullmatch(value) is None
    ):
        raise CountOnlyHcwProvenanceError(
            "slice_id must be a path-safe slug "
            "(letters, digits, '.', '_', '-'; no '..', '/', or leading '.')"
        )
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _derive_counts(
    receipts: tuple[HcwMeasurementReceipt, ...],
) -> dict[str, Any]:
    intervention_count = 0
    help_event_count = 0
    outcome_event_count = 0
    active_seconds = 0.0
    has_active_seconds = False
    source_receipt_digests: list[str] = []
    for receipt in receipts:
        intervention_count += receipt.operator_intervention_count
        help_event_count += receipt.help_response_count
        outcome_event_count += receipt.accepted_outcome_count
        if receipt.active_operator_seconds is not None:
            active_seconds += receipt.active_operator_seconds
            has_active_seconds = True
        source_receipt_digests.append(receipt.receipt_digest)
    return {
        "intervention_count": intervention_count,
        "help_event_count": help_event_count,
        "outcome_event_count": outcome_event_count,
        "operator_minutes": (active_seconds / 60.0) if has_active_seconds else None,
        "source_receipt_digests": tuple(source_receipt_digests),
    }


@dataclass(frozen=True)
class CountOnlyHcwProvenance:
    """Count-only HCW provenance record with a self-verifying content digest."""

    slice_id: str
    mandate_id: str
    binding_digest: str
    measurement_status: str
    intervention_count: int
    operator_minutes: float | None
    outcome_event_count: int
    help_event_count: int
    source_receipt_digests: tuple[str, ...]
    recorded_at: str
    claim_ceiling: str
    record_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "slice_id": self.slice_id,
            "mandate_id": self.mandate_id,
            "binding_digest": self.binding_digest,
            "measurement_status": self.measurement_status,
            "intervention_count": self.intervention_count,
            "operator_minutes": self.operator_minutes,
            "outcome_event_count": self.outcome_event_count,
            "help_event_count": self.help_event_count,
            "source_receipt_digests": list(self.source_receipt_digests),
            "recorded_at": self.recorded_at,
            "claim_ceiling": self.claim_ceiling,
            "record_digest": self.record_digest,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CountOnlyHcwProvenance":
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            raise CountOnlyHcwProvenanceError("provenance schema version drift")
        unsigned = dict(payload)
        record_digest = unsigned.pop("record_digest", None)
        if not isinstance(record_digest, str) or not record_digest.strip():
            raise CountOnlyHcwProvenanceError("provenance record digest missing")
        if content_digest(unsigned) != record_digest:
            raise CountOnlyHcwProvenanceError("provenance record digest mismatch")
        try:
            return cls(
                slice_id=str(payload["slice_id"]),
                mandate_id=str(payload["mandate_id"]),
                binding_digest=str(payload["binding_digest"]),
                measurement_status=str(payload["measurement_status"]),
                intervention_count=int(payload["intervention_count"]),
                operator_minutes=(
                    float(payload["operator_minutes"])
                    if payload.get("operator_minutes") is not None
                    else None
                ),
                outcome_event_count=int(payload["outcome_event_count"]),
                help_event_count=int(payload["help_event_count"]),
                source_receipt_digests=tuple(
                    str(digest) for digest in payload["source_receipt_digests"]
                ),
                recorded_at=str(payload["recorded_at"]),
                claim_ceiling=str(payload["claim_ceiling"]),
                record_digest=record_digest,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CountOnlyHcwProvenanceError(
                "provenance record payload is malformed"
            ) from exc

    def invariant_fields(self) -> dict[str, Any]:
        """Fields that must match a fresh derivation for independent verification."""
        return {
            "slice_id": self.slice_id,
            "mandate_id": self.mandate_id,
            "binding_digest": self.binding_digest,
            "measurement_status": self.measurement_status,
            "intervention_count": self.intervention_count,
            "operator_minutes": self.operator_minutes,
            "outcome_event_count": self.outcome_event_count,
            "help_event_count": self.help_event_count,
            "source_receipt_digests": self.source_receipt_digests,
            "claim_ceiling": self.claim_ceiling,
        }

    @classmethod
    def build(
        cls,
        *,
        store: SQLiteResponsibilityLoopStore,
        binding: Any,
        slice_id: str,
        clock: Any = _utc_now,
    ) -> "CountOnlyHcwProvenance":
        if not str(slice_id).strip():
            raise CountOnlyHcwProvenanceError("slice_id is required")
        _validate_slice_id(slice_id)
        try:
            receipts = store.list_hcw_measurement_receipts(binding.digest)
        except ResponsibilityLoopBindingDrift as exc:
            raise CountOnlyHcwProvenanceError(
                f"HCW measurement receipt drift: {exc}"
            ) from exc
        for receipt in receipts:
            if receipt.binding_digest != binding.digest:
                raise CountOnlyHcwProvenanceError(
                    "HCW measurement receipt binding scope mismatch"
                )
        counts = _derive_counts(receipts)
        recorded_at = clock().isoformat()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "slice_id": str(slice_id),
            "mandate_id": binding.mandate_id,
            "binding_digest": binding.digest,
            "measurement_status": HcwMeasurementStatus.HCW_INSUFFICIENT_DATA.value,
            "intervention_count": counts["intervention_count"],
            "operator_minutes": counts["operator_minutes"],
            "outcome_event_count": counts["outcome_event_count"],
            "help_event_count": counts["help_event_count"],
            "source_receipt_digests": list(counts["source_receipt_digests"]),
            "recorded_at": recorded_at,
            "claim_ceiling": CLAIM_CEILING,
        }
        record_digest = content_digest(payload)
        return cls.from_dict({**payload, "record_digest": record_digest})


def provenance_path(task_dir: Path, slice_id: str) -> Path:
    _validate_slice_id(slice_id)
    return Path(task_dir) / f"{slice_id}.{PROVENANCE_FILENAME}"


def record_count_only_hcw_provenance(
    *,
    store: SQLiteResponsibilityLoopStore,
    binding: Any,
    slice_id: str,
    task_dir: Path,
    clock: Any = _utc_now,
) -> CountOnlyHcwProvenance:
    """Derive and write a count-only HCW provenance record to the task directory.

    Fails closed if ``task_dir`` cannot be written, if any receipt digest drifts,
    or if the binding scope does not match. The record is derived exclusively
    from persisted measurement receipts; callers cannot inject counts.
    """
    record = CountOnlyHcwProvenance.build(
        store=store,
        binding=binding,
        slice_id=slice_id,
        clock=clock,
    )
    path = provenance_path(task_dir, slice_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        canonical = canonical_json(record.to_dict())
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".hcw_provenance.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(canonical + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError as exc:
        raise CountOnlyHcwProvenanceError(
            f"failed to write provenance record: {exc}"
        ) from exc
    return record


def verify_count_only_hcw_provenance(
    *,
    store: SQLiteResponsibilityLoopStore,
    binding: Any,
    slice_id: str,
    task_dir: Path,
) -> CountOnlyHcwProvenance:
    """Independently re-derive counts and confirm the record file matches.

    Read-only: re-opens the store, recomputes the sums, re-checks the record
    content digest, and raises ``CountOnlyHcwProvenanceError`` on any mismatch
    of the invariant fields (identity, counts, status, source digests). The
    write-time ``recorded_at`` and ``record_digest`` are not re-derived.
    """
    path = provenance_path(task_dir, slice_id)
    if not path.is_file():
        raise CountOnlyHcwProvenanceError(
            f"provenance record missing: {path}"
        )
    stored = CountOnlyHcwProvenance.from_dict(
        json.loads(path.read_text(encoding="utf-8"))
    )
    expected = CountOnlyHcwProvenance.build(
        store=store,
        binding=binding,
        slice_id=slice_id,
    )
    if stored.invariant_fields() != expected.invariant_fields():
        raise CountOnlyHcwProvenanceError(
            "count-only HCW provenance does not match the real persisted events"
        )
    return stored
