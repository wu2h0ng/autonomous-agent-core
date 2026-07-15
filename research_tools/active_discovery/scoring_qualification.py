from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_json, content_digest
from .contracts import ProbeObservation, ProbeRequest
from .families.opaque_cli import (
    OpaqueCliFamily,
    OpaqueCliSemantics,
    RepeatMode,
    UnknownMode,
)
from .families.opaque_expiry import OpaqueExpiryFamily, OpaqueExpirySemantics
from .families.opaque_graph import OpaqueGraphFamily, OpaqueGraphSemantics
from .families.opaque_quota import OpaqueQuotaFamily, OpaqueQuotaSemantics


QUALIFICATION_MANIFEST_SCHEMA = "active-discovery-scoring-qualification/v1"


class QualificationError(ValueError):
    """The implementer-visible Q-SCORE qualification corpus drifted."""


@dataclass(frozen=True, slots=True)
class QualificationRecord:
    record_id: str
    family_code: str
    semantic_variant: str
    label_permutation: int
    semantic_config_json: str
    behavior_signature: str
    label_map_digest: str
    split: str
    scientific_use: str
    raw_hex: str
    raw_sha256: str

    @property
    def raw_bytes(self) -> bytes:
        return bytes.fromhex(self.raw_hex)

    def to_mapping(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "family_code": self.family_code,
            "semantic_variant": self.semantic_variant,
            "label_permutation": self.label_permutation,
            "semantic_config_json": self.semantic_config_json,
            "behavior_signature": self.behavior_signature,
            "label_map_digest": self.label_map_digest,
            "split": self.split,
            "scientific_use": self.scientific_use,
            "raw_hex": self.raw_hex,
            "raw_sha256": self.raw_sha256,
        }

    def manifest_mapping(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "semantic_config_digest": content_digest(
                "qualification-semantic-config/v1",
                json.loads(self.semantic_config_json),
            ),
            "behavior_signature": self.behavior_signature,
            "label_map_digest": self.label_map_digest,
            "raw_sha256": self.raw_sha256,
        }


def _request(
    *,
    family: Any,
    descriptor: Any,
    step_index: int,
    payload: Mapping[str, Any],
) -> ProbeObservation:
    request = ProbeRequest.from_mapping(
        {
            "episode_id": "q-score-witness",
            "arm_id": "QUALIFICATION_FIXTURE",
            "step_index": step_index,
            "probe_id": f"q-probe-{step_index}",
            "operation_id": descriptor.operation_id,
            "payload_json": canonical_json(dict(payload)),
            "expected_state_digest": family.state_digest(),
            "cost_units": 1,
        }
    )
    return family.execute(request)


def _normalized_observation(
    observation: ProbeObservation, output_fields: tuple[str, ...]
) -> dict[str, object]:
    output = json.loads(observation.output_json)
    return {
        "status_code": observation.status_code,
        "output_values": [output[field] for field in output_fields],
        "state_relation": (
            "SAME"
            if observation.before_state_digest == observation.after_state_digest
            else "CHANGED"
        ),
    }


def _f1_witness(config: Mapping[str, Any], seed: int) -> tuple[dict[str, object], str]:
    semantics = OpaqueCliSemantics(
        source_precedence=tuple(config["source_precedence"]),  # type: ignore[arg-type]
        repeat_mode=RepeatMode(config["repeat_mode"]),
        unknown_mode=UnknownMode(config["unknown_mode"]),
        empty_is_missing=config["empty_is_missing"],
        atomic_on_error=config["atomic_on_error"],
    )
    family = OpaqueCliFamily(seed=seed, semantics=semantics)
    descriptor = family.public_descriptor()
    schema = json.loads(descriptor.schema_json)
    sequence, map_one, map_two = [item["field_id"] for item in schema["input_fields"]]
    setting = schema["tokens"]["setting"]
    output_field = schema["output_field"]
    observation = _request(
        family=family,
        descriptor=descriptor,
        step_index=0,
        payload={
            sequence: [f"{setting}=from-sequence"],
            map_one: {setting: "from-map-one"},
            map_two: {setting: "from-map-two"},
        },
    )
    return _normalized_observation(observation, (output_field,)), descriptor.descriptor_digest


