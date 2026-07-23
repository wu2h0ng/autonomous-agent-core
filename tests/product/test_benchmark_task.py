from __future__ import annotations

from pathlib import Path

import pytest

from agent_os_contracts import (
    BENCHMARK_GOLD_FILE_MAX_BYTES,
    BENCHMARK_TASK_INVALID,
    BenchmarkTaskValidationError,
    SelfDevelopmentBenchmarkTask,
)
from agent_os_core import (
    VERIFIER_ARGV_SCHEMA,
    build_benchmark_task,
    build_verifier_argv,
    validate_f2p_p2p_disjoint,
    validate_gold_file,
)

ISSUE_TEXT_HASH = "b" * 64
DEP_HASH = "a" * 64
F2P_ID = "tests/queries/tests.py::QueryTests::test_filter"
P2P_ID = "tests/queries/tests.py::QueryTests::test_ordering"


def _manifest(**overrides: object) -> dict[str, object]:
    manifest: dict[str, object] = {
        "interpreter": "python3.11",
        "pinned_deps": (
            "pytest==8.3.2",
            f"six==1.16.0 --hash=sha256:{DEP_HASH}",
        ),
        "verifier_timeout_seconds": 120,
        "min_output_tokens": 4096,
    }
    manifest.update(overrides)
    return manifest


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "task_id": "swe-bench-verified:django__django-11099",
        "repo_url": "https://github.com/django/django",
        "base_commit": "0" * 40,
        "issue_text_hash": ISSUE_TEXT_HASH,
        "gold_file_path": "django/db/models/query.py",
        "gold_file_bytes": 1234,
        "f2p_node_ids": (F2P_ID,),
        "p2p_node_ids": (P2P_ID,),
        "env_manifest": _manifest(),
    }
    payload.update(overrides)
    return payload


def _assert_invalid(payload: dict[str, object]) -> None:
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        build_benchmark_task(payload)
    assert excinfo.value.code == BENCHMARK_TASK_INVALID


def test_benchmark_task_builds_and_digest_is_stable() -> None:
    task = build_benchmark_task(_payload())
    assert isinstance(task, SelfDevelopmentBenchmarkTask)
    assert task.f2p_node_ids == (F2P_ID,)
    assert task.p2p_node_ids == (P2P_ID,)
    assert task.env_manifest.interpreter == "python3.11"
    digest = task.task_digest()
    assert len(digest) == 64
    assert all(char in "0123456789abcdef" for char in digest)
    assert digest == build_benchmark_task(_payload()).task_digest()
    changed = build_benchmark_task(_payload(gold_file_bytes=4321))
    assert changed.task_digest() != digest


def test_benchmark_task_rejects_oversized_gold_file() -> None:
    _assert_invalid(_payload(gold_file_bytes=BENCHMARK_GOLD_FILE_MAX_BYTES + 1))
    _assert_invalid(_payload(gold_file_bytes=0))


def test_benchmark_task_rejects_empty_f2p() -> None:
    _assert_invalid(_payload(f2p_node_ids=()))


def test_benchmark_task_rejects_unknown_keys() -> None:
    _assert_invalid(_payload(surprise="nope"))
    _assert_invalid(_payload(env_manifest=_manifest(surprise="nope")))


@pytest.mark.parametrize(
    "node_id",
    [
        "tests/x.py",
        "tests/x.py::",
        "::test_x",
        "tests/x.py::C::test_x::extra",
        "tests/x.py::test x",
        "tests/x.py::test;rm",
        "tests/x.py::test$(id)",
        "tests/x.py::test|cat",
        "tests/x.py::test_x[1]",
        "/abs/path.py::test_x",
        "tests/../x.py::test_x",
        "tests//x.py::test_x",
    ],
)
def test_benchmark_task_rejects_bad_node_ids(node_id: str) -> None:
    _assert_invalid(_payload(f2p_node_ids=(node_id,)))
    _assert_invalid(_payload(p2p_node_ids=(node_id,)))


@pytest.mark.parametrize(
    "node_id",
    [
        "tests/test_mod.py::test_func",
        "tests/pkg/test_mod.py::TestClass::test_method",
        "a/b_c/d-e.py::test_x",
        "conftest.py::C::test_y",
    ],
)
def test_benchmark_task_accepts_enumerated_node_id_forms(node_id: str) -> None:
    task = SelfDevelopmentBenchmarkTask.model_validate(
        _payload(f2p_node_ids=(node_id,), p2p_node_ids=())
    )
    assert task.f2p_node_ids == (node_id,)


