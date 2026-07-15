from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .budget import BudgetLedger
from .canonical import canonical_json, content_digest
from .contracts import ProbeRequest, PublicEnvironmentDescriptor
from .families.opaque_cli import (
    OpaqueCliFamily,
    OpaqueCliSemantics,
    RepeatMode,
    UnknownMode,
)
from .referee import SealedRefereeSession


DEV_SCHEMA = "active-discovery-dev/v1"


class DevelopmentSpecError(ValueError):
    """A development-only qualification spec is not closed and inert."""


@dataclass(frozen=True, slots=True)
class DevelopmentSpec:
    schema_version: str
    mode: str
    family_seed: int
    budget_limit: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> DevelopmentSpec:
        fields = frozenset({"schema_version", "mode", "family_seed", "budget_limit"})
        unknown = set(raw) - fields
        missing = fields - set(raw)
        if unknown:
            raise DevelopmentSpecError(f"unknown fields: {sorted(unknown)}")
        if missing:
            raise DevelopmentSpecError(f"missing fields: {sorted(missing)}")
        if raw["schema_version"] != DEV_SCHEMA or raw["mode"] != "NOT_EVIDENCE":
            raise DevelopmentSpecError(
                "development spec must use NOT_EVIDENCE schema and mode"
            )
        seed = raw["family_seed"]
        budget = raw["budget_limit"]
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise DevelopmentSpecError("family_seed must be an integer")
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 2:
            raise DevelopmentSpecError("budget_limit must be an integer >= 2")
        return cls(DEV_SCHEMA, "NOT_EVIDENCE", seed, budget)

    @property
    def spec_digest(self) -> str:
        return content_digest(
            "development-spec",
            {
                "schema_version": self.schema_version,
                "mode": self.mode,
                "family_seed": self.family_seed,
                "budget_limit": self.budget_limit,
            },
        )


class _NeverHalted:
    def halted(self, episode_id: str) -> bool:
        return False


def _load_spec(path: str) -> DevelopmentSpec:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise DevelopmentSpecError("development spec must be a JSON object")
    return DevelopmentSpec.from_mapping(raw)


def _family(spec: DevelopmentSpec) -> OpaqueCliFamily:
    return OpaqueCliFamily(
        seed=spec.family_seed,
        semantics=OpaqueCliSemantics(
            source_precedence=("map_two", "sequence", "map_one"),
            repeat_mode=RepeatMode.LAST,
            unknown_mode=UnknownMode.ERROR,
            empty_is_missing=True,
            atomic_on_error=True,
        ),
    )


def _payloads(descriptor: PublicEnvironmentDescriptor) -> tuple[str, str]:
    schema = json.loads(descriptor.schema_json)
    sequence_field, map_one_field, map_two_field = [
        item["field_id"] for item in schema["input_fields"]
    ]
    token = schema["tokens"]["setting"]
    empty = {
        sequence_field: [],
        map_one_field: {},
        map_two_field: {},
    }
    conflict = {
        sequence_field: [f"{token}=sequence-value"],
        map_one_field: {token: "map-one-value"},
        map_two_field: {token: "map-two-value"},
    }
    return canonical_json(empty), canonical_json(conflict)


def _run_qualification(spec: DevelopmentSpec) -> tuple[tuple[str, ...], str, str]:
    family = _family(spec)
    descriptor = family.public_descriptor()
    budget = BudgetLedger(spec.budget_limit)
    session = SealedRefereeSession(
        episode_id="qualification-episode",
        adapter=family,
        budget=budget,
        halt_authority=_NeverHalted(),
    )
    observations = []
    for step, payload in enumerate(_payloads(descriptor)):
        request = ProbeRequest.from_mapping(
            {
                "episode_id": "qualification-episode",
                "arm_id": "QUALIFY_DEV",
                "step_index": step,
                "probe_id": f"qualification-probe-{step}",
                "operation_id": descriptor.operation_id,
                "payload_json": payload,
                "expected_state_digest": family.state_digest(),
                "cost_units": 1,
            }
        )
        observations.append(session.probe(request).observation_digest)
    return tuple(observations), budget.ledger_digest, descriptor.descriptor_digest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="active-discovery")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate-spec", "qualify-dev"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--spec", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    spec = _load_spec(args.spec)
    if args.command == "validate-spec":
        print(
            canonical_json(
                {
                    "status": "VALID",
                    "mode": "NOT_EVIDENCE",
                    "qualification_only": True,
                    "spec_digest": spec.spec_digest,
                }
            )
        )
        return 0

    first, ledger_digest, descriptor_digest = _run_qualification(spec)
    replay, replay_ledger_digest, replay_descriptor_digest = _run_qualification(spec)
    print(
        canonical_json(
            {
                "status": "NOT_EVIDENCE",
                "qualification_only": True,
                "spec_digest": spec.spec_digest,
                "descriptor_digest": descriptor_digest,
                "budget_ledger_digest": ledger_digest,
                "observation_digests": list(first),
                "replay_match": (
                    first == replay
                    and ledger_digest == replay_ledger_digest
                    and descriptor_digest == replay_descriptor_digest
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
