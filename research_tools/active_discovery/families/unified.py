from __future__ import annotations

import json
from typing import Any

from ..canonical import canonical_json, content_digest
from ..catalogue import VisibleProbeCandidate, VisibleProbeCatalogue
from ..contracts import ProbeObservation, ProbeRequest, PublicEnvironmentDescriptor
from ..referee import HiddenAdapter, HiddenScore
from ..selector import (
    HypothesisPrediction,
    HypothesisWeight,
    OutcomeLikelihood,
)
from .manifest import FAMILY_MANIFEST_SCHEMA, FamilyCode, FamilyManifest
from .opaque_cli import OpaqueCliFamily, OpaqueCliSemantics, RepeatMode, UnknownMode
from .opaque_expiry import OpaqueExpiryFamily, OpaqueExpirySemantics
from .opaque_graph import OpaqueGraphFamily, OpaqueGraphSemantics
from .opaque_quota import OpaqueQuotaFamily, OpaqueQuotaSemantics


class UnifiedAdapterError(ValueError):
    """A manifest cannot be bound to an exact development family adapter."""


def _hidden_family(
    family_code: FamilyCode, seed: int
) -> tuple[HiddenAdapter, dict[str, object]]:
    if family_code is FamilyCode.F1:
        semantics = OpaqueCliSemantics(
            source_precedence=("map_two", "sequence", "map_one"),
            repeat_mode=RepeatMode.LAST,
            unknown_mode=UnknownMode.ERROR,
            empty_is_missing=True,
            atomic_on_error=True,
        )
        return OpaqueCliFamily(seed=seed, semantics=semantics), {
            "source_precedence": list(semantics.source_precedence),
            "repeat_mode": semantics.repeat_mode.value,
            "unknown_mode": semantics.unknown_mode.value,
            "empty_is_missing": semantics.empty_is_missing,
            "atomic_on_error": semantics.atomic_on_error,
        }
    if family_code is FamilyCode.F2:
        semantics = OpaqueExpirySemantics(
            lifetime_steps=2,
            refresh_on_write=True,
            expires_at_boundary=True,
        )
        return OpaqueExpiryFamily(seed=seed, semantics=semantics), {
            "lifetime_steps": semantics.lifetime_steps,
            "refresh_on_write": semantics.refresh_on_write,
            "expires_at_boundary": semantics.expires_at_boundary,
        }
    if family_code is FamilyCode.F3:
        semantics = OpaqueQuotaSemantics(
            capacity_units=5,
            refill_per_step=2,
            refill_before_request=True,
            deny_consumes=False,
        )
        return OpaqueQuotaFamily(seed=seed, semantics=semantics), {
            "capacity_units": semantics.capacity_units,
            "refill_per_step": semantics.refill_per_step,
            "refill_before_request": semantics.refill_before_request,
            "deny_consumes": semantics.deny_consumes,
        }
    semantics = OpaqueGraphSemantics(
        directed=True,
        remove_missing_error=False,
        allow_self_loop=False,
    )
    return OpaqueGraphFamily(seed=seed, semantics=semantics), {
        "directed": semantics.directed,
        "remove_missing_error": semantics.remove_missing_error,
        "allow_self_loop": semantics.allow_self_loop,
    }


def _opaque_value(descriptor_digest: str, index: int) -> str:
    return f"x_{content_digest('visible-catalogue-value', {'descriptor': descriptor_digest, 'index': index})[:12]}"


