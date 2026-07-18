from __future__ import annotations

import hashlib
import io
import struct
import zipfile
import zlib
from pathlib import Path

import pytest

from experiments.r_nonoracle_perturb_kill_1.selective_zip import (
    ArchiveBinding,
    MemberBinding,
    ProvenanceError,
    RangeResponse,
    extract_allowlisted_members,
)


def _zip_fixture() -> tuple[bytes, bytes, dict[str, zipfile.ZipInfo]]:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("allowed/a.txt", b"allowlisted bytes")
        archive.writestr("forbidden.txt", b"must never reach builder")
    payload = stream.getvalue()
    eocd_offset = payload.rfind(b"PK\x05\x06")
    _, _, _, _, _, central_size, central_offset, _ = struct.unpack_from("<4s4H2LH", payload, eocd_offset)
    central_directory = payload[central_offset : central_offset + central_size]
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = {info.filename: info for info in archive.infolist()}
    return payload, central_directory, infos


def _bindings() -> tuple[ArchiveBinding, RangeResponse, RangeResponse, dict[str, MemberBinding], dict[str, RangeResponse]]:
    archive, central_directory, infos = _zip_fixture()
    eocd_offset = archive.rfind(b"PK\x05\x06")
    _, _, _, _, _, central_size, central_offset, _ = struct.unpack_from("<4s4H2LH", archive, eocd_offset)
    head = {"content_length": str(len(archive)), "last_modified": "stable", "accept_ranges": "bytes", "etag": "opaque"}
    archive_binding = ArchiveBinding(
        record_url="https://zenodo.org/records/5784651",
        archive_size=len(archive),
        upstream_md5=hashlib.md5(archive, usedforsecurity=False).hexdigest(),
        head_before=head,
        head_after=dict(head),
        central_directory_sha256=hashlib.sha256(central_directory).hexdigest(),
    )
    member_bindings: dict[str, MemberBinding] = {}
    ranges: dict[str, RangeResponse] = {}
    for name, info in infos.items():
        local_offset = info.header_offset
        filename_length, extra_length = struct.unpack_from("<HH", archive, local_offset + 26)
        range_end = local_offset + 30 + filename_length + extra_length + info.compress_size
        member_range = archive[local_offset:range_end]
        compressed = member_range[30 + filename_length + extra_length :]
        member_bindings[name] = MemberBinding(
            name=name,
            local_header_offset=local_offset,
            method=info.compress_type,
            compressed_size=info.compress_size,
            uncompressed_size=info.file_size,
            crc32=info.CRC,
            compressed_sha256=hashlib.sha256(compressed).hexdigest(),
            uncompressed_sha256=hashlib.sha256(zipfile.ZipFile(io.BytesIO(archive)).read(name)).hexdigest(),
        )
        ranges[name] = RangeResponse(
            content_range=f"bytes {local_offset}-{range_end - 1}/{len(archive)}",
            body=member_range,
        )
    central_range = RangeResponse(
        content_range=f"bytes {central_offset}-{central_offset + central_size - 1}/{len(archive)}",
        body=central_directory,
    )
    tail_range = RangeResponse(
        content_range=f"bytes {central_offset}-{len(archive) - 1}/{len(archive)}",
        body=archive[central_offset:],
    )
    return archive_binding, central_range, tail_range, member_bindings, ranges


def test_selective_extractor_binds_archive_central_directory_range_and_member_bytes(tmp_path: Path) -> None:
    archive, central_directory, tail, members, ranges = _bindings()

    manifest = extract_allowlisted_members(
        archive=archive,
        central_directory=central_directory,
        archive_tail=tail,
        members={"allowed/a.txt": members["allowed/a.txt"]},
        ranges={"allowed/a.txt": ranges["allowed/a.txt"]},
        allowlist=("allowed/a.txt",),
        destination=tmp_path / "builder-bytes",
    )

    assert (tmp_path / "builder-bytes" / "allowed" / "a.txt").read_bytes() == b"allowlisted bytes"
    assert not (tmp_path / "builder-bytes" / "forbidden.txt").exists()
    assert manifest["record_url"] == "https://zenodo.org/records/5784651"
    assert manifest["archive_size"] > 0
    assert manifest["member_count"] == 1
    assert manifest["eocd_central_directory_offset"] >= 0
    assert manifest["eocd_central_directory_size"] == len(central_directory.body)
    assert manifest["eocd_entry_count"] == 2
    assert manifest["members"][0]["content_range"].startswith("bytes ")
    assert "uncompressed_sha256" in manifest["members"][0]


