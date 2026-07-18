from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import struct
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


_CONTENT_RANGE = re.compile(r"^bytes ([0-9]+)-([0-9]+)/([0-9]+)$")
_HEX_32 = re.compile(r"^[0-9a-f]{32}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class ProvenanceError(ValueError):
    """Fail-closed selective ZIP provenance error."""


@dataclass(frozen=True)
class ArchiveBinding:
    record_url: str
    archive_size: int
    upstream_md5: str
    head_before: Mapping[str, str]
    head_after: Mapping[str, str]
    central_directory_sha256: str


@dataclass(frozen=True)
class MemberBinding:
    name: str
    local_header_offset: int
    method: int
    compressed_size: int
    uncompressed_size: int
    crc32: int
    compressed_sha256: str
    uncompressed_sha256: str


@dataclass(frozen=True)
class RangeResponse:
    content_range: str
    body: bytes


@dataclass(frozen=True)
class _CentralEntry:
    name: str
    creator_system: int
    external_attributes: int
    flags: int
    method: int
    crc32: int
    compressed_size: int
    uncompressed_size: int
    local_header_offset: int


def _parse_central_directory(payload: bytes) -> dict[str, _CentralEntry]:
    entries: dict[str, _CentralEntry] = {}
    offset = 0
    while offset < len(payload):
        if len(payload) - offset < 46:
            raise ProvenanceError("truncated central directory")
        values = struct.unpack_from("<4s6H3L5H2L", payload, offset)
        if values[0] != b"PK\x01\x02":
            raise ProvenanceError("central directory contains non-entry bytes")
        creator_system = values[1] >> 8
        flags, method = values[3], values[4]
        crc32, compressed_size, uncompressed_size = values[7], values[8], values[9]
        filename_length, extra_length, comment_length = values[10], values[11], values[12]
        disk_start, external_attributes, local_header_offset = (
            values[13],
            values[15],
            values[16],
        )
        if disk_start != 0 or 0xFFFFFFFF in (compressed_size, uncompressed_size, local_header_offset):
            raise ProvenanceError("multi-disk or ZIP64 member is outside this tool")
        end = offset + 46 + filename_length + extra_length + comment_length
        if end > len(payload):
            raise ProvenanceError("truncated central directory entry")
        raw_name = payload[offset + 46 : offset + 46 + filename_length]
        encoding = "utf-8" if flags & 0x800 else "cp437"
        try:
            name = raw_name.decode(encoding)
        except UnicodeDecodeError as error:
            raise ProvenanceError("central directory filename is undecodable") from error
        if not name or "\x00" in name or name in entries:
            raise ProvenanceError("central directory filenames must be non-empty and unique")
        entries[name] = _CentralEntry(
            name=name,
            creator_system=creator_system,
            external_attributes=external_attributes,
            flags=flags,
            method=method,
            crc32=crc32,
            compressed_size=compressed_size,
            uncompressed_size=uncompressed_size,
            local_header_offset=local_header_offset,
        )
        offset = end
    if not entries:
        raise ProvenanceError("central directory is empty")
    return entries


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts) or "\\" in name or name.endswith("/"):
        raise ProvenanceError("allowlisted member path is unsafe")
    return path


def _parse_range(response: RangeResponse, archive_size: int, label: str) -> tuple[int, int]:
    match = _CONTENT_RANGE.fullmatch(response.content_range)
    if match is None:
        raise ProvenanceError(f"{label} Content-Range is malformed")
    start, end, total = (int(value) for value in match.groups())
    if total != archive_size or end < start or end - start + 1 != len(response.body):
        raise ProvenanceError(f"{label} Content-Range does not bind returned bytes")
    return start, end


def _parse_eocd(archive_size: int, archive_tail: RangeResponse) -> tuple[int, int, int]:
    tail_start, tail_end = _parse_range(archive_tail, archive_size, "tail range")
    if tail_end != archive_size - 1:
        raise ProvenanceError("tail range must end at archive size")
    candidates: list[tuple[int, int, int, int, int, int, int]] = []
    search_at = 0
    while True:
        offset = archive_tail.body.find(b"PK\x05\x06", search_at)
        if offset < 0:
            break
        if len(archive_tail.body) - offset >= 22:
            _, disk_number, central_disk, disk_entries, total_entries, central_size, central_offset, comment_length = struct.unpack_from(
                "<4s4H2LH", archive_tail.body, offset
            )
            if offset + 22 + comment_length == len(archive_tail.body):
                candidates.append(
                    (
                        offset,
                        disk_number,
                        central_disk,
                        disk_entries,
                        total_entries,
                        central_size,
                        central_offset,
                    )
                )
        search_at = offset + 1
    if len(candidates) != 1:
        raise ProvenanceError("tail must contain one unique terminal EOCD")
    (
        eocd_offset,
        disk_number,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
    ) = candidates[0]
    if disk_number != 0 or central_disk != 0 or disk_entries != total_entries:
        raise ProvenanceError("multi-disk ZIP is forbidden")
    if total_entries == 0xFFFF or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF:
        raise ProvenanceError("ZIP64 central directory is outside this tool")
    if central_offset + central_size != tail_start + eocd_offset:
        raise ProvenanceError("EOCD central directory extent is inconsistent")
    return central_offset, central_size, total_entries


