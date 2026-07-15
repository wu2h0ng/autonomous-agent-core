from __future__ import annotations

import dataclasses
import hashlib
import tempfile
import unittest
from pathlib import Path

from experiments.r_eval_indep_1.contracts import CaseTruth, MutationClass

try:
    from experiments.r_eval_indep_1.corpus_registry import (
        REGISTRY,
        SnapshotRef,
        compile_corpus_dev,
        read_pinned_snapshot,
    )
    from experiments.r_eval_indep_1.qualifier import verify_corpus_dev
except ModuleNotFoundError:
    REGISTRY = None  # type: ignore[assignment]
    SnapshotRef = None  # type: ignore[assignment,misc]
    compile_corpus_dev = None  # type: ignore[assignment]
    read_pinned_snapshot = None  # type: ignore[assignment]
    verify_corpus_dev = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(REGISTRY is None, "real corpus registry not implemented")
class SnapshotBoundaryTests(unittest.TestCase):
    def test_digest_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "src/aac/value.py"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"before\n")
            ref = SnapshotRef(
                "src/aac/value.py", hashlib.sha256(b"before\n").hexdigest()
            )
            path.write_bytes(b"after\n")
            with self.assertRaises(ValueError):
                read_pinned_snapshot(root, ref, {ref.relpath})

    def test_path_escape_non_allowlisted_path_and_symlink_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outside = root.parent / "outside-r-eval.py"
            outside.write_bytes(b"outside\n")
            digest = hashlib.sha256(b"outside\n").hexdigest()
            with self.assertRaises(ValueError):
                read_pinned_snapshot(
                    root,
                    SnapshotRef("../outside-r-eval.py", digest),
                    {"../outside-r-eval.py"},
                )

            target = root / "src/aac/target.py"
            target.parent.mkdir(parents=True)
            target.symlink_to(outside)
            with self.assertRaises(ValueError):
                read_pinned_snapshot(
                    root,
                    SnapshotRef("src/aac/target.py", digest),
                    {"src/aac/target.py"},
                )

            regular = root / "src/aac/regular.py"
            regular.write_bytes(b"regular\n")
            regular_ref = SnapshotRef(
                "src/aac/regular.py", hashlib.sha256(b"regular\n").hexdigest()
            )
            with self.assertRaises(ValueError):
                read_pinned_snapshot(root, regular_ref, {"tests/only.py"})

            for path in ("src//aac/regular.py", "src/./aac/regular.py"):
                with self.subTest(path=path):
                    with self.assertRaises(ValueError):
                        SnapshotRef(path, regular_ref.sha256)


@unittest.skipIf(REGISTRY is None, "real corpus registry not implemented")
class RealCorpusRegistryTests(unittest.TestCase):
    def test_registry_has_seven_distinct_real_mutations_and_clean_controls(self) -> None:
        harmful = [item for item in REGISTRY if item.case_truth is CaseTruth.HARMFUL]
        clean = [item for item in REGISTRY if item.case_truth is CaseTruth.CLEAN]
        self.assertEqual(len(harmful), 7)
        self.assertEqual(len(clean), 7)
        self.assertEqual({item.mutation_class for item in harmful}, set(MutationClass))
        self.assertEqual(len({item.source.relpath for item in harmful}), 7)
        self.assertEqual(
            {item.source.relpath for item in harmful},
            {item.source.relpath for item in clean},
        )
        self.assertEqual(len({item.patch.patch_sha256 for item in clean}), 7)
        self.assertEqual({item.timeout_seconds for item in REGISTRY}, {1.5})

    def test_real_registry_compiles_with_exact_pins_and_separate_digests(self) -> None:
        compiled = compile_corpus_dev(REPO_ROOT)
        self.assertEqual(len(compiled.cases), 14)
        self.assertNotEqual(
            compiled.manifest.public_cases_sha256,
            compiled.manifest.referee_cases_sha256,
        )
        self.assertEqual(
            len(compiled.manifest.to_public_mapping()["public_cases"]), 14
        )

    def test_every_material_identity_pin_fails_closed_on_drift(self) -> None:
        recipe = REGISTRY[0]
        zero = "0" * 64
        drifted_inputs = (
            dataclasses.replace(
                recipe,
                source=dataclasses.replace(recipe.source, sha256=zero),
            ),
            dataclasses.replace(
                recipe,
                public_test=dataclasses.replace(recipe.public_test, sha256=zero),
            ),
            dataclasses.replace(
                recipe,
                support=(
                    dataclasses.replace(recipe.support[0], sha256=zero),
                    *recipe.support[1:],
                ),
            ),
            dataclasses.replace(
                recipe,
                patch=dataclasses.replace(recipe.patch, candidate_sha256=zero),
            ),
            dataclasses.replace(
                recipe,
                patch=dataclasses.replace(recipe.patch, patch_sha256=zero),
            ),
        )
        for drifted in drifted_inputs:
            with self.subTest(drifted=drifted):
                with self.assertRaises(ValueError):
                    compile_corpus_dev(REPO_ROOT, registry=(drifted,))
        with self.assertRaises(ValueError):
            dataclasses.replace(recipe, oracle_sha256=zero)

    def test_real_mutations_are_killed_and_clean_controls_survive(self) -> None:
        compiled = compile_corpus_dev(REPO_ROOT)
        records = verify_corpus_dev(compiled)
        self.assertEqual(len(records), 14)
        self.assertTrue(all(record.qualified for record in records))
        harmful = [record for record in records if record.case_truth is CaseTruth.HARMFUL]
        clean = [record for record in records if record.case_truth is CaseTruth.CLEAN]
        self.assertEqual(len(harmful), 7)
        self.assertEqual(len(clean), 7)


class RegistryRedGate(unittest.TestCase):
    def test_real_registry_module_exists(self) -> None:
        self.assertIsNotNone(REGISTRY)
        self.assertIsNotNone(read_pinned_snapshot)
        self.assertIsNotNone(verify_corpus_dev)


if __name__ == "__main__":
    unittest.main()
