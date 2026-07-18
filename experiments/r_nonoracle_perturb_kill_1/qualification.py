from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Mapping, Sequence


STIM_WELLS = (5, 6, 7, 8)
DONORS = ("A", "B")
SUPPORT_PER_GUIDE_BLOCK = 10
TARGET_GATE = 40
NTC_MIN_PER_SPLIT_SIDE_BLOCK = 25
_TERMINAL_SUFFIX = re.compile(r"^(.+)-([0-9]+)$")


class QualificationError(ValueError):
    """Fail-closed qualification input or join error."""


@dataclass(frozen=True)
class QualificationInputs:
    barcodes: Path
    features: Path
    guidecalls: Path
    rna_metrics: Path
    donor_calls: Path
    souporcell_by_well: Mapping[int, Path]


@dataclass(frozen=True)
class _Guide:
    target: str
    is_ntc: bool


@dataclass(frozen=True)
class _Metrics:
    total: int
    detected: int
    mt: int


def _open_text(path: Path) -> IO[str]:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _split_terminal_suffix(value: str) -> tuple[str, int]:
    match = _TERMINAL_SUFFIX.fullmatch(value)
    if match is None:
        raise QualificationError("guide feature lacks a terminal numeric suffix")
    return match.group(1), int(match.group(2))


def _read_barcodes(path: Path) -> list[str]:
    barcodes: list[str] = []
    with _open_text(path) as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) != 1 or not row[0]:
                raise QualificationError("barcode file must contain exactly one non-empty column")
            barcodes.append(row[0])
    if not barcodes or len(barcodes) != len(set(barcodes)):
        raise QualificationError("barcodes must be non-empty and unique")
    return barcodes


def _read_guides(path: Path) -> dict[str, _Guide]:
    guides: dict[str, _Guide] = {}
    with _open_text(path) as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) != 3:
                raise QualificationError("features must have exactly three columns")
            feature_id, feature_name, feature_type = row
            if feature_type != "CRISPR Guide Capture":
                continue
            if feature_id != feature_name:
                raise QualificationError("guide feature id/name mismatch is ambiguous")
            target, _ = _split_terminal_suffix(feature_id)
            if feature_id in guides:
                raise QualificationError("duplicate guide feature")
            guides[feature_id] = _Guide(target=target, is_ntc=target == "NO-TARGET")
    if not guides:
        raise QualificationError("no CRISPR Guide Capture features")
    return guides


def _read_metrics(path: Path, expected_cells: int) -> list[_Metrics]:
    expected_header = ["cell_index", "total_umi", "detected_features", "mt_umi"]
    metrics: list[_Metrics] = []
    with _open_text(path) as handle:
        reader = csv.reader(handle, delimiter="\t")
        if next(reader, None) != expected_header:
            raise QualificationError("RNA metrics header mismatch")
        for expected_index, row in enumerate(reader, start=1):
            if len(row) != 4:
                raise QualificationError("RNA metrics row width mismatch")
            try:
                index, total, detected, mt = (int(value) for value in row)
            except ValueError as error:
                raise QualificationError("RNA metrics must be integers") from error
            if index != expected_index or total < 0 or detected < 0 or mt < 0 or mt > total:
                raise QualificationError("RNA metrics index or value invariant failed")
            metrics.append(_Metrics(total=total, detected=detected, mt=mt))
    if len(metrics) != expected_cells:
        raise QualificationError("RNA metrics/barcode cardinality mismatch")
    return metrics


def _read_guidecalls(path: Path, guide_registry: Mapping[str, _Guide]) -> dict[str, tuple[str | None, int, int | None]]:
    expected_header = ["cell_barcode", "num_features", "feature_call", "num_umis"]
    calls: dict[str, tuple[str | None, int, int | None]] = {}
    with _open_text(path) as handle:
        reader = csv.reader(handle, delimiter="\t")
        if next(reader, None) != expected_header:
            raise QualificationError("guidecalls header mismatch")
        for row in reader:
            if len(row) != 4:
                raise QualificationError("guidecalls row width mismatch")
            barcode, raw_num_features, guide, raw_umis = row
            try:
                num_features = int(raw_num_features)
            except ValueError as error:
                raise QualificationError("guidecall feature count must be an integer") from error
            if barcode in calls:
                raise QualificationError("duplicate guidecall barcode")
            if num_features < 0:
                raise QualificationError("guidecall feature count must be non-negative")
            if num_features == 0:
                raise QualificationError(
                    "zero-guide cells must be represented by an absent guidecall row"
                )
            guide_names = guide.split("|")
            raw_umi_counts = raw_umis.split("|")
            if (
                len(guide_names) != num_features
                or len(raw_umi_counts) != num_features
                or len(set(guide_names)) != num_features
                or any(name not in guide_registry for name in guide_names)
            ):
                raise QualificationError(
                    "multi-guide segments must match count and guide registry"
                )
            try:
                umi_counts = [int(value) for value in raw_umi_counts]
            except ValueError as error:
                raise QualificationError(
                    "multi-guide UMI segments must be integers"
                ) from error
            if any(value < 0 for value in umi_counts):
                raise QualificationError(
                    "multi-guide UMI segments must be non-negative"
                )
            if num_features != 1:
                calls[barcode] = (None, num_features, None)
                continue
            calls[barcode] = (guide_names[0], num_features, umi_counts[0])
    return calls


