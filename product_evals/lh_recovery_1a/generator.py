"""Canonical D1E-PGP-2 deterministic generator."""

from __future__ import annotations

from ast import Attribute, Call, Constant, Name, Subscript, parse, walk
from dataclasses import dataclass
from hashlib import sha256
from hmac import new
from json import dumps
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from unicodedata import normalize


@dataclass(frozen=True, slots=True)
class PopulationDesign:
    families: tuple[str, ...]
    regimes: tuple[str, ...]
    failures: tuple[str, ...]
    latin_orders: tuple[str, ...]
    replicates: tuple[int, ...]
    instances_per_family_regime_failure_order_cell: int
    instances_per_family_regime_failure_cell: int
    instance_count: int
    arms_per_instance: int
    episode_count: int
    instances_per_family: int
    instances_per_regime: int
    instances_per_failure: int
    instances_per_latin_order: int
    instances_per_replicate: int


@dataclass(frozen=True, slots=True)
class CaseCoordinate:
    family: str
    regime: str
    failure: str
    latin_order: str
    replicate: int


@dataclass(frozen=True, slots=True)
class GeneratedCase:
    coordinate: CaseCoordinate
    case_id: str
    case_seed: bytes
    declaration: SemanticFixtureDeclaration


@dataclass(frozen=True, slots=True)
class StringTransformSpec:
    text_v1: str
    text_v2: str
    operation: str


@dataclass(frozen=True, slots=True)
class NumericReducerSpec:
    values_v1: tuple[int, ...]
    values_v2: tuple[int, ...]
    operation: str


@dataclass(frozen=True, slots=True)
class ValidatorSpec:
    value_v1: str
    value_v2: str
    rule: str


@dataclass(frozen=True, slots=True)
class FormatterSpec:
    template: str
    values_v1: tuple[tuple[str, object], ...]
    values_v2: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class RecordFilterSpec:
    records_v1: tuple[tuple[tuple[str, object], ...], ...]
    records_v2: tuple[tuple[tuple[str, object], ...], ...]
    field: str
    equals: object


@dataclass(frozen=True, slots=True)
class SmallStateMachineSpec:
    initial_state: str
    events_v1: tuple[str, ...]
    events_v2: tuple[str, ...]
    transitions: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True)
class FamilyArtifacts:
    fixture: object
    requirement_v1: object
    requirement_v2: object
    initial_content: object
    final_content: object
    test: object
    prompt: object
    expected_result: object
    provider_response: object


@dataclass(frozen=True, slots=True)
class SemanticFixtureDeclaration:
    case_id: str
    family: str
    family_spec: object
    fixture_id: str
    fixture_prefix: str
    fixture_version_v1: int
    fixture_version_v2: int
    fixture: object
    requirement_v1: object
    requirement_v2: object
    initial_content: object
    final_content: object
    test: object
    prompt: object
    expected_result: object
    provider_response: object


