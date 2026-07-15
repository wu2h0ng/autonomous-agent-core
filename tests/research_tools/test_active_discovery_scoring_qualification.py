from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_tools.active_discovery.scoring_qualification import (
    QUALIFICATION_MANIFEST_SCHEMA,
    build_qualification_manifest,
    build_qualification_records,
    load_qualification_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPO_ROOT
    / "research_tools/active_discovery/scoring_qualification_manifest.json"
)


def test_qualification_has_exact_16_behavior_distinct_and_label_isomorphic_records() -> None:
    records = build_qualification_records()

    assert len(records) == 16
    assert {record.family_code for record in records} == {"F1", "F2", "F3", "F4"}
    assert {record.semantic_variant for record in records} == {"A", "B"}
    assert {record.label_permutation for record in records} == {0, 1}
    assert len({record.record_id for record in records}) == 16
    assert len({record.raw_sha256 for record in records}) == 16
    assert all(record.split == "Q-SCORE" for record in records)
    assert all(record.scientific_use == "PERMANENTLY_EXCLUDED" for record in records)

    for family_code in ("F1", "F2", "F3", "F4"):
        family = [record for record in records if record.family_code == family_code]
        for variant in ("A", "B"):
            permutations = [
                record for record in family if record.semantic_variant == variant
            ]
            assert len(permutations) == 2
            assert len({record.behavior_signature for record in permutations}) == 1
            assert len({record.label_map_digest for record in permutations}) == 2
        signatures = {
            record.semantic_variant: record.behavior_signature for record in family
        }
        assert signatures["A"] != signatures["B"]


def test_qualification_raw_bytes_and_materialized_manifest_replay() -> None:
    records = build_qualification_records()
    for record in records:
        assert hashlib.sha256(record.raw_bytes).hexdigest() == record.raw_sha256
        raw = json.loads(record.raw_bytes)
        assert raw["record_id"] == record.record_id
        assert raw["behavior_signature"] == record.behavior_signature

    expected = build_qualification_manifest()
    materialized = load_qualification_manifest(MANIFEST_PATH)
    assert materialized == expected
    assert materialized["schema_version"] == QUALIFICATION_MANIFEST_SCHEMA
    assert materialized["mode"] == "NOT_EVIDENCE"
    assert materialized["record_count"] == 16
    assert materialized["scientific_use"] == "PERMANENTLY_EXCLUDED"


def test_qualification_does_not_modify_accepted_family_source() -> None:
    opaque_graph = REPO_ROOT / "research_tools/active_discovery/families/opaque_graph.py"
    assert hashlib.sha256(opaque_graph.read_bytes()).hexdigest() == (
        "1a2a3565035422a7ee60aac2e193a17e475307ecda08b18dc5c837f3c11cf405"
    )
