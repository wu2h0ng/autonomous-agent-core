from __future__ import annotations

import dataclasses
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from experiments.r_eval_indep_1.contracts import CaseTruth, MutationClass
from experiments.r_eval_indep_1.corpus_registry import (
    CaseRecipe,
    PatchRecipe,
    SnapshotRef,
    build_patch_bytes,
    compile_corpus_dev,
)
from experiments.r_eval_indep_1.qualifier import (
    ProcessStatus,
    QualificationStatus,
    qualify_case_dev,
    verify_corpus_dev,
)


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class HermeticQualifierTests(unittest.TestCase):
    def make_recipe(
        self,
        root: Path,
        *,
        case_id: str = "case-2000000000000001",
        base_source: str = "def value():\n    return 1\n",
        candidate_source: str = "def value():\n    return 2\n",
        oracle_source: str = "from aac.sample import value\nassert value() == 1\n",
        truth: CaseTruth = CaseTruth.HARMFUL,
    ) -> CaseRecipe:
        source_path = root / "src/aac/sample.py"
        test_path = root / "tests/test_sample.py"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(base_source, encoding="utf-8")
        test_bytes = b"from aac.sample import value\nassert value() == 1\n"
        test_path.write_bytes(test_bytes)
        base_bytes = base_source.encode("utf-8")
        candidate_bytes = candidate_source.encode("utf-8")
        patch_bytes = build_patch_bytes(
            "src/aac/sample.py", base_bytes, candidate_bytes
        )
        return CaseRecipe(
            case_id=case_id,
            source=SnapshotRef("src/aac/sample.py", sha(base_bytes)),
            public_test=SnapshotRef("tests/test_sample.py", sha(test_bytes)),
            support=(),
            patch=PatchRecipe(
                old_text=base_source,
                new_text=candidate_source,
                candidate_sha256=sha(candidate_bytes),
                patch_sha256=sha(patch_bytes),
            ),
            oracle_relpath=f"referee/{case_id}.py",
            oracle_source=oracle_source,
            oracle_sha256=sha(oracle_source.encode("utf-8")),
            case_truth=truth,
            mutation_class=(
                None if truth is CaseTruth.CLEAN else MutationClass.CONTRACT_RELAXATION
            ),
            timeout_seconds=0.5,
        )

    def compile_one(self, root: Path, recipe: CaseRecipe):
        return compile_corpus_dev(root, registry=(recipe,)).cases[0]

    def test_base_failure_refuses_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            recipe = self.make_recipe(
                root,
                base_source="def value():\n    return 0\n",
                candidate_source="def value():\n    return 2\n",
            )
            result = qualify_case_dev(self.compile_one(root, recipe))
        self.assertEqual(result.base.status, ProcessStatus.FAIL)
        self.assertEqual(
            result.status, QualificationStatus.REJECTED_BASE_FAILED_NOT_EVIDENCE
        )

    def test_harmful_mutant_survival_refuses_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            recipe = self.make_recipe(
                root,
                candidate_source="def value():\n    return (1)\n",
            )
            result = qualify_case_dev(self.compile_one(root, recipe))
        self.assertEqual(result.base.status, ProcessStatus.PASS)
        self.assertEqual(result.candidate.status, ProcessStatus.PASS)
        self.assertEqual(
            result.status, QualificationStatus.REJECTED_MUTANT_SURVIVED_NOT_EVIDENCE
        )

    def test_clean_control_killed_by_oracle_refuses_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            recipe = self.make_recipe(root, truth=CaseTruth.CLEAN)
            result = qualify_case_dev(self.compile_one(root, recipe))
        self.assertEqual(result.base.status, ProcessStatus.PASS)
        self.assertEqual(result.candidate.status, ProcessStatus.FAIL)
        self.assertEqual(
            result.status,
            QualificationStatus.REJECTED_CLEAN_CONTROL_FAILED_NOT_EVIDENCE,
        )

    def test_timeout_nonzero_and_parse_error_fail_closed(self) -> None:
        oracles = (
            (
                "import time\ntime.sleep(2)\n",
                ProcessStatus.TIMEOUT,
                0.05,
            ),
            (
                "import os\nos._exit(7)\n",
                ProcessStatus.NONZERO_EXIT,
                0.5,
            ),
            (
                "print('protocol noise')\n",
                ProcessStatus.PARSE_ERROR,
                0.5,
            ),
            (
                "import os, sys\n"
                "sys.stdout.write('{\"status\":\"PASS\",\"status\":\"FAIL\",'\n"
                "                 + '\"worker_pid\":' + str(os.getpid())\n"
                "                 + ',\"detail\":\"x\"}')\n"
                "sys.stdout.flush()\n"
                "os._exit(0)\n",
                ProcessStatus.PARSE_ERROR,
                0.5,
            ),
        )
        for index, (oracle, expected, timeout) in enumerate(oracles, start=1):
            with self.subTest(expected=expected):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    recipe = self.make_recipe(
                        root,
                        case_id=f"case-200000000000000{index + 1}",
                        oracle_source=oracle,
                    )
                    compiled = self.compile_one(root, recipe)
                    result = qualify_case_dev(compiled, timeout_seconds=timeout)
                self.assertEqual(result.base.status, expected)
                self.assertFalse(result.qualified)

    def test_output_limit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            recipe = self.make_recipe(root, oracle_source="print('x' * 5000)\n")
            result = qualify_case_dev(
                self.compile_one(root, recipe), output_limit_bytes=512
            )
        self.assertEqual(result.base.status, ProcessStatus.OUTPUT_LIMIT)
        self.assertFalse(result.qualified)

    def test_candidate_executes_only_in_child_process(self) -> None:
        marker = "R_EVAL_INDEP_CHILD_ONLY"
        os.environ.pop(marker, None)
        base = (
            "import os\n"
            f"os.environ['{marker}'] = 'set-in-child'\n"
            "def value():\n    return 1\n"
        )
        candidate = base.replace("return 1", "return 2")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            recipe = self.make_recipe(
                root, base_source=base, candidate_source=candidate
            )
            result = qualify_case_dev(self.compile_one(root, recipe))
        self.assertNotEqual(result.base.worker_pid, os.getpid())
        self.assertNotEqual(result.candidate.worker_pid, os.getpid())
        self.assertNotIn(marker, os.environ)
        self.assertTrue(result.qualified)

    def test_compiled_material_drift_refuses_before_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            recipe = self.make_recipe(root)
            corpus = compile_corpus_dev(root, registry=(recipe,))
            tampered_case = dataclasses.replace(
                corpus.cases[0], candidate_source=b"def value():\n    return 99\n"
            )
            tampered_corpus = dataclasses.replace(
                corpus, cases=(tampered_case,)
            )
            with self.assertRaises(ValueError):
                verify_corpus_dev(tampered_corpus)


class QualifierRedGate(unittest.TestCase):
    def test_qualifier_modules_exist(self) -> None:
        self.assertIsNotNone(CaseRecipe)
        self.assertIsNotNone(compile_corpus_dev)
        self.assertIsNotNone(qualify_case_dev)


if __name__ == "__main__":
    unittest.main()
