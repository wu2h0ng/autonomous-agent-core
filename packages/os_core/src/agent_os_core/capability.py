from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    ActionReceipt,
    CapabilitySpec,
    ReceiptStatus,
    SideEffectGuarantee,
)

from .governance import CorrectionAuthority


class CapabilityDenied(PermissionError):
    pass


@dataclass(frozen=True)
class CapabilityResult:
    receipt: ActionReceipt
    output: dict[str, object]


class CapabilityBroker:
    """The only execution boundary for typed capability actions."""

    def __init__(self, connector: WorkspaceSandbox, correction: CorrectionAuthority) -> None:
        self.connector = connector
        self.correction = correction

    def invoke(self, action: ActionContract, permit: ActionPermit, attempt: int = 1) -> CapabilityResult:
        if not permit.matches(action):
            raise CapabilityDenied("broker rejected a permit/action digest mismatch")
        return self.connector.invoke(action, permit, self.correction, attempt=attempt)


class WorkspaceSandbox:
    """Allowlisted repository capabilities on a disposable, path-confined workspace."""

    def __init__(self, root: str | Path, artifacts: str | Path | None = None, idempotency_store: object | None = None) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts = Path(artifacts or self.root / ".agent-os-artifacts").resolve()
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self._snapshots: dict[str, tuple[Path, bool]] = {}
        self._idempotency_store = idempotency_store

    def specs(self, now: datetime | None = None) -> dict[str, CapabilitySpec]:
        at = now or datetime.now(timezone.utc)
        common: dict[str, Any] = dict(
            input_contract="json:object:1",
            output_contract="json:object:1",
            credential_class="none",
            data_boundary="workspace-local",
            risk_tier=1,
            timeout_seconds=120,
            audit_policy="event-and-artifact",
            created_by="system",
            created_at=at,
        )
        return {
            "workspace.read": CapabilitySpec(
                capability_id="workspace.read", version="1", display_name="Read workspace file",
                side_effect_guarantee=SideEffectGuarantee.READ_ONLY, idempotency_supported=True,
                cancellation_supported=True, compensation_supported=False, **common,
            ),
            "workspace.apply_patch": CapabilitySpec(
                capability_id="workspace.apply_patch", version="1", display_name="Apply unified patch",
                side_effect_guarantee=SideEffectGuarantee.SANDBOX_COMPENSATABLE, idempotency_supported=True,
                cancellation_supported=True, compensation_supported=True, **common,
            ),
            "workspace.run_tests": CapabilitySpec(
                capability_id="workspace.run_tests", version="1", display_name="Run allowlisted tests",
                side_effect_guarantee=SideEffectGuarantee.SANDBOX_COMPENSATABLE, idempotency_supported=True,
                cancellation_supported=True, compensation_supported=True, **common,
            ),
            "artifact.write": CapabilitySpec(
                capability_id="artifact.write", version="1", display_name="Write content-addressed artifact",
                side_effect_guarantee=SideEffectGuarantee.SANDBOX_COMPENSATABLE, idempotency_supported=True,
                cancellation_supported=True, compensation_supported=True, **common,
            ),
        }

    def invoke(self, action: ActionContract, permit: ActionPermit, correction: CorrectionAuthority, attempt: int = 1) -> CapabilityResult:
        if not permit.matches(action):
            raise CapabilityDenied("permit does not match action")
        if correction.snapshot(action.task_id, action.run_id, action.capability_id) != permit.correction_epochs:
            raise CapabilityDenied("stale correction epoch")
        args = json.loads(action.arguments_json)
        if not isinstance(args, dict):
            raise CapabilityDenied("capability arguments must be an object")
        stored = self._get_idempotency(action.idempotency_key)
        if stored is not None:
            output: dict[str, object] = stored
            status = ReceiptStatus.SUCCEEDED
            error_code = "error:none"
        else:
            try:
                output = self._dispatch(action.capability_id, args, action.idempotency_key)
                self._put_idempotency(action.idempotency_key, output)
                status = ReceiptStatus.SUCCEEDED
                error_code = "error:none"
            except Exception as exc:
                output = {"error": type(exc).__name__}
                status = ReceiptStatus.FAILED
                error_code = type(exc).__name__
        receipt = ActionReceipt(
            receipt_id=f"receipt-{uuid4()}", action_id=action.action_id,
            action_digest=action.action_digest(), permit_id=permit.permit_id,
            tenant_id=action.tenant_id, workspace_id=action.workspace_id,
            connector_id=action.capability_id, status=status,
            idempotency_key=action.idempotency_key, attempt=attempt,
            output_artifact_ids=tuple(str(value) for value in _as_sequence(output.get("artifact_ids", ()))),
            error_code=error_code, occurred_at=datetime.now(timezone.utc),
        )
        return CapabilityResult(receipt=receipt, output=output)

    def _get_idempotency(self, key: str) -> dict[str, object] | None:
        if self._idempotency_store is None:
            return None
        getter = getattr(self._idempotency_store, "get_idempotency", None)
        return getter("capability", key) if getter is not None else None

    def _put_idempotency(self, key: str, output: dict[str, object]) -> None:
        if self._idempotency_store is None:
            return
        setter = getattr(self._idempotency_store, "put_idempotency", None)
        if setter is not None:
            setter("capability", key, output, datetime.now(timezone.utc).isoformat())

    def _dispatch(self, capability_id: str, args: dict[str, object], action_key: str) -> dict[str, object]:
        if capability_id == "workspace.read":
            path = self._safe_path(str(args.get("path", "")))
            if not path.is_file():
                raise FileNotFoundError(str(args.get("path")))
            content = path.read_text(encoding="utf-8")
            return {"path": str(path.relative_to(self.root)), "content": content, "sha256": _sha256(content.encode())}
        if capability_id == "workspace.apply_patch":
            return self._apply_patch(args, action_key)
        if capability_id == "workspace.run_tests":
            return self._run_tests(args, action_key)
        if capability_id == "artifact.write":
            content = str(args.get("content", "")).encode("utf-8")
            digest = _sha256(content)
            target = self.artifacts / digest
            if not target.exists():
                target.write_bytes(content)
            return {"artifact_ids": (f"artifact:{digest}",), "digest": digest}
        raise CapabilityDenied(f"capability is not registered: {capability_id}")

    def _safe_path(self, value: str) -> Path:
        if not value or value.startswith("/") or "\\" in value:
            raise CapabilityDenied("path must be a relative workspace path")
        raw = self.root / value
        if any(part.is_symlink() for part in (self.root, *raw.parents) if part.exists()):
            raise CapabilityDenied("symlink paths are forbidden")
        candidate = raw.resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise CapabilityDenied("path escapes workspace")
        return candidate

    def _apply_patch(self, args: dict[str, object], action_key: str) -> dict[str, object]:
        path = self._safe_path(str(args.get("path", "")))
        content = str(args.get("content", ""))
        expected = args.get("expected_sha256")
        actual = _sha256(path.read_bytes()) if path.exists() else None
        if expected is not None and expected != actual:
            raise CapabilityDenied("workspace changed since proposal")
        if action_key in self._snapshots:
            return {"path": str(path.relative_to(self.root)), "sha256": _sha256(path.read_bytes()), "replayed": True}
        snapshot = Path(tempfile.mkdtemp(prefix="agent-os-snapshot-")) / "before"
        if path.exists():
            shutil.copy2(path, snapshot)
        else:
            snapshot.write_text("", encoding="utf-8")
        self._snapshots[action_key] = (snapshot, path.exists())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"path": str(path.relative_to(self.root)), "sha256": _sha256(content.encode()), "replayed": False}

    def compensate(self, action_key: str, path: str) -> None:
        snapshot_record = self._snapshots.get(action_key)
        target = self._safe_path(path)
        if snapshot_record is not None:
            snapshot, existed = snapshot_record
            if not existed:
                target.unlink(missing_ok=True)
                return
            shutil.copy2(snapshot, target)

    def _run_tests(self, args: dict[str, object], action_key: str) -> dict[str, object]:
        command = str(args.get("command", ""))
        allowed = {"pytest", "python -m pytest", "python3 -m pytest"}
        if command not in allowed:
            raise CapabilityDenied("only the allowlisted test commands are permitted")
        timeout = min(int(str(args.get("timeout_seconds", 120))), 120)
        result = subprocess.run(
            command.split(), cwd=self.root, capture_output=True, text=True,
            timeout=timeout, check=False, env={**os.environ, "NO_COLOR": "1"},
        )
        output = (result.stdout + "\n" + result.stderr).encode("utf-8")
        digest = _sha256(output)
        artifact = self.artifacts / digest
        if not artifact.exists():
            artifact.write_bytes(output)
        return {"exit_code": result.returncode, "artifact_ids": (f"artifact:{digest}",), "digest": digest}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _as_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, (tuple, list)):
        return tuple(value)
    return ()
