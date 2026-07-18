from __future__ import annotations

import gzip
import subprocess
from pathlib import Path

import pytest


PACKAGE = Path(__file__).resolve().parents[2] / "experiments" / "r_nonoracle_perturb_kill_1"


def _compile_scanner(tmp_path: Path, *, fail_fsync: bool = False) -> Path:
    binary = tmp_path / "matrix_scan"
    command = ["cc", "-O2", "-Wall", "-Wextra", "-Werror"]
    if fail_fsync:
        wrapper = tmp_path / "fail_fsync.c"
        wrapper.write_text(
            "#include <errno.h>\n"
            "int test_fsync(int fd) { (void)fd; errno = EIO; return -1; }\n",
            encoding="ascii",
        )
        command.extend(["-Dfsync=test_fsync", str(wrapper)])
    command.extend([str(PACKAGE / "matrix_scan.c"), "-lz", "-o", str(binary)])
    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return binary


def _write_matrix(path: Path, entries: list[str], *, declared_nnz: int | None = None) -> None:
    nnz = len(entries) if declared_nnz is None else declared_nnz
    body = "\n".join(
        [
            "%%MatrixMarket matrix coordinate integer general",
            "% fixture",
            f"5 2 {nnz}",
            *entries,
            "",
        ]
    )
    with gzip.open(path, "wt", encoding="ascii", newline="") as handle:
        handle.write(body)


def _run(scanner: Path, matrix: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(scanner), str(matrix), str(output), "5", "2", "5", "3", "2", "2"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_scanner_counts_only_rna_rows_and_tracks_mt_exactly(tmp_path: Path) -> None:
    scanner = _compile_scanner(tmp_path)
    matrix = tmp_path / "matrix.mtx.gz"
    output = tmp_path / "metrics.tsv"
    _write_matrix(matrix, ["1 1 10", "2 1 2", "4 1 7", "1 2 5", "3 2 3"])

    result = _run(scanner, matrix, output)

    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="ascii") == (
        "cell_index\ttotal_umi\tdetected_features\tmt_umi\n"
        "1\t12\t2\t2\n"
        "2\t8\t2\t0\n"
    )


@pytest.mark.parametrize(
    ("entries", "declared_nnz", "message"),
    [
        (["1 1 10", "1 1 2", "4 1 7", "1 2 5", "3 2 3"], None, "order or duplicate"),
        (["2 1 2", "1 1 10", "4 1 7", "1 2 5", "3 2 3"], None, "order or duplicate"),
        (["1 1 10", "2 1 2", "4 1 7", "1 2 5"], 5, "nnz"),
        (["1 1 -10", "2 1 2", "4 1 7", "1 2 5", "3 2 3"], None, "coordinate or value"),
    ],
)
def test_scanner_fails_closed_on_duplicate_order_or_nnz_drift(
    tmp_path: Path,
    entries: list[str],
    declared_nnz: int | None,
    message: str,
) -> None:
    scanner = _compile_scanner(tmp_path)
    matrix = tmp_path / "bad.mtx.gz"
    output = tmp_path / "metrics.tsv"
    _write_matrix(matrix, entries, declared_nnz=declared_nnz)

    result = _run(scanner, matrix, output)

    assert result.returncode != 0
    assert message in result.stderr.lower()
    assert not output.exists()


def test_scanner_rejects_invalid_feature_and_mt_boundaries(tmp_path: Path) -> None:
    scanner = _compile_scanner(tmp_path)
    matrix = tmp_path / "matrix.mtx.gz"
    output = tmp_path / "metrics.tsv"
    _write_matrix(matrix, ["1 1 10", "2 1 2", "4 1 7", "1 2 5", "3 2 3"])

    result = subprocess.run(
        [str(scanner), str(matrix), str(output), "5", "2", "5", "3", "4", "4"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "mt boundary" in result.stderr.lower()
    assert not output.exists()


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["4", "2", "5", "3", "2", "2"], "dimensions"),
        (["5", "2", "5", "6", "2", "2"], "feature boundary"),
    ],
)
def test_scanner_rejects_dimension_or_rna_feature_boundary_drift(
    tmp_path: Path, arguments: list[str], message: str
) -> None:
    scanner = _compile_scanner(tmp_path)
    matrix = tmp_path / "matrix.mtx.gz"
    output = tmp_path / "metrics.tsv"
    _write_matrix(matrix, ["1 1 10", "2 1 2", "4 1 7", "1 2 5", "3 2 3"])

    result = subprocess.run(
        [str(scanner), str(matrix), str(output), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert message in result.stderr.lower()
    assert not output.exists()


def test_scanner_fsync_failure_never_exposes_final_output(tmp_path: Path) -> None:
    scanner = _compile_scanner(tmp_path, fail_fsync=True)
    matrix = tmp_path / "matrix.mtx.gz"
    output = tmp_path / "metrics.tsv"
    _write_matrix(matrix, ["1 1 10", "2 1 2", "4 1 7", "1 2 5", "3 2 3"])

    result = _run(scanner, matrix, output)

    assert result.returncode != 0
    assert "sync" in result.stderr.lower()
    assert not output.exists()
    assert tuple(tmp_path.glob("metrics.tsv.tmp.*")) == ()


def test_scanner_no_replace_publish_preserves_existing_output(tmp_path: Path) -> None:
    scanner = _compile_scanner(tmp_path)
    matrix = tmp_path / "matrix.mtx.gz"
    output = tmp_path / "metrics.tsv"
    output.write_text("existing\n", encoding="ascii")
    _write_matrix(matrix, ["1 1 10", "2 1 2", "4 1 7", "1 2 5", "3 2 3"])

    result = _run(scanner, matrix, output)

    assert result.returncode != 0
    assert output.read_text(encoding="ascii") == "existing\n"
    assert tuple(tmp_path.glob("metrics.tsv.tmp.*")) == ()
