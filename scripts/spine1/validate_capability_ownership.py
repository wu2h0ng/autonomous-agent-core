from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


ALLOWED_DISPOSITIONS = {
    "KEEP_IN_AGENT_OS_CORE",
    "EXTRACT_TO_SHARED_PACKAGE",
    "MOVE_TO_DATA_AGENT_PACK",
    "RETAIN_AS_HISTORICAL_EVIDENCE",
    "PARK_NO_CONSUMER",
    "DROP_DUPLICATE_AFTER_PROOF",
    "BLOCK_UNRESOLVED",
}
REQUIRED_FIELDS = {
    "capability_id",
    "user_need_ref",
    "source_repo",
    "source_paths",
    "source_sha",
    "public_entrypoint",
    "contracts",
    "failure_paths",
    "tests",
    "current_evidence",
    "target_owner",
    "disposition",
    "consumer",
    "residual_gap",
    "semantic_scope",
    "authority_key",
    "runtime_authority",
    "post_migration_runtime_owners",
}


class OwnershipError(ValueError):
    """Raised when the convergence ownership matrix permits ambiguous authority."""


def _is_full_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        char in "0123456789abcdef" for char in value
    )


def validate_matrix(matrix: dict[str, Any]) -> None:
    rows = matrix.get("capabilities")
    if matrix.get("schema_version") != 1 or not isinstance(rows, list) or not rows:
        raise OwnershipError("schema_version 1 and a non-empty capabilities list are required")

    seen_ids: set[str] = set()
    authority_owners: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if not isinstance(row, dict):
            raise OwnershipError("every capability row must be a mapping")
        missing = sorted(REQUIRED_FIELDS - row.keys())
        if missing:
            raise OwnershipError(f"capability row missing fields: {', '.join(missing)}")
        capability_id = row["capability_id"]
        if not isinstance(capability_id, str) or not capability_id:
            raise OwnershipError("capability_id must be non-empty")
        if capability_id in seen_ids:
            raise OwnershipError(f"duplicate capability_id: {capability_id}")
        seen_ids.add(capability_id)
        if not _is_full_sha(row["source_sha"]):
            raise OwnershipError(f"{capability_id}: source_sha must be a full SHA")
        if row["disposition"] not in ALLOWED_DISPOSITIONS:
            raise OwnershipError(f"{capability_id}: unsupported disposition")
        if row["semantic_scope"] not in {"GENERIC", "DATA_DOMAIN", "HISTORICAL"}:
            raise OwnershipError(f"{capability_id}: invalid semantic_scope")
        if not isinstance(row["consumer"], list):
            raise OwnershipError(f"{capability_id}: consumer must be a list")
        if (
            row["disposition"] == "EXTRACT_TO_SHARED_PACKAGE"
            and len(set(row["consumer"])) < 2
        ):
            raise OwnershipError(
                f"{capability_id}: shared extraction requires at least two consumers"
            )
        if row["semantic_scope"] == "DATA_DOMAIN" and str(row["target_owner"]).startswith(
            "packages/os_core"
        ):
            raise OwnershipError(
                f"{capability_id}: Data-domain semantics cannot target packages/os_core"
            )

        owners = row["post_migration_runtime_owners"]
        if not isinstance(owners, list):
            raise OwnershipError(
                f"{capability_id}: post_migration_runtime_owners must be a list"
            )
        if row["runtime_authority"]:
            if len(owners) != 1:
                raise OwnershipError(
                    f"{capability_id}: runtime authority requires exactly one post-migration runtime owner"
                )
            authority_owners[str(row["authority_key"])].update(str(item) for item in owners)
        elif owners:
            raise OwnershipError(
                f"{capability_id}: non-runtime rows cannot claim a runtime owner"
            )

    ambiguous = {
        key: sorted(owners) for key, owners in authority_owners.items() if len(owners) != 1
    }
    if ambiguous:
        raise OwnershipError(f"authority keys have multiple runtime owners: {ambiguous}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate SPINE-1 capability ownership")
    parser.add_argument("matrix", type=Path)
    args = parser.parse_args()
    matrix = yaml.safe_load(args.matrix.read_text(encoding="utf-8"))
    validate_matrix(matrix)
    print(f"validated {len(matrix['capabilities'])} capability ownership rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