def _f2_witness(config: Mapping[str, Any], seed: int) -> tuple[list[dict[str, object]], str]:
    family = OpaqueExpiryFamily(
        seed=seed,
        semantics=OpaqueExpirySemantics(
            lifetime_steps=config["lifetime_steps"],
            refresh_on_write=config["refresh_on_write"],
            expires_at_boundary=config["expires_at_boundary"],
        ),
    )
    descriptor = family.public_descriptor()
    schema = json.loads(descriptor.schema_json)
    action, slot, value, steps = [item["field_id"] for item in schema["inputs"]]
    put, get, advance = schema["command_tokens"]
    output_fields = tuple(item["field_id"] for item in schema["outputs"])
    payloads = (
        {action: put, slot: "slot", value: "value", steps: 0},
        {action: advance, slot: "", value: "", steps: 1},
        {action: get, slot: "slot", value: "", steps: 0},
    )
    observations = [
        _request(
            family=family,
            descriptor=descriptor,
            step_index=index,
            payload=payload,
        )
        for index, payload in enumerate(payloads)
    ]
    return (
        [_normalized_observation(item, output_fields) for item in observations],
        descriptor.descriptor_digest,
    )


def _f3_witness(config: Mapping[str, Any], seed: int) -> tuple[dict[str, object], str]:
    family = OpaqueQuotaFamily(
        seed=seed,
        semantics=OpaqueQuotaSemantics(
            capacity_units=config["capacity_units"],
            refill_per_step=config["refill_per_step"],
            refill_before_request=config["refill_before_request"],
            deny_consumes=config["deny_consumes"],
        ),
    )
    descriptor = family.public_descriptor()
    schema = json.loads(descriptor.schema_json)
    amount, progress = [item["field_id"] for item in schema["inputs"]]
    output_fields = tuple(item["field_id"] for item in schema["outputs"])
    observation = _request(
        family=family,
        descriptor=descriptor,
        step_index=0,
        payload={amount: 4, progress: 0},
    )
    return _normalized_observation(observation, output_fields), descriptor.descriptor_digest


def _f4_witness(config: Mapping[str, Any], seed: int) -> tuple[list[dict[str, object]], str]:
    family = OpaqueGraphFamily(
        seed=seed,
        semantics=OpaqueGraphSemantics(
            directed=config["directed"],
            remove_missing_error=config["remove_missing_error"],
            allow_self_loop=config["allow_self_loop"],
        ),
    )
    descriptor = family.public_descriptor()
    schema = json.loads(descriptor.schema_json)
    action, left, right = [item["field_id"] for item in schema["inputs"]]
    add, _, query = schema["command_tokens"]
    output_fields = tuple(item["field_id"] for item in schema["outputs"])
    payloads = (
        {action: add, left: "node-a", right: "node-b"},
        {action: query, left: "node-b", right: "node-a"},
    )
    observations = [
        _request(
            family=family,
            descriptor=descriptor,
            step_index=index,
            payload=payload,
        )
        for index, payload in enumerate(payloads)
    ]
    return (
        [_normalized_observation(item, output_fields) for item in observations],
        descriptor.descriptor_digest,
    )


