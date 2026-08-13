from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class HistoryInventoryError(ValueError):
    """Raised when a complete, deterministic Git history inventory cannot be built."""


@dataclass(frozen=True, order=True)
class BlobRecord:
    object_id: str
    path: str
    size: int
    binary: bool
    lfs_pointer: bool


@dataclass(frozen=True)
class HistoryInventory:
    ref_sha: str
    commits: int
    trees: int
    blob_object_count: int
    blobs: tuple[BlobRecord, ...]
    lfs_pointers: tuple[BlobRecord, ...]
    oversized_blobs: tuple[BlobRecord, ...]
    paths: tuple[str, ...]
    max_blob_bytes: int

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ref_sha": self.ref_sha,
            "commits": self.commits,
            "trees": self.trees,
            "blob_object_count": self.blob_object_count,
            "blobs": [asdict(item) for item in self.blobs],
            "lfs_pointers": [asdict(item) for item in self.lfs_pointers],
            "oversized_blobs": [asdict(item) for item in self.oversized_blobs],
            "paths": list(self.paths),
            "max_blob_bytes": self.max_blob_bytes,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def canonical_json(self) -> str:
        return json.dumps(
            self._payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "sha256": self.sha256}


def _git(repo: Path, *args: str, input_text: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            input=input_text,
            check=True,
            capture_output=True,
            text=True,
            errors="surrogateescape",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise HistoryInventoryError(f"git {' '.join(args)} failed: {detail.strip()}") from exc
    return result.stdout


def _blob_prefix(repo: Path, object_id: str, *, limit: int = 8192) -> bytes:
    process = subprocess.Popen(
        ["git", "-C", str(repo), "cat-file", "blob", object_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    prefix = process.stdout.read(limit)
    process.terminate()
    try:
        process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
    if process.returncode not in (0, -15):
        raise HistoryInventoryError(f"cannot inspect blob prefix for {object_id}")
    return prefix


def _resolve_commit(repo: Path, ref: str) -> str:
    if not ref or ref.startswith("-"):
        raise HistoryInventoryError("ref must identify one commit")
    resolved = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    if len(resolved) != 40 or any(ch not in "0123456789abcdef" for ch in resolved):
        raise HistoryInventoryError("ref must resolve to one full 40-character commit SHA")
    return resolved


def inventory_history(
    *, repo: Path, ref: str, max_blob_bytes: int = 10 * 1024 * 1024
) -> HistoryInventory:
    repo = repo.resolve()
    if max_blob_bytes <= 0:
        raise HistoryInventoryError("max_blob_bytes must be positive")
    if not (repo / ".git").exists():
        raise HistoryInventoryError(f"repository has no .git entry: {repo}")

    ref_sha = _resolve_commit(repo, ref)
    object_lines = _git(repo, "rev-list", "--objects", ref_sha).splitlines()
    object_paths: dict[str, set[str]] = {}
    for line in object_lines:
        object_id, separator, path = line.partition(" ")
        object_paths.setdefault(object_id, set())
        if separator and path:
            object_paths[object_id].add(path)

    object_ids = sorted(object_paths)
    batch_input = "".join(f"{object_id}\n" for object_id in object_ids)
    metadata_lines = _git(
        repo,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        input_text=batch_input,
    ).splitlines()
    if len(metadata_lines) != len(object_ids):
        raise HistoryInventoryError("Git object metadata count mismatch")

    commits = 0
    trees = 0
    blob_object_count = 0
    blob_records: list[BlobRecord] = []
    for line in metadata_lines:
        fields = line.split()
        if len(fields) != 3:
            raise HistoryInventoryError(f"invalid Git object metadata: {line!r}")
        object_id, object_type, raw_size = fields
        size = int(raw_size)
        if object_type == "commit":
            commits += 1
            continue
        if object_type == "tree":
            trees += 1
            continue
        if object_type != "blob":
            continue
        blob_object_count += 1
        prefix = _blob_prefix(repo, object_id)
        is_lfs = prefix.startswith(b"version https://git-lfs.github.com/spec/v1\n")
        is_binary = b"\x00" in prefix
        paths = object_paths[object_id] or {""}
        blob_records.extend(
            BlobRecord(
                object_id=object_id,
                path=path,
                size=size,
                binary=is_binary,
                lfs_pointer=is_lfs,
            )
            for path in paths
        )

    blobs = tuple(sorted(blob_records))
    return HistoryInventory(
        ref_sha=ref_sha,
        commits=commits,
        trees=trees,
        blob_object_count=blob_object_count,
        blobs=blobs,
        lfs_pointers=tuple(item for item in blobs if item.lfs_pointer),
        oversized_blobs=tuple(item for item in blobs if item.size > max_blob_bytes),
        paths=tuple(sorted({item.path for item in blobs if item.path})),
        max_blob_bytes=max_blob_bytes,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory all objects reachable from one Git ref")
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--max-blob-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    inventory = inventory_history(
        repo=args.repo, ref=args.ref, max_blob_bytes=args.max_blob_bytes
    )
    args.output.write_text(
        json.dumps(inventory.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
