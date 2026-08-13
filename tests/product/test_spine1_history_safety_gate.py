from __future__ import annotations

import hashlib
import json

from scripts.spine1.history_safety_gate import decide


def _inventory() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "ref_sha": "a" * 40,
        "commits": 1,
        "trees": 1,
        "blob_object_count": 1,
        "blobs": [],
        "lfs_pointers": [],
        "oversized_blobs": [],
        "paths": ["README.md"],
        "max_blob_bytes": 10,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {**payload, "sha256": hashlib.sha256(canonical.encode()).hexdigest()}


def _scanner(*findings: dict[str, object]) -> dict[str, object]:
    return {
        "scanner": "gitleaks",
        "scanner_version": "8.29.1",
        "config_digest": "b" * 64,
        "binary_sha256": "c" * 64,
        "findings": list(findings),
    }


def _manual(*findings: dict[str, object]) -> dict[str, object]:
    return {
        "adjudicator": "security-reviewer",
        "inventory_sha256": _inventory()["sha256"],
        "donor_sha": "a" * 40,
        "pii_status": "NO_UNRESOLVED_FINDINGS",
        "license_status": "NO_UNRESOLVED_FINDINGS",
        "findings": list(findings),
    }


def _finding() -> dict[str, object]:
    return {
        "object_id": "d" * 40,
        "path": "fixture.env",
        "rule_id": "github-pat",
        "category": "SECRET",
        "match": "must-never-enter-report",
    }


def test_missing_scanner_result_aborts() -> None:
    verdict = decide(
        inventory=_inventory(), scanner=None, adjudications=_manual(), donor_sha="a" * 40
    )
    assert verdict.verdict == "ABORT"


def test_unresolved_secret_requires_remediation() -> None:
    verdict = decide(
        inventory=_inventory(),
        scanner=_scanner(_finding()),
        adjudications=_manual(),
        donor_sha="a" * 40,
    )
    assert verdict.verdict == "REMEDIATE"
    assert verdict.unresolved_findings == 1


def test_inventory_digest_tamper_aborts() -> None:
    inventory = _inventory()
    inventory["paths"] = ["tampered"]
    verdict = decide(
        inventory=inventory,
        scanner=_scanner(),
        adjudications=_manual(),
        donor_sha="a" * 40,
    )
    assert verdict.verdict == "ABORT"


def test_resolved_finding_can_pass_without_leaking_match_content() -> None:
    finding = _finding()
    adjudication = {
        key: finding[key] for key in ("object_id", "path", "rule_id", "category")
    }
    adjudication.update(
        {
            "disposition": "SAFE_TEST_FIXTURE",
            "rationale": "Synthetic canary only; no credential value is valid.",
        }
    )
    verdict = decide(
        inventory=_inventory(),
        scanner=_scanner(finding),
        adjudications=_manual(adjudication),
        donor_sha="a" * 40,
    )
    assert verdict.verdict == "PASS"
    assert "must-never-enter-report" not in json.dumps(verdict.report)
    assert verdict.report["findings"][0]["disposition"] == "SAFE_TEST_FIXTURE"
