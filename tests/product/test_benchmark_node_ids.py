from __future__ import annotations

from pathlib import Path

import pytest

from agent_os_contracts import (
    BenchmarkTaskValidationError,
    is_valid_benchmark_node_id,
)
from agent_os_core import (
    BENCHMARK_NODE_ID_UNRESOLVED,
    resolve_benchmark_node_id,
    resolve_benchmark_node_ids,
)

UNITTEST_MODULE = """\
import unittest


class RequestsTestCase(unittest.TestCase):
    def test_z(self):
        assert True

    def test_z_extra(self):
        assert True
"""

DJANGO_STYLE_MODULE = """\
from django.test import TestCase


class QueryTests(TestCase):
    def test_filter(self):
        assert True
"""

BOUNDED_MODULE = """\
class BoundedCase:
    def test_z_extra(self):
        pass
"""

BARE_FUNCTION_MODULE = """\
def test_Identity():
    assert True
"""


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _assert_unresolved(raw_id: str, repo_root: Path) -> None:
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        resolve_benchmark_node_id(raw_id, repo_root=repo_root)
    assert excinfo.value.code == BENCHMARK_NODE_ID_UNRESOLVED


def test_pytest_style_ids_pass_through_unchanged(tmp_path: Path) -> None:
    assert (
        resolve_benchmark_node_id(
            "tests/test_x.py::TestY::test_z", repo_root=tmp_path
        )
        == "tests/test_x.py::TestY::test_z"
    )
    assert (
        resolve_benchmark_node_id("test_mod.py::test_z", repo_root=tmp_path)
        == "test_mod.py::test_z"
    )


def test_invalid_pytest_style_ids_fail_closed(tmp_path: Path) -> None:
    _assert_unresolved("tests/test_x.py::test_z[param]", tmp_path)
    _assert_unresolved("tests/test_x.py::", tmp_path)
    _assert_unresolved("../test_x.py::test_z", tmp_path)


