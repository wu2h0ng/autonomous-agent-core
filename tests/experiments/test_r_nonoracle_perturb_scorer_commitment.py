from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
RECEIPT_PATH = (
    REPO_ROOT
    / "docs"
    / "research"
    / "R-NONORACLE-PERTURB-KILL-1-scorer-commitment.json"
)
HEX_256 = re.compile(r"^[0-9a-f]{64}$")


def _receipt() -> dict[str, Any]:
    return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))


def test_public_scorer_receipt_is_exactly_bound_and_commitment_only() -> None:
    raw = RECEIPT_PATH.read_bytes()
    receipt = _receipt()

    assert hashlib.sha256(raw).hexdigest() == (
        "7d679d8f5f98b56f183a0885350fa3d24468920781557eaa55eec0139f64c50a"
    )
    assert set(receipt) == {
        "algorithm",
        "binding",
        "claim_boundary",
        "counts",
        "key_commitment_sha256",
        "opaque_assignment_commitments",
        "schema",
        "status",
        "verdicts",
    }
    assert receipt["schema"] == (
        "r-nonoracle-perturb-kill-1/scorer-assignment-commitment/v1"
    )
    assert receipt["status"] == "HMAC_ASSIGNMENT_COMMITTED"
    assert receipt["claim_boundary"] == [
        "ASSIGNMENT_COMMITMENT_ONLY",
        "NOT_FROZEN",
        "NOT_RUN",
    ]
    binding = receipt["binding"]
    assert isinstance(binding, dict)
    assert binding["agent_os_head"] == "075e6df0b831ef0fc39931c8eac9056e0f89c06e"
    assert binding["selective_zip_manifest_sha256"] == (
        "e943b3a3c2457c63914538edd83f2b7eceb2f59b8bc5f7f2630d4be59f439e0a"
    )
    algorithm = receipt["algorithm"]
    assert isinstance(algorithm, dict)
    assert algorithm["id"] == "domain-separated-hmac-sha256-balanced-order/v1"
    assert algorithm["artifact_sha256"] == (
        "d56ef0226050d194fa050f3f4e703d87ab1a2a18f2d81b032731bd713a3373a7"
    )
    assert algorithm["digest"] == "HMAC-SHA256"


def test_ntc_assignment_passes_once_without_exposing_identity() -> None:
    receipt = _receipt()
    counts = receipt["counts"]
    verdicts = receipt["verdicts"]
    assert isinstance(counts, dict)
    assert isinstance(verdicts, dict)

    assert counts["eligible_target_family_count"] == 40
    assert counts["distinct_ntc_guide_count"] == 8
    assert counts["ntc_guide_count_by_side"] == {"hidden": 4, "public": 4}
    assert counts["public_ntc_group_guide_count"] == {"A": 2, "B": 2}
    ab_counts = counts["public_ntc_ab_cells_by_group_and_block"]
    assert set(ab_counts) == {"A", "B"}
    assert all(len(block_counts) == 8 for block_counts in ab_counts.values())
    assert min(
        value for block_counts in ab_counts.values() for value in block_counts.values()
    ) > 0
    side_counts = counts["ntc_cells_by_side_and_block"]
    assert isinstance(side_counts, dict)
    assert set(side_counts) == {"public", "hidden"}
    assert all(len(block_counts) == 8 for block_counts in side_counts.values())
    assert min(
        value for block_counts in side_counts.values() for value in block_counts.values()
    ) >= 25
    assert verdicts == {
        "ntc_min_25_each_side_each_block": True,
        "one_shot_no_retry": True,
        "public_ntc_ab_all_blocks_covered": True,
        "public_ntc_ab_nonempty": True,
    }

    assert HEX_256.fullmatch(receipt["key_commitment_sha256"])
    commitments = receipt["opaque_assignment_commitments"]
    assert isinstance(commitments, dict)
    assert set(commitments) == {
        "private_assignment_without_key_sha256",
        "target_guide_assignment_sha256",
        "ntc_side_assignment_sha256",
        "public_ntc_ab_assignment_sha256",
    }
    assert all(HEX_256.fullmatch(value) for value in commitments.values())

    serialized = RECEIPT_PATH.read_text(encoding="utf-8")
    for forbidden in (
        '"key_hex"',
        '"target_guide_assignment"',
        '"ntc_side_assignment"',
        '"public_ntc_ab_assignment"',
    ):
        assert forbidden not in serialized
    assert re.search(r"NO-TARGET-[0-9]+", serialized) is None