def _f1_payloads(descriptor: PublicEnvironmentDescriptor) -> tuple[dict[str, Any], ...]:
    schema = json.loads(descriptor.schema_json)
    sequence, map_one, map_two = [item["field_id"] for item in schema["input_fields"]]
    setting = schema["tokens"]["setting"]
    first = _opaque_value(descriptor.descriptor_digest, 0)
    second = _opaque_value(descriptor.descriptor_digest, 1)
    third = _opaque_value(descriptor.descriptor_digest, 2)
    return (
        {sequence: [], map_one: {}, map_two: {}},
        {sequence: [f"{setting}={first}"], map_one: {}, map_two: {}},
        {sequence: [], map_one: {setting: second}, map_two: {}},
        {sequence: [], map_one: {}, map_two: {setting: third}},
        {
            sequence: [f"{setting}={first}"],
            map_one: {setting: second},
            map_two: {setting: third},
        },
        {
            sequence: [f"{setting}={first}", f"{setting}={second}"],
            map_one: {},
            map_two: {},
        },
    )


def _f2_payloads(descriptor: PublicEnvironmentDescriptor) -> tuple[dict[str, Any], ...]:
    schema = json.loads(descriptor.schema_json)
    action, slot, value, steps = [item["field_id"] for item in schema["inputs"]]
    put, get, advance = schema["command_tokens"]
    slot_a = _opaque_value(descriptor.descriptor_digest, 0)
    slot_b = _opaque_value(descriptor.descriptor_digest, 1)
    value_a = _opaque_value(descriptor.descriptor_digest, 2)
    value_b = _opaque_value(descriptor.descriptor_digest, 3)
    return (
        {action: put, slot: slot_a, value: value_a, steps: 0},
        {action: get, slot: slot_a, value: "", steps: 0},
        {action: advance, slot: "", value: "", steps: 1},
        {action: get, slot: slot_a, value: "", steps: 0},
        {action: put, slot: slot_b, value: value_b, steps: 0},
        {action: advance, slot: "", value: "", steps: 2},
    )


def _f3_payloads(descriptor: PublicEnvironmentDescriptor) -> tuple[dict[str, Any], ...]:
    schema = json.loads(descriptor.schema_json)
    amount, progress = [item["field_id"] for item in schema["inputs"]]
    return tuple(
        {amount: requested, progress: advanced}
        for requested, advanced in ((1, 0), (4, 0), (2, 0), (1, 1), (6, 0), (0, 2))
    )


def _f4_payloads(descriptor: PublicEnvironmentDescriptor) -> tuple[dict[str, Any], ...]:
    schema = json.loads(descriptor.schema_json)
    action, left, right = [item["field_id"] for item in schema["inputs"]]
    add, remove, query = schema["command_tokens"]
    node_a = _opaque_value(descriptor.descriptor_digest, 0)
    node_b = _opaque_value(descriptor.descriptor_digest, 1)
    node_c = _opaque_value(descriptor.descriptor_digest, 2)
    return (
        {action: add, left: node_a, right: node_b},
        {action: add, left: node_b, right: node_c},
        {action: query, left: node_a, right: node_c},
        {action: query, left: node_c, right: node_a},
        {action: remove, left: node_b, right: node_c},
        {action: query, left: node_a, right: node_c},
    )


def _catalogue(
    family_code: FamilyCode, descriptor: PublicEnvironmentDescriptor
) -> VisibleProbeCatalogue:
    builders = {
        FamilyCode.F1: _f1_payloads,
        FamilyCode.F2: _f2_payloads,
        FamilyCode.F3: _f3_payloads,
        FamilyCode.F4: _f4_payloads,
    }
    payloads = builders[family_code](descriptor)
    hypothesis_ids = tuple(
        f"h_{content_digest('visible-hypothesis-label', {'descriptor': descriptor.descriptor_digest, 'index': index})[:12]}"
        for index in range(2)
    )
    zero_label = f"r_{content_digest('visible-status-label', {'descriptor': descriptor.descriptor_digest, 'bucket': 0})[:12]}"
    nonzero_label = f"r_{content_digest('visible-status-label', {'descriptor': descriptor.descriptor_digest, 'bucket': 1})[:12]}"
    strengths = (900_000, 800_000, 700_000, 600_000, 550_000, 500_000)
    candidates: list[VisibleProbeCandidate] = []
    for stable_order, (payload, strength) in enumerate(zip(payloads, strengths)):
        predictions = (
            HypothesisPrediction(
                hypothesis_ids[0],
                (
                    OutcomeLikelihood(zero_label, strength),
                    OutcomeLikelihood(nonzero_label, 1_000_000 - strength),
                ),
            ),
            HypothesisPrediction(
                hypothesis_ids[1],
                (
                    OutcomeLikelihood(zero_label, 1_000_000 - strength),
                    OutcomeLikelihood(nonzero_label, strength),
                ),
            ),
        )
        candidates.append(
            VisibleProbeCandidate(
                probe_id=f"p_{content_digest('visible-probe-label', {'descriptor': descriptor.descriptor_digest, 'order': stable_order})[:12]}",
                stable_order=stable_order,
                payload_json=canonical_json(payload),
                cost_units=1,
                zero_status_label=zero_label,
                nonzero_status_label=nonzero_label,
                predictions=predictions,
            )
        )
    return VisibleProbeCatalogue(
        candidates=tuple(candidates),
        initial_weights=(
            HypothesisWeight(hypothesis_ids[0], 500_000),
            HypothesisWeight(hypothesis_ids[1], 500_000),
        ),
    )


