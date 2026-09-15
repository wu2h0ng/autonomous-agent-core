from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_os_contracts import (
    ActionContract,
    CapabilitySpec,
    ReceiptStatus,
    SideEffectGuarantee,
    content_digest,
)
from agent_os_core import (
    CapabilityDenied,
    CapabilityEffect,
    CapabilityResult,
    DurableActionOutcomeRepository,
    ExecutionLease,
)

from .dangerous_command import require_safe_shell_command

# OS-SANDBOX-0: execution isolation is an OS-level confinement below the
# permit/approval spine. It never substitutes for approval and is never an
# input to the policy kernel (design docs live in the portfolio repo at
# docs/agent-cli/CP-AB-OS-SANDBOX-0-*.md and OS-SANDBOX-0-RESULT-*.md).
EXECUTION_ISOLATION_TRUSTED_WORKSPACE = "trusted_workspace_only"
EXECUTION_ISOLATION_SANDBOXED = "sandboxed"
_EXECUTION_ISOLATION_VALUES = (
    EXECUTION_ISOLATION_TRUSTED_WORKSPACE,
    EXECUTION_ISOLATION_SANDBOXED,
)

_ALLOWLISTED_TEST_COMMANDS = frozenset(
    {"pytest", "python -m pytest", "python3 -m pytest"}
)

# Read prefixes denied even though file-read* is otherwise broad, then
# selectively re-allowed for the workspace and runtime interpreter.
_DENIED_READ_PREFIXES = (
    "/Users",
    "/Volumes",
    "/Network",
    "/private/tmp",
    "/private/var/folders",
)


def _sandbox_read_roots(root: Path) -> tuple[Path, ...]:
    """Interpreter/runtime/tooling roots the shell needs to read to run.

    Mirrors the SELFDEV verifier profile (:1180): workspace, active + base
    interpreter prefixes, site-packages and PATH directories, so allowlisted
    ``pytest``/``git``/``ruff`` can resolve and execute. Roots that would
    re-open the denied read surface (the filesystem root, the home directory,
    or an ancestor of a denied read prefix) are dropped, except the workspace
    itself.
    """

    overbroad: set[Path] = {Path("/")}
    for probe in (Path.home(), *(Path(value) for value in _DENIED_READ_PREFIXES)):
        try:
            resolved_probe = probe.resolve()
        except OSError:
            resolved_probe = probe
        overbroad.add(resolved_probe)
        overbroad.update(resolved_probe.parents)

    roots: list[Path] = [root]
    for candidate in (sys.prefix, sys.base_prefix):
        if candidate:
            roots.append(Path(candidate))
    roots.append(Path(sys.executable).resolve().parent.parent)
    for entry in sys.path:
        if entry.endswith("site-packages"):
            roots.append(Path(entry))
    for raw in os.environ.get("PATH", "").split(os.pathsep):
        if not raw:
            continue
        candidate = Path(raw)
        if candidate.is_dir():
            roots.append(candidate)
    resolved_roots: list[Path] = []
    for candidate in roots:
        try:
            value = candidate.resolve()
        except OSError:
            continue
        if value != root.resolve() and value in overbroad:
            continue
        if value not in resolved_roots:
            resolved_roots.append(value)
    return tuple(resolved_roots)


def _assert_seatbelt_paths(paths: tuple[str, ...]) -> None:
    """Reject profile path interpolation that could break/inject the S-expression."""

    for value in paths:
        if '"' in value or "\\" in value or "\n" in value:
            raise CapabilityDenied("sandboxed execution path contains unsafe characters")


def _workspace_seatbelt_profile(
    root: Path,
    sandbox_root: Path,
    sandbox_tmp: Path,
) -> str:
    """Build the Seatbelt profile for a sandboxed shell/test run.

    Emission order is fixed and later-rules-override (Seatbelt semantics):
    deny default + network, then broad read with /Users|/Volumes|/Network|
    /private/{tmp,var/folders} denied, then re-allow workspace + runtime, then
    confine writes to the workspace and the redirected HOME/TMPDIR. The rule
    digest is computed over this exact text (with only the volatile sandbox
    root normalised), so it binds the real workspace and runtime read set.
    """

    workspace = str(root)
    sandbox = str(sandbox_root)
    tmp = str(sandbox_tmp)
    read_roots = tuple(str(value) for value in _sandbox_read_roots(root))
    _assert_seatbelt_paths((workspace, sandbox, tmp, *read_roots))
    reads = "".join(f' (subpath "{value}")' for value in read_roots)
    denied = " ".join(f'(subpath "{prefix}")' for prefix in _DENIED_READ_PREFIXES)
    return "\n".join(
        (
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            "(allow sysctl-read)",
            "(deny network*)",
            '(deny process-exec* (literal "/usr/bin/sudo"))',
            "(allow file-read*)",
            f"(deny file-read* {denied})",
            f'(allow file-read* (subpath "{workspace}") (subpath "{sandbox}"){reads})',
            (
                "(allow file-write* "
                f'(subpath "{workspace}") '
                f'(subpath "{sandbox}") '
                f'(subpath "{tmp}") '
                '(literal "/dev/null") '
                '(literal "/dev/stdout") '
                '(literal "/dev/stderr") '
                '(literal "/dev/dtracehelper"))'
            ),
        )
    )


