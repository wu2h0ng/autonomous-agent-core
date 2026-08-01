from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess
from typing import Any

from agent_os_contracts import SelfDevelopmentWorkSpec

_MAX_COMPLETE_REPLACEMENT_CHARACTERS = 20_000


class SelfDevelopmentOrganBlocked(RuntimeError):
    """Fail-closed admission or drift error for the SELFDEV organ."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class SelfDevelopmentOrgan:
    """Admit one exact linked-worktree Task into the governed execution spine."""

    def __init__(
        self,
        *,
        workspace: Path,
        execute_task: Callable[[str, dict[str, Any], Any, Any], None],
        validate_task: Callable[[str], None] | None = None,
    ) -> None:
        self._workspace = Path(workspace).resolve()
        self._execute_task = execute_task
        self._validate_task = validate_task or (lambda _task_id: None)

    def __call__(
        self,
        task_id: str,
        spec: SelfDevelopmentWorkSpec,
        assert_current: Callable[[str], None],
        execute_effect: Any,
    ) -> None:
        self._assert_exact_workspace(spec, require_clean=True)
        self._assert_target_admitted(spec)
        self._validate_task(task_id)
        assert_current("before_selfdev_execution")

        def assert_selfdev_current(phase: str) -> None:
            assert_current(phase)
            if phase in {
                "before_outcome_evaluation",
                "before_run_finalization",
            }:
                self._assert_exact_workspace(spec, require_clean=False)
                self._assert_only_target_changed(spec)

        self._execute_task(
            task_id,
            {
                "target_path": spec.target_path,
                "test_command": spec.verifier_command,
                "selfdev_execution_envelope": {
                    "repository_head": spec.repository_head,
                    "isolated_branch": spec.isolated_branch,
                    "allowed_write_path": spec.target_path,
                    "verifier_command": spec.verifier_command,
                    "rollback_strategy": spec.rollback_strategy,
                    "prohibited_effects": (
                        "main",
                        "master",
                        "release",
                        "commit",
                        "push",
                        "merge",
                    ),
                },
            },
            assert_selfdev_current,
            execute_effect,
        )
        assert_current("after_selfdev_execution")
        self._assert_exact_workspace(spec, require_clean=False)
        self._assert_only_target_changed(spec)

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

    def _assert_target_admitted(self, spec: SelfDevelopmentWorkSpec) -> None:
        target = self._workspace / spec.target_path
        if not target.is_file() or target.is_symlink():
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_TARGET_UNSAFE",
                "single-target SELFDEV requires one existing non-symlink file",
            )
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_TARGET_UNSAFE",
                "target must be readable UTF-8 text",
            ) from exc
        if len(content) > _MAX_COMPLETE_REPLACEMENT_CHARACTERS:
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_TARGET_TOO_LARGE",
                "complete-replacement route is limited to fully provider-visible files",
            )

    def _assert_only_target_changed(self, spec: SelfDevelopmentWorkSpec) -> None:
        changed = self._git_status_paths()
        if changed - {spec.target_path}:
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
