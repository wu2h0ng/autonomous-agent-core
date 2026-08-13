from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PASS_DISPOSITIONS = {
    "FALSE_POSITIVE",
    "SAFE_TEST_FIXTURE",
    "LICENSE_ACCEPTED",
    "PII_NON_SENSITIVE",
}
FINDING_FIELDS = ("object_id", "path", "rule_id", "category")


@dataclass(frozen=True)
class SafetyVerdict:
    verdict: str
    report_digest: str
    unresolved_findings: int
    report: dict[str, Any]


def _canonical_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _inventory_digest(inventory: dict[str, Any]) -> str:
    payload = {key: value for key, value in inventory.items() if key != "sha256"}
    return _canonical_digest(payload)


def _finding_key(finding: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(str(finding.get(field, "")) for field in FINDING_FIELDS)  # type: ignore[return-value]


def _safe_finding(
    finding: dict[str, Any],
    *,
    adjudicator: str,
    disposition: str,
    rationale: str,
) -> dict[str, str]:
    return {
        **{field: str(finding.get(field, "")) for field in FINDING_FIELDS},
        "adjudicator": adjudicator,
        "disposition": disposition,
        "rationale": rationale,
    }


def _finalize(report: dict[str, Any], verdict: str, unresolved: int) -> SafetyVerdict:
    report = {**report, "verdict": verdict, "unresolved_findings": unresolved}
    digest = _canonical_digest(report)
    report["report_digest"] = digest
    return SafetyVerdict(
        verdict=verdict,
        report_digest=digest,
        unresolved_findings=unresolved,
        report=report,
    )


def decide(
    *,
    inventory: dict[str, Any],
    scanner: dict[str, Any] | None,
    adjudications: dict[str, Any],
    donor_sha: str,
) -> SafetyVerdict:
    report: dict[str, Any] = {
        "schema_version": 1,
        "donor_sha": donor_sha,
        "inventory_sha256": inventory.get("sha256", ""),
        "scanner": "",
        "scanner_version": "",
        "config_digest": "",
        "scanner_binary_sha256": "",
        "findings": [],
    }
    if inventory.get("sha256") != _inventory_digest(inventory):
        report["failure_reason"] = "INVENTORY_DIGEST_MISMATCH"
        return _finalize(report, "ABORT", 0)
    if inventory.get("ref_sha") != donor_sha:
        report["failure_reason"] = "DONOR_SHA_MISMATCH"
        return _finalize(report, "ABORT", 0)
    if scanner is None:
        report["failure_reason"] = "SCANNER_RESULT_MISSING"
        return _finalize(report, "ABORT", 0)

    required_scanner = (
        "scanner",
        "scanner_version",
        "config_digest",
        "binary_sha256",
        "findings",
    )
    if any(not scanner.get(field) and field != "findings" for field in required_scanner):
        report["failure_reason"] = "SCANNER_METADATA_MISSING"
        return _finalize(report, "ABORT", 0)
    if not isinstance(scanner.get("findings"), list):
        report["failure_reason"] = "SCANNER_FINDINGS_INVALID"
        return _finalize(report, "ABORT", 0)

    report.update(
        {
            "scanner": str(scanner["scanner"]),
            "scanner_version": str(scanner["scanner_version"]),
            "config_digest": str(scanner["config_digest"]),
            "scanner_binary_sha256": str(scanner["binary_sha256"]),
            "scanner_scope": scanner.get("scope", {}),
        }
    )
    if (
        adjudications.get("inventory_sha256") != inventory["sha256"]
        or adjudications.get("donor_sha") != donor_sha
    ):
        report["failure_reason"] = "ADJUDICATION_BINDING_MISMATCH"
        return _finalize(report, "ABORT", 0)
    if not adjudications.get("adjudicator"):
        report["failure_reason"] = "ADJUDICATOR_MISSING"
        return _finalize(report, "ABORT", 0)
    if adjudications.get("pii_status") not in {
        "NO_UNRESOLVED_FINDINGS",
        "RESOLVED_FINDINGS",
    } or adjudications.get("license_status") not in {
        "NO_UNRESOLVED_FINDINGS",
        "RESOLVED_FINDINGS",
    }:
        report["failure_reason"] = "MANUAL_REVIEW_INCOMPLETE"
        return _finalize(report, "REMEDIATE", 1)

    manual_findings = adjudications.get("findings", [])
    if not isinstance(manual_findings, list):
        report["failure_reason"] = "ADJUDICATION_FINDINGS_INVALID"
        return _finalize(report, "ABORT", 0)
    manual_by_key = {_finding_key(item): item for item in manual_findings}
    safe_findings: list[dict[str, str]] = []
    unresolved = 0
    adjudicator = str(adjudications["adjudicator"])

    for finding in scanner["findings"]:
        manual = manual_by_key.get(_finding_key(finding), {})
        disposition = str(manual.get("disposition", "UNRESOLVED"))
        rationale = str(manual.get("rationale", "No adjudication supplied."))
        if disposition not in PASS_DISPOSITIONS:
            unresolved += 1
        safe_findings.append(
            _safe_finding(
                finding,
                adjudicator=adjudicator,
                disposition=disposition,
                rationale=rationale,
            )
        )

    scanner_keys = {_finding_key(item) for item in scanner["findings"]}
    for finding in manual_findings:
        if _finding_key(finding) in scanner_keys:
            continue
        disposition = str(finding.get("disposition", "UNRESOLVED"))
        if disposition not in PASS_DISPOSITIONS:
            unresolved += 1
        safe_findings.append(
            _safe_finding(
                finding,
                adjudicator=adjudicator,
                disposition=disposition,
                rationale=str(finding.get("rationale", "No rationale supplied.")),
            )
        )

    report["findings"] = sorted(
        safe_findings,
        key=lambda item: tuple(item[field] for field in FINDING_FIELDS),
    )
    report["manual_review"] = {
        "adjudicator": adjudicator,
        "pii_status": adjudications["pii_status"],
        "license_status": adjudications["license_status"],
        "rationale": str(adjudications.get("rationale", "")),
    }
    return _finalize(report, "PASS" if unresolved == 0 else "REMEDIATE", unresolved)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_gitleaks(raw: Any, *, config: Path) -> dict[str, Any]:
    binary = shutil.which("gitleaks")
    if binary is None:
        raise RuntimeError("gitleaks binary is missing")
    version_result = subprocess.run(
        [binary, "version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if "8.29.1" not in version_result:
        raise RuntimeError(f"unexpected gitleaks version: {version_result}")
    if not isinstance(raw, list):
        raise RuntimeError("gitleaks JSON report must be a list")
    findings = [
        {
            "object_id": str(item.get("Commit") or item.get("ObjectID") or ""),
            "path": str(item.get("File") or ""),
            "rule_id": str(item.get("RuleID") or ""),
            "category": "SECRET",
        }
        for item in raw
    ]
    return {
        "scanner": "gitleaks",
        "scanner_version": "8.29.1",
        "config_digest": _sha256_file(config),
        "binary_sha256": _sha256_file(Path(binary)),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Adjudicate the SPINE-1 history gate")
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--scanner", required=True, type=Path)
    parser.add_argument("--adjudications", required=True, type=Path)
    parser.add_argument("--donor-sha", required=True)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("gitleaks-v8.29.1.toml"),
    )
    args = parser.parse_args()

    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    raw_scanner = json.loads(args.scanner.read_text(encoding="utf-8"))
    scanner = _normalize_gitleaks(raw_scanner, config=args.config)
    scanner["scope"] = {
        "mode": "GIT_LOG_OPTS_EXACT_REF",
        "log_opts": args.donor_sha,
        "redacted": True,
    }
    adjudications = json.loads(args.adjudications.read_text(encoding="utf-8"))
    verdict = decide(
        inventory=inventory,
        scanner=scanner,
        adjudications=adjudications,
        donor_sha=args.donor_sha,
    )
    args.report.write_text(
        json.dumps(verdict.report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "program": "T-P-OS-SPINE-1",
        "status": f"G2_{verdict.verdict}",
        "donor_sha": args.donor_sha,
        "inventory_sha256": inventory.get("sha256", ""),
        "history_safety_report": str(args.report),
        "report_digest": verdict.report_digest,
        "scanner": {
            "name": scanner["scanner"],
            "version": scanner["scanner_version"],
            "binary_sha256": scanner["binary_sha256"],
            "config_digest": scanner["config_digest"],
            "scope": scanner["scope"],
        },
        "import_commit": None,
        "imported_path": None,
        "boundary": "No import is authorized unless status is G2_PASS.",
    }
    args.manifest.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return 0 if verdict.verdict == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
