from __future__ import annotations

from collections.abc import Callable
from enum import Enum
import hashlib
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

from agent_os_contracts import SelfDevelopmentWorkSpec, content_digest

_MAX_COMPLETE_REPLACEMENT_CHARACTERS = 20_000


class SelfDevelopmentOrganBlocked(RuntimeError):
    """Fail-closed admission or drift error for the SELFDEV organ."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class SelfDevelopmentAgentLoopState(str, Enum):
    COMPLETED = "COMPLETED"
    WAITING_APPROVAL = "WAITING_APPROVAL"


class SelfDevelopmentOrgan:
    """Admit one exact linked-worktree Task into the governed execution spine."""

    def __init__(
        self,
        *,
        workspace: Path,
        execute_task: Callable[[str, dict[str, Any], Any, Any], None],
        validate_task: Callable[[str, SelfDevelopmentWorkSpec], None] | None = None,
        execute_agent_loop: Callable[[str, SelfDevelopmentWorkSpec, Any, Any], SelfDevelopmentAgentLoopState] | None = None,
        has_persisted_effects: Callable[[str], bool] | None = None,
        fail_agent_loop: Callable[[str, BaseException, Any], None] | None = None,
    ) -> None:
        self._workspace = Path(workspace).resolve()
        self._execute_task = execute_task
        self._validate_task = validate_task or (lambda _task_id, _spec: None)
        self._execute_agent_loop = execute_agent_loop
        self._has_persisted_effects = has_persisted_effects or (
            lambda _task_id: False
        )
        self._fail_agent_loop = fail_agent_loop

    def __call__(
        self,
        task_id: str,
        spec: SelfDevelopmentWorkSpec,
        assert_current: Callable[[str], None],
        execute_effect: Any,
    ) -> None:
        precise_resume = (
            spec.edit_mode == "agent_loop_precise"
            and self._has_persisted_effects(task_id)
        )
        self._assert_exact_workspace(spec, require_clean=not precise_resume)
        self._assert_verifier_bindings(spec)
        if precise_resume:
            self._assert_only_target_changed(spec)
        self._assert_targets_admitted(spec)
        self._validate_task(task_id, spec)
        assert_current("before_selfdev_execution")

        def assert_selfdev_current(phase: str) -> None:
            assert_current(phase)
            self._assert_verifier_bindings(spec)
            if phase in {
                "before_outcome_evaluation",
                "before_run_finalization",
            }:
                self._assert_exact_workspace(spec, require_clean=False)
                self._assert_only_target_changed(spec)

        execution_envelope: dict[str, Any] = {
            "repository_head": spec.repository_head,
            "isolated_branch": spec.isolated_branch,
            "allowed_write_path": spec.target_path,
            "verifier_command": spec.verifier_command,
            "verifier_bindings": [
                binding.model_dump(mode="json")
                for binding in spec.verifier_bindings
            ],
            "verifier_binding_digest": content_digest(
                {
                    "verifier_bindings": [
                        binding.model_dump(mode="json")
                        for binding in spec.verifier_bindings
                    ]
                }
            ),
            "rollback_strategy": spec.rollback_strategy,
            "prohibited_effects": (
                "main",
                "master",
                "release",
                "commit",
                "push",
                "merge",
            ),
        }
        if spec.edit_mode == "agent_loop_precise":
            execution_envelope["allowed_write_paths"] = spec.allowed_write_paths
            execution_envelope["edit_mode"] = spec.edit_mode
        if spec.edit_mode == "agent_loop_precise":
            if self._execute_agent_loop is None:
                raise SelfDevelopmentOrganBlocked(
                    "SELFDEV_AGENT_LOOP_NOT_BOUND",
                    "precise SELFDEV requires the existing-Task AgentLoop organ",
                )
            try:
                state = self._execute_agent_loop(
                    task_id,
                    spec,
                    assert_selfdev_current,
                    execute_effect,
                )
            except BaseException as exc:
                if self._fail_agent_loop is not None:
                    self._fail_agent_loop(task_id, exc, execute_effect)
                raise
            self._assert_exact_workspace(spec, require_clean=False)
            self._assert_only_target_changed(spec)
            if state is SelfDevelopmentAgentLoopState.WAITING_APPROVAL:
                return
            if state is not SelfDevelopmentAgentLoopState.COMPLETED:
                raise SelfDevelopmentOrganBlocked(
                    "SELFDEV_AGENT_LOOP_STOPPED",
                    "precise AgentLoop did not reach its verification handoff",
                )
        self._execute_task(
            task_id,
            {
                "target_path": spec.target_path,
                "test_command": spec.verifier_command,
                "selfdev_execution_envelope": execution_envelope,
            },
            assert_selfdev_current,
            execute_effect,
        )
        assert_current("after_selfdev_execution")
        self._assert_exact_workspace(spec, require_clean=False)
        self._assert_only_target_changed(spec)

    def _assert_verifier_bindings(self, spec: SelfDevelopmentWorkSpec) -> None:
        if not spec.verifier_bindings:
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_VERIFIER_UNBOUND",
                "SELFDEV execution requires an admission-sealed Product oracle",
            )
        paths = tuple(binding.path for binding in spec.verifier_bindings)
        if len(set(paths)) != len(paths) or set(paths) & set(spec.allowed_write_paths):
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_VERIFIER_BINDING_INVALID",
                "verifier paths must be unique and outside the SELFDEV write set",
            )
        for binding in spec.verifier_bindings:
            tree = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self._workspace),
                    "ls-tree",
                    spec.repository_head,
                    "--",
                    binding.path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            records = tuple(line for line in tree.stdout.splitlines() if line)
            if tree.returncode != 0 or len(records) != 1 or "\t" not in records[0]:
                raise SelfDevelopmentOrganBlocked(
                    "SELFDEV_VERIFIER_BASE_DRIFT",
                    f"verifier base blob is unavailable: {binding.path}",
                )
            metadata, recorded_path = records[0].split("\t", 1)
            parts = metadata.split()
            if (
                len(parts) != 3
                or parts[0] not in {"100644", "100755"}
                or parts[1] != "blob"
                or recorded_path != binding.path
            ):
                raise SelfDevelopmentOrganBlocked(
                    "SELFDEV_VERIFIER_BASE_DRIFT",
                    f"verifier base object is not a regular blob: {binding.path}",
                )
            blob = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self._workspace),
                    "cat-file",
                    "blob",
                    parts[2],
                ],
                check=False,
                capture_output=True,
            )
            oracle = self._workspace / binding.path
            if (
                blob.returncode != 0
                or hashlib.sha256(blob.stdout).hexdigest()
                != binding.base_blob_sha256
                or not oracle.is_file()
                or oracle.is_symlink()
                or hashlib.sha256(oracle.read_bytes()).hexdigest()
                != binding.base_blob_sha256
            ):
                raise SelfDevelopmentOrganBlocked(
                    "SELFDEV_VERIFIER_WORKTREE_DRIFT",
                    f"verifier bytes differ from the sealed base blob: {binding.path}",
                )

    def _assert_exact_workspace(
        self,
        spec: SelfDevelopmentWorkSpec,
        *,
        require_clean: bool,
    ) -> None:
        git_marker = self._workspace / ".git"
        if not git_marker.is_file() or git_marker.is_symlink():
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_WORKTREE_NOT_ISOLATED",
                "workspace must be a linked Git worktree, not a primary checkout",
            )
        top_level = self._git("rev-parse", "--show-toplevel")
        if Path(top_level).resolve() != self._workspace:
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_WORKTREE_SCOPE_MISMATCH",
                "Git top-level does not match the admitted workspace",
            )
        branch = self._git("symbolic-ref", "--quiet", "--short", "HEAD")
        if branch != spec.isolated_branch:
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_BRANCH_MISMATCH",
                "current branch does not match the persisted isolated branch",
            )
        head = self._git("rev-parse", "HEAD")
        if head != spec.repository_head:
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_HEAD_MISMATCH",
                "current HEAD does not match the persisted repository head",
            )
        if require_clean and self._git_status_paths():
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_WORKTREE_DIRTY",
                "admitted worktree must be clean before SELFDEV execution",
            )

    def _assert_targets_admitted(self, spec: SelfDevelopmentWorkSpec) -> None:
        for relative_path in spec.allowed_write_paths:
            target = self._workspace / relative_path
            if not target.is_file() or target.is_symlink():
                raise SelfDevelopmentOrganBlocked(
                    "SELFDEV_TARGET_UNSAFE",
                    "SELFDEV requires existing non-symlink write targets",
                )
            try:
                content = target.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise SelfDevelopmentOrganBlocked(
                    "SELFDEV_TARGET_UNSAFE",
                    "targets must be readable UTF-8 text",
                ) from exc
            if (
                spec.edit_mode == "complete_replacement"
                and len(content) > _MAX_COMPLETE_REPLACEMENT_CHARACTERS
            ):
                raise SelfDevelopmentOrganBlocked(
                    "SELFDEV_TARGET_TOO_LARGE",
                    "complete-replacement route is limited to fully provider-visible files",
                )

    def _assert_only_target_changed(self, spec: SelfDevelopmentWorkSpec) -> None:
        changed = self._git_status_paths()
        if changed - set(spec.allowed_write_paths):
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_SCOPE_DRIFT",
                "SELFDEV execution changed a path outside its persisted target",
            )

    def _git_status_paths(self) -> set[str]:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(self._workspace),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            check=False,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_GIT_IDENTITY_UNAVAILABLE",
                "workspace change scope cannot be proven",
            )
        paths: set[str] = set()
        entries = completed.stdout.split(b"\0")
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if not entry:
                continue
            decoded = entry.decode("utf-8", errors="strict")
            status = decoded[:2]
            path = decoded[3:]
            paths.add(path)
            if status[0] in {"R", "C"} and index < len(entries):
                paths.add(entries[index].decode("utf-8", errors="strict"))
                index += 1
        operational_paths = {
            "agent-os.sqlite3",
            "agent-os.sqlite3-shm",
            "agent-os.sqlite3-wal",
            "agent-os.sqlite3-journal",
            "agent-os.sqlite3.loop.lock",
            "agent-os.sqlite3.collaboration",
            "agent-os.sqlite3.collaboration.lock",
        }
        return {
            path
            for path in paths
            if path not in operational_paths
            and not path.startswith(".agent-os-artifacts/")
            and not path.startswith(".agent_os/")
        }

    def _git(self, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self._workspace), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        value = completed.stdout.strip()
        if completed.returncode != 0 or not value:
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_GIT_IDENTITY_UNAVAILABLE",
                "workspace Git identity cannot be proven",
            )
        return value


def inspect_selfdev_workspace(
    workspace: Path,
    spec: SelfDevelopmentWorkSpec,
) -> set[str]:
    """Reuse the execution organ's exact identity, target, and -z scope proof."""

    def unreachable_execute(
        _task_id: str,
        _inputs: dict[str, Any],
        _assert_current: Any,
        _execute_effect: Any,
    ) -> None:
        raise AssertionError("workspace inspection cannot execute a Task")

    inspector = SelfDevelopmentOrgan(
        workspace=workspace,
        execute_task=unreachable_execute,
    )
    inspector._assert_exact_workspace(spec, require_clean=False)
    inspector._assert_targets_admitted(spec)
    _reject_special_workspace_nodes(inspector._workspace)
    return inspector._git_status_paths()


def _reject_special_workspace_nodes(workspace: Path) -> None:
    pending = [workspace]
    visited = 0
    max_nodes = 100_000
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    visited += 1
                    if visited > max_nodes:
                        raise SelfDevelopmentOrganBlocked(
                            "SELFDEV_WORKSPACE_SCAN_BUDGET_EXCEEDED",
                            "workspace special-node scan exceeded its fixed budget",
                        )
                    try:
                        mode = entry.stat(follow_symlinks=False).st_mode
                    except OSError as exc:
                        raise SelfDevelopmentOrganBlocked(
                            "SELFDEV_WORKSPACE_SCAN_FAILED",
                            "workspace node type changed during inspection",
                        ) from exc
                    if stat.S_ISDIR(mode):
                        pending.append(Path(entry.path))
                    elif not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
                        raise SelfDevelopmentOrganBlocked(
                            "SELFDEV_WORKSPACE_SPECIAL_NODE",
                            f"workspace contains unsupported special node: {entry.name!r}",
                        )
        except SelfDevelopmentOrganBlocked:
            raise
        except OSError as exc:
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_WORKSPACE_SCAN_FAILED",
                "workspace node iteration cannot be proven",
            ) from exc
