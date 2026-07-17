"""Non-authorizing subprocess surface for R-STATE execution admission bytes."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import BinaryIO

from experiments.r_state_credit_1.execution_bridge import (
    ExecutionAdmission,
    ExecutionBridgeViolation,
    canonical_json,
)


_MAX_ADMISSION_BYTES = 1024 * 1024


def _write_json(stream: BinaryIO, payload: object) -> None:
    stream.write((canonical_json(payload) + "\n").encode())


def _read_admission(stream: BinaryIO) -> bytes:
    encoded = stream.read(_MAX_ADMISSION_BYTES + 1)
    if len(encoded) > _MAX_ADMISSION_BYTES:
        raise ExecutionBridgeViolation(
            f"execution admission exceeds {_MAX_ADMISSION_BYTES} bytes"
        )
    return encoded


def main(argv: Sequence[str] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments != ("validate-admission",):
        _write_json(
            sys.stderr.buffer,
            {
                "error_code": "CLI_USAGE_REJECTED",
                "message": "expected exactly: validate-admission",
                "schema_version": "r-state-credit-1-execution-cli-error-v1",
            },
        )
        return 2
    try:
        admission = ExecutionAdmission.from_canonical_json(
            _read_admission(sys.stdin.buffer)
        )
    except ExecutionBridgeViolation as exc:
        _write_json(
            sys.stderr.buffer,
            {
                "error_code": "EXECUTION_ADMISSION_REJECTED",
                "message": str(exc),
                "schema_version": "r-state-credit-1-execution-cli-error-v1",
            },
        )
        return 2
    _write_json(
        sys.stdout.buffer,
        {
            "authority_verified": False,
            "envelope_core_sha256": admission.envelope_core_sha256,
            "envelope_sha256": admission.envelope_sha256,
            "execution_code_head": admission.execution_code_head,
            "route_id": admission.route_id,
            "run_id": admission.run_id,
            "schema_version": "r-state-credit-1-admission-parse-receipt-v1",
            "status": "PARSED_ONLY",
            "mechanism_head": admission.mechanism_head,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