def _read_donor_rules(path: Path) -> dict[int, dict[str, str]]:
    expected_header = [
        "Sample",
        "Well_ID",
        "Souporcell_call0_DonorA_or_B",
        "Souporcell_call1_DonorA_or_B",
    ]
    rules: dict[int, dict[str, str]] = {}
    with _open_text(path) as handle:
        reader = csv.reader(handle, delimiter="\t")
        if next(reader, None) != expected_header:
            raise QualificationError("donor calls header mismatch")
        for row in reader:
            if len(row) != 4:
                raise QualificationError("donor calls row width mismatch")
            _, raw_well, call0, call1 = (value.strip() for value in row)
            try:
                well = int(raw_well)
            except ValueError as error:
                raise QualificationError("donor call well must be numeric") from error
            if well not in STIM_WELLS:
                continue
            if well in rules or {call0, call1} != set(DONORS):
                raise QualificationError("each stimulated well needs one unique donor rule")
            rules[well] = {"0": call0, "1": call1}
    if set(rules) != set(STIM_WELLS):
        raise QualificationError("stimulated wells lack a unique donor rule")
    return rules


def _read_souporcell(path: Path) -> dict[str, tuple[str, str]]:
    expected_header = [
        "barcode",
        "status",
        "assignment",
        "log_prob_singleton",
        "log_prob_doublet",
        "cluster0",
        "cluster1",
    ]
    records: dict[str, tuple[str, str]] = {}
    with _open_text(path) as handle:
        reader = csv.reader(handle, delimiter="\t")
        if next(reader, None) != expected_header:
            raise QualificationError("raw Souporcell status schema mismatch")
        for row in reader:
            if len(row) != 7:
                raise QualificationError("raw Souporcell row width mismatch")
            barcode, status, assignment = row[:3]
            core, suffix = _split_terminal_suffix(barcode)
            if suffix != 1:
                raise QualificationError("Souporcell source barcode must retain raw suffix 1")
            if core in records:
                raise QualificationError("duplicate Souporcell barcode core")
            valid_assignment = (
                (status == "singlet" and assignment in {"0", "1"})
                or (status == "doublet" and assignment in {"0/1", "1/0"})
                or (
                    status == "unassigned"
                    and assignment in {"0", "1", "0/1", "1/0"}
                )
            )
            if not valid_assignment:
                raise QualificationError(
                    "Souporcell status or assignment format is invalid"
                )
            records[core] = (status, assignment)
    return records


