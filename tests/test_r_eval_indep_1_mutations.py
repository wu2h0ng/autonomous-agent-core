from __future__ import annotations

import unittest

from experiments.r_eval_indep_1.contracts import MutationClass, canonical_digest
from experiments.r_eval_indep_1.mutations import (
    REGISTRY,
    MutationFixture,
    public_bundle_for_fixture,
    qualify_all_dev,
    registry_digest,
    validate_registry,
)


class DeterministicMutationRegistryTests(unittest.TestCase):
    def test_registry_entries_are_closed_contracts(self) -> None:
        payload = REGISTRY[0].to_mapping()
        payload["unknown"] = "must-not-pass"
        with self.assertRaises(ValueError):
            MutationFixture.from_mapping(payload)

    def test_registry_covers_every_first_wave_mutation_class(self) -> None:
        validate_registry(REGISTRY)
        self.assertEqual({entry.mutation_class for entry in REGISTRY}, set(MutationClass))
        self.assertGreaterEqual(len(REGISTRY), len(MutationClass))

    def test_each_fixture_qualifies_as_dev_not_evidence(self) -> None:
        records = qualify_all_dev(REGISTRY)
        self.assertEqual(len(records), len(REGISTRY))
        for record in records:
            self.assertEqual(record.status, "QUALIFIED_DEV_NOT_EVIDENCE")
            self.assertTrue(record.base_oracle_passed)
            self.assertTrue(record.mutant_oracle_rejected)
            self.assertTrue(record.public_check_passed)

    def test_public_bundle_has_only_the_closed_public_field_set(self) -> None:
        expected_fields = {
            "case_id",
            "source_language",
            "base_snapshot_sha256",
            "candidate_patch",
            "public_requirements",
            "public_checks",
            "public_manifest_sha256",
        }
        private_fields = {"mutation_class", "case_truth", "oracle_id", "fixture_id"}
        for entry in REGISTRY:
            bundle = public_bundle_for_fixture(entry)
            payload = bundle.to_mapping()
            payload_digest = canonical_digest(payload)
            self.assertRegex(payload_digest, r"^[0-9a-f]{64}$")
            self.assertEqual(set(payload), expected_fields)
            self.assertTrue(private_fields.isdisjoint(payload))
            self.assertEqual(payload["case_id"], entry.case_id)
            self.assertEqual(payload["public_checks"], ["python -m py_compile module.py"])

    def test_registry_digest_is_deterministic_and_not_constant(self) -> None:
        first = registry_digest(REGISTRY)
        second = registry_digest(tuple(REGISTRY))
        changed = registry_digest(REGISTRY[:-1])
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)


if __name__ == "__main__":
    unittest.main()
