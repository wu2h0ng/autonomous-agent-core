from __future__ import annotations

from dataclasses import replace
import unicodedata

import pytest

from research_tools.active_discovery.hidden_byte_codec import (
    CommitmentRegistry,
    HiddenByteCodecError,
    HiddenByteFields,
    HiddenCommitmentRecord,
    HiddenRole,
    HiddenSplit,
    NORMATIVE_COMMITMENT_SHA256,
    NORMATIVE_ENVELOPE_HEX,
    commitment_sha256,
    decode_hidden_byte_envelope,
    encode_hidden_byte_envelope,
)


def _fields(**changes: object) -> HiddenByteFields:
    values: dict[str, object] = {
        "schema_id": "opaque-target/v1",
        "split": HiddenSplit.E,
        "role": HiddenRole.TARGET,
        "object_id": "object-0001",
        "custodian_id": "custodian-test",
        "nonce": bytes(range(32)),
        "raw_bytes": b"\x00\xffA\n",
    }
    values.update(changes)
    return HiddenByteFields(**values)  # type: ignore[arg-type]


def test_normative_vector_freezes_exact_binary_codec() -> None:
    envelope = encode_hidden_byte_envelope(_fields(), max_raw_length=2**24)

    assert len(envelope) == 136
    assert envelope.hex() == NORMATIVE_ENVELOPE_HEX
    assert commitment_sha256(envelope) == NORMATIVE_COMMITMENT_SHA256
    assert decode_hidden_byte_envelope(envelope, max_raw_length=2**24) == _fields()


def test_codec_preserves_arbitrary_raw_bytes_and_rejects_trailers() -> None:
    fields = _fields(raw_bytes=bytes(range(256)))
    envelope = encode_hidden_byte_envelope(fields, max_raw_length=256)
    assert decode_hidden_byte_envelope(envelope, max_raw_length=256).raw_bytes == bytes(
        range(256)
    )

    with pytest.raises(HiddenByteCodecError, match="trailing"):
        decode_hidden_byte_envelope(envelope + b"x", max_raw_length=256)
    with pytest.raises(HiddenByteCodecError, match="maximum"):
        decode_hidden_byte_envelope(envelope, max_raw_length=255)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("schema_id", "UPPER", "schema_id"),
        ("object_id", "bad object", "object_id"),
        ("custodian_id", "bad\x00id", "custodian_id"),
        ("nonce", b"short", "nonce"),
    ),
)
def test_encoder_rejects_noncanonical_fields(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(HiddenByteCodecError, match=message):
        encode_hidden_byte_envelope(_fields(**{field: value}), max_raw_length=2**24)

    if field == "custodian_id":
        decomposed = unicodedata.normalize("NFD", "custodién")
        with pytest.raises(HiddenByteCodecError, match="NFC"):
            encode_hidden_byte_envelope(
                _fields(custodian_id=decomposed), max_raw_length=2**24
            )


def test_decoder_rejects_domain_version_enum_length_and_commitment_drift() -> None:
    envelope = bytearray(encode_hidden_byte_envelope(_fields(), max_raw_length=2**24))
    domain_start = 2
    version_start = 2 + 39

    wrong_domain = bytearray(envelope)
    wrong_domain[domain_start] ^= 1
    with pytest.raises(HiddenByteCodecError, match="domain"):
        decode_hidden_byte_envelope(bytes(wrong_domain), max_raw_length=2**24)

    wrong_version = bytearray(envelope)
    wrong_version[version_start : version_start + 2] = b"\x00\x02"
    with pytest.raises(HiddenByteCodecError, match="version"):
        decode_hidden_byte_envelope(bytes(wrong_version), max_raw_length=2**24)

    split_offset = version_start + 2 + 2 + len("opaque-target/v1")
    wrong_split = bytearray(envelope)
    wrong_split[split_offset] = 9
    with pytest.raises(HiddenByteCodecError, match="split"):
        decode_hidden_byte_envelope(bytes(wrong_split), max_raw_length=2**24)

    with pytest.raises(HiddenByteCodecError, match="commitment"):
        decode_hidden_byte_envelope(
            bytes(envelope),
            max_raw_length=2**24,
            expected_commitment="0" * 64,
        )

    with pytest.raises(HiddenByteCodecError):
        decode_hidden_byte_envelope(bytes(envelope[:-1]), max_raw_length=2**24)


def test_metadata_digest_is_defined_and_registry_owns_cross_object_reuse_checks() -> None:
    registry = CommitmentRegistry(max_raw_length=2**24)
    envelope = encode_hidden_byte_envelope(_fields(), max_raw_length=2**24)
    record = HiddenCommitmentRecord.from_envelope(envelope, max_raw_length=2**24)

    registry.register(record=record, envelope=envelope)
    assert record.envelope_metadata_digest != record.commitment
    assert record.raw_byte_length == 4

    alias_fields = _fields(object_id="object-0002")
    alias_envelope = encode_hidden_byte_envelope(alias_fields, max_raw_length=2**24)
    alias_record = HiddenCommitmentRecord.from_envelope(
        alias_envelope, max_raw_length=2**24
    )
    with pytest.raises(HiddenByteCodecError, match="nonce reuse"):
        registry.register(record=alias_record, envelope=alias_envelope)

    with pytest.raises(HiddenByteCodecError, match="manifest object"):
        registry.register(
            record=replace(record, object_id="object-9999"), envelope=envelope
        )


def test_split_role_schema_and_custodian_aliases_change_commitment() -> None:
    original = encode_hidden_byte_envelope(_fields(), max_raw_length=2**24)
    aliases = (
        _fields(split=HiddenSplit.P),
        _fields(role=HiddenRole.CHALLENGE),
        _fields(schema_id="opaque-target/v2"),
        _fields(object_id="object-0002"),
        _fields(custodian_id="custodian-other"),
    )

    assert len(
        {
            commitment_sha256(original),
            *(
                commitment_sha256(
                    encode_hidden_byte_envelope(item, max_raw_length=2**24)
                )
                for item in aliases
            ),
        }
    ) == 6