_CONFIGS: dict[str, dict[str, dict[str, object]]] = {
    "F1": {
        "A": {
            "source_precedence": ["map_two", "sequence", "map_one"],
            "repeat_mode": "LAST",
            "unknown_mode": "ERROR",
            "empty_is_missing": True,
            "atomic_on_error": True,
        },
        "B": {
            "source_precedence": ["map_one", "sequence", "map_two"],
            "repeat_mode": "LAST",
            "unknown_mode": "ERROR",
            "empty_is_missing": True,
            "atomic_on_error": True,
        },
    },
    "F2": {
        "A": {
            "lifetime_steps": 1,
            "refresh_on_write": True,
            "expires_at_boundary": True,
        },
        "B": {
            "lifetime_steps": 2,
            "refresh_on_write": True,
            "expires_at_boundary": True,
        },
    },
    "F3": {
        "A": {
            "capacity_units": 3,
            "refill_per_step": 0,
            "refill_before_request": True,
            "deny_consumes": False,
        },
        "B": {
            "capacity_units": 5,
            "refill_per_step": 0,
            "refill_before_request": True,
            "deny_consumes": False,
        },
    },
    "F4": {
        "A": {
            "directed": True,
            "remove_missing_error": False,
            "allow_self_loop": False,
        },
        "B": {
            "directed": False,
            "remove_missing_error": False,
            "allow_self_loop": False,
        },
    },
}


def _witness(
    family_code: str, config: Mapping[str, Any], seed: int
) -> tuple[object, str]:
    if family_code == "F1":
        return _f1_witness(config, seed)
    if family_code == "F2":
        return _f2_witness(config, seed)
    if family_code == "F3":
        return _f3_witness(config, seed)
    return _f4_witness(config, seed)


def build_qualification_records() -> tuple[QualificationRecord, ...]:
    records: list[QualificationRecord] = []
    for family_index, family_code in enumerate(("F1", "F2", "F3", "F4")):
        for semantic_variant in ("A", "B"):
            config = _CONFIGS[family_code][semantic_variant]
            for label_permutation in (0, 1):
                seed = 10_000 + family_index * 100 + label_permutation
                normalized_behavior, label_map_digest = _witness(
                    family_code, config, seed
                )
                behavior_signature = content_digest(
                    "qualification-behavior-signature/v1", normalized_behavior
                )
                record_id = (
                    f"q-{family_code.lower()}-{semantic_variant.lower()}-p{label_permutation}"
                )
                raw_payload = {
                    "record_id": record_id,
                    "family_code": family_code,
                    "semantic_variant": semantic_variant,
                    "label_permutation": label_permutation,
                    "semantic_config": config,
                    "behavior_signature": behavior_signature,
                    "label_map_digest": label_map_digest,
                    "split": "Q-SCORE",
                    "scientific_use": "PERMANENTLY_EXCLUDED",
                }
                raw_bytes = canonical_json(raw_payload).encode("utf-8")
                records.append(
                    QualificationRecord(
                        record_id=record_id,
                        family_code=family_code,
                        semantic_variant=semantic_variant,
                        label_permutation=label_permutation,
                        semantic_config_json=canonical_json(config),
                        behavior_signature=behavior_signature,
                        label_map_digest=label_map_digest,
                        split="Q-SCORE",
                        scientific_use="PERMANENTLY_EXCLUDED",
                        raw_hex=raw_bytes.hex(),
                        raw_sha256=hashlib.sha256(raw_bytes).hexdigest(),
                    )
                )
    return tuple(records)


def build_qualification_manifest() -> dict[str, object]:
    records = build_qualification_records()
    payload: dict[str, object] = {
        "schema_version": QUALIFICATION_MANIFEST_SCHEMA,
        "mode": "NOT_EVIDENCE",
        "qualification_state": "IMPLEMENTER_VISIBLE_Q_SCORE_ONLY",
        "split": "Q-SCORE",
        "record_count": len(records),
        "scientific_use": "PERMANENTLY_EXCLUDED",
        "records": [item.manifest_mapping() for item in records],
    }
    return {
        **payload,
        "manifest_digest": content_digest(
            "scoring-qualification-manifest/v1", payload
        ),
    }


def load_qualification_manifest(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError("qualification manifest could not be read") from exc
    if not isinstance(raw, dict) or raw != build_qualification_manifest():
        raise QualificationError("qualification manifest does not match exact fixtures")
    return raw