def test_selective_extractor_rejects_extra_member_even_when_valid(tmp_path: Path) -> None:
    archive, central_directory, tail, members, ranges = _bindings()

    with pytest.raises(ProvenanceError, match="exactly match allowlist"):
        extract_allowlisted_members(
            archive=archive,
            central_directory=central_directory,
            archive_tail=tail,
            members=members,
            ranges=ranges,
            allowlist=("allowed/a.txt",),
            destination=tmp_path / "builder-bytes",
        )

    assert not (tmp_path / "builder-bytes").exists()


def test_selective_extractor_fails_closed_before_write_on_tampered_range(tmp_path: Path) -> None:
    archive, central_directory, tail, members, ranges = _bindings()
    response = ranges["allowed/a.txt"]
    tampered = response.body[:-1] + bytes([response.body[-1] ^ 1])

    with pytest.raises(ProvenanceError, match="compressed sha256"):
        extract_allowlisted_members(
            archive=archive,
            central_directory=central_directory,
            archive_tail=tail,
            members={"allowed/a.txt": members["allowed/a.txt"]},
            ranges={"allowed/a.txt": RangeResponse(response.content_range, tampered)},
            allowlist=("allowed/a.txt",),
            destination=tmp_path / "builder-bytes",
        )

    assert not (tmp_path / "builder-bytes").exists()


def test_selective_extractor_rejects_head_drift(tmp_path: Path) -> None:
    archive, central_directory, tail, members, ranges = _bindings()
    drifted = ArchiveBinding(
        record_url=archive.record_url,
        archive_size=archive.archive_size,
        upstream_md5=archive.upstream_md5,
        head_before=archive.head_before,
        head_after={**archive.head_after, "last_modified": "changed"},
        central_directory_sha256=archive.central_directory_sha256,
    )

    with pytest.raises(ProvenanceError, match="head fields changed"):
        extract_allowlisted_members(
            archive=drifted,
            central_directory=central_directory,
            archive_tail=tail,
            members={"allowed/a.txt": members["allowed/a.txt"]},
            ranges={"allowed/a.txt": ranges["allowed/a.txt"]},
            allowlist=("allowed/a.txt",),
            destination=tmp_path / "builder-bytes",
        )


def test_fabricated_central_directory_offset_is_rejected_by_eocd(tmp_path: Path) -> None:
    archive, central_directory, tail, members, ranges = _bindings()
    raw_interval, raw_total = central_directory.content_range.split()[1].split("/")
    raw_start, raw_end = (int(value) for value in raw_interval.split("-"))
    fabricated = RangeResponse(
        content_range=f"bytes {raw_start + 1}-{raw_end + 1}/{raw_total}",
        body=central_directory.body,
    )

    with pytest.raises(ProvenanceError, match="eocd central directory offset"):
        extract_allowlisted_members(
            archive=archive,
            central_directory=fabricated,
            archive_tail=tail,
            members={"allowed/a.txt": members["allowed/a.txt"]},
            ranges={"allowed/a.txt": ranges["allowed/a.txt"]},
            allowlist=("allowed/a.txt",),
            destination=tmp_path / "builder-bytes",
        )


def test_raw_deflate_fixture_is_actually_valid() -> None:
    archive, _, _, members, ranges = _bindings()
    response = ranges["allowed/a.txt"]
    filename_length, extra_length = struct.unpack_from("<HH", response.body, 26)
    compressed = response.body[30 + filename_length + extra_length :]

    assert zlib.decompress(compressed, -zlib.MAX_WBITS) == b"allowlisted bytes"
    assert archive.archive_size > len(response.body)
