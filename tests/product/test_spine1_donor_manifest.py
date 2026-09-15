from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_spine1_donor_manifest import (  # noqa: E402
    DEFAULT_MANIFEST,
    build_matchers,
    classify,
    glob_to_regex,
    load_manifest,
    low_confidence_missing_recommendations,
    main,
    target_gaps,
    unresolved_dispositions,
    unreviewed_entries,
)


def _write_manifest(tmp_path: Path, entries: list[dict], file_count: int, recommendations: dict | None = None) -> Path:
    manifest = {
        "donor": {"repository": "x", "pinned_sha": "deadbeef", "snapshot": "unused", "file_count": file_count},
        "entries": entries,
        "low_confidence_recommendations": recommendations or {},
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return path


def _write_files(tmp_path: Path, files: list[str]) -> Path:
    path = tmp_path / "files.txt"
    path.write_text("\n".join(files) + "\n", encoding="utf-8")
    return path


# --- glob semantics -----------------------------------------------------------------


def test_glob_double_star_crosses_directories() -> None:
    pattern = glob_to_regex("packages/os_core/src/agent_os_core/sql_safety/**")
    assert pattern.match("packages/os_core/src/agent_os_core/sql_safety/__init__.py")
    assert not pattern.match("packages/os_core/src/agent_os_core/report/__init__.py")


def test_glob_midpath_double_star_matches_zero_and_many_dirs() -> None:
    pattern = glob_to_regex("a/**/b.py")
    assert pattern.match("a/b.py")
    assert pattern.match("a/x/y/b.py")
    assert not pattern.match("a/xb.py")  # regression: must not swallow a sibling file


def test_glob_single_star_stays_in_segment() -> None:
    pattern = glob_to_regex("docs/*.md")
    assert pattern.match("docs/README.md")
    assert not pattern.match("docs/sub/README.md")


# --- classify -----------------------------------------------------------------------


def test_classify_flags_unowned_file() -> None:
    matchers = build_matchers([{"id": "A", "globs": ["a/**"]}])
    counts, unmatched, ambiguous = classify(["a/x.py", "b/y.py"], matchers)
    assert counts["A"] == ["a/x.py"]
    assert unmatched == ["b/y.py"]
    assert ambiguous == []


def test_classify_flags_ambiguous_file() -> None:
    matchers = build_matchers([{"id": "A", "globs": ["a/**"]}, {"id": "B", "globs": ["a/**"]}])
    counts, unmatched, ambiguous = classify(["a/x.py"], matchers)
    assert ambiguous == ["a/x.py"]
    assert unmatched == []
    assert counts["A"] == []
    assert counts["B"] == []


# --- falsifiable unit checks on the review helpers ----------------------------------


def test_unreviewed_entries_is_falsifiable() -> None:
    assert unreviewed_entries({"entries": [{"id": "A", "status": "PROPOSED_UNREVIEWED"}]}) == ["A"]
    assert unreviewed_entries({"entries": [{"id": "A", "status": "REVIEWED"}]}) == []


def test_low_confidence_missing_recommendations_is_falsifiable() -> None:
    manifest = {
        "entries": [{"id": "A", "confidence": "low"}, {"id": "B", "confidence": "high"}],
        "low_confidence_recommendations": {},
    }
    assert low_confidence_missing_recommendations(manifest) == ["A"]
    manifest["low_confidence_recommendations"] = {"A": {"recommended_disposition": "DROP_SUPERSEDED"}}
    assert low_confidence_missing_recommendations(manifest) == []


# --- CLI gate behavior (drives main, not just helpers) ------------------------------


def test_cli_clean_manifest_passes_strict(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        [{"id": "A", "disposition": "RETAIN_AS_HISTORY", "status": "REVIEWED", "reviewed_by": "cto", "globs": ["a/**"]}],
        file_count=1,
    )
    files = _write_files(tmp_path, ["a/x.py"])
    assert main(["--manifest", str(manifest), "--files-from", str(files), "--strict"]) == 0


def test_cli_unmatched_file_fails(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        [{"id": "A", "disposition": "RETAIN_AS_HISTORY", "status": "REVIEWED", "reviewed_by": "cto", "globs": ["a/**"]}],
        file_count=2,
    )
    files = _write_files(tmp_path, ["a/x.py", "b/y.py"])
    assert main(["--manifest", str(manifest), "--files-from", str(files)]) == 1


def test_cli_ambiguous_file_fails(tmp_path: Path) -> None:
    entries = [
        {"id": "A", "disposition": "RETAIN_AS_HISTORY", "status": "REVIEWED", "reviewed_by": "cto", "globs": ["a/**"]},
        {"id": "B", "disposition": "RETAIN_AS_HISTORY", "status": "REVIEWED", "reviewed_by": "cto", "globs": ["a/**"]},
    ]
    manifest = _write_manifest(tmp_path, entries, file_count=1)
    files = _write_files(tmp_path, ["a/x.py"])
    assert main(["--manifest", str(manifest), "--files-from", str(files)]) == 1


def test_cli_strict_blocks_unreviewed(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        [{"id": "A", "disposition": "RETAIN_AS_HISTORY", "status": "PROPOSED_UNREVIEWED", "globs": ["a/**"]}],
        file_count=1,
    )
    files = _write_files(tmp_path, ["a/x.py"])
    assert main(["--manifest", str(manifest), "--files-from", str(files), "--strict"]) == 1


def test_cli_strict_blocks_reviewed_without_identity(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        [{"id": "A", "disposition": "RETAIN_AS_HISTORY", "status": "REVIEWED", "globs": ["a/**"]}],
        file_count=1,
    )
    files = _write_files(tmp_path, ["a/x.py"])
    assert main(["--manifest", str(manifest), "--files-from", str(files), "--strict"]) == 1


def test_cli_invalid_disposition_exits_2(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        [{"id": "A", "disposition": "TOTALLY_WRONG", "status": "REVIEWED", "reviewed_by": "cto", "globs": ["a/**"]}],
        file_count=1,
    )
    files = _write_files(tmp_path, ["a/x.py"])
    assert main(["--manifest", str(manifest), "--files-from", str(files)]) == 2


def test_cli_strict_blocks_unresolved_split(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        [{"id": "A", "disposition": "SPLIT", "status": "REVIEWED", "reviewed_by": "cto", "globs": ["a/**"]}],
        file_count=1,
    )
    files = _write_files(tmp_path, ["a/x.py"])
    assert main(["--manifest", str(manifest), "--files-from", str(files), "--strict"]) == 1


def test_cli_strict_blocks_missing_low_confidence_recommendation(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        [{"id": "A", "disposition": "RETAIN_AS_HISTORY", "status": "REVIEWED", "confidence": "low", "reviewed_by": "cto", "globs": ["a/**"]}],
        file_count=1,
    )
    files = _write_files(tmp_path, ["a/x.py"])
    assert main(["--manifest", str(manifest), "--files-from", str(files), "--strict"]) == 1


# --- real manifest vs pinned donor snapshot ------------------------------------------


def test_real_manifest_covers_pinned_donor_snapshot() -> None:
    manifest = load_manifest(DEFAULT_MANIFEST)
    snapshot_path = REPO_ROOT / manifest["donor"]["snapshot"]
    files = [line for line in snapshot_path.read_text(encoding="utf-8").splitlines() if line]
    matchers = build_matchers(manifest["entries"])
    counts, unmatched, ambiguous = classify(files, matchers)
    assert unmatched == []
    assert ambiguous == []
    assert len(files) == manifest["donor"]["file_count"]
    assert sum(len(v) for v in counts.values()) == len(files)


def test_real_low_confidence_entries_have_recommendations() -> None:
    manifest = load_manifest(DEFAULT_MANIFEST)
    assert low_confidence_missing_recommendations(manifest) == []


def test_retirement_still_blocked_on_pending_extraction() -> None:
    """Guard: keep this failing until the extraction is actually executed.

    After review rounds 1-3 every entry is reviewed and no SPLIT remains, so the manifest-level
    blocker is now that the EXTRACT* targets do not yet exist. Flipping this test to assert
    readiness requires an accepted retirement ADR, every EXTRACT* target present, and founder
    authorization for the four gates.
    """
    manifest = load_manifest(DEFAULT_MANIFEST)
    assert unresolved_dispositions(manifest) == [], "SPLIT entries reappeared; re-review needed"
    assert target_gaps(manifest, REPO_ROOT, None), "expected pending EXTRACT* targets"