def _validate_archive(
    binding: ArchiveBinding,
    central_directory: RangeResponse,
    archive_tail: RangeResponse,
) -> tuple[int, int, int]:
    if not binding.record_url.startswith("https://") or binding.archive_size <= 0:
        raise ProvenanceError("record URL and archive size must be bound")
    if _HEX_32.fullmatch(binding.upstream_md5) is None:
        raise ProvenanceError("upstream MD5 must be a lowercase digest")
    if _HEX_64.fullmatch(binding.central_directory_sha256) is None:
        raise ProvenanceError("central directory SHA256 must be a lowercase digest")
    if dict(binding.head_before) != dict(binding.head_after):
        raise ProvenanceError("head fields changed between probes")
    required = {"content_length", "last_modified", "accept_ranges"}
    if not required.issubset(binding.head_before):
        raise ProvenanceError("HEAD binding lacks stable required fields")
    if binding.head_before["content_length"] != str(binding.archive_size) or binding.head_before["accept_ranges"].lower() != "bytes":
        raise ProvenanceError("HEAD size or range capability mismatch")
    central_offset, central_size, total_entries = _parse_eocd(binding.archive_size, archive_tail)
    range_start, range_end = _parse_range(central_directory, binding.archive_size, "central directory range")
    if range_start != central_offset:
        raise ProvenanceError("eocd central directory offset does not match range")
    if range_end != central_offset + central_size - 1:
        raise ProvenanceError("eocd central directory size does not match range")
    tail_start, _ = _parse_range(archive_tail, binding.archive_size, "tail range")
    if central_offset >= tail_start:
        relative = central_offset - tail_start
        if archive_tail.body[relative : relative + central_size] != central_directory.body:
            raise ProvenanceError("central directory bytes differ from archive tail")
    if hashlib.sha256(central_directory.body).hexdigest() != binding.central_directory_sha256:
        raise ProvenanceError("central directory SHA256 mismatch")
    return central_offset, central_size, total_entries