def _profile_digest(profile: str, sandbox_root: Path) -> str:
    """Hash the dispatched profile with only the volatile sandbox root masked.

    Binds the executed workspace root, runtime read set and rule order while
    staying stable across runs (each run uses a fresh temp sandbox root).
    """

    return _sha256(
        profile.replace(str(sandbox_root), "__SANDBOX_ROOT__").encode("utf-8")
    )


class DeveloperWorkspaceAdapter:
    """Allowlisted repository capabilities on a disposable, path-confined workspace."""

    def __init__(
        self,
        root: str | Path,
        artifacts: str | Path | None = None,
        idempotency_store: object | None = None,
        shell_allowlist: tuple[str, ...] | None = None,
        execution_isolation: str = EXECUTION_ISOLATION_TRUSTED_WORKSPACE,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts = Path(artifacts or self.root / ".agent-os-artifacts").resolve()
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self._idempotency_store = idempotency_store
        self._shell_allowlist = (
            tuple(shell_allowlist)
            if shell_allowlist is not None
            else ("pytest", "python -m pytest", "python3 -m pytest")
        )
        self.set_execution_isolation(execution_isolation)

    def set_shell_allowlist(self, allowlist: tuple[str, ...]) -> None:
        self._shell_allowlist = tuple(allowlist)

    def set_execution_isolation(self, isolation: str) -> None:
        if isolation not in _EXECUTION_ISOLATION_VALUES:
            raise ValueError(
                "execution_isolation must be one of "
                + ", ".join(_EXECUTION_ISOLATION_VALUES)
            )
        self._execution_isolation = isolation

    def execution_isolation(self) -> str:
        return self._execution_isolation

    def outcomes(self) -> DurableActionOutcomeRepository | None:
        """Durable reservation/outcome repository (ADR-0059 connector contract)."""

        if self._idempotency_store is None:
            return None
        return DurableActionOutcomeRepository(self._idempotency_store)

    def replay(self, action: ActionContract) -> CapabilityResult | None:
        outcomes = self.outcomes()
        if outcomes is None:
            return None
        return outcomes.replay(action)

    def preflight(
        self,
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> None:
        """Deterministic deny before any reservation (ADR-0059 P1)."""

        self._preflight(capability_id, args, action_key)

    def acquire_execution_lease(
        self, action: ActionContract, owner: str
    ) -> ExecutionLease:
        outcomes = self.outcomes()
        if outcomes is None:
            raise CapabilityDenied(
                "durable idempotency store is required for execution lease"
            )
        return outcomes.acquire_execution_lease(action, owner)

    def release_execution_lease(self, lease: ExecutionLease) -> bool:
        outcomes = self.outcomes()
        if outcomes is None:
            raise CapabilityDenied(
                "durable idempotency store is required for execution lease"
            )
        return outcomes.release_execution_lease(lease)

    def reconcile_effect(
        self,
        action: ActionContract,
        result: CapabilityResult,
    ) -> None:
        """Read current local evidence without altering or replaying history."""

        args = json.loads(action.arguments_json)
        if not isinstance(args, dict):
            raise CapabilityDenied("capability arguments must be an object")
        if (
            result.receipt.status is ReceiptStatus.SUCCEEDED
            and action.capability_id in {"workspace.apply_patch", "workspace.edit"}
        ):
            self._validate_cached_patch_effect(args, result.output)
        elif (
            result.receipt.status is ReceiptStatus.COMPENSATED
            and action.capability_id == "workspace.compensate_patch"
        ):
            self._validate_cached_compensation_effect(args, result.output)

    def _preflight(
        self,
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> None:
        if capability_id == "workspace.read":
            path = self._safe_path(str(args.get("path", "")))
            if not path.is_file():
                raise FileNotFoundError(str(args.get("path")))
            return
        if capability_id == "workspace.apply_patch":
            self._preflight_apply_patch(args, action_key)
            return
        if capability_id == "workspace.edit":
            patch_args = self._edit_patch_args(args)
            self._preflight_apply_patch(patch_args, action_key)
            return
        if capability_id == "workspace.search":
            self._preflight_search(args)
            return
        if capability_id == "workspace.shell":
            self._preflight_shell(args)
            return
        if capability_id == "workspace.compensate_patch":
            self._preflight_compensate_patch(args)
            return
        if capability_id == "workspace.run_tests":
            self._preflight_run_tests(args)
            return
        if capability_id == "session.todo_write":
            _normalize_todos(args)
            return
        if capability_id == "artifact.write":
            return
        raise CapabilityDenied(f"capability is not registered: {capability_id}")

    def _preflight_apply_patch(
        self,
        args: dict[str, object],
        action_key: str,
    ) -> None:
        path = self._safe_path(str(args.get("path", "")))
        content_bytes = str(args.get("content", "")).encode("utf-8")
        relative_path = str(path.relative_to(self.root))
        key_digest = _sha256(action_key.encode("utf-8"))
        compensation_ref = f"compensation:{key_digest}"
        snapshot_dir = self.artifacts / "compensation" / key_digest
        applied_sha256 = _sha256(content_bytes)
        if snapshot_dir.exists():
            manifest, _, state, _ = self._load_snapshot(compensation_ref)
            if state == "COMPENSATED":
                raise CapabilityDenied("patch was already compensated and cannot replay")
            if manifest["action_key_sha256"] != key_digest:
                raise CapabilityDenied("snapshot action key binding mismatch")
            if manifest["relative_path"] != relative_path:
                raise CapabilityDenied("snapshot path binding mismatch")
            if manifest["applied_sha256"] != applied_sha256:
                raise CapabilityDenied(
                    "idempotency key reused for different patch content"
                )
            current_matches_applied = (
                path.exists() and _sha256(path.read_bytes()) == applied_sha256
            )
            before_existed = bool(manifest["before_existed"])
            current_matches_before = (
                path.exists()
                and before_existed
                and _sha256(path.read_bytes()) == manifest["before_sha256"]
            ) or (not path.exists() and not before_existed)
            if state == "PREPARED" and not (
                current_matches_before or current_matches_applied
            ):
                raise CapabilityDenied(
                    "workspace changed outside the prepared patch replay"
                )
            if state == "APPLIED" and not current_matches_applied:
                raise CapabilityDenied(
                    "APPLIED snapshot no longer matches the patch effect"
                )
            return
        expected = args.get("expected_sha256")
        before_existed = path.exists()
        before_bytes = path.read_bytes() if before_existed else b""
        actual = _sha256(before_bytes) if before_existed else None
        if expected is not None and expected != actual:
            raise CapabilityDenied("workspace changed since proposal")

    def _preflight_compensate_patch(self, args: dict[str, object]) -> None:
        relative_path = str(args.get("path", ""))
        target = self._safe_path(relative_path)
        action_key = str(args.get("original_action_key", ""))
        compensation_ref = str(args.get("compensation_ref", ""))
        expected_manifest_sha256 = str(args.get("manifest_sha256", ""))
        manifest, _, state, _ = self._load_snapshot(
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
            return
        if state != "APPLIED":
            raise CapabilityDenied("patch snapshot is not in APPLIED state")
        if not current_is_applied and not current_is_before:
            raise CapabilityDenied("target changed after patch; compensation refused")

    def _edit_patch_args(
        self,
        args: dict[str, object],
    ) -> dict[str, object]:
        relative_path = str(args.get("path", ""))
        path = self._safe_path(relative_path)
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        old_string = str(args.get("old_string", ""))
        new_string = str(args.get("new_string", ""))
        if not old_string:
            raise CapabilityDenied("workspace.edit requires a non-empty old_string")
        if old_string == new_string:
            raise CapabilityDenied("workspace.edit old_string and new_string are identical")
        content = path.read_text(encoding="utf-8")
        occurrences = content.count(old_string)
        if occurrences != 1:
            raise CapabilityDenied(
                f"workspace.edit old_string must match exactly once (found {occurrences})"
            )
        patch_args: dict[str, object] = {
            "path": relative_path,
            "content": content.replace(old_string, new_string, 1),
        }
        if args.get("expected_sha256") is not None:
            patch_args["expected_sha256"] = args["expected_sha256"]
        return patch_args

    _SEARCH_SKIP_DIRS = frozenset({".git", ".agent-os-artifacts", "node_modules", "__pycache__", ".venv"})
    _SEARCH_MAX_RESULTS = 200
    _SEARCH_MAX_OUTPUT_CHARS = 20000

    def _preflight_search(self, args: dict[str, object]) -> None:
        mode = str(args.get("mode", ""))
        base_value = str(args.get("path", "") or ".")
        base = self.root if base_value == "." else self._safe_path(base_value)
        if mode == "ls":
            if not base.is_dir():
                raise FileNotFoundError(base_value)
            return
        if mode == "glob":
            if not str(args.get("pattern", "")):
                raise CapabilityDenied("workspace.search glob requires a pattern")
            return
        if mode == "grep":
            pattern = str(args.get("pattern", ""))
            if not pattern:
                raise CapabilityDenied("workspace.search grep requires a pattern")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise CapabilityDenied(f"invalid grep pattern: {exc}") from exc
            return
        raise CapabilityDenied(f"unsupported workspace.search mode: {mode}")

    def _preflight_shell(self, args: dict[str, object]) -> None:
        command = " ".join(str(args.get("command", "")).split())
        require_safe_shell_command(
            command, self._shell_allowlist, "command is not in the shell allowlist"
        )
        int(str(args.get("timeout_seconds", 120)))

    @staticmethod
    def _preflight_run_tests(args: dict[str, object]) -> None:
        command = str(args.get("command", ""))
        require_safe_shell_command(
            command,
            _ALLOWLISTED_TEST_COMMANDS,
            "only the allowlisted test commands are permitted",
        )
        int(str(args.get("timeout_seconds", 120)))

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
            "session.todo_write": CapabilitySpec(
                capability_id="session.todo_write",
                version="1",
                display_name="Replace session todo list",
                side_effect_guarantee=SideEffectGuarantee.TRANSACTIONAL_INTERNAL,
                idempotency_supported=True,
                cancellation_supported=True,
                compensation_supported=False,
                **common,
            ),
            "workspace.read": CapabilitySpec(
                capability_id="workspace.read",
                version="1",
                display_name="Read workspace file",
                side_effect_guarantee=SideEffectGuarantee.READ_ONLY,
                idempotency_supported=True,
                cancellation_supported=True,
                compensation_supported=False,
                **common,
            ),
            "workspace.apply_patch": CapabilitySpec(
                capability_id="workspace.apply_patch",
                version="1",
                display_name="Apply unified patch",
                side_effect_guarantee=SideEffectGuarantee.SANDBOX_COMPENSATABLE,
                idempotency_supported=True,
                cancellation_supported=True,
                compensation_supported=True,
                collaboration_required=True,
                **{**common, "risk_tier": 2},
            ),
            "workspace.run_tests": CapabilitySpec(
                capability_id="workspace.run_tests",
                version="1",
                display_name="Run allowlisted tests",
                side_effect_guarantee=SideEffectGuarantee.SANDBOX_IDEMPOTENT,
                idempotency_supported=True,
                cancellation_supported=True,
                compensation_supported=False,
                **common,
            ),
            "workspace.edit": CapabilitySpec(
                capability_id="workspace.edit",
                version="1",
                display_name="Exact string replacement edit",
                side_effect_guarantee=SideEffectGuarantee.SANDBOX_COMPENSATABLE,
                idempotency_supported=True,
                cancellation_supported=True,
                compensation_supported=True,
                collaboration_required=True,
                **{**common, "risk_tier": 2},
            ),
            "workspace.search": CapabilitySpec(
                capability_id="workspace.search",
                version="1",
                display_name="Search workspace (glob/grep/ls)",
                side_effect_guarantee=SideEffectGuarantee.READ_ONLY,
                idempotency_supported=True,
                cancellation_supported=True,
                compensation_supported=False,
                **common,
            ),
            "workspace.shell": CapabilitySpec(
                capability_id="workspace.shell",
                version="1",
                display_name="Run allowlisted shell command",
                side_effect_guarantee=SideEffectGuarantee.SANDBOX_IDEMPOTENT,
                idempotency_supported=True,
                cancellation_supported=True,
                compensation_supported=False,
                **{**common, "risk_tier": 3},
            ),
            "artifact.write": CapabilitySpec(
                capability_id="artifact.write",
                version="1",
                display_name="Write content-addressed artifact",
                side_effect_guarantee=SideEffectGuarantee.SANDBOX_IDEMPOTENT,
                idempotency_supported=True,
                cancellation_supported=True,
                compensation_supported=False,
                **common,
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
        """Physical effect execution (ADR-0059 connector contract).

        Deterministic checks already ran in preflight (before reservation).
        Any exception here propagates to the broker, which converts it to a
        typed UNKNOWN (never FAILED). No adapter-level idempotency: replay,
        reservation, and outcome authority belong to the broker's durable
        outcome repository.
        """

        args = json.loads(action.arguments_json)
        if not isinstance(args, dict):
            raise CapabilityDenied("capability arguments must be an object")
        output = self._dispatch(action.capability_id, args, action.idempotency_key)
        return CapabilityEffect(status=ReceiptStatus.SUCCEEDED, output=output)

    def _dispatch(
        self, capability_id: str, args: dict[str, object], action_key: str
    ) -> dict[str, object]:
        if capability_id == "workspace.read":
            path = self._safe_path(str(args.get("path", "")))
            if not path.is_file():
                raise FileNotFoundError(str(args.get("path")))
            content = path.read_text(encoding="utf-8")
            return {
                "path": str(path.relative_to(self.root)),
                "content": content,
                "sha256": _sha256(content.encode()),
            }
        if capability_id == "workspace.apply_patch":
            return self._apply_patch(args, action_key)
        if capability_id == "workspace.edit":
            return self._edit(args, action_key)
        if capability_id == "workspace.search":
            return self._search(args)
        if capability_id == "workspace.shell":
            return self._shell(args, action_key)
        if capability_id == "workspace.compensate_patch":
            return self._compensate_patch(args)
        if capability_id == "workspace.run_tests":
            return self._run_tests(args, action_key)
        if capability_id == "session.todo_write":
            # Session scratchpad: no physical effect. Durable truth is the
            # PROPOSED/RECEIPT event chain; the output is the normalized
            # full-replace list (GC-SESSION-TODO-WRITE).
            todos = _normalize_todos(args)
            return {"ok": True, "todos": todos, "count": len(todos)}
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
        first = Path(value).parts[0] if Path(value).parts else ""
        if first in {".agent-os-artifacts", ".agent_os"}:
            raise CapabilityDenied("workspace agent state is reserved")
        raw = self.root / value
        if any(
            part.is_symlink()
            for part in (self.root, *raw.parents, raw)
            if part.exists() or part.is_symlink()
        ):
            raise CapabilityDenied("symlink paths are forbidden")
        candidate = raw.resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise CapabilityDenied("path escapes workspace")
        if candidate == self.artifacts or self.artifacts in candidate.parents:
            raise CapabilityDenied("workspace agent state is reserved")
        agent_os_dir = (self.root / ".agent_os").resolve()
        if candidate == agent_os_dir or agent_os_dir in candidate.parents:
            raise CapabilityDenied("workspace agent state is reserved")
        return candidate

    def _apply_patch(
        self, args: dict[str, object], action_key: str
    ) -> dict[str, object]:
        path = self._safe_path(str(args.get("path", "")))
        content = str(args.get("content", ""))
        content_bytes = content.encode("utf-8")
        relative_path = str(path.relative_to(self.root))
        key_digest = _sha256(action_key.encode("utf-8"))
        compensation_ref = f"compensation:{key_digest}"
        snapshot_dir = self.artifacts / "compensation" / key_digest
        applied_sha256 = _sha256(content_bytes)
        if snapshot_dir.exists():
            manifest, manifest_sha256, state, _ = self._load_snapshot(compensation_ref)
            if state == "COMPENSATED":
                raise CapabilityDenied(
                    "patch was already compensated and cannot replay"
                )
            if manifest["action_key_sha256"] != key_digest:
                raise CapabilityDenied("snapshot action key binding mismatch")
            if manifest["relative_path"] != relative_path:
                raise CapabilityDenied("snapshot path binding mismatch")
            if manifest["applied_sha256"] != applied_sha256:
                raise CapabilityDenied(
                    "idempotency key reused for different patch content"
                )
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
        descriptor, raw_temp = tempfile.mkstemp(
            prefix=f".{path.name}-", dir=path.parent
        )
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

    def _edit(self, args: dict[str, object], action_key: str) -> dict[str, object]:
        relative_path = str(args.get("path", ""))
        path = self._safe_path(relative_path)
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        old_string = str(args.get("old_string", ""))
        new_string = str(args.get("new_string", ""))
        if not old_string:
            raise CapabilityDenied("workspace.edit requires a non-empty old_string")
        if old_string == new_string:
            raise CapabilityDenied(
                "workspace.edit old_string and new_string are identical"
            )
        content = path.read_text(encoding="utf-8")
        occurrences = content.count(old_string)
        if occurrences != 1:
            raise CapabilityDenied(
                f"workspace.edit old_string must match exactly once (found {occurrences})"
            )
        patch_args: dict[str, object] = {
            "path": relative_path,
            "content": content.replace(old_string, new_string, 1),
        }
        if args.get("expected_sha256") is not None:
            patch_args["expected_sha256"] = args["expected_sha256"]
        return self._apply_patch(patch_args, action_key)

    _SEARCH_SKIP_DIRS = frozenset(
        {
            ".git",
            ".agent-os-artifacts",
            ".agent_os",
            "node_modules",
            "__pycache__",
            ".venv",
        }
    )
    _SEARCH_MAX_RESULTS = 200
    _SEARCH_MAX_OUTPUT_CHARS = 20000

    def _search(self, args: dict[str, object]) -> dict[str, object]:
        mode = str(args.get("mode", ""))
        base_value = str(args.get("path", "") or ".")
        base = self.root if base_value == "." else self._safe_path(base_value)
        if mode == "ls":
            if not base.is_dir():
                raise FileNotFoundError(base_value)
            entries = sorted(
                entry.name + ("/" if entry.is_dir() else "")
                for entry in base.iterdir()
                if entry.name not in self._SEARCH_SKIP_DIRS
            )
            truncated = len(entries) > self._SEARCH_MAX_RESULTS
            return {
                "mode": "ls",
                "entries": entries[: self._SEARCH_MAX_RESULTS],
                "truncated": truncated,
            }
        if mode == "glob":
            pattern = str(args.get("pattern", ""))
            if not pattern:
                raise CapabilityDenied("workspace.search glob requires a pattern")
            matches: list[str] = []
            for candidate in sorted(self.root.rglob("*")):
                if any(
                    part in self._SEARCH_SKIP_DIRS for part in candidate.parts
                ) or not self._is_safe_search_candidate(candidate):
                    continue
                relative = str(candidate.relative_to(self.root))
                if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(
                    candidate.name, pattern
                ):
                    matches.append(relative + ("/" if candidate.is_dir() else ""))
                if len(matches) >= self._SEARCH_MAX_RESULTS:
                    break
            truncated = len(matches) >= self._SEARCH_MAX_RESULTS
            return {"mode": "glob", "matches": matches, "truncated": truncated}
        if mode == "grep":
            pattern = str(args.get("pattern", ""))
            if not pattern:
                raise CapabilityDenied("workspace.search grep requires a pattern")
            try:
                regex = re.compile(pattern)
            except re.error as exc:
                raise CapabilityDenied(f"invalid grep pattern: {exc}") from exc
            matches = []
            scanned = 0
            truncated = False
            for candidate in sorted(base.rglob("*") if base.is_dir() else [base]):
                if any(
                    part in self._SEARCH_SKIP_DIRS for part in candidate.parts
                ) or not self._is_safe_search_candidate(candidate):
                    continue
                if not candidate.is_file() or candidate.stat().st_size > 1_000_000:
                    continue
                scanned += 1
                if scanned > 1000:
                    truncated = True
                    break
                try:
                    text = candidate.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if regex.search(line):
                        matches.append(
                            f"{candidate.relative_to(self.root)}:{lineno}:{line[:500]}"
                        )
                        if len(matches) >= self._SEARCH_MAX_RESULTS:
                            truncated = True
                            break
                if truncated:
                    break
            output = matches
            total = 0
            for index, line in enumerate(matches):
                total += len(line) + 1
                if total > self._SEARCH_MAX_OUTPUT_CHARS:
                    output = matches[:index]
                    truncated = True
                    break
            return {"mode": "grep", "matches": output, "truncated": truncated}
        raise CapabilityDenied(f"unsupported workspace.search mode: {mode}")

    def _is_safe_search_candidate(self, candidate: Path) -> bool:
        if candidate.is_symlink():
            return False
        try:
            resolved = candidate.resolve()
        except OSError:
            return False
        if resolved != self.root and self.root not in resolved.parents:
            return False
        return resolved != self.artifacts and self.artifacts not in resolved.parents

    def _execute_confined(
        self,
        argv: list[str],
        timeout: int,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        """Run ``argv`` inside the configured execution isolation.

        ``trusted_workspace_only`` (default) preserves the prior in-process
        behaviour. ``sandboxed`` wraps the command in the OS filesystem
        sandbox; if the OS sandbox is unavailable it fails closed with
        ``CapabilityDenied`` (never silently falls back to the weaker mode).
        """

        if self._execution_isolation == EXECUTION_ISOLATION_TRUSTED_WORKSPACE:
            result = subprocess.run(
                argv,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=_subprocess_env(),
            )
            return result, {
                "execution_isolation": EXECUTION_ISOLATION_TRUSTED_WORKSPACE
            }
        if sys.platform != "darwin":
            raise CapabilityDenied(
                "sandboxed execution isolation is only available on macOS"
            )
        sandbox_exec = shutil.which("sandbox-exec")
        if sandbox_exec is None:
            raise CapabilityDenied(
                "sandboxed execution isolation requires an OS filesystem sandbox"
            )
        with tempfile.TemporaryDirectory(prefix="agent-os-shell-sandbox-") as raw:
            sandbox_root = Path(raw).resolve()
            sandbox_tmp = sandbox_root / "tmp"
            sandbox_home = sandbox_root / "home"
            sandbox_tmp.mkdir()
            sandbox_home.mkdir()
            profile = _workspace_seatbelt_profile(self.root, sandbox_root, sandbox_tmp)
            profile_digest = _profile_digest(profile, sandbox_root)
            environment = _subprocess_env()
            environment["HOME"] = str(sandbox_home)
            environment["TMPDIR"] = str(sandbox_tmp)
            environment["TEMP"] = str(sandbox_tmp)
            environment["TMP"] = str(sandbox_tmp)
            result = subprocess.run(
                [sandbox_exec, "-p", profile, *argv],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=environment,
            )
            return result, {
                "execution_isolation": EXECUTION_ISOLATION_SANDBOXED,
                "sandbox_profile_sha256": profile_digest,
            }

    def _shell(self, args: dict[str, object], action_key: str) -> dict[str, object]:
        command = " ".join(str(args.get("command", "")).split())
        # Same guard as the preflight: reaching execution without it must not bypass
        # the classifier (an allowlisted dangerous command is still refused here).
        require_safe_shell_command(
            command, self._shell_allowlist, "command is not in the shell allowlist"
        )
        timeout = min(int(str(args.get("timeout_seconds", 120))), 300)
        result, isolation = self._execute_confined(command.split(), timeout)
        report = {
            "schema_version": "shell-report.v1",
            "action_key_sha256": _sha256(action_key.encode("utf-8")),
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            **isolation,
        }
        output = _canonical_json_bytes(report)
        digest = _sha256(output)
        artifact = self.artifacts / digest
        if not artifact.exists():
            artifact.write_bytes(output)
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
            "artifact_ids": (f"artifact:{digest}",),
            "digest": digest,
        }

    def _run_tests(self, args: dict[str, object], action_key: str) -> dict[str, object]:
        command = str(args.get("command", ""))
        require_safe_shell_command(
            command,
            _ALLOWLISTED_TEST_COMMANDS,
            "only the allowlisted test commands are permitted",
        )
        timeout = min(int(str(args.get("timeout_seconds", 120))), 120)
        snapshot = args.get("selfdev_verification_snapshot")
        verifier_bindings: list[dict[str, str]] | None = None
        verifier_argv: list[str] | None = None
        isolation: dict[str, object] | None = None
        if isinstance(snapshot, dict):
            (
                result,
                verifier_bindings,
                verifier_argv,
                selfdev_profile_digest,
            ) = self._run_selfdev_tests_in_mirror(
                command,
                timeout,
                snapshot,
            )
            # The SELFDEV verifier always runs inside the Seatbelt mirror; record
            # that isolation mode even though it is not the workspace profile.
            isolation = {
                "execution_isolation": EXECUTION_ISOLATION_SANDBOXED,
                "sandbox_profile_sha256": selfdev_profile_digest,
            }
        else:
            result, isolation = self._execute_confined(command.split(), timeout)
        report = {
            "schema_version": "test-report.v1",
            "action_key_sha256": _sha256(action_key.encode("utf-8")),
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        if isolation is not None:
            report.update(isolation)
        if verifier_bindings is not None and verifier_argv is not None:
            report["verifier_bindings"] = verifier_bindings
            report["verifier_binding_digest"] = content_digest(
                {"verifier_bindings": verifier_bindings}
            )
            report["argv"] = verifier_argv
        output = _canonical_json_bytes(report)
        digest = _sha256(output)
        artifact = self.artifacts / digest
        if not artifact.exists():
            artifact.write_bytes(output)
        return {
            "exit_code": result.returncode,
            "artifact_ids": (f"artifact:{digest}",),
            "digest": digest,
        }

    def _run_selfdev_tests_in_mirror(
        self,
        command: str,
        timeout: int,
        snapshot: dict[str, object],
    ) -> tuple[
        subprocess.CompletedProcess[str],
        list[dict[str, str]],
        list[str],
        str,
    ]:
        expected_head = str(snapshot.get("repository_head", ""))
        if set(snapshot) != {
            "repository_head",
            "verifier_bindings",
            "verifier_binding_digest",
        }:
            raise CapabilityDenied("SELFDEV verifier snapshot is malformed")
        raw_bindings = snapshot.get("verifier_bindings")
        if not isinstance(raw_bindings, (list, tuple)) or not 1 <= len(raw_bindings) <= 8:
            raise CapabilityDenied("SELFDEV verifier binding set is invalid")
        verifier_bindings: list[dict[str, str]] = []
        base_blobs: list[bytes] = []
        for raw_binding in raw_bindings:
            if not isinstance(raw_binding, dict) or set(raw_binding) != {
                "schema_version",
                "path",
                "base_blob_sha256",
            } or raw_binding.get("schema_version") != "1.0":
                raise CapabilityDenied("SELFDEV verifier binding is malformed")
            path = str(raw_binding["path"])
            digest = str(raw_binding["base_blob_sha256"])
            if re.fullmatch(r"tests/product/test_[A-Za-z0-9_]+\.py", path) is None:
                raise CapabilityDenied("SELFDEV verifier path is invalid")
            tree = subprocess.run(
                ["git", "-C", str(self.root), "ls-tree", expected_head, "--", path],
                capture_output=True,
                text=True,
                check=False,
            )
            records = tuple(line for line in tree.stdout.splitlines() if line)
            if tree.returncode != 0 or len(records) != 1 or "\t" not in records[0]:
                raise CapabilityDenied("SELFDEV verifier base blob is unavailable")
            metadata, recorded_path = records[0].split("\t", 1)
            parts = metadata.split()
            if (
                len(parts) != 3
                or parts[0] not in {"100644", "100755"}
                or parts[1] != "blob"
                or recorded_path != path
            ):
                raise CapabilityDenied("SELFDEV verifier base object is not a regular blob")
            blob = subprocess.run(
                ["git", "-C", str(self.root), "cat-file", "blob", parts[2]],
                capture_output=True,
                check=False,
            )
            oracle = self._safe_path(path)
            if (
                blob.returncode != 0
                or _sha256(blob.stdout) != digest
                or not oracle.is_file()
                or oracle.is_symlink()
                or _sha256(oracle.read_bytes()) != digest
            ):
                raise CapabilityDenied("SELFDEV verifier blob or worktree oracle drift")
            verifier_bindings.append(
                {
                    "schema_version": "1.0",
                    "path": path,
                    "base_blob_sha256": digest,
                }
            )
            base_blobs.append(blob.stdout)
        target_paths = tuple(binding["path"] for binding in verifier_bindings)
        if len(set(target_paths)) != len(target_paths):
            raise CapabilityDenied("SELFDEV verifier binding paths must be unique")
        if snapshot.get("verifier_binding_digest") != content_digest(
            {"verifier_bindings": verifier_bindings}
        ):
            raise CapabilityDenied("SELFDEV verifier binding digest drift")
        head = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if head.returncode != 0 or head.stdout.strip() != expected_head:
            raise CapabilityDenied("SELFDEV verifier repository HEAD drift")
        sandbox_exec = shutil.which("sandbox-exec")
        if sandbox_exec is None:
            raise CapabilityDenied("SELFDEV verifier requires an OS filesystem sandbox")
        with tempfile.TemporaryDirectory(prefix="agent-os-selfdev-verify-") as raw:
            verification_root = Path(raw).resolve()
            mirror = verification_root / "workspace"
            shutil.copytree(
                self.root,
                mirror,
                symlinks=True,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".agent_os",
                    ".agent-os-artifacts",
                    "agent-os.sqlite3*",
                    "__pycache__",
                    ".pytest_cache",
                ),
            )
            for target_path, base_blob in zip(target_paths, base_blobs, strict=True):
                mirrored_oracle = mirror / target_path
                mirrored_oracle.parent.mkdir(parents=True, exist_ok=True)
                mirrored_oracle.write_bytes(base_blob)
            sandbox_tmp = verification_root / "tmp"
            sandbox_home = verification_root / "home"
            runtime_site = verification_root / "runtime-site"
            sandbox_tmp.mkdir()
            sandbox_home.mkdir()
            source_site = next(
                (
                    Path(value)
                    for value in sys.path
                    if value.endswith("site-packages")
                    and (Path(value) / "pytest").is_dir()
                ),
                None,
            )
            if source_site is None:
                raise CapabilityDenied("SELFDEV verifier pytest runtime is unavailable")

            def ignore_runtime(_directory: str, names: list[str]) -> set[str]:
                return {
                    name
                    for name in names
                    if name.endswith(".pth")
                    or name.startswith("__editable__")
                    or name.startswith("_virtualenv")
                }

            def hardlink_or_copy(source: str, destination: str) -> str:
                try:
                    os.link(source, destination)
                    return destination
                except OSError:
                    return shutil.copy2(source, destination)

            shutil.copytree(
                source_site,
                runtime_site,
                symlinks=False,
                ignore=ignore_runtime,
                copy_function=hardlink_or_copy,
            )
            base_executable = Path(
                getattr(sys, "_base_executable", sys.executable)
            ).resolve()
            base_runtime = base_executable.parent.parent
            profile = "\n".join(
                (
                    "(version 1)",
                    "(deny default)",
                    "(allow process*)",
                    "(allow sysctl-read)",
                    "(deny network*)",
                    "(allow file-read*)",
                    '(deny file-read* (subpath "/Users") '
                    '(subpath "/Volumes") (subpath "/Network") '
                    '(subpath "/private/tmp") '
                    '(subpath "/private/var/folders"))',
                    "(allow file-read* "
                    f'(subpath "{mirror}") '
                    f'(subpath "{runtime_site}") '
                    f'(subpath "{base_runtime}") '
                    f'(subpath "{verification_root}"))',
                    "(allow file-write* "
                    f'(subpath "{sandbox_tmp}") '
                    f'(subpath "{sandbox_home}") '
                    '(literal "/dev/null"))',
                )
            )
            python_paths = (
                runtime_site,
                mirror,
                mirror / "packages" / "contracts" / "src",
                mirror / "packages" / "os_core" / "src",
                mirror / "apps",
            )
            environment = {
                "HOME": str(sandbox_home),
                "TMPDIR": str(sandbox_tmp),
                "TEMP": str(sandbox_tmp),
                "TMP": str(sandbox_tmp),
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": os.pathsep.join(str(path) for path in python_paths),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "NO_COLOR": "1",
                "LANG": os.environ.get("LANG", "C.UTF-8"),
            }
            argv = [
                sandbox_exec,
                "-p",
                profile,
                str(base_executable),
                "-S",
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-q",
                *target_paths,
            ]
            result = subprocess.run(
                argv,
                cwd=mirror,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=environment,
            )
            return (
                result,
                verifier_bindings,
                [str(value) for value in argv],
                _profile_digest(profile, verification_root),
            )


def _normalize_todos(args: dict[str, object]) -> list[dict[str, str]]:
    raw = args.get("todos")
    if set(args) != {"todos"} or not isinstance(raw, list):
        raise CapabilityDenied("todos must be an array")
    if len(raw) > 100:
        raise CapabilityDenied("todos cannot exceed 100 items")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"id", "content", "status"}:
            raise CapabilityDenied("each todo requires id, content, and status")
        identifier = item["id"]
        content = item["content"]
        status = item["status"]
        if not isinstance(identifier, str) or not isinstance(content, str):
            raise CapabilityDenied("todo id and content must be strings")
        identifier = identifier.strip()
        content = content.strip()
        if not identifier or not content:
            raise CapabilityDenied("todo id and content cannot be blank")
        if status not in ("pending", "in_progress", "done"):
            raise CapabilityDenied("invalid todo status")
        if identifier in seen:
            raise CapabilityDenied("todo ids must be unique")
        seen.add(identifier)
        result.append({"id": identifier, "content": content, "status": status})
    return result


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


def _subprocess_env() -> dict[str, str]:
    allowed = {
        "CI",
        "COLORTERM",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "PYTHONPATH",
        "SYSTEMROOT",
        "TEMP",
        "TERM",
        "TMP",
        "TMPDIR",
        "VIRTUAL_ENV",
        "WINDIR",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment["NO_COLOR"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment
