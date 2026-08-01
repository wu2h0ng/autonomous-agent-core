from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess
from typing import Any

from agent_os_contracts import SelfDevelopmentWorkSpec


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
    ) -> None:
        self._workspace = Path(workspace).resolve()
        self._execute_task = execute_task

    def __call__(
        self,
        task_id: str,
        spec: SelfDevelopmentWorkSpec,
        assert_current: Callable[[str], None],
        execute_effect: Any,
    ) -> None:
        self._assert_exact_workspace(spec)
        assert_current("before_selfdev_execution")
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
            assert_current,
            execute_effect,
        )
        assert_current("after_selfdev_execution")
        self._assert_exact_workspace(spec)

    def _assert_exact_workspace(self, spec: SelfDevelopmentWorkSpec) -> None:
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
