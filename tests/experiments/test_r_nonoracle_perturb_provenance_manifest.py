from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = (
    ROOT
    / "docs"
    / "research"
    / "R-NONORACLE-PERTURB-KILL-1-selective-zip-provenance.json"
)
HEX_8 = re.compile(r"^[0-9a-f]{8}$")
HEX_32 = re.compile(r"^[0-9a-f]{32}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
CONTENT_RANGE = re.compile(r"^bytes ([0-9]+)-([0-9]+)/([0-9]+)$")
EXPECTED_MEMBERS = {
    "Perturb-seq/data/souporcell_match_vcf_res/donor_calls.txt",
    "Perturb-seq/data/souporcell/stim_well1_results/clusters.tsv",
    "Perturb-seq/data/souporcell/stim_well2_results/clusters.tsv",
    "Perturb-seq/data/souporcell/stim_well3_results/clusters.tsv",
    "Perturb-seq/data/souporcell/stim_well4_results/clusters.tsv",
}


def _load_manifest() -> dict[str, Any]:
    loaded = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_real_selective_zip_manifest_binds_archive_and_eocd() -> None:
    manifest = _load_manifest()

    assert manifest["schema"] == "selective-zip-member-provenance/v1"
    assert manifest["package_id"] == "R-NONORACLE-PERTURB-KILL-1"
    assert manifest["record_id"] == 5_784_651
    assert manifest["record_url"].endswith("/5784651")
    assert manifest["record_doi"] == "10.5281/zenodo.5784651"
    assert manifest["archive_file_name"] == "CRISPRa-Perturb-seq.zip"
    assert manifest["archive_size"] == 3_055_676_205
    assert HEX_32.fullmatch(manifest["upstream_md5"])
    assert HEX_64.fullmatch(manifest["record_json_sha256"])
    assert HEX_64.fullmatch(manifest["tail_sha256"])
    assert HEX_64.fullmatch(manifest["central_directory_sha256"])
    assert manifest["head_stable_fields"] == {
        "accept_ranges": "bytes",
        "content_length": "3055676205",
        "last_modified": "Sun, 14 Jun 2026 04:34:48 GMT",
    }
    assert manifest["tail_content_range"].endswith("-3055676204/3055676205")
    assert manifest["central_directory_content_range"] == (
        "bytes 3055656196-3055676182/3055676205"
    )
    assert manifest["eocd_central_directory_offset"] == 3_055_656_196
    assert manifest["eocd_central_directory_size"] == 19_987
    assert manifest["eocd_entry_count"] == 148


def test_manifest_allowlists_only_qualification_members_and_binds_bytes() -> None:
    manifest = _load_manifest()
    members = manifest["members"]
    names = {member["name"] for member in members}

    assert manifest["allowlist_policy"] == "qualification-inputs-only"
    assert manifest["member_count"] == len(members) == 5
    assert names == EXPECTED_MEMBERS
    assert manifest["forbidden_member"] not in names
    assert "guide-target-categories" in manifest["forbidden_member"]
    for member in members:
        match = CONTENT_RANGE.fullmatch(member["content_range"])
        assert match is not None
        start, end, total = (int(value) for value in match.groups())
        assert start == member["local_header_offset"]
        assert end >= start + member["compressed_size"]
        assert total == manifest["archive_size"]
        assert member["method"] in {0, 8}
        assert member["compressed_size"] > 0
        assert member["uncompressed_size"] > 0
        assert HEX_8.fullmatch(member["crc32"])
        assert HEX_64.fullmatch(member["compressed_sha256"])
        assert HEX_64.fullmatch(member["uncompressed_sha256"])


def test_manifest_binds_exact_qualification_source_hashes() -> None:
    source_hashes = _load_manifest()["qualification_source_sha256"]

    assert source_hashes == {
        "barcodes": "2465729feb9dd448fff059530b5fd732412c7f2c3eeddaa9dbe9a6406586fdf6",
        "features": "9905919eb3c62529f38122490f8f6472fc6ef36a43f2126ad39e3065355a34e9",
        "guidecalls": "ffd5a3050a69d013ddc09a43fae63642a7659cdb778f78c865e0829207e17b7c",
        "matrix": "38113a6099f117ed1449cfde2f9f61bf10379da262af49364308f1a0602e3fc1",
        "rna_metrics": "701827190ea31d9e3aecb7722e3022b02fe1ebd880e94c483b6d6425f4e58104",
    }
