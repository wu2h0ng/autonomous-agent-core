from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Mapping, Sequence

from .canonical import canonical_json, content_digest


CHALLENGE_CATALOGUE_SCHEMA = "active-discovery-challenge-catalogue/v1"
SCORE_BUNDLE_SCHEMA = "active-discovery-score-bundle/v1"
STATEFUL_TEST_IR_SCHEMA = "active-discovery-stateful-test-ir/v2"
HIDDEN_SCORE_RECEIPT_SCHEMA = "active-discovery-hidden-score-receipt/v2"
PROBABILITY_SCALE = 1_000_000
_MODE = "NOT_EVIDENCE"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ScoringContractError(ValueError):
    """A successor scoring record escaped its closed data-only grammar."""


def _closed(raw: Mapping[str, Any], fields: frozenset[str], label: str) -> None:
    unknown = set(raw) - fields
    missing = fields - set(raw)
    if unknown:
        raise ScoringContractError(f"{label} has unknown fields: {sorted(unknown)}")
    if missing:
        raise ScoringContractError(f"{label} is missing fields: {sorted(missing)}")


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScoringContractError(f"{field} must be a non-empty string")
    if "\x00" in value:
        raise ScoringContractError(f"{field} must be NUL-free")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ScoringContractError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _integer(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ScoringContractError(
            f"{field} must be an integer in [{minimum},{maximum}]"
        )
    return value


def _canonical_object(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ScoringContractError(f"{field} must be canonical JSON text")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ScoringContractError(f"{field} must be valid JSON") from exc
    if not isinstance(decoded, dict) or canonical_json(decoded) != value:
        raise ScoringContractError(f"{field} must be a canonical JSON object")
    return value


def _fixed_literal(value: Any) -> None | bool | int | str | tuple[Any, ...]:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered.startswith(("$actual", "actual.", "${")):
            raise ScoringContractError("expected must be a fixed literal")
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_fixed_literal(item) for item in value)
    raise ScoringContractError("expected must be a fixed literal")


class StateRelation(str, Enum):
    SAME = "SAME"
    CHANGED = "CHANGED"


@dataclass(frozen=True, slots=True)
class OutcomeAtom:
    status_code: int
    stdout: str
    stderr: str
    output_json: str
    state_relation: StateRelation

    def __post_init__(self) -> None:
        if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
            raise ScoringContractError("status_code must be an integer")
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise ScoringContractError("stdout and stderr must be strings")
        _canonical_object(self.output_json, "output_json")
        if not isinstance(self.state_relation, StateRelation):
            raise ScoringContractError("state_relation must be SAME or CHANGED")

    @classmethod
    def create(
        cls,
        *,
        status_code: int,
        stdout: str,
        stderr: str,
        output: Mapping[str, Any],
        state_relation: str | StateRelation,
    ) -> OutcomeAtom:
        try:
            relation = StateRelation(state_relation)
        except (TypeError, ValueError) as exc:
            raise ScoringContractError(
                "state_relation must be SAME or CHANGED"
            ) from exc
        return cls(
            status_code=status_code,
            stdout=stdout,
            stderr=stderr,
            output_json=canonical_json(dict(output)),
            state_relation=relation,
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> OutcomeAtom:
        fields = frozenset(
            {"status_code", "stdout", "stderr", "output_json", "state_relation"}
        )
        _closed(raw, fields, "outcome atom")
        return cls.create(
            status_code=raw["status_code"],
            stdout=raw["stdout"],
            stderr=raw["stderr"],
            output=json.loads(_canonical_object(raw["output_json"], "output_json")),
            state_relation=raw["state_relation"],
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "status_code": self.status_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "output_json": self.output_json,
            "state_relation": self.state_relation.value,
        }


@dataclass(frozen=True, slots=True)
class BehaviorTrace:
    atoms: tuple[OutcomeAtom, ...]

    def __post_init__(self) -> None:
        if not self.atoms or any(not isinstance(item, OutcomeAtom) for item in self.atoms):
            raise ScoringContractError("behavior trace requires outcome atoms")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> BehaviorTrace:
        _closed(raw, frozenset({"atoms"}), "behavior trace")
        atoms_raw = raw["atoms"]
        if not isinstance(atoms_raw, list):
            raise ScoringContractError("behavior trace atoms must be a list")
        return cls(tuple(OutcomeAtom.from_mapping(item) for item in atoms_raw))

    def to_mapping(self) -> dict[str, object]:
        return {"atoms": [item.to_mapping() for item in self.atoms]}

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json(self.to_mapping()).encode("utf-8")

    @property
    def trace_digest(self) -> str:
        return content_digest("behavior-trace/v1", self.to_mapping())


@dataclass(frozen=True, slots=True)
class ChallengeStep:
    operation_id: str
    payload_json: str

    def __post_init__(self) -> None:
        _name(self.operation_id, "operation_id")
        _canonical_object(self.payload_json, "payload_json")

    @classmethod
    def create(
        cls, *, operation_id: str, payload: Mapping[str, Any]
    ) -> ChallengeStep:
        return cls(_name(operation_id, "operation_id"), canonical_json(dict(payload)))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ChallengeStep:
        _closed(raw, frozenset({"operation_id", "payload_json"}), "challenge step")
        return cls(
            _name(raw["operation_id"], "operation_id"),
            _canonical_object(raw["payload_json"], "payload_json"),
        )

    @property
    def request_mapping(self) -> dict[str, str]:
        return {"operation_id": self.operation_id, "payload_json": self.payload_json}

    def to_mapping(self) -> dict[str, str]:
        return self.request_mapping


def request_sequence_digest(steps: Sequence[ChallengeStep | StatefulTestStep]) -> str:
    return content_digest(
        "request-sequence/v1", [item.request_mapping for item in steps]
    )


@dataclass(frozen=True, slots=True)
class ChallengeSequence:
    reset_slot: str
    steps: tuple[ChallengeStep, ...]
    traces: tuple[BehaviorTrace, ...]

    def __post_init__(self) -> None:
        _name(self.reset_slot, "reset_slot")
        if not self.steps or any(not isinstance(item, ChallengeStep) for item in self.steps):
            raise ScoringContractError("challenge sequence requires ordered steps")
        if not self.traces:
            raise ScoringContractError("challenge sequence requires traces")
        if any(len(trace.atoms) != len(self.steps) for trace in self.traces):
            raise ScoringContractError("trace step count must match challenge step count")
        encodings = tuple(item.canonical_bytes for item in self.traces)
        if len(encodings) != len(set(encodings)):
            raise ScoringContractError("duplicate complete-trace encoding")
        if encodings != tuple(sorted(encodings)):
            raise ScoringContractError("complete traces must use canonical byte order")

    @classmethod
    def create(
        cls,
        *,
        reset_slot: str,
        steps: tuple[ChallengeStep, ...],
        traces: tuple[BehaviorTrace, ...],
    ) -> ChallengeSequence:
        return cls(reset_slot=_name(reset_slot, "reset_slot"), steps=steps, traces=traces)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ChallengeSequence:
        _closed(raw, frozenset({"reset_slot", "steps", "traces"}), "challenge")
        if not isinstance(raw["steps"], list) or not isinstance(raw["traces"], list):
            raise ScoringContractError("challenge steps and traces must be lists")
        return cls.create(
            reset_slot=raw["reset_slot"],
            steps=tuple(ChallengeStep.from_mapping(item) for item in raw["steps"]),
            traces=tuple(BehaviorTrace.from_mapping(item) for item in raw["traces"]),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "reset_slot": self.reset_slot,
            "steps": [item.to_mapping() for item in self.steps],
            "traces": [item.to_mapping() for item in self.traces],
        }

    @property
    def request_sequence_digest(self) -> str:
        return content_digest(
            "request-sequence/v1", [item.to_mapping() for item in self.steps]
        )

    @property
    def challenge_digest(self) -> str:
        return content_digest("challenge-sequence/v1", self.to_mapping())


@dataclass(frozen=True, slots=True)
class ChallengeCatalogue:
    schema_version: str
    instance_public_digest: str
    sequences: tuple[ChallengeSequence, ...]
    probe_sequence_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != CHALLENGE_CATALOGUE_SCHEMA:
            raise ScoringContractError("unsupported challenge catalogue schema")
        _digest(self.instance_public_digest, "instance_public_digest")
        if not self.sequences:
            raise ScoringContractError("challenge catalogue requires sequences")
        challenge_ids = tuple(item.challenge_digest for item in self.sequences)
        if len(challenge_ids) != len(set(challenge_ids)):
            raise ScoringContractError("challenge sequences must be unique")
        for value in self.probe_sequence_digests:
            _digest(value, "probe_sequence_digest")
        if len(self.probe_sequence_digests) != len(set(self.probe_sequence_digests)):
            raise ScoringContractError("probe sequence digests must be unique")

    @classmethod
    def create(
        cls,
        *,
        instance_public_digest: str,
        sequences: tuple[ChallengeSequence, ...],
        probe_sequence_digests: tuple[str, ...],
    ) -> ChallengeCatalogue:
        return cls(
            CHALLENGE_CATALOGUE_SCHEMA,
            _digest(instance_public_digest, "instance_public_digest"),
            sequences,
            probe_sequence_digests,
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ChallengeCatalogue:
        fields = frozenset(
            {
                "schema_version",
                "instance_public_digest",
                "sequences",
                "probe_sequence_digests",
            }
        )
        _closed(raw, fields, "challenge catalogue")
        if not isinstance(raw["sequences"], list) or not isinstance(
            raw["probe_sequence_digests"], list
        ):
            raise ScoringContractError("catalogue sequence fields must be lists")
        return cls(
            schema_version=raw["schema_version"],
            instance_public_digest=raw["instance_public_digest"],
            sequences=tuple(
                ChallengeSequence.from_mapping(item) for item in raw["sequences"]
            ),
            probe_sequence_digests=tuple(raw["probe_sequence_digests"]),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "instance_public_digest": self.instance_public_digest,
            "sequences": [item.to_mapping() for item in self.sequences],
            "probe_sequence_digests": list(self.probe_sequence_digests),
        }

    @property
    def catalogue_digest(self) -> str:
        return content_digest("challenge-catalogue/v1", self.to_mapping())

    @property
    def forbidden_sequence_digests(self) -> frozenset[str]:
        return frozenset(
            (*self.probe_sequence_digests, *(item.request_sequence_digest for item in self.sequences))
        )


@dataclass(frozen=True, slots=True)
class TraceProbability:
    trace_digest: str
    probability_micros: int

    def __post_init__(self) -> None:
        _digest(self.trace_digest, "trace_digest")
        _integer(
            self.probability_micros,
            "probability_micros",
            minimum=0,
            maximum=PROBABILITY_SCALE,
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> TraceProbability:
        _closed(raw, frozenset({"trace_digest", "probability_micros"}), "probability")
        return cls(raw["trace_digest"], raw["probability_micros"])

    def to_mapping(self) -> dict[str, object]:
        return {
            "trace_digest": self.trace_digest,
            "probability_micros": self.probability_micros,
        }


@dataclass(frozen=True, slots=True)
class ChallengePrediction:
    challenge_digest: str
    probabilities: tuple[TraceProbability, ...]
    predicted_trace_digest: str

    def __post_init__(self) -> None:
        _digest(self.challenge_digest, "challenge_digest")
        _digest(self.predicted_trace_digest, "predicted_trace_digest")
        if not self.probabilities:
            raise ScoringContractError("probability vector must be non-empty")
        trace_ids = tuple(item.trace_digest for item in self.probabilities)
        if len(trace_ids) != len(set(trace_ids)):
            raise ScoringContractError("probability vector contains duplicate traces")
        if sum(item.probability_micros for item in self.probabilities) != PROBABILITY_SCALE:
            raise ScoringContractError("probability vector must sum exactly to 1_000_000")
        object.__setattr__(
            self,
            "probabilities",
            tuple(sorted(self.probabilities, key=lambda item: item.trace_digest)),
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ChallengePrediction:
        fields = frozenset(
            {"challenge_digest", "probabilities", "predicted_trace_digest"}
        )
        _closed(raw, fields, "challenge prediction")
        if not isinstance(raw["probabilities"], list):
            raise ScoringContractError("probabilities must be a list")
        return cls(
            challenge_digest=raw["challenge_digest"],
            probabilities=tuple(
                TraceProbability.from_mapping(item) for item in raw["probabilities"]
            ),
            predicted_trace_digest=raw["predicted_trace_digest"],
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "challenge_digest": self.challenge_digest,
            "probabilities": [item.to_mapping() for item in self.probabilities],
            "predicted_trace_digest": self.predicted_trace_digest,
        }


class AssertionSource(str, Enum):
    STATUS_CODE = "STATUS_CODE"
    STDOUT = "STDOUT"
    STDERR = "STDERR"
    OUTPUT_JSON = "OUTPUT_JSON"
    STATE_RELATION = "STATE_RELATION"


class AssertionOperator(str, Enum):
    EQ = "EQ"
    NE = "NE"
    CONTAINS = "CONTAINS"


@dataclass(frozen=True, slots=True)
class StatefulTestAssertion:
    source: AssertionSource
    operator: AssertionOperator
    expected: None | bool | int | str | tuple[Any, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source, AssertionSource) or not isinstance(
            self.operator, AssertionOperator
        ):
            raise ScoringContractError("test assertion enum is invalid")
        _fixed_literal(self.expected)
        if self.operator is AssertionOperator.CONTAINS and not isinstance(
            self.expected, str
        ):
            raise ScoringContractError("CONTAINS requires a fixed string literal")

    @classmethod
    def create(
        cls, *, source: str, operator: str, expected: Any
    ) -> StatefulTestAssertion:
        try:
            source_value = AssertionSource(source)
            operator_value = AssertionOperator(operator)
        except (TypeError, ValueError) as exc:
            raise ScoringContractError("test assertion enum is invalid") from exc
        return cls(source_value, operator_value, _fixed_literal(expected))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> StatefulTestAssertion:
        _closed(raw, frozenset({"source", "operator", "expected"}), "assertion")
        return cls.create(
            source=raw["source"], operator=raw["operator"], expected=raw["expected"]
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "source": self.source.value,
            "operator": self.operator.value,
            "expected": self.expected,
        }


@dataclass(frozen=True, slots=True)
class StatefulTestStep:
    operation_id: str
    payload_json: str
    assertions: tuple[StatefulTestAssertion, ...]

    def __post_init__(self) -> None:
        _name(self.operation_id, "operation_id")
        _canonical_object(self.payload_json, "payload_json")
        if not self.assertions or any(
            not isinstance(item, StatefulTestAssertion) for item in self.assertions
        ):
            raise ScoringContractError("test step requires assertions")

    @classmethod
    def create(
        cls,
        *,
        operation_id: str,
        payload: object,
        assertions: tuple[StatefulTestAssertion, ...],
    ) -> StatefulTestStep:
        if not isinstance(payload, Mapping):
            raise ScoringContractError("payload must be a JSON object")
        return cls(operation_id, canonical_json(dict(payload)), assertions)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> StatefulTestStep:
        _closed(
            raw,
            frozenset({"operation_id", "payload_json", "assertions"}),
            "test step",
        )
        if not isinstance(raw["assertions"], list):
            raise ScoringContractError("test assertions must be a list")
        return cls(
            operation_id=raw["operation_id"],
            payload_json=raw["payload_json"],
            assertions=tuple(
                StatefulTestAssertion.from_mapping(item) for item in raw["assertions"]
            ),
        )

    @property
    def request_mapping(self) -> dict[str, str]:
        return {"operation_id": self.operation_id, "payload_json": self.payload_json}

    def to_mapping(self) -> dict[str, object]:
        return {
            **self.request_mapping,
            "assertions": [item.to_mapping() for item in self.assertions],
        }


@dataclass(frozen=True, slots=True)
class StatefulTestCase:
    test_id: str
    reset_slot: str
    steps: tuple[StatefulTestStep, ...]
    provenance_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _name(self.test_id, "test_id")
        _name(self.reset_slot, "reset_slot")
        if not 1 <= len(self.steps) <= 8:
            raise ScoringContractError("stateful test requires 1-8 ordered steps")
        if any(not isinstance(item, StatefulTestStep) for item in self.steps):
            raise ScoringContractError("stateful test step is invalid")
        if not self.provenance_refs or any(
            not isinstance(item, str) or not item for item in self.provenance_refs
        ):
            raise ScoringContractError("test requires provenance refs")
        if self.provenance_refs != tuple(sorted(set(self.provenance_refs))):
            raise ScoringContractError("provenance refs must be sorted and unique")
        forbidden = ("source", "filesystem", "network", "hidden", "score")
        if any(
            term in ref.lower()
            for ref in self.provenance_refs
            for term in forbidden
            if ref != "public-descriptor"
        ):
            raise ScoringContractError("test provenance is outside actor-visible data")

    @classmethod
    def create(
        cls,
        *,
        test_id: str,
        reset_slot: str,
        steps: tuple[StatefulTestStep, ...],
        provenance_refs: tuple[str, ...],
    ) -> StatefulTestCase:
        return cls(
            test_id=_name(test_id, "test_id"),
            reset_slot=_name(reset_slot, "reset_slot"),
            steps=steps,
            provenance_refs=tuple(sorted(set(provenance_refs))),
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> StatefulTestCase:
        fields = frozenset({"test_id", "reset_slot", "steps", "provenance_refs"})
        _closed(raw, fields, "stateful test")
        if not isinstance(raw["steps"], list) or not isinstance(
            raw["provenance_refs"], list
        ):
            raise ScoringContractError("test sequence fields must be lists")
        return cls.create(
            test_id=raw["test_id"],
            reset_slot=raw["reset_slot"],
            steps=tuple(StatefulTestStep.from_mapping(item) for item in raw["steps"]),
            provenance_refs=tuple(raw["provenance_refs"]),
        )

    @property
    def request_sequence_digest(self) -> str:
        return content_digest(
            "request-sequence/v1", [item.request_mapping for item in self.steps]
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "test_id": self.test_id,
            "reset_slot": self.reset_slot,
            "steps": [item.to_mapping() for item in self.steps],
            "provenance_refs": list(self.provenance_refs),
        }


@dataclass(frozen=True, slots=True)
class StatefulTestIR:
    tests: tuple[StatefulTestCase, ...]
    schema_version: str = STATEFUL_TEST_IR_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != STATEFUL_TEST_IR_SCHEMA:
            raise ScoringContractError("unsupported StatefulTestIR schema")
        if not 1 <= len(self.tests) <= 16:
            raise ScoringContractError("StatefulTestIR requires 1-16 tests")
        ids = tuple(item.test_id for item in self.tests)
        sequences = tuple(item.request_sequence_digest for item in self.tests)
        if len(ids) != len(set(ids)) or len(sequences) != len(set(sequences)):
            raise ScoringContractError("tests and request sequences must be unique")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> StatefulTestIR:
        _closed(raw, frozenset({"schema_version", "tests"}), "StatefulTestIR")
        if not isinstance(raw["tests"], list):
            raise ScoringContractError("StatefulTestIR tests must be a list")
        return cls(
            tests=tuple(StatefulTestCase.from_mapping(item) for item in raw["tests"]),
            schema_version=raw["schema_version"],
        )

    def validate_disjoint(self, forbidden_sequence_digests: frozenset[str]) -> None:
        overlap = {
            item.request_sequence_digest for item in self.tests
        } & forbidden_sequence_digests
        if overlap:
            raise ScoringContractError(
                "generated test copies an executed probe or public challenge sequence"
            )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "tests": [item.to_mapping() for item in self.tests],
        }

    @property
    def ir_digest(self) -> str:
        return content_digest("stateful-test-ir/v2", self.to_mapping())


@dataclass(frozen=True, slots=True)
class DiscoveryScoreBundle:
    schema_version: str
    mode: str
    experiment_id: str
    instance_public_digest: str
    arm_id: str
    actor_binding_digest: str
    prefix_index: int
    parent_bundle_digest: str | None
    predictions: tuple[ChallengePrediction, ...]
    test_ir: StatefulTestIR
    transcript_prefix_digest: str
    consumed_units: int
    budget_receipt_digest: str

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "mode",
            "experiment_id",
            "instance_public_digest",
            "arm_id",
            "actor_binding_digest",
            "prefix_index",
            "parent_bundle_digest",
            "predictions",
            "test_ir",
            "transcript_prefix_digest",
            "consumed_units",
            "budget_receipt_digest",
        }
    )

    def __post_init__(self) -> None:
        if self.schema_version != SCORE_BUNDLE_SCHEMA or self.mode != _MODE:
            raise ScoringContractError("bundle must use closed NOT_EVIDENCE schema")
        _name(self.experiment_id, "experiment_id")
        _digest(self.instance_public_digest, "instance_public_digest")
        _name(self.arm_id, "arm_id")
        _digest(self.actor_binding_digest, "actor_binding_digest")
        _integer(self.prefix_index, "prefix_index", minimum=0, maximum=4)
        if self.prefix_index == 0:
            if self.parent_bundle_digest is not None:
                raise ScoringContractError("prefix zero must have a null parent")
        else:
            _digest(self.parent_bundle_digest, "parent_bundle_digest")
        if not self.predictions:
            raise ScoringContractError("bundle requires challenge predictions")
        if not isinstance(self.test_ir, StatefulTestIR):
            raise ScoringContractError("bundle requires StatefulTestIR/v2")
        _digest(self.transcript_prefix_digest, "transcript_prefix_digest")
        _integer(self.consumed_units, "consumed_units", minimum=0, maximum=4)
        if self.consumed_units != self.prefix_index:
            raise ScoringContractError("consumed_units must equal prefix_index")
        _digest(self.budget_receipt_digest, "budget_receipt_digest")

    @classmethod
    def create(
        cls,
        *,
        experiment_id: str,
        instance_public_digest: str,
        arm_id: str,
        actor_binding_digest: str,
        prefix_index: int,
        parent_bundle_digest: str | None,
        predictions: tuple[ChallengePrediction, ...],
        test_ir: StatefulTestIR,
        transcript_prefix_digest: str,
        consumed_units: int,
        budget_receipt_digest: str,
        catalogue: ChallengeCatalogue,
    ) -> DiscoveryScoreBundle:
        bundle = cls(
            schema_version=SCORE_BUNDLE_SCHEMA,
            mode=_MODE,
            experiment_id=experiment_id,
            instance_public_digest=instance_public_digest,
            arm_id=arm_id,
            actor_binding_digest=actor_binding_digest,
            prefix_index=prefix_index,
            parent_bundle_digest=parent_bundle_digest,
            predictions=predictions,
            test_ir=test_ir,
            transcript_prefix_digest=transcript_prefix_digest,
            consumed_units=consumed_units,
            budget_receipt_digest=budget_receipt_digest,
        )
        bundle._validate_against_catalogue(catalogue)
        return bundle

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], catalogue: ChallengeCatalogue
    ) -> DiscoveryScoreBundle:
        _closed(raw, cls.FIELDS, "score bundle")
        if not isinstance(raw["predictions"], list) or not isinstance(
            raw["test_ir"], Mapping
        ):
            raise ScoringContractError("bundle nested fields are invalid")
        bundle = cls(
            schema_version=raw["schema_version"],
            mode=raw["mode"],
            experiment_id=raw["experiment_id"],
            instance_public_digest=raw["instance_public_digest"],
            arm_id=raw["arm_id"],
            actor_binding_digest=raw["actor_binding_digest"],
            prefix_index=raw["prefix_index"],
            parent_bundle_digest=raw["parent_bundle_digest"],
            predictions=tuple(
                ChallengePrediction.from_mapping(item) for item in raw["predictions"]
            ),
            test_ir=StatefulTestIR.from_mapping(raw["test_ir"]),
            transcript_prefix_digest=raw["transcript_prefix_digest"],
            consumed_units=raw["consumed_units"],
            budget_receipt_digest=raw["budget_receipt_digest"],
        )
        bundle._validate_against_catalogue(catalogue)
        return bundle

    def _validate_against_catalogue(self, catalogue: ChallengeCatalogue) -> None:
        if self.instance_public_digest != catalogue.instance_public_digest:
            raise ScoringContractError("bundle instance binding mismatch")
        expected = {item.challenge_digest: item for item in catalogue.sequences}
        actual = {item.challenge_digest: item for item in self.predictions}
        if len(actual) != len(self.predictions) or set(actual) != set(expected):
            raise ScoringContractError("bundle must predict every exact challenge once")
        for challenge_digest, prediction in actual.items():
            trace_ids = tuple(item.trace_digest for item in expected[challenge_digest].traces)
            probabilities = {item.trace_digest: item.probability_micros for item in prediction.probabilities}
            if set(probabilities) != set(trace_ids):
                raise ScoringContractError("probability vector must cover the exact trace universe")
            maximum = max(probabilities.values())
            if probabilities.get(prediction.predicted_trace_digest) != maximum:
                raise ScoringContractError(
                    "predicted trace must be a maximum-probability trace"
                )
        self.test_ir.validate_disjoint(catalogue.forbidden_sequence_digests)

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "experiment_id": self.experiment_id,
            "instance_public_digest": self.instance_public_digest,
            "arm_id": self.arm_id,
            "actor_binding_digest": self.actor_binding_digest,
            "prefix_index": self.prefix_index,
            "parent_bundle_digest": self.parent_bundle_digest,
            "predictions": [item.to_mapping() for item in self.predictions],
            "test_ir": self.test_ir.to_mapping(),
            "transcript_prefix_digest": self.transcript_prefix_digest,
            "consumed_units": self.consumed_units,
            "budget_receipt_digest": self.budget_receipt_digest,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json(self.to_mapping()).encode("utf-8")

    @property
    def bundle_digest(self) -> str:
        return content_digest("discovery-score-bundle/v1", self.to_mapping())

    def creation_arguments(
        self, *, catalogue: ChallengeCatalogue, **overrides: object
    ) -> dict[str, Any]:
        values: dict[str, Any] = {
            "experiment_id": self.experiment_id,
            "instance_public_digest": self.instance_public_digest,
            "arm_id": self.arm_id,
            "actor_binding_digest": self.actor_binding_digest,
            "prefix_index": self.prefix_index,
            "parent_bundle_digest": self.parent_bundle_digest,
            "predictions": self.predictions,
            "test_ir": self.test_ir,
            "transcript_prefix_digest": self.transcript_prefix_digest,
            "consumed_units": self.consumed_units,
            "budget_receipt_digest": self.budget_receipt_digest,
            "catalogue": catalogue,
        }
        values.update(overrides)
        return values


@dataclass(frozen=True, slots=True)
class HiddenScoreReceipt:
    scorer_source_digest: str
    hidden_commitment_digest: str
    reveal_policy_digest: str
    challenge_catalogue_digest: str
    target_digest: str
    contrast_digest: str
    transcript_digest: str
    prefix_bundle_digests: tuple[str, ...]
    final_bundle_digest: str
    h_micros: int
    c_micros: int
    t_micros: int
    score_micros: int
    auc_qe_micros: int
    calibration_digest: str
    count_digest: str
    budget_receipt_digest: str
    c7_receipt_digest: str
    details_digest: str
    schema_version: str = HIDDEN_SCORE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != HIDDEN_SCORE_RECEIPT_SCHEMA:
            raise ScoringContractError("unsupported hidden score receipt schema")
        for field_name in (
            "scorer_source_digest",
            "hidden_commitment_digest",
            "reveal_policy_digest",
            "challenge_catalogue_digest",
            "target_digest",
            "contrast_digest",
            "transcript_digest",
            "final_bundle_digest",
            "calibration_digest",
            "count_digest",
            "budget_receipt_digest",
            "c7_receipt_digest",
            "details_digest",
        ):
            _digest(getattr(self, field_name), field_name)
        for value in self.prefix_bundle_digests:
            _digest(value, "prefix_bundle_digest")
        for field_name in (
            "h_micros",
            "c_micros",
            "t_micros",
            "score_micros",
            "auc_qe_micros",
        ):
            _integer(
                getattr(self, field_name), field_name, minimum=0, maximum=PROBABILITY_SCALE
            )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scorer_source_digest": self.scorer_source_digest,
            "hidden_commitment_digest": self.hidden_commitment_digest,
            "reveal_policy_digest": self.reveal_policy_digest,
            "challenge_catalogue_digest": self.challenge_catalogue_digest,
            "target_digest": self.target_digest,
            "contrast_digest": self.contrast_digest,
            "transcript_digest": self.transcript_digest,
            "prefix_bundle_digests": list(self.prefix_bundle_digests),
            "final_bundle_digest": self.final_bundle_digest,
            "h_micros": self.h_micros,
            "c_micros": self.c_micros,
            "t_micros": self.t_micros,
            "score_micros": self.score_micros,
            "auc_qe_micros": self.auc_qe_micros,
            "calibration_digest": self.calibration_digest,
            "count_digest": self.count_digest,
            "budget_receipt_digest": self.budget_receipt_digest,
            "c7_receipt_digest": self.c7_receipt_digest,
            "details_digest": self.details_digest,
        }

    @property
    def receipt_digest(self) -> str:
        return content_digest("hidden-score-receipt/v2", self.to_mapping())
