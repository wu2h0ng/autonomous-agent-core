from __future__ import annotations

import dataclasses
import hashlib
import tempfile
import unittest
from pathlib import Path

from experiments.r_eval_indep_1.contracts import CaseTruth, MutationClass
from experiments.r_eval_indep_1.corpus_cases_batch2b import (
    CASE_DEFINITIONS,
    MATERIAL_PINS,
    build_batch2b_materials,
)
from experiments.r_eval_indep_1.corpus_registry import (
    REGISTRY,
    SnapshotRef,
    compile_corpus_dev,
    read_pinned_snapshot,
)
from experiments.r_eval_indep_1.qualifier import verify_corpus_dev


REPO_ROOT = Path(__file__).resolve().parents[1]


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


class RealCorpusRegistryTests(unittest.TestCase):
    def test_batch2b_material_table_is_closed_unique_and_fully_pinned(self) -> None:
        materials = build_batch2b_materials()
        self.assertEqual(len(CASE_DEFINITIONS), 60)
        self.assertEqual(len(MATERIAL_PINS), 60)
        self.assertEqual(len(materials), 60)
        self.assertEqual(
            set(MATERIAL_PINS), {definition.key for definition in CASE_DEFINITIONS}
        )
        self.assertEqual(len({item.case_id for item in materials}), 60)
        self.assertEqual(len({item.candidate_sha256 for item in materials}), 60)
        self.assertEqual(len({item.patch_sha256 for item in materials}), 60)

    def test_registry_has_sixty_real_mutations_and_fourteen_clean_controls(self) -> None:
        harmful = [item for item in REGISTRY if item.case_truth is CaseTruth.HARMFUL]
        clean = [item for item in REGISTRY if item.case_truth is CaseTruth.CLEAN]
        self.assertEqual(len(harmful), 60)
        self.assertEqual(len(clean), 14)
        self.assertEqual(len(REGISTRY), 74)
        self.assertEqual({item.mutation_class for item in harmful}, set(MutationClass))
        self.assertGreaterEqual(len({item.source.relpath for item in harmful}), 10)
        self.assertTrue(
            all(item.source.relpath.startswith("src/aac/") for item in REGISTRY)
        )
        self.assertTrue(
            all(item.public_test.relpath.startswith("tests/") for item in REGISTRY)
        )
        self.assertEqual(len({item.case_id for item in REGISTRY}), 74)
        self.assertEqual(len({item.patch.candidate_sha256 for item in REGISTRY}), 74)
        self.assertEqual(len({item.patch.patch_sha256 for item in REGISTRY}), 74)
        self.assertEqual(len({item.patch.patch_sha256 for item in clean}), 14)
        self.assertEqual({item.timeout_seconds for item in REGISTRY}, {1.5})

    def test_real_registry_compiles_with_exact_pins_and_separate_digests(self) -> None:
        compiled = compile_corpus_dev(REPO_ROOT)
        self.assertEqual(len(compiled.cases), 74)
        self.assertNotEqual(
            compiled.manifest.public_cases_sha256,
            compiled.manifest.referee_cases_sha256,
        )
        self.assertEqual(
            len(compiled.manifest.to_public_mapping()["public_cases"]), 74
        )

    def test_every_material_identity_pin_fails_closed_on_drift(self) -> None:
        recipe = next(
            item for item in REGISTRY if item.case_id == "case-b8efb3d71beb9c06"
        )
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

    def test_duplicate_candidate_and_patch_identity_fail_closed(self) -> None:
        recipe = REGISTRY[0]
        duplicate = dataclasses.replace(
            recipe,
            case_id="case-0000000000000000",
        )
        with self.assertRaisesRegex(ValueError, "duplicate candidate source digest"):
            compile_corpus_dev(REPO_ROOT, registry=(recipe, duplicate))

    def test_real_mutations_are_killed_and_clean_controls_survive(self) -> None:
        compiled = compile_corpus_dev(REPO_ROOT)
        records = verify_corpus_dev(compiled)
        self.assertEqual(len(records), 74)
        self.assertTrue(all(record.qualified for record in records))
        harmful = [record for record in records if record.case_truth is CaseTruth.HARMFUL]
        clean = [record for record in records if record.case_truth is CaseTruth.CLEAN]
        self.assertEqual(len(harmful), 60)
        self.assertEqual(len(clean), 14)


class RegistryRedGate(unittest.TestCase):
    def test_real_registry_module_exists(self) -> None:
        self.assertIsNotNone(REGISTRY)
        self.assertIsNotNone(read_pinned_snapshot)
        self.assertIsNotNone(verify_corpus_dev)


if __name__ == "__main__":
    unittest.main()
