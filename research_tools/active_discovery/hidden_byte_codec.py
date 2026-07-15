from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from enum import IntEnum

from .canonical import content_digest


DOMAIN = b"active-discovery:hidden-byte-commitment"
CODEC_VERSION = 1
NORMATIVE_ENVELOPE_HEX = (
    "00276163746976652d646973636f766572793a68696464656e2d627974652d"
    "636f6d6d69746d656e74000100106f70617175652d7461726765742f763103"
    "01000b6f626a6563742d30303031000e637573746f6469616e2d7465737400"
    "0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
    "000000000000000400ff410a"
)
NORMATIVE_COMMITMENT_SHA256 = (
    "5eba14f5e5a57193a784d62c0349cc00a934f13e0df972c952c4f3361993b1c5"
)
_SCHEMA_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
_OBJECT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class HiddenByteCodecError(ValueError):
    """A hidden-byte envelope or its public manifest binding is non-canonical."""


class HiddenSplit(IntEnum):
    Q = 1
    P = 2
    E = 3


class HiddenRole(IntEnum):
    TARGET = 1
    CHALLENGE = 2
    CONTRAST = 3
    WITNESS = 4


def _validate_schema(value: object) -> str:
    if not isinstance(value, str) or _SCHEMA_RE.fullmatch(value) is None:
        raise HiddenByteCodecError("schema_id is outside the canonical ASCII grammar")
    if not 1 <= len(value.encode("ascii")) <= 128:
        raise HiddenByteCodecError("schema_id length is outside 1-128 bytes")
    return value


def _validate_object(value: object) -> str:
    if not isinstance(value, str) or _OBJECT_RE.fullmatch(value) is None:
        raise HiddenByteCodecError("object_id is outside the canonical ASCII grammar")
    return value


