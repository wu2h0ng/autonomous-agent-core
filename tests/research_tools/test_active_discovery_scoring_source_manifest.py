from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_tools.active_discovery.canonical import content_digest


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPO_ROOT / "research_tools/active_discovery/scoring_source_manifest.json"
)

EXPECTED_NEW_SOURCES = frozenset(
    {
        "research_tools/active_discovery/baselines.py",
        "research_tools/active_discovery/hidden_byte_codec.py",
        "research_tools/active_discovery/hidden_corpus_contracts.py",
        "research_tools/active_discovery/hidden_scoring.py",
        "research_tools/active_discovery/scored_arm_runner.py",
        "research_tools/active_discovery/scoring_collusion.py",
        "research_tools/active_discovery/scoring_contracts.py",
        "research_tools/active_discovery/scoring_qualification.py",
        "research_tools/active_discovery/scoring_referee.py",
        "research_tools/active_discovery/trace_universe_verifier.py",
    }
)
EXPECTED_NEW_DATA = frozenset(
    {
        "research_tools/active_discovery/hidden_custody_design_manifest.json",
        "research_tools/active_discovery/scoring_collusion_manifest.json",
        "research_tools/active_discovery/scoring_qualification_manifest.json",
    }
)
EXPECTED_NEW_TESTS = frozenset(
    {
        "tests/research_tools/test_active_discovery_baselines.py",
        "tests/research_tools/test_active_discovery_hidden_byte_codec.py",
        "tests/research_tools/test_active_discovery_hidden_custody.py",
        "tests/research_tools/test_active_discovery_hidden_scoring.py",
        "tests/research_tools/test_active_discovery_scored_arm_runner.py",
        "tests/research_tools/test_active_discovery_scoring_collusion.py",
        "tests/research_tools/test_active_discovery_scoring_contracts.py",
        "tests/research_tools/test_active_discovery_scoring_qualification.py",
        "tests/research_tools/test_active_discovery_scoring_referee.py",
        "tests/research_tools/test_active_discovery_scoring_source_manifest.py",
        "tests/research_tools/test_active_discovery_trace_universe_verifier.py",
    }
)


def _raw_sha256(relative_path: str) -> str:
    return hashlib.sha256((REPO_ROOT / relative_path).read_bytes()).hexdigest()


def _assert_exact_file_list(records: object, expected: frozenset[str]) -> None:
    assert isinstance(records, list)
    assert {item["path"] for item in records} == expected
    for item in records:
        assert set(item) == {"path", "sha256"}
        assert item["sha256"] == _raw_sha256(item["path"])


def test_source_manifest_binds_only_additive_scoring_bytes_and_exact_review_head() -> None:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "active-discovery-scoring-source-manifest/v1"
    assert raw["mode"] == "QUALIFIED_INSTRUMENT"
    assert raw["authority_ceiling"] == ["NOT_FROZEN", "NOT_RUN", "NOT_EVIDENCE"]
    assert raw["reviewed_spec_head"] == "e5002d784a0f43a5610d9353d7f5c84c9b6c8135"
    assert raw["self_exclusion"] == (
        "This manifest cannot bind its own bytes; its digest binds every other field."
    )
    _assert_exact_file_list(raw["new_source_files"], EXPECTED_NEW_SOURCES)
    _assert_exact_file_list(raw["new_data_files"], EXPECTED_NEW_DATA)
    _assert_exact_file_list(raw["new_test_files"], EXPECTED_NEW_TESTS)
    assert all(
        item["path"] != "research_tools/active_discovery/scoring_source_manifest.json"
        for section in ("new_source_files", "new_data_files", "new_test_files")
        for item in raw[section]
    )
    payload = {key: value for key, value in raw.items() if key != "manifest_digest"}
    assert raw["manifest_digest"] == content_digest(
        "active-discovery-scoring-source-manifest/v1", payload
    )


def test_source_manifest_locks_donors_design_authority_and_stage_a_lineage() -> None:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    _assert_exact_file_list(
        raw["accepted_donor_files"],
        frozenset(
            {
                "research_tools/active_discovery/referee.py",
                "research_tools/active_discovery/arm_runner.py",
            }
        ),
    )
    _assert_exact_file_list(
        raw["reviewed_spec_files"],
        frozenset(
            {
                "docs/superpowers/specs/2026-07-15-active-discovery-hidden-scoring-spec.md",
                "docs/superpowers/plans/2026-07-15-active-discovery-hidden-scoring-tdd-plan.md",
            }
        ),
    )
    stage_a = raw["stage_a_lineage"]
    assert stage_a == {
        "candidate_path": "research_tools/active_discovery/stage_a_prereg_candidate.json",
        "candidate_sha256": "de05497e5058e650742550d7d2c7b5ec0a4fe0bac3ea576f1b72355a87f51c85",
        "source_manifest_digest": "f9f191f06a29ba6d2becd3f817dfd406f8721dcb128f704b3db0ea3d496b7192",
    }
    assert stage_a["candidate_sha256"] == _raw_sha256(stage_a["candidate_path"])
    candidate = json.loads(
        (REPO_ROOT / stage_a["candidate_path"]).read_text(encoding="utf-8")
    )
    assert stage_a["source_manifest_digest"] == content_digest(
        "active-discovery-stage-a-source-manifest", candidate["source_manifest"]
    )
