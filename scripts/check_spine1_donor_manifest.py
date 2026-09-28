#!/usr/bin/env python3
"""SPINE-1 donor owner-completeness checker.

Encodes the ADR-0054 / donor-retirement precondition that *every* file in the
pinned Data Agent donor has exactly one migration disposition and one target
owner. It fails closed on:

  * any donor file matched by zero dispositions (unowned), or
  * any donor file matched by more than one disposition (ambiguous), or
  * with ``--strict``: any entry not ``MACHINE_VERIFIED``/``REVIEWED``, any
    ``REVIEWED`` entry without a ``reviewed_by`` identity, any ``EXTRACT*``
    target path that does not exist, a donor pin mismatch, or a low-confidence
    entry without a recommendation.

This is a governance/process tool. It does NOT migrate code, push or retire the
donor. Reachability of files is not authorization.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "docs/architecture/SPINE-1-DONOR-OWNER-COMPLETENESS-MANIFEST.yaml"
DEFAULT_DONOR = REPO_ROOT.parent / "ai-native-business-data-agent-os"

GATE_OK_STATUSES = {"MACHINE_VERIFIED", "REVIEWED"}
VALID_STATUSES = {"MACHINE_VERIFIED", "REVIEWED", "PROPOSED_UNREVIEWED"}
VALID_DISPOSITIONS = {
    "EXTRACTED",
    "EXTRACT_TO_PACKAGE",
    "EXTRACT_TO_DOMAIN_PACK",
    "RETAIN_AS_HISTORY",
    "DROP_SUPERSEDED",
    "DROP_OPERATIONAL",
    "SPLIT",
    # Terminal: the founder explicitly accepted NOT carrying this capability forward.
    "REDUCED_BY_FOUNDER",
}
EXTRACT_DISPOSITIONS = {"EXTRACTED", "EXTRACT_TO_PACKAGE", "EXTRACT_TO_DOMAIN_PACK"}
# SPLIT means the module spans generic (package) and domain (domain pack) ownership and
# must be resolved into specific entries before retirement.
NON_FINAL_DISPOSITIONS = {"SPLIT"}
VALID_RECOMMENDATION_DISPOSITIONS = VALID_DISPOSITIONS


def glob_to_regex(glob: str) -> re.Pattern[str]:
    """Translate a path glob to a regex.

    ``**`` matches across separators (a ``**/`` also matches zero directories,
    so ``a/**/b`` matches both ``a/b`` and ``a/x/b``); ``*`` within a segment;
    ``?`` a single non-separator character.
    """
    out: list[str] = []
    i = 0
    while i < len(glob):
        if glob[i : i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif glob[i : i + 2] == "**":
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def load_manifest(path: Path) -> dict:
    if yaml is None:  # pragma: no cover
        raise RuntimeError("PyYAML is required to read the manifest")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def build_matchers(entries: Iterable[dict]) -> list[tuple[dict, list[re.Pattern[str]], list[re.Pattern[str]]]]:
    """Return (entry, positive_patterns, negative_patterns).

    A glob prefixed with ``!`` is a per-entry exclusion (gitignore-like): a path
    matches an entry only if it matches a positive glob and no negative glob.
    """
    matchers = []
    for entry in entries:
        positives = [glob_to_regex(g) for g in entry["globs"] if not g.startswith("!")]
        negatives = [glob_to_regex(g[1:]) for g in entry["globs"] if g.startswith("!")]
        matchers.append((entry, positives, negatives))
    return matchers


def classify(
    files: Iterable[str],
    matchers: list[tuple[dict, list[re.Pattern[str]], list[re.Pattern[str]]]],
) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """Return (counts_by_entry_id, unmatched, ambiguous)."""
    counts: dict[str, list[str]] = {entry["id"]: [] for entry, _, _ in matchers}
    unmatched: list[str] = []
    ambiguous: list[str] = []
    for path in files:
        hits = [
            entry
            for entry, positives, negatives in matchers
            if any(p.match(path) for p in positives) and not any(n.match(path) for n in negatives)
        ]
        if not hits:
            unmatched.append(path)
        elif len(hits) > 1:
            ambiguous.append(path)
        else:
            counts[hits[0]["id"]].append(path)
    return counts, unmatched, ambiguous


def donor_files_from_git(donor: Path) -> list[str]:
    proc = subprocess.run(["git", "-C", str(donor), "ls-files"], check=True, capture_output=True, text=True)
    return [line for line in proc.stdout.splitlines() if line]


def donor_head(donor: Path) -> tuple[str, int]:
    head = subprocess.run(
        ["git", "-C", str(donor), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(donor), "status", "--porcelain"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return head, len([line for line in status.splitlines() if line])


def unreviewed_entries(manifest: dict) -> list[str]:
    return [e["id"] for e in manifest["entries"] if e.get("status") not in GATE_OK_STATUSES]


def reviewed_without_identity(manifest: dict) -> list[str]:
    default = manifest.get("reviewed_by_default")
    return [
        e["id"]
        for e in manifest["entries"]
        if e.get("status") == "REVIEWED" and not (e.get("reviewed_by") or default)
    ]


def unresolved_dispositions(manifest: dict) -> list[str]:
    return [e["id"] for e in manifest["entries"] if e["disposition"] in NON_FINAL_DISPOSITIONS]


def invalid_status(manifest: dict) -> list[str]:
    bad: list[str] = []
    for e in manifest["entries"]:
        if e.get("status") not in VALID_STATUSES:
            bad.append(f"{e['id']} status={e.get('status')}")
        elif e["status"] == "MACHINE_VERIFIED" and e["disposition"] != "EXTRACTED":
            bad.append(f"{e['id']} MACHINE_VERIFIED but disposition={e['disposition']}")
    return bad


def _looks_like_path(target: str) -> bool:
    if not target or target == "—":
        return False
    return not any(ch in target for ch in " ();+")


def _target_in_ref(repo_root: Path, ref: str, target: str) -> bool:
    """True if `target` (file or directory prefix) exists at `ref` in repo_root."""
    try:
        if "." in Path(target).name:
            proc = subprocess.run(
                ["git", "-C", str(repo_root), "cat-file", "-e", f"{ref}:{target}"],
                capture_output=True,
                text=True,
            )
            return proc.returncode == 0
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "ls-tree", "-r", "--name-only", ref, "--", target],
            check=True,
            capture_output=True,
            text=True,
        )
        return bool(proc.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def target_gaps(manifest: dict, repo_root: Path, target_ref: str | None = None) -> list[str]:
    """Return EXTRACT entries not backed by declared, existing ``verified_paths``.

    A bare directory target never counts: pre-existing package/domain-pack directories would
    otherwise satisfy the gate without any module being ported. Every EXTRACT entry must declare
    ``verified_paths`` (the concrete files the extraction produced) and each must exist.
    """
    verified_map = manifest.get("verified_paths") or {}
    gaps: list[str] = []
    for e in manifest["entries"]:
        if e["disposition"] not in EXTRACT_DISPOSITIONS:
            continue
        verified = verified_map.get(e["id"])
        if not verified:
            gaps.append(
                f"{e['id']} -> (no verified_paths; target {e.get('target')!r} not credited)"
            )
            continue
        for path in verified:
            if (repo_root / path).exists():
                continue
            if target_ref and _target_in_ref(repo_root, target_ref, path):
                continue
            gaps.append(f"{e['id']} -> {path}")
    return gaps


def low_confidence_missing_recommendations(manifest: dict) -> list[str]:
    recommendations = manifest.get("low_confidence_recommendations") or {}
    return [e["id"] for e in manifest["entries"] if e.get("confidence") == "low" and e["id"] not in recommendations]


def invalid_recommendations(manifest: dict) -> list[str]:
    bad: list[str] = []
    for entry_id, rec in (manifest.get("low_confidence_recommendations") or {}).items():
        disposition = rec.get("recommended_disposition")
        if disposition not in VALID_RECOMMENDATION_DISPOSITIONS:
            bad.append(f"{entry_id} recommended_disposition={disposition}")
    return bad


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--donor", type=Path, default=DEFAULT_DONOR)
    parser.add_argument("--files-from", type=Path, default=None, help="newline file list instead of live donor")
    parser.add_argument("--strict", action="store_true", help="retirement gate: implies --require-targets and --verify-pin")
    parser.add_argument("--require-targets", action="store_true")
    parser.add_argument("--verify-pin", action="store_true")
    parser.add_argument("--allow-partial", action="store_true", help="skip the file-count equality guard")
    parser.add_argument(
        "--target-ref",
        default="origin/main",
        help="monorepo git ref used to resolve EXTRACT* targets when absent from the worktree",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    strict = args.strict
    require_targets = args.require_targets or strict
    verify_pin = args.verify_pin or strict

    try:
        manifest = load_manifest(args.manifest)
    except FileNotFoundError:
        print(f"ERROR: manifest not found: {args.manifest}", file=sys.stderr)
        return 2
    except Exception as exc:  # malformed YAML etc.
        print(f"ERROR: cannot parse manifest: {exc}", file=sys.stderr)
        return 2

    donor_pin = manifest["donor"]["pinned_sha"]
    live_pin: str | None = None
    dirty_count: int | None = None

    if args.files_from:
        try:
            files = [line for line in args.files_from.read_text(encoding="utf-8").splitlines() if line]
        except FileNotFoundError:
            print(f"ERROR: file list not found: {args.files_from}", file=sys.stderr)
            return 2
    elif args.donor.exists():
        try:
            files = donor_files_from_git(args.donor)
            live_pin, dirty_count = donor_head(args.donor)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(f"ERROR: donor is not a readable git repository: {exc}", file=sys.stderr)
            return 2
    else:
        snapshot = REPO_ROOT / manifest["donor"]["snapshot"]
        if not snapshot.exists():
            print(f"ERROR: snapshot not found: {snapshot}", file=sys.stderr)
            return 2
        files = [line for line in snapshot.read_text(encoding="utf-8").splitlines() if line]

    bad_dispositions = [e["id"] for e in manifest["entries"] if e["disposition"] not in VALID_DISPOSITIONS]
    bad_statuses = invalid_status(manifest)
    bad_recommendations = invalid_recommendations(manifest)
    if bad_dispositions or bad_statuses or bad_recommendations:
        for item in bad_dispositions:
            print(f"INVALID disposition: {item}", file=sys.stderr)
        for item in bad_statuses:
            print(f"INVALID status: {item}", file=sys.stderr)
        for item in bad_recommendations:
            print(f"INVALID recommendation: {item}", file=sys.stderr)
        return 2

    matchers = build_matchers(manifest["entries"])
    counts, unmatched, ambiguous = classify(files, matchers)
    unreviewed = unreviewed_entries(manifest)
    reviewer_gaps = reviewed_without_identity(manifest)
    recommendation_gaps = low_confidence_missing_recommendations(manifest)
    unresolved = unresolved_dispositions(manifest)
    # Always compute the full gate picture for the report; the flags only control exit behavior.
    missing = target_gaps(manifest, REPO_ROOT, args.target_ref)
    pin_ok = (live_pin == donor_pin) if live_pin else None

    by_disposition: dict[str, int] = {}
    for entry in manifest["entries"]:
        by_disposition.setdefault(entry["disposition"], 0)
        by_disposition[entry["disposition"]] += len(counts[entry["id"]])

    count_mismatch = len(files) != manifest["donor"]["file_count"] and not args.allow_partial
    retirement_ready = not (
        unmatched
        or ambiguous
        or unreviewed
        or reviewer_gaps
        or recommendation_gaps
        or unresolved
        or missing
        or bad_statuses
        or (pin_ok is False)
        or count_mismatch
    )

    report = {
        "donor_pin": donor_pin,
        "live_donor_pin": live_pin,
        "donor_worktree_dirty_files": dirty_count,
        "donor_file_count": len(files),
        "manifest_file_count": manifest["donor"]["file_count"],
        "counts_by_disposition": by_disposition,
        "unmatched": unmatched,
        "ambiguous": ambiguous,
        "unreviewed_entries": unreviewed,
        "reviewed_without_identity": reviewer_gaps,
        "low_confidence_without_recommendation": recommendation_gaps,
        "unresolved_dispositions": unresolved,
        "missing_extract_targets": missing,
        "pin_ok": pin_ok,
        "retirement_ready": retirement_ready,
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"donor pin        : {donor_pin}" + (f" (live {live_pin}, dirty={dirty_count})" if live_pin else ""))
        print(f"donor files      : {len(files)} (manifest declares {manifest['donor']['file_count']})")
        for disposition, count in sorted(by_disposition.items()):
            print(f"  {disposition:24s} {count}")
        print(f"unmatched        : {len(unmatched)}")
        print(f"ambiguous        : {len(ambiguous)}")
        print(f"unreviewed       : {len(unreviewed)}")
        print(f"review-no-ident  : {len(reviewer_gaps)}")
        if recommendation_gaps:
            print(f"low-conf gaps    : {len(recommendation_gaps)}")
        if unresolved:
            print(f"unresolved split : {len(unresolved)}")
        if missing:
            print(f"missing targets  : {len(missing)}")
        if pin_ok is not None:
            print(f"pin_ok           : {pin_ok}")
        print(f"retirement_ready : {retirement_ready}")

    if count_mismatch:
        print(f"ERROR: file count mismatch ({len(files)} != {manifest['donor']['file_count']})", file=sys.stderr)
        return 1
    if unmatched or ambiguous:
        for path in unmatched:
            print(f"UNMATCHED: {path}", file=sys.stderr)
        for path in ambiguous:
            print(f"AMBIGUOUS: {path}", file=sys.stderr)
        return 1
    if strict and unreviewed:
        print(f"STRICT: {len(unreviewed)} entries are not MACHINE_VERIFIED/REVIEWED: {', '.join(unreviewed)}", file=sys.stderr)
        return 1
    if strict and reviewer_gaps:
        print(f"STRICT: REVIEWED without reviewed_by: {', '.join(reviewer_gaps)}", file=sys.stderr)
        return 1
    if strict and recommendation_gaps:
        print(f"STRICT: low-confidence entries without a recommendation: {', '.join(recommendation_gaps)}", file=sys.stderr)
        return 1
    if strict and unresolved:
        print(f"STRICT: SPLIT entries must be resolved into specific targets: {', '.join(unresolved)}", file=sys.stderr)
        return 1
    if verify_pin and pin_ok is False:
        print(f"STRICT: donor pin mismatch (manifest {donor_pin} != live {live_pin})", file=sys.stderr)
        return 1
    if require_targets and missing:
        for target in missing:
            print(f"MISSING TARGET: {target}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
