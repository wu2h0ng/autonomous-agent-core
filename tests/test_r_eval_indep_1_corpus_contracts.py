from __future__ import annotations

import dataclasses
import unittest

from experiments.r_eval_indep_1.contracts import canonical_digest

try:
    from experiments.r_eval_indep_1.corpus_contracts import (
        CorpusManifest,
        PublicCaseManifest,
        RefereeCaseManifest,
    )
except ModuleNotFoundError:
    CorpusManifest = None  # type: ignore[assignment,misc]
    PublicCaseManifest = None  # type: ignore[assignment,misc]
    RefereeCaseManifest = None  # type: ignore[assignment,misc]


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
CASE_HARMFUL = "case-1000000000000001"
CASE_CLEAN = "case-1000000000000002"


def public_mapping(case_id: str, **updates: object) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "case_id": case_id,
        "source_relpath": "src/aac/safe_expr.py",
        "source_sha256": SHA_A,
        "test_relpath": "tests/test_safe_expr.py",
        "test_sha256": SHA_B,
        "support_sha256": {},
        "candidate_sha256": SHA_C,
        "patch_sha256": SHA_A,
        "candidate_patch": "--- a/src/aac/safe_expr.py\n+++ b/src/aac/safe_expr.py\n",
        "public_checks": ["isolated-independent-oracle-v1"],
    }
    unsigned.update(updates)
    payload = dict(unsigned)
    payload["public_manifest_sha256"] = canonical_digest(unsigned)
    return payload


def referee_mapping(
    case_id: str,
    public_sha256: str,
    *,
    clean: bool = False,
    **updates: object,
) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "case_id": case_id,
        "public_manifest_sha256": public_sha256,
        "case_truth": "CLEAN" if clean else "HARMFUL",
        "mutation_class": None if clean else "contract_relaxation",
        "expected_disposition": "ACCEPT" if clean else "REJECT",
        "oracle_relpath": "referee/oracle.py",
        "oracle_sha256": SHA_B,
    }
    unsigned.update(updates)
    payload = dict(unsigned)
    payload["referee_manifest_sha256"] = canonical_digest(unsigned)
    return payload


