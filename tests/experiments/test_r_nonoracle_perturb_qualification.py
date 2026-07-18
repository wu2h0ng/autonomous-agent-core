from __future__ import annotations

import csv
import gzip
import inspect
import json
from pathlib import Path

import pytest

from experiments.r_nonoracle_perturb_kill_1.qualification import (
    QualificationError,
    QualificationInputs,
    qualify_support,
)


def _write_gzip_tsv(path: Path, rows: list[list[str]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(rows)


def _build_fixture(tmp_path: Path) -> QualificationInputs:
    barcodes: list[str] = []
    guide_rows = [["cell_barcode", "num_features", "feature_call", "num_umis"]]
    metric_rows = [["cell_index", "total_umi", "detected_features", "mt_umi"]]
    souporcell_paths: dict[int, Path] = {}
    index = 0

    donor_assignment = {5: {"A": "0", "B": "1"}, 6: {"A": "1", "B": "0"}, 7: {"A": "1", "B": "0"}, 8: {"A": "1", "B": "0"}}
    for well in range(5, 9):
        souporcell_rows = [["barcode", "status", "assignment", "log_prob_singleton", "log_prob_doublet", "cluster0", "cluster1"]]
        for donor in ("A", "B"):
            block_guides = [
                (f"OPAQUE-{target_index:02d}-{guide_index}", 10)
                for target_index in range(40)
                for guide_index in (1, 2)
            ]
            block_guides.extend(
                [
                    ("OPAQUE-FAIL-1", 9 if (well, donor) == (5, "A") else 10),
                    ("OPAQUE-FAIL-2", 10),
                ]
            )
            block_guides.extend((f"NO-TARGET-{guide_index}", 7 if guide_index < 3 else 6) for guide_index in range(1, 9))
            for guide, count in block_guides:
                for _ in range(count):
                    index += 1
                    core = f"BC{index:08d}"
                    barcode = f"{core}-{well}"
                    barcodes.append(barcode)
                    guide_rows.append([barcode, "1", guide, "5"])
                    metric_rows.append([str(index), "1000", "401", "249"])
                    souporcell_rows.append([core + "-1", "singlet", donor_assignment[well][donor], "-1", "-2", "-1", "-2"])
        index += 1
        core = f"BC{index:08d}"
        barcode = f"{core}-{well}"
        barcodes.append(barcode)
        guide_rows.append([barcode, "1", "OPAQUE-00-1", "5"])
        metric_rows.append([str(index), "1000", "401", "249"])
        souporcell_rows.append([core + "-1", "doublet", "1/0", "-1", "-2", "-1", "-2"])
        souporcell_path = tmp_path / f"souporcell-well-{well}.tsv"
        _write_gzip_tsv(souporcell_path.with_suffix(".tsv.gz"), souporcell_rows)
        souporcell_paths[well] = souporcell_path.with_suffix(".tsv.gz")

    barcodes_path = tmp_path / "barcodes.tsv.gz"
    _write_gzip_tsv(barcodes_path, [[barcode] for barcode in barcodes])
    guidecalls_path = tmp_path / "guidecalls.tsv.gz"
    _write_gzip_tsv(guidecalls_path, guide_rows)
    metrics_path = tmp_path / "metrics.tsv.gz"
    _write_gzip_tsv(metrics_path, metric_rows)
    features_path = tmp_path / "features.tsv.gz"
    feature_rows = [["ENSG-1", "OPAQUE-RNA", "Gene Expression"]]
    target_guides = [
        f"OPAQUE-{target_index:02d}-{guide_index}"
        for target_index in range(40)
        for guide_index in (1, 2)
    ]
    for guide in [*target_guides, "OPAQUE-FAIL-1", "OPAQUE-FAIL-2", *[f"NO-TARGET-{i}" for i in range(1, 9)]]:
        feature_rows.append([guide, guide, "CRISPR Guide Capture"])
    _write_gzip_tsv(features_path, feature_rows)

    donor_calls = tmp_path / "donor_calls.tsv"
    donor_calls.write_text(
        "Sample\tWell_ID\tSouporcell_call0_DonorA_or_B\tSouporcell_call1_DonorA_or_B\n"
        "stim1\t5\tA\tB\n"
        "stim2\t6\tB\tA\n"
        "stim3\t7\tB\tA\n"
        "stim4\t8\tB\tA\n",
        encoding="utf-8",
    )
    return QualificationInputs(
        barcodes=barcodes_path,
        features=features_path,
        guidecalls=guidecalls_path,
        rna_metrics=metrics_path,
        donor_calls=donor_calls,
        souporcell_by_well=souporcell_paths,
    )


def test_support_qualification_is_singlet_only_and_emits_no_target_ids(tmp_path: Path) -> None:
    inputs = _build_fixture(tmp_path)

    report = qualify_support(inputs)

    assert report["status"] == "TARGET_SUPPORT_MET / MARGIN_0 / NTC_SPLIT_PENDING"
    assert report["final_cells"] == 6959
    assert report["candidate_targets"] == 41
    assert report["eligible_targets"] == 40
    assert report["target_margin"] == 0
    assert report["eligible_aggregate_count"] == 640
    assert report["eligible_aggregate_min"] == 10
    assert report["eligible_aggregate_max"] == 10
    assert report["ntc_total_min_per_block"] == 50
    serialized = json.dumps(report, sort_keys=True)
    for forbidden in ("OPAQUE-00", "OPAQUE-FAIL", "OPAQUE-00-1", "NO-TARGET-1"):
        assert forbidden not in serialized


def test_qualification_api_has_no_guide_map_or_category_input() -> None:
    fields = set(QualificationInputs.__dataclass_fields__)
    parameters = set(inspect.signature(qualify_support).parameters)

    assert fields == {"barcodes", "features", "guidecalls", "rna_metrics", "donor_calls", "souporcell_by_well"}
    assert "guide_map" not in fields | parameters
    assert "category" not in fields | parameters


def test_duplicate_or_non_bijective_donor_rule_fails_closed(tmp_path: Path) -> None:
    inputs = _build_fixture(tmp_path)
    inputs.donor_calls.write_text(
        "Sample\tWell_ID\tSouporcell_call0_DonorA_or_B\tSouporcell_call1_DonorA_or_B\n"
        "stim1\t5\tA\tA\n"
        "stim2\t6\tB\tA\n"
        "stim3\t7\tB\tA\n"
        "stim4\t8\tB\tA\n",
        encoding="utf-8",
    )

    with pytest.raises(QualificationError, match="unique donor rule"):
        qualify_support(inputs)


def test_guide_target_must_come_from_terminal_numeric_suffix(tmp_path: Path) -> None:
    inputs = _build_fixture(tmp_path)
    with gzip.open(inputs.features, "at", encoding="utf-8", newline="") as handle:
        handle.write("BAD-GUIDE\tBAD-GUIDE\tCRISPR Guide Capture\n")

    with pytest.raises(QualificationError, match="terminal numeric suffix"):
        qualify_support(inputs)


def test_valid_multiguide_pipe_fields_are_validated_then_excluded(tmp_path: Path) -> None:
    inputs = _build_fixture(tmp_path)
    with gzip.open(inputs.guidecalls, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    rows[1][1:] = ["2", "OPAQUE-00-1|OPAQUE-01-2", "66|12"]
    _write_gzip_tsv(inputs.guidecalls, rows)

    report = qualify_support(inputs)

    assert report["exactly_one_guide"] == report["raw_barcodes"] - 1
    assert report["eligible_targets"] == 39


@pytest.mark.parametrize(
    ("num_features", "feature_call", "num_umis"),
    [
        ("2", "OPAQUE-00-1|OPAQUE-01-2", "5"),
        ("3", "OPAQUE-00-1|OPAQUE-01-2", "5|6"),
        ("2", "OPAQUE-00-1|NOT-IN-REGISTRY", "5|6"),
        ("2", "OPAQUE-00-1|OPAQUE-00-1", "5|6"),
        ("2", "OPAQUE-00-1|OPAQUE-01-2", "5|-1"),
        ("2", "OPAQUE-00-1|OPAQUE-01-2", "5|not-an-int"),
    ],
)
def test_multiguide_segments_registry_and_umis_are_strictly_validated(
    tmp_path: Path,
    num_features: str,
    feature_call: str,
    num_umis: str,
) -> None:
    inputs = _build_fixture(tmp_path)
    with gzip.open(inputs.guidecalls, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    rows[1][1:] = [num_features, feature_call, num_umis]
    _write_gzip_tsv(inputs.guidecalls, rows)

    with pytest.raises(QualificationError, match="multi-guide"):
        qualify_support(inputs)


def test_zero_guide_is_represented_by_absent_row_not_synthetic_zero_call(
    tmp_path: Path,
) -> None:
    inputs = _build_fixture(tmp_path)
    with gzip.open(inputs.guidecalls, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    rows[1][1:] = ["0", "", ""]
    _write_gzip_tsv(inputs.guidecalls, rows)

    with pytest.raises(QualificationError, match="zero-guide"):
        qualify_support(inputs)


def test_souporcell_source_barcode_must_use_raw_suffix_one(tmp_path: Path) -> None:
    inputs = _build_fixture(tmp_path)
    path = inputs.souporcell_by_well[5]
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    rows[1][0] = rows[1][0][:-1] + "2"
    _write_gzip_tsv(path, rows)

    with pytest.raises(QualificationError, match="raw suffix 1"):
        qualify_support(inputs)


def test_each_stimulated_well_requires_exact_matrix_souporcell_barcode_cores(
    tmp_path: Path,
) -> None:
    inputs = _build_fixture(tmp_path)
    path = inputs.souporcell_by_well[5]
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    rows[1][0] = "FOREIGN-BARCODE-1"
    _write_gzip_tsv(path, rows)

    with pytest.raises(QualificationError, match="barcode cores"):
        qualify_support(inputs)


@pytest.mark.parametrize(
    ("status", "assignment"),
    [
        ("triplet", "0"),
        ("singlet", "0/1"),
        ("doublet", "0"),
        ("unassigned", "2"),
    ],
)
def test_souporcell_status_and_assignment_format_are_strict(
    tmp_path: Path,
    status: str,
    assignment: str,
) -> None:
    inputs = _build_fixture(tmp_path)
    path = inputs.souporcell_by_well[5]
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    rows[1][1:3] = [status, assignment]
    _write_gzip_tsv(path, rows)

    with pytest.raises(QualificationError, match="status or assignment"):
        qualify_support(inputs)