class UnifiedFamilyAdapter:
    """Referee-owned exact binding of a hidden family and visible catalogue."""

    def __init__(
        self,
        *,
        family: HiddenAdapter,
        manifest: FamilyManifest,
        catalogue: VisibleProbeCatalogue,
    ) -> None:
        self._family = family
        self._manifest = manifest
        self._catalogue = catalogue

    @classmethod
    def build(
        cls,
        *,
        family_code: FamilyCode,
        seed: int,
        probe_budget_units: int,
    ) -> UnifiedFamilyAdapter:
        if not isinstance(family_code, FamilyCode):
            raise UnifiedAdapterError("family_code must be one of F1-F4")
        family, hidden_configuration = _hidden_family(family_code, seed)
        descriptor = family.public_descriptor()
        catalogue = _catalogue(family_code, descriptor)
        if (
            isinstance(probe_budget_units, bool)
            or not isinstance(probe_budget_units, int)
            or not 1 <= probe_budget_units <= len(catalogue.candidates)
        ):
            raise UnifiedAdapterError(
                "probe budget must fit the exact unit-cost public catalogue"
            )
        manifest = FamilyManifest(
            schema_version=FAMILY_MANIFEST_SCHEMA,
            mode="NOT_EVIDENCE",
            family_code=family_code,
            seed=seed,
            probe_budget_units=probe_budget_units,
            descriptor_digest=descriptor.descriptor_digest,
            catalogue_digest=catalogue.catalogue_digest,
            hidden_configuration_digest=content_digest(
                "hidden-family-configuration",
                {
                    "family_code": family_code.value,
                    "configuration": hidden_configuration,
                },
            ),
        )
        return cls(family=family, manifest=manifest, catalogue=catalogue)

    @classmethod
    def from_manifest(cls, manifest: FamilyManifest) -> UnifiedFamilyAdapter:
        rebuilt = cls.build(
            family_code=manifest.family_code,
            seed=manifest.seed,
            probe_budget_units=manifest.probe_budget_units,
        )
        if rebuilt.manifest != manifest:
            raise UnifiedAdapterError("manifest binding mismatch")
        return rebuilt

    @property
    def manifest(self) -> FamilyManifest:
        return self._manifest

    @property
    def catalogue(self) -> VisibleProbeCatalogue:
        return self._catalogue

    def public_descriptor(self) -> PublicEnvironmentDescriptor:
        return self._family.public_descriptor()

    def state_digest(self) -> str:
        return self._family.state_digest()

    def execute(self, request: ProbeRequest) -> ProbeObservation:
        return self._family.execute(request)

    def hidden_score(
        self, bundle_digest: str, transcript: tuple[ProbeObservation, ...]
    ) -> HiddenScore:
        return self._family.hidden_score(bundle_digest, transcript)