@pytest.mark.parametrize(
    "dep",
    [
        "pytest",
        "pytest>=8.3.2",
        "pytest ==8.3.2",
        "pytest==8.3.2 --hash=md5:abcd",
        "pytest==8.3.2 --hash=sha256:not-hex",
    ],
)
def test_benchmark_task_rejects_unpinned_or_badly_hashed_deps(dep: str) -> None:
    _assert_invalid(_payload(env_manifest=_manifest(pinned_deps=(dep,))))


def test_benchmark_task_rejects_bad_manifest_budgets() -> None:
    _assert_invalid(_payload(env_manifest=_manifest(verifier_timeout_seconds=0)))
    _assert_invalid(_payload(env_manifest=_manifest(min_output_tokens=0)))


def test_validate_f2p_p2p_disjoint_rejects_overlap() -> None:
    task = SelfDevelopmentBenchmarkTask.model_validate(
        _payload(
            f2p_node_ids=(F2P_ID,),
            p2p_node_ids=(F2P_ID, P2P_ID),
        )
    )
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        validate_f2p_p2p_disjoint(task)
    assert excinfo.value.code == BENCHMARK_TASK_INVALID


def test_build_benchmark_task_rejects_overlapping_f2p_p2p() -> None:
    _assert_invalid(_payload(p2p_node_ids=(F2P_ID,)))


def test_validate_f2p_p2p_disjoint_accepts_disjoint_sets() -> None:
    validate_f2p_p2p_disjoint(build_benchmark_task(_payload()))


def test_build_verifier_argv_returns_exact_list() -> None:
    argv = build_verifier_argv(
        ("tests/a.py::test_one", "tests/b.py::Thing::test_two"),
        timeout_seconds=120,
    )
    assert argv == [
        "python",
        "-m",
        "pytest",
        "tests/a.py::test_one",
        "tests/b.py::Thing::test_two",
    ]
    assert isinstance(argv, list)


def test_verifier_argv_schema_documents_the_enumerated_form() -> None:
    assert "python -m pytest" in VERIFIER_ARGV_SCHEMA


def test_build_verifier_argv_rejects_empty_node_ids() -> None:
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        build_verifier_argv((), timeout_seconds=120)
    assert excinfo.value.code == BENCHMARK_TASK_INVALID


@pytest.mark.parametrize(
    "node_id",
    [
        "--maxfail=1",
        "-k",
        "tests/a.py::test_one;rm",
        "tests/a.py::test_one$(id)",
        "tests/a.py::test_one && id",
        "tests/a.py",
    ],
)
def test_build_verifier_argv_rejects_flags_and_metacharacters(
    node_id: str,
) -> None:
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        build_verifier_argv((node_id,), timeout_seconds=120)
    assert excinfo.value.code == BENCHMARK_TASK_INVALID


def test_build_verifier_argv_rejects_non_positive_timeout() -> None:
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        build_verifier_argv(("tests/a.py::test_one",), timeout_seconds=0)
    assert excinfo.value.code == BENCHMARK_TASK_INVALID


def test_validate_gold_file_returns_byte_and_line_counts(tmp_path: Path) -> None:
    gold = tmp_path / "gold.py"
    content = b"line one\nline two\nline three\n"
    gold.write_bytes(content)
    byte_count, line_count = validate_gold_file(gold)
    assert byte_count == len(content)
    assert line_count == 3


def test_validate_gold_file_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        validate_gold_file(tmp_path / "missing.py")
    assert excinfo.value.code == BENCHMARK_TASK_INVALID


def test_validate_gold_file_rejects_oversized_file(tmp_path: Path) -> None:
    gold = tmp_path / "gold.py"
    gold.write_bytes(b"x" * (BENCHMARK_GOLD_FILE_MAX_BYTES + 1))
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        validate_gold_file(gold)
    assert excinfo.value.code == BENCHMARK_TASK_INVALID


def test_validate_gold_file_honors_custom_max_bytes(tmp_path: Path) -> None:
    gold = tmp_path / "gold.py"
    gold.write_bytes(b"12345")
    with pytest.raises(BenchmarkTaskValidationError):
        validate_gold_file(gold, max_bytes=4)
    assert validate_gold_file(gold, max_bytes=5) == (5, 1)
