from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.spine1.history_inventory import HistoryInventoryError, inventory_history


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def _history_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "spine1@example.invalid")
    _git(repo, "config", "user.name", "SPINE-1 Test")

    (repo / "deleted.env").write_text("TOKEN=fake-test-value\n", encoding="utf-8")
    _commit(repo, "add deleted fixture")
    (repo / "deleted.env").unlink()
    (repo / "model.bin").write_bytes(b"\x00binary-payload")
    (repo / "asset.dat").write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:" + "a" * 64 + "\n"
        "size 123\n",
        encoding="utf-8",
    )
    _commit(repo, "replace fixture")
    return repo


def test_inventory_includes_deleted_lfs_and_binary_objects(tmp_path: Path) -> None:
    repo = _history_fixture(tmp_path)

    result = inventory_history(repo=repo, ref="HEAD", max_blob_bytes=4)

    assert result.ref_sha == _git(repo, "rev-parse", "HEAD")
    assert any(item.path == "deleted.env" for item in result.blobs)
    assert any(item.path == "model.bin" for item in result.oversized_blobs)
    assert any(item.path == "asset.dat" for item in result.lfs_pointers)
    assert any(item.path == "model.bin" and item.binary for item in result.blobs)
    assert result.commits >= 2
    assert result.trees >= 2


def test_inventory_is_deterministic_and_omits_blob_contents(tmp_path: Path) -> None:
    repo = _history_fixture(tmp_path)

    first = inventory_history(repo=repo, ref="HEAD", max_blob_bytes=4)
    second = inventory_history(repo=repo, ref=first.ref_sha, max_blob_bytes=4)

    assert first.to_dict() == second.to_dict()
    serialized = first.canonical_json()
    assert "fake-test-value" not in serialized
    assert first.sha256 == second.sha256


def test_inventory_rejects_non_commit_or_invalid_threshold(tmp_path: Path) -> None:
    repo = _history_fixture(tmp_path)
    blob = _git(repo, "rev-parse", "HEAD:model.bin")

    with pytest.raises(HistoryInventoryError, match="commit"):
        inventory_history(repo=repo, ref=blob, max_blob_bytes=4)
    with pytest.raises(HistoryInventoryError, match="positive"):
        inventory_history(repo=repo, ref="HEAD", max_blob_bytes=0)
