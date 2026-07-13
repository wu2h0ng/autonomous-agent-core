"""Public-only helpers shared by SPINE product evaluations."""

from __future__ import annotations

import os
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from apps.api_server.app import AgentOSApplication


_PROVIDER_VARIABLES = (
    "AGENT_OS_PROVIDER_BASE_URL",
    "AGENT_OS_PROVIDER_MODEL",
    "AGENT_OS_PROVIDER_TEMPERATURE",
    "AGENT_OS_PROVIDER_API_KEY_ENV",
    "OPENAI_API_KEY",
    "AGENT_OS_RUNTIME_PROVIDER_KEY",
    "SPINE_E2E_1_PROVIDER_KEY",
)
_OMIT_KEYS = frozenset(
    {
        "task_id",
        "run_id",
        "event_id",
        "approval_id",
        "proposal_id",
        "action_id",
        "request_id",
        "artifact_id",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "decided_at",
        "expires_at",
        "duration_seconds",
    }
)


@dataclass(frozen=True)
class CaseArmPaths:
    workspace: Path
    database: Path


def case_arm_paths(root: Path, case_id: str, arm: str) -> CaseArmPaths:
    if not case_id or not arm or Path(case_id).name != case_id or Path(arm).name != arm:
        raise ValueError("case_id and arm must be safe path components")
    base = Path(root) / "cases" / case_id / arm
    return CaseArmPaths(
        workspace=base / "workspace",
        database=base / "state" / "agent-os.sqlite3",
    )


def _safe_fixture_path(workspace: Path, value: object) -> Path:
    relative = Path(str(value))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("fixture path must be a safe relative path")
    root = workspace.resolve()
    destination = (root / relative).resolve()
    if destination == root or root not in destination.parents:
        raise ValueError("fixture path must be a safe relative path")
    return destination


def write_case_fixture(workspace: Path, case: Mapping[str, Any]) -> None:
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    files = (
        (_safe_fixture_path(root, case["target_path"]), case["initial_content"]),
        (_safe_fixture_path(root, case["test_path"]), case["pytest_source"]),
    )
    if files[0][0] == files[1][0]:
        raise ValueError("fixture paths must be distinct")
    for destination, content in files:
        if not isinstance(content, str):
            raise ValueError("fixture content must be text")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def configure_provider_environment(base_url: str) -> None:
    if not base_url.startswith("http://127.0.0.1:") or not base_url.endswith("/v1"):
        raise ValueError("provider must be the frozen loopback /v1 endpoint")
    for name in _PROVIDER_VARIABLES:
        os.environ.pop(name, None)
    os.environ.update(
        {
            "AGENT_OS_PROVIDER_BASE_URL": base_url,
            "AGENT_OS_PROVIDER_MODEL": "spine-e2e-1-frozen",
            "AGENT_OS_PROVIDER_TEMPERATURE": "0",
            "AGENT_OS_PROVIDER_API_KEY_ENV": "SPINE_E2E_1_PROVIDER_KEY",
            "SPINE_E2E_1_PROVIDER_KEY": "spine-e2e-1-local-dummy",
        }
    )


def open_application(database: Path, workspace: Path) -> AgentOSApplication:
    if str(database) == ":memory:":
        raise ValueError("SPINE requires an explicit file database")
    database.parent.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    application = AgentOSApplication(database=database, workspace=workspace)
    status = application.provider_status()
    if status != {
        "configured": True,
        "provider_id": "openai-compatible",
        "model_id": "spine-e2e-1-frozen",
        "endpoint_class": "openai-compatible",
        "credential_ref_id": "credential:default",
    }:
        raise RuntimeError("frozen provider status mismatch")
    return application


def normalize_projection(value: Any) -> Any:
    """Remove identity/time/artifact noise while preserving semantic public state."""
    if isinstance(value, Mapping):
        return {
            str(key): normalize_projection(item)
            for key, item in value.items()
            if str(key) not in _OMIT_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [normalize_projection(item) for item in value]
    return value


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def workspace_tree_sha256(workspace: Path) -> str:
    root = Path(workspace)
    entries: list[dict[str, str]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if any(
            part in {".agent-os-artifacts", ".pytest_cache", "__pycache__"}
            for part in relative.parts
        ):
            continue
        entries.append({"path": relative.as_posix(), "sha256": _sha256_path(path)})
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def public_evidence(
    application: Any,
    task_id: str,
    workspace: Path,
    provider_ledger: Path,
) -> dict[str, Any]:
    task = application.task_json(task_id)
    evidence = application.evidence_json(task_id)
    recovery = application.recovery_json(task_id)
    run = task.get("run") if isinstance(task, Mapping) else None
    lease_fence = recovery.get("lease_fence", 0)
    if isinstance(run, Mapping):
        lease_fence = run.get("lease_fence", lease_fence)
    return {
        "status": task.get("status"),
        "sequence": task.get("sequence"),
        "lease_fence": lease_fence,
        "action_receipt_count": sum(
            item.get("event_type") == "ACTION_RECEIPT_RECORDED"
            for item in evidence
            if isinstance(item, Mapping)
        ),
        "projection": normalize_projection(
            {"task": task, "evidence": evidence, "recovery": recovery}
        ),
        "workspace_tree_sha256": workspace_tree_sha256(workspace),
        "provider_ledger_sha256": _sha256_path(provider_ledger),
    }


def prepare_case(
    run_root: Path,
    case: Mapping[str, Any],
    base_url: str,
    provider_ledger: Path,
) -> dict[str, Any]:
    from product_evals.spine_e2e_1.protocol import prepare

    bindings: dict[str, tuple[CaseArmPaths, AgentOSApplication]] = {}
    for arm in ("uninterrupted", "interrupted"):
        paths = case_arm_paths(run_root, str(case["case_id"]), arm)
        write_case_fixture(paths.workspace, case)
        configure_provider_environment(base_url)
        bindings[arm] = (paths, open_application(paths.database, paths.workspace))
    result = prepare(bindings["uninterrupted"][1], bindings["interrupted"][1], case)
    result["paths"] = {
        arm: {"workspace": str(value[0].workspace), "database": str(value[0].database)}
        for arm, value in bindings.items()
    }
    result["public_evidence"] = {
        arm: public_evidence(
            bindings[arm][1],
            result["task_ids"][arm],
            bindings[arm][0].workspace,
            provider_ledger,
        )
        for arm in bindings
    }
    return result