TASK_FAMILIES = (
    "string_transform",
    "numeric_reducer",
    "validator",
    "formatter",
    "record_filter",
    "small_state_machine",
)
REGIME_NAMES = (
    "R0_DIRECT_REFRESH",
    "R1_DEPENDENCY_BEFORE_PROVIDER",
    "R2_RELEASE_BEFORE_APPLY",
)
FAILURE_NAMES = (
    "PRE_CONSEQUENCE_PROCESS_EXIT",
    "POST_APPLY_WORKER_INTERRUPTED",
    "CORRECTION_HALT_BEFORE_APPLY",
)
LATIN_ORDER_NAMES = ("W0", "W1", "W2", "W3")
SEMANTIC_CHANNELS = (
    "fixture",
    "requirement_v1",
    "requirement_v2",
    "initial_content",
    "final_content",
    "test",
    "prompt",
    "expected_result",
    "provider_response",
)
SEMANTIC_NORMALIZATION_STEPS = (
    "unicode_nfkc",
    "normalize_newlines_lf",
    "strip_trailing_line_whitespace",
    "canonical_json_sorted_keys",
    "utf8",
)
NO_RESCUE_RULES = (
    "NO_SEED_CHANGE",
    "NO_CASE_REMOVAL_OR_REPLACEMENT",
    "NO_BASELINE_WEAKENING",
    "NO_THRESHOLD_MOVEMENT",
    "NO_ENVIRONMENT_CHANGE",
    "NO_METRIC_SUBSTITUTION",
    "NO_RERUN",
    "NO_RESCUE",
)
FORBIDDEN_PRE_D1_BASENAMES = (
    "fixed_baseline.py",
    "fixed_dag.json",
    "d1_f.json",
    "LH-RECOVERY-1A-D1-F.yaml",
    "LH-RECOVERY-1A-COMBINED-D1-PRECOMMIT.yaml",
    "LH-RECOVERY-1A-preregistration-spec.yaml",
    "frozen_tasks.json",
    "assignments.json",
    "provider_bank.json",
    "provider_responses.json",
    "failure_schedule.json",
)
FORBIDDEN_PRE_D1_PATTERNS = (
    "root_seed*",
    "*root_seed*",
    "*nonce*",
    "*corpus*",
    "*provider_bank*",
    "*oracle*",
    "*fixed-dag*",
    "*fixed_dag*",
    "*d1-f*",
    "*d1_f*",
    "*d2*",
)
_PGP2_FORBIDDEN_LEDGER_ROOTS = (
    "approvalrequests",
    "approvals",
    "handoff",
    "messages",
    "teammessages",
    "auditledger",
    "mutableledger",
)
_PGP2_FORBIDDEN_DIGEST_MARKERS = (
    "archive",
    "checksum",
    "digest",
    "filehash",
    "hash",
    "sha",
    "snapshot",
    "wholefile",
)
WILLIAMS_ORDERS = MappingProxyType(
    {
        "W0": ("C", "F", "K", "R"),
        "W1": ("F", "R", "C", "K"),
        "W2": ("R", "K", "F", "C"),
        "W3": ("K", "C", "R", "F"),
    }
)
SEMANTIC_NORMALIZATION_RULES = MappingProxyType(
    {
        "fixture": SEMANTIC_NORMALIZATION_STEPS,
        "requirement_v1": SEMANTIC_NORMALIZATION_STEPS,
        "requirement_v2": SEMANTIC_NORMALIZATION_STEPS,
        "initial_content": SEMANTIC_NORMALIZATION_STEPS,
        "final_content": SEMANTIC_NORMALIZATION_STEPS,
        "test": SEMANTIC_NORMALIZATION_STEPS,
        "prompt": SEMANTIC_NORMALIZATION_STEPS,
        "expected_result": SEMANTIC_NORMALIZATION_STEPS,
        "provider_response": SEMANTIC_NORMALIZATION_STEPS,
    }
)
FAMILY_IR = (
    ("string_transform", "upper"),
    ("numeric_reducer", "sum"),
    ("validator", "contains_digit"),
    ("formatter", "name_count"),
    ("record_filter", "equals"),
    ("small_state_machine", "linear"),
)
FAMILY_SPEC_TYPES = MappingProxyType(
    {
        "string_transform": StringTransformSpec,
        "numeric_reducer": NumericReducerSpec,
        "validator": ValidatorSpec,
        "formatter": FormatterSpec,
        "record_filter": RecordFilterSpec,
        "small_state_machine": SmallStateMachineSpec,
    }
)
POPULATION_DESIGN = PopulationDesign(
    TASK_FAMILIES,
    REGIME_NAMES,
    FAILURE_NAMES,
    LATIN_ORDER_NAMES,
    (0, 1),
    2,
    8,
    432,
    4,
    1728,
    72,
    144,
    144,
    108,
    216,
)