@unittest.skipIf(PublicCaseManifest is None, "corpus contracts not implemented")
class PublicManifestContractTests(unittest.TestCase):
    def test_public_mapping_is_closed_and_rejects_private_fields(self) -> None:
        valid = PublicCaseManifest.from_mapping(public_mapping(CASE_HARMFUL))
        self.assertEqual(valid.case_id, CASE_HARMFUL)

        leaked = public_mapping(CASE_HARMFUL)
        leaked["case_truth"] = "HARMFUL"
        with self.assertRaises(ValueError):
            PublicCaseManifest.from_mapping(leaked)

    def test_public_text_rejects_referee_and_camel_case_oracle_leaks(self) -> None:
        with self.assertRaises(ValueError):
            PublicCaseManifest.from_mapping(
                public_mapping(CASE_HARMFUL, source_relpath="referee/source.py")
            )
        with self.assertRaises(ValueError):
            PublicCaseManifest.from_mapping(
                public_mapping(
                    CASE_HARMFUL,
                    candidate_patch="+++ module.py\n+# consult hiddenOracle\n",
                )
            )

    def test_public_paths_must_already_be_normalized(self) -> None:
        for path in ("src//aac/safe_expr.py", "src/./aac/safe_expr.py"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    PublicCaseManifest.from_mapping(
                        public_mapping(CASE_HARMFUL, source_relpath=path)
                    )

    def test_public_manifest_digest_binds_exact_content(self) -> None:
        payload = public_mapping(CASE_HARMFUL)
        payload["candidate_sha256"] = SHA_A
        with self.assertRaises(ValueError):
            PublicCaseManifest.from_mapping(payload)

    def test_support_identity_mapping_is_immutable(self) -> None:
        manifest = PublicCaseManifest.from_mapping(public_mapping(CASE_HARMFUL))
        with self.assertRaises(TypeError):
            manifest.support_sha256["src/aac/other.py"] = SHA_A  # type: ignore[index]


@unittest.skipIf(RefereeCaseManifest is None, "corpus contracts not implemented")
class RefereeManifestContractTests(unittest.TestCase):
    def test_harmful_and_clean_truth_contracts_are_closed(self) -> None:
        public = PublicCaseManifest.from_mapping(public_mapping(CASE_HARMFUL))
        harmful = RefereeCaseManifest.from_mapping(
            referee_mapping(CASE_HARMFUL, public.public_manifest_sha256)
        )
        self.assertEqual(harmful.expected_disposition.value, "REJECT")

        clean_public = PublicCaseManifest.from_mapping(public_mapping(CASE_CLEAN))
        clean = RefereeCaseManifest.from_mapping(
            referee_mapping(CASE_CLEAN, clean_public.public_manifest_sha256, clean=True)
        )
        self.assertIsNone(clean.mutation_class)
        self.assertEqual(clean.expected_disposition.value, "ACCEPT")

    def test_clean_cannot_carry_mutation_class_or_reject_verdict(self) -> None:
        public = PublicCaseManifest.from_mapping(public_mapping(CASE_CLEAN))
        with self.assertRaises(ValueError):
            RefereeCaseManifest.from_mapping(
                referee_mapping(
                    CASE_CLEAN,
                    public.public_manifest_sha256,
                    clean=True,
                    mutation_class="authority_bypass",
                )
            )


@unittest.skipIf(CorpusManifest is None, "corpus contracts not implemented")
class CorpusManifestContractTests(unittest.TestCase):
    def _pair(self, case_id: str, *, clean: bool = False):
        public = PublicCaseManifest.from_mapping(public_mapping(case_id))
        referee = RefereeCaseManifest.from_mapping(
            referee_mapping(
                case_id,
                public.public_manifest_sha256,
                clean=clean,
            )
        )
        return public, referee

    def test_public_projection_contains_no_referee_truth(self) -> None:
        harmful = self._pair(CASE_HARMFUL)
        clean = self._pair(CASE_CLEAN, clean=True)
        manifest = CorpusManifest.build(
            corpus_id="r-eval-indep-1-dev-v1",
            runner_sha256=SHA_C,
            public_cases=(harmful[0], clean[0]),
            referee_cases=(harmful[1], clean[1]),
        )

        public_projection = manifest.to_public_mapping()
        self.assertEqual(
            set(public_projection),
            {
                "schema_version",
                "corpus_id",
                "runner_sha256",
                "public_cases",
                "public_cases_sha256",
                "public_projection_sha256",
            },
        )
        serialized = str(public_projection).lower()
        for forbidden in (
            "case_truth",
            "mutation_class",
            "oracle_relpath",
            "expected_disposition",
            "referee_manifest",
        ):
            self.assertNotIn(forbidden, serialized)

        round_trip = CorpusManifest.from_mapping(manifest.to_mapping())
        self.assertEqual(round_trip.corpus_manifest_sha256, manifest.corpus_manifest_sha256)

    def test_duplicate_case_ids_and_case_set_mismatch_fail_closed(self) -> None:
        harmful = self._pair(CASE_HARMFUL)
        with self.assertRaises(ValueError):
            CorpusManifest.build(
                corpus_id="r-eval-indep-1-dev-v1",
                runner_sha256=SHA_C,
                public_cases=(harmful[0], harmful[0]),
                referee_cases=(harmful[1], harmful[1]),
            )
        with self.assertRaises(ValueError):
            CorpusManifest.build(
                corpus_id="r-eval-indep-1-dev-v1",
                runner_sha256=SHA_C,
                public_cases=(harmful[0],),
                referee_cases=(),
            )

    def test_build_revalidates_supplied_manifest_instances(self) -> None:
        public, referee = self._pair(CASE_HARMFUL)
        drifted_public = dataclasses.replace(
            public, public_manifest_sha256=SHA_A
        )
        with self.assertRaises(ValueError):
            CorpusManifest.build(
                corpus_id="r-eval-indep-1-dev-v1",
                runner_sha256=SHA_C,
                public_cases=(drifted_public,),
                referee_cases=(referee,),
            )


class CorpusContractRedGate(unittest.TestCase):
    def test_corpus_contract_module_exists(self) -> None:
        self.assertIsNotNone(PublicCaseManifest)
        self.assertIsNotNone(RefereeCaseManifest)
        self.assertIsNotNone(CorpusManifest)


if __name__ == "__main__":
    unittest.main()