def _validate_custodian(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise HiddenByteCodecError("custodian_id must be a non-empty UTF-8 string")
    if unicodedata.normalize("NFC", value) != value:
        raise HiddenByteCodecError("custodian_id must already be Unicode NFC")
    if any(character == "\x00" or unicodedata.category(character) == "Cc" for character in value):
        raise HiddenByteCodecError("custodian_id contains a forbidden control character")
    encoded = value.encode("utf-8")
    if not 1 <= len(encoded) <= 255:
        raise HiddenByteCodecError("custodian_id length is outside 1-255 bytes")
    return value


@dataclass(frozen=True, slots=True)
class HiddenByteFields:
    schema_id: str
    split: HiddenSplit
    role: HiddenRole
    object_id: str
    custodian_id: str
    nonce: bytes
    raw_bytes: bytes

    def __post_init__(self) -> None:
        _validate_schema(self.schema_id)
        if not isinstance(self.split, HiddenSplit):
            raise HiddenByteCodecError("split must be Q, P, or E")
        if not isinstance(self.role, HiddenRole):
            raise HiddenByteCodecError("role is outside the closed enum")
        _validate_object(self.object_id)
        _validate_custodian(self.custodian_id)
        if not isinstance(self.nonce, bytes) or len(self.nonce) != 32:
            raise HiddenByteCodecError("nonce must contain exactly 32 raw bytes")
        if not isinstance(self.raw_bytes, bytes):
            raise HiddenByteCodecError("raw_bytes must be bytes")


def _lp16(value: bytes, label: str) -> bytes:
    if not value or len(value) > 0xFFFF:
        raise HiddenByteCodecError(f"{label} length is outside LP16")
    return len(value).to_bytes(2, "big") + value


def encode_hidden_byte_envelope(
    fields: HiddenByteFields, *, max_raw_length: int
) -> bytes:
    if not isinstance(fields, HiddenByteFields):
        raise HiddenByteCodecError("fields must be HiddenByteFields")
    if (
        isinstance(max_raw_length, bool)
        or not isinstance(max_raw_length, int)
        or not 0 <= max_raw_length <= 2**24
    ):
        raise HiddenByteCodecError("maximum raw length must be in [0,2^24]")
    if len(fields.raw_bytes) > max_raw_length:
        raise HiddenByteCodecError("raw bytes exceed the maximum raw length")
    schema = _validate_schema(fields.schema_id).encode("ascii")
    object_id = _validate_object(fields.object_id).encode("ascii")
    custodian = _validate_custodian(fields.custodian_id).encode("utf-8")
    return b"".join(
        (
            _lp16(DOMAIN, "domain"),
            CODEC_VERSION.to_bytes(2, "big"),
            _lp16(schema, "schema_id"),
            int(fields.split).to_bytes(1, "big"),
            int(fields.role).to_bytes(1, "big"),
            _lp16(object_id, "object_id"),
            _lp16(custodian, "custodian_id"),
            fields.nonce,
            len(fields.raw_bytes).to_bytes(8, "big"),
            fields.raw_bytes,
        )
    )


def commitment_sha256(envelope: bytes) -> str:
    if not isinstance(envelope, bytes):
        raise HiddenByteCodecError("envelope must be bytes")
    return hashlib.sha256(envelope).hexdigest()


class _Reader:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0

    def read(self, count: int, label: str) -> bytes:
        end = self._offset + count
        if end > len(self._payload):
            raise HiddenByteCodecError(f"truncated {label}")
        result = self._payload[self._offset : end]
        self._offset = end
        return result

    def lp16(self, label: str) -> bytes:
        length = int.from_bytes(self.read(2, f"{label} length"), "big")
        if length == 0:
            raise HiddenByteCodecError(f"{label} length must be non-zero")
        return self.read(length, label)

    @property
    def remaining(self) -> int:
        return len(self._payload) - self._offset


def decode_hidden_byte_envelope(
    envelope: bytes,
    *,
    max_raw_length: int,
    expected_commitment: str | None = None,
) -> HiddenByteFields:
    if not isinstance(envelope, bytes):
        raise HiddenByteCodecError("envelope must be bytes")
    if (
        isinstance(max_raw_length, bool)
        or not isinstance(max_raw_length, int)
        or not 0 <= max_raw_length <= 2**24
    ):
        raise HiddenByteCodecError("maximum raw length must be in [0,2^24]")
    reader = _Reader(envelope)
    if reader.lp16("domain") != DOMAIN:
        raise HiddenByteCodecError("hidden-byte commitment domain mismatch")
    version = int.from_bytes(reader.read(2, "version"), "big")
    if version != CODEC_VERSION:
        raise HiddenByteCodecError("hidden-byte codec version mismatch")
    try:
        schema_id = reader.lp16("schema_id").decode("ascii")
    except UnicodeDecodeError as exc:
        raise HiddenByteCodecError("schema_id is not ASCII") from exc
    _validate_schema(schema_id)
    try:
        split = HiddenSplit(int.from_bytes(reader.read(1, "split"), "big"))
    except ValueError as exc:
        raise HiddenByteCodecError("unknown hidden split code") from exc
    try:
        role = HiddenRole(int.from_bytes(reader.read(1, "role"), "big"))
    except ValueError as exc:
        raise HiddenByteCodecError("unknown hidden role code") from exc
    try:
        object_id = reader.lp16("object_id").decode("ascii")
    except UnicodeDecodeError as exc:
        raise HiddenByteCodecError("object_id is not ASCII") from exc
    _validate_object(object_id)
    try:
        custodian_id = reader.lp16("custodian_id").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HiddenByteCodecError("custodian_id is not valid UTF-8") from exc
    _validate_custodian(custodian_id)
    nonce = reader.read(32, "nonce")
    raw_length = int.from_bytes(reader.read(8, "raw length"), "big")
    if raw_length > max_raw_length:
        raise HiddenByteCodecError("raw bytes exceed the maximum raw length")
    raw_bytes = reader.read(raw_length, "raw bytes")
    if reader.remaining:
        raise HiddenByteCodecError("hidden-byte envelope has trailing bytes")
    fields = HiddenByteFields(
        schema_id=schema_id,
        split=split,
        role=role,
        object_id=object_id,
        custodian_id=custodian_id,
        nonce=nonce,
        raw_bytes=raw_bytes,
    )
    if encode_hidden_byte_envelope(fields, max_raw_length=max_raw_length) != envelope:
        raise HiddenByteCodecError("hidden-byte envelope is not a canonical re-encoding")
    if expected_commitment is not None:
        if _SHA256_RE.fullmatch(expected_commitment) is None:
            raise HiddenByteCodecError("expected commitment is not lowercase SHA-256")
        if commitment_sha256(envelope) != expected_commitment:
            raise HiddenByteCodecError("hidden-byte commitment mismatch")
    return fields


def envelope_metadata_mapping(fields: HiddenByteFields) -> dict[str, object]:
    """Return the public, metadata-only subset; nonce and raw bytes stay excluded."""

    return {
        "domain": DOMAIN.decode("ascii"),
        "codec_version": CODEC_VERSION,
        "schema_id": fields.schema_id,
        "split": fields.split.name,
        "role": fields.role.name,
        "object_id": fields.object_id,
        "custodian_id": fields.custodian_id,
        "raw_byte_length": len(fields.raw_bytes),
    }


def envelope_metadata_digest(fields: HiddenByteFields) -> str:
    return content_digest(
        "hidden-byte-envelope-metadata/v1", envelope_metadata_mapping(fields)
    )


@dataclass(frozen=True, slots=True)
class HiddenCommitmentRecord:
    commitment: str
    raw_byte_length: int
    codec_version: int
    schema_id: str
    split: HiddenSplit
    role: HiddenRole
    object_id: str
    custodian_id: str
    envelope_metadata_digest: str

    @classmethod
    def from_envelope(
        cls, envelope: bytes, *, max_raw_length: int
    ) -> HiddenCommitmentRecord:
        fields = decode_hidden_byte_envelope(
            envelope, max_raw_length=max_raw_length
        )
        return cls(
            commitment=commitment_sha256(envelope),
            raw_byte_length=len(fields.raw_bytes),
            codec_version=CODEC_VERSION,
            schema_id=fields.schema_id,
            split=fields.split,
            role=fields.role,
            object_id=fields.object_id,
            custodian_id=fields.custodian_id,
            envelope_metadata_digest=envelope_metadata_digest(fields),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "commitment": self.commitment,
            "raw_byte_length": self.raw_byte_length,
            "codec_version": self.codec_version,
            "schema_id": self.schema_id,
            "split": self.split.name,
            "role": self.role.name,
            "object_id": self.object_id,
            "custodian_id": self.custodian_id,
            "envelope_metadata_digest": self.envelope_metadata_digest,
        }


class CommitmentRegistry:
    """Manifest-layer uniqueness checks that cannot belong to a single decoder."""

    def __init__(self, *, max_raw_length: int) -> None:
        if (
            isinstance(max_raw_length, bool)
            or not isinstance(max_raw_length, int)
            or not 0 <= max_raw_length <= 2**24
        ):
            raise HiddenByteCodecError("maximum raw length must be in [0,2^24]")
        self._max_raw_length = max_raw_length
        self._objects: dict[str, HiddenCommitmentRecord] = {}
        self._nonces: set[bytes] = set()
        self._commitment_objects: dict[str, str] = {}

    def register(self, *, record: HiddenCommitmentRecord, envelope: bytes) -> None:
        fields = decode_hidden_byte_envelope(
            envelope,
            max_raw_length=self._max_raw_length,
            expected_commitment=record.commitment,
        )
        expected = HiddenCommitmentRecord.from_envelope(
            envelope, max_raw_length=self._max_raw_length
        )
        if record != expected:
            raise HiddenByteCodecError("public record does not match its manifest object")
        existing_object = self._commitment_objects.get(record.commitment)
        if existing_object is not None and existing_object != record.object_id:
            raise HiddenByteCodecError("one commitment cannot bind two manifest objects")
        if record.object_id in self._objects:
            raise HiddenByteCodecError("manifest object_id is duplicated")
        if fields.nonce in self._nonces:
            raise HiddenByteCodecError("nonce reuse across manifest objects is forbidden")
        self._objects[record.object_id] = record
        self._nonces.add(fields.nonce)
        self._commitment_objects[record.commitment] = record.object_id

    @property
    def records(self) -> tuple[HiddenCommitmentRecord, ...]:
        return tuple(self._objects[key] for key in sorted(self._objects))
