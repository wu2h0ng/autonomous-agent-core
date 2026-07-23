from __future__ import annotations

import re
from typing import Annotated, TypeAlias

from pydantic import AfterValidator, Field

from .common import ContractModel, NonEmptyStr, content_digest
from .evidence import Sha256Digest


BENCHMARK_TASK_INVALID = "BENCHMARK_TASK_INVALID"
BENCHMARK_GOLD_FILE_MAX_BYTES = 19000
BENCHMARK_TASK_DIGEST_SCHEMA = "SELFDEV2-BENCHMARK-TASK-V1"

_NODE_ID_PATH_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-/]*")
_NODE_ID_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PINNED_DEP_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
    r"=="
    r"[A-Za-z0-9][A-Za-z0-9.!*+_-]*"
    r"(?:[ \t]+--hash=sha256:[0-9a-f]{64})?"
)


class BenchmarkTaskValidationError(ValueError):
    """Raised when a benchmark task or baseline artifact fails validation."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def is_valid_benchmark_node_id(value: str) -> bool:
    """Return True iff value is an allowlisted pytest node id.

    Enumerated forms (ADR-0056 decision 6): ``path::Class::test`` or
    ``path::test``. The path must be relative with no whitespace, shell
    metacharacters or parent segments; class/test names must be plain
    identifiers (no parametrized ids, no pytest flags).
    """

    if not isinstance(value, str) or not value:
        return False
    parts = value.split("::")
    if len(parts) not in (2, 3):
        return False
    path, names = parts[0], parts[1:]
    if not path or any(not name for name in names):
        return False
    if _NODE_ID_PATH_PATTERN.fullmatch(path) is None:
        return False
    if any(segment in ("", ".", "..") for segment in path.split("/")):
        return False
    return all(
        _NODE_ID_NAME_PATTERN.fullmatch(name) is not None for name in names
    )


def _require_benchmark_node_id(value: str) -> str:
    if not is_valid_benchmark_node_id(value):
        raise ValueError(f"invalid pytest node id: {value!r}")
    return value


def _require_pinned_dep(value: str) -> str:
    if _PINNED_DEP_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "pinned dep must be 'name==version' with an optional "
            f"'--hash=sha256:<64 hex>' suffix: {value!r}"
        )
    return value


BenchmarkNodeId: TypeAlias = Annotated[str, AfterValidator(_require_benchmark_node_id)]
PinnedDep: TypeAlias = Annotated[str, AfterValidator(_require_pinned_dep)]


def benchmark_task_digest(task: SelfDevelopmentBenchmarkTask) -> str:
    return content_digest(
        {
            "schema": BENCHMARK_TASK_DIGEST_SCHEMA,
            "task": task,
        }
    )


class BenchmarkEnvironmentManifest(ContractModel):
    """Pinned, hash-locked per-task verifier environment (ADR-0056 item 1)."""

    interpreter: NonEmptyStr
    pinned_deps: tuple[PinnedDep, ...] = ()
    verifier_timeout_seconds: int = Field(ge=1)
    min_output_tokens: int = Field(ge=1)


class SelfDevelopmentBenchmarkTask(ContractModel):
    """External benchmark task admission contract (ADR-0056 decision 1)."""

    task_id: NonEmptyStr
    repo_url: NonEmptyStr
    base_commit: NonEmptyStr
    issue_text_hash: Sha256Digest
    gold_file_path: NonEmptyStr
    gold_file_bytes: int = Field(ge=1, le=BENCHMARK_GOLD_FILE_MAX_BYTES)
    f2p_node_ids: tuple[BenchmarkNodeId, ...] = Field(min_length=1)
    p2p_node_ids: tuple[BenchmarkNodeId, ...] = ()
    env_manifest: BenchmarkEnvironmentManifest

    def task_digest(self) -> str:
        """Content digest binding every admitted field (schema-tagged)."""
        return benchmark_task_digest(self)