def qualify_support(inputs: QualificationInputs) -> dict[str, Any]:
    """Apply the fixed GSE190604 pre-freeze support gate and emit aggregates only."""

    if set(inputs.souporcell_by_well) != set(STIM_WELLS):
        raise QualificationError("exactly four stimulated Souporcell inputs are required")
    barcodes = _read_barcodes(inputs.barcodes)
    guides = _read_guides(inputs.features)
    metrics = _read_metrics(inputs.rna_metrics, len(barcodes))
    calls = _read_guidecalls(inputs.guidecalls, guides)
    if not set(calls).issubset(barcodes):
        raise QualificationError("guidecalls contain barcodes absent from matrix")
    donor_rules = _read_donor_rules(inputs.donor_calls)
    souporcell = {well: _read_souporcell(path) for well, path in inputs.souporcell_by_well.items()}
    matrix_cores_by_well = {well: set() for well in STIM_WELLS}
    for barcode in barcodes:
        core, well = _split_terminal_suffix(barcode)
        if well in matrix_cores_by_well:
            matrix_cores_by_well[well].add(core)
    if any(
        matrix_cores_by_well[well] != set(souporcell[well])
        for well in STIM_WELLS
    ):
        raise QualificationError(
            "matrix and Souporcell barcode cores must match exactly per stimulated well"
        )

    stages: Counter[str] = Counter(raw_barcodes=len(barcodes))
    support: Counter[tuple[str, str, int, str]] = Counter()
    ntc_by_block: Counter[tuple[int, str]] = Counter()
    for barcode, metric in zip(barcodes, metrics, strict=True):
        call = calls.get(barcode)
        if call is None or call[1] != 1:
            continue
        stages["exactly_one_guide"] += 1
        guide_name, _, guide_umis = call
        if guide_name is None or guide_umis is None:
            raise QualificationError("single-guide record lost its validated feature or UMI")
        if guide_umis < 5:
            continue
        stages["guide_umi_ge_5"] += 1
        if metric.total == 0 or metric.mt * 4 >= metric.total:
            continue
        stages["rna_mt_fraction_lt_0_25"] += 1
        if not 400 < metric.detected < 6000:
            continue
        stages["rna_detected_features_open_400_6000"] += 1
        core, well = _split_terminal_suffix(barcode)
        if well not in STIM_WELLS:
            continue
        stages["stim_cells"] += 1
        status_assignment = souporcell[well].get(core)
        if status_assignment is None or status_assignment[0] != "singlet":
            continue
        stages["souporcell_singlets"] += 1
        assignment = status_assignment[1]
        donor = donor_rules[well].get(assignment)
        if donor is None:
            raise QualificationError("singlet assignment lacks unique donor rule")
        stages["final_cells"] += 1
        guide = guides[guide_name]
        if guide.is_ntc:
            ntc_by_block[(well, donor)] += 1
        else:
            support[(guide.target, guide_name, well, donor)] += 1

    guide_families: dict[str, set[str]] = defaultdict(set)
    for guide_name, guide in guides.items():
        if not guide.is_ntc:
            guide_families[guide.target].add(guide_name)
    if any(len(family) != 2 for family in guide_families.values()):
        raise QualificationError("every non-NTC target must derive exactly two guide features")

    eligible_targets: list[str] = []
    for target, target_guides in guide_families.items():
        counts = [
            support[(target, guide_name, well, donor)]
            for guide_name in target_guides
            for well in STIM_WELLS
            for donor in DONORS
        ]
        if min(counts, default=0) >= SUPPORT_PER_GUIDE_BLOCK:
            eligible_targets.append(target)
    eligible_counts = [
        support[(target, guide_name, well, donor)]
        for target in eligible_targets
        for guide_name in guide_families[target]
        for well in STIM_WELLS
        for donor in DONORS
    ]
    ntc_counts = [ntc_by_block[(well, donor)] for well in STIM_WELLS for donor in DONORS]
    target_margin = len(eligible_targets) - TARGET_GATE
    if target_margin < 0:
        status = "PARK_TARGET_SUPPORT / NTC_SPLIT_NOT_REACHED"
    elif min(ntc_counts, default=0) < 2 * NTC_MIN_PER_SPLIT_SIDE_BLOCK:
        status = "PARK_NTC_SPLIT_IMPOSSIBLE"
    else:
        status = "TARGET_SUPPORT_MET / MARGIN_0 / NTC_SPLIT_PENDING" if target_margin == 0 else "TARGET_SUPPORT_MET / NTC_SPLIT_PENDING"

    source_sha256 = {
        "barcodes": _sha256(inputs.barcodes),
        "features": _sha256(inputs.features),
        "guidecalls": _sha256(inputs.guidecalls),
        "rna_metrics": _sha256(inputs.rna_metrics),
        "donor_calls": _sha256(inputs.donor_calls),
        "souporcell": {str(well): _sha256(inputs.souporcell_by_well[well]) for well in STIM_WELLS},
    }
    return {
        "schema": "r-nonoracle-perturb-kill-1/data-qualification/v1",
        "status": status,
        **dict(stages),
        "candidate_targets": len(guide_families),
        "eligible_targets": len(eligible_targets),
        "target_gate": TARGET_GATE,
        "target_margin": target_margin,
        "support_per_guide_block": SUPPORT_PER_GUIDE_BLOCK,
        "natural_block_count": len(STIM_WELLS) * len(DONORS),
        "eligible_aggregate_count": len(eligible_counts),
        "eligible_aggregate_min": min(eligible_counts, default=0),
        "eligible_aggregate_max": max(eligible_counts, default=0),
        "ntc_total_min_per_block": min(ntc_counts, default=0),
        "ntc_total_max_per_block": max(ntc_counts, default=0),
        "ntc_min_per_split_side_block": NTC_MIN_PER_SPLIT_SIDE_BLOCK,
        "ntc_split_pending": True,
        "donor_labels": "OPAQUE_A_B",
        "source_sha256": source_sha256,
    }


def _parse_souporcell(value: str) -> tuple[int, Path]:
    try:
        raw_well, raw_path = value.split("=", 1)
        well = int(raw_well)
    except (ValueError, TypeError) as error:
        raise argparse.ArgumentTypeError("Souporcell input must be WELL=PATH") from error
    return well, Path(raw_path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--barcodes", required=True, type=Path)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--guidecalls", required=True, type=Path)
    parser.add_argument("--rna-metrics", required=True, type=Path)
    parser.add_argument("--donor-calls", required=True, type=Path)
    parser.add_argument("--souporcell", action="append", required=True, type=_parse_souporcell)
    arguments = parser.parse_args(argv)
    souporcell_by_well = dict(arguments.souporcell)
    report = qualify_support(
        QualificationInputs(
            barcodes=arguments.barcodes,
            features=arguments.features,
            guidecalls=arguments.guidecalls,
            rna_metrics=arguments.rna_metrics,
            donor_calls=arguments.donor_calls,
            souporcell_by_well=souporcell_by_well,
        )
    )
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