def test_unittest_style_resolves_direct_module_path(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_requests.py", UNITTEST_MODULE)
    resolved = resolve_benchmark_node_id(
        "test_z (tests.test_requests.RequestsTestCase)", repo_root=tmp_path
    )
    assert resolved == "tests/test_requests.py::RequestsTestCase::test_z"
    assert is_valid_benchmark_node_id(resolved)


def test_unittest_style_resolves_package_init(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/tests/__init__.py", UNITTEST_MODULE)
    resolved = resolve_benchmark_node_id(
        "test_z (pkg.tests.RequestsTestCase)", repo_root=tmp_path
    )
    assert resolved == "pkg/tests/__init__.py::RequestsTestCase::test_z"
    assert is_valid_benchmark_node_id(resolved)


def test_unittest_style_falls_back_to_path_tail(tmp_path: Path) -> None:
    _write(tmp_path, "tests/queries/tests.py", DJANGO_STYLE_MODULE)
    resolved = resolve_benchmark_node_id(
        "test_filter (queries.tests.QueryTests)", repo_root=tmp_path
    )
    assert resolved == "tests/queries/tests.py::QueryTests::test_filter"


def test_unittest_style_direct_module_wins_over_tail_match(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "queries/tests.py", DJANGO_STYLE_MODULE)
    _write(tmp_path, "tests/queries/tests.py", DJANGO_STYLE_MODULE)
    resolved = resolve_benchmark_node_id(
        "test_filter (queries.tests.QueryTests)", repo_root=tmp_path
    )
    assert resolved == "queries/tests.py::QueryTests::test_filter"


def test_unittest_style_tail_prefers_fewest_path_components(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "tests/queries/tests.py", DJANGO_STYLE_MODULE)
    _write(tmp_path, "deep/nested/queries/tests.py", DJANGO_STYLE_MODULE)
    resolved = resolve_benchmark_node_id(
        "test_filter (queries.tests.QueryTests)", repo_root=tmp_path
    )
    assert resolved == "tests/queries/tests.py::QueryTests::test_filter"


def test_unittest_style_tail_breaks_ties_lexicographically(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "zeta/queries/tests.py", DJANGO_STYLE_MODULE)
    _write(tmp_path, "alpha/queries/tests.py", DJANGO_STYLE_MODULE)
    resolved = resolve_benchmark_node_id(
        "test_filter (queries.tests.QueryTests)", repo_root=tmp_path
    )
    assert resolved == "alpha/queries/tests.py::QueryTests::test_filter"


def test_unittest_style_module_not_found_fails_closed(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_other.py", UNITTEST_MODULE)
    _assert_unresolved("test_z (missing.module.RequestsTestCase)", tmp_path)


def test_unittest_style_without_module_fails_closed(tmp_path: Path) -> None:
    _assert_unresolved("test_z (RequestsTestCase)", tmp_path)


def test_unittest_style_class_not_found_fails_closed(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_requests.py", UNITTEST_MODULE)
    _assert_unresolved("test_z (tests.test_requests.MissingCase)", tmp_path)


def test_unittest_style_method_not_found_fails_closed(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_requests.py", UNITTEST_MODULE)
    _assert_unresolved("test_missing (tests.test_requests.RequestsTestCase)", tmp_path)


def test_unittest_style_method_match_is_word_bounded(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_bounded.py", BOUNDED_MODULE)
    _assert_unresolved("test_z (tests.test_bounded.BoundedCase)", tmp_path)


def test_bare_name_resolves_single_match(tmp_path: Path) -> None:
    _write(tmp_path, "sympy/core/tests/test_basic.py", BARE_FUNCTION_MODULE)
    # a same-named def outside any "test" path must not count
    _write(tmp_path, "sympy/core/basic.py", BARE_FUNCTION_MODULE)
    resolved = resolve_benchmark_node_id("test_Identity", repo_root=tmp_path)
    assert resolved == "sympy/core/tests/test_basic.py::test_Identity"
    assert is_valid_benchmark_node_id(resolved)


def test_bare_name_zero_matches_fails_closed(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_basic.py", "def test_other():\n    pass\n")
    _assert_unresolved("test_Identity", tmp_path)


def test_bare_name_multiple_files_fail_closed(tmp_path: Path) -> None:
    _write(tmp_path, "sympy/core/tests/test_basic.py", BARE_FUNCTION_MODULE)
    _write(tmp_path, "sympy/matrices/tests/test_matrices.py", BARE_FUNCTION_MODULE)
    _assert_unresolved("test_Identity", tmp_path)


def test_repo_search_skips_hidden_directories(tmp_path: Path) -> None:
    _write(tmp_path, ".venv/lib/tests/test_hidden.py", BARE_FUNCTION_MODULE)
    _assert_unresolved("test_Identity", tmp_path)


def test_unrecognized_style_fails_closed(tmp_path: Path) -> None:
    _assert_unresolved(
        "Migration directories without an __init__.py file are loaded.",
        tmp_path,
    )
    _assert_unresolved("", tmp_path)


def test_resolve_benchmark_node_ids_maps_in_order(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_requests.py", UNITTEST_MODULE)
    _write(tmp_path, "sympy/core/tests/test_basic.py", BARE_FUNCTION_MODULE)
    resolved = resolve_benchmark_node_ids(
        (
            "tests/test_x.py::TestY::test_z",
            "test_z (tests.test_requests.RequestsTestCase)",
            "test_Identity",
        ),
        repo_root=tmp_path,
    )
    assert resolved == (
        "tests/test_x.py::TestY::test_z",
        "tests/test_requests.py::RequestsTestCase::test_z",
        "sympy/core/tests/test_basic.py::test_Identity",
    )
    assert all(is_valid_benchmark_node_id(node_id) for node_id in resolved)


def test_resolve_benchmark_node_ids_fails_closed_on_any_bad_id(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "tests/test_requests.py", UNITTEST_MODULE)
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        resolve_benchmark_node_ids(
            (
                "test_z (tests.test_requests.RequestsTestCase)",
                "test_missing (tests.test_requests.RequestsTestCase)",
            ),
            repo_root=tmp_path,
        )
    assert excinfo.value.code == BENCHMARK_NODE_ID_UNRESOLVED