def _pgp2_require_json_tree(value):
    value_type = type(value)
    if value is None or value_type is bool or value_type is int or value_type is str:
        return
    if value_type is float:
        if not isfinite(value):
            raise ValueError("non-finite float")
        return
    if value_type is list or value_type is tuple:
        for item in value:
            _pgp2_require_json_tree(item)
        return
    if value_type is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("JSON keys must be exact strings")
            _pgp2_require_json_tree(item)
        return
    raise TypeError("value is outside the exact JSON tree")


def _pgp2_normalize_text(value):
    if type(value) is not str:
        raise TypeError("text must be an exact string")
    normalized = normalize("NFKC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in normalized.split("\n"):
        lines.append(line.rstrip(" \t"))
    return "\n".join(lines)


def _pgp2_normalize_json(value):
    value_type = type(value)
    if value is None or value_type is bool or value_type is int:
        return value
    if value_type is float:
        if not isfinite(value):
            raise ValueError("non-finite float")
        return value
    if value_type is str:
        return _pgp2_normalize_text(value)
    if value_type is list or value_type is tuple:
        list_result = []
        for item in value:
            list_result.append(_pgp2_normalize_json(item))
        return list_result
    if value_type is dict:
        dict_result = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("JSON keys must be exact strings")
            normalized_key = _pgp2_normalize_text(key)
            if normalized_key in dict_result:
                raise ValueError("normalized key collision")
            dict_result[normalized_key] = _pgp2_normalize_json(item)
        return dict_result
    raise TypeError("value is outside the exact JSON tree")


def _pgp2_validate_coordinate(coordinate):
    if type(coordinate) is not CaseCoordinate:
        raise TypeError("coordinate must be exact CaseCoordinate")
    if type(coordinate.family) is not str:
        raise TypeError("family must be exact str")
    if type(coordinate.regime) is not str:
        raise TypeError("regime must be exact str")
    if type(coordinate.failure) is not str:
        raise TypeError("failure must be exact str")
    if type(coordinate.latin_order) is not str:
        raise TypeError("latin_order must be exact str")
    if type(coordinate.replicate) is not int:
        raise TypeError("replicate must be exact int")
    if coordinate.family not in TASK_FAMILIES:
        raise ValueError("undeclared family")
    if coordinate.regime not in REGIME_NAMES:
        raise ValueError("undeclared regime")
    if coordinate.failure not in FAILURE_NAMES:
        raise ValueError("undeclared failure")
    if coordinate.latin_order not in LATIN_ORDER_NAMES:
        raise ValueError("undeclared latin order")
    if coordinate.replicate not in (0, 1):
        raise ValueError("undeclared replicate")


def _pgp2_validate_family_spec(spec):
    spec_type = type(spec)
    if spec_type is StringTransformSpec:
        if type(spec.text_v1) is not str or type(spec.text_v2) is not str:
            raise TypeError("string transform text must be exact str")
        if type(spec.operation) is not str or spec.operation != "upper":
            raise ValueError("unsupported string transform")
        return "string_transform"
    if spec_type is NumericReducerSpec:
        if type(spec.values_v1) is not tuple or type(spec.values_v2) is not tuple:
            raise TypeError("numeric values must be exact tuples")
        for value in spec.values_v1:
            if type(value) is not int:
                raise TypeError("numeric values must be exact ints")
        for value in spec.values_v2:
            if type(value) is not int:
                raise TypeError("numeric values must be exact ints")
        if type(spec.operation) is not str or spec.operation != "sum":
            raise ValueError("unsupported numeric reducer")
        return "numeric_reducer"
    if spec_type is ValidatorSpec:
        if type(spec.value_v1) is not str or type(spec.value_v2) is not str:
            raise TypeError("validator values must be exact str")
        if type(spec.rule) is not str or spec.rule != "contains_digit":
            raise ValueError("unsupported validator")
        return "validator"
    if spec_type is FormatterSpec:
        if type(spec.template) is not str or spec.template != "{name}:{count:02d}":
            raise ValueError("unsupported formatter template")
        for values in (spec.values_v1, spec.values_v2):
            if type(values) is not tuple:
                raise TypeError("formatter values must be exact tuples")
            for pair in values:
                if type(pair) is not tuple or len(pair) != 2:
                    raise TypeError("formatter pair must be exact two-tuple")
                if type(pair[0]) is not str:
                    raise TypeError("formatter key must be exact str")
                _pgp2_require_json_tree(pair[1])
        return "formatter"
    if spec_type is RecordFilterSpec:
        for records in (spec.records_v1, spec.records_v2):
            if type(records) is not tuple:
                raise TypeError("records must be exact tuples")
            for record in records:
                if type(record) is not tuple:
                    raise TypeError("record must be exact tuple")
                for pair in record:
                    if type(pair) is not tuple or len(pair) != 2:
                        raise TypeError("record pair must be exact two-tuple")
                    if type(pair[0]) is not str:
                        raise TypeError("record key must be exact str")
                    _pgp2_require_json_tree(pair[1])
        if type(spec.field) is not str:
            raise TypeError("record field must be exact str")
        _pgp2_require_json_tree(spec.equals)
        return "record_filter"
    if spec_type is SmallStateMachineSpec:
        if type(spec.initial_state) is not str:
            raise TypeError("initial state must be exact str")
        for events in (spec.events_v1, spec.events_v2):
            if type(events) is not tuple:
                raise TypeError("events must be exact tuple")
            for event in events:
                if type(event) is not str:
                    raise TypeError("event must be exact str")
        if type(spec.transitions) is not tuple:
            raise TypeError("transitions must be exact tuple")
        for transition in spec.transitions:
            if type(transition) is not tuple or len(transition) != 3:
                raise TypeError("transition must be exact three-tuple")
            for value in transition:
                if type(value) is not str:
                    raise TypeError("transition value must be exact str")
        return "small_state_machine"
    raise TypeError("unknown family spec")


def _pgp2_reference_result(spec, version):
    if type(version) is not str:
        raise TypeError("version must be exact str")
    if version not in ("v1", "v2"):
        raise ValueError("unsupported version")
    family = _pgp2_validate_family_spec(spec)
    if family == "string_transform":
        if version == "v1":
            return spec.text_v1.upper()
        return spec.text_v2.upper()
    if family == "numeric_reducer":
        if version == "v1":
            return sum(spec.values_v1)
        return sum(spec.values_v2)
    if family == "validator":
        if version == "v1":
            value = spec.value_v1
        else:
            value = spec.value_v2
        for character in value:
            if character.isdigit():
                return True
        return False
    if family == "formatter":
        if version == "v1":
            values = dict(spec.values_v1)
        else:
            values = dict(spec.values_v2)
        return str(values["name"]) + ":" + str(values["count"]).rjust(2, "0")
    if family == "record_filter":
        if version == "v1":
            records = spec.records_v1
        else:
            records = spec.records_v2
        result = []
        for record in records:
            if dict(record).get(spec.field) == spec.equals:
                result.append(record)
        return tuple(result)
    transitions = {}
    for source, event, target in spec.transitions:
        key = (source, event)
        if key in transitions:
            raise ValueError("ambiguous transition")
        transitions[key] = target
    state = spec.initial_state
    if version == "v1":
        events = spec.events_v1
    else:
        events = spec.events_v2
    for event in events:
        key = (state, event)
        if key not in transitions:
            raise ValueError("unsupported transition")
        state = transitions[key]
    return state


def _pgp2_family_artifacts(spec):
    family = _pgp2_validate_family_spec(spec)
    initial = _pgp2_reference_result(spec, "v1")
    final = _pgp2_reference_result(spec, "v2")
    requirement_v1 = "produce:" + repr(initial)
    requirement_v2 = "produce:" + repr(final)
    test_text = "assert result == " + repr(final)
    return FamilyArtifacts(
        {"family": family, "v1": initial, "v2": final},
        requirement_v1,
        requirement_v2,
        initial,
        final,
        test_text,
        requirement_v2,
        final,
        {"result": final},
    )


def _pgp2_channel_value(declaration, channel):
    if channel == "fixture":
        return declaration.fixture
    if channel == "requirement_v1":
        return declaration.requirement_v1
    if channel == "requirement_v2":
        return declaration.requirement_v2
    if channel == "initial_content":
        return declaration.initial_content
    if channel == "final_content":
        return declaration.final_content
    if channel == "test":
        return declaration.test
    if channel == "prompt":
        return declaration.prompt
    if channel == "expected_result":
        return declaration.expected_result
    if channel == "provider_response":
        return declaration.provider_response
    raise ValueError("unknown semantic channel")


def _pgp2_make_family_spec(family, case_id, case_seed):
    if family == "string_transform":
        return StringTransformSpec(
            case_id + ":agent os", case_id + ":agent core", "upper"
        )
    if family == "numeric_reducer":
        number = int.from_bytes(case_seed, "big")
        return NumericReducerSpec((number,), (number, 1), "sum")
    if family == "validator":
        if type(case_id) is not str:
            raise TypeError("validator case_id must be exact str")
        if case_id[:10] != "validator-":
            raise ValueError("validator case_id prefix mismatch")
        suffix = case_id[10:]
        if len(suffix) != 64:
            raise ValueError("validator case_id suffix length mismatch")
        for character in suffix:
            if character not in "0123456789abcdef":
                raise ValueError("validator case_id suffix must be lowercase hex")
        semantic_suffix = suffix
        for source, target in (
            ("0", "g"),
            ("1", "h"),
            ("2", "i"),
            ("3", "j"),
            ("4", "k"),
            ("5", "l"),
            ("6", "m"),
            ("7", "n"),
            ("8", "o"),
            ("9", "p"),
        ):
            transformed_suffix = ""
            for character in semantic_suffix:
                if character == source:
                    transformed_suffix += target
                else:
                    transformed_suffix += character
            semantic_suffix = transformed_suffix
        semantic_token = "validator-" + semantic_suffix
        value_v1 = "agent-" + semantic_token
        return ValidatorSpec(value_v1, value_v1 + "-7", "contains_digit")
    if family == "formatter":
        return FormatterSpec(
            "{name}:{count:02d}",
            (("name", case_id), ("count", 1)),
            (("name", case_id), ("count", 2)),
        )
    if family == "record_filter":
        return RecordFilterSpec(
            ((("case", case_id), ("keep", False)),),
            (
                (("case", case_id), ("keep", True)),
                (("case", case_id), ("keep", False)),
            ),
            "keep",
            True,
        )
    if family == "small_state_machine":
        idle = case_id + ":idle"
        running = case_id + ":running"
        done = case_id + ":done"
        return SmallStateMachineSpec(
            idle,
            ("start",),
            ("start", "finish"),
            ((idle, "start", running), (running, "finish", done)),
        )
    raise ValueError("undeclared family")


def _pgp2_generate_case(root_seed, coordinate):
    _pgp2_validate_coordinate(coordinate)
    case_seed = derive_case_seed(root_seed, coordinate)
    case_id = coordinate.family + "-" + case_seed.hex()
    family_spec = _pgp2_make_family_spec(coordinate.family, case_id, case_seed)
    artifacts = _pgp2_family_artifacts(family_spec)
    declaration = SemanticFixtureDeclaration(
        case_id,
        coordinate.family,
        family_spec,
        case_id + "-fixture",
        case_id,
        1,
        2,
        artifacts.fixture,
        artifacts.requirement_v1,
        artifacts.requirement_v2,
        artifacts.initial_content,
        artifacts.final_content,
        artifacts.test,
        artifacts.prompt,
        artifacts.expected_result,
        artifacts.provider_response,
    )
    return GeneratedCase(coordinate, case_id, case_seed, declaration)


def _pgp2_generate_cases(root_seed):
    if type(root_seed) is not bytes:
        raise TypeError("root_seed must be exact bytes")
    if len(root_seed) != 32:
        raise ValueError("root_seed must be 32 bytes")
    result = []
    for family in TASK_FAMILIES:
        for regime in REGIME_NAMES:
            for failure in FAILURE_NAMES:
                for latin_order in LATIN_ORDER_NAMES:
                    for replicate in (0, 1):
                        coordinate = CaseCoordinate(
                            family, regime, failure, latin_order, replicate
                        )
                        result.append(_pgp2_generate_case(root_seed, coordinate))
    return tuple(result)


def _pgp2_semantic_uniqueness(declarations):
    if type(declarations) is not tuple:
        raise TypeError("declarations must be exact tuple")
    seen_case_ids = []
    seen_family_specs = []
    seen_fixture_ids = []
    seen_fixture_prefixes = []
    duplicate_case_id = False
    duplicate_family_spec = False
    duplicate_fixture_id = False
    duplicate_fixture_prefix = False
    for declaration in declarations:
        if type(declaration) is not SemanticFixtureDeclaration:
            raise TypeError("declaration must be exact SemanticFixtureDeclaration")
        if type(declaration.case_id) is not str:
            raise TypeError("case_id must be exact str")
        if type(declaration.fixture_id) is not str:
            raise TypeError("fixture_id must be exact str")
        if type(declaration.fixture_prefix) is not str:
            raise TypeError("fixture_prefix must be exact str")
        _pgp2_validate_family_spec(declaration.family_spec)
        if declaration.case_id in seen_case_ids:
            duplicate_case_id = True
        else:
            seen_case_ids.append(declaration.case_id)
        matching_family_spec = False
        for seen_family_spec in seen_family_specs:
            if type(declaration.family_spec) is type(seen_family_spec):
                if declaration.family_spec == seen_family_spec:
                    matching_family_spec = True
                    break
        if matching_family_spec:
            duplicate_family_spec = True
        else:
            seen_family_specs.append(declaration.family_spec)
        if declaration.fixture_id in seen_fixture_ids:
            duplicate_fixture_id = True
        else:
            seen_fixture_ids.append(declaration.fixture_id)
        if declaration.fixture_prefix in seen_fixture_prefixes:
            duplicate_fixture_prefix = True
        else:
            seen_fixture_prefixes.append(declaration.fixture_prefix)
    violations = []
    if duplicate_case_id:
        violations.append("DUPLICATE_CASE_ID")
    if duplicate_family_spec:
        violations.append("DUPLICATE_FAMILY_SPEC")
    if duplicate_fixture_id:
        violations.append("DUPLICATE_FIXTURE_ID")
    if duplicate_fixture_prefix:
        violations.append("DUPLICATE_FIXTURE_PREFIX")
    return tuple(violations)


def _pgp2_validate_family_semantics(declaration):
    if type(declaration) is not SemanticFixtureDeclaration:
        raise TypeError("declaration must be exact SemanticFixtureDeclaration")
    expected_type = None
    if declaration.family == "string_transform":
        expected_type = StringTransformSpec
    elif declaration.family == "numeric_reducer":
        expected_type = NumericReducerSpec
    elif declaration.family == "validator":
        expected_type = ValidatorSpec
    elif declaration.family == "formatter":
        expected_type = FormatterSpec
    elif declaration.family == "record_filter":
        expected_type = RecordFilterSpec
    elif declaration.family == "small_state_machine":
        expected_type = SmallStateMachineSpec
    else:
        return ("FAMILY_UNDECLARED",)
    if type(declaration.family_spec) is not expected_type:
        return ("FAMILY_SPEC_TYPE_MISMATCH",)
    artifacts = _pgp2_family_artifacts(declaration.family_spec)
    violations = []
    for channel in SEMANTIC_CHANNELS:
        actual = _pgp2_channel_value(declaration, channel)
        _pgp2_require_json_tree(actual)
        expected = _pgp2_channel_value(artifacts, channel)
        if actual != expected:
            violations.append("FAMILY_ARTIFACT_MISMATCH_" + channel.upper())
    return tuple(violations)


def _pgp2_validate_fixture_lineage(declaration):
    if type(declaration) is not SemanticFixtureDeclaration:
        raise TypeError("declaration must be exact SemanticFixtureDeclaration")
    violations = []
    if (
        type(declaration.fixture_version_v1) is not int
        or type(declaration.fixture_version_v2) is not int
    ):
        raise TypeError("fixture versions must be exact ints")
    if declaration.fixture_version_v2 <= declaration.fixture_version_v1:
        violations.append("FIXTURE_VERSION_NOT_INCREMENTED")
    if (
        type(declaration.fixture_id) is not str
        or type(declaration.fixture_prefix) is not str
    ):
        raise TypeError("fixture identifiers must be exact str")
    if not declaration.fixture_id.startswith(declaration.fixture_prefix + "-"):
        violations.append("FIXTURE_ID_PREFIX_MISMATCH")
    if declaration.requirement_v2 == declaration.requirement_v1:
        violations.append("REQUIREMENT_CHANGE_MISSING")
    if declaration.final_content == declaration.initial_content:
        violations.append("CONTENT_CHANGE_MISSING")
    artifacts = _pgp2_family_artifacts(declaration.family_spec)
    if declaration.requirement_v2 != artifacts.requirement_v2:
        violations.append("REQUIREMENT_V2_NOT_LINKED_TO_FINAL")
    if declaration.expected_result != artifacts.expected_result:
        violations.append("EXPECTED_RESULT_NOT_LINKED_TO_FINAL")
    if declaration.test != artifacts.test:
        violations.append("TEST_NOT_LINKED_TO_FINAL")
    if declaration.provider_response != artifacts.provider_response:
        violations.append("PROVIDER_RESPONSE_NOT_LINKED_TO_FINAL")
    return tuple(violations)


def _pgp2_is_forbidden_digest_name(value):
    if type(value) is not str:
        return False
    lowered = value.lower()
    collapsed = ""
    for character in lowered:
        if character.isalnum():
            collapsed = collapsed + character
    if collapsed in (
        "canonicalrequestrowsha256",
        "canonicalapprovalrowsha256",
        "matchingrowsha256",
        "canonicalledgerheadsha256",
        "githeadbloboid",
    ):
        return False
    root_found = False
    for root in _PGP2_FORBIDDEN_LEDGER_ROOTS:
        if root in collapsed:
            root_found = True
    marker_found = False
    for marker in _PGP2_FORBIDDEN_DIGEST_MARKERS:
        if marker in collapsed:
            marker_found = True
    return root_found and marker_found


def _pgp2_detect_forbidden_bindings(value):
    value_type = type(value)
    if value is None or value_type is bool or value_type is int or value_type is str:
        return ()
    if value_type is float:
        if not isfinite(value):
            raise ValueError("non-finite float")
        return ()
    found = set()
    if value_type is list or value_type is tuple:
        for item in value:
            for name in _pgp2_detect_forbidden_bindings(item):
                found.add(name)
        return tuple(sorted(found))
    if value_type is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("binding keys must be exact str")
            if _pgp2_is_forbidden_digest_name(key):
                found.add(key.lower())
            for name in _pgp2_detect_forbidden_bindings(item):
                found.add(name)
        return tuple(sorted(found))
    raise TypeError("binding tree contains a custom object")


def _pgp2_detect_forbidden_ast(source):
    if type(source) is not str:
        raise TypeError("source must be exact str")
    tree = parse(source)
    found = set()
    for node in walk(tree):
        candidate = None
        if type(node) is Name:
            candidate = node.id
        elif type(node) is Attribute:
            candidate = node.attr
        elif type(node) is Constant and type(node.value) is str:
            candidate = node.value
        elif (
            type(node) is Subscript
            and type(node.slice) is Constant
            and type(node.slice.value) is str
        ):
            candidate = node.slice.value
        elif (
            type(node) is Call and type(node.func) is Name and node.func.id == "getattr"
        ):
            if (
                len(node.args) >= 2
                and type(node.args[1]) is Constant
                and type(node.args[1].value) is str
            ):
                candidate = node.args[1].value
        if candidate is not None and _pgp2_is_forbidden_digest_name(candidate):
            found.add(candidate.lower())
    return tuple(sorted(found))


def _pgp2_scan(roots):
    if type(roots) is not tuple:
        raise TypeError("roots must be wrapper-created exact tuple")
    concrete_path_type = type(Path())
    found = []
    for root in roots:
        if type(root) is str:
            root_path = Path(root)
        elif type(root) is concrete_path_type:
            root_path = root
        else:
            raise TypeError("root must be exact str or concrete Path")
        for path in root_path.rglob("*"):
            if type(path) is not concrete_path_type:
                raise TypeError("scanner yielded non-concrete Path")
            if not path.is_file():
                continue
            forbidden = path.name in FORBIDDEN_PRE_D1_BASENAMES
            for pattern in FORBIDDEN_PRE_D1_PATTERNS:
                if path.match(pattern):
                    forbidden = True
            if forbidden:
                found.append(str(path))
    return tuple(sorted(found))


def canonical_length_delimited_json(payload):
    if type(payload) is not dict:
        raise TypeError("payload must be exact dict")
    _pgp2_require_json_tree(payload)
    raw = dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return len(raw).to_bytes(8, byteorder="big") + raw


def derive_case_seed(root_seed, coordinate):
    if type(root_seed) is not bytes:
        raise TypeError("root_seed must be exact bytes")
    if len(root_seed) != 32:
        raise ValueError("root_seed must be 32 bytes")
    _pgp2_validate_coordinate(coordinate)
    payload = {
        "failure": coordinate.failure,
        "family": coordinate.family,
        "latin_order": coordinate.latin_order,
        "regime": coordinate.regime,
        "replicate": coordinate.replicate,
    }
    return new(root_seed, canonical_length_delimited_json(payload), "sha256").digest()


def derive_family_artifacts(spec):
    return _pgp2_family_artifacts(spec)


def generate_case(root_seed, coordinate):
    return _pgp2_generate_case(root_seed, coordinate)


def generate_cases(root_seed):
    return _pgp2_generate_cases(root_seed)


def normalized_semantic_bytes(channel, payload):
    if type(channel) is not str:
        raise TypeError("channel must be exact str")
    if channel not in SEMANTIC_CHANNELS:
        raise ValueError("unknown semantic channel")
    normalized = _pgp2_normalize_json(payload)
    return dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def reference_result(spec, version):
    return _pgp2_reference_result(spec, version)


def semantic_digest(channel, payload):
    return sha256(normalized_semantic_bytes(channel, payload)).hexdigest()


def semantic_uniqueness_violations(declarations):
    return _pgp2_semantic_uniqueness(declarations)


def validate_family_semantics(declaration):
    return _pgp2_validate_family_semantics(declaration)


def validate_fixture_lineage(declaration):
    return _pgp2_validate_fixture_lineage(declaration)


def detect_forbidden_digest_bindings(value):
    return _pgp2_detect_forbidden_bindings(value)


def detect_forbidden_digest_ast(source):
    return _pgp2_detect_forbidden_ast(source)


def scan_forbidden_pre_d1_artifacts(*roots):
    return _pgp2_scan(roots)
