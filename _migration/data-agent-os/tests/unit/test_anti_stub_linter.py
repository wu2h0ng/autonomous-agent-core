"""Tests for the anti-stub linter."""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from anti_stub_linter import (  # noqa: E402
    _collect_test_files,
    _has_test_file,
    _is_under_dir,
    find_stubs,
    is_stub_body,
    main,
)


class StubDetectionTest(unittest.TestCase):
    def test_pass_only_is_stub(self) -> None:
        tree = ast.parse("def f():\n    pass")
        func = tree.body[0]
        assert isinstance(func, ast.FunctionDef)
        self.assertTrue(is_stub_body(func.body))

    def test_ellipsis_only_is_stub(self) -> None:
        tree = ast.parse("def f():\n    ...")
        func = tree.body[0]
        assert isinstance(func, ast.FunctionDef)
        self.assertTrue(is_stub_body(func.body))

    def test_docstring_plus_pass_is_stub(self) -> None:
        tree = ast.parse('def f():\n    """doc."""\n    pass')
        func = tree.body[0]
        assert isinstance(func, ast.FunctionDef)
        self.assertTrue(is_stub_body(func.body))

    def test_not_implemented_error_is_stub(self) -> None:
        tree = ast.parse("def f():\n    raise NotImplementedError")
        func = tree.body[0]
        assert isinstance(func, ast.FunctionDef)
        self.assertTrue(is_stub_body(func.body))

    def test_not_implemented_error_call_is_stub(self) -> None:
        tree = ast.parse("def f():\n    raise NotImplementedError('todo')")
        func = tree.body[0]
        assert isinstance(func, ast.FunctionDef)
        self.assertTrue(is_stub_body(func.body))

    def test_return_not_implemented_is_stub(self) -> None:
        tree = ast.parse("def f():\n    return NotImplemented")
        func = tree.body[0]
        assert isinstance(func, ast.FunctionDef)
        self.assertTrue(is_stub_body(func.body))

    def test_real_body_is_not_stub(self) -> None:
        tree = ast.parse("def f():\n    return 1 + 2")
        func = tree.body[0]
        assert isinstance(func, ast.FunctionDef)
        self.assertFalse(is_stub_body(func.body))

    def test_empty_body_is_stub(self) -> None:
        self.assertTrue(is_stub_body([]))


class FileScanningTest(unittest.TestCase):
    def test_find_stubs_detects_stub_function(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write("class C:\n    def f(self):\n        pass\n")
            path = Path(fh.name)
        try:
            issues = find_stubs(path)
            self.assertEqual(len(issues), 2)
            reasons = {reason for _, reason in issues}
            self.assertIn("stub class: C", reasons)
            self.assertIn("stub function/method: f", reasons)
        finally:
            path.unlink()

    def test_find_stubs_allows_real_module(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write("def add(a, b):\n    return a + b\n")
            path = Path(fh.name)
        try:
            issues = find_stubs(path)
            self.assertEqual(issues, [])
        finally:
            path.unlink()

    def test_has_test_file(self) -> None:
        self.assertTrue(_has_test_file(Path("foo.py"), {"test_foo"}))
        self.assertFalse(_has_test_file(Path("foo.py"), {"test_bar"}))
        self.assertTrue(_has_test_file(Path("__init__.py"), set()))

    def test_is_under_dir(self) -> None:
        root = Path("/repo")
        self.assertTrue(_is_under_dir(Path("/repo/packages/foo.py"), root / "packages"))
        self.assertFalse(_is_under_dir(Path("/repo/tests/foo.py"), root / "packages"))

    def test_collect_test_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tests" / "unit").mkdir(parents=True)
            (root / "tests" / "unit" / "test_foo.py").write_text("pass\n")
            names = _collect_test_files(["tests"], root)
            self.assertIn("test_foo", names)


class MainIntegrationTest(unittest.TestCase):
    def test_main_passes_on_clean_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "packages").mkdir()
            (root / "packages" / "real.py").write_text("def add(a, b):\n    return a + b\n")
            (root / "tests").mkdir()
            (root / "tests" / "test_real.py").write_text("pass\n")
            rc = main(
                ["--source-dirs", "packages", "--test-dirs", "tests", "--all"],
                repo_root=root,
            )
            self.assertEqual(rc, 0)

    def test_main_fails_on_stub_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "packages").mkdir()
            (root / "packages" / "stubby.py").write_text("def f():\n    pass\n")
            (root / "tests").mkdir()
            (root / "tests" / "test_stubby.py").write_text("pass\n")
            rc = main(
                ["--source-dirs", "packages", "--test-dirs", "tests", "--all"],
                repo_root=root,
            )
            self.assertEqual(rc, 1)

    def test_main_fails_on_untested_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "packages").mkdir()
            (root / "packages" / "untested.py").write_text("def add(a, b):\n    return a + b\n")
            (root / "tests").mkdir()
            rc = main(
                ["--source-dirs", "packages", "--test-dirs", "tests", "--all"],
                repo_root=root,
            )
            # --all mode does not check for missing tests.
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