def _extract_member(binding: ArchiveBinding, member: MemberBinding, central: _CentralEntry, response: RangeResponse) -> tuple[bytes, dict[str, Any]]:
    if member.name != central.name:
        raise ProvenanceError("member name mismatch")
    dos_attributes = central.external_attributes & 0xFF
    dos_regular_attributes = 0x01 | 0x02 | 0x04 | 0x20
    dos_type_is_regular = dos_attributes & ~dos_regular_attributes == 0
    if central.creator_system == 3:
        unix_mode = (central.external_attributes >> 16) & 0xFFFF
        is_regular = (
            stat.S_IFMT(unix_mode) == stat.S_IFREG and dos_type_is_regular
        )
    elif central.creator_system == 0:
        is_regular = dos_type_is_regular
    else:
        is_regular = False
    if not is_regular:
        raise ProvenanceError("allowlisted ZIP member must be a regular file")
    expected = (
        central.local_header_offset,
        central.method,
        central.compressed_size,
        central.uncompressed_size,
        central.crc32,
    )
    observed = (
        member.local_header_offset,
        member.method,
        member.compressed_size,
        member.uncompressed_size,
        member.crc32,
    )
    if observed != expected:
        raise ProvenanceError("member binding differs from central directory")
    if central.flags & 1:
        raise ProvenanceError("encrypted ZIP members are forbidden")
    if central.method not in (0, 8):
        raise ProvenanceError("unsupported ZIP compression method")
    if _HEX_64.fullmatch(member.compressed_sha256) is None or _HEX_64.fullmatch(member.uncompressed_sha256) is None:
        raise ProvenanceError("member SHA256 binding is malformed")

    match = _CONTENT_RANGE.fullmatch(response.content_range)
    if match is None:
        raise ProvenanceError("range Content-Range is malformed")
    start, end, total = (int(value) for value in match.groups())
    if start != central.local_header_offset or total != binding.archive_size or end - start + 1 != len(response.body):
        raise ProvenanceError("range Content-Range does not bind returned bytes")
    if len(response.body) < 30:
        raise ProvenanceError("local header range is truncated")
    local = struct.unpack_from("<4s5H3L2H", response.body, 0)
    signature, flags, method = local[0], local[2], local[3]
    local_crc, local_compressed, local_uncompressed = local[6], local[7], local[8]
    filename_length, extra_length = local[9], local[10]
    if signature != b"PK\x03\x04" or flags != central.flags or method != central.method:
        raise ProvenanceError("local header differs from central directory")
    payload_offset = 30 + filename_length + extra_length
    if payload_offset > len(response.body):
        raise ProvenanceError("local header filename or extra field is truncated")
    encoding = "utf-8" if flags & 0x800 else "cp437"
    try:
        local_name = response.body[30 : 30 + filename_length].decode(encoding)
    except UnicodeDecodeError as error:
        raise ProvenanceError("local filename is undecodable") from error
    if local_name != central.name:
        raise ProvenanceError("local filename differs from central directory")
    if not flags & 0x8 and (local_crc, local_compressed, local_uncompressed) != (
        central.crc32,
        central.compressed_size,
        central.uncompressed_size,
    ):
        raise ProvenanceError("local size or CRC differs from central directory")
    compressed = response.body[payload_offset:]
    if len(compressed) != central.compressed_size or end != start + payload_offset + len(compressed) - 1:
        raise ProvenanceError("range must contain one exact local header and compressed member")
    if hashlib.sha256(compressed).hexdigest() != member.compressed_sha256:
        raise ProvenanceError("compressed sha256 mismatch")
    try:
        uncompressed = compressed if central.method == 0 else zlib.decompress(compressed, -zlib.MAX_WBITS)
    except zlib.error as error:
        raise ProvenanceError("raw deflate member is invalid") from error
    if len(uncompressed) != central.uncompressed_size:
        raise ProvenanceError("uncompressed size mismatch")
    if zlib.crc32(uncompressed) & 0xFFFFFFFF != central.crc32:
        raise ProvenanceError("member CRC32 mismatch")
    if hashlib.sha256(uncompressed).hexdigest() != member.uncompressed_sha256:
        raise ProvenanceError("uncompressed SHA256 mismatch")
    manifest = {
        "name": member.name,
        "local_header_offset": member.local_header_offset,
        "method": member.method,
        "compressed_size": member.compressed_size,
        "uncompressed_size": member.uncompressed_size,
        "crc32": f"{member.crc32:08x}",
        "content_range": response.content_range,
        "compressed_sha256": member.compressed_sha256,
        "uncompressed_sha256": member.uncompressed_sha256,
    }
    return uncompressed, manifest


def extract_allowlisted_members(
    *,
    archive: ArchiveBinding,
    central_directory: RangeResponse,
    archive_tail: RangeResponse,
    members: Mapping[str, MemberBinding],
    ranges: Mapping[str, RangeResponse],
    allowlist: Sequence[str],
    destination: Path,
) -> dict[str, Any]:
    """Verify selective ranges and expose only allowlisted uncompressed member bytes."""

    requested = tuple(allowlist)
    if not requested or len(requested) != len(set(requested)):
        raise ProvenanceError("allowlist must be non-empty and unique")
    if set(members) != set(requested) or set(ranges) != set(requested):
        raise ProvenanceError("members and ranges must exactly match allowlist")
    safe_paths = {name: _safe_member_path(name) for name in requested}
    central_offset, central_size, total_entries = _validate_archive(
        archive, central_directory, archive_tail
    )
    central_entries = _parse_central_directory(central_directory.body)
    if len(central_entries) != total_entries:
        raise ProvenanceError("EOCD entry count differs from central directory")

    verified: dict[str, bytes] = {}
    member_manifests: list[dict[str, Any]] = []
    for name in requested:
        central = central_entries.get(name)
        if central is None:
            raise ProvenanceError("allowlisted member is absent from central directory")
        payload, manifest = _extract_member(archive, members[name], central, ranges[name])
        verified[name] = payload
        member_manifests.append(manifest)

    if destination.exists():
        raise ProvenanceError("builder destination must not already exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".selective-zip-", dir=destination.parent))
    try:
        for name in requested:
            output = temporary.joinpath(*safe_paths[name].parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(verified[name])
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return {
        "schema": "selective-zip-member-provenance/v1",
        "record_url": archive.record_url,
        "archive_size": archive.archive_size,
        "upstream_md5": archive.upstream_md5,
        "head_stable_fields": dict(sorted(archive.head_before.items())),
        "tail_content_range": archive_tail.content_range,
        "central_directory_content_range": central_directory.content_range,
        "central_directory_sha256": archive.central_directory_sha256,
        "eocd_central_directory_offset": central_offset,
        "eocd_central_directory_size": central_size,
        "eocd_entry_count": total_entries,
        "member_count": len(member_manifests),
        "members": member_manifests,
    }
