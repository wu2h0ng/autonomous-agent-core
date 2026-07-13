"""E2E4 product-side pre-freeze permission sentinel brake.

The generic preregistration runner does not understand experiment-local
sentinels.  This command therefore must run before manifest review/freeze.  It
is read-only: it parses the draft spec, verifies the current permission ledgers
through the typed authority verifier, and requires byte-independent semantic
equality for every frozen permission field.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime  # noqa: F401 - public test-facing constructor
from pathlib import Path
from typing import Any, Mapping, Sequence

from product_evals.common.authority_binding import (
    AuthorityBinding,
    verify_authority_binding,
)

from .identity import IDENTITY

PERMISSION_SENTINEL = "PRE_FREEZE_PERMISSION_UNBOUND"
PERMISSION_ACTION = "team.event.record"
PERMISSION_PATH = f".agent_runs/{IDENTITY.run_id}/agent_events.jsonl"
TARGET_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = TARGET_ROOT.parents[2]
RUNNER_INTERPRETER = Path(
    os.path.abspath(WORKSPACE_ROOT / "ai-agent-engineering-workflow/.venv/bin/python")
)


def frozen_permission_fields(authority: AuthorityBinding) -> dict[str, object]:
    """Return the one exact spec projection of a verified typed binding."""

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


def validate_prefreeze_permission(
    permission: object, authority: AuthorityBinding
) -> None:
    """Reject sentinels, omissions, extras, or substituted valid authority."""

    if not isinstance(permission, Mapping):
        raise ValueError("PREFREEZE_PERMISSION_UNBOUND")
    required = frozen_permission_fields(authority)
    if any(value == PERMISSION_SENTINEL for value in permission.values()):
        raise ValueError("PREFREEZE_PERMISSION_UNBOUND")
    observed = {key: permission.get(key) for key in required}
    if observed != required:
        raise ValueError("INVALID_AUTHORITY_BINDING")


def _reject_permission_sentinel(permission: object) -> None:
    if not isinstance(permission, Mapping) or any(
        value == PERMISSION_SENTINEL for value in permission.values()
    ):
        raise ValueError("PREFREEZE_PERMISSION_UNBOUND")


def _load_yaml(path: Path) -> dict[str, Any]:
    """Parse YAML via the pinned runner environment without adding a product dep."""

    script = (
        "import json,sys,yaml; "
        "value=yaml.load(open(sys.argv[1],encoding='utf-8'),Loader=yaml.BaseLoader); "
        "json.dump(value,sys.stdout,allow_nan=False)"
    )
    try:
        completed = subprocess.run(
            (str(RUNNER_INTERPRETER), "-c", script, str(path)),
            cwd=TARGET_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        value = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise ValueError("INVALID_PREFREEZE_SPEC") from exc
    if not isinstance(value, dict):
        raise ValueError("INVALID_PREFREEZE_SPEC")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=WORKSPACE_ROOT / ".agent_runs" / IDENTITY.run_id,
    )
    args = parser.parse_args(argv)
    spec = _load_yaml(args.spec)
    permission = spec.get("permission_binding")
    _reject_permission_sentinel(permission)
    authority = verify_authority_binding(
        args.run_root,
        run_id=IDENTITY.run_id,
        action=PERMISSION_ACTION,
        affected_path=PERMISSION_PATH,
    )
    validate_prefreeze_permission(permission, authority)
    print(
        json.dumps(
            {
                "status": "PREFREEZE_PERMISSION_BOUND",
                "run_id": IDENTITY.run_id,
                "request_row_sha256": authority.request_sha256,
                "approval_row_sha256": authority.approval_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - module CLI boundary
    raise SystemExit(main())
