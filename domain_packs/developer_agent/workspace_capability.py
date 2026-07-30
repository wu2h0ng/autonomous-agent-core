from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_os_contracts import (
    ActionContract,
    CapabilitySpec,
    ReceiptStatus,
    SideEffectGuarantee,
)
from agent_os_core import CapabilityDenied, CapabilityEffect


class DeveloperWorkspaceAdapter:
    """Allowlisted repository capabilities on a disposable, path-confined workspace."""

    def __init__(self, root: str | Path, artifacts: str | Path | None = None, idempotency_store: object | None = None) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts = Path(artifacts or self.root / ".agent-os-artifacts").resolve()
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self._idempotency_store = idempotency_store

    def specs(
        self,
        now: datetime | None = None,
        *,
        include_internal: bool = False,
    ) -> dict[str, CapabilitySpec]:
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
        specs = {
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
                side_effect_guarantee=SideEffectGuarantee.SANDBOX_IDEMPOTENT, idempotency_supported=True,
                cancellation_supported=True, compensation_supported=False, **common,
            ),
            "artifact.write": CapabilitySpec(
                capability_id="artifact.write", version="1", display_name="Write content-addressed artifact",
                side_effect_guarantee=SideEffectGuarantee.SANDBOX_IDEMPOTENT, idempotency_supported=True,
                cancellation_supported=True, compensation_supported=False, **common,
            ),
        }
        if include_internal:
            specs["workspace.compensate_patch"] = CapabilitySpec(
                capability_id="workspace.compensate_patch",
                version="1",
                display_name="Restore governed patch snapshot",
                side_effect_guarantee=SideEffectGuarantee.SANDBOX_IDEMPOTENT,
                idempotency_supported=True,
                cancellation_supported=True,
                compensation_supported=False,
                **common,
            )
        return specs

    def execute(self, action: ActionContract) -> CapabilityEffect:
        args = json.loads(action.arguments_json)
        if not isinstance(args, dict):
            raise CapabilityDenied("capability arguments must be an object")
        intent_fingerprint = _intent_fingerprint(action)
        stored = self._get_idempotency(
            action.idempotency_key,
            intent_fingerprint,
        )
        if stored is not None:
            if action.capability_id == "workspace.apply_patch":
                self._validate_cached_patch_effect(args, stored)
            elif action.capability_id == "workspace.compensate_patch":
                self._validate_cached_compensation_effect(args, stored)
            output: dict[str, object] = stored
            status = (
                ReceiptStatus.COMPENSATED
                if action.capability_id == "workspace.compensate_patch"
                else ReceiptStatus.SUCCEEDED
            )
            error_code = "error:none"
        else:
            try:
                output = self._dispatch(action.capability_id, args, action.idempotency_key)
                self._put_idempotency(
                    action.idempotency_key,
                    intent_fingerprint,
                    output,
                )
                status = (
                    ReceiptStatus.COMPENSATED
                    if action.capability_id == "workspace.compensate_patch"
                    else ReceiptStatus.SUCCEEDED
                )
                error_code = "error:none"
            except Exception as exc:
                output = {"error": type(exc).__name__}
                status = ReceiptStatus.FAILED
                error_code = type(exc).__name__
        return CapabilityEffect(
            status=status,
            output=output,
            error_code=error_code,
            detail_ref=str(output.get("compensation_ref", "detail:none")),
        )

    def _get_idempotency(
        self,
        key: str,
        intent_fingerprint: str,
    ) -> dict[str, object] | None:
        if self._idempotency_store is None:
            return None
        getter = getattr(self._idempotency_store, "get_idempotency", None)
        stored = getter("capability", key) if getter is not None else None
        if stored is None:
            return None
        if not isinstance(stored, dict):
            raise CapabilityDenied("invalid idempotency record")
        if stored.get("intent_fingerprint") != intent_fingerprint:
            raise CapabilityDenied("idempotency key reused for a different action intent")
        output = stored.get("output")
        if not isinstance(output, dict):
            raise CapabilityDenied("invalid idempotency output record")
        return output

    def _put_idempotency(
        self,
        key: str,
        intent_fingerprint: str,
        output: dict[str, object],
    ) -> None:
        if self._idempotency_store is None:
            return
        setter = getattr(self._idempotency_store, "put_idempotency", None)
        if setter is not None:
            stored = {
                "intent_fingerprint": intent_fingerprint,
                "output": output,
            }
            inserted = setter(
                "capability",
                key,
                stored,
                datetime.now(timezone.utc).isoformat(),
            )
            if inserted is False:
                self._get_idempotency(key, intent_fingerprint)

    def _dispatch(self, capability_id: str, args: dict[str, object], action_key: str) -> dict[str, object]:
        if capability_id == "workspace.read":
            path = self._safe_path(str(args.get("path", "")))
            if not path.is_file():
                raise FileNotFoundError(str(args.get("path")))
            content = path.read_text(encoding="utf-8")
            return {"path": str(path.relative_to(self.root)), "content": content, "sha256": _sha256(content.encode())}
        if capability_id == "workspace.apply_patch":
            return self._apply_patch(args, action_key)
        if capability_id == "workspace.compensate_patch":
            return self._compensate_patch(args)
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

    def read_artifact_bytes(self, artifact_id: str) -> bytes | None:
        prefix = "artifact:"
        if not artifact_id.startswith(prefix):
            return None
        digest = artifact_id.removeprefix(prefix)
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            return None
        path = self.artifacts / digest
        if not path.is_file() or path.is_symlink():
            return None
        content = path.read_bytes()
        return content if _sha256(content) == digest else None

    def _safe_path(self, value: str) -> Path:
        if not value or value.startswith("/") or "\\" in value:
            raise CapabilityDenied("path must be a relative workspace path")
        if Path(value).parts and Path(value).parts[0] == ".agent-os-artifacts":
            raise CapabilityDenied("workspace artifact state is reserved")
        raw = self.root / value
        if any(part.is_symlink() for part in (self.root, *raw.parents) if part.exists()):
            raise CapabilityDenied("symlink paths are forbidden")
        candidate = raw.resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise CapabilityDenied("path escapes workspace")
        if candidate == self.artifacts or self.artifacts in candidate.parents:
            raise CapabilityDenied("workspace artifact state is reserved")
        return candidate

    def _apply_patch(self, args: dict[str, object], action_key: str) -> dict[str, object]:
        path = self._safe_path(str(args.get("path", "")))
        content = str(args.get("content", ""))
        content_bytes = content.encode("utf-8")
        relative_path = str(path.relative_to(self.root))
        key_digest = _sha256(action_key.encode("utf-8"))
        compensation_ref = f"compensation:{key_digest}"
        snapshot_dir = self.artifacts / "compensation" / key_digest
        applied_sha256 = _sha256(content_bytes)
        if snapshot_dir.exists():
            manifest, manifest_sha256, state, _ = self._load_snapshot(
                compensation_ref
            )
            if state == "COMPENSATED":
                raise CapabilityDenied("patch was already compensated and cannot replay")
            if manifest["action_key_sha256"] != key_digest:
                raise CapabilityDenied("snapshot action key binding mismatch")
            if manifest["relative_path"] != relative_path:
                raise CapabilityDenied("snapshot path binding mismatch")
            if manifest["applied_sha256"] != applied_sha256:
                raise CapabilityDenied("idempotency key reused for different patch content")
            current_matches_applied = (
                path.exists() and _sha256(path.read_bytes()) == applied_sha256
            )
            before_existed = bool(manifest["before_existed"])
            current_matches_before = (
                path.exists()
                and before_existed
                and _sha256(path.read_bytes()) == manifest["before_sha256"]
            ) or (not path.exists() and not before_existed)
            if state == "PREPARED":
                if current_matches_before:
                    self._atomic_write(path, content_bytes)
                elif not current_matches_applied:
                    raise CapabilityDenied(
                        "workspace changed outside the prepared patch replay"
                    )
                self._write_snapshot_state(snapshot_dir, "APPLIED")
            elif state == "APPLIED" and not current_matches_applied:
                raise CapabilityDenied(
                    "APPLIED snapshot no longer matches the patch effect"
                )
            return {
                "path": relative_path,
                "sha256": applied_sha256,
                "before_sha256": manifest["before_sha256"],
                "applied_sha256": applied_sha256,
                "compensation_ref": compensation_ref,
                "manifest_sha256": manifest_sha256,
                "replayed": True,
            }
        expected = args.get("expected_sha256")
        before_existed = path.exists()
        before_bytes = path.read_bytes() if before_existed else b""
        actual = _sha256(before_bytes) if before_existed else None
        if expected is not None and expected != actual:
            raise CapabilityDenied("workspace changed since proposal")
        manifest: dict[str, object] = {
            "schema_version": "1.0",
            "compensation_ref": compensation_ref,
            "action_key_sha256": key_digest,
            "relative_path": relative_path,
            "before_existed": before_existed,
            "before_sha256": _sha256(before_bytes),
            "applied_sha256": applied_sha256,
        }
        manifest_sha256 = self._persist_snapshot(
            snapshot_dir,
            manifest,
            before_bytes,
        )
        self._atomic_write(path, content_bytes)
        self._write_snapshot_state(snapshot_dir, "APPLIED")
        return {
            "path": relative_path,
            "sha256": applied_sha256,
            "before_sha256": manifest["before_sha256"],
            "applied_sha256": applied_sha256,
            "compensation_ref": compensation_ref,
            "manifest_sha256": manifest_sha256,
            "replayed": False,
        }

    def _validate_cached_patch_effect(
        self,
        args: dict[str, object],
        output: dict[str, object],
    ) -> None:
        compensation_ref = output.get("compensation_ref")
        manifest_sha256 = output.get("manifest_sha256")
        applied_sha256 = output.get("applied_sha256")
        if not all(
            isinstance(value, str)
            for value in (compensation_ref, manifest_sha256, applied_sha256)
        ):
            raise CapabilityDenied("cached patch lacks durable compensation binding")
        _, _, state, _ = self._load_snapshot(
            str(compensation_ref),
            expected_manifest_sha256=str(manifest_sha256),
        )
        if state == "COMPENSATED":
            raise CapabilityDenied("cached patch was already compensated")
        target = self._safe_path(str(args.get("path", "")))
        if not target.is_file() or _sha256(target.read_bytes()) != applied_sha256:
            raise CapabilityDenied("cached patch effect is no longer present")

    def _validate_cached_compensation_effect(
        self,
        args: dict[str, object],
        output: dict[str, object],
    ) -> None:
        compensation_ref = output.get("compensation_ref")
        manifest_sha256 = output.get("manifest_sha256")
        if not isinstance(compensation_ref, str) or not isinstance(
            manifest_sha256, str
        ):
            raise CapabilityDenied("cached compensation lacks snapshot binding")
        if compensation_ref != args.get("compensation_ref"):
            raise CapabilityDenied("cached compensation reference mismatch")
        manifest, _, state, _ = self._load_snapshot(
            compensation_ref,
            expected_manifest_sha256=manifest_sha256,
        )
        if state != "COMPENSATED":
            raise CapabilityDenied("cached compensation state is not terminal")
        action_key = str(args.get("original_action_key", ""))
        if manifest["action_key_sha256"] != _sha256(action_key.encode("utf-8")):
            raise CapabilityDenied("cached compensation action key mismatch")
        relative_path = str(args.get("path", ""))
        if manifest["relative_path"] != relative_path:
            raise CapabilityDenied("cached compensation path mismatch")
        target = self._safe_path(relative_path)
        before_existed = bool(manifest["before_existed"])
        current_is_before = (
            target.exists()
            and before_existed
            and _sha256(target.read_bytes()) == manifest["before_sha256"]
        ) or (not target.exists() and not before_existed)
        if not current_is_before:
            raise CapabilityDenied("cached compensation effect is no longer present")

    def compensate(self, action_key: str, path: str) -> None:
        compensation_ref = f"compensation:{_sha256(action_key.encode('utf-8'))}"
        _, manifest_sha256, _, _ = self._load_snapshot(compensation_ref)
        self._compensate_patch(
            {
                "path": path,
                "original_action_key": action_key,
                "compensation_ref": compensation_ref,
                "manifest_sha256": manifest_sha256,
            }
        )

    def _compensate_patch(self, args: dict[str, object]) -> dict[str, object]:
        relative_path = str(args.get("path", ""))
        target = self._safe_path(relative_path)
        action_key = str(args.get("original_action_key", ""))
        compensation_ref = str(args.get("compensation_ref", ""))
        expected_manifest_sha256 = str(args.get("manifest_sha256", ""))
        manifest, manifest_sha256, state, before_bytes = self._load_snapshot(
            compensation_ref,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        if manifest["action_key_sha256"] != _sha256(action_key.encode("utf-8")):
            raise CapabilityDenied("snapshot action key binding mismatch")
        if manifest["relative_path"] != relative_path:
            raise CapabilityDenied("snapshot path binding mismatch")
        applied_sha256 = str(manifest["applied_sha256"])
        before_existed = bool(manifest["before_existed"])
        before_sha256 = str(manifest["before_sha256"])
        current_is_applied = (
            target.exists() and _sha256(target.read_bytes()) == applied_sha256
        )
        current_is_before = (
            target.exists()
            and before_existed
            and _sha256(target.read_bytes()) == before_sha256
        ) or (not target.exists() and not before_existed)
        if state == "COMPENSATED":
            if not current_is_before:
                raise CapabilityDenied(
                    "COMPENSATED snapshot is terminal and target has changed"
                )
            return {
                "path": relative_path,
                "compensation_ref": compensation_ref,
                "manifest_sha256": manifest_sha256,
                "compensated": True,
                "replayed": True,
            }
        if state != "APPLIED":
            raise CapabilityDenied("patch snapshot is not in APPLIED state")
        if current_is_applied:
            if before_existed:
                self._atomic_write(target, before_bytes)
            else:
                target.unlink(missing_ok=True)
        elif not current_is_before:
            raise CapabilityDenied("target changed after patch; compensation refused")
        self._write_snapshot_state(
            self.artifacts
            / "compensation"
            / compensation_ref.removeprefix("compensation:"),
            "COMPENSATED",
        )
        return {
            "path": relative_path,
            "compensation_ref": compensation_ref,
            "manifest_sha256": manifest_sha256,
            "compensated": True,
            "replayed": current_is_before,
        }

    def _persist_snapshot(
        self,
        snapshot_dir: Path,
        manifest: dict[str, object],
        before_bytes: bytes,
    ) -> str:
        root = snapshot_dir.parent
        root.mkdir(parents=True, exist_ok=True)
        manifest_bytes = _canonical_json_bytes(manifest)
        manifest_sha256 = _sha256(manifest_bytes)
        staging = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=root))
        try:
            self._write_new_file(staging / "manifest.json", manifest_bytes)
            if bool(manifest["before_existed"]):
                self._write_new_file(staging / "before.bin", before_bytes)
            self._write_new_file(
                staging / "state.json",
                _canonical_json_bytes({"state": "PREPARED"}),
            )
            _fsync_directory(staging)
            try:
                os.rename(staging, snapshot_dir)
            except FileExistsError:
                raise CapabilityDenied("snapshot already exists for action key")
            _fsync_directory(root)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return manifest_sha256

    def _load_snapshot(
        self,
        compensation_ref: str,
        *,
        expected_manifest_sha256: str | None = None,
    ) -> tuple[dict[str, object], str, str, bytes]:
        if not compensation_ref.startswith("compensation:"):
            raise CapabilityDenied("invalid compensation reference")
        digest = compensation_ref.removeprefix("compensation:")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise CapabilityDenied("invalid compensation reference digest")
        snapshot_dir = self.artifacts / "compensation" / digest
        manifest_path = snapshot_dir / "manifest.json"
        state_path = snapshot_dir / "state.json"
        if not manifest_path.is_file() or not state_path.is_file():
            raise CapabilityDenied("compensation manifest or state is missing")
        manifest_bytes = manifest_path.read_bytes()
        manifest_sha256 = _sha256(manifest_bytes)
        if (
            expected_manifest_sha256 is not None
            and manifest_sha256 != expected_manifest_sha256
        ):
            raise CapabilityDenied("compensation manifest digest mismatch")
        try:
            manifest_value = json.loads(manifest_bytes)
            state_value = json.loads(state_path.read_bytes())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CapabilityDenied("invalid compensation manifest JSON") from exc
        if not isinstance(manifest_value, dict) or not isinstance(state_value, dict):
            raise CapabilityDenied("invalid compensation manifest shape")
        manifest: dict[str, object] = manifest_value
        required = {
            "schema_version",
            "compensation_ref",
            "action_key_sha256",
            "relative_path",
            "before_existed",
            "before_sha256",
            "applied_sha256",
        }
        if set(manifest) != required:
            raise CapabilityDenied("invalid compensation manifest fields")
        if manifest["compensation_ref"] != compensation_ref:
            raise CapabilityDenied("compensation manifest reference mismatch")
        state = state_value.get("state")
        if state not in {"PREPARED", "APPLIED", "COMPENSATED"}:
            raise CapabilityDenied("invalid compensation snapshot state")
        before_existed = bool(manifest["before_existed"])
        before_path = snapshot_dir / "before.bin"
        if before_existed:
            if not before_path.is_file():
                raise CapabilityDenied("compensation before image is missing")
            before_bytes = before_path.read_bytes()
        else:
            if before_path.exists():
                raise CapabilityDenied("unexpected compensation before image")
            before_bytes = b""
        if _sha256(before_bytes) != manifest["before_sha256"]:
            raise CapabilityDenied("compensation before image digest mismatch")
        return manifest, manifest_sha256, str(state), before_bytes

    def _write_snapshot_state(self, snapshot_dir: Path, state: str) -> None:
        self._atomic_write(
            snapshot_dir / "state.json",
            _canonical_json_bytes({"state": state}),
        )

    @staticmethod
    def _write_new_file(path: Path, value: bytes) -> None:
        with path.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _atomic_write(path: Path, value: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
        temp_path = Path(raw_temp)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            _fsync_directory(path.parent)
        finally:
            temp_path.unlink(missing_ok=True)

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
        report = {
            "schema_version": "test-report.v1",
            "action_key_sha256": _sha256(action_key.encode("utf-8")),
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        output = _canonical_json_bytes(report)
        digest = _sha256(output)
        artifact = self.artifacts / digest
        if not artifact.exists():
            artifact.write_bytes(output)
        return {"exit_code": result.returncode, "artifact_ids": (f"artifact:{digest}",), "digest": digest}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _intent_fingerprint(action: ActionContract) -> str:
    return _sha256(
        _canonical_json_bytes(
            {
                "tenant_id": action.tenant_id,
                "workspace_id": action.workspace_id,
                "principal_id": action.principal_id,
                "run_id": action.run_id,
                "node_id": action.node_id,
                "capability_id": action.capability_id,
                "capability_version": action.capability_version,
                "arguments_json": action.arguments_json,
                "policy_version": action.policy_version,
                "expected_outcome_id": action.expected_outcome_id,
            }
        )
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
