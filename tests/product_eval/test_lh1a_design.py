"""Executable RED contract for the sealed LH-RECOVERY-1A D1-E packet.

These tests intentionally name the public design interfaces before any D1-E
implementation exists.  They exercise only an ephemeral in-memory generator;
they do not create a formal root, persistent corpus, assignments, provider data,
nonces, or a fixed baseline.
"""

from __future__ import annotations

import ast
import builtins
from collections import Counter
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import importlib
import inspect
import json
import math
from pathlib import Path
import re
import sys
from types import MappingProxyType, ModuleType, SimpleNamespace
from typing import Any
import unicodedata

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    ExternalSignal,
    NodeKind,
    ProviderToolProposal,
    RunStatus,
    TaskEventType,
    TaskStatus,
    WorkflowGraph,
)
from agent_os_core import DeterministicProvider, ReplanRejectedError
from apps.api_server.app import AgentOSApplication
from domain_packs.developer_agent import DeveloperWorkspaceAdapter


REPO_ROOT = Path(__file__).resolve().parents[2]
D1E_ROOT = REPO_ROOT / "product_evals/lh_recovery_1a"
MANIFEST_PATH = REPO_ROOT / "docs/research/LH-RECOVERY-1A-DESIGN-PRECOMMIT.yaml"
MANIFEST_RELATIVE_PATH = "docs/research/LH-RECOVERY-1A-DESIGN-PRECOMMIT.yaml"
SUCCESSOR_PATH = (
    REPO_ROOT / "docs/research/LH-RECOVERY-1A-RUNTIME-SHAPE-SUCCESSOR-v2.yaml"
)
MODULE_NAMES = ("generator", "regimes", "templates", "evaluator", "statistics")
RUNTIME_SOURCE_PATHS = (
    "packages/contracts/src/agent_os_contracts/workflow.py",
    "packages/os_core/src/agent_os_core/execution.py",
    "packages/os_core/src/agent_os_core/task_service.py",
    "packages/os_core/src/agent_os_core/capability.py",
)
REFERENCE_DUAL_EXECUTION_TESTS = (
    "test_ephemeral_generator_is_pure_deterministic_and_domain_separated",
    "test_generation_scanner_and_initializer_closures_are_fail_closed_and_stable",
    "test_six_families_have_distinct_typed_semantics_and_reference_oracles",
    "test_williams_orders_balance_positions_and_all_directed_adjacencies",
    "test_declaration_uniqueness_and_semantic_normalization_are_frozen",
    "test_forbidden_pre_d1_artifact_scan_is_recursive_across_arbitrary_roots",
)
FAMILIES = (
    "string_transform",
    "numeric_reducer",
    "validator",
    "formatter",
    "record_filter",
    "small_state_machine",
)
REGIMES = (
    "R0_DIRECT_REFRESH",
    "R1_DEPENDENCY_BEFORE_PROVIDER",
    "R2_RELEASE_BEFORE_APPLY",
)
FAILURES = (
    "PRE_CONSEQUENCE_PROCESS_EXIT",
    "POST_APPLY_WORKER_INTERRUPTED",
    "CORRECTION_HALT_BEFORE_APPLY",
)
WILLIAMS_ORDERS = {
    "W0": ("C", "F", "K", "R"),
    "W1": ("F", "R", "C", "K"),
    "W2": ("R", "K", "F", "C"),
    "W3": ("K", "C", "R", "F"),
}
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
EPHEMERAL_TEST_KEY = hashlib.sha256(
    b"LH1A-EPHEMERAL-TEST-KEY-NOT-A-FORMAL-ROOT"
).digest()
SECOND_EPHEMERAL_TEST_KEY = hashlib.sha256(
    b"LH1A-SECOND-EPHEMERAL-TEST-KEY-NOT-A-FORMAL-ROOT"
).digest()
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
SECONDARY_HYPOTHESIS_IDS = tuple(
    [*(f"family:{family}" for family in FAMILIES)]
    + [*(f"regime:{regime}" for regime in REGIMES)]
    + [*(f"failure:{failure}" for failure in FAILURES)]
)


def _module(name: str) -> Any:
    if name == "generator":
        return _load_pgp2_generator()
    return importlib.import_module(f"product_evals.lh_recovery_1a.{name}")


def _exact_binomial_upper_tail(successes: int, trials: int) -> float:
    return sum(math.comb(trials, k) for k in range(successes, trials + 1)) / (2**trials)


def _all_mapping_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in _all_mapping_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _all_mapping_keys(child)}
    return set()


def _canonical_length_delimited_json(payload: object) -> bytes:
    raw = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return len(raw).to_bytes(8, byteorder="big") + raw


class PGP2Violation(AssertionError):
    """Stable, machine-checkable D1E-PGP-2 rejection."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


PGP2_REASON_CODES = (
    "PGP2_M_PARSE",
    "PGP2_M_REFERENCE_PROVENANCE",
    "PGP2_M_AST_MISMATCH",
    "PGP2_M_TOPLEVEL_SEQUENCE",
    "PGP2_M_IMPORT_SET",
    "PGP2_M_SYMBOL_SET",
    "PGP2_M_PUBLIC_API",
    "PGP2_D_CLASS_SET",
    "PGP2_D_CLASS_SHAPE",
    "PGP2_D_FIELD_SCHEMA",
    "PGP2_D_CONST_SCHEMA",
    "PGP2_D_IR_SCHEMA",
    "PGP2_F_FUNCTION_SET",
    "PGP2_F_SIGNATURE",
    "PGP2_F_BODY_SCHEMA",
    "PGP2_F_CALL_SCHEMA",
    "PGP2_F_EFFECT_EDGE",
    "PGP2_F_VARARG",
    "PGP2_R_PARAM_EXACT_TYPE",
    "PGP2_R_EXTERNAL_IDENTITY",
    "PGP2_R_ENVIRONMENT_DRIFT",
    "PGP2_R_HARNESS_IDENTITY",
    "PGP2_R_DEFINITION_STATE",
    "PGP2_R_BOUND_OWNER",
    "PGP2_R_GLOBAL_STATE",
    "PGP2_R_NAMESPACE_DRIFT",
    "PGP2_R_SOURCE_IDENTITY",
)


# This literal certificate is intentionally declared before the canonical
# source, its AST, or any Product candidate is read.  It is the independently
# authored test-domain authority; nothing below derives it from generator.py.
REFERENCE_CERTIFICATE = {
    "harness_identity": ("cpython", 3, 12),
    "imports": (
        ("__future__", ("annotations",)),
        (
            "ast",
            ("Attribute", "Call", "Constant", "Name", "Subscript", "parse", "walk"),
        ),
        ("dataclasses", ("dataclass",)),
        ("hashlib", ("sha256",)),
        ("hmac", ("new",)),
        ("json", ("dumps",)),
        ("math", ("isfinite",)),
        ("pathlib", ("Path",)),
        ("types", ("MappingProxyType",)),
        ("unicodedata", ("normalize",)),
    ),
    "classes": (
        (
            "PopulationDesign",
            (
                ("families", "tuple[str, ...]"),
                ("regimes", "tuple[str, ...]"),
                ("failures", "tuple[str, ...]"),
                ("latin_orders", "tuple[str, ...]"),
                ("replicates", "tuple[int, ...]"),
                ("instances_per_family_regime_failure_order_cell", "int"),
                ("instances_per_family_regime_failure_cell", "int"),
                ("instance_count", "int"),
                ("arms_per_instance", "int"),
                ("episode_count", "int"),
                ("instances_per_family", "int"),
                ("instances_per_regime", "int"),
                ("instances_per_failure", "int"),
                ("instances_per_latin_order", "int"),
                ("instances_per_replicate", "int"),
            ),
        ),
        (
            "CaseCoordinate",
            (
                ("family", "str"),
                ("regime", "str"),
                ("failure", "str"),
                ("latin_order", "str"),
                ("replicate", "int"),
            ),
        ),
        (
            "GeneratedCase",
            (
                ("coordinate", "CaseCoordinate"),
                ("case_id", "str"),
                ("case_seed", "bytes"),
                ("declaration", "SemanticFixtureDeclaration"),
            ),
        ),
        (
            "StringTransformSpec",
            (("text_v1", "str"), ("text_v2", "str"), ("operation", "str")),
        ),
        (
            "NumericReducerSpec",
            (
                ("values_v1", "tuple[int, ...]"),
                ("values_v2", "tuple[int, ...]"),
                ("operation", "str"),
            ),
        ),
        (
            "ValidatorSpec",
            (("value_v1", "str"), ("value_v2", "str"), ("rule", "str")),
        ),
        (
            "FormatterSpec",
            (
                ("template", "str"),
                ("values_v1", "tuple[tuple[str, object], ...]"),
                ("values_v2", "tuple[tuple[str, object], ...]"),
            ),
        ),
        (
            "RecordFilterSpec",
            (
                ("records_v1", "tuple[tuple[tuple[str, object], ...], ...]"),
                ("records_v2", "tuple[tuple[tuple[str, object], ...], ...]"),
                ("field", "str"),
                ("equals", "object"),
            ),
        ),
        (
            "SmallStateMachineSpec",
            (
                ("initial_state", "str"),
                ("events_v1", "tuple[str, ...]"),
                ("events_v2", "tuple[str, ...]"),
                ("transitions", "tuple[tuple[str, str, str], ...]"),
            ),
        ),
        (
            "FamilyArtifacts",
            (
                ("fixture", "object"),
                ("requirement_v1", "object"),
                ("requirement_v2", "object"),
                ("initial_content", "object"),
                ("final_content", "object"),
                ("test", "object"),
                ("prompt", "object"),
                ("expected_result", "object"),
                ("provider_response", "object"),
            ),
        ),
        (
            "SemanticFixtureDeclaration",
            (
                ("case_id", "str"),
                ("family", "str"),
                ("family_spec", "object"),
                ("fixture_id", "str"),
                ("fixture_prefix", "str"),
                ("fixture_version_v1", "int"),
                ("fixture_version_v2", "int"),
                ("fixture", "object"),
                ("requirement_v1", "object"),
                ("requirement_v2", "object"),
                ("initial_content", "object"),
                ("final_content", "object"),
                ("test", "object"),
                ("prompt", "object"),
                ("expected_result", "object"),
                ("provider_response", "object"),
            ),
        ),
    ),
    "constants": (
        ("TASK_FAMILIES", "tuple"),
        ("REGIME_NAMES", "tuple"),
        ("FAILURE_NAMES", "tuple"),
        ("LATIN_ORDER_NAMES", "tuple"),
        ("SEMANTIC_CHANNELS", "tuple"),
        ("SEMANTIC_NORMALIZATION_STEPS", "tuple"),
        ("NO_RESCUE_RULES", "tuple"),
        ("FORBIDDEN_PRE_D1_BASENAMES", "tuple"),
        ("FORBIDDEN_PRE_D1_PATTERNS", "tuple"),
        ("_PGP2_FORBIDDEN_LEDGER_ROOTS", "tuple"),
        ("_PGP2_FORBIDDEN_DIGEST_MARKERS", "tuple"),
        ("WILLIAMS_ORDERS", "mapping_proxy"),
        ("SEMANTIC_NORMALIZATION_RULES", "mapping_proxy"),
        ("FAMILY_IR", "tuple_ir"),
        ("FAMILY_SPEC_TYPES", "class_mapping_proxy"),
        ("POPULATION_DESIGN", "record"),
    ),
    "private_effects": (
        ("_pgp2_require_json_tree", "GEN"),
        ("_pgp2_normalize_text", "GEN"),
        ("_pgp2_normalize_json", "GEN"),
        ("_pgp2_validate_coordinate", "GEN"),
        ("_pgp2_validate_family_spec", "GEN"),
        ("_pgp2_reference_result", "GEN"),
        ("_pgp2_family_artifacts", "GEN"),
        ("_pgp2_channel_value", "GEN"),
        ("_pgp2_make_family_spec", "GEN"),
        ("_pgp2_generate_case", "GEN"),
        ("_pgp2_generate_cases", "GEN"),
        ("_pgp2_semantic_uniqueness", "GEN"),
        ("_pgp2_validate_family_semantics", "GEN"),
        ("_pgp2_validate_fixture_lineage", "GEN"),
        ("_pgp2_is_forbidden_digest_name", "ANALYZE"),
        ("_pgp2_detect_forbidden_bindings", "ANALYZE"),
        ("_pgp2_detect_forbidden_ast", "ANALYZE"),
        ("_pgp2_scan", "SCAN"),
    ),
    "public_signatures": (
        ("canonical_length_delimited_json", ("payload",), None, None),
        ("derive_case_seed", ("root_seed", "coordinate"), None, None),
        ("derive_family_artifacts", ("spec",), None, None),
        ("generate_case", ("root_seed", "coordinate"), None, None),
        ("generate_cases", ("root_seed",), None, None),
        ("normalized_semantic_bytes", ("channel", "payload"), None, None),
        ("reference_result", ("spec", "version"), None, None),
        ("semantic_digest", ("channel", "payload"), None, None),
        ("semantic_uniqueness_violations", ("declarations",), None, None),
        ("validate_family_semantics", ("declaration",), None, None),
        ("validate_fixture_lineage", ("declaration",), None, None),
        ("detect_forbidden_digest_bindings", ("value",), None, None),
        ("detect_forbidden_digest_ast", ("source",), None, None),
        ("scan_forbidden_pre_d1_artifacts", (), "roots", None),
    ),
    "minimal_builtins": (
        "NotImplemented",
        "TypeError",
        "ValueError",
        "__build_class__",
        "all",
        "any",
        "bool",
        "bytes",
        "dict",
        "enumerate",
        "float",
        "frozenset",
        "getattr",
        "hash",
        "int",
        "isinstance",
        "len",
        "list",
        "object",
        "range",
        "repr",
        "set",
        "sorted",
        "str",
        "sum",
        "super",
        "tuple",
        "type",
        "zip",
    ),
    "ambient_builtin_keys": (
        "ArithmeticError",
        "AssertionError",
        "AttributeError",
        "BaseException",
        "BaseExceptionGroup",
        "BlockingIOError",
        "BrokenPipeError",
        "BufferError",
        "BytesWarning",
        "ChildProcessError",
        "ConnectionAbortedError",
        "ConnectionError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "DeprecationWarning",
        "EOFError",
        "Ellipsis",
        "EncodingWarning",
        "EnvironmentError",
        "Exception",
        "ExceptionGroup",
        "False",
        "FileExistsError",
        "FileNotFoundError",
        "FloatingPointError",
        "FutureWarning",
        "GeneratorExit",
        "IOError",
        "ImportError",
        "ImportWarning",
        "IndentationError",
        "IndexError",
        "InterruptedError",
        "IsADirectoryError",
        "KeyError",
        "KeyboardInterrupt",
        "LookupError",
        "MemoryError",
        "ModuleNotFoundError",
        "NameError",
        "None",
        "NotADirectoryError",
        "NotImplemented",
        "NotImplementedError",
        "OSError",
        "OverflowError",
        "PendingDeprecationWarning",
        "PermissionError",
        "ProcessLookupError",
        "RecursionError",
        "ReferenceError",
        "ResourceWarning",
        "RuntimeError",
        "RuntimeWarning",
        "StopAsyncIteration",
        "StopIteration",
        "SyntaxError",
        "SyntaxWarning",
        "SystemError",
        "SystemExit",
        "TabError",
        "TimeoutError",
        "True",
        "TypeError",
        "UnboundLocalError",
        "UnicodeDecodeError",
        "UnicodeEncodeError",
        "UnicodeError",
        "UnicodeTranslateError",
        "UnicodeWarning",
        "UserWarning",
        "ValueError",
        "Warning",
        "ZeroDivisionError",
        "__build_class__",
        "__debug__",
        "__doc__",
        "__import__",
        "__loader__",
        "__name__",
        "__package__",
        "__spec__",
        "abs",
        "aiter",
        "all",
        "anext",
        "any",
        "ascii",
        "bin",
        "bool",
        "breakpoint",
        "bytearray",
        "bytes",
        "callable",
        "chr",
        "classmethod",
        "compile",
        "complex",
        "copyright",
        "credits",
        "delattr",
        "dict",
        "dir",
        "divmod",
        "enumerate",
        "eval",
        "exec",
        "exit",
        "filter",
        "float",
        "format",
        "frozenset",
        "getattr",
        "globals",
        "hasattr",
        "hash",
        "help",
        "hex",
        "id",
        "input",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "license",
        "list",
        "locals",
        "map",
        "max",
        "memoryview",
        "min",
        "next",
        "object",
        "oct",
        "open",
        "ord",
        "pow",
        "print",
        "property",
        "quit",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "setattr",
        "slice",
        "sorted",
        "staticmethod",
        "str",
        "sum",
        "super",
        "tuple",
        "type",
        "vars",
        "zip",
    ),
    "python_external_callables": (
        ("ast.parse", ()),
        ("ast.walk", ("iter_child_nodes",)),
        ("dataclasses.dataclass", ("_process_class",)),
        ("hmac.new", ("HMAC",)),
        ("json.dumps", ("_default_encoder", "JSONEncoder")),
    ),
    "direct_external_calls": (
        "ast.parse",
        "ast.walk",
        "dataclasses.dataclass",
        "hashlib.sha256",
        "hmac.new",
        "json.dumps",
        "math.isfinite",
        "pathlib.Path",
        "types.MappingProxyType",
        "unicodedata.normalize",
    ),
    "forbidden_names": (
        "ROOT_SEED",
        "CORPUS",
        "ASSIGNMENTS",
        "PROVIDER_BANK",
        "NONCES",
        "ENVIRONMENT_NONCE",
        "REVIEWER_NONCE",
        "FUTURE_ANSWERS",
        "RUNNER_EVENT_FIELDS",
        "MUTABLE_LEDGER_SHA256",
        "PERMISSION_REQUEST_ID",
        "PERMISSION_APPROVAL_ID",
        "PRODUCT_TARGET_HEAD",
        "RUNNER_TARGET_HEAD",
        "SPINE_RESULT_SHA256",
        "fixed_baseline.py",
        "fixed_dag.json",
        "d1_f.json",
        "D1-F",
        "D2",
    ),
    "runtime_namespace_keys": (
        "Attribute",
        "Call",
        "CaseCoordinate",
        "Constant",
        "FAILURE_NAMES",
        "FAMILY_IR",
        "FAMILY_SPEC_TYPES",
        "FORBIDDEN_PRE_D1_BASENAMES",
        "FORBIDDEN_PRE_D1_PATTERNS",
        "FamilyArtifacts",
        "FormatterSpec",
        "GeneratedCase",
        "LATIN_ORDER_NAMES",
        "MappingProxyType",
        "NO_RESCUE_RULES",
        "Name",
        "NumericReducerSpec",
        "POPULATION_DESIGN",
        "Path",
        "PopulationDesign",
        "REGIME_NAMES",
        "RecordFilterSpec",
        "SEMANTIC_CHANNELS",
        "SEMANTIC_NORMALIZATION_RULES",
        "SEMANTIC_NORMALIZATION_STEPS",
        "SemanticFixtureDeclaration",
        "SmallStateMachineSpec",
        "StringTransformSpec",
        "Subscript",
        "TASK_FAMILIES",
        "ValidatorSpec",
        "WILLIAMS_ORDERS",
        "_PGP2_FORBIDDEN_DIGEST_MARKERS",
        "_PGP2_FORBIDDEN_LEDGER_ROOTS",
        "__builtins__",
        "__doc__",
        "__file__",
        "__loader__",
        "__name__",
        "__package__",
        "__spec__",
        "_pgp2_detect_forbidden_ast",
        "_pgp2_detect_forbidden_bindings",
        "_pgp2_family_artifacts",
        "_pgp2_channel_value",
        "_pgp2_generate_case",
        "_pgp2_generate_cases",
        "_pgp2_is_forbidden_digest_name",
        "_pgp2_make_family_spec",
        "_pgp2_normalize_json",
        "_pgp2_normalize_text",
        "_pgp2_reference_result",
        "_pgp2_require_json_tree",
        "_pgp2_scan",
        "_pgp2_semantic_uniqueness",
        "_pgp2_validate_coordinate",
        "_pgp2_validate_family_semantics",
        "_pgp2_validate_family_spec",
        "_pgp2_validate_fixture_lineage",
        "annotations",
        "canonical_length_delimited_json",
        "dataclass",
        "derive_case_seed",
        "derive_family_artifacts",
        "detect_forbidden_digest_ast",
        "detect_forbidden_digest_bindings",
        "dumps",
        "generate_case",
        "generate_cases",
        "isfinite",
        "new",
        "normalize",
        "normalized_semantic_bytes",
        "parse",
        "reference_result",
        "scan_forbidden_pre_d1_artifacts",
        "semantic_digest",
        "semantic_uniqueness_violations",
        "sha256",
        "validate_family_semantics",
        "validate_fixture_lineage",
        "walk",
    ),
}


def _pgp2_callable_state(value: object) -> tuple[object, ...]:
    if not inspect.isfunction(value):
        return ("identity", value)
    closure = tuple(cell.cell_contents for cell in (value.__closure__ or ()))
    kwdefaults = tuple(sorted((value.__kwdefaults__ or {}).items()))
    dictionary = tuple(sorted(value.__dict__.items()))
    return (
        "python_function",
        value.__code__,
        value.__defaults__,
        kwdefaults,
        closure,
        value.__builtins__,
        dictionary,
    )


def _build_pgp2_trust_capsule() -> SimpleNamespace:
    ambient_builtins = dict(vars(builtins))
    if tuple(sorted(ambient_builtins)) != REFERENCE_CERTIFICATE["ambient_builtin_keys"]:
        raise PGP2Violation("PGP2_R_HARNESS_IDENTITY")

    import_facades: dict[str, SimpleNamespace] = {}
    external_objects: dict[str, object] = {}
    for module_name, member_names in REFERENCE_CERTIFICATE["imports"]:
        ambient_module = importlib.import_module(module_name)
        facade_members: dict[str, object] = {}
        for member_name in member_names:
            member = getattr(ambient_module, member_name)
            facade_members[member_name] = member
            external_objects[f"{module_name}.{member_name}"] = member
        import_facades[module_name] = SimpleNamespace(**facade_members)

    def import_router(
        name: str,
        globals: object = None,
        locals: object = None,
        fromlist: object = (),
        level: int = 0,
    ) -> object:
        del globals, locals
        if type(name) is not str or type(level) is not int or level != 0:
            raise ImportError("PGP2 import router rejects dynamic or relative import")
        if name not in import_facades:
            raise ImportError("PGP2 import router rejects undeclared module")
        if type(fromlist) is not tuple:
            raise ImportError("PGP2 import router requires exact fromlist tuple")
        declared = dict(REFERENCE_CERTIFICATE["imports"])[name]
        if tuple(fromlist) != declared:
            raise ImportError("PGP2 import router rejects undeclared member")
        return import_facades[name]

    minimal_builtins = {
        name: ambient_builtins[name]
        for name in REFERENCE_CERTIFICATE["minimal_builtins"]
    }
    minimal_builtins["__import__"] = import_router
    expected_minimal_builtins = dict(minimal_builtins)

    python_callable_states: dict[str, tuple[object, ...]] = {}
    owner_helpers: dict[tuple[str, str], object] = {}
    for qualified_name, helper_names in REFERENCE_CERTIFICATE[
        "python_external_callables"
    ]:
        callable_object = external_objects[qualified_name]
        python_callable_states[qualified_name] = _pgp2_callable_state(callable_object)
        if inspect.isfunction(callable_object):
            for helper_name in helper_names:
                owner_helpers[(qualified_name, helper_name)] = (
                    callable_object.__globals__[helper_name]
                )

    return SimpleNamespace(
        ambient_builtins=ambient_builtins,
        external_objects=external_objects,
        expected_minimal_builtins=expected_minimal_builtins,
        import_facades=import_facades,
        import_router=import_router,
        minimal_builtins=minimal_builtins,
        owner_helpers=owner_helpers,
        python_callable_states=python_callable_states,
    )


def _attest_pgp2_environment(capsule: SimpleNamespace) -> None:
    runtime_identity = (
        sys.implementation.name,
        sys.version_info.major,
        sys.version_info.minor,
    )
    if runtime_identity != REFERENCE_CERTIFICATE["harness_identity"]:
        raise PGP2Violation("PGP2_R_HARNESS_IDENTITY")
    ambient_now = vars(builtins)
    if tuple(sorted(ambient_now)) != REFERENCE_CERTIFICATE["ambient_builtin_keys"]:
        raise PGP2Violation("PGP2_R_ENVIRONMENT_DRIFT")
    for name, expected in capsule.ambient_builtins.items():
        if ambient_now.get(name) is not expected:
            raise PGP2Violation("PGP2_R_ENVIRONMENT_DRIFT")
    if set(capsule.minimal_builtins) != set(capsule.expected_minimal_builtins):
        raise PGP2Violation("PGP2_R_ENVIRONMENT_DRIFT")
    for name, expected in capsule.expected_minimal_builtins.items():
        if capsule.minimal_builtins.get(name) is not expected:
            raise PGP2Violation("PGP2_R_ENVIRONMENT_DRIFT")
    try:
        _pgp2_trusted_future_feature_snapshot(
            capsule.external_objects["__future__.annotations"]
        )
    except AssertionError:
        raise PGP2Violation("PGP2_R_ENVIRONMENT_DRIFT") from None
    if (
        capsule.import_facades["__future__"].annotations
        is not _PGP2_TRUSTED_FUTURE_ANNOTATIONS
    ):
        raise PGP2Violation("PGP2_R_ENVIRONMENT_DRIFT")
    for module_name, member_names in REFERENCE_CERTIFICATE["imports"]:
        facade = capsule.import_facades[module_name]
        if set(vars(facade)) != set(member_names):
            raise PGP2Violation("PGP2_R_ENVIRONMENT_DRIFT")
        for member_name in member_names:
            qualified_name = f"{module_name}.{member_name}"
            if (
                getattr(facade, member_name)
                is not capsule.external_objects[qualified_name]
            ):
                raise PGP2Violation("PGP2_R_ENVIRONMENT_DRIFT")
    for qualified_name, expected_state in capsule.python_callable_states.items():
        if _pgp2_callable_state(capsule.external_objects[qualified_name]) != (
            expected_state
        ):
            raise PGP2Violation("PGP2_R_ENVIRONMENT_DRIFT")
    for (qualified_name, helper_name), expected in capsule.owner_helpers.items():
        callable_object = capsule.external_objects[qualified_name]
        if callable_object.__globals__.get(helper_name) is not expected:
            raise PGP2Violation("PGP2_R_ENVIRONMENT_DRIFT")


# Constructed before REFERENCE_SOURCE exists or is parsed.  It captures only the
# finite declared host surface and never traverses modules or sys.modules.
_PGP2_TRUST_CAPSULE = _build_pgp2_trust_capsule()
_PGP2_TRUSTED_FUTURE_ANNOTATIONS = _PGP2_TRUST_CAPSULE.external_objects[
    "__future__.annotations"
]
_PGP2_TRUSTED_FUTURE_FEATURE_TYPE = type(_PGP2_TRUSTED_FUTURE_ANNOTATIONS)
_PGP2_TRUSTED_FUTURE_FEATURE_TYPE_MODULE = "__future__"
_PGP2_TRUSTED_FUTURE_FEATURE_TYPE_NAME = "_Feature"
_PGP2_TRUSTED_FUTURE_FEATURE_TYPE_QUALNAME = "_Feature"
_PGP2_TRUSTED_FUTURE_FEATURE_KEYS = (
    "optional",
    "mandatory",
    "compiler_flag",
)
_PGP2_TRUSTED_FUTURE_FEATURE_OPTIONAL = (3, 7, 0, "beta", 1)
_PGP2_TRUSTED_FUTURE_FEATURE_COMPILER_FLAG = 16777216
_PGP2_TRUSTED_FUTURE_FEATURE_SNAPSHOT = (
    "trusted_future_feature",
    (
        (
            "optional",
            (
                "tuple",
                (
                    ("int", 3),
                    ("int", 7),
                    ("int", 0),
                    ("str", "beta"),
                    ("int", 1),
                ),
            ),
        ),
        ("mandatory", ("NoneType", None)),
        ("compiler_flag", ("int", 16777216)),
    ),
)


def _pgp2_trusted_future_feature_snapshot(value: object) -> tuple[object, ...]:
    value_type = type(value)
    assert value_type is _PGP2_TRUSTED_FUTURE_FEATURE_TYPE, (
        "trusted future feature type identity drift"
    )
    type_module = value_type.__module__
    type_name = value_type.__name__
    type_qualname = value_type.__qualname__
    assert type(type_module) is str and (
        type_module == _PGP2_TRUSTED_FUTURE_FEATURE_TYPE_MODULE
    ), "trusted future feature type module drift"
    assert type(type_name) is str and (
        type_name == _PGP2_TRUSTED_FUTURE_FEATURE_TYPE_NAME
    ), "trusted future feature type name drift"
    assert type(type_qualname) is str and (
        type_qualname == _PGP2_TRUSTED_FUTURE_FEATURE_TYPE_QUALNAME
    ), "trusted future feature type qualname drift"
    assert value is _PGP2_TRUSTED_FUTURE_ANNOTATIONS, (
        "trusted future feature object identity drift"
    )
    state = vars(value)
    assert type(state) is dict, "trusted future feature state must be exact dict"
    assert len(state) == 3 and all(
        key in state for key in _PGP2_TRUSTED_FUTURE_FEATURE_KEYS
    ), "trusted future feature keys drift"
    assert all(type(key) is str for key in state), (
        "trusted future feature keys must be exact str"
    )
    optional = state["optional"]
    mandatory = state["mandatory"]
    compiler_flag = state["compiler_flag"]
    assert type(optional) is tuple and len(optional) == 5, (
        "trusted future optional must be exact five-tuple"
    )
    assert type(optional[0]) is int and optional[0] == 3
    assert type(optional[1]) is int and optional[1] == 7
    assert type(optional[2]) is int and optional[2] == 0
    assert type(optional[3]) is str and optional[3] == "beta"
    assert type(optional[4]) is int and optional[4] == 1
    assert optional == _PGP2_TRUSTED_FUTURE_FEATURE_OPTIONAL
    assert mandatory is None
    assert type(compiler_flag) is int and (
        compiler_flag == _PGP2_TRUSTED_FUTURE_FEATURE_COMPILER_FLAG
    )
    return (
        "trusted_future_feature",
        (
            (
                "optional",
                (
                    "tuple",
                    (
                        ("int", optional[0]),
                        ("int", optional[1]),
                        ("int", optional[2]),
                        ("str", optional[3]),
                        ("int", optional[4]),
                    ),
                ),
            ),
            ("mandatory", ("NoneType", mandatory)),
            ("compiler_flag", ("int", compiler_flag)),
        ),
    )


REFERENCE_SOURCE = '''"""Canonical D1E-PGP-2 deterministic generator."""

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
    normalized = normalized.replace("\\r\\n", "\\n").replace("\\r", "\\n")
    lines = []
    for line in normalized.split("\\n"):
        lines.append(line.rstrip(" \\t"))
    return "\\n".join(lines)


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
        return StringTransformSpec(case_id + ":agent os", case_id + ":agent core", "upper")
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
                        coordinate = CaseCoordinate(family, regime, failure, latin_order, replicate)
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
    if type(declaration.fixture_version_v1) is not int or type(declaration.fixture_version_v2) is not int:
        raise TypeError("fixture versions must be exact ints")
    if declaration.fixture_version_v2 <= declaration.fixture_version_v1:
        violations.append("FIXTURE_VERSION_NOT_INCREMENTED")
    if type(declaration.fixture_id) is not str or type(declaration.fixture_prefix) is not str:
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
        elif type(node) is Subscript and type(node.slice) is Constant and type(node.slice.value) is str:
            candidate = node.slice.value
        elif type(node) is Call and type(node.func) is Name and node.func.id == "getattr":
            if len(node.args) >= 2 and type(node.args[1]) is Constant and type(node.args[1].value) is str:
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
    raw = dumps(payload, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
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
    return dumps(normalized, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


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
'''


def _pgp2_parse(source: str) -> ast.Module:
    if type(source) is not str:
        raise PGP2Violation("PGP2_R_PARAM_EXACT_TYPE")
    try:
        return ast.parse(source, type_comments=False)
    except (SyntaxError, ValueError, TypeError) as error:
        raise PGP2Violation("PGP2_M_PARSE") from error


def _pgp2_ast_shape(tree: ast.AST) -> str:
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def _pgp2_import_declarations(
    tree: ast.Module,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    declarations: list[tuple[str, tuple[str, ...]]] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            raise PGP2Violation("PGP2_M_IMPORT_SET")
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level != 0 or node.module is None:
            raise PGP2Violation("PGP2_M_IMPORT_SET")
        names: list[str] = []
        for alias in node.names:
            if alias.asname is not None or alias.name == "*":
                raise PGP2Violation("PGP2_M_IMPORT_SET")
            names.append(alias.name)
        declarations.append((node.module, tuple(names)))
    return tuple(declarations)


def _pgp2_function_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[tuple[str, ...], str | None, str | None]:
    if node.args.posonlyargs or node.args.kwonlyargs:
        raise PGP2Violation("PGP2_F_SIGNATURE")
    if node.args.defaults or any(item is not None for item in node.args.kw_defaults):
        raise PGP2Violation("PGP2_F_SIGNATURE")
    return (
        tuple(argument.arg for argument in node.args.args),
        node.args.vararg.arg if node.args.vararg is not None else None,
        node.args.kwarg.arg if node.args.kwarg is not None else None,
    )


def _pgp2_top_level_assignments(tree: ast.Module) -> tuple[str, ...]:
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise PGP2Violation("PGP2_D_CONST_SCHEMA")
            names.append(node.targets[0].id)
        elif isinstance(node, ast.AnnAssign):
            raise PGP2Violation("PGP2_D_CONST_SCHEMA")
    return tuple(names)


def _pgp2_class_schema(node: ast.ClassDef) -> tuple[tuple[str, str], ...]:
    if node.bases or node.keywords:
        raise PGP2Violation("PGP2_D_CLASS_SHAPE")
    if len(node.decorator_list) != 1:
        raise PGP2Violation("PGP2_D_CLASS_SHAPE")
    decorator = node.decorator_list[0]
    if not isinstance(decorator, ast.Call):
        raise PGP2Violation("PGP2_D_CLASS_SHAPE")
    if not isinstance(decorator.func, ast.Name) or decorator.func.id != "dataclass":
        raise PGP2Violation("PGP2_D_CLASS_SHAPE")
    if decorator.args:
        raise PGP2Violation("PGP2_D_CLASS_SHAPE")
    keywords = {
        keyword.arg: keyword.value
        for keyword in decorator.keywords
        if keyword.arg is not None
    }
    if set(keywords) != {"frozen", "slots"}:
        raise PGP2Violation("PGP2_D_CLASS_SHAPE")
    if not all(
        isinstance(value, ast.Constant) and value.value is True
        for value in keywords.values()
    ):
        raise PGP2Violation("PGP2_D_CLASS_SHAPE")
    fields_found: list[tuple[str, str]] = []
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign):
            raise PGP2Violation("PGP2_D_CLASS_SHAPE")
        if not isinstance(statement.target, ast.Name) or statement.value is not None:
            raise PGP2Violation("PGP2_D_CLASS_SHAPE")
        fields_found.append((statement.target.id, ast.unparse(statement.annotation)))
    return tuple(fields_found)


def _pgp2_local_function_domains(tree: ast.Module) -> dict[str, str]:
    domains = dict(REFERENCE_CERTIFICATE["private_effects"])
    for name, _, _, _ in REFERENCE_CERTIFICATE["public_signatures"]:
        if name in {"detect_forbidden_digest_bindings", "detect_forbidden_digest_ast"}:
            domains[name] = "ANALYZE"
        elif name == "scan_forbidden_pre_d1_artifacts":
            domains[name] = "SCAN"
        else:
            domains[name] = "GEN"
    return domains


def _pgp2_static_call_form(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts = [node.attr]
        current = node.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            return ".".join(reversed(parts))
        if isinstance(current, ast.Call):
            return "<result>." + ".".join(reversed(parts))
        if isinstance(current, ast.Constant):
            return "<literal>." + ".".join(reversed(parts))
    return "<dynamic>"


def _pgp2_assert_call_and_effect_schema(tree: ast.Module) -> None:
    domains = _pgp2_local_function_domains(tree)
    imported_locals: dict[str, str] = {}
    for module_name, names in REFERENCE_CERTIFICATE["imports"]:
        for name in names:
            imported_locals[name] = f"{module_name}.{name}"
    observed_external: set[str] = set()
    allowed_direct_names = (
        set(domains)
        | {name for name, _ in REFERENCE_CERTIFICATE["classes"]}
        | set(imported_locals)
        | {
            "TypeError",
            "ValueError",
            "dict",
            "len",
            "repr",
            "set",
            "sorted",
            "str",
            "sum",
            "tuple",
            "type",
        }
    )
    forbidden_body_nodes = (
        ast.AsyncFor,
        ast.AsyncFunctionDef,
        ast.AsyncWith,
        ast.Await,
        ast.DictComp,
        ast.GeneratorExp,
        ast.Lambda,
        ast.ListComp,
        ast.Match,
        ast.NamedExpr,
        ast.SetComp,
        ast.Yield,
        ast.YieldFrom,
    )
    if any(isinstance(node, forbidden_body_nodes) for node in ast.walk(tree)):
        raise PGP2Violation("PGP2_F_BODY_SCHEMA")
    for definition in (node for node in tree.body if isinstance(node, ast.FunctionDef)):
        signature = _pgp2_function_signature(definition)
        if definition.name == "scan_forbidden_pre_d1_artifacts":
            if signature != ((), "roots", None):
                raise PGP2Violation("PGP2_F_VARARG")
        elif signature[1] is not None or signature[2] is not None:
            raise PGP2Violation("PGP2_F_VARARG")
        parameters = set(signature[0])
        if definition.args.vararg is not None:
            parameters.add(definition.args.vararg.arg)
        for node in ast.walk(definition):
            if (
                isinstance(node, (ast.FunctionDef, ast.ClassDef))
                and node is not definition
            ):
                raise PGP2Violation("PGP2_F_BODY_SCHEMA")
            if not isinstance(node, ast.Call):
                continue
            if any(keyword.arg is None for keyword in node.keywords):
                raise PGP2Violation("PGP2_F_CALL_SCHEMA")
            if any(isinstance(argument, ast.Starred) for argument in node.args):
                raise PGP2Violation("PGP2_F_CALL_SCHEMA")
            if not isinstance(node.func, (ast.Name, ast.Attribute)):
                raise PGP2Violation("PGP2_F_CALL_SCHEMA")
            form = _pgp2_static_call_form(node.func)
            if form == "<dynamic>":
                raise PGP2Violation("PGP2_F_CALL_SCHEMA")
            if isinstance(node.func, ast.Name):
                if node.func.id in parameters:
                    raise PGP2Violation("PGP2_F_CALL_SCHEMA")
                if node.func.id not in allowed_direct_names:
                    raise PGP2Violation("PGP2_F_CALL_SCHEMA")
                if node.func.id in {"eval", "exec", "getattr", "map", "filter"}:
                    raise PGP2Violation("PGP2_F_CALL_SCHEMA")
                if node.func.id == "type" and len(node.args) != 1:
                    raise PGP2Violation("PGP2_F_CALL_SCHEMA")
                if node.func.id == "sorted" and any(
                    keyword.arg == "key" for keyword in node.keywords
                ):
                    raise PGP2Violation("PGP2_F_CALL_SCHEMA")
                if any(
                    keyword.arg
                    in {
                        "default",
                        "default_factory",
                        "key",
                        "object_hook",
                        "object_pairs_hook",
                        "parse_constant",
                        "parse_float",
                        "parse_int",
                        "repl",
                    }
                    for keyword in node.keywords
                ):
                    raise PGP2Violation("PGP2_F_CALL_SCHEMA")
                if node.func.id in imported_locals:
                    observed_external.add(imported_locals[node.func.id])
                if node.func.id in domains:
                    source_domain = domains[definition.name]
                    target_domain = domains[node.func.id]
                    if (source_domain, target_domain) in {
                        ("GEN", "ANALYZE"),
                        ("GEN", "SCAN"),
                        ("ANALYZE", "GEN"),
                        ("SCAN", "GEN"),
                    }:
                        raise PGP2Violation("PGP2_F_EFFECT_EDGE")
            if isinstance(node.func, ast.Attribute) and node.func.attr in {
                "chmod",
                "mkdir",
                "rename",
                "replace",
                "rmdir",
                "symlink_to",
                "touch",
                "unlink",
                "write_bytes",
                "write_text",
            }:
                if domains[definition.name] == "SCAN":
                    raise PGP2Violation("PGP2_F_CALL_SCHEMA")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id in imported_locals:
            observed_external.add(imported_locals[node.func.id])
    if tuple(sorted(observed_external)) != tuple(
        sorted(REFERENCE_CERTIFICATE["direct_external_calls"])
    ):
        raise PGP2Violation("PGP2_F_CALL_SCHEMA")


def _pgp2_assert_reference_certificate(tree: ast.Module) -> None:
    if not tree.body:
        raise PGP2Violation("PGP2_M_REFERENCE_PROVENANCE")
    first = tree.body[0]
    if not (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and first.value.value == "Canonical D1E-PGP-2 deterministic generator."
    ):
        raise PGP2Violation("PGP2_M_TOPLEVEL_SEQUENCE")
    if _pgp2_import_declarations(tree) != REFERENCE_CERTIFICATE["imports"]:
        raise PGP2Violation("PGP2_M_IMPORT_SET")

    class_nodes = tuple(node for node in tree.body if isinstance(node, ast.ClassDef))
    expected_classes = REFERENCE_CERTIFICATE["classes"]
    if tuple(node.name for node in class_nodes) != tuple(
        name for name, _ in expected_classes
    ):
        raise PGP2Violation("PGP2_D_CLASS_SET")
    for node, (_, expected_fields) in zip(class_nodes, expected_classes):
        if _pgp2_class_schema(node) != expected_fields:
            raise PGP2Violation("PGP2_D_FIELD_SCHEMA")

    constant_names = _pgp2_top_level_assignments(tree)
    expected_constant_names = tuple(
        name for name, _ in REFERENCE_CERTIFICATE["constants"]
    )
    if constant_names != expected_constant_names:
        raise PGP2Violation("PGP2_D_CONST_SCHEMA")
    family_ir_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "FAMILY_IR"
    )
    family_ir = ast.literal_eval(family_ir_node.value)
    if tuple(item[0] for item in family_ir) != FAMILIES or len(family_ir) != 6:
        raise PGP2Violation("PGP2_D_IR_SCHEMA")
    if any(
        not isinstance(item, tuple)
        or len(item) != 2
        or any(type(value) is not str for value in item)
        for item in family_ir
    ):
        raise PGP2Violation("PGP2_D_IR_SCHEMA")

    function_nodes = tuple(
        node for node in tree.body if isinstance(node, ast.FunctionDef)
    )
    expected_private = tuple(
        name for name, _ in REFERENCE_CERTIFICATE["private_effects"]
    )
    expected_public = tuple(
        name for name, _, _, _ in REFERENCE_CERTIFICATE["public_signatures"]
    )
    if (
        tuple(node.name for node in function_nodes)
        != expected_private + expected_public
    ):
        raise PGP2Violation("PGP2_F_FUNCTION_SET")
    if any(node.decorator_list for node in function_nodes):
        raise PGP2Violation("PGP2_F_BODY_SCHEMA")
    public_signatures = {
        name: (parameters, vararg, kwarg)
        for name, parameters, vararg, kwarg in REFERENCE_CERTIFICATE[
            "public_signatures"
        ]
    }
    for node in function_nodes:
        signature = _pgp2_function_signature(node)
        if node.name in public_signatures and signature != public_signatures[node.name]:
            if node.args.vararg is not None or node.args.kwarg is not None:
                raise PGP2Violation("PGP2_F_VARARG")
            raise PGP2Violation("PGP2_M_PUBLIC_API")
    scanner = next(
        node
        for node in function_nodes
        if node.name == "scan_forbidden_pre_d1_artifacts"
    )
    if _pgp2_ast_shape(
        ast.Module(body=scanner.body, type_ignores=[])
    ) != _pgp2_ast_shape(ast.parse("return _pgp2_scan(roots)")):
        raise PGP2Violation("PGP2_M_PUBLIC_API")
    _pgp2_assert_call_and_effect_schema(tree)


_PGP2_REFERENCE_TREE = _pgp2_parse(REFERENCE_SOURCE)
_pgp2_assert_reference_certificate(_PGP2_REFERENCE_TREE)
_PGP2_REFERENCE_SHAPE = _pgp2_ast_shape(_PGP2_REFERENCE_TREE)


def _pgp2_diagnostic_code(tree: ast.Module) -> str:
    try:
        if _pgp2_import_declarations(tree) != REFERENCE_CERTIFICATE["imports"]:
            return "PGP2_M_IMPORT_SET"
        class_nodes = tuple(
            node for node in tree.body if isinstance(node, ast.ClassDef)
        )
        expected_classes = REFERENCE_CERTIFICATE["classes"]
        if tuple(node.name for node in class_nodes) != tuple(
            name for name, _ in expected_classes
        ):
            return "PGP2_D_CLASS_SET"
        for node, (_, expected_fields) in zip(class_nodes, expected_classes):
            try:
                fields_found = _pgp2_class_schema(node)
            except PGP2Violation as error:
                return error.code
            if fields_found != expected_fields:
                return "PGP2_D_FIELD_SCHEMA"
        if _pgp2_top_level_assignments(tree) != tuple(
            name for name, _ in REFERENCE_CERTIFICATE["constants"]
        ):
            return "PGP2_D_CONST_SCHEMA"
        function_nodes = tuple(
            node for node in tree.body if isinstance(node, ast.FunctionDef)
        )
        expected_functions = tuple(
            name for name, _ in REFERENCE_CERTIFICATE["private_effects"]
        ) + tuple(name for name, _, _, _ in REFERENCE_CERTIFICATE["public_signatures"])
        if tuple(node.name for node in function_nodes) != expected_functions:
            return "PGP2_F_FUNCTION_SET"
        public = {
            name: (parameters, vararg, kwarg)
            for name, parameters, vararg, kwarg in REFERENCE_CERTIFICATE[
                "public_signatures"
            ]
        }
        for node in function_nodes:
            try:
                signature = _pgp2_function_signature(node)
            except PGP2Violation as error:
                return error.code
            if node.name in public and signature != public[node.name]:
                if node.args.vararg is not None or node.args.kwarg is not None:
                    return "PGP2_F_VARARG"
                return "PGP2_M_PUBLIC_API"
        try:
            _pgp2_assert_call_and_effect_schema(tree)
        except PGP2Violation as error:
            return error.code
    except (KeyError, StopIteration, TypeError, ValueError):
        return "PGP2_M_TOPLEVEL_SEQUENCE"
    return "PGP2_M_AST_MISMATCH"


def _validate_pgp2_source(source: str) -> ast.Module:
    _attest_pgp2_environment(_PGP2_TRUST_CAPSULE)
    tree = _pgp2_parse(source)
    if _pgp2_ast_shape(tree) != _PGP2_REFERENCE_SHAPE:
        raise PGP2Violation(_pgp2_diagnostic_code(tree))
    return tree


def _execute_pgp2_source(
    source: str,
    *,
    source_path: str,
    module_name: str,
    capsule: SimpleNamespace,
) -> ModuleType:
    _attest_pgp2_environment(capsule)
    code = compile(source, source_path, "exec", dont_inherit=True, optimize=0)
    module = ModuleType(module_name)
    module.__file__ = source_path
    module.__package__ = module_name.rpartition(".")[0]
    module.__loader__ = None
    module.__spec__ = None
    module.__dict__["__builtins__"] = capsule.minimal_builtins
    sentinel = object()
    prior = sys.modules.get(module_name, sentinel)
    sys.modules[module_name] = module
    try:
        exec(code, module.__dict__)
    finally:
        if prior is sentinel:
            del sys.modules[module_name]
        else:
            sys.modules[module_name] = prior
    if module.__file__ != source_path or module.__name__ != module_name:
        raise PGP2Violation("PGP2_R_SOURCE_IDENTITY")
    return module


def _pgp2_code_state(code: object) -> tuple[object, ...]:
    if not inspect.iscode(code):
        raise PGP2Violation("PGP2_R_DEFINITION_STATE")
    constants: list[object] = []
    for value in code.co_consts:
        if inspect.iscode(value):
            constants.append(_pgp2_code_state(value))
        else:
            constants.append(value)
    return (
        code.co_argcount,
        code.co_posonlyargcount,
        code.co_kwonlyargcount,
        code.co_nlocals,
        code.co_stacksize,
        code.co_flags,
        code.co_code,
        tuple(constants),
        code.co_names,
        code.co_varnames,
        code.co_freevars,
        code.co_cellvars,
    )


def _pgp2_function_state(value: object) -> tuple[object, ...]:
    if not inspect.isfunction(value):
        raise PGP2Violation("PGP2_R_DEFINITION_STATE")
    if value.__defaults__ is not None or value.__kwdefaults__ is not None:
        raise PGP2Violation("PGP2_R_DEFINITION_STATE")
    if value.__closure__ is not None or value.__dict__:
        raise PGP2Violation("PGP2_R_DEFINITION_STATE")
    return (
        value.__name__,
        value.__qualname__,
        tuple(sorted(value.__annotations__.items())),
        _pgp2_code_state(value.__code__),
    )


def _pgp2_class_state(value: object) -> tuple[object, ...]:
    if not inspect.isclass(value) or type(value) is not type:
        raise PGP2Violation("PGP2_R_DEFINITION_STATE")
    if value.__bases__ != (object,):
        raise PGP2Violation("PGP2_R_DEFINITION_STATE")
    if not is_dataclass(value) or value.__dataclass_params__.frozen is not True:
        raise PGP2Violation("PGP2_R_DEFINITION_STATE")
    slots = value.__slots__
    if type(slots) is str:
        slots_tuple = (slots,)
    else:
        slots_tuple = tuple(slots)
    field_state = tuple(
        (field.name, field.type, field.default, field.default_factory)
        for field in fields(value)
    )
    return (
        value.__name__,
        value.__qualname__,
        tuple(sorted(vars(value))),
        tuple(sorted(value.__annotations__.items())),
        slots_tuple,
        field_state,
    )


def _pgp2_global_value_state(
    value: object,
    *,
    allow_class_leaf: bool = False,
    seen: frozenset[int] = frozenset(),
) -> object:
    value_type = type(value)
    if value is None or value_type in {bool, int, float, str, bytes}:
        return (value_type.__name__, value)
    if inspect.ismethod(value) or (
        inspect.isbuiltin(value) and getattr(value, "__self__", None) is not None
    ):
        raise PGP2Violation("PGP2_R_BOUND_OWNER")
    if inspect.isclass(value):
        if allow_class_leaf:
            return ("local_class_leaf", value.__name__)
        raise PGP2Violation("PGP2_R_GLOBAL_STATE")
    identity = id(value)
    if identity in seen:
        raise PGP2Violation("PGP2_R_GLOBAL_STATE")
    nested_seen = seen | {identity}
    if value_type is tuple:
        return (
            "tuple",
            tuple(_pgp2_global_value_state(item, seen=nested_seen) for item in value),
        )
    if value_type is MappingProxyType:
        items: list[tuple[object, object]] = []
        for key, item in value.items():
            items.append(
                (
                    _pgp2_global_value_state(key, seen=nested_seen),
                    _pgp2_global_value_state(
                        item,
                        allow_class_leaf=allow_class_leaf,
                        seen=nested_seen,
                    ),
                )
            )
        return ("mapping_proxy", tuple(items))
    if is_dataclass(value) and not isinstance(value, type):
        if value_type.__dataclass_params__.frozen is not True:
            raise PGP2Violation("PGP2_R_GLOBAL_STATE")
        return (
            "record",
            value_type.__name__,
            tuple(
                (
                    field.name,
                    _pgp2_global_value_state(
                        getattr(value, field.name),
                        seen=nested_seen,
                    ),
                )
                for field in fields(value)
            ),
        )
    raise PGP2Violation("PGP2_R_GLOBAL_STATE")


def _capture_pgp2_runtime_state(module: ModuleType) -> SimpleNamespace:
    expected_keys = set(REFERENCE_CERTIFICATE["runtime_namespace_keys"])
    if set(vars(module)) != expected_keys:
        raise PGP2Violation("PGP2_R_NAMESPACE_DRIFT")
    functions = {
        name: _pgp2_function_state(getattr(module, name))
        for name, _ in REFERENCE_CERTIFICATE["private_effects"]
    }
    for name, _, _, _ in REFERENCE_CERTIFICATE["public_signatures"]:
        functions[name] = _pgp2_function_state(getattr(module, name))
    classes = {
        name: _pgp2_class_state(getattr(module, name))
        for name, _ in REFERENCE_CERTIFICATE["classes"]
    }
    constants: dict[str, object] = {}
    for name, kind in REFERENCE_CERTIFICATE["constants"]:
        constants[name] = _pgp2_global_value_state(
            getattr(module, name),
            allow_class_leaf=kind == "class_mapping_proxy",
        )
    return SimpleNamespace(
        classes=classes,
        constants=constants,
        functions=functions,
    )


def _validate_pgp2_runtime(
    module: ModuleType,
    *,
    capsule: SimpleNamespace,
    reference_state: SimpleNamespace,
) -> tuple[tuple[str, object], ...]:
    _attest_pgp2_environment(capsule)
    if set(vars(module)) != set(REFERENCE_CERTIFICATE["runtime_namespace_keys"]):
        raise PGP2Violation("PGP2_R_NAMESPACE_DRIFT")
    if module.__dict__.get("__builtins__") is not capsule.minimal_builtins:
        raise PGP2Violation("PGP2_R_EXTERNAL_IDENTITY")
    for module_name, member_names in REFERENCE_CERTIFICATE["imports"]:
        for member_name in member_names:
            expected = capsule.external_objects[f"{module_name}.{member_name}"]
            if getattr(module, member_name) is not expected:
                raise PGP2Violation("PGP2_R_EXTERNAL_IDENTITY")
    for name, expected in reference_state.functions.items():
        if _pgp2_function_state(getattr(module, name)) != expected:
            raise PGP2Violation("PGP2_R_DEFINITION_STATE")
    for name, expected in reference_state.classes.items():
        if _pgp2_class_state(getattr(module, name)) != expected:
            raise PGP2Violation("PGP2_R_DEFINITION_STATE")
    constant_state: list[tuple[str, object]] = []
    for name, kind in REFERENCE_CERTIFICATE["constants"]:
        actual = _pgp2_global_value_state(
            getattr(module, name),
            allow_class_leaf=kind == "class_mapping_proxy",
        )
        if actual != reference_state.constants[name]:
            raise PGP2Violation("PGP2_R_GLOBAL_STATE")
        constant_state.append((name, actual))
    return tuple(constant_state)


_PGP2_REFERENCE_MODULE = _execute_pgp2_source(
    REFERENCE_SOURCE,
    source_path="<d1e-pgp2-reviewer-reference>",
    module_name="_d1e_pgp2_reviewer_reference",
    capsule=_PGP2_TRUST_CAPSULE,
)
_PGP2_REFERENCE_RUNTIME_STATE = _capture_pgp2_runtime_state(_PGP2_REFERENCE_MODULE)
_validate_pgp2_runtime(
    _PGP2_REFERENCE_MODULE,
    capsule=_PGP2_TRUST_CAPSULE,
    reference_state=_PGP2_REFERENCE_RUNTIME_STATE,
)


_PGP2_GENERATOR_PATH = (D1E_ROOT.resolve() / "generator.py").resolve()
_PGP2_GENERATOR_CACHE: dict[str, object] = {}


def _load_pgp2_path(
    source_path: Path,
    *,
    module_name: str,
    capsule: SimpleNamespace,
    cache: dict[str, object],
) -> ModuleType:
    _attest_pgp2_environment(capsule)
    pinned_path = source_path.resolve()
    if not source_path.is_absolute() or source_path != pinned_path:
        raise PGP2Violation("PGP2_R_SOURCE_IDENTITY")
    try:
        source_bytes = pinned_path.read_bytes()
        source = source_bytes.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise PGP2Violation("PGP2_R_SOURCE_IDENTITY") from error
    _validate_pgp2_source(source)
    cached_module = cache.get("module")
    if cached_module is not None:
        if source != cache.get("source"):
            cache.clear()
            raise PGP2Violation("PGP2_R_SOURCE_IDENTITY")
        if not isinstance(cached_module, ModuleType):
            cache.clear()
            raise PGP2Violation("PGP2_R_NAMESPACE_DRIFT")
        try:
            _validate_pgp2_runtime(
                cached_module,
                capsule=capsule,
                reference_state=_PGP2_REFERENCE_RUNTIME_STATE,
            )
        except PGP2Violation:
            cache.clear()
            raise
        return cached_module
    module = _execute_pgp2_source(
        source,
        source_path=str(pinned_path),
        module_name=module_name,
        capsule=capsule,
    )
    _validate_pgp2_runtime(
        module,
        capsule=capsule,
        reference_state=_PGP2_REFERENCE_RUNTIME_STATE,
    )
    cache["module"] = module
    cache["source"] = source
    return module


def _load_pgp2_generator() -> ModuleType:
    if _PGP2_GENERATOR_PATH.parent != D1E_ROOT.resolve():
        raise PGP2Violation("PGP2_R_SOURCE_IDENTITY")
    return _load_pgp2_path(
        _PGP2_GENERATOR_PATH,
        module_name="product_evals.lh_recovery_1a.generator",
        capsule=_PGP2_TRUST_CAPSULE,
        cache=_PGP2_GENERATOR_CACHE,
    )


@pytest.fixture(params=("reference", "product"), ids=("reference", "product"))
def generator_subject(request: pytest.FixtureRequest) -> tuple[ModuleType, str]:
    if request.param == "reference":
        return _PGP2_REFERENCE_MODULE, REFERENCE_SOURCE
    generator = _module("generator")
    return generator, inspect.getsource(generator)


_PURE_GENERATION_IMPORT_ROOTS = frozenset(
    {
        "__future__",
        "collections",
        "dataclasses",
        "enum",
        "hashlib",
        "hmac",
        "itertools",
        "json",
        "math",
        "re",
        "types",
        "typing",
        "unicodedata",
    }
)
_SCANNER_ONLY_IMPORT_ROOTS = frozenset({"pathlib"})
_ALLOWED_SCANNER_PATHLIB_CALL_LEAVES = frozenset(
    {
        "Path",
        "PurePath",
        "as_posix",
        "exists",
        "glob",
        "is_dir",
        "is_file",
        "is_relative_to",
        "iterdir",
        "match",
        "relative_to",
        "resolve",
        "rglob",
        "stat",
    }
)
_TYPE_METADATA_IMPORT_ROOTS = frozenset({"__future__", "typing"})
_DENIED_PURE_ROOT_CALL_PATHS = frozenset(
    {
        ("hashlib", "file_digest"),
        ("json", "dump"),
        ("json", "load"),
    }
)
_ALLOWED_PURE_ROOT_CALL_HEADS = MappingProxyType(
    {
        "collections": frozenset({"Counter"}),
        "dataclasses": frozenset(
            {"asdict", "astuple", "dataclass", "is_dataclass", "replace"}
        ),
        "enum": frozenset({"auto", "unique"}),
        "hashlib": frozenset({"new", "sha256"}),
        "hmac": frozenset({"HMAC", "compare_digest", "digest", "new"}),
        "json": frozenset({"dumps", "loads"}),
        "re": frozenset(
            {"compile", "escape", "fullmatch", "match", "search", "sub", "subn"}
        ),
        "types": frozenset({"MappingProxyType"}),
    }
)
_ALLOWED_PURE_BUILTINS = frozenset(
    {
        "abs",
        "all",
        "any",
        "AssertionError",
        "bool",
        "bytes",
        "callable",
        "chr",
        "dict",
        "divmod",
        "enumerate",
        "filter",
        "float",
        "format",
        "frozenset",
        "hash",
        "hex",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "map",
        "max",
        "min",
        "next",
        "NotImplementedError",
        "oct",
        "ord",
        "pow",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "slice",
        "sorted",
        "str",
        "sum",
        "tuple",
        "type",
        "TypeError",
        "ValueError",
        "zip",
    }
)
_DENIED_BUILTINS = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "globals",
        "help",
        "input",
        "locals",
        "open",
        "print",
        "vars",
    }
)
_REFLECTION_OR_MUTATION_ESCAPES = frozenset(
    {
        "__builtins__",
        "__class__",
        "__closure__",
        "__dict__",
        "__globals__",
        "__mro__",
        "__subclasses__",
    }
)
_MUTATING_METHODS = frozenset(
    {
        "__delattr__",
        "__delitem__",
        "__setattr__",
        "__setitem__",
        "add",
        "append",
        "clear",
        "difference_update",
        "discard",
        "extend",
        "insert",
        "intersection_update",
        "pop",
        "popitem",
        "remove",
        "reverse",
        "setdefault",
        "sort",
        "symmetric_difference_update",
        "update",
    }
)
_GENERATION_ENTRY_POINTS = frozenset(
    {
        "canonical_length_delimited_json",
        "derive_case_seed",
        "derive_family_artifacts",
        "generate_case",
        "generate_cases",
        "normalized_semantic_bytes",
        "reference_result",
        "semantic_digest",
        "semantic_uniqueness_violations",
        "validate_family_semantics",
        "validate_fixture_lineage",
    }
)
_SCANNER_ENTRY_POINTS = frozenset({"scan_forbidden_pre_d1_artifacts"})
_ANALYZE_ENTRY_POINTS = frozenset(
    {"detect_forbidden_digest_bindings", "detect_forbidden_digest_ast"}
)
_ANALYZE_ONLY_IMPORT_ROOTS = frozenset({"ast"})
_PGP2_CERTIFIED_UNRESOLVED_METHODS = MappingProxyType(
    {
        "generation": frozenset(
            {
                "append",
                "isdigit",
                "items",
                "replace",
                "rstrip",
                "split",
                "startswith",
                "upper",
            }
        ),
        "analyze": frozenset({"isalnum", "items", "lower"}),
        "scanner": frozenset({"is_file", "match", "rglob"}),
    }
)
_UNRESOLVED_ORIGIN = ("<unresolved>",)


def _assignment_names(target: ast.AST) -> tuple[str, ...]:
    return tuple(
        node.id
        for node in ast.walk(target)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    )


def _is_dunder_name(name: str) -> bool:
    return len(name) >= 4 and name.startswith("__") and name.endswith("__")


def _scope_alias_bindings(
    root: ast.AST,
) -> dict[str, tuple[ast.AST | tuple[str, ...] | None, ...]]:
    bindings: dict[str, list[ast.AST | tuple[str, ...] | None]] = {}
    supported_store_ids: set[int] = set()
    scope_nodes = _walk_without_nested_definition_bodies(root)

    def append(name: str, value: ast.AST | tuple[str, ...] | None) -> None:
        bindings.setdefault(name, []).append(value)

    for node in scope_nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    append(target.id, node.value)
                    supported_store_ids.add(id(target))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            append(node.target.id, node.value)
            supported_store_ids.add(id(node.target))
        elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            append(node.target.id, node.value)
            supported_store_ids.add(id(node.target))
        elif isinstance(node, ast.ExceptHandler) and node.name is not None:
            append(node.name, None)

    for node in scope_nodes:
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and id(node) not in supported_store_ids
        ):
            append(node.id, None)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Del):
            append(node.id, None)
    return {name: tuple(values) for name, values in bindings.items()}


def _resolve_consistent_alias_origins(
    base_origins: dict[str, tuple[str, ...]],
    bindings: dict[str, tuple[ast.AST | tuple[str, ...] | None, ...]],
    frozen_class_mappings: frozenset[str],
    *,
    protected_names: frozenset[str] = frozenset(),
) -> dict[str, tuple[str, ...]]:
    rebound_names = bindings.keys() - protected_names
    stable_base = {
        name: origin
        for name, origin in base_origins.items()
        if name not in rebound_names or name in protected_names
    }
    origins = {
        **stable_base,
        **{
            name: _UNRESOLVED_ORIGIN for name in bindings if name not in protected_names
        },
    }
    for _ in range(len(bindings) + 1):
        resolved = {
            **stable_base,
            **{
                name: _UNRESOLVED_ORIGIN
                for name in bindings
                if name not in protected_names
            },
        }
        for name, values in bindings.items():
            if name in protected_names:
                continue
            candidates: list[tuple[str, ...]] = []
            for value in values:
                if value is None:
                    candidates.append(_UNRESOLVED_ORIGIN)
                elif isinstance(value, tuple):
                    candidates.append(value)
                else:
                    candidates.append(
                        _origin_from_ast(value, origins, frozen_class_mappings)
                    )
            if (
                candidates
                and candidates[0] != _UNRESOLVED_ORIGIN
                and all(candidate == candidates[0] for candidate in candidates)
            ):
                resolved[name] = candidates[0]
        if resolved == origins:
            return resolved
        origins = resolved
    return origins


def _assert_no_dunder_state_or_lambda(tree: ast.Module) -> None:
    for node in ast.walk(tree):
        assert not isinstance(node, ast.Lambda), "lambda bodies are not closure-audited"
        assert not isinstance(node, ast.Match), (
            "structural pattern matching has unaudited lexical bindings"
        )
        if isinstance(node, ast.Attribute):
            assert not _is_dunder_name(node.attr), (
                f"dunder attribute access is forbidden: {node.attr}"
            )
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "__builtins__"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            assert not _is_dunder_name(node.slice.value), (
                f"dunder builtins lookup is forbidden: {node.slice.value}"
            )
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            assert not _is_dunder_name(node.args[1].value), (
                f"dunder getattr is forbidden: {node.args[1].value}"
            )

    for definition in (
        node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ):
        for statement in definition.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert not _is_dunder_name(statement.name), (
                    f"source-declared dunder method is forbidden: "
                    f"{definition.name}.{statement.name}"
                )
            elif isinstance(statement, ast.Assign):
                declared_names = {
                    name
                    for target in statement.targets
                    for name in _assignment_names(target)
                }
                assert not any(_is_dunder_name(name) for name in declared_names), (
                    f"source-declared dunder class assignment is forbidden: "
                    f"{definition.name}"
                )
            elif isinstance(statement, ast.AnnAssign):
                declared_names = set(_assignment_names(statement.target))
                assert not any(_is_dunder_name(name) for name in declared_names), (
                    f"source-declared dunder class annotation is forbidden: "
                    f"{definition.name}"
                )


def _is_recursively_immutable_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return node.value is None or isinstance(
            node.value, (bool, int, float, complex, str, bytes)
        )
    if isinstance(node, ast.Tuple):
        return all(_is_recursively_immutable_literal(item) for item in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_recursively_immutable_literal(node.operand)
    return False


def _is_mutable_expression(node: ast.AST) -> bool:
    if isinstance(
        node,
        (
            ast.Dict,
            ast.DictComp,
            ast.GeneratorExp,
            ast.List,
            ast.ListComp,
            ast.Set,
            ast.SetComp,
        ),
    ):
        return True
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Name):
        return node.func.id in {
            "bytearray",
            "dict",
            "enumerate",
            "filter",
            "iter",
            "list",
            "map",
            "reversed",
            "set",
            "zip",
        }
    return isinstance(node.func, ast.Attribute) and _root_name(node.func) == "itertools"


def _is_proven_immutable_initializer(
    node: ast.AST,
    origins: dict[str, tuple[str, ...]],
    frozen_class_mappings: frozenset[str],
    frozen_classes: frozenset[str],
    enum_classes: frozenset[str],
) -> bool:
    if _is_recursively_immutable_literal(node):
        return True
    if isinstance(node, ast.Name):
        origin = _origin_from_ast(node, origins, frozen_class_mappings)
        return bool(
            origin
            and origin[0] == "local"
            and origin[1] in frozen_classes | enum_classes
        )
    if not isinstance(node, ast.Call):
        return False
    origin = _origin_from_ast(node.func, origins, frozen_class_mappings)
    if origin[-2:] == ("re", "compile"):
        return all(
            _is_recursively_immutable_literal(argument) for argument in node.args
        ) and all(
            _is_recursively_immutable_literal(keyword.value)
            for keyword in node.keywords
        )
    if origin[-2:] == ("enum", "auto") and not node.args and not node.keywords:
        return True
    if origin == ("types", "MappingProxyType") and len(node.args) == 1:
        payload = node.args[0]
        return isinstance(payload, ast.Dict) and all(
            key is not None
            and _is_proven_immutable_initializer(
                key,
                origins,
                frozen_class_mappings,
                frozen_classes,
                enum_classes,
            )
            and _is_proven_immutable_initializer(
                value,
                origins,
                frozen_class_mappings,
                frozen_classes,
                enum_classes,
            )
            for key, value in zip(payload.keys, payload.values)
        )
    if origin in {("builtins", "frozenset"), ("builtins", "tuple")}:
        return all(
            _is_recursively_immutable_literal(argument)
            or isinstance(argument, (ast.List, ast.Set, ast.Tuple))
            and all(_is_recursively_immutable_literal(item) for item in argument.elts)
            for argument in node.args
        )
    if origin and origin[0] == "local" and origin[1] in (frozen_classes | enum_classes):
        return all(
            _is_proven_immutable_initializer(
                argument,
                origins,
                frozen_class_mappings,
                frozen_classes,
                enum_classes,
            )
            for argument in node.args
        ) and all(
            _is_proven_immutable_initializer(
                keyword.value,
                origins,
                frozen_class_mappings,
                frozen_classes,
                enum_classes,
            )
            for keyword in node.keywords
        )
    return False


def _source_assignment_values(tree: ast.Module) -> dict[str, ast.AST]:
    return {
        name: values[-1]
        for name, values in _scope_alias_bindings(tree).items()
        if values and all(isinstance(value, ast.AST) for value in values)
    }


def _origin_from_ast(
    node: ast.AST,
    origins: dict[str, tuple[str, ...]],
    frozen_class_mappings: frozenset[str],
) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        if node.id in origins:
            return origins[node.id]
        if node.id == "__builtins__":
            return ("builtins",)
        if node.id in _ALLOWED_PURE_BUILTINS | _DENIED_BUILTINS | {
            "classmethod",
            "delattr",
            "getattr",
            "object",
            "property",
            "setattr",
            "staticmethod",
        }:
            return ("builtins", node.id)
        return ()
    if isinstance(node, ast.Constant):
        return ("builtins", type(node.value).__name__)
    if isinstance(node, ast.Tuple):
        return ("builtins", "tuple")
    if isinstance(node, ast.List):
        return ("builtins", "list")
    if isinstance(node, ast.Dict):
        return ("builtins", "dict")
    if isinstance(node, ast.Set):
        return ("builtins", "set")
    if isinstance(node, ast.ListComp):
        return ("builtins", "list")
    if isinstance(node, ast.SetComp):
        return ("builtins", "set")
    if isinstance(node, ast.DictComp):
        return ("builtins", "dict")
    if isinstance(node, ast.GeneratorExp):
        return ("builtins", "generator")
    if isinstance(node, ast.JoinedStr):
        return ("builtins", "str")
    if isinstance(node, ast.Lambda):
        return ("local_nested", "lambda")
    if isinstance(node, ast.Attribute):
        assert not _is_dunder_name(node.attr), (
            f"dunder attribute access is forbidden: {node.attr}"
        )
        parent = _origin_from_ast(node.value, origins, frozen_class_mappings)
        if parent == _UNRESOLVED_ORIGIN:
            return _UNRESOLVED_ORIGIN
        return (*parent, node.attr) if parent else ()
    if isinstance(node, ast.Subscript):
        parent = _origin_from_ast(node.value, origins, frozen_class_mappings)
        if parent == _UNRESOLVED_ORIGIN:
            return _UNRESOLVED_ORIGIN
        if parent == ("builtins",) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                assert not _is_dunder_name(node.slice.value), (
                    f"dunder builtins lookup is forbidden: {node.slice.value}"
                )
                return ("builtins", node.slice.value)
        root = node.value.id if isinstance(node.value, ast.Name) else ""
        if root in frozen_class_mappings:
            return ("local_frozen_class_mapping", root)
        return ()
    if isinstance(node, ast.Call):
        callable_origin = _origin_from_ast(node.func, origins, frozen_class_mappings)
        if callable_origin == ("builtins", "getattr"):
            assert len(node.args) >= 2, (
                "getattr without a constant attribute is forbidden"
            )
            requested = node.args[1]
            assert isinstance(requested, ast.Constant) and isinstance(
                requested.value, str
            ), "dynamic getattr is forbidden"
            assert not _is_dunder_name(requested.value), (
                f"dunder getattr is forbidden: {requested.value}"
            )
            target = _origin_from_ast(node.args[0], origins, frozen_class_mappings)
            assert target and target != _UNRESOLVED_ORIGIN, (
                "getattr target provenance is unresolved"
            )
            return (*target, requested.value)
        return callable_origin
    if isinstance(node, ast.IfExp):
        left = _origin_from_ast(node.body, origins, frozen_class_mappings)
        right = _origin_from_ast(node.orelse, origins, frozen_class_mappings)
        return left if left == right else ()
    return ()


def _is_frozen_dataclass_ast(
    node: ast.ClassDef,
    origins: dict[str, tuple[str, ...]],
    frozen_class_mappings: frozenset[str],
) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        origin = _origin_from_ast(target, origins, frozen_class_mappings)
        if not origin or origin[-1] != "dataclass":
            continue
        if not isinstance(decorator, ast.Call):
            return False
        return any(
            keyword.arg == "frozen"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in decorator.keywords
        )
    return False


def _is_enum_ast(
    node: ast.ClassDef,
    origins: dict[str, tuple[str, ...]],
    frozen_class_mappings: frozenset[str],
) -> bool:
    return any(
        (origin := _origin_from_ast(base, origins, frozen_class_mappings))
        and origin[0] == "enum"
        and origin[-1] in {"Enum", "IntEnum", "StrEnum"}
        for base in node.bases
    )


def _import_origin_bindings(
    tree: ast.Module,
) -> dict[str, tuple[tuple[str, ...], ...]]:
    bindings: dict[str, list[tuple[str, ...]]] = {}
    top_level_ids = {id(node) for node in tree.body}
    permitted_roots = (
        _PURE_GENERATION_IMPORT_ROOTS
        | _ANALYZE_ONLY_IMPORT_ROOTS
        | _SCANNER_ONLY_IMPORT_ROOTS
    )

    def append(name: str, origin: tuple[str, ...]) -> None:
        bindings.setdefault(name, []).append(origin)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert id(node) in top_level_ids, (
                "imports are permitted only at module top level"
            )
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                assert root in permitted_roots, f"unknown or impure import root: {root}"
                local_name = alias.asname or root
                append(
                    local_name,
                    tuple(alias.name.split(".")) if alias.asname else (root,),
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, (
                "relative imports are not permitted in the generator"
            )
            root = (node.module or "").split(".", 1)[0]
            assert root in permitted_roots, f"unknown or impure import root: {root}"
            for alias in node.names:
                assert alias.name != "*", "star imports have unresolved provenance"
                local_name = alias.asname or alias.name
                append(
                    local_name,
                    (*tuple((node.module or "").split(".")), alias.name),
                )
    return {name: tuple(origins) for name, origins in bindings.items()}


def _local_definition_closure(
    roots: frozenset[str],
    definitions: dict[str, ast.AST],
) -> frozenset[str]:
    missing = roots - definitions.keys()
    assert not missing, f"missing purity closure roots: {sorted(missing)}"
    reached: set[str] = set()
    frontier = list(sorted(roots, reverse=True))
    while frontier:
        name = frontier.pop()
        if name in reached:
            continue
        reached.add(name)
        references = {
            child.id
            for child in ast.walk(definitions[name])
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
        }
        frontier.extend(
            sorted((references & definitions.keys()) - reached, reverse=True)
        )
    return frozenset(reached)


def _root_name(node: ast.AST) -> str:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def _definition_origins(
    definition: ast.AST,
    module_origins: dict[str, tuple[str, ...]],
    frozen_class_mappings: frozenset[str],
    *,
    owner_class: str | None = None,
) -> dict[str, tuple[str, ...]]:
    origins = dict(module_origins)
    lexical_bindings = {
        name: list(values) for name, values in _scope_alias_bindings(definition).items()
    }
    if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
        arguments = (
            *definition.args.posonlyargs,
            *definition.args.args,
            *definition.args.kwonlyargs,
        )
        for argument in arguments:
            lexical_bindings.setdefault(argument.arg, []).insert(0, None)
        if definition.args.vararg is not None:
            lexical_bindings.setdefault(definition.args.vararg.arg, []).insert(0, None)
        if definition.args.kwarg is not None:
            lexical_bindings.setdefault(definition.args.kwarg.arg, []).insert(0, None)
        if owner_class is not None:
            if arguments and arguments[0].arg in {"self", "cls"}:
                lexical_bindings[arguments[0].arg][0] = ("local", owner_class)
    for child in _direct_nested_definitions(definition):
        origins[child.name] = ("local_nested", child.name)
        if child.name in lexical_bindings:
            lexical_bindings[child.name].insert(0, ("local_nested", child.name))
    return _resolve_consistent_alias_origins(
        origins,
        {name: tuple(values) for name, values in lexical_bindings.items()},
        frozen_class_mappings,
    )


def _assert_call_origin_allowed(
    call: ast.Call,
    origins: dict[str, tuple[str, ...]],
    frozen_class_mappings: frozenset[str],
    *,
    scope: str,
    closure: frozenset[str],
    definitions: dict[str, ast.AST],
    frozen_classes: frozenset[str],
    enum_classes: frozenset[str],
    pgp2_certified: bool,
) -> None:
    if isinstance(call.func, ast.Call):
        inner_origin = _origin_from_ast(call.func.func, origins, frozen_class_mappings)
        assert inner_origin == ("builtins", "getattr"), (
            f"callable return provenance is unresolved at line {call.lineno}"
        )
    origin = _origin_from_ast(call.func, origins, frozen_class_mappings)
    if (
        pgp2_certified
        and origin == _UNRESOLVED_ORIGIN
        and isinstance(call.func, ast.Attribute)
        and call.func.attr in _PGP2_CERTIFIED_UNRESOLVED_METHODS.get(scope, ())
    ):
        return
    assert origin and origin != _UNRESOLVED_ORIGIN, (
        f"unresolved callable provenance at line {call.lineno}"
    )
    root = origin[0]
    leaf = origin[-1]
    assert leaf not in _REFLECTION_OR_MUTATION_ESCAPES
    if root == "builtins":
        assert leaf not in _DENIED_BUILTINS, f"forbidden builtin: {leaf}"
        assert not (
            len(origin) >= 3
            and origin[-2] in {"object", "type"}
            and leaf == "__setattr__"
        ), "class/object mutation is forbidden"
        if leaf == "getattr":
            assert len(call.args) >= 2
            requested = call.args[1]
            assert isinstance(requested, ast.Constant) and isinstance(
                requested.value, str
            ), "dynamic getattr is forbidden"
            assert not _is_dunder_name(requested.value), (
                f"dunder getattr is forbidden: {requested.value}"
            )
            assert requested.value not in (
                _DENIED_BUILTINS | _REFLECTION_OR_MUTATION_ESCAPES
            )
            target_origin = _origin_from_ast(
                call.args[0], origins, frozen_class_mappings
            )
            assert target_origin and target_origin != _UNRESOLVED_ORIGIN, (
                "getattr target provenance is unresolved"
            )
            return
        assert leaf not in {"delattr", "setattr"}
        builtin_type_method = len(origin) >= 3 and origin[1] in {
            "bool",
            "bytes",
            "dict",
            "float",
            "frozenset",
            "int",
            "list",
            "set",
            "str",
            "tuple",
        }
        assert (
            origin[1] in _ALLOWED_PURE_BUILTINS
            or origin[1] in {"classmethod", "getattr", "property", "staticmethod"}
            or builtin_type_method
        ), f"builtin callable is not explicitly pure: {'.'.join(origin)}"
        return
    if root == "local_frozen_class_mapping":
        return
    if root == "local_nested":
        return
    if root == "local":
        local_name = origin[1]
        if scope == "initializer":
            assert local_name in frozen_classes | enum_classes, (
                f"module initializer calls arbitrary local definition: {local_name}"
            )
            return
        assert local_name in closure, (
            f"local call escapes {scope} closure: {local_name}"
        )
        assert local_name in definitions
        return
    if root in _SCANNER_ONLY_IMPORT_ROOTS:
        assert scope == "scanner", f"scanner-only import used by {scope}: {root}"
        assert leaf in _ALLOWED_SCANNER_PATHLIB_CALL_LEAVES, (
            f"scanner filesystem call is not read-only: {'.'.join(origin)}"
        )
        return
    if root in _ANALYZE_ONLY_IMPORT_ROOTS:
        assert scope == "analyze", f"analyze-only import used by {scope}: {root}"
        return
    assert root in _PURE_GENERATION_IMPORT_ROOTS, (
        f"unknown or impure callable root at line {call.lineno}: {root}"
    )
    assert origin[:2] not in _DENIED_PURE_ROOT_CALL_PATHS, (
        f"I/O-bearing member of a pure root is forbidden: {'.'.join(origin)}"
    )
    if root in _ALLOWED_PURE_ROOT_CALL_HEADS:
        assert len(origin) >= 2 and origin[1] in _ALLOWED_PURE_ROOT_CALL_HEADS[root], (
            f"call member is outside the frozen pure surface: {'.'.join(origin)}"
        )
    assert root not in _TYPE_METADATA_IMPORT_ROOTS, (
        f"type metadata is not callable runtime provenance: {'.'.join(origin)}"
    )


def _mutable_locals_captured_by_nested_function(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> frozenset[str]:
    mutable_locals: set[str] = set()
    for statement in function.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for child in ast.walk(statement):
            if isinstance(child, ast.Assign) and _is_mutable_expression(child.value):
                mutable_locals.update(
                    name
                    for target in child.targets
                    for name in _assignment_names(target)
                )
            elif (
                isinstance(child, ast.AnnAssign)
                and child.value is not None
                and _is_mutable_expression(child.value)
            ):
                mutable_locals.update(_assignment_names(child.target))
    captured: set[str] = set()
    for nested in ast.walk(function):
        if nested is function or not isinstance(
            nested, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
        ):
            continue
        captured.update(
            child.id
            for child in ast.walk(nested)
            if isinstance(child, ast.Name)
            and isinstance(child.ctx, ast.Load)
            and child.id in mutable_locals
        )
    return frozenset(captured)


def _walk_without_nested_definition_bodies(root: ast.AST) -> tuple[ast.AST, ...]:
    walked: list[ast.AST] = []
    frontier = [root]
    while frontier:
        node = frontier.pop()
        walked.append(node)
        children = tuple(ast.iter_child_nodes(node))
        frontier.extend(
            child
            for child in reversed(children)
            if child is root
            or not isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
            )
        )
    return tuple(walked)


def _direct_nested_definitions(root: ast.AST) -> tuple[ast.AST, ...]:
    nested: list[ast.AST] = []
    frontier = list(ast.iter_child_nodes(root))
    while frontier:
        node = frontier.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nested.append(node)
            continue
        frontier.extend(ast.iter_child_nodes(node))
    return tuple(nested)


def _assert_definition_is_pure(
    definition: ast.AST,
    module_origins: dict[str, tuple[str, ...]],
    frozen_class_mappings: frozenset[str],
    *,
    scope: str,
    closure: frozenset[str],
    definitions: dict[str, ast.AST],
    module_global_names: frozenset[str],
    frozen_classes: frozenset[str],
    enum_classes: frozenset[str],
    pgp2_certified: bool,
    owner_class: str | None = None,
) -> None:
    origins = _definition_origins(
        definition,
        module_origins,
        frozen_class_mappings,
        owner_class=owner_class,
    )
    lexical_names = set(_scope_alias_bindings(definition))
    if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
        lexical_names.update(
            argument.arg
            for argument in (
                *definition.args.posonlyargs,
                *definition.args.args,
                *definition.args.kwonlyargs,
            )
        )
        if definition.args.vararg is not None:
            lexical_names.add(definition.args.vararg.arg)
        if definition.args.kwarg is not None:
            lexical_names.add(definition.args.kwarg.arg)
        defaults = (*definition.args.defaults, *definition.args.kw_defaults)
        assert all(
            default is None or _is_recursively_immutable_literal(default)
            for default in defaults
        ), f"mutable or callable default in {definition.name}"
        captured = _mutable_locals_captured_by_nested_function(definition)
        assert not captured, (
            f"mutable closure state in {definition.name}: {sorted(captured)}"
        )
    decorators = getattr(definition, "decorator_list", ())
    for decorator in decorators:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        decorator_origin = _origin_from_ast(target, origins, frozen_class_mappings)
        assert decorator_origin, "decorator provenance is unresolved"
        assert decorator_origin[0] not in {
            "local",
            "local_nested",
            *_ANALYZE_ONLY_IMPORT_ROOTS,
            *_SCANNER_ONLY_IMPORT_ROOTS,
            *_TYPE_METADATA_IMPORT_ROOTS,
        }, f"decorator executes a forbidden initializer: {'.'.join(decorator_origin)}"
        if decorator_origin[0] == "builtins":
            assert decorator_origin[-1] in {
                "classmethod",
                "property",
                "staticmethod",
            }
        else:
            assert decorator_origin[:2] in {
                ("dataclasses", "dataclass"),
                ("enum", "unique"),
            }, (
                f"decorator is outside the frozen initializer surface: {'.'.join(decorator_origin)}"
            )
    if isinstance(definition, ast.ClassDef):
        assert not definition.keywords, f"custom metaclass forbidden: {definition.name}"
        assert definition.name in frozen_classes | enum_classes, (
            f"generation class must be a frozen dataclass or enum: {definition.name}"
        )
        for statement in definition.body:
            assert isinstance(
                statement,
                (
                    ast.AnnAssign,
                    ast.Assign,
                    ast.AsyncFunctionDef,
                    ast.Expr,
                    ast.FunctionDef,
                    ast.Pass,
                ),
            ), f"arbitrary class-body initializer: {definition.name}"
            if isinstance(statement, ast.Expr):
                assert isinstance(statement.value, ast.Constant) and isinstance(
                    statement.value.value, str
                ), f"class-body expression initializer: {definition.name}"
            value: ast.AST | None = None
            target_name = ""
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                if isinstance(statement.targets[0], ast.Name):
                    target_name = statement.targets[0].id
                    value = statement.value
            elif isinstance(statement, ast.AnnAssign) and isinstance(
                statement.target, ast.Name
            ):
                target_name = statement.target.id
                value = statement.value
            if target_name:
                assert not _is_dunder_name(target_name), (
                    f"source-declared dunder class state is forbidden: "
                    f"{definition.name}.{target_name}"
                )
            if value is not None:
                assert _is_proven_immutable_initializer(
                    value,
                    origins,
                    frozen_class_mappings,
                    frozen_classes,
                    enum_classes,
                ), f"mutable/callable class state: {definition.name}.{target_name}"
    nested_owner = (
        definition.name if isinstance(definition, ast.ClassDef) else owner_class
    )
    nested_definitions = _direct_nested_definitions(definition)
    lexical_names.update(nested.name for nested in nested_definitions)
    for nested in nested_definitions:
        _assert_definition_is_pure(
            nested,
            origins,
            frozen_class_mappings,
            scope=scope,
            closure=closure,
            definitions=definitions,
            module_global_names=module_global_names,
            frozen_classes=frozen_classes,
            enum_classes=enum_classes,
            pgp2_certified=pgp2_certified,
            owner_class=nested_owner,
        )

    for node in _walk_without_nested_definition_bodies(definition):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            assert node.id not in _REFLECTION_OR_MUTATION_ESCAPES
            loaded_origin = _origin_from_ast(node, origins, frozen_class_mappings)
            if scope == "generation" and node.id not in lexical_names:
                assert loaded_origin and loaded_origin != _UNRESOLVED_ORIGIN, (
                    f"unresolved module-global read in generation: {node.id}"
                )
            if loaded_origin:
                assert not (
                    loaded_origin[0] in _SCANNER_ONLY_IMPORT_ROOTS
                    and scope != "scanner"
                ), f"scanner-only name used by {scope}: {node.id}"
                assert not (
                    loaded_origin[0] in _ANALYZE_ONLY_IMPORT_ROOTS
                    and scope != "analyze"
                ), f"analyze-only name used by {scope}: {node.id}"
                assert not (
                    loaded_origin[0] == "builtins"
                    and loaded_origin[-1] in _DENIED_BUILTINS
                ), f"forbidden builtin reference: {loaded_origin[-1]}"
        if isinstance(node, ast.Attribute):
            assert node.attr not in _REFLECTION_OR_MUTATION_ESCAPES
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise AssertionError(
                f"shared-scope mutation in {scope}: {type(node).__name__}"
            )
        if isinstance(node, ast.Call):
            _assert_call_origin_allowed(
                node,
                origins,
                frozen_class_mappings,
                scope=scope,
                closure=closure,
                definitions=definitions,
                frozen_classes=frozen_classes,
                enum_classes=enum_classes,
                pgp2_certified=pgp2_certified,
            )
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in _MUTATING_METHODS:
                    assert _root_name(node.func.value) not in module_global_names, (
                        "generation mutates module-owned state"
                    )
        targets: tuple[ast.AST, ...] = ()
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = (node.target,)
        elif isinstance(node, ast.Delete):
            targets = tuple(node.targets)
        for target in targets:
            for part in ast.walk(target):
                if isinstance(part, (ast.Attribute, ast.Subscript)):
                    assert _root_name(part) not in module_global_names, (
                        "generation writes module-owned state"
                    )


def _audit_generator_purity_source(
    source: str,
    *,
    generation_roots: frozenset[str] = _GENERATION_ENTRY_POINTS,
    analyze_roots: frozenset[str] = frozenset(),
    scanner_roots: frozenset[str] = _SCANNER_ENTRY_POINTS,
) -> dict[str, frozenset[str]]:
    tree = ast.parse(source)
    pgp2_certified = _pgp2_ast_shape(tree) == _PGP2_REFERENCE_SHAPE
    _assert_no_dunder_state_or_lambda(tree)
    definition_nodes = tuple(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )
    definitions = {node.name: node for node in definition_nodes}
    assert len(definitions) == len(definition_nodes), (
        "duplicate top-level definitions have ambiguous provenance"
    )
    import_bindings = _import_origin_bindings(tree)
    base_module_origins: dict[str, tuple[str, ...]] = {}
    module_bindings = {
        name: list(values) for name, values in _scope_alias_bindings(tree).items()
    }
    for name, origins in import_bindings.items():
        module_bindings.setdefault(name, [])[0:0] = origins
    for name in definitions:
        module_bindings.setdefault(name, []).insert(0, ("local", name))
    module_origins = _resolve_consistent_alias_origins(
        base_module_origins,
        {name: tuple(values) for name, values in module_bindings.items()},
        frozenset(),
    )
    assignment_values = _source_assignment_values(tree)
    frozen_class_mappings: set[str] = set()
    frozen_mapping_value_classes: dict[str, frozenset[str]] = {}

    frozen_classes = frozenset(
        name
        for name, node in definitions.items()
        if isinstance(node, ast.ClassDef)
        and _is_frozen_dataclass_ast(node, module_origins, frozenset())
    )
    enum_classes = frozenset(
        name
        for name, node in definitions.items()
        if isinstance(node, ast.ClassDef)
        and _is_enum_ast(node, module_origins, frozenset())
    )
    for name, value in assignment_values.items():
        if not isinstance(value, ast.Call) or not value.args:
            continue
        resolved_bindings = tuple(
            binding
            if isinstance(binding, tuple)
            else ()
            if binding is None
            else _origin_from_ast(binding, module_origins, frozenset())
            for binding in module_bindings.get(name, [])
        )
        if not resolved_bindings or not all(
            origin == ("types", "MappingProxyType") for origin in resolved_bindings
        ):
            continue
        origin = _origin_from_ast(value.func, module_origins, frozenset())
        payload = value.args[0]
        if origin[-2:] != ("types", "MappingProxyType") or not isinstance(
            payload, ast.Dict
        ):
            continue
        value_names = {item.id for item in payload.values if isinstance(item, ast.Name)}
        if len(value_names) == len(payload.values) and value_names <= frozen_classes:
            frozen_class_mappings.add(name)
            frozen_mapping_value_classes[name] = frozenset(value_names)
            module_origins[name] = ("local_frozen_class_mapping", name)
    for _ in range(len(assignment_values) + 1):
        changed = False
        current_mapping_names = frozenset(frozen_class_mappings)
        for name, value in assignment_values.items():
            if name in frozen_class_mappings:
                continue
            bindings = module_bindings.get(name, [])
            resolved_bindings = tuple(
                binding
                if isinstance(binding, tuple)
                else ()
                if binding is None
                else _origin_from_ast(binding, module_origins, current_mapping_names)
                for binding in bindings
            )
            if (
                not resolved_bindings
                or not resolved_bindings[0]
                or not all(
                    origin == resolved_bindings[0] for origin in resolved_bindings
                )
                or resolved_bindings[0][0] != "local_frozen_class_mapping"
            ):
                continue
            source_mapping = resolved_bindings[0][1]
            frozen_class_mappings.add(name)
            frozen_mapping_value_classes[name] = frozen_mapping_value_classes[
                source_mapping
            ]
            module_origins[name] = ("local_frozen_class_mapping", name)
            changed = True
        if not changed:
            break
    frozen_class_mapping_names = frozenset(frozen_class_mappings)
    module_origins = _resolve_consistent_alias_origins(
        {
            **base_module_origins,
            **{
                name: ("local_frozen_class_mapping", name)
                for name in frozen_class_mapping_names
            },
        },
        {name: tuple(values) for name, values in module_bindings.items()},
        frozen_class_mapping_names,
        protected_names=frozen_class_mapping_names,
    )

    preliminary_generation_closure = _local_definition_closure(
        generation_roots, definitions
    )
    referenced_frozen_mappings = {
        child.id
        for name in preliminary_generation_closure
        for child in ast.walk(definitions[name])
        if isinstance(child, ast.Name)
        and isinstance(child.ctx, ast.Load)
        and child.id in frozen_class_mapping_names
    }
    mapped_generation_classes = frozenset(
        class_name
        for mapping_name in referenced_frozen_mappings
        for class_name in frozen_mapping_value_classes[mapping_name]
    )
    generation_closure = _local_definition_closure(
        generation_roots | mapped_generation_classes,
        definitions,
    )
    analyze_closure = (
        _local_definition_closure(analyze_roots, definitions)
        if analyze_roots
        else frozenset()
    )
    scanner_total_closure = _local_definition_closure(scanner_roots, definitions)
    scanner_own_closure = scanner_total_closure - analyze_closure
    assert generation_closure.isdisjoint(analyze_closure), (
        "generation and analyze closures must be disjoint"
    )
    assert generation_closure.isdisjoint(scanner_total_closure), (
        "generation and scanner-total closures must be disjoint"
    )
    passive_frozen_definitions = (frozen_classes | enum_classes) - (
        generation_closure | analyze_closure | scanner_own_closure
    )
    dead_definitions = definitions.keys() - (
        generation_closure
        | analyze_closure
        | scanner_own_closure
        | passive_frozen_definitions
    )
    assert not dead_definitions, (
        f"top-level definitions escape all audited closures: {sorted(dead_definitions)}"
    )

    initializer_nodes = tuple(
        node
        for node in tree.body
        if not isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.Import,
                ast.ImportFrom,
            ),
        )
    )
    implicit_header_helpers: set[str] = set()
    for definition in definitions.values():
        for nested_definition in ast.walk(definition):
            if not isinstance(
                nested_definition,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ):
                continue
            headers: list[ast.AST] = list(nested_definition.decorator_list)
            if isinstance(nested_definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
                headers.extend(nested_definition.args.defaults)
                headers.extend(
                    default
                    for default in nested_definition.args.kw_defaults
                    if default is not None
                )
            else:
                headers.extend(nested_definition.bases)
                headers.extend(keyword.value for keyword in nested_definition.keywords)
            implicit_header_helpers.update(
                child.id
                for header in headers
                for child in ast.walk(header)
                if isinstance(child, ast.Name)
                and isinstance(child.ctx, ast.Load)
                and child.id in definitions
                and isinstance(
                    definitions[child.id], (ast.FunctionDef, ast.AsyncFunctionDef)
                )
            )
    direct_initializer_helpers = frozenset(
        name
        for node in initializer_nodes
        for child in ast.walk(node)
        if isinstance(child, ast.Name)
        and isinstance(child.ctx, ast.Load)
        and (name := child.id) in definitions
        and isinstance(definitions[name], (ast.FunctionDef, ast.AsyncFunctionDef))
    ) | frozenset(implicit_header_helpers)
    initializer_helpers = (
        _local_definition_closure(direct_initializer_helpers, definitions)
        if direct_initializer_helpers
        else frozenset()
    )
    assert not initializer_helpers, (
        f"module initializer calls arbitrary local helpers: {sorted(initializer_helpers)}"
    )
    assert generation_closure.isdisjoint(initializer_helpers)
    assert analyze_closure.isdisjoint(initializer_helpers)
    assert scanner_total_closure.isdisjoint(initializer_helpers)

    for node in initializer_nodes:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is not None:
                assert not _is_mutable_expression(value), (
                    "module initializer exposes mutable state"
                )
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute):
                assert child.attr not in _REFLECTION_OR_MUTATION_ESCAPES
            if isinstance(child, ast.Call):
                _assert_call_origin_allowed(
                    child,
                    module_origins,
                    frozen_class_mapping_names,
                    scope="initializer",
                    closure=initializer_helpers,
                    definitions=definitions,
                    frozen_classes=frozen_classes,
                    enum_classes=enum_classes,
                    pgp2_certified=pgp2_certified,
                )
                origin = _origin_from_ast(
                    child.func, module_origins, frozen_class_mapping_names
                )
                assert origin[0] not in _SCANNER_ONLY_IMPORT_ROOTS
                assert origin[0] not in _ANALYZE_ONLY_IMPORT_ROOTS
                assert not (
                    origin[0] == "local"
                    and origin[1]
                    in generation_closure | analyze_closure | scanner_total_closure
                    and origin[1] not in frozen_classes | enum_classes
                ), "module initializer reaches an effect closure"

    module_global_names = frozenset(
        set(module_origins) | set(assignment_values) | set(definitions)
    )
    for name in sorted(generation_closure):
        _assert_definition_is_pure(
            definitions[name],
            module_origins,
            frozen_class_mapping_names,
            scope="generation",
            closure=generation_closure,
            definitions=definitions,
            module_global_names=module_global_names,
            frozen_classes=frozen_classes,
            enum_classes=enum_classes,
            pgp2_certified=pgp2_certified,
        )
    for name in sorted(analyze_closure):
        _assert_definition_is_pure(
            definitions[name],
            module_origins,
            frozen_class_mapping_names,
            scope="analyze",
            closure=analyze_closure,
            definitions=definitions,
            module_global_names=module_global_names,
            frozen_classes=frozen_classes,
            enum_classes=enum_classes,
            pgp2_certified=pgp2_certified,
        )
    for name in sorted(scanner_own_closure):
        _assert_definition_is_pure(
            definitions[name],
            module_origins,
            frozen_class_mapping_names,
            scope="scanner",
            closure=scanner_total_closure,
            definitions=definitions,
            module_global_names=module_global_names,
            frozen_classes=frozen_classes,
            enum_classes=enum_classes,
            pgp2_certified=pgp2_certified,
        )
    for name in sorted(passive_frozen_definitions):
        _assert_definition_is_pure(
            definitions[name],
            module_origins,
            frozen_class_mapping_names,
            scope="initializer",
            closure=passive_frozen_definitions,
            definitions=definitions,
            module_global_names=module_global_names,
            frozen_classes=frozen_classes,
            enum_classes=enum_classes,
            pgp2_certified=pgp2_certified,
        )
    return {
        "generation": generation_closure,
        "analyze": analyze_closure,
        "initializer": initializer_helpers,
        "scanner": scanner_total_closure,
    }


def _runtime_state_snapshot(
    value: object,
    *,
    module_name: str,
    generation_classes: frozenset[str],
    seen: frozenset[int] = frozenset(),
) -> object:
    if type(value) is _PGP2_TRUSTED_FUTURE_FEATURE_TYPE:
        return _pgp2_trusted_future_feature_snapshot(value)
    if value is None or isinstance(value, (bool, int, float, complex, str, bytes)):
        return (type(value).__name__, value)
    if isinstance(value, re.Pattern):
        return ("regex", value.pattern, value.flags)
    value_type = type(value)
    if value_type.__module__ == module_name and any(
        base.__module__ == "enum" for base in value_type.__mro__[1:]
    ):
        return (
            "enum_member",
            value_type.__qualname__,
            value.name,
            _runtime_state_snapshot(
                value.value,
                module_name=module_name,
                generation_classes=generation_classes,
                seen=seen,
            ),
        )
    if inspect.ismodule(value):
        return ("external_module", value.__name__)
    if inspect.isfunction(value):
        if value.__module__ != module_name:
            return ("external_function", value.__module__, value.__qualname__)
        assert not value.__dict__, f"function dictionary state: {value.__qualname__}"
        defaults = value.__defaults__ or ()
        kwdefaults = value.__kwdefaults__ or {}
        closure_values = tuple(cell.cell_contents for cell in (value.__closure__ or ()))
        assert not any(callable(item) for item in defaults)
        assert not any(callable(item) for item in kwdefaults.values())
        assert not any(callable(item) for item in closure_values)
        return (
            "local_function",
            value.__qualname__,
            tuple(
                _runtime_state_snapshot(
                    item,
                    module_name=module_name,
                    generation_classes=generation_classes,
                    seen=seen,
                )
                for item in defaults
            ),
            tuple(
                (
                    key,
                    _runtime_state_snapshot(
                        item,
                        module_name=module_name,
                        generation_classes=generation_classes,
                        seen=seen,
                    ),
                )
                for key, item in sorted(kwdefaults.items())
            ),
            tuple(
                _runtime_state_snapshot(
                    item,
                    module_name=module_name,
                    generation_classes=generation_classes,
                    seen=seen,
                )
                for item in closure_values
            ),
        )
    if inspect.isclass(value):
        if value.__module__ != module_name:
            return ("external_class", value.__module__, value.__qualname__)
        is_enum = any(base.__module__ == "enum" for base in value.__mro__[1:])
        assert type(value) is type or is_enum, f"custom metaclass: {value.__qualname__}"
        if value.__name__ in generation_classes:
            is_frozen_dataclass = is_dataclass(value) and (
                value.__dataclass_params__.frozen is True
            )
            assert is_frozen_dataclass or is_enum, (
                f"generation class is stateful: {value.__qualname__}"
            )
        class_state: list[tuple[str, object]] = []
        for name, item in sorted(vars(value).items()):
            if name.startswith("__"):
                continue
            if isinstance(item, (staticmethod, classmethod)):
                item = item.__func__
            if isinstance(item, property):
                accessors = tuple(
                    accessor
                    for accessor in (item.fget, item.fset, item.fdel)
                    if accessor is not None
                )
                class_state.append(
                    (
                        name,
                        tuple(
                            _runtime_state_snapshot(
                                accessor,
                                module_name=module_name,
                                generation_classes=generation_classes,
                                seen=seen,
                            )
                            for accessor in accessors
                        ),
                    )
                )
                continue
            assert not (
                callable(item)
                and not inspect.isfunction(item)
                and not inspect.isclass(item)
            ), f"arbitrary callable class state: {value.__qualname__}.{name}"
            class_state.append(
                (
                    name,
                    _runtime_state_snapshot(
                        item,
                        module_name=module_name,
                        generation_classes=generation_classes,
                        seen=seen,
                    ),
                )
            )
        return ("local_class", value.__qualname__, tuple(class_state))
    if inspect.isbuiltin(value) or inspect.ismethoddescriptor(value):
        return ("builtin", getattr(value, "__qualname__", repr(value)))
    if inspect.isdatadescriptor(value):
        return ("data_descriptor", type(value).__module__, type(value).__qualname__)
    identity = id(value)
    assert identity not in seen, "cyclic Product-owned runtime state"
    nested_seen = seen | {identity}
    if isinstance(value, tuple):
        return (
            "tuple",
            tuple(
                _runtime_state_snapshot(
                    item,
                    module_name=module_name,
                    generation_classes=generation_classes,
                    seen=nested_seen,
                )
                for item in value
            ),
        )
    if isinstance(value, frozenset):
        children = tuple(
            _runtime_state_snapshot(
                item,
                module_name=module_name,
                generation_classes=generation_classes,
                seen=nested_seen,
            )
            for item in value
        )
        return ("frozenset", tuple(sorted(children, key=repr)))
    if isinstance(value, MappingProxyType):
        children = tuple(
            (
                _runtime_state_snapshot(
                    key,
                    module_name=module_name,
                    generation_classes=generation_classes,
                    seen=nested_seen,
                ),
                _runtime_state_snapshot(
                    item,
                    module_name=module_name,
                    generation_classes=generation_classes,
                    seen=nested_seen,
                ),
            )
            for key, item in value.items()
        )
        return ("mapping_proxy", tuple(sorted(children, key=repr)))
    if is_dataclass(value) and not isinstance(value, type):
        assert type(value).__dataclass_params__.frozen is True
        return (
            "frozen_dataclass",
            type(value).__qualname__,
            tuple(
                (
                    field.name,
                    _runtime_state_snapshot(
                        getattr(value, field.name),
                        module_name=module_name,
                        generation_classes=generation_classes,
                        seen=nested_seen,
                    ),
                )
                for field in fields(value)
            ),
        )
    assert not callable(value), f"arbitrary stateful callable: {value!r}"
    raise AssertionError(f"mutable or stateful Product-owned value: {type(value)!r}")


def _module_runtime_state_snapshot(
    module: Any,
    generation_closure: frozenset[str],
) -> tuple[tuple[str, object], ...]:
    generation_classes = frozenset(
        name
        for name in generation_closure
        if inspect.isclass(getattr(module, name, None))
    ) | frozenset(
        item.__name__
        for value in vars(module).values()
        if isinstance(value, MappingProxyType)
        for item in value.values()
        if inspect.isclass(item) and item.__module__ == module.__name__
    )
    state: list[tuple[str, object]] = []
    for name, value in sorted(vars(module).items()):
        if name.startswith("__"):
            continue
        state.append(
            (
                name,
                _runtime_state_snapshot(
                    value,
                    module_name=module.__name__,
                    generation_classes=generation_classes,
                ),
            )
        )
    return tuple(state)


def _expected_node_spec(
    node_id: str,
    kind: str,
    input_contract: str,
    output_contract: str,
    *,
    capability: str | None = None,
    timeout_seconds: int = 60,
    risk_tier: int = 0,
    idempotency: str = "none",
    wait_signal_name: str | None = None,
    wait_correlation_key: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "node_id": node_id,
        "kind": kind,
        "input_contract": input_contract,
        "output_contract": output_contract,
        "capability": capability,
        "timeout_seconds": timeout_seconds,
        "max_attempts": 1,
        "risk_tier": risk_tier,
        "idempotency": idempotency,
        "max_iterations": None,
        "max_concurrency": None,
        "subworkflow_ref": None,
        "failure_edge": None,
        "retry_class": "never",
        "stop_predicate": None,
        "wait_signal_name": wait_signal_name,
        "wait_correlation_key": wait_correlation_key,
    }


EXPECTED_NODE_SPECS = {
    "read_v1": _expected_node_spec(
        "read_v1",
        "tool",
        "contract:lh1a-case-fixture:1",
        "contract:lh1a-workspace-snapshot-v1:1",
        capability="workspace.read",
        idempotency="idempotent",
    ),
    "provider_v1": _expected_node_spec(
        "provider_v1",
        "provider",
        "contract:lh1a-workspace-snapshot-v1:1",
        "contract:lh1a-provider-response-v1:1",
        capability="provider.chat",
        timeout_seconds=120,
        idempotency="idempotent",
    ),
    "wait_change": _expected_node_spec(
        "wait_change",
        "wait_event",
        "contract:lh1a-provider-response-v1:1",
        "contract:lh1a-change-notice:1",
        timeout_seconds=21600,
        wait_signal_name="requirement.changed",
        wait_correlation_key="case:{case_id}:change",
    ),
    "read_v2": _expected_node_spec(
        "read_v2",
        "tool",
        "contract:lh1a-change-notice:1",
        "contract:lh1a-provider-context-v2:1",
        capability="workspace.read",
        idempotency="idempotent",
    ),
    "wait_dependency": _expected_node_spec(
        "wait_dependency",
        "wait_event",
        "contract:lh1a-provider-context-v2:1",
        "contract:lh1a-provider-context-v2:1",
        timeout_seconds=300,
        wait_signal_name="dependency.ready",
        wait_correlation_key="case:{case_id}:dependency",
    ),
    "provider_v2": _expected_node_spec(
        "provider_v2",
        "provider",
        "contract:lh1a-provider-context-v2:1",
        "contract:lh1a-action-proposal-v2:1",
        capability="provider.chat",
        timeout_seconds=120,
        idempotency="idempotent",
    ),
    "wait_release": _expected_node_spec(
        "wait_release",
        "wait_event",
        "contract:lh1a-action-proposal-v2:1",
        "contract:lh1a-action-proposal-v2:1",
        timeout_seconds=300,
        wait_signal_name="release.ready",
        wait_correlation_key="case:{case_id}:release",
    ),
    "approval": _expected_node_spec(
        "approval",
        "approval",
        "contract:lh1a-action-proposal-v2:1",
        "contract:lh1a-approval-decision:1",
        timeout_seconds=600,
        risk_tier=1,
    ),
    "apply": _expected_node_spec(
        "apply",
        "tool",
        "contract:lh1a-approval-decision:1",
        "contract:lh1a-apply-receipt:1",
        capability="workspace.apply_patch",
        timeout_seconds=120,
        risk_tier=1,
        idempotency="compensatable",
    ),
    "test": _expected_node_spec(
        "test",
        "tool",
        "contract:lh1a-apply-receipt:1",
        "contract:lh1a-test-result:1",
        capability="workspace.run_tests",
        timeout_seconds=300,
        idempotency="idempotent",
    ),
    "evaluate": _expected_node_spec(
        "evaluate",
        "evaluation",
        "contract:lh1a-test-result:1",
        "contract:lh1a-episode-score:1",
    ),
    "done": _expected_node_spec(
        "done",
        "terminal",
        "contract:lh1a-episode-score:1",
        "contract:lh1a-terminal-receipt:1",
    ),
}


def _assert_exact_workflow(
    workflow: WorkflowGraph,
    *,
    workflow_id: str,
    version: int,
    max_replans: int,
    node_ids: tuple[str, ...],
) -> None:
    assert workflow.model_dump(mode="json", exclude={"nodes", "edges"}) == {
        "schema_version": "1.0",
        "workflow_id": workflow_id,
        "version": version,
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "created_by": "lh1a-d1e-environment",
        "created_at": "2000-01-01T00:00:00Z",
        "policy_version": "lh1a-d1e-v1",
        "evaluator_refs": ["evaluator:lh1a:1"],
        "max_replans": max_replans,
    }
    assert tuple(node.node_id for node in workflow.nodes) == node_ids
    assert tuple(
        node.model_dump(mode="json", exclude_none=False) for node in workflow.nodes
    ) == tuple(EXPECTED_NODE_SPECS[node_id] for node_id in node_ids)
    assert tuple(
        edge.model_dump(mode="json", exclude_none=False) for edge in workflow.edges
    ) == tuple(
        {
            "schema_version": "1.0",
            "source": source,
            "target": target,
            "condition": None,
        }
        for source, target in zip(node_ids, node_ids[1:])
    )


def _pgp2_single_source_mutation(old: str, new: str) -> str:
    assert REFERENCE_SOURCE.count(old) == 1, old
    return REFERENCE_SOURCE.replace(old, new, 1)


def _assert_forbidden_digest_detector_core(generator: ModuleType) -> None:
    allowed = {
        "canonical_request_row_sha256": "dynamic",
        "canonical_approval_row_sha256": "dynamic",
        "matching_row_sha256": "dynamic",
        "canonical_ledger_head_sha256": "dynamic",
        "git_head_blob_oid": "dynamic",
    }
    forbidden = {
        "mutable_ledger_snapshot_sha256": "forbidden",
        "audit_ledger_file_digest": "forbidden",
        "approval_requests_archive_hash": "forbidden",
        "approvals_whole_file_sha256": "forbidden",
        "handoff_log_digest": "forbidden",
        "messages_file_hash": "forbidden",
        "team_messages_archive_checksum": "forbidden",
        "auditLedgerSha": "forbidden",
    }
    nested = {
        "allowed": allowed,
        "level_one": {
            "level_two": [
                {key: value} for key, value in reversed(tuple(forbidden.items()))
            ]
        },
    }
    assert generator.detect_forbidden_digest_bindings(nested) == tuple(
        sorted(key.lower() for key in forbidden)
    )
    assert generator.detect_forbidden_digest_bindings({"allowed": allowed}) == ()
    assert generator.detect_forbidden_digest_ast(
        'binding = {"approval_requests_archive_hash": dynamic_value}'
    ) == ("approval_requests_archive_hash",)
    assert (
        generator.detect_forbidden_digest_ast(
            'binding = "canonical_request_row_sha256"'
        )
        == ()
    )
    bypass_source = """
MUTABLE_LEDGER_SNAPSHOT_SHA256 = dynamic_value
payload["renamed_messages_file_hash"]
receipt.approvals_whole_file_sha256
getattr(receipt, "handoff_log_digest")
binding = {"approval_requests_archive_hash": dynamic_value}
"""
    assert generator.detect_forbidden_digest_ast(bypass_source) == (
        "approval_requests_archive_hash",
        "approvals_whole_file_sha256",
        "handoff_log_digest",
        "mutable_ledger_snapshot_sha256",
        "renamed_messages_file_hash",
    )


def test_pgp2_reference_certificate_is_independent_closed_and_cardinality_exact() -> (
    None
):
    outer_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    assignments = {
        target.id: index
        for index, node in enumerate(outer_tree.body)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert assignments["REFERENCE_CERTIFICATE"] < assignments["REFERENCE_SOURCE"]
    assert assignments["_PGP2_TRUST_CAPSULE"] < assignments["REFERENCE_SOURCE"]
    assert _pgp2_ast_shape(_PGP2_REFERENCE_TREE) == _PGP2_REFERENCE_SHAPE
    _assert_forbidden_digest_detector_core(_PGP2_REFERENCE_MODULE)
    assert len(REFERENCE_CERTIFICATE["classes"]) == 11
    assert len(REFERENCE_CERTIFICATE["public_signatures"]) == 14
    assert {domain for _, domain in REFERENCE_CERTIFICATE["private_effects"]} == {
        "GEN",
        "ANALYZE",
        "SCAN",
    }
    assert not any(
        key in REFERENCE_CERTIFICATE
        for key in (
            "acceptance_digest",
            "ast_sha256",
            "candidate_sha256",
            "file_sha256",
            "source_sha256",
        )
    )
    first = _PGP2_REFERENCE_MODULE.generate_cases(b"a" * 32)
    second = _PGP2_REFERENCE_MODULE.generate_cases(b"b" * 32)
    validator = next(
        case.declaration for case in first if case.coordinate.family == "validator"
    )
    assert _PGP2_REFERENCE_MODULE.reference_result(validator.family_spec, "v1") is False
    assert _PGP2_REFERENCE_MODULE.reference_result(validator.family_spec, "v2") is True
    assert _PGP2_REFERENCE_MODULE.validate_fixture_lineage(validator) == ()
    assert len(first) == len(second) == 6 * 3 * 3 * 4 * 2 == 432
    assert len({case.case_id for case in first}) == 432
    assert len({case.case_seed for case in first}) == 432
    assert tuple(case.coordinate for case in first) == tuple(
        case.coordinate for case in second
    )
    assert all(
        left.case_id != right.case_id and left.case_seed != right.case_seed
        for left, right in zip(first, second)
    )
    exact_spec_types = tuple(_PGP2_REFERENCE_MODULE.FAMILY_SPEC_TYPES.values())
    validator_total = 0
    for generated in (first, second):
        declarations = tuple(case.declaration for case in generated)
        assert _PGP2_REFERENCE_MODULE.semantic_uniqueness_violations(declarations) == ()
        assert len({case.declaration.fixture_id for case in generated}) == 432
        assert len({case.declaration.fixture_prefix for case in generated}) == 432
        family_specs = tuple(case.declaration.family_spec for case in generated)
        assert all(
            any(type(family_spec) is spec_type for spec_type in exact_spec_types)
            for family_spec in family_specs
        )
        for index, family_spec in enumerate(family_specs):
            assert all(
                type(family_spec) is not type(previous) or family_spec != previous
                for previous in family_specs[:index]
            )
        root_validator_v1_values: set[str] = set()
        root_validator_count = 0
        for generated_case in generated:
            declaration = generated_case.declaration
            family = generated_case.coordinate.family
            family_spec = declaration.family_spec
            independent_v1 = _independent_family_oracle(family, family_spec, "v1")
            independent_v2 = _independent_family_oracle(family, family_spec, "v2")
            reference_v1 = _PGP2_REFERENCE_MODULE.reference_result(family_spec, "v1")
            reference_v2 = _PGP2_REFERENCE_MODULE.reference_result(family_spec, "v2")
            assert reference_v1 == independent_v1
            assert reference_v2 == independent_v2
            derived = _PGP2_REFERENCE_MODULE.derive_family_artifacts(family_spec)
            expected_artifacts = {
                "fixture": {
                    "family": family,
                    "v1": independent_v1,
                    "v2": independent_v2,
                },
                "requirement_v1": "produce:" + repr(independent_v1),
                "requirement_v2": "produce:" + repr(independent_v2),
                "initial_content": independent_v1,
                "final_content": independent_v2,
                "test": "assert result == " + repr(independent_v2),
                "prompt": "produce:" + repr(independent_v2),
                "expected_result": independent_v2,
                "provider_response": {"result": independent_v2},
            }
            assert tuple(expected_artifacts) == SEMANTIC_CHANNELS
            for channel, expected_value in expected_artifacts.items():
                assert getattr(derived, channel) == expected_value
                assert getattr(declaration, channel) == expected_value
            assert _PGP2_REFERENCE_MODULE.validate_family_semantics(declaration) == ()
            assert _PGP2_REFERENCE_MODULE.validate_fixture_lineage(declaration) == ()
            if family == "validator":
                root_validator_count += 1
                validator_total += 1
                assert type(family_spec) is _PGP2_REFERENCE_MODULE.ValidatorSpec
                assert re.fullmatch(r"validator-[0-9a-f]{64}", declaration.case_id)
                assert family_spec.value_v1.startswith("agent-validator-")
                assert not any(
                    character.isdigit() for character in family_spec.value_v1
                )
                assert family_spec.value_v2 == family_spec.value_v1 + "-7"
                assert reference_v1 is False
                assert reference_v2 is True
                root_validator_v1_values.add(family_spec.value_v1)
        assert root_validator_count == 72
        assert len(root_validator_v1_values) == 72
    assert validator_total == 144
    predecessor_raw_case_id = "validator-" + ("0" * 64)
    predecessor_validator_spec = _PGP2_REFERENCE_MODULE.ValidatorSpec(
        predecessor_raw_case_id,
        predecessor_raw_case_id + "-7",
        "contains_digit",
    )
    assert (
        _PGP2_REFERENCE_MODULE.reference_result(predecessor_validator_spec, "v1")
        is True
    )
    assert (
        _PGP2_REFERENCE_MODULE.reference_result(predecessor_validator_spec, "v2")
        is True
    )
    assert all(
        type(left.declaration.family_spec) is type(right.declaration.family_spec)
        and left.declaration.family_spec != right.declaration.family_spec
        and left.declaration.fixture_id != right.declaration.fixture_id
        and left.declaration.fixture_prefix != right.declaration.fixture_prefix
        for left, right in zip(first, second)
    )
    left = first[0].declaration
    right = first[1].declaration
    duplicate_case_id = replace(right, case_id=left.case_id)
    duplicate_family_spec = replace(right, family_spec=left.family_spec)
    duplicate_fixture_id = replace(right, fixture_id=left.fixture_id)
    duplicate_fixture_prefix = replace(right, fixture_prefix=left.fixture_prefix)
    detector = _PGP2_REFERENCE_MODULE.semantic_uniqueness_violations
    assert detector((left, duplicate_case_id)) == ("DUPLICATE_CASE_ID",)
    assert detector((left, duplicate_family_spec)) == ("DUPLICATE_FAMILY_SPEC",)
    assert detector((left, duplicate_fixture_id)) == ("DUPLICATE_FIXTURE_ID",)
    assert detector((left, duplicate_fixture_prefix)) == ("DUPLICATE_FIXTURE_PREFIX",)
    assert detector((left, left)) == (
        "DUPLICATE_CASE_ID",
        "DUPLICATE_FAMILY_SPEC",
        "DUPLICATE_FIXTURE_ID",
        "DUPLICATE_FIXTURE_PREFIX",
    )
    assert duplicate_family_spec.case_id != left.case_id
    assert duplicate_family_spec.fixture_id != left.fixture_id
    assert duplicate_family_spec.fixture_prefix != left.fixture_prefix


@pytest.mark.parametrize(
    ("label", "old", "new", "expected_code"),
    (
        (
            "poisoned_import_binding",
            "from pathlib import Path\n",
            "from pathlib import Path as Path\n",
            "PGP2_M_IMPORT_SET",
        ),
        (
            "extra_import_member",
            "from pathlib import Path\n",
            "from pathlib import Path, PurePath\n",
            "PGP2_M_IMPORT_SET",
        ),
        (
            "frozen_record_callback_field",
            "class StringTransformSpec:\n    text_v1: str\n    text_v2: str\n    operation: str\n",
            "class StringTransformSpec:\n    text_v1: str\n    text_v2: str\n    operation: str\n    callback: object\n",
            "PGP2_D_FIELD_SCHEMA",
        ),
        (
            "record_default",
            "class StringTransformSpec:\n    text_v1: str\n",
            "class StringTransformSpec:\n    text_v1: str = []\n",
            "PGP2_D_CLASS_SHAPE",
        ),
        (
            "record_default_factory",
            "class StringTransformSpec:\n    text_v1: str\n",
            "class StringTransformSpec:\n    text_v1: str = field(default_factory=tuple)\n",
            "PGP2_D_CLASS_SHAPE",
        ),
        (
            "record_property",
            "class StringTransformSpec:\n    text_v1: str\n",
            "class StringTransformSpec:\n    @property\n    def callback(self):\n        return self.text_v1\n    text_v1: str\n",
            "PGP2_D_CLASS_SHAPE",
        ),
        (
            "record_method_descriptor",
            "class StringTransformSpec:\n    text_v1: str\n",
            "class StringTransformSpec:\n    def callback(self):\n        return self.text_v1\n    text_v1: str\n",
            "PGP2_D_CLASS_SHAPE",
        ),
        (
            "record_base",
            "class StringTransformSpec:\n",
            "class StringTransformSpec(object):\n",
            "PGP2_D_CLASS_SHAPE",
        ),
        (
            "record_metaclass",
            "class StringTransformSpec:\n",
            "class StringTransformSpec(metaclass=type):\n",
            "PGP2_D_CLASS_SHAPE",
        ),
        (
            "record_class_cache",
            "class StringTransformSpec:\n    text_v1: str\n",
            "class StringTransformSpec:\n    cache: tuple[str, ...] = ()\n    text_v1: str\n",
            "PGP2_D_CLASS_SHAPE",
        ),
        (
            "list_comprehension",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    leaked = [item for item in ()]\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_BODY_SCHEMA",
        ),
        (
            "set_comprehension",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    leaked = {item for item in ()}\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_BODY_SCHEMA",
        ),
        (
            "dict_comprehension",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    leaked = {item: item for item in ()}\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_BODY_SCHEMA",
        ),
        (
            "generator_expression",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    leaked = (item for item in ())\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_BODY_SCHEMA",
        ),
        (
            "match_case",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    match root_seed:\n        case _:\n            pass\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_BODY_SCHEMA",
        ),
        (
            "nested_definition",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    def nested():\n        return root_seed\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_BODY_SCHEMA",
        ),
        (
            "async_definition",
            "def _pgp2_generate_cases(root_seed):\n",
            "async def _pgp2_generate_cases(root_seed):\n",
            "PGP2_F_FUNCTION_SET",
        ),
        (
            "yield",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    leaked = (yield root_seed)\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_BODY_SCHEMA",
        ),
        (
            "lambda",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    leaked = lambda value: value\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_BODY_SCHEMA",
        ),
        (
            "dynamic_type",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            'def _pgp2_generate_cases(root_seed):\n    leaked = type("Box", (), {"state": []})\n    if type(root_seed) is not bytes:\n',
            "PGP2_F_CALL_SCHEMA",
        ),
        (
            "callable_parameter",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed, callback):\n    callback(root_seed)\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_CALL_SCHEMA",
        ),
        (
            "annotated_callable_parameter",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed, callback: object):\n    callback(root_seed)\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_CALL_SCHEMA",
        ),
        (
            "assigned_callable_alias",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    callback = len\n    callback(root_seed)\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_CALL_SCHEMA",
        ),
        (
            "subscript_dispatch",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            'def _pgp2_generate_cases(root_seed):\n    {"callback": len}["callback"](root_seed)\n    if type(root_seed) is not bytes:\n',
            "PGP2_F_CALL_SCHEMA",
        ),
        (
            "return_value_dispatch",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    str.upper()(root_seed)\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_CALL_SCHEMA",
        ),
        (
            "map_callback",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    map(str, ())\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_CALL_SCHEMA",
        ),
        (
            "filter_callback",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    filter(str, ())\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_CALL_SCHEMA",
        ),
        (
            "sorted_key_callback",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    sorted((), key=str)\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_CALL_SCHEMA",
        ),
        (
            "json_callback",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    dumps({}, default=str)\n    if type(root_seed) is not bytes:\n",
            "PGP2_F_CALL_SCHEMA",
        ),
        (
            "regex_callback_import",
            "from pathlib import Path\n",
            "from pathlib import Path\nfrom re import sub\n",
            "PGP2_M_IMPORT_SET",
        ),
        (
            "function_attribute_cache",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            "def _pgp2_generate_cases(root_seed):\n    generate_cases.cache = {}\n    if type(root_seed) is not bytes:\n",
            "PGP2_M_AST_MISMATCH",
        ),
        (
            "module_bound_list_mutator",
            "\n\ndef _pgp2_require_json_tree(value):\n",
            "\nBOUND_MUTATOR = [].append\n\ndef _pgp2_require_json_tree(value):\n",
            "PGP2_D_CONST_SCHEMA",
        ),
        (
            "module_bound_hash_updater",
            "\n\ndef _pgp2_require_json_tree(value):\n",
            "\nBOUND_UPDATER = sha256().update\n\ndef _pgp2_require_json_tree(value):\n",
            "PGP2_D_CONST_SCHEMA",
        ),
        (
            "spoofed_external_identity",
            "def _pgp2_generate_cases(root_seed):\n    if type(root_seed) is not bytes:\n",
            'def _pgp2_generate_cases(root_seed):\n    leaked = type("Box", (), {"__module__": "pathlib", "state": []})\n    if type(root_seed) is not bytes:\n',
            "PGP2_F_CALL_SCHEMA",
        ),
        (
            "scanner_write",
            "def _pgp2_scan(roots):\n    if type(roots) is not tuple:\n",
            'def _pgp2_scan(roots):\n    Path("escape").touch()\n    if type(roots) is not tuple:\n',
            "PGP2_F_CALL_SCHEMA",
        ),
        (
            "private_vararg",
            "def _pgp2_generate_cases(root_seed):\n",
            "def _pgp2_generate_cases(root_seed, *args):\n",
            "PGP2_F_VARARG",
        ),
        (
            "private_kwargs",
            "def _pgp2_generate_cases(root_seed):\n",
            "def _pgp2_generate_cases(root_seed, **kwargs):\n",
            "PGP2_F_VARARG",
        ),
        (
            "call_expansion",
            "def _pgp2_scan(roots):\n    if type(roots) is not tuple:\n",
            "def _pgp2_scan(roots):\n    tuple(*roots)\n    if type(roots) is not tuple:\n",
            "PGP2_F_CALL_SCHEMA",
        ),
        (
            "forbidden_effect_edge",
            "def generate_cases(root_seed):\n    return _pgp2_generate_cases(root_seed)\n",
            "def generate_cases(root_seed):\n    return _pgp2_detect_forbidden_bindings(root_seed)\n",
            "PGP2_F_EFFECT_EDGE",
        ),
    ),
)
def test_pgp2_full_reference_source_mutations_fail_with_stable_codes(
    label: str,
    old: str,
    new: str,
    expected_code: str,
) -> None:
    mutated = _pgp2_single_source_mutation(old, new)
    with pytest.raises(PGP2Violation) as error:
        _validate_pgp2_source(mutated)
    assert error.value.code == expected_code, label


def test_pgp2_runtime_mutations_fail_closed_before_cached_return() -> None:
    assert _PGP2_REFERENCE_MODULE.detect_forbidden_digest_ast(
        'binding = {"approval_requests_archive_hash": dynamic_value}'
    ) == ("approval_requests_archive_hash",)
    mutations = (
        ("import", "PGP2_R_EXTERNAL_IDENTITY"),
        ("function", "PGP2_R_DEFINITION_STATE"),
        ("class", "PGP2_R_DEFINITION_STATE"),
        ("global", "PGP2_R_GLOBAL_STATE"),
        ("bound", "PGP2_R_BOUND_OWNER"),
        ("namespace", "PGP2_R_NAMESPACE_DRIFT"),
    )
    for index, (kind, expected_code) in enumerate(mutations):
        module = _execute_pgp2_source(
            REFERENCE_SOURCE,
            source_path=f"<pgp2-runtime-{index}>",
            module_name=f"_d1e_pgp2_runtime_{index}",
            capsule=_PGP2_TRUST_CAPSULE,
        )
        if kind == "import":
            module.Path = object
        elif kind == "function":
            module.generate_cases.cache = []
        elif kind == "class":
            module.CaseCoordinate.cache = ()
        elif kind == "global":
            module.TASK_FAMILIES = ("mutated",)
        elif kind == "bound":
            owner: list[object] = []
            module.FAMILY_IR = owner.append
        else:
            module.EXTRA_NAMESPACE = "forbidden"
        with pytest.raises(PGP2Violation) as error:
            _validate_pgp2_runtime(
                module,
                capsule=_PGP2_TRUST_CAPSULE,
                reference_state=_PGP2_REFERENCE_RUNTIME_STATE,
            )
        assert error.value.code == expected_code, kind


def test_pgp2_finite_environment_negative_controls_execute_no_poison() -> None:
    expected_future_snapshot = (
        "trusted_future_feature",
        (
            (
                "optional",
                (
                    "tuple",
                    (
                        ("int", 3),
                        ("int", 7),
                        ("int", 0),
                        ("str", "beta"),
                        ("int", 1),
                    ),
                ),
            ),
            ("mandatory", ("NoneType", None)),
            ("compiler_flag", ("int", 16777216)),
        ),
    )
    assert expected_future_snapshot == _PGP2_TRUSTED_FUTURE_FEATURE_SNAPSHOT
    assert (
        _runtime_state_snapshot(
            _PGP2_TRUST_CAPSULE.external_objects["__future__.annotations"],
            module_name="_pgp2_future_control",
            generation_classes=frozenset(),
        )
        == expected_future_snapshot
    )
    side_effects = {"count": 0}

    def poison(*args: object, **kwargs: object) -> object:
        del args, kwargs
        side_effects["count"] += 1
        raise AssertionError("poison executed")

    def rejected(capsule: SimpleNamespace, label: str) -> None:
        with pytest.raises(PGP2Violation) as error:
            _execute_pgp2_source(
                REFERENCE_SOURCE,
                source_path=f"<pgp2-environment-{label}>",
                module_name="_d1e_pgp2_environment_probe",
                capsule=capsule,
            )
        assert error.value.code == "PGP2_R_ENVIRONMENT_DRIFT", label
        assert side_effects["count"] == 0, label

    def future_snapshot(value: object) -> object:
        return _runtime_state_snapshot(
            value,
            module_name="_pgp2_future_control",
            generation_classes=frozenset(),
        )

    def future_module_snapshot(value: object) -> tuple[tuple[str, object], ...]:
        synthetic_module = SimpleNamespace(
            __name__="_pgp2_future_synthetic",
            annotations=value,
        )
        return _module_runtime_state_snapshot(synthetic_module, frozenset())

    def reject_direct_and_synthetic(value: object, label: str) -> None:
        with pytest.raises(AssertionError):
            future_snapshot(value)
        with pytest.raises(AssertionError):
            future_module_snapshot(value)
        assert label

    trusted_future = _PGP2_TRUSTED_FUTURE_ANNOTATIONS
    future_clone = _PGP2_TRUSTED_FUTURE_FEATURE_TYPE(
        (3, 7, 0, "beta", 1),
        None,
        16777216,
    )
    reject_direct_and_synthetic(future_clone, "same-state-different-identity")

    clone_capsule = _build_pgp2_trust_capsule()
    clone_capsule.external_objects = dict(clone_capsule.external_objects)
    clone_capsule.import_facades = dict(clone_capsule.import_facades)
    clone_capsule.import_facades["__future__"] = SimpleNamespace(
        **vars(clone_capsule.import_facades["__future__"])
    )
    clone_capsule.external_objects["__future__.annotations"] = future_clone
    clone_capsule.import_facades["__future__"].annotations = future_clone
    rejected(clone_capsule, "future-self-consistent-clone")

    future_module = importlib.import_module("__future__")
    reject_direct_and_synthetic(future_module.barry_as_FLUFL, "barry-as-flufl")
    matching_fields = SimpleNamespace(
        optional=(3, 7, 0, "beta", 1),
        mandatory=None,
        compiler_flag=16777216,
    )
    reject_direct_and_synthetic(matching_fields, "matching-fields-custom-object")

    original_future_state = dict(vars(trusted_future))
    original_future_type_identity = (
        _PGP2_TRUSTED_FUTURE_FEATURE_TYPE.__module__,
        _PGP2_TRUSTED_FUTURE_FEATURE_TYPE.__name__,
        _PGP2_TRUSTED_FUTURE_FEATURE_TYPE.__qualname__,
    )

    def assert_restored_future_baseline() -> None:
        _attest_pgp2_environment(_PGP2_TRUST_CAPSULE)
        assert future_snapshot(trusted_future) == expected_future_snapshot
        assert future_module_snapshot(trusted_future) == (
            ("annotations", expected_future_snapshot),
        )

    for mutation in (
        "extra-key",
        "missing-optional",
        "bool-for-int-optional",
        "compiler-flag",
        "type-module",
        "type-name",
        "type-qualname",
    ):
        try:
            if mutation == "extra-key":
                vars(trusted_future)["extra"] = "x"
            elif mutation == "missing-optional":
                vars(trusted_future).pop("optional")
            elif mutation == "bool-for-int-optional":
                trusted_future.optional = (3, 7, 0, "beta", True)
            elif mutation == "compiler-flag":
                trusted_future.compiler_flag = 16777217
            elif mutation == "type-module":
                _PGP2_TRUSTED_FUTURE_FEATURE_TYPE.__module__ = "spoofed_future"
            elif mutation == "type-name":
                _PGP2_TRUSTED_FUTURE_FEATURE_TYPE.__name__ = "_SpoofedFeature"
            else:
                _PGP2_TRUSTED_FUTURE_FEATURE_TYPE.__qualname__ = "_SpoofedFeature"
            with pytest.raises(PGP2Violation) as environment_error:
                _attest_pgp2_environment(_PGP2_TRUST_CAPSULE)
            assert environment_error.value.code == "PGP2_R_ENVIRONMENT_DRIFT"
            reject_direct_and_synthetic(trusted_future, mutation)
        finally:
            vars(trusted_future).clear()
            vars(trusted_future).update(original_future_state)
            (
                _PGP2_TRUSTED_FUTURE_FEATURE_TYPE.__module__,
                _PGP2_TRUSTED_FUTURE_FEATURE_TYPE.__name__,
                _PGP2_TRUSTED_FUTURE_FEATURE_TYPE.__qualname__,
            ) = original_future_type_identity
        assert_restored_future_baseline()

    for name in (*REFERENCE_CERTIFICATE["minimal_builtins"], "__import__"):
        capsule = _build_pgp2_trust_capsule()
        original = capsule.minimal_builtins[name]
        capsule.minimal_builtins[name] = poison
        try:
            rejected(capsule, f"builtin-{name}")
        finally:
            capsule.minimal_builtins[name] = original

    for module_name, member_names in REFERENCE_CERTIFICATE["imports"]:
        for member_name in member_names:
            capsule = _build_pgp2_trust_capsule()
            facade = capsule.import_facades[module_name]
            original = getattr(facade, member_name)
            setattr(facade, member_name, poison)
            try:
                rejected(capsule, f"facade-{module_name}-{member_name}")
            finally:
                setattr(facade, member_name, original)

    for qualified_name, _ in REFERENCE_CERTIFICATE["python_external_callables"]:
        capsule = _build_pgp2_trust_capsule()
        function = capsule.external_objects[qualified_name]
        assert inspect.isfunction(function)
        original_dictionary = dict(function.__dict__)
        function.__dict__["_pgp2_poison"] = poison
        try:
            rejected(capsule, f"callable-{qualified_name}")
        finally:
            function.__dict__.clear()
            function.__dict__.update(original_dictionary)

    for qualified_name, helper_names in REFERENCE_CERTIFICATE[
        "python_external_callables"
    ]:
        capsule = _build_pgp2_trust_capsule()
        function = capsule.external_objects[qualified_name]
        if not inspect.isfunction(function):
            continue
        for helper_name in helper_names:
            original = function.__globals__[helper_name]
            function.__globals__[helper_name] = poison
            try:
                rejected(capsule, f"helper-{qualified_name}-{helper_name}")
            finally:
                function.__globals__[helper_name] = original

    capsule = _build_pgp2_trust_capsule()
    original_ascii = builtins.ascii
    builtins.ascii = poison
    try:
        rejected(capsule, "ambient-ascii")
    finally:
        builtins.ascii = original_ascii
    assert side_effects["count"] == 0


def test_pgp2_public_exact_type_guards_execute_no_custom_protocol() -> None:
    callbacks = {"count": 0}

    class BytesBomb(bytes):
        def __len__(self) -> int:
            callbacks["count"] += 1
            return 32

    class StrBomb(str):
        def __eq__(self, other: object) -> bool:
            del other
            callbacks["count"] += 1
            return True

        def __format__(self, spec: str) -> str:
            del spec
            callbacks["count"] += 1
            return "poison"

        def __str__(self) -> str:
            callbacks["count"] += 1
            return "poison"

    class TupleBomb(tuple):
        def __iter__(self):
            callbacks["count"] += 1
            return super().__iter__()

    class DictBomb(dict):
        def items(self):
            callbacks["count"] += 1
            return super().items()

    class PathLikeBomb:
        def __fspath__(self) -> str:
            callbacks["count"] += 1
            return "poison"

    module = _PGP2_REFERENCE_MODULE
    coordinate = module.CaseCoordinate(
        StrBomb(FAMILIES[0]),
        REGIMES[0],
        FAILURES[0],
        "W0",
        0,
    )
    for function, arguments in (
        (module.generate_cases, (BytesBomb(b"x" * 32),)),
        (module.derive_case_seed, (b"x" * 32, coordinate)),
        (module.normalized_semantic_bytes, (StrBomb("fixture"), {})),
        (module.canonical_length_delimited_json, (DictBomb(),)),
        (module.semantic_uniqueness_violations, (TupleBomb(),)),
        (module.scan_forbidden_pre_d1_artifacts, (PathLikeBomb(),)),
    ):
        with pytest.raises(TypeError):
            function(*arguments)
    assert callbacks["count"] == 0


def test_pgp2_loader_revalidates_exact_source_cache_and_runtime(
    tmp_path: Path,
) -> None:
    expected_dual_tests = (
        "test_ephemeral_generator_is_pure_deterministic_and_domain_separated",
        "test_generation_scanner_and_initializer_closures_are_fail_closed_and_stable",
        "test_six_families_have_distinct_typed_semantics_and_reference_oracles",
        "test_williams_orders_balance_positions_and_all_directed_adjacencies",
        "test_declaration_uniqueness_and_semantic_normalization_are_frozen",
        "test_forbidden_pre_d1_artifact_scan_is_recursive_across_arbitrary_roots",
    )
    expected_product_only_tests = {
        "test_population_is_a_closed_summary_and_does_not_embed_cases",
        "test_failure_declarations_are_exact_and_population_balanced",
        "test_d1e_manifest_is_immutable_environment_only_and_not_combined_d1",
        "test_manifest_declares_live_runtime_source_shape_and_public_semantics",
        "test_whole_ledger_digest_detection_is_recursive_generic_and_ast_aware",
    }
    assert REFERENCE_DUAL_EXECUTION_TESTS == expected_dual_tests
    assert len(REFERENCE_DUAL_EXECUTION_TESTS) == 6
    assert len(expected_product_only_tests) == 5
    outer_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    outer_functions = {
        node.name: node
        for node in outer_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    subject_fixture = outer_functions["generator_subject"]
    assert tuple(argument.arg for argument in subject_fixture.args.args) == ("request",)
    assert subject_fixture.args.posonlyargs == []
    assert subject_fixture.args.kwonlyargs == []
    assert subject_fixture.args.vararg is None
    assert subject_fixture.args.kwarg is None
    assert len(subject_fixture.decorator_list) == 1
    fixture_decorator = subject_fixture.decorator_list[0]
    assert isinstance(fixture_decorator, ast.Call)
    assert isinstance(fixture_decorator.func, ast.Attribute)
    assert isinstance(fixture_decorator.func.value, ast.Name)
    assert fixture_decorator.func.value.id == "pytest"
    assert fixture_decorator.func.attr == "fixture"
    assert fixture_decorator.args == []
    assert {
        keyword.arg: ast.literal_eval(keyword.value)
        for keyword in fixture_decorator.keywords
    } == {
        "params": ("reference", "product"),
        "ids": ("reference", "product"),
    }

    def direct_generator_load_count(function: ast.AST) -> int:
        return sum(
            1
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_module"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "generator"
        )

    def module_loads(function: ast.AST) -> tuple[str, ...]:
        return tuple(
            node.args[0].value
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_module"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        )

    direct_generator_loader_owners = {
        name
        for name, function in outer_functions.items()
        if direct_generator_load_count(function)
    }
    assert direct_generator_loader_owners == {
        "generator_subject",
        *expected_product_only_tests,
    }
    assert direct_generator_load_count(subject_fixture) == 1
    assert all(
        direct_generator_load_count(outer_functions[test_name]) == 1
        for test_name in expected_product_only_tests
    )
    for test_name in expected_dual_tests:
        function = outer_functions[test_name]
        argument_names = tuple(argument.arg for argument in function.args.args)
        assert "generator_subject" in argument_names
        subject_unpacking = tuple(
            node
            for node in function.body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Name)
            and node.value.id == "generator_subject"
        )
        assert len(subject_unpacking) == 1
        subject_assignment = subject_unpacking[0]
        assert len(subject_assignment.targets) == 1
        subject_target = subject_assignment.targets[0]
        assert isinstance(subject_target, ast.Tuple)
        assert len(subject_target.elts) == 2
        assert all(isinstance(element, ast.Name) for element in subject_target.elts)
        assert tuple(
            element.id
            for element in subject_target.elts
            if isinstance(element, ast.Name)
        ) in {("generator", "source"), ("generator", "_source")}
        assert (
            sum(
                1
                for node in ast.walk(function)
                if isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id == "generator_subject"
            )
            == 1
        )
        assert direct_generator_load_count(function) == 0
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "inspect"
            and node.func.attr == "getsource"
            for node in ast.walk(function)
        )

    population = outer_functions[
        "test_population_is_a_closed_summary_and_does_not_embed_cases"
    ]
    failure_declarations = outer_functions[
        "test_failure_declarations_are_exact_and_population_balanced"
    ]
    immutable_manifest = outer_functions[
        "test_d1e_manifest_is_immutable_environment_only_and_not_combined_d1"
    ]
    runtime_manifest = outer_functions[
        "test_manifest_declares_live_runtime_source_shape_and_public_semantics"
    ]
    whole_ledger = outer_functions[
        "test_whole_ledger_digest_detection_is_recursive_generic_and_ast_aware"
    ]
    assert set(module_loads(population)) == {"generator", "regimes"}
    assert set(module_loads(failure_declarations)) == {"generator", "regimes"}
    immutable_names = {
        node.id
        for node in ast.walk(immutable_manifest)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    assert set(module_loads(immutable_manifest)) == {
        "generator",
        "regimes",
        "templates",
        "statistics",
    }
    assert "MANIFEST_PATH" in immutable_names
    runtime_names = {
        node.id
        for node in ast.walk(runtime_manifest)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    assert set(module_loads(runtime_manifest)) == {"generator"}
    assert {"MANIFEST_PATH", "RUNTIME_SOURCE_PATHS"} <= runtime_names
    whole_ledger_names = {
        node.id
        for node in ast.walk(whole_ledger)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    assert set(module_loads(whole_ledger)) == {"generator"}
    assert {"MODULE_NAMES", "D1E_ROOT"} <= whole_ledger_names
    source_path = (tmp_path / "generator.py").resolve()
    source_path.write_text(REFERENCE_SOURCE, encoding="utf-8")
    cache: dict[str, object] = {}
    first = _load_pgp2_path(
        source_path,
        module_name="_d1e_pgp2_cache_probe",
        capsule=_PGP2_TRUST_CAPSULE,
        cache=cache,
    )
    second = _load_pgp2_path(
        source_path,
        module_name="_d1e_pgp2_cache_probe",
        capsule=_PGP2_TRUST_CAPSULE,
        cache=cache,
    )
    assert second is first

    source_path.write_text(REFERENCE_SOURCE + "\n# source drift\n", encoding="utf-8")
    with pytest.raises(PGP2Violation) as source_error:
        _load_pgp2_path(
            source_path,
            module_name="_d1e_pgp2_cache_probe",
            capsule=_PGP2_TRUST_CAPSULE,
            cache=cache,
        )
    assert source_error.value.code == "PGP2_R_SOURCE_IDENTITY"
    assert cache == {}

    source_path.write_text(REFERENCE_SOURCE, encoding="utf-8")
    reloaded = _load_pgp2_path(
        source_path,
        module_name="_d1e_pgp2_cache_probe",
        capsule=_PGP2_TRUST_CAPSULE,
        cache=cache,
    )
    reloaded.generate_cases.cache = []
    with pytest.raises(PGP2Violation) as runtime_error:
        _load_pgp2_path(
            source_path,
            module_name="_d1e_pgp2_cache_probe",
            capsule=_PGP2_TRUST_CAPSULE,
            cache=cache,
        )
    assert runtime_error.value.code == "PGP2_R_DEFINITION_STATE"
    assert cache == {}

    side_effects = {"count": 0}

    class PoisonedModule(ModuleType):
        def __getattribute__(self, name: str) -> object:
            if name not in {"__class__", "__dict__"}:
                side_effects["count"] += 1
            return super().__getattribute__(name)

    poisoned_name = "_d1e_pgp2_poisoned_prior"
    poisoned = PoisonedModule(poisoned_name)
    sys.modules[poisoned_name] = poisoned
    try:
        loaded = _execute_pgp2_source(
            REFERENCE_SOURCE,
            source_path="<pgp2-poisoned-module>",
            module_name=poisoned_name,
            capsule=_PGP2_TRUST_CAPSULE,
        )
        assert isinstance(loaded, ModuleType)
        assert sys.modules[poisoned_name] is poisoned
        assert side_effects["count"] == 0
    finally:
        del sys.modules[poisoned_name]


def test_population_is_a_closed_summary_and_does_not_embed_cases() -> None:
    generator = _module("generator")
    regimes = _module("regimes")

    assert generator.TASK_FAMILIES == FAMILIES
    assert regimes.FAILURE_MODES == FAILURES
    assert generator.WILLIAMS_ORDERS == WILLIAMS_ORDERS
    design = generator.POPULATION_DESIGN
    assert is_dataclass(design)
    assert tuple(field.name for field in fields(design)) == (
        "families",
        "regimes",
        "failures",
        "latin_orders",
        "replicates",
        "instances_per_family_regime_failure_order_cell",
        "instances_per_family_regime_failure_cell",
        "instance_count",
        "arms_per_instance",
        "episode_count",
        "instances_per_family",
        "instances_per_regime",
        "instances_per_failure",
        "instances_per_latin_order",
        "instances_per_replicate",
    )
    assert design.families == FAMILIES
    assert design.regimes == REGIMES
    assert design.failures == FAILURES
    assert design.latin_orders == tuple(WILLIAMS_ORDERS)
    assert design.replicates == (0, 1)
    assert design.instances_per_family_regime_failure_order_cell == 2
    assert design.instances_per_family_regime_failure_cell == 8
    assert design.instance_count == 432
    assert design.arms_per_instance == 4
    assert design.episode_count == 1728
    assert design.instances_per_family == 72
    assert design.instances_per_regime == 144
    assert design.instances_per_failure == 144
    assert design.instances_per_latin_order == 108
    assert design.instances_per_replicate == 216
    assert not hasattr(generator, "assignments")


def test_ephemeral_generator_is_pure_deterministic_and_domain_separated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    generator_subject: tuple[ModuleType, str],
) -> None:
    generator, _source = generator_subject
    for function_name, parameter_names in {
        "derive_case_seed": ("root_seed", "coordinate"),
        "generate_case": ("root_seed", "coordinate"),
        "generate_cases": ("root_seed",),
    }.items():
        signature = inspect.signature(getattr(generator, function_name))
        assert tuple(signature.parameters) == parameter_names
        assert all(
            parameter.default is inspect.Parameter.empty
            for parameter in signature.parameters.values()
        )
    assert is_dataclass(generator.CaseCoordinate)
    assert tuple(field.name for field in fields(generator.CaseCoordinate)) == (
        "family",
        "regime",
        "failure",
        "latin_order",
        "replicate",
    )
    assert is_dataclass(generator.GeneratedCase)
    assert tuple(field.name for field in fields(generator.GeneratedCase)) == (
        "coordinate",
        "case_id",
        "case_seed",
        "declaration",
    )

    coordinate = generator.CaseCoordinate(
        family=FAMILIES[0],
        regime=REGIMES[0],
        failure=FAILURES[0],
        latin_order="W0",
        replicate=0,
    )
    coordinate_payload = {
        "failure": FAILURES[0],
        "family": FAMILIES[0],
        "latin_order": "W0",
        "regime": REGIMES[0],
        "replicate": 0,
    }
    canonical = _canonical_length_delimited_json(coordinate_payload)
    assert generator.canonical_length_delimited_json(coordinate_payload) == canonical
    assert canonical[:8] == (len(canonical) - 8).to_bytes(8, byteorder="big")
    expected_seed = hmac.new(
        EPHEMERAL_TEST_KEY,
        canonical,
        hashlib.sha256,
    ).digest()
    assert generator.derive_case_seed(EPHEMERAL_TEST_KEY, coordinate) == expected_seed
    assert len(expected_seed) == 32
    with pytest.raises(TypeError):
        generator.canonical_length_delimited_json(["not", "a", "mapping"])
    for nonfinite in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            generator.canonical_length_delimited_json({"value": nonfinite})
    invalid_root_seeds = (
        "not-bytes",
        bytearray(EPHEMERAL_TEST_KEY),
        True,
        b"too-short",
        b"x" * 31,
        b"x" * 33,
    )
    for invalid_root_seed in invalid_root_seeds:
        for function, arguments in (
            (generator.derive_case_seed, (invalid_root_seed, coordinate)),
            (generator.generate_case, (invalid_root_seed, coordinate)),
            (generator.generate_cases, (invalid_root_seed,)),
        ):
            with pytest.raises((TypeError, ValueError)):
                function(*arguments)
    assert (
        generator.derive_case_seed(SECOND_EPHEMERAL_TEST_KEY, coordinate)
        != expected_seed
    )
    coordinate_mutations = (
        replace(coordinate, family=FAMILIES[1]),
        replace(coordinate, regime=REGIMES[1]),
        replace(coordinate, failure=FAILURES[1]),
        replace(coordinate, latin_order="W1"),
        replace(coordinate, replicate=1),
    )
    assert all(
        generator.derive_case_seed(EPHEMERAL_TEST_KEY, mutation) != expected_seed
        for mutation in coordinate_mutations
    )
    invalid_coordinates = (
        replace(coordinate, family="undeclared_family"),
        replace(coordinate, regime="undeclared_regime"),
        replace(coordinate, failure="undeclared_failure"),
        replace(coordinate, latin_order="W9"),
        replace(coordinate, replicate=2),
    )
    for invalid in invalid_coordinates:
        with pytest.raises(ValueError):
            generator.derive_case_seed(EPHEMERAL_TEST_KEY, invalid)

    monkeypatch.chdir(tmp_path)
    before = tuple(tmp_path.rglob("*"))
    first = generator.generate_cases(EPHEMERAL_TEST_KEY)
    second = generator.generate_cases(EPHEMERAL_TEST_KEY)
    other_root = generator.generate_cases(SECOND_EPHEMERAL_TEST_KEY)
    after = tuple(tmp_path.rglob("*"))
    assert before == after == ()
    assert first == second
    assert tuple(case.coordinate for case in first) == tuple(
        case.coordinate for case in other_root
    )
    assert isinstance(first, tuple)
    assert isinstance(other_root, tuple)
    assert len(first) == len(other_root) == 432
    assert all(
        isinstance(case, generator.GeneratedCase)
        for cases in (first, other_root)
        for case in cases
    )
    for root_seed, generated_cases in (
        (EPHEMERAL_TEST_KEY, first),
        (SECOND_EPHEMERAL_TEST_KEY, other_root),
    ):
        for generated_case in generated_cases:
            generated_coordinate = generated_case.coordinate
            independent_payload = {
                "failure": generated_coordinate.failure,
                "family": generated_coordinate.family,
                "latin_order": generated_coordinate.latin_order,
                "regime": generated_coordinate.regime,
                "replicate": generated_coordinate.replicate,
            }
            independent_raw_json = json.dumps(
                independent_payload,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            independent_canonical = (
                len(independent_raw_json).to_bytes(8, byteorder="big")
                + independent_raw_json
            )
            independent_seed = hmac.new(
                root_seed,
                independent_canonical,
                hashlib.sha256,
            ).digest()
            assert generated_case.case_seed == independent_seed
            assert (
                generator.derive_case_seed(root_seed, generated_coordinate)
                == independent_seed
            )
            single_case = generator.generate_case(root_seed, generated_coordinate)
            assert single_case.case_seed == independent_seed
            assert single_case.coordinate == generated_case.coordinate
            assert single_case.case_id == generated_case.case_id
            assert single_case.case_seed == generated_case.case_seed
            assert single_case.declaration == generated_case.declaration
        assert len({case.case_id for case in generated_cases}) == 432
        assert len({case.case_seed for case in generated_cases}) == 432
        declarations = tuple(case.declaration for case in generated_cases)
        assert generator.semantic_uniqueness_violations(declarations) == ()
        assert len({declaration.fixture_id for declaration in declarations}) == 432
        assert len({declaration.fixture_prefix for declaration in declarations}) == 432
        family_specs = tuple(declaration.family_spec for declaration in declarations)
        exact_spec_types = tuple(generator.FAMILY_SPEC_TYPES.values())
        assert all(
            any(type(family_spec) is spec_type for spec_type in exact_spec_types)
            for family_spec in family_specs
        )
        for index, family_spec in enumerate(family_specs):
            assert all(
                type(family_spec) is not type(previous) or family_spec != previous
                for previous in family_specs[:index]
            )
    assert all(
        left.case_seed != right.case_seed
        and left.case_id != right.case_id
        and type(left.declaration.family_spec) is type(right.declaration.family_spec)
        and left.declaration.family_spec != right.declaration.family_spec
        and left.declaration.fixture_id != right.declaration.fixture_id
        and left.declaration.fixture_prefix != right.declaration.fixture_prefix
        for left, right in zip(first, other_root)
    )
    assert Counter(
        (
            case.coordinate.family,
            case.coordinate.regime,
            case.coordinate.failure,
            case.coordinate.latin_order,
            case.coordinate.replicate,
        )
        for case in first
    ) == Counter(
        (family, regime, failure, latin_order, replicate)
        for family in FAMILIES
        for regime in REGIMES
        for failure in FAILURES
        for latin_order in WILLIAMS_ORDERS
        for replicate in (0, 1)
    )

    def coordinate_key(item: object) -> tuple[object, ...]:
        return tuple(
            getattr(item, field.name) for field in fields(generator.CaseCoordinate)
        )

    sample_coordinates = tuple(case.coordinate for case in first[:24])
    forward = {
        coordinate_key(item): generator.generate_case(EPHEMERAL_TEST_KEY, item)
        for item in sample_coordinates
    }
    backward = {
        coordinate_key(item): generator.generate_case(EPHEMERAL_TEST_KEY, item)
        for item in reversed(sample_coordinates)
    }
    generated_by_coordinate = {coordinate_key(case.coordinate): case for case in first}
    assert forward == backward
    assert all(
        generated_by_coordinate[key] == generated_case
        for key, generated_case in forward.items()
    )
    assert not hasattr(generator, "ROOT_SEED")
    assert not hasattr(generator, "materialized_corpus")
    assert not hasattr(generator, "CASES")
    assert not hasattr(generator, "ASSIGNMENTS")


def test_fail_closed_purity_policy_rejects_independent_malicious_ast_fixtures() -> None:
    reference_closures = _audit_generator_purity_source(
        REFERENCE_SOURCE,
        analyze_roots=_ANALYZE_ENTRY_POINTS,
    )
    assert _ANALYZE_ENTRY_POINTS <= reference_closures["analyze"]
    builtin_name = ast.Name(id="len", ctx=ast.Load())
    assert _origin_from_ast(builtin_name, {}, frozenset()) == ("builtins", "len")
    shadowed_origins = _resolve_consistent_alias_origins(
        {},
        {"len": (None,)},
        frozenset(),
    )
    assert shadowed_origins == {"len": _UNRESOLVED_ORIGIN}
    assert (
        _origin_from_ast(builtin_name, shadowed_origins, frozenset())
        == _UNRESOLVED_ORIGIN
    )

    accepted_source = """
import re
from dataclasses import dataclass
from re import compile as regex_compile
from types import MappingProxyType

PATTERN = re.compile(r"^[a-z]+$")
REGEX_BUILDER = regex_compile
REGEX_BUILDER_ALIAS = REGEX_BUILDER
ALIASED_PATTERN = REGEX_BUILDER_ALIAS(r"^[0-9]+$")

@dataclass(frozen=True)
class FrozenSpec:
    value: str

SPEC_TYPES = MappingProxyType({"text": FrozenSpec})
SPEC_TYPES_ALIAS = SPEC_TYPES

def generate_cases(root_seed: bytes) -> tuple[bool, bool]:
    spec = SPEC_TYPES_ALIAS["text"]("agent")
    return (
        bool(PATTERN.fullmatch(spec.value)),
        bool(ALIASED_PATTERN.fullmatch("7")),
    )

def scan_forbidden_pre_d1_artifacts(*roots: str) -> tuple[str, ...]:
    return ()
"""
    closures = _audit_generator_purity_source(
        accepted_source,
        generation_roots=frozenset({"generate_cases"}),
    )
    assert closures == {
        "generation": frozenset({"FrozenSpec", "generate_cases"}),
        "analyze": frozenset(),
        "initializer": frozenset(),
        "scanner": frozenset({"scan_forbidden_pre_d1_artifacts"}),
    }

    malicious_sources = {
        "local_path_alias_touch": """
def generate_cases(root_seed):
    from pathlib import Path as P
    P("escape").touch()

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "top_level_chained_path_alias_touch": """
from pathlib import Path as P

P2 = P
P3 = P2

def generate_cases(root_seed):
    P3("escape").touch()

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "scanner_path_mutation": """
from pathlib import Path

def generate_cases(root_seed):
    return ()

def scan_forbidden_pre_d1_artifacts(*roots):
    Path("escape").touch()
""",
        "local_builtins_compile_alias": """
def generate_cases(root_seed):
    from builtins import compile as c
    return c("1 + 1", "<fixture>", "eval")

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "builtins_open_subscript": """
def generate_cases(root_seed):
    return __builtins__["open"]("escape")

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "builtins_compile_getattr": """
def generate_cases(root_seed):
    return getattr(__builtins__, "compile")("1 + 1", "<fixture>", "eval")

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "unknown_wrapper": """
import harmless_wrapper

def generate_cases(root_seed):
    return harmless_wrapper.make("escape")

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "io_member_of_known_pure_root": """
import json

def generate_cases(root_seed, sink):
    json.dump({"seed": root_seed}, sink)

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "unresolved_parameter_callable": """
def generate_cases(root_seed, wrapper):
    return wrapper(root_seed)

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "same_leaf_noncanonical_receiver_items": """
def generate_cases(root_seed, receiver):
    return receiver.items()

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "allowed_builtin_parameter_shadow": """
def generate_cases(root_seed, len):
    return len(root_seed)

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "overwritten_local_builtin_alias": """
def generate_cases(root_seed, replacement):
    size = len
    size = replacement
    return size(root_seed)

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "annotated_dynamic_callable_parameter": """
from typing import Callable

def generate_cases(root_seed, wrapper: Callable[[bytes], bytes]):
    return wrapper(root_seed)

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "nested_outer_builtin_shadow": """
def generate_cases(root_seed, len):
    def invoke():
        return len(())
    return invoke()

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "nested_outer_import_shadow": """
import re

def generate_cases(root_seed, re):
    def invoke():
        return re.compile("constant")
    return invoke()

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "nested_annotated_builtin_shadow": """
from typing import Callable

def generate_cases(root_seed, len: Callable[[object], int]):
    def invoke():
        return len(())
    return invoke()

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "unproven_mapping_callable": """
import re
from types import MappingProxyType

CALLABLES = MappingProxyType({"regex": re.compile})

def generate_cases(root_seed):
    return CALLABLES["regex"]("escape")

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "unproven_mapping_get_callable": """
import re
from types import MappingProxyType

CALLABLES = MappingProxyType({"regex": re.compile})

def generate_cases(root_seed):
    return CALLABLES.get("regex")("escape")

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "mutable_default_cache": """
def generate_cases(root_seed, cache={}):
    cache[root_seed] = True
    return cache

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "closure_cache": """
def build_cached_generator():
    cache = []
    def cached_generate(root_seed):
        cache.append(root_seed)
        return tuple(cache)
    return cached_generate

CACHED_GENERATE = build_cached_generator()

def generate_cases(root_seed):
    return CACHED_GENERATE(root_seed)

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "class_level_cache": """
from dataclasses import dataclass

@dataclass(frozen=True)
class CaseCache:
    values = []

def generate_cases(root_seed):
    return len(CaseCache.values)

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "direct_custom_dunder_cache_access": """
from dataclasses import dataclass

@dataclass(frozen=True)
class FrozenSpec:
    value: str

def generate_cases(root_seed):
    cache = FrozenSpec.__cache__
    cache.append(root_seed)
    return tuple(cache)

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "getattr_custom_dunder_cache_access": """
from dataclasses import dataclass

@dataclass(frozen=True)
class FrozenSpec:
    value: str

def generate_cases(root_seed):
    cache = getattr(FrozenSpec, "__cache__")
    cache.append(root_seed)
    return tuple(cache)

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "direct_dataclass_fields_alias_mutation": """
from dataclasses import dataclass

@dataclass(frozen=True)
class FrozenSpec:
    value: str

def generate_cases(root_seed):
    field_map = FrozenSpec.__dataclass_fields__
    field_map["escaped"] = root_seed
    return tuple(field_map)

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "dataclass_field_object_mutation": """
import dataclasses

@dataclasses.dataclass(frozen=True)
class FrozenSpec:
    value: str

def generate_cases(root_seed):
    field = dataclasses.fields(FrozenSpec)[0]
    field.name = "escaped"
    return field.name

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "source_declared_dunder_class_assignment": """
from dataclasses import dataclass

@dataclass(frozen=True)
class FrozenSpec:
    value: str
    __cache__ = ()

def generate_cases(root_seed):
    return FrozenSpec(str(root_seed))

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "source_declared_dunder_class_annotation": """
from dataclasses import dataclass

@dataclass(frozen=True)
class FrozenSpec:
    value: str
    __memo__: tuple[str, ...] = ()

def generate_cases(root_seed):
    return FrozenSpec(str(root_seed))

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "source_declared_dunder_method": """
from dataclasses import dataclass

@dataclass(frozen=True)
class FrozenSpec:
    value: str

    def __stash__(self):
        return self.value

def generate_cases(root_seed):
    return FrozenSpec(str(root_seed))

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "lambda_denied_builtin": """
def generate_cases(root_seed):
    invoke = lambda: open("escape")
    return invoke()

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "lambda_scanner_filesystem": """
from pathlib import Path

def generate_cases(root_seed):
    probe = lambda: Path("escape").exists()
    return probe()

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "stale_local_callable_alias": """
import re

def generate_cases(root_seed, wrapper):
    regex_builder = re.compile
    regex_builder = wrapper
    return regex_builder(r"^[a-z]+$")

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "reassigned_import_alias": """
from re import compile as regex_builder

regex_builder = unresolved_wrapper

def generate_cases(root_seed):
    return regex_builder(r"^[a-z]+$")

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "match_capture_overwrites_allowed_alias": """
import re

def generate_cases(root_seed):
    regex_builder = re.compile
    match root_seed:
        case regex_builder:
            return regex_builder(r"^[a-z]+$")

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "import_alias_overwritten_by_dict_comprehension": """
import re as regex_builder

regex_builder = {item: item for item in range(1)}

def generate_cases(root_seed):
    return len(regex_builder)

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "import_alias_overwritten_by_generator_expression": """
import re as regex_builder

regex_builder = (item for item in range(1))

def generate_cases(root_seed):
    return len(tuple(regex_builder))

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "unresolved_module_global_read_through_builtin": """
import re as regex_builder

regex_builder = unresolved_value

def generate_cases(root_seed):
    return len(regex_builder)

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "multiply_bound_import_alias": """
from json import dumps as serializer
from re import compile as serializer

def generate_cases(root_seed):
    return serializer(r"^[a-z]+$")

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "unannotated_parameter_shadows_import": """
import re

def generate_cases(root_seed, re):
    return re.compile(r"^[a-z]+$")

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "unused_class_import_time_shelter": """
from pathlib import Path

class UnusedShelter:
    escaped = Path("escape").exists()

def generate_cases(root_seed):
    return ()

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "unused_function_default_import_time_shelter": """
from pathlib import Path

def unused_shelter(escaped=Path("escape").exists()):
    return escaped

def generate_cases(root_seed):
    return ()

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
        "initializer_calls_scanner": """
def generate_cases(root_seed):
    return ()

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()

SCANNED = scan_forbidden_pre_d1_artifacts(".")
""",
        "initializer_calls_local_decorator": """
def local_decorator(function):
    return function

@local_decorator
def generate_cases(root_seed):
    return ()

def scan_forbidden_pre_d1_artifacts(*roots):
    return ()
""",
    }
    expected_v8_rejections = {
        "allowed_builtin_parameter_shadow": "unresolved callable provenance",
        "annotated_dynamic_callable_parameter": "unresolved callable provenance",
        "import_alias_overwritten_by_dict_comprehension": (
            "module initializer exposes mutable state"
        ),
        "import_alias_overwritten_by_generator_expression": (
            "module initializer exposes mutable state"
        ),
        "match_capture_overwrites_allowed_alias": (
            "structural pattern matching has unaudited lexical bindings"
        ),
        "nested_annotated_builtin_shadow": "unresolved callable provenance",
        "nested_outer_builtin_shadow": "unresolved callable provenance",
        "nested_outer_import_shadow": "unresolved callable provenance",
        "overwritten_local_builtin_alias": "unresolved callable provenance",
        "reassigned_import_alias": "unresolved callable provenance",
        "same_leaf_noncanonical_receiver_items": "unresolved callable provenance",
        "unresolved_module_global_read_through_builtin": (
            "unresolved module-global read in generation"
        ),
    }
    for label, source in malicious_sources.items():
        with pytest.raises(AssertionError) as error:
            _audit_generator_purity_source(
                source,
                generation_roots=frozenset({"generate_cases"}),
            )
        assert error.value, label
        if expected_rejection := expected_v8_rejections.get(label):
            assert expected_rejection in str(error.value), label
    synthetic_module = SimpleNamespace(
        __name__="test_lh1a_synthetic_generator",
        imported_alias=re,
    )
    assert _module_runtime_state_snapshot(synthetic_module, frozenset()) == (
        ("imported_alias", ("external_module", "re")),
    )

    synthetic_module.imported_alias = {"mutable": True}
    with pytest.raises(AssertionError, match="mutable or stateful"):
        _module_runtime_state_snapshot(synthetic_module, frozenset())

    generated_state = (item for item in ())
    synthetic_module.imported_alias = generated_state
    try:
        with pytest.raises(AssertionError, match="mutable or stateful"):
            _module_runtime_state_snapshot(synthetic_module, frozenset())
    finally:
        generated_state.close()


def test_generation_scanner_and_initializer_closures_are_fail_closed_and_stable(
    generator_subject: tuple[ModuleType, str],
) -> None:
    generator, source = generator_subject
    closures = _audit_generator_purity_source(
        source,
        analyze_roots=_ANALYZE_ENTRY_POINTS,
    )
    assert tuple(closures) == (
        "generation",
        "analyze",
        "initializer",
        "scanner",
    )
    assert _GENERATION_ENTRY_POINTS <= closures["generation"]
    assert _ANALYZE_ENTRY_POINTS <= closures["analyze"]
    assert _SCANNER_ENTRY_POINTS <= closures["scanner"]
    assert closures["initializer"] == frozenset()
    assert closures["generation"].isdisjoint(closures["analyze"])
    assert closures["generation"].isdisjoint(closures["scanner"])
    assert closures["generation"].isdisjoint(closures["initializer"])
    assert closures["analyze"].isdisjoint(closures["initializer"])
    assert closures["scanner"].isdisjoint(closures["initializer"])
    assert (
        _runtime_state_snapshot(
            _PGP2_TRUSTED_FUTURE_ANNOTATIONS,
            module_name="_pgp2_future_purity_control",
            generation_classes=frozenset(),
        )
        == _PGP2_TRUSTED_FUTURE_FEATURE_SNAPSHOT
    )

    global_names_before = frozenset(
        name for name in vars(generator) if not name.startswith("__")
    )
    assert len(global_names_before) == 75
    state_before = _module_runtime_state_snapshot(
        generator,
        closures["generation"],
    )
    generator.generate_cases(EPHEMERAL_TEST_KEY)
    generator.generate_cases(SECOND_EPHEMERAL_TEST_KEY)
    global_names_after = frozenset(
        name for name in vars(generator) if not name.startswith("__")
    )
    state_after = _module_runtime_state_snapshot(
        generator,
        closures["generation"],
    )
    assert global_names_after == global_names_before
    assert state_after == state_before

    for mapping_name in (
        "FAMILY_SPEC_TYPES",
        "SEMANTIC_NORMALIZATION_RULES",
        "WILLIAMS_ORDERS",
    ):
        assert isinstance(getattr(generator, mapping_name), MappingProxyType)
    for sequence_name in (
        "FORBIDDEN_PRE_D1_BASENAMES",
        "FORBIDDEN_PRE_D1_PATTERNS",
        "TASK_FAMILIES",
    ):
        assert isinstance(getattr(generator, sequence_name), tuple)
    assert all(isinstance(order, tuple) for order in generator.WILLIAMS_ORDERS.values())
    assert all(
        isinstance(steps, tuple)
        for steps in generator.SEMANTIC_NORMALIZATION_RULES.values()
    )


def _independent_family_oracle(family: str, spec: object, version: str) -> object:
    assert version in {"v1", "v2"}
    if family == "string_transform":
        operation = getattr(spec, "operation")
        assert operation == "upper", f"unsupported string transform: {operation}"
        return getattr(spec, f"text_{version}").upper()
    if family == "numeric_reducer":
        operation = getattr(spec, "operation")
        assert operation == "sum", f"unsupported numeric reducer: {operation}"
        return sum(getattr(spec, f"values_{version}"))
    if family == "validator":
        rule = getattr(spec, "rule")
        assert rule == "contains_digit", f"unsupported validator rule: {rule}"
        value = getattr(spec, f"value_{version}")
        return any(character.isdigit() for character in value)
    if family == "formatter":
        values = dict(getattr(spec, f"values_{version}"))
        return getattr(spec, "template").format(**values)
    if family == "record_filter":
        records = getattr(spec, f"records_{version}")
        field = getattr(spec, "field")
        expected = getattr(spec, "equals")
        return tuple(
            record for record in records if dict(record).get(field) == expected
        )
    if family == "small_state_machine":
        transitions: dict[tuple[object, object], object] = {}
        for source, event, target in getattr(spec, "transitions"):
            key = (source, event)
            assert key not in transitions, f"ambiguous transition: {key!r}"
            transitions[key] = target
        state = getattr(spec, "initial_state")
        for event in getattr(spec, f"events_{version}"):
            key = (state, event)
            assert key in transitions, f"unsupported transition: {key!r}"
            state = transitions[key]
        return state
    raise AssertionError(f"unsupported family: {family}")


def test_six_families_have_distinct_typed_semantics_and_reference_oracles(
    generator_subject: tuple[ModuleType, str],
) -> None:
    generator, _source = generator_subject
    spec_types = {
        "string_transform": generator.StringTransformSpec,
        "numeric_reducer": generator.NumericReducerSpec,
        "validator": generator.ValidatorSpec,
        "formatter": generator.FormatterSpec,
        "record_filter": generator.RecordFilterSpec,
        "small_state_machine": generator.SmallStateMachineSpec,
    }
    assert generator.FAMILY_SPEC_TYPES == spec_types
    assert len(set(spec_types.values())) == len(FAMILIES)
    expected_fields = {
        "string_transform": ("text_v1", "text_v2", "operation"),
        "numeric_reducer": ("values_v1", "values_v2", "operation"),
        "validator": ("value_v1", "value_v2", "rule"),
        "formatter": ("template", "values_v1", "values_v2"),
        "record_filter": ("records_v1", "records_v2", "field", "equals"),
        "small_state_machine": (
            "initial_state",
            "events_v1",
            "events_v2",
            "transitions",
        ),
    }
    for family, spec_type in spec_types.items():
        assert is_dataclass(spec_type)
        assert spec_type.__dataclass_params__.frozen is True
        assert (
            tuple(field.name for field in fields(spec_type)) == expected_fields[family]
        )
    assert is_dataclass(generator.SemanticFixtureDeclaration)
    assert generator.SemanticFixtureDeclaration.__dataclass_params__.frozen is True
    assert tuple(
        field.name for field in fields(generator.SemanticFixtureDeclaration)
    ) == (
        "case_id",
        "family",
        "family_spec",
        "fixture_id",
        "fixture_prefix",
        "fixture_version_v1",
        "fixture_version_v2",
        *SEMANTIC_CHANNELS,
    )

    reference_examples = {
        "string_transform": (
            generator.StringTransformSpec(
                text_v1="agent os",
                text_v2="agent core",
                operation="upper",
            ),
            ("AGENT OS", "AGENT CORE"),
        ),
        "numeric_reducer": (
            generator.NumericReducerSpec(
                values_v1=(2, 3),
                values_v2=(2, 3, 4),
                operation="sum",
            ),
            (5, 9),
        ),
        "validator": (
            generator.ValidatorSpec(
                value_v1="agent",
                value_v2="agent-7",
                rule="contains_digit",
            ),
            (False, True),
        ),
        "formatter": (
            generator.FormatterSpec(
                template="{name}:{count:02d}",
                values_v1=(("name", "agent"), ("count", 2)),
                values_v2=(("name", "agent"), ("count", 3)),
            ),
            ("agent:02", "agent:03"),
        ),
        "record_filter": (
            generator.RecordFilterSpec(
                records_v1=((("keep", False), ("value", "b")),),
                records_v2=(
                    (("keep", True), ("value", "a")),
                    (("keep", False), ("value", "b")),
                ),
                field="keep",
                equals=True,
            ),
            ((), ((("keep", True), ("value", "a")),)),
        ),
        "small_state_machine": (
            generator.SmallStateMachineSpec(
                initial_state="idle",
                events_v1=("start",),
                events_v2=("start", "finish"),
                transitions=(
                    ("idle", "start", "running"),
                    ("running", "finish", "done"),
                ),
            ),
            ("running", "done"),
        ),
    }
    for family, (spec, (expected_v1, expected_v2)) in reference_examples.items():
        assert _independent_family_oracle(family, spec, "v1") == expected_v1
        assert _independent_family_oracle(family, spec, "v2") == expected_v2
        assert generator.reference_result(spec, "v1") == expected_v1
        assert generator.reference_result(spec, "v2") == expected_v2
        with pytest.raises(ValueError):
            generator.reference_result(spec, "v3")
        artifacts = generator.derive_family_artifacts(spec)
        assert tuple(field.name for field in fields(artifacts)) == SEMANTIC_CHANNELS
        assert artifacts.initial_content == expected_v1
        assert artifacts.final_content == expected_v2
        assert artifacts.expected_result == expected_v2
        assert artifacts.provider_response == {"result": expected_v2}
        assert artifacts.fixture["family"] == family

    generated_by_root = (
        generator.generate_cases(EPHEMERAL_TEST_KEY),
        generator.generate_cases(SECOND_EPHEMERAL_TEST_KEY),
    )
    assert all(len(generated) == 432 for generated in generated_by_root)
    for generated in generated_by_root:
        for generated_case in generated:
            declaration = generated_case.declaration
            family = generated_case.coordinate.family
            assert declaration.case_id == generated_case.case_id
            assert declaration.family == family
            assert isinstance(declaration.family_spec, spec_types[family])
            oracle_v1 = _independent_family_oracle(
                family, declaration.family_spec, "v1"
            )
            oracle_v2 = _independent_family_oracle(
                family, declaration.family_spec, "v2"
            )
            assert (
                generator.reference_result(declaration.family_spec, "v1") == oracle_v1
            )
            assert (
                generator.reference_result(declaration.family_spec, "v2") == oracle_v2
            )
            derived = generator.derive_family_artifacts(declaration.family_spec)
            assert derived.initial_content == oracle_v1
            assert derived.final_content == oracle_v2
            assert derived.expected_result == oracle_v2
            assert derived.provider_response == {"result": oracle_v2}
            assert all(
                getattr(declaration, channel) == getattr(derived, channel)
                for channel in SEMANTIC_CHANNELS
            )
            assert generator.validate_family_semantics(declaration) == ()
            assert generator.validate_fixture_lineage(declaration) == ()

    generated = generated_by_root[0]
    representative_by_family = {
        family: next(
            case.declaration for case in generated if case.coordinate.family == family
        )
        for family in FAMILIES
    }
    for index, family in enumerate(FAMILIES):
        declaration = representative_by_family[family]
        assert declaration.family == family
        assert isinstance(declaration.family_spec, spec_types[family])
        derived = generator.derive_family_artifacts(declaration.family_spec)
        assert all(
            getattr(declaration, channel) == getattr(derived, channel)
            for channel in SEMANTIC_CHANNELS
        )
        assert generator.validate_family_semantics(declaration) == ()

        swapped_family = FAMILIES[(index + 1) % len(FAMILIES)]
        assert "FAMILY_SPEC_TYPE_MISMATCH" in generator.validate_family_semantics(
            replace(declaration, family=swapped_family)
        )
        for channel in SEMANTIC_CHANNELS:
            original = getattr(declaration, channel)
            mutation_value = (
                {"mutated": True}
                if isinstance(original, dict)
                else ("mutated",)
                if isinstance(original, tuple)
                else "mutated"
            )
            mutation = replace(declaration, **{channel: mutation_value})
            assert (
                f"FAMILY_ARTIFACT_MISMATCH_{channel.upper()}"
                in generator.validate_family_semantics(mutation)
            )


def test_williams_orders_balance_positions_and_all_directed_adjacencies(
    generator_subject: tuple[ModuleType, str],
) -> None:
    generator, _source = generator_subject
    orders = generator.WILLIAMS_ORDERS

    for position in range(4):
        assert Counter(order[position] for order in orders.values()) == {
            arm: 1 for arm in ("C", "F", "K", "R")
        }
    directed_pairs = Counter(
        pair for order in orders.values() for pair in zip(order, order[1:])
    )
    assert len(directed_pairs) == 12
    assert set(directed_pairs.values()) == {1}
    assert set(directed_pairs) == {
        (left, right)
        for left in ("C", "F", "K", "R")
        for right in ("C", "F", "K", "R")
        if left != right
    }


def test_declaration_uniqueness_and_semantic_normalization_are_frozen(
    generator_subject: tuple[ModuleType, str],
) -> None:
    generator, _source = generator_subject

    assert generator.SEMANTIC_NORMALIZATION_RULES == {
        channel: SEMANTIC_NORMALIZATION_STEPS for channel in SEMANTIC_CHANNELS
    }
    normalized_text = unicodedata.normalize("NFKC", "Ａ\r\nB \t\rC\t")
    normalized_text = normalized_text.replace("\r\n", "\n").replace("\r", "\n")
    normalized_text = "\n".join(
        line.rstrip(" \t") for line in normalized_text.split("\n")
    )
    expected_payload = {
        "a": {
            "y": unicodedata.normalize("NFKC", "e\u0301"),
            "z": unicodedata.normalize("NFKC", "Å ").rstrip(" \t"),
        },
        "b": normalized_text,
    }
    expected_bytes = json.dumps(
        expected_payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    raw_payload = {
        "ｂ": "Ａ\r\nB \t\rC\t",
        "a": {"z": "Å ", "y": "e\u0301"},
    }
    assert generator.normalized_semantic_bytes("fixture", raw_payload) == expected_bytes
    assert (
        generator.semantic_digest("fixture", raw_payload)
        == hashlib.sha256(expected_bytes).hexdigest()
    )
    for channel in SEMANTIC_CHANNELS:
        left = generator.semantic_digest(
            channel, {"text": "A\r\nB  ", "nested": {"b": 2, "a": 1}}
        )
        right = generator.semantic_digest(
            channel, {"nested": {"a": 1, "b": 2}, "text": "A\nB"}
        )
        assert left == right
        assert re.fullmatch(r"[0-9a-f]{64}", left)
        assert generator.semantic_digest(channel, {"text": "different"}) != left
        for nonfinite in (math.nan, math.inf, -math.inf):
            with pytest.raises(ValueError):
                generator.normalized_semantic_bytes(channel, {"value": nonfinite})
        with pytest.raises(ValueError, match="collision"):
            generator.normalized_semantic_bytes(channel, {"Å": 1, "Å": 2})
    with pytest.raises(ValueError):
        generator.semantic_digest("unknown_channel", {"text": "fail closed"})
    assert not hasattr(generator, "materialized_corpus")
    assert not hasattr(generator, "ROOT_SEED")
    assert not hasattr(generator, "CASES")
    assert not hasattr(generator, "ASSIGNMENTS")

    family_spec = generator.StringTransformSpec(
        text_v1="initial alpha",
        text_v2="final alpha",
        operation="upper",
    )
    family_artifacts = generator.derive_family_artifacts(family_spec)
    declaration = generator.SemanticFixtureDeclaration(
        case_id="case-a",
        family="string_transform",
        family_spec=family_spec,
        fixture_id="alpha-beta-001",
        fixture_prefix="alpha",
        fixture_version_v1=1,
        fixture_version_v2=2,
        **{
            channel: getattr(family_artifacts, channel) for channel in SEMANTIC_CHANNELS
        },
    )
    assert generator.validate_fixture_lineage(declaration) == ()
    lineage_mutations = (
        (
            replace(declaration, fixture_version_v2=1),
            "FIXTURE_VERSION_NOT_INCREMENTED",
        ),
        (
            replace(declaration, fixture_id="other-001"),
            "FIXTURE_ID_PREFIX_MISMATCH",
        ),
        (
            replace(declaration, requirement_v2=declaration.requirement_v1),
            "REQUIREMENT_CHANGE_MISSING",
        ),
        (
            replace(declaration, final_content=declaration.initial_content),
            "CONTENT_CHANGE_MISSING",
        ),
        (
            replace(declaration, requirement_v2="unlinked requirement"),
            "REQUIREMENT_V2_NOT_LINKED_TO_FINAL",
        ),
        (
            replace(declaration, expected_result="unlinked expectation"),
            "EXPECTED_RESULT_NOT_LINKED_TO_FINAL",
        ),
        (
            replace(declaration, test="assert something else"),
            "TEST_NOT_LINKED_TO_FINAL",
        ),
        (
            replace(declaration, provider_response={"result": "other"}),
            "PROVIDER_RESPONSE_NOT_LINKED_TO_FINAL",
        ),
    )
    for mutation, expected_violation in lineage_mutations:
        assert expected_violation in generator.validate_fixture_lineage(mutation)

    other_family_spec = generator.StringTransformSpec(
        text_v1="initial beta",
        text_v2="final beta",
        operation="upper",
    )
    other_family_artifacts = generator.derive_family_artifacts(other_family_spec)
    other_declaration = generator.SemanticFixtureDeclaration(
        case_id="case-b",
        family="string_transform",
        family_spec=other_family_spec,
        fixture_id="beta-001",
        fixture_prefix="beta",
        fixture_version_v1=1,
        fixture_version_v2=2,
        **{
            channel: getattr(other_family_artifacts, channel)
            for channel in SEMANTIC_CHANNELS
        },
    )
    assert generator.validate_family_semantics(other_declaration) == ()
    assert generator.validate_fixture_lineage(other_declaration) == ()

    duplicate_case_id = replace(other_declaration, case_id=declaration.case_id)
    duplicate_family_spec = replace(
        other_declaration,
        family_spec=declaration.family_spec,
        **{
            channel: getattr(family_artifacts, channel) for channel in SEMANTIC_CHANNELS
        },
    )
    duplicate_fixture_id = replace(
        other_declaration,
        fixture_id=declaration.fixture_id,
        fixture_prefix="alpha-beta",
    )
    duplicate_fixture_prefix = replace(
        other_declaration,
        fixture_id="alpha-other-001",
        fixture_prefix=declaration.fixture_prefix,
    )
    assert generator.semantic_uniqueness_violations(
        (declaration, duplicate_case_id)
    ) == ("DUPLICATE_CASE_ID",)
    assert generator.semantic_uniqueness_violations(
        (declaration, duplicate_family_spec)
    ) == ("DUPLICATE_FAMILY_SPEC",)
    assert generator.semantic_uniqueness_violations(
        (declaration, duplicate_fixture_id)
    ) == ("DUPLICATE_FIXTURE_ID",)
    assert generator.semantic_uniqueness_violations(
        (declaration, duplicate_fixture_prefix)
    ) == ("DUPLICATE_FIXTURE_PREFIX",)
    assert generator.semantic_uniqueness_violations((declaration, declaration)) == (
        "DUPLICATE_CASE_ID",
        "DUPLICATE_FAMILY_SPEC",
        "DUPLICATE_FIXTURE_ID",
        "DUPLICATE_FIXTURE_PREFIX",
    )
    assert duplicate_family_spec.case_id != declaration.case_id
    assert duplicate_family_spec.fixture_id != declaration.fixture_id
    assert duplicate_family_spec.fixture_prefix != declaration.fixture_prefix


def test_regime_schemas_and_arm_neutral_event_orders_are_exact() -> None:
    regimes = _module("regimes")
    expected_orders = {
        "R0_DIRECT_REFRESH": (
            "change",
            "read_v2",
            "provider",
            "approval",
            "apply",
            "test",
        ),
        "R1_DEPENDENCY_BEFORE_PROVIDER": (
            "change",
            "dependency_wait_satisfied",
            "provider",
            "approval",
            "apply",
        ),
        "R2_RELEASE_BEFORE_APPLY": (
            "change",
            "provider",
            "release_wait_satisfied",
            "approval",
            "apply",
        ),
    }
    expected_couplings = {
        "R0_DIRECT_REFRESH": (
            "AFTER_CHANGE_BEFORE_READ_V2",
            "wait_change",
            "requirement.changed",
            "change",
            None,
            None,
            None,
        ),
        "R1_DEPENDENCY_BEFORE_PROVIDER": (
            "AFTER_READ_V2_BEFORE_PROVIDER_V2",
            "wait_change",
            "requirement.changed",
            "change",
            "wait_dependency",
            "dependency.ready",
            "dependency",
        ),
        "R2_RELEASE_BEFORE_APPLY": (
            "AFTER_PROVIDER_V2_BEFORE_APPROVAL",
            "wait_change",
            "requirement.changed",
            "change",
            "wait_release",
            "release.ready",
            "release",
        ),
    }
    assert tuple(regimes.REGIME_SPECS) == REGIMES
    assert is_dataclass(regimes.RegimeSpec)
    assert tuple(field.name for field in fields(regimes.RegimeSpec)) == (
        "regime",
        "required_gate_position",
        "required_post_change_event_order",
        "change_wait_node_id",
        "change_signal_name",
        "change_correlation_suffix",
        "secondary_wait_node_id",
        "secondary_signal_name",
        "secondary_correlation_suffix",
    )
    assert regimes.CHANGE_NOTICE_FIELDS == (
        "schema_version",
        "case_id",
        "change_id",
        "goal_v2",
        "regime",
        "required_gate_position",
        "signal_name",
        "correlation_key",
    )
    assert tuple(regimes.ChangeNotice.model_fields) == regimes.CHANGE_NOTICE_FIELDS
    assert tuple(inspect.signature(regimes.events_for_regime).parameters) == ("regime",)
    for name, event_order in expected_orders.items():
        spec = regimes.REGIME_SPECS[name]
        assert is_dataclass(spec)
        assert tuple(getattr(spec, field.name) for field in fields(spec)) == (
            name,
            expected_couplings[name][0],
            event_order,
            *expected_couplings[name][1:],
        )
        assert spec.required_post_change_event_order == event_order
        assert regimes.events_for_regime(name) == event_order
        forbidden_field_tokens = (
            "answer",
            "arm",
            "content",
            "digest",
            "expected",
            "final",
            "outcome",
            "provider_response",
            "test_answer",
        )
        assert not any(
            token in field.name.lower()
            for field in fields(spec)
            for token in forbidden_field_tokens
        )
        spec_payload = {field.name: getattr(spec, field.name) for field in fields(spec)}
        with pytest.raises(TypeError):
            regimes.RegimeSpec(**spec_payload, expected_answer="forbidden")

        notice = regimes.change_notice_for(
            name,
            case_id="case-001",
            change_id="change-001",
            goal_v2="produce the v2 result",
        )
        expected_notice = {
            "schema_version": "lh1a-change-notice-v1",
            "case_id": "case-001",
            "change_id": "change-001",
            "goal_v2": "produce the v2 result",
            "regime": name,
            "required_gate_position": expected_couplings[name][0],
            "signal_name": "requirement.changed",
            "correlation_key": "case:case-001:change",
        }
        assert notice.model_dump(mode="json") == expected_notice
        for hidden_field in (
            "arm",
            "expected_answer",
            "final_content",
            "outcome",
            "provider_response",
        ):
            with pytest.raises(ValidationError):
                regimes.ChangeNotice(**expected_notice, **{hidden_field: "forbidden"})
        for field_name, invalid_value in (
            ("schema_version", "lh1a-change-notice-v2"),
            ("regime", "R9_UNDECLARED"),
            ("required_gate_position", "WRONG_GATE"),
            ("signal_name", "wrong.signal"),
            ("correlation_key", "case:case-001:wrong"),
        ):
            with pytest.raises(ValidationError):
                regimes.ChangeNotice(**{**expected_notice, field_name: invalid_value})
        with pytest.raises(ValidationError):
            regimes.ChangeNotice(**{**expected_notice, "case_id": "case-002"})
        for nonblank_field in ("case_id", "change_id", "goal_v2"):
            with pytest.raises(ValidationError):
                regimes.ChangeNotice(**{**expected_notice, nonblank_field: "   "})
    with pytest.raises(ValueError):
        regimes.change_notice_for(
            "R9_UNDECLARED",
            case_id="case-001",
            change_id="change-001",
            goal_v2="goal",
        )
    with pytest.raises(TypeError):
        regimes.events_for_regime(REGIMES[0], arm="C")


def test_candidate_public_call_sequences_and_wait_terminalization_are_exact() -> None:
    regimes = _module("regimes")
    assert regimes.CANDIDATE_PUBLIC_CALL_SEQUENCES == {
        "R0_DIRECT_REFRESH": (
            "signal_change_once",
            "repeat_identical_signal_id_and_payload",
            "run_committed_direct_suffix",
            "reach_assigned_failure_checkpoint",
        ),
        "R1_DEPENDENCY_BEFORE_PROVIDER": (
            "signal_change_once",
            "repeat_identical_signal_id_and_payload",
            "pause_task",
            "replan_task_exactly_once",
            "run_to_dependency_waiting_event",
            "deliver_matching_dependency_signal_once",
            "persist_dependency_wait_satisfied_projection",
            "reach_assigned_failure_checkpoint",
        ),
        "R2_RELEASE_BEFORE_APPLY": (
            "signal_change_once",
            "repeat_identical_signal_id_and_payload",
            "pause_task",
            "replan_task_exactly_once",
            "run_to_release_waiting_event",
            "deliver_matching_release_signal_once",
            "persist_release_wait_satisfied_projection",
            "reach_assigned_failure_checkpoint",
        ),
    }
    assert (
        regimes.waiting_recovery_disposition(
            elapsed_seconds=299,
            typed_timeout_or_failure_present=False,
        )
        == "WAITING_UNTIL_FROZEN_DEADLINE"
    )
    assert (
        regimes.waiting_recovery_disposition(
            elapsed_seconds=300,
            typed_timeout_or_failure_present=True,
        )
        == "TERMINAL_TYPED_TIMEOUT_OR_FAILURE"
    )
    assert (
        regimes.waiting_recovery_disposition(
            elapsed_seconds=300,
            typed_timeout_or_failure_present=False,
        )
        == "INVALID_PROTOCOL"
    )
    assert "Z0" not in {
        regimes.waiting_recovery_disposition(
            elapsed_seconds=elapsed,
            typed_timeout_or_failure_present=proof,
        )
        for elapsed in (299, 300, 360)
        for proof in (False, True)
    }


def test_failure_declarations_are_exact_and_population_balanced() -> None:
    generator = _module("generator")
    regimes = _module("regimes")

    assert regimes.FAILURE_MODES == FAILURES
    assert generator.POPULATION_DESIGN.failures == FAILURES
    assert generator.POPULATION_DESIGN.instances_per_failure == 144


def test_timing_ttl_and_lease_constants_are_exact_and_closed() -> None:
    regimes = _module("regimes")
    timing = regimes.TIMING_CONTRACT

    assert is_dataclass(timing)
    assert tuple(field.name for field in fields(timing)) == (
        "prepare_to_change_min_seconds",
        "change_to_recovery_min_seconds",
        "prepare_to_adjudicate_min_seconds",
        "wait_change_timeout_seconds",
        "secondary_wait_timeout_seconds",
        "commitment_ttl_seconds",
        "approval_ttl_seconds",
        "max_approval_to_apply_seconds",
        "stale_lease_seconds",
    )
    assert tuple(getattr(timing, field.name) for field in fields(timing)) == (
        7200,
        360,
        7560,
        21600,
        300,
        28800,
        600,
        120,
        300,
    )
    assert all(
        type(getattr(timing, field.name)) is int and getattr(timing, field.name) > 0
        for field in fields(timing)
    )


def test_failure_injectors_and_no_rescue_rules_are_frozen_declarations() -> None:
    regimes = _module("regimes")
    assert regimes.NO_RESCUE_RULES == NO_RESCUE_RULES
    assert tuple(regimes.FAILURE_INJECTORS) == FAILURES
    expected = {
        "PRE_CONSEQUENCE_PROCESS_EXIT": (
            "matched_post_change_pre_consequence_checkpoint",
            (
                "fresh_process_exits",
                "no_live_lease_remains",
                "injection_event_is_publicly_proven",
            ),
        ),
        "POST_APPLY_WORKER_INTERRUPTED": (
            "immediately_after_apply",
            (
                "stop_after_node_apply",
                "durable_logical_receipt_exists",
                "fresh_process_reacquires_without_stale_lease_override",
                "duplicate_effect_count_is_zero",
            ),
        ),
        "CORRECTION_HALT_BEFORE_APPLY": (
            "after_fresh_approval_before_apply",
            (
                "authorized_correction_is_publicly_recorded",
                "halted_action_is_denied_with_zero_effect",
                "resume_occurs_after_recovery_gate",
                "post_resume_approval_is_fresh",
            ),
        ),
    }
    for failure, (checkpoint, proofs) in expected.items():
        declaration = regimes.FAILURE_INJECTORS[failure]
        assert is_dataclass(declaration)
        assert tuple(field.name for field in fields(declaration)) == (
            "failure",
            "checkpoint",
            "required_public_proofs",
        )
        assert declaration.failure == failure
        assert declaration.checkpoint == checkpoint
        assert declaration.required_public_proofs == proofs


def test_candidate_initial_and_regime_templates_freeze_only_the_suffix(
    tmp_path: Path,
) -> None:
    templates = _module("templates")
    prefix = ("read_v1", "provider_v1", "wait_change")
    suffixes = {
        "R0_DIRECT_REFRESH": (
            "read_v2",
            "provider_v2",
            "approval",
            "apply",
            "test",
            "evaluate",
            "done",
        ),
        "R1_DEPENDENCY_BEFORE_PROVIDER": (
            "read_v2",
            "wait_dependency",
            "provider_v2",
            "approval",
            "apply",
            "test",
            "evaluate",
            "done",
        ),
        "R2_RELEASE_BEFORE_APPLY": (
            "read_v2",
            "provider_v2",
            "wait_release",
            "approval",
            "apply",
            "test",
            "evaluate",
            "done",
        ),
    }
    initial = templates.candidate_initial_template()
    assert isinstance(initial.workflow, WorkflowGraph)
    assert initial.budget_ceiling == templates.budget_ceiling_for("C")
    _assert_exact_workflow(
        initial.workflow,
        workflow_id="lh1a-candidate",
        version=1,
        max_replans=1,
        node_ids=prefix + suffixes["R0_DIRECT_REFRESH"],
    )
    initial_nodes = {node.node_id: node for node in initial.workflow.nodes}
    initial_prefix_edges = tuple(
        edge
        for edge in initial.workflow.edges
        if edge.source in prefix and edge.target in prefix
    )
    initial_incoming_prefix_edges = tuple(
        edge for edge in initial.workflow.edges if edge.target in prefix
    )
    for regime, suffix in suffixes.items():
        template = templates.candidate_template_for(regime)
        workflow = template.workflow
        assert isinstance(workflow, WorkflowGraph)
        assert template.budget_ceiling == templates.budget_ceiling_for("C")
        assert template.completed_prefix == prefix
        assert tuple(node.node_id for node in workflow.nodes) == prefix + suffix
        assert template.required_replans == (0 if regime.startswith("R0_") else 1)
        assert template.base_version == 1
        expected_version = 1 if regime.startswith("R0_") else 2
        assert template.version_increment == expected_version - 1
        _assert_exact_workflow(
            workflow,
            workflow_id="lh1a-candidate",
            version=expected_version,
            max_replans=1,
            node_ids=prefix + suffix,
        )
        assert len(workflow.nodes) == (10 if regime.startswith("R0_") else 11)
        assert workflow.nodes[-1].node_id == "done"
        assert workflow.nodes[-1].kind is NodeKind.TERMINAL
        assert workflow.edges[-1].target == "done"
        assert template.post_change_nodes == suffix
        nodes = {node.node_id: node for node in workflow.nodes}
        assert tuple(nodes[node_id] for node_id in prefix) == tuple(
            initial_nodes[node_id] for node_id in prefix
        )
        assert (
            tuple(
                edge
                for edge in workflow.edges
                if edge.source in prefix and edge.target in prefix
            )
            == initial_prefix_edges
        )
        assert (
            tuple(edge for edge in workflow.edges if edge.target in prefix)
            == initial_incoming_prefix_edges
        )
        if regime == "R0_DIRECT_REFRESH":
            assert workflow == initial.workflow

    instantiated_initial = templates.instantiate_candidate_initial("case-runtime-001")
    assert isinstance(instantiated_initial.workflow, WorkflowGraph)
    assert (
        templates.validate_instantiated_workflow(
            instantiated_initial.workflow,
            case_id="case-runtime-001",
        )
        == ()
    )
    tool_specs = DeveloperWorkspaceAdapter(tmp_path / "capability-check").specs()
    for regime in REGIMES:
        instantiated = templates.instantiate_candidate_for(
            regime,
            case_id="case-runtime-001",
        )
        workflow = instantiated.workflow
        assert workflow.workflow_id == "lh1a-candidate"
        assert workflow.evaluator_refs == ("evaluator:lh1a:1",)
        assert "{case_id}" not in workflow.model_dump_json()
        assert (
            templates.validate_instantiated_workflow(
                workflow,
                case_id="case-runtime-001",
            )
            == ()
        )
        for node in workflow.nodes:
            if node.kind is NodeKind.TOOL:
                assert node.capability in tool_specs
            elif node.kind is NodeKind.PROVIDER:
                assert node.capability == "provider.chat"
            if node.kind is NodeKind.WAIT_EVENT:
                assert node.wait_signal_name
                assert node.wait_correlation_key
                assert node.wait_correlation_key.startswith("case:case-runtime-001:")
        if regime == "R0_DIRECT_REFRESH":
            assert workflow == instantiated_initial.workflow

    placeholder_nodes = tuple(
        node.model_copy(update={"wait_correlation_key": "case:{case_id}:change"})
        if node.node_id == "wait_change"
        else node
        for node in instantiated_initial.workflow.nodes
    )
    placeholder_workflow = instantiated_initial.workflow.model_copy(
        update={"nodes": placeholder_nodes}
    )
    assert "UNRESOLVED_PLACEHOLDER" in templates.validate_instantiated_workflow(
        placeholder_workflow,
        case_id="case-runtime-001",
    )
    wrong_case_nodes = tuple(
        node.model_copy(update={"wait_correlation_key": "case:other:change"})
        if node.node_id == "wait_change"
        else node
        for node in instantiated_initial.workflow.nodes
    )
    wrong_case_workflow = instantiated_initial.workflow.model_copy(
        update={"nodes": wrong_case_nodes}
    )
    assert "CORRELATION_CASE_MISMATCH" in templates.validate_instantiated_workflow(
        wrong_case_workflow,
        case_id="case-runtime-001",
    )
    with pytest.raises(ValueError):
        templates.instantiate_candidate_for("R9_UNDECLARED", case_id="case-runtime-001")


def test_instantiated_wait_notice_and_external_signal_are_byte_linked() -> None:
    regimes = _module("regimes")
    templates = _module("templates")
    occurred_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    for regime in REGIMES:
        case_id = f"case-{regime.lower()}"
        workflow = templates.instantiate_candidate_for(
            regime,
            case_id=case_id,
        ).workflow
        nodes = {node.node_id: node for node in workflow.nodes}
        notice = regimes.change_notice_for(
            regime,
            case_id=case_id,
            change_id=f"change-{case_id}",
            goal_v2=f"goal-v2-{case_id}",
        )
        wait_node_ids = ["wait_change"]
        secondary_wait = regimes.REGIME_SPECS[regime].secondary_wait_node_id
        if secondary_wait is not None:
            wait_node_ids.append(secondary_wait)
        for node_id in wait_node_ids:
            node = nodes[node_id]
            signal = regimes.external_signal_for_wait(
                regime=regime,
                case_id=case_id,
                wait_node=node,
                notice=notice,
                task_id=f"task-{case_id}",
                run_id=f"run-{case_id}",
                tenant_id="tenant:local",
                workspace_id="workspace:local",
                occurred_at=occurred_at,
            )
            assert isinstance(signal, ExternalSignal)
            assert signal.signal_id == f"signal:{case_id}:{node_id}:{notice.change_id}"
            assert signal.signal_name == node.wait_signal_name
            assert signal.correlation_key == node.wait_correlation_key
            assert signal.payload_json == json.dumps(
                {"change_notice": notice.model_dump(mode="json")},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            assert signal.decoded_payload()["change_notice"] == notice.model_dump(
                mode="json"
            )
        assert notice.signal_name == nodes["wait_change"].wait_signal_name
        assert notice.correlation_key == nodes["wait_change"].wait_correlation_key

        inconsistent_node = nodes["wait_change"].model_copy(
            update={"wait_correlation_key": f"case:{case_id}:wrong"}
        )
        with pytest.raises(ValueError):
            regimes.external_signal_for_wait(
                regime=regime,
                case_id=case_id,
                wait_node=inconsistent_node,
                notice=notice,
                task_id=f"task-{case_id}",
                run_id=f"run-{case_id}",
                tenant_id="tenant:local",
                workspace_id="workspace:local",
                occurred_at=occurred_at,
            )

    r1_workflow = templates.instantiate_candidate_for(
        REGIMES[1], case_id="case-mismatch"
    ).workflow
    r0_notice = regimes.change_notice_for(
        REGIMES[0],
        case_id="case-mismatch",
        change_id="change-mismatch",
        goal_v2="goal mismatch",
    )
    with pytest.raises(ValueError):
        regimes.external_signal_for_wait(
            regime=REGIMES[1],
            case_id="case-mismatch",
            wait_node=next(
                node for node in r1_workflow.nodes if node.node_id == "wait_change"
            ),
            notice=r0_notice,
            task_id="task-mismatch",
            run_id="run-mismatch",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            occurred_at=occurred_at,
        )


def test_public_application_accepts_only_same_identity_prefix_preserving_replan(
    tmp_path: Path,
) -> None:
    regimes = _module("regimes")
    templates = _module("templates")
    prefix = ("read_v1", "provider_v1", "wait_change")

    def ready_for_replan(
        root: Path,
        *,
        regime: str,
        case_id: str,
    ) -> tuple[AgentOSApplication, str, WorkflowGraph, WorkflowGraph]:
        root.mkdir(parents=True)
        (root / "fixture.txt").write_text("v1\n", encoding="utf-8")
        app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
        provider_proposal = ProviderToolProposal(
            proposal_id="proposal:lh1a-fixture-v2",
            capability_id="workspace.apply_patch",
            arguments_json=json.dumps(
                {
                    "path": "fixture.txt",
                    "content": "v2\n",
                }
            ),
        )
        assert json.loads(provider_proposal.arguments_json) == {
            "content": "v2\n",
            "path": "fixture.txt",
        }
        app.provider = DeterministicProvider(
            text="provider-v1",
            tool_proposals=(provider_proposal,),
        )
        app.provider_configured = True
        now = datetime.now(timezone.utc)
        initial = templates.instantiate_candidate_initial(case_id).workflow
        replacement = templates.instantiate_candidate_for(
            regime,
            case_id=case_id,
        ).workflow
        task = app.create_task(
            {
                "goal_id": f"goal:{case_id}",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "created_by": "lh1a-test-principal",
                "created_at": now,
                "statement": "exercise the public D1-E replan seam",
            }
        )
        app.commit_task(
            task.task_id,
            {
                "commitment": {
                    "commitment_id": f"commitment:{case_id}",
                    "task_id": task.task_id,
                    "goal_id": f"goal:{case_id}",
                    "tenant_id": "tenant:local",
                    "workspace_id": "workspace:local",
                    "accepted_by": "lh1a-test-principal",
                    "accepted_at": now,
                    "deliverables": ["typed D1-E receipt"],
                    "acceptance_criteria": ["lh1a evaluator"],
                    "authority_scopes": ["workspace:read", "workspace:write"],
                    "budget": {
                        "max_cost_usd": "1",
                        "max_duration_seconds": 28800,
                        "max_provider_tokens": 4096,
                        "max_tool_calls": 20,
                    },
                    "risk_tier": 1,
                    "exit_conditions": ["frozen evaluator disposition"],
                    "expires_at": now + timedelta(hours=8),
                },
                "workflow": initial.model_dump(mode="json"),
                "expected_outcome": {
                    "expected_outcome_id": f"expected:{case_id}",
                    "task_id": task.task_id,
                    "tenant_id": "tenant:local",
                    "workspace_id": "workspace:local",
                    "evaluator_type": "lh1a",
                    "evaluator_version": "1",
                    "evidence_requirements": ["lh1a-episode-evidence"],
                    "failure_semantics": ["typed invalid or not met"],
                    "threshold": 1,
                    "observation_window_seconds": 300,
                    "frozen_at": now,
                },
            },
        )
        committed = app.tasks.get_task(task.task_id)
        assert committed.expected_outcome is not None
        assert (
            committed.expected_outcome.evaluator_type,
            committed.expected_outcome.evaluator_version,
        ) == ("lh1a", "1")
        waiting = app.run_task(
            task.task_id,
            {"target_path": "fixture.txt", "test_command": "python -m pytest"},
        )
        assert waiting.status is TaskStatus.WAITING
        assert waiting.run is not None
        assert waiting.run.status is RunStatus.WAITING_EVENT
        completed_prefix = tuple(
            event.decoded_payload()["node_id"]
            for event in app.store.read(task.task_id)
            if event.event_type is TaskEventType.NODE_COMPLETED
        )
        assert completed_prefix == prefix[:2]
        notice = regimes.change_notice_for(
            regime,
            case_id=case_id,
            change_id=f"change-{case_id}",
            goal_v2=f"goal-v2-{case_id}",
        )
        wait_node = next(
            node for node in initial.nodes if node.node_id == "wait_change"
        )
        signal = regimes.external_signal_for_wait(
            regime=regime,
            case_id=case_id,
            wait_node=wait_node,
            notice=notice,
            task_id=task.task_id,
            run_id=waiting.run.run_id,
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            occurred_at=app.tasks.now(),
        )
        signalled = app.signal_task(task.task_id, signal.model_dump(mode="json"))
        duplicate = app.signal_task(task.task_id, signal.model_dump(mode="json"))
        assert duplicate.sequence == signalled.sequence
        completed_prefix = tuple(
            event.decoded_payload()["node_id"]
            for event in app.store.read(task.task_id)
            if event.event_type is TaskEventType.NODE_COMPLETED
        )
        assert completed_prefix == prefix
        app.pause_task(task.task_id)
        return app, task.task_id, initial, replacement

    for regime in REGIMES[1:]:
        valid_root = tmp_path / f"valid-{regime.lower()}"
        app, task_id, initial, replacement = ready_for_replan(
            valid_root,
            regime=regime,
            case_id=f"case-valid-{regime.lower()}",
        )
        before_replan = app.tasks.get_task(task_id)
        assert before_replan.run is not None
        task_id_before_replan = before_replan.task_id
        run_id_before_replan = before_replan.run.run_id
        rebound = app.replan_task(
            task_id,
            {
                "workflow": replacement.model_dump(mode="json"),
                "reason": "bind the frozen regime suffix",
            },
        )
        assert rebound.run is not None
        assert rebound.workflow is not None
        assert rebound.task_id == task_id_before_replan
        assert rebound.run.run_id == run_id_before_replan
        assert rebound.run.replan_count == 1
        assert rebound.run.workflow_version == 2
        assert rebound.workflow.workflow_id == "lh1a-candidate"
        assert rebound.last_rebound is not None
        assert rebound.last_rebound.task_id == task_id_before_replan
        assert rebound.last_rebound.run_id == run_id_before_replan
        assert set(prefix).issubset(rebound.last_rebound.preserved_node_ids)
        initial_nodes = {node.node_id: node for node in initial.nodes}
        rebound_nodes = {node.node_id: node for node in rebound.workflow.nodes}
        assert tuple(rebound_nodes[node_id] for node_id in prefix) == tuple(
            initial_nodes[node_id] for node_id in prefix
        )
        assert tuple(
            edge for edge in rebound.workflow.edges if edge.target in prefix
        ) == tuple(edge for edge in initial.edges if edge.target in prefix)

        mutation_builders = {
            "workflow_id": lambda graph: graph.model_copy(
                update={"workflow_id": "lh1a-other"}
            ),
            "evaluator_ref": lambda graph: graph.model_copy(
                update={"evaluator_refs": ("evaluator:other:1",)}
            ),
            "completed_prefix_node": lambda graph: graph.model_copy(
                update={
                    "nodes": tuple(
                        node.model_copy(
                            update={"output_contract": "contract:mutated:1"}
                        )
                        if node.node_id == "read_v1"
                        else node
                        for node in graph.nodes
                    )
                }
            ),
            "incoming_prefix_edge": lambda graph: graph.model_copy(
                update={
                    "edges": tuple(
                        edge.model_copy(update={"condition": "mutated"})
                        if (edge.source, edge.target) == ("read_v1", "provider_v1")
                        else edge
                        for edge in graph.edges
                    )
                }
            ),
        }
        for mutation_name, mutate in mutation_builders.items():
            mutation_root = tmp_path / f"{mutation_name}-{regime.lower()}"
            mutation_app, mutation_task_id, _, mutation_replacement = ready_for_replan(
                mutation_root,
                regime=regime,
                case_id=f"case-{mutation_name}-{regime.lower()}",
            )
            mutated = mutate(mutation_replacement)
            with pytest.raises(ReplanRejectedError):
                mutation_app.replan_task(
                    mutation_task_id,
                    {
                        "workflow": mutated.model_dump(mode="json"),
                        "reason": f"reject {mutation_name}",
                    },
                )


def test_restart_has_identical_information_budget_and_human_charge() -> None:
    templates = _module("templates")
    restart_workflow_ids = {
        "R0_DIRECT_REFRESH": "lh1a-restart-r0-direct-refresh",
        "R1_DEPENDENCY_BEFORE_PROVIDER": "lh1a-restart-r1-dependency-before-provider",
        "R2_RELEASE_BEFORE_APPLY": "lh1a-restart-r2-release-before-apply",
    }

    for regime in REGIMES:
        common = tuple(
            templates.common_information_envelope(arm, regime)
            for arm in ("C", "F", "K", "R")
        )
        assert len(set(common)) == 1
        assert tuple(field.name for field in fields(common[0])) == (
            "fixture_schema",
            "change_notice_schema",
            "event_journal_schema",
            "provider_response_channel",
            "retry_ceiling",
            "context_ceiling",
            "tool_ceiling",
            "token_ceiling",
            "synthetic_cost_ceiling",
            "evaluator_contract",
            "failure_declaration",
        )
        assert not any(
            forbidden in field.name.lower()
            for field in fields(common[0])
            for forbidden in (
                "answer",
                "expected_content",
                "final_digest",
                "outcome",
                "arm",
            )
        )
        candidate = templates.candidate_template_for(regime)
        restart = templates.restart_template_for(regime)
        assert isinstance(restart.workflow, WorkflowGraph)
        assert restart.budget_ceiling == templates.budget_ceiling_for("R")
        _assert_exact_workflow(
            restart.workflow,
            workflow_id=restart_workflow_ids[regime],
            version=1,
            max_replans=0,
            node_ids=candidate.post_change_nodes,
        )
        assert restart.workflow.nodes[-1].kind is NodeKind.TERMINAL
        candidate_information = templates.information_envelope("C", regime)
        restart_information = templates.information_envelope("R", regime)
        assert candidate_information == restart_information
        assert candidate_information.budget_ceiling == templates.budget_ceiling_for("C")
        assert restart_information.budget_ceiling == templates.budget_ceiling_for("R")
        assert candidate_information.topology_selection_human_minutes == 2.0
        assert restart_information.topology_selection_human_minutes == 2.0
        assert templates.BUDGET_CEILINGS["C"] == templates.BUDGET_CEILINGS["R"]


def test_restart_evidence_predicate_requires_fresh_disjoint_matched_execution() -> None:
    evaluator = _module("evaluator")
    assert is_dataclass(evaluator.RestartEvidence)
    assert tuple(field.name for field in fields(evaluator.RestartEvidence)) == (
        "old_task_id",
        "new_task_id",
        "old_run_id",
        "new_run_id",
        "private_state_reused",
        "episode1_evidence_location",
        "sidecar_evidence_refs",
        "new_task_evidence_refs",
        "change_notice_matches",
        "template_matches",
        "topology_information_matches",
        "topology_selection_charge_c_half_minutes",
        "topology_selection_charge_r_half_minutes",
    )
    valid = evaluator.RestartEvidence(
        old_task_id="task-old",
        new_task_id="task-new",
        old_run_id="run-old",
        new_run_id="run-new",
        private_state_reused=False,
        episode1_evidence_location="RETAINED_SIDECAR_NOT_INJECTED",
        sidecar_evidence_refs=("evidence:episode-1",),
        new_task_evidence_refs=("evidence:episode-2",),
        change_notice_matches=True,
        template_matches=True,
        topology_information_matches=True,
        topology_selection_charge_c_half_minutes=4,
        topology_selection_charge_r_half_minutes=4,
    )
    assert evaluator.restart_disposition(valid) == "VALID_RESTART"
    mutations = tuple(
        [
            replace(valid, old_task_id=valid.new_task_id),
            replace(valid, new_task_id=valid.old_task_id),
            replace(valid, old_run_id=valid.new_run_id),
            replace(valid, new_run_id=valid.old_run_id),
            replace(valid, private_state_reused=True),
            replace(valid, episode1_evidence_location="INJECTED_INTO_NEW_TASK"),
            replace(
                valid,
                sidecar_evidence_refs=valid.new_task_evidence_refs,
            ),
            replace(
                valid,
                new_task_evidence_refs=valid.sidecar_evidence_refs,
            ),
            replace(valid, change_notice_matches=False),
            replace(valid, template_matches=False),
            replace(valid, topology_information_matches=False),
            replace(valid, topology_selection_charge_c_half_minutes=5),
            replace(valid, topology_selection_charge_r_half_minutes=5),
        ]
    )
    assert len(mutations) == len(fields(valid))
    assert all(
        evaluator.restart_disposition(mutation) == "INVALID_RESTART"
        for mutation in mutations
    )
    valid_payload = {field.name: getattr(valid, field.name) for field in fields(valid)}
    with pytest.raises(TypeError):
        evaluator.RestartEvidence(**valid_payload, hidden_state="forbidden")


def test_budget_ceiling_is_closed_positive_matched_and_candidate_derived() -> None:
    templates = _module("templates")
    ceilings = templates.BUDGET_CEILINGS
    assert tuple(ceilings) == ("C", "F", "R", "K")
    assert len(set(ceilings.values())) == 1
    ceiling = ceilings["C"]
    assert is_dataclass(ceiling)
    assert tuple(field.name for field in fields(ceiling)) == (
        "max_nodes",
        "max_retries_per_node",
        "max_context_tokens",
        "max_provider_tokens",
        "max_tool_calls",
        "max_synthetic_cost_units",
    )
    assert tuple(getattr(ceiling, field.name) for field in fields(ceiling)) == (
        11,
        1,
        8192,
        4096,
        4,
        10000,
    )
    assert all(
        type(getattr(ceiling, field.name)) is int and getattr(ceiling, field.name) > 0
        for field in fields(ceiling)
    )
    max_candidate_nodes = max(
        len(templates.candidate_template_for(regime).workflow.nodes)
        for regime in REGIMES
    )
    assert max_candidate_nodes == 11 == ceiling.max_nodes
    candidate_workflows = tuple(
        templates.candidate_template_for(regime).workflow for regime in REGIMES
    )
    assert (
        templates.fixed_ceiling_from_candidate_templates(candidate_workflows) == ceiling
    )
    with pytest.raises(ValueError):
        templates.fixed_ceiling_from_candidate_templates(
            candidate_workflows + (SimpleNamespace(nodes=tuple(range(12))),)
        )
    for arm in ("C", "F", "R", "K"):
        assert templates.budget_ceiling_for(arm) == ceiling
    with pytest.raises(ValueError):
        templates.budget_ceiling_for("UNDECLARED")
    with pytest.raises(TypeError):
        type(ceiling)(
            **{field.name: getattr(ceiling, field.name) for field in fields(ceiling)},
            extra_field=1,
        )
    usage = templates.information_envelope("C", "R2_RELEASE_BEFORE_APPLY").budget_usage
    assert templates.budget_disposition(usage, ceiling) == "ALLOW"
    usage_to_ceiling = {
        "node_count": "max_nodes",
        "retries_per_node": "max_retries_per_node",
        "context_tokens": "max_context_tokens",
        "provider_tokens": "max_provider_tokens",
        "tool_calls": "max_tool_calls",
        "synthetic_cost_units": "max_synthetic_cost_units",
    }
    assert tuple(field.name for field in fields(usage)) == tuple(usage_to_ceiling)
    for usage_field, ceiling_field in usage_to_ceiling.items():
        over_budget = replace(
            usage, **{usage_field: getattr(ceiling, ceiling_field) + 1}
        )
        assert templates.budget_disposition(over_budget, ceiling) == "DENY"
        negative = replace(usage, **{usage_field: -1})
        assert templates.budget_disposition(negative, ceiling) == "DENY"
    with pytest.raises(TypeError):
        type(usage)(
            **{field.name: getattr(usage, field.name) for field in fields(usage)},
            undeclared_usage=1,
        )


def test_human_charges_and_cost_rates_are_explicitly_synthetic() -> None:
    templates = _module("templates")
    ceiling = templates.BUDGET_CEILINGS["C"]
    charges = templates.HUMAN_CHARGES
    assert is_dataclass(charges)
    assert tuple(field.name for field in fields(charges)) == (
        "approval_minutes",
        "topology_selection_minutes",
        "correction_resume_minutes",
        "task_recreate_additional_minutes",
    )
    assert tuple(getattr(charges, field.name) for field in fields(charges)) == (
        0.5,
        2.0,
        1.0,
        0.0,
    )
    rates = templates.SYNTHETIC_RATE_UNITS
    assert is_dataclass(rates)
    assert tuple(field.name for field in fields(rates)) == (
        "provider_token_units",
        "tool_call_units",
    )
    assert (rates.provider_token_units, rates.tool_call_units) == (1, 1000)
    assert (
        ceiling.max_provider_tokens * rates.provider_token_units
        + ceiling.max_tool_calls * rates.tool_call_units
        == 8096
        <= ceiling.max_synthetic_cost_units
    )
    assert "usd" not in " ".join(field.name for field in fields(rates)).lower()
    assert {
        charge: templates.human_charge_minutes(charge)
        for charge in (
            "APPROVAL",
            "TOPOLOGY_SELECTION",
            "CORRECTION_RESUME",
            "TASK_RECREATE",
        )
    } == {
        "APPROVAL": 0.5,
        "TOPOLOGY_SELECTION": 2.0,
        "CORRECTION_RESUME": 1.0,
        "TASK_RECREATE": 0.0,
    }
    with pytest.raises(ValueError):
        templates.human_charge_minutes("UNDECLARED")
    assert (
        templates.human_minutes_for(
            approvals=1,
            topology_selections=1,
            correction_resumes=1,
            task_recreates=1,
            charges=charges,
        )
        == 3.5
    )
    assert (
        templates.human_minutes_for(
            approvals=1,
            topology_selections=1,
            correction_resumes=1,
            task_recreates=1,
            charges=replace(charges, approval_minutes=0.75),
        )
        == 3.75
    )
    assert (
        templates.human_minutes_for(
            approvals=0,
            topology_selections=0,
            correction_resumes=0,
            task_recreates=0,
            charges=charges,
        )
        == 0.0
    )
    with pytest.raises(ValueError):
        templates.human_minutes_for(
            approvals=-1,
            topology_selections=0,
            correction_resumes=0,
            task_recreates=0,
            charges=charges,
        )
    assert templates.synthetic_cost_units(3, 2, rates=rates) == 2003
    assert (
        templates.synthetic_cost_units(
            3,
            2,
            rates=replace(rates, provider_token_units=2),
        )
        == 2006
    )
    with pytest.raises(ValueError):
        templates.synthetic_cost_units(-1, 0, rates=rates)
    with pytest.raises(TypeError):
        templates.synthetic_cost_units(1, 1, rates=rates, unknown_rate=1)


def test_checkpoint_is_a_fresh_approval_stale_sha_negative_control() -> None:
    evaluator = _module("evaluator")
    assert evaluator.APPROVAL_MAX_AGE_INCLUSIVE_SECONDS == 120
    assert is_dataclass(evaluator.CheckpointEvidence)
    assert tuple(field.name for field in fields(evaluator.CheckpointEvidence)) == (
        "approval_recorded_after_change",
        "approval_age_seconds",
        "approval_fresh",
        "expected_sha_stale",
        "rejection_code",
        "workspace_digest_before",
        "workspace_digest_after",
        "successful_apply_receipts",
        "logical_effects",
    )
    digest = hashlib.sha256(b"checkpoint-workspace-before-and-after").hexdigest()
    valid = evaluator.CheckpointEvidence(
        approval_recorded_after_change=True,
        approval_age_seconds=120,
        approval_fresh=True,
        expected_sha_stale=True,
        rejection_code="EXPECTED_SHA_MISMATCH",
        workspace_digest_before=digest,
        workspace_digest_after=digest,
        successful_apply_receipts=0,
        logical_effects=0,
    )
    assert evaluator.checkpoint_disposition(valid) == "VALID_NEGATIVE_CONTROL"
    invalid_mutations = (
        replace(valid, approval_recorded_after_change=False),
        replace(valid, approval_age_seconds=121),
        replace(valid, approval_fresh=False),
        replace(valid, expected_sha_stale=False),
        replace(valid, rejection_code="APPROVAL_EXPIRED"),
    )
    safety_mutations = (
        replace(valid, workspace_digest_before=hashlib.sha256(b"other").hexdigest()),
        replace(valid, workspace_digest_after=hashlib.sha256(b"other").hexdigest()),
        replace(valid, successful_apply_receipts=1),
        replace(valid, logical_effects=1),
    )
    assert len(invalid_mutations) + len(safety_mutations) == len(fields(valid))
    assert all(
        evaluator.checkpoint_disposition(mutation) == "INVALID_NEGATIVE_CONTROL"
        for mutation in invalid_mutations
    )
    assert all(
        evaluator.checkpoint_disposition(mutation) == "SAFETY_REGRESSION"
        for mutation in safety_mutations
    )
    valid_payload = {field.name: getattr(valid, field.name) for field in fields(valid)}
    with pytest.raises(TypeError):
        evaluator.CheckpointEvidence(**valid_payload, hidden_effect="forbidden")


def _accepted_evidence(evaluator: Any, events: tuple[str, ...]) -> Any:
    return evaluator.EpisodeEvidence(
        product_verified=True,
        final_digest_matches=True,
        test_matches=True,
        required_evidence_matches=True,
        budget_matches=True,
        duplicate_logical_effects=0,
        severe_safety_breaches=0,
        failure_reached=True,
        failure_proven=True,
        fresh_process_recovery=True,
        public_event_order=events,
    )


def test_evaluator_accepts_only_outcome_failure_and_exact_public_order() -> None:
    evaluator = _module("evaluator")
    regimes = _module("regimes")
    assert is_dataclass(evaluator.EpisodeEvidence)
    assert tuple(field.name for field in fields(evaluator.EpisodeEvidence)) == (
        "product_verified",
        "final_digest_matches",
        "test_matches",
        "required_evidence_matches",
        "budget_matches",
        "duplicate_logical_effects",
        "severe_safety_breaches",
        "failure_reached",
        "failure_proven",
        "fresh_process_recovery",
        "public_event_order",
    )
    validation_order = regimes.events_for_regime(REGIMES[0])
    valid_payload = {
        field.name: getattr(_accepted_evidence(evaluator, validation_order), field.name)
        for field in fields(evaluator.EpisodeEvidence)
    }
    boolean_fields = (
        "product_verified",
        "final_digest_matches",
        "test_matches",
        "required_evidence_matches",
        "budget_matches",
        "failure_reached",
        "failure_proven",
        "fresh_process_recovery",
    )
    for field_name in boolean_fields:
        with pytest.raises((TypeError, ValueError)):
            evaluator.EpisodeEvidence(**{**valid_payload, field_name: 1})
    for field_name in ("duplicate_logical_effects", "severe_safety_breaches"):
        for invalid_count in (-1, 1.0, True):
            with pytest.raises((TypeError, ValueError)):
                evaluator.EpisodeEvidence(
                    **{**valid_payload, field_name: invalid_count}
                )
    for invalid_order in ([], (), ("",), ("valid", 1)):
        with pytest.raises((TypeError, ValueError)):
            evaluator.EpisodeEvidence(
                **{**valid_payload, "public_event_order": invalid_order}
            )
    for regime in REGIMES:
        required = regimes.events_for_regime(regime)
        accepted = _accepted_evidence(evaluator, required)
        assert tuple(field.name for field in fields(accepted)) == tuple(
            field.name for field in fields(evaluator.EpisodeEvidence)
        )
        score = evaluator.evaluate_episode(accepted, required)
        assert tuple(field.name for field in fields(score)) == (
            "accepted",
            "recovered",
            "z",
        )
        assert (score.accepted, score.recovered, score.z) == (1, 1, 1)

        event_mutations = (
            required[1:],
            required + ("unexpected_extra_event",),
            ("wrong_first_event",) + required[1:],
            required[:1] + tuple(reversed(required[1:])),
        )
        for event_order in event_mutations:
            rejected = evaluator.evaluate_episode(
                replace(accepted, public_event_order=event_order), required
            )
            assert (rejected.accepted, rejected.recovered, rejected.z) == (0, 0, 0)

        accepted_only_fields = (
            "product_verified",
            "final_digest_matches",
            "test_matches",
            "required_evidence_matches",
            "budget_matches",
        )
        for field_name in accepted_only_fields:
            rejected = evaluator.evaluate_episode(
                replace(accepted, **{field_name: False}), required
            )
            assert (rejected.accepted, rejected.recovered, rejected.z) == (0, 0, 0)
        for field_name in ("duplicate_logical_effects", "severe_safety_breaches"):
            rejected = evaluator.evaluate_episode(
                replace(accepted, **{field_name: 1}), required
            )
            assert (rejected.accepted, rejected.recovered, rejected.z) == (0, 0, 0)
        for field_name in (
            "failure_reached",
            "failure_proven",
            "fresh_process_recovery",
        ):
            not_recovered = evaluator.evaluate_episode(
                replace(accepted, **{field_name: False}), required
            )
            assert (
                not_recovered.accepted,
                not_recovered.recovered,
                not_recovered.z,
            ) == (1, 0, 0)
        empty = evaluator.EpisodeEvidence.empty(public_event_order=required)
        assert evaluator.evaluate_episode(empty, required) == type(score)(0, 0, 0)

    required = regimes.events_for_regime(REGIMES[0])
    with pytest.raises(TypeError):
        evaluator.EpisodeEvidence(**valid_payload, hidden_arm="C")


def test_evaluator_api_is_arm_name_blind_and_rebind_is_not_success() -> None:
    evaluator = _module("evaluator")
    parameter_names = tuple(inspect.signature(evaluator.evaluate_episode).parameters)
    evidence_fields = {
        field.name.lower() for field in fields(evaluator.EpisodeEvidence)
    }
    assert not any("arm" in name.lower() for name in parameter_names)
    assert not any("arm" in name for name in evidence_fields)

    tree = ast.parse(inspect.getsource(evaluator))
    evaluate_tree = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "evaluate_episode"
    )
    forbidden_arm_tokens = {
        "arm",
        "arm_name",
        "arm_id",
        "arm_label",
        "candidate",
        "fixed",
        "restart",
        "checkpoint",
        "c",
        "f",
        "r",
        "k",
    }
    observed_bypass_tokens: set[str] = set()
    for node in ast.walk(evaluate_tree):
        if isinstance(node, ast.Name):
            observed_bypass_tokens.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            observed_bypass_tokens.add(node.attr.lower())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            observed_bypass_tokens.add(node.value.lower())
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            observed_bypass_tokens.add(node.slice.value.lower())
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            observed_bypass_tokens.add(node.args[1].value.lower())
    assert observed_bypass_tokens.isdisjoint(forbidden_arm_tokens)
    assert "run_plan_rebound" not in observed_bypass_tokens

    empty = evaluator.EpisodeEvidence.empty(public_event_order=("RUN_PLAN_REBOUND",))
    score = evaluator.evaluate_episode(empty, ("RUN_PLAN_REBOUND",))
    assert (score.accepted, score.recovered, score.z) == (0, 0, 0)


def test_no_rescue_integrity_is_exact_ordered_and_fail_closed() -> None:
    evaluator = _module("evaluator")

    assert evaluator.no_rescue_integrity(NO_RESCUE_RULES) == "VALID"
    mutations = (
        NO_RESCUE_RULES[:-1],
        tuple(reversed(NO_RESCUE_RULES)),
        NO_RESCUE_RULES + ("ALLOW_RETRY",),
        ("ALLOW_SEED_CHANGE",) + NO_RESCUE_RULES[1:],
    )
    for mutation in mutations:
        assert evaluator.no_rescue_integrity(mutation) == "INVALID"
    assert (
        evaluator.design_integrity_disposition(
            requested_action="EXECUTE_FROZEN_PHASE",
            failure_schedule_intact=True,
        )
        == "ALLOW"
    )
    for rescue_action in (
        "RESEED",
        "REMOVE_OR_REPLACE_CASE",
        "WEAKEN_BASELINE",
        "MOVE_THRESHOLD",
        "SUBSTITUTE_METRIC",
        "RETRY_FAILED_CASE",
        "PATCH_AFTER_ORACLE",
        "REWRITE_FAILURE_SCHEDULE",
        "UNDECLARED_ACTION",
    ):
        assert (
            evaluator.design_integrity_disposition(
                requested_action=rescue_action,
                failure_schedule_intact=True,
            )
            == "INVALID"
        )
    assert (
        evaluator.design_integrity_disposition(
            requested_action="EXECUTE_FROZEN_PHASE",
            failure_schedule_intact=False,
        )
        == "INVALID"
    )


def test_mcnemar_effect_gate_and_edge_cases_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statistics = _module("statistics")

    assert statistics.exact_one_sided_mcnemar(0, 0) == 1.0
    assert statistics.exact_one_sided_mcnemar(10, 5) == pytest.approx(
        _exact_binomial_upper_tail(10, 15)
    )
    effect_44 = statistics.primary_effect(n10=44, n01=0, total=432)
    effect_43 = statistics.primary_effect(n10=43, n01=0, total=432)
    effect_40 = statistics.primary_effect(n10=50, n01=10, total=432)
    assert effect_44.integer_margin == 44
    assert effect_44.delta_hat == pytest.approx(44 / 432)
    assert effect_44.effect_floor_pass is True
    assert effect_44.confirmatory_pass is True
    assert effect_43.p_value < 0.05
    assert effect_43.effect_floor_pass is False
    assert effect_43.confirmatory_pass is False
    assert effect_40.integer_margin == 40
    assert effect_40.delta_hat == pytest.approx(40 / 432)
    assert effect_40.effect_floor_pass is False
    assert statistics.joint_primary_accepts(n10=44, n01=0, total=432) is True
    assert statistics.joint_primary_accepts(n10=43, n01=0, total=432) is False
    assert statistics.joint_primary_accepts(n10=50, n01=10, total=432) is False
    with pytest.raises(ValueError):
        statistics.exact_one_sided_mcnemar(-1, 0)
    monkeypatch.setattr(statistics, "exact_one_sided_mcnemar", lambda _n10, _n01: 1.0)
    assert statistics.joint_primary_accepts(n10=44, n01=0, total=432) is False
    monkeypatch.setattr(statistics, "exact_one_sided_mcnemar", lambda _n10, _n01: 0.0)
    assert statistics.joint_primary_accepts(n10=43, n01=0, total=432) is False


@pytest.mark.parametrize("function_name", ("primary_effect", "joint_primary_accepts"))
@pytest.mark.parametrize("invalid_total", (True, 432.0, 0, -1))
def test_primary_rejects_non_exact_or_non_positive_totals(
    function_name: str,
    invalid_total: object,
) -> None:
    statistics = _module("statistics")
    function = getattr(statistics, function_name)
    with pytest.raises((TypeError, ValueError)):
        function(n10=1, n01=0, total=invalid_total)


@pytest.mark.parametrize("function_name", ("primary_effect", "joint_primary_accepts"))
def test_primary_rejects_discordance_larger_than_total(function_name: str) -> None:
    statistics = _module("statistics")
    function = getattr(statistics, function_name)

    class IntSubclass(int):
        pass

    with pytest.raises(TypeError):
        function(n10=1, n01=0, total=IntSubclass(432))
    with pytest.raises(ValueError):
        function(n10=6, n01=5, total=10)


@pytest.mark.parametrize("function_name", ("primary_effect", "joint_primary_accepts"))
def test_primary_rejects_invalid_discordance_before_mcnemar(
    function_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statistics = _module("statistics")
    function = getattr(statistics, function_name)

    def reject_calculation(_n10: int, _n01: int) -> float:
        pytest.fail("McNemar must not run for an invalid primary paired table")

    monkeypatch.setattr(statistics, "exact_one_sided_mcnemar", reject_calculation)
    with pytest.raises(ValueError, match="n10 \\+ n01 cannot exceed total"):
        function(n10=6, n01=5, total=10)


def test_primary_effect_floor_uses_exact_integer_cross_multiplication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statistics = _module("statistics")
    monkeypatch.setattr(statistics, "exact_one_sided_mcnemar", lambda _n10, _n01: 0.0)
    total = 10**18 + 1
    effect = statistics.primary_effect(n10=10**17, n01=0, total=total)
    assert effect.delta_hat == pytest.approx((10**17) / total)
    assert effect.effect_floor_pass is False
    assert effect.confirmatory_pass is False
    assert statistics.joint_primary_accepts(n10=10**17, n01=0, total=total) is False


def test_zero_denominator_metric_rules_are_frozen() -> None:
    statistics = _module("statistics")

    assert statistics.per_z(7.5, 0) == 7.5
    assert statistics.duplicate_work_ratio(0, 0) == 0.0
    assert statistics.duplicate_work_ratio(1, 0) == 1.0
    assert math.isinf(statistics.incremental_human_per_net_recovered(10.0, 1.0, 5, 5))
    assert math.isinf(statistics.incremental_human_per_net_recovered(10.0, 1.0, 5, 6))
    assert statistics.incremental_human_per_net_recovered(10.0, 1.0, 6, 5) == 9.0
    assert statistics.incremental_human_per_net_recovered(1.0, 10.0, 6, 5) == 0.0


def test_base_plan_restart_duplicate_and_per_z_gates_are_exact() -> None:
    statistics = _module("statistics")
    metrics = statistics.MetGateInputs.boundary_passing_fixture()

    restart_only = replace(
        metrics,
        total_z_r=398,
        noncontributing_units_r=398,
        work_units_r=3980,
        human_half_minute_units_r=1990,
        provider_tokens_r=398,
        tool_calls_r=398,
    )
    restart_results = statistics.evaluate_met_gates(restart_only)
    assert {name for name, passed in restart_results.items() if not passed} == {
        "restart_guardrail"
    }
    assert statistics.evaluate_met_gates(metrics)["restart_guardrail"] is True

    zero_r_denominators = replace(
        metrics,
        total_z_r=0,
        noncontributing_units_r=0,
        work_units_r=0,
        human_half_minute_units_r=0,
        provider_tokens_r=0,
        tool_calls_r=0,
    )
    zero_r_results = statistics.evaluate_met_gates(zero_r_denominators)
    assert zero_r_results["duplicate_work_ratio"] is False
    assert zero_r_results["human_minutes_per_z"] is False
    assert zero_r_results["provider_tokens_per_z"] is False
    assert zero_r_results["tool_calls_per_z"] is False

    negative_recovery_denominator = replace(
        metrics,
        total_z_c=388,
        accepted_c=388,
        recovered_c=388,
        z_c_by_regime={REGIMES[0]: 129, REGIMES[1]: 129, REGIMES[2]: 130},
        z_c_by_failure={FAILURES[0]: 129, FAILURES[1]: 129, FAILURES[2]: 130},
        n10_cf=0,
        n01_cf=1,
        n10_cf_r1_r2=0,
        n01_cf_r1_r2=0,
        total_z_f=389,
        human_half_minute_units_c=1,
        human_half_minute_units_f=100,
    )
    assert (
        statistics.evaluate_met_gates(negative_recovery_denominator)[
            "incremental_human_per_net_recovered"
        ]
        is False
    )


def test_base_plan_prefix_and_metric_input_invariants_are_closed() -> None:
    statistics = _module("statistics")
    metrics = statistics.MetGateInputs.boundary_passing_fixture()

    for update in (
        {"preserved_prefix_count_c": 0, "preserved_prefix_eligible_c": 0},
        {"preserved_prefix_count_c": 431, "preserved_prefix_eligible_c": 431},
        {"preserved_prefix_count_c": 431, "preserved_prefix_eligible_c": 432},
    ):
        changed = replace(metrics, **update)
        assert statistics.evaluate_met_gates(changed)["preserved_prefix"] is False
    with pytest.raises(ValueError):
        replace(
            metrics,
            preserved_prefix_count_c=432,
            preserved_prefix_eligible_c=431,
        )
    for noncontributing_field, work_field in (
        ("noncontributing_units_c", "work_units_c"),
        ("noncontributing_units_r", "work_units_r"),
    ):
        with pytest.raises(ValueError):
            replace(metrics, **{noncontributing_field: 2, work_field: 1})


def test_overall_and_subset_paired_tables_are_jointly_validated() -> None:
    statistics = _module("statistics")
    metrics = statistics.MetGateInputs.boundary_passing_fixture()

    legal_overall = replace(
        metrics,
        total_z_c=100,
        accepted_c=100,
        recovered_c=100,
        z_c_by_regime={REGIMES[0]: 34, REGIMES[1]: 33, REGIMES[2]: 33},
        z_c_by_failure={FAILURES[0]: 34, FAILURES[1]: 33, FAILURES[2]: 33},
        n10_cf=100,
        n01_cf=100,
        n10_cf_r1_r2=66,
        total_z_f=100,
    )
    assert legal_overall.n10_cf == legal_overall.n01_cf == 100
    assert legal_overall.n10_cf <= legal_overall.total_z_c
    assert legal_overall.n01_cf <= legal_overall.total_z_f
    assert legal_overall.total_z_c + legal_overall.n01_cf <= 432
    assert legal_overall.total_z_f + legal_overall.n10_cf <= 432

    with pytest.raises(ValueError):
        replace(
            metrics,
            total_z_c=420,
            accepted_c=420,
            recovered_c=420,
            z_c_by_regime={REGIMES[0]: 140, REGIMES[1]: 140, REGIMES[2]: 140},
            z_c_by_failure={FAILURES[0]: 140, FAILURES[1]: 140, FAILURES[2]: 140},
            n10_cf=10,
            n01_cf=20,
            n10_cf_r1_r2=0,
            n01_cf_r1_r2=0,
            total_z_f=430,
        )
    with pytest.raises(ValueError):
        replace(metrics, n10_cf_r1_r2=metrics.n10_cf + 1)
    with pytest.raises(ValueError):
        replace(metrics, n01_cf_r1_r2=metrics.n01_cf + 1)
    with pytest.raises(ValueError):
        replace(
            metrics,
            n10_cf=28,
            n01_cf=0,
            n10_cf_r1_r2=29,
            n01_cf_r1_r2=0,
            total_z_f=361,
        )


def test_r1_r2_c_only_discordance_cannot_exceed_c_successes() -> None:
    statistics = _module("statistics")
    metrics = statistics.MetGateInputs.boundary_passing_fixture()

    with pytest.raises(ValueError):
        replace(
            metrics,
            z_c_by_regime={REGIMES[0]: 144, REGIMES[1]: 122, REGIMES[2]: 123},
            n10_cf=246,
            n01_cf=0,
            n10_cf_r1_r2=246,
            n01_cf_r1_r2=0,
            total_z_f=143,
        )


def test_r1_r2_f_only_discordance_cannot_exceed_c_failures() -> None:
    statistics = _module("statistics")
    metrics = statistics.MetGateInputs.boundary_passing_fixture()

    with pytest.raises(ValueError):
        replace(
            metrics,
            n10_cf=44,
            n01_cf=23,
            n10_cf_r1_r2=29,
            n01_cf_r1_r2=23,
            total_z_f=368,
        )


def test_r0_c_only_complement_cannot_exceed_c_successes() -> None:
    statistics = _module("statistics")
    metrics = statistics.MetGateInputs.boundary_passing_fixture()

    with pytest.raises(ValueError):
        replace(
            metrics,
            z_c_by_regime={REGIMES[0]: 101, REGIMES[1]: 144, REGIMES[2]: 144},
            n10_cf=131,
            n01_cf=0,
            n10_cf_r1_r2=29,
            n01_cf_r1_r2=0,
            total_z_f=258,
        )


def test_r0_f_only_complement_cannot_exceed_c_failures() -> None:
    statistics = _module("statistics")
    metrics = statistics.MetGateInputs.boundary_passing_fixture()

    with pytest.raises(ValueError):
        replace(
            metrics,
            n10_cf=44,
            n01_cf=22,
            n10_cf_r1_r2=29,
            n01_cf_r1_r2=0,
            total_z_f=367,
        )


def test_met_gate_inputs_are_exact_revalidated_and_fresh_at_consumption() -> None:
    statistics = _module("statistics")
    first = statistics.MetGateInputs.boundary_passing_fixture()
    second = statistics.MetGateInputs.boundary_passing_fixture()
    assert first is not second
    assert first.z_c_by_regime is not second.z_c_by_regime
    assert first.z_c_by_failure is not second.z_c_by_failure

    fake = SimpleNamespace(
        **{field.name: getattr(first, field.name) for field in fields(first)}
    )
    with pytest.raises(TypeError):
        statistics.evaluate_met_gates(fake)

    class MetGateInputsSubclass(statistics.MetGateInputs):
        pass

    subclass_instance = MetGateInputsSubclass(
        **{field.name: getattr(first, field.name) for field in fields(first)}
    )
    with pytest.raises(TypeError):
        statistics.evaluate_met_gates(subclass_instance)

    for map_field in ("z_c_by_regime", "z_c_by_failure"):
        mutable = replace(
            first,
            z_c_by_regime=dict(first.z_c_by_regime),
            z_c_by_failure=dict(first.z_c_by_failure),
        )
        getattr(mutable, map_field)["UNDECLARED"] = 0
        with pytest.raises(ValueError):
            statistics.evaluate_met_gates(mutable)


def test_integer_met_gate_boundaries_and_gate_set_are_exact() -> None:
    statistics = _module("statistics")
    metrics = statistics.MetGateInputs.boundary_passing_fixture()
    result = statistics.evaluate_met_gates(metrics)
    assert set(result) == {
        "z_c_rate",
        "accepted_c_rate",
        "recovered_c_rate",
        "z_c_by_regime",
        "z_c_by_failure",
        "delta_c_vs_f",
        "mcnemar_c_vs_f",
        "delta_c_vs_f_r1_r2",
        "restart_guardrail",
        "duplicate_work_ratio",
        "human_minutes_per_z",
        "provider_tokens_per_z",
        "tool_calls_per_z",
        "preserved_prefix",
        "incremental_human_per_net_recovered",
        "no_duplicate_effects",
        "no_severe_safety_breach",
    }
    assert all(result.values())
    assert tuple(field.name for field in fields(metrics)) == (
        "total_z_c",
        "accepted_c",
        "recovered_c",
        "z_c_by_regime",
        "z_c_by_failure",
        "n10_cf",
        "n01_cf",
        "n10_cf_r1_r2",
        "n01_cf_r1_r2",
        "total_z_r",
        "total_z_f",
        "noncontributing_units_c",
        "work_units_c",
        "noncontributing_units_r",
        "work_units_r",
        "human_half_minute_units_c",
        "human_half_minute_units_r",
        "human_half_minute_units_f",
        "provider_tokens_c",
        "provider_tokens_r",
        "tool_calls_c",
        "tool_calls_r",
        "preserved_prefix_count_c",
        "preserved_prefix_eligible_c",
        "duplicate_logical_side_effects_all",
        "severe_safety_breaches_all",
    )
    expected_boundary_values = {
        "total_z_c": 389,
        "accepted_c": 389,
        "recovered_c": 389,
        "z_c_by_regime": {
            REGIMES[0]: 123,
            REGIMES[1]: 123,
            REGIMES[2]: 143,
        },
        "z_c_by_failure": {
            FAILURES[0]: 123,
            FAILURES[1]: 123,
            FAILURES[2]: 143,
        },
        "n10_cf": 44,
        "n01_cf": 0,
        "n10_cf_r1_r2": 29,
        "n01_cf_r1_r2": 0,
        "total_z_r": 397,
        "total_z_f": 345,
        "noncontributing_units_c": 389,
        "work_units_c": 3890,
        "noncontributing_units_r": 397,
        "work_units_r": 3970,
        "human_half_minute_units_c": 1945,
        "human_half_minute_units_r": 1985,
        "human_half_minute_units_f": 185,
        "provider_tokens_c": 427,
        "provider_tokens_r": 397,
        "tool_calls_c": 427,
        "tool_calls_r": 397,
        "preserved_prefix_count_c": 432,
        "preserved_prefix_eligible_c": 432,
        "duplicate_logical_side_effects_all": 0,
        "severe_safety_breaches_all": 0,
    }
    assert {
        field.name: getattr(metrics, field.name) for field in fields(metrics)
    } == expected_boundary_values
    assert all(
        type(item) is int
        for field in fields(metrics)
        for item in (
            getattr(metrics, field.name).values()
            if isinstance(getattr(metrics, field.name), dict)
            else (getattr(metrics, field.name),)
        )
    )
    scalar_fields = tuple(
        field.name
        for field in fields(metrics)
        if not isinstance(getattr(metrics, field.name), dict)
    )
    for field_name in scalar_fields:
        for invalid_value in (True, 1.0, -1):
            with pytest.raises((TypeError, ValueError)):
                statistics.MetGateInputs(
                    **{**expected_boundary_values, field_name: invalid_value}
                )
    for map_field, exact_keys in (
        ("z_c_by_regime", REGIMES),
        ("z_c_by_failure", FAILURES),
    ):
        original_map = expected_boundary_values[map_field]
        assert isinstance(original_map, dict)
        first_key = exact_keys[0]
        for invalid_value in (True, 1.0, -1):
            with pytest.raises((TypeError, ValueError)):
                statistics.MetGateInputs(
                    **{
                        **expected_boundary_values,
                        map_field: {**original_map, first_key: invalid_value},
                    }
                )
        with pytest.raises(ValueError):
            statistics.MetGateInputs(
                **{
                    **expected_boundary_values,
                    map_field: {
                        key: value
                        for key, value in original_map.items()
                        if key != first_key
                    },
                }
            )
        with pytest.raises(ValueError):
            statistics.MetGateInputs(
                **{
                    **expected_boundary_values,
                    map_field: {**original_map, "UNDECLARED": 0},
                }
            )
        with pytest.raises(ValueError):
            statistics.MetGateInputs(
                **{
                    **expected_boundary_values,
                    map_field: {**original_map, first_key: 145},
                }
            )
        second_key = exact_keys[1]
        balanced_denominator_violation = dict(original_map)
        balanced_denominator_violation[first_key] = 145
        balanced_denominator_violation[second_key] = balanced_denominator_violation[
            second_key
        ] - (145 - original_map[first_key])
        assert set(balanced_denominator_violation) == set(exact_keys)
        assert (
            sum(balanced_denominator_violation.values())
            == expected_boundary_values["total_z_c"]
        )
        assert balanced_denominator_violation[first_key] == 145
        with pytest.raises(ValueError):
            statistics.MetGateInputs(
                **{
                    **expected_boundary_values,
                    map_field: balanced_denominator_violation,
                }
            )
    bounded_432 = (
        "total_z_c",
        "accepted_c",
        "recovered_c",
        "n10_cf",
        "n01_cf",
        "total_z_r",
        "total_z_f",
        "preserved_prefix_count_c",
        "preserved_prefix_eligible_c",
    )
    for field_name in bounded_432:
        with pytest.raises(ValueError):
            statistics.MetGateInputs(**{**expected_boundary_values, field_name: 433})
    for field_name in ("n10_cf_r1_r2", "n01_cf_r1_r2"):
        with pytest.raises(ValueError):
            statistics.MetGateInputs(**{**expected_boundary_values, field_name: 289})
    identity_mutations = (
        {"z_c_by_regime": {**metrics.z_c_by_regime, REGIMES[0]: 124}},
        {"z_c_by_failure": {**metrics.z_c_by_failure, FAILURES[0]: 124}},
        {"total_z_f": 344},
        {"accepted_c": 388},
        {"recovered_c": 388},
        {"n10_cf": 400, "n01_cf": 33, "total_z_f": 22},
        {"n10_cf_r1_r2": 200, "n01_cf_r1_r2": 89},
        {"preserved_prefix_count_c": 433, "preserved_prefix_eligible_c": 432},
    )
    for update in identity_mutations:
        with pytest.raises(ValueError):
            statistics.MetGateInputs(**{**expected_boundary_values, **update})
    missing = dict(expected_boundary_values)
    del missing["total_z_c"]
    with pytest.raises(TypeError):
        statistics.MetGateInputs(**missing)
    with pytest.raises(TypeError):
        statistics.MetGateInputs(**expected_boundary_values, undeclared=0)
    assert 10 * metrics.total_z_c >= 9 * 432
    assert 10 * (metrics.total_z_c - 1) < 9 * 432
    assert 20 * min(metrics.z_c_by_regime.values()) >= 17 * 144
    assert 20 * (min(metrics.z_c_by_regime.values()) - 1) < 17 * 144
    assert 20 * min(metrics.z_c_by_failure.values()) >= 17 * 144
    assert 20 * (min(metrics.z_c_by_failure.values()) - 1) < 17 * 144
    assert metrics.n10_cf - metrics.n01_cf == 44
    assert metrics.n10_cf_r1_r2 - metrics.n01_cf_r1_r2 == 29
    assert metrics.total_z_c == metrics.total_z_r - 8
    assert (
        metrics.noncontributing_units_c * metrics.work_units_r
        == metrics.noncontributing_units_r * metrics.work_units_c
    )
    assert (
        metrics.human_half_minute_units_c * metrics.total_z_r
        == metrics.human_half_minute_units_r * metrics.total_z_c
    )
    assert (
        10 * metrics.provider_tokens_c * metrics.total_z_r
        <= 11 * metrics.provider_tokens_r * metrics.total_z_c
    )
    assert (
        10 * (metrics.provider_tokens_c + 1) * metrics.total_z_r
        > 11 * metrics.provider_tokens_r * metrics.total_z_c
    )
    assert (
        10 * metrics.tool_calls_c * metrics.total_z_r
        <= 11 * metrics.tool_calls_r * metrics.total_z_c
    )
    assert (
        10 * (metrics.tool_calls_c + 1) * metrics.total_z_r
        > 11 * metrics.tool_calls_r * metrics.total_z_c
    )
    assert (
        metrics.human_half_minute_units_c - metrics.human_half_minute_units_f
        == 40 * (metrics.total_z_c - metrics.total_z_f)
    )
    low_c_maps = {
        REGIMES[0]: 129,
        REGIMES[1]: 129,
        REGIMES[2]: 130,
    }
    low_c_failures = {
        FAILURES[0]: 129,
        FAILURES[1]: 129,
        FAILURES[2]: 130,
    }
    low_c_identity = {
        "total_z_c": 388,
        "z_c_by_regime": low_c_maps,
        "z_c_by_failure": low_c_failures,
        "total_z_f": 344,
    }
    mcnemar_false_update = {"n10_cf": 29, "n01_cf": 18, "total_z_f": 378}
    mcnemar_false = replace(metrics, **mcnemar_false_update)
    r0_n10 = mcnemar_false.n10_cf - mcnemar_false.n10_cf_r1_r2
    r0_n01 = mcnemar_false.n01_cf - mcnemar_false.n01_cf_r1_r2
    r0_both1 = mcnemar_false.z_c_by_regime[REGIMES[0]] - r0_n10
    r0_both0 = 144 - r0_both1 - r0_n10 - r0_n01
    assert (r0_both1, r0_n10, r0_n01, r0_both0) == (123, 0, 18, 3)
    assert statistics.exact_one_sided_mcnemar(29, 18) == pytest.approx(
        _exact_binomial_upper_tail(29, 47)
    )
    mutations = (
        ("z_c_rate", low_c_identity),
        ("accepted_c_rate", {**low_c_identity, "accepted_c": 388}),
        ("recovered_c_rate", {**low_c_identity, "recovered_c": 388}),
        (
            "z_c_by_regime",
            {
                "z_c_by_regime": {
                    REGIMES[0]: 122,
                    REGIMES[1]: 124,
                    REGIMES[2]: 143,
                }
            },
        ),
        (
            "z_c_by_failure",
            {
                "z_c_by_failure": {
                    FAILURES[0]: 122,
                    FAILURES[1]: 124,
                    FAILURES[2]: 143,
                }
            },
        ),
        (
            "delta_c_vs_f",
            {"n10_cf": 43, "n01_cf": 0, "total_z_f": 346},
        ),
        (
            "mcnemar_c_vs_f",
            mcnemar_false_update,
        ),
        (
            "delta_c_vs_f_r1_r2",
            {"n10_cf_r1_r2": 28, "n01_cf_r1_r2": 0},
        ),
        (
            "restart_guardrail",
            low_c_identity,
        ),
        (
            "duplicate_work_ratio",
            {"noncontributing_units_c": metrics.noncontributing_units_c + 1},
        ),
        (
            "human_minutes_per_z",
            {"human_half_minute_units_c": (metrics.human_half_minute_units_c + 1)},
        ),
        (
            "provider_tokens_per_z",
            {"provider_tokens_c": metrics.provider_tokens_c + 1},
        ),
        (
            "tool_calls_per_z",
            {"tool_calls_c": metrics.tool_calls_c + 1},
        ),
        (
            "preserved_prefix",
            {"preserved_prefix_count_c": metrics.preserved_prefix_count_c - 1},
        ),
        (
            "incremental_human_per_net_recovered",
            {"human_half_minute_units_f": (metrics.human_half_minute_units_f - 1)},
        ),
        ("no_duplicate_effects", {"duplicate_logical_side_effects_all": 1}),
        ("no_severe_safety_breach", {"severe_safety_breaches_all": 1}),
    )
    assert {gate for gate, _ in mutations} == set(result)
    for gate, update in mutations:
        mutated = statistics.evaluate_met_gates(replace(metrics, **update))
        assert mutated[gate] is False, gate
    assert result["restart_guardrail"]

    huge = 2**54
    exact_ratio_boundaries = {
        "duplicate_work_ratio": replace(
            metrics,
            noncontributing_units_c=389 * huge,
            work_units_c=3890 * huge,
            noncontributing_units_r=397 * huge,
            work_units_r=3970 * huge,
        ),
        "human_minutes_per_z": replace(
            metrics,
            human_half_minute_units_c=389 * huge,
            human_half_minute_units_r=397 * huge,
        ),
        "provider_tokens_per_z": replace(
            metrics,
            provider_tokens_c=389 * 11 * huge,
            provider_tokens_r=397 * 10 * huge,
        ),
        "tool_calls_per_z": replace(
            metrics,
            tool_calls_c=389 * 11 * huge,
            tool_calls_r=397 * 10 * huge,
        ),
        "incremental_human_per_net_recovered": replace(
            metrics,
            human_half_minute_units_c=huge + 1945,
            human_half_minute_units_f=huge + 185,
        ),
    }
    plus_one_fields = {
        "duplicate_work_ratio": "noncontributing_units_c",
        "human_minutes_per_z": "human_half_minute_units_c",
        "provider_tokens_per_z": "provider_tokens_c",
        "tool_calls_per_z": "tool_calls_c",
        "incremental_human_per_net_recovered": "human_half_minute_units_c",
    }
    for gate, boundary in exact_ratio_boundaries.items():
        assert statistics.evaluate_met_gates(boundary)[gate], gate
        field_name = plus_one_fields[gate]
        plus_one = replace(
            boundary,
            **{field_name: getattr(boundary, field_name) + 1},
        )
        assert not statistics.evaluate_met_gates(plus_one)[gate], gate
    gate_tree = ast.parse(inspect.getsource(statistics.evaluate_met_gates))
    assert not any(isinstance(node, ast.Div) for node in ast.walk(gate_tree))


def test_pooled_power_table_is_exact_and_never_claims_floor_power() -> None:
    statistics = _module("statistics")

    assert statistics.POOLED_POWER_TABLE == {
        0.60: 0.911,
        0.75: 0.885,
        0.90: 0.863,
        1.00: 0.856,
    }
    assert statistics.POOLED_POWER_EFFECT == 0.15
    assert statistics.EFFECT_FLOOR == 0.10
    assert statistics.power_at_effect_floor() == pytest.approx(0.50, abs=0.02)


@pytest.mark.parametrize(
    "invalid_case",
    (
        "not_tuple",
        "tuple_subclass",
        "empty",
        "missing",
        "duplicate",
        "foreign_coordinate",
        "wrong_cell_type",
        "cell_subclass",
        "wrong_n",
        "bool_n",
        "negative_probability",
        "nan_probability",
        "infinite_probability",
        "over_one_probability",
        "probability_sum_over_one",
    ),
)
def test_stratified_dp_rejects_invalid_inputs_before_calculation(
    monkeypatch: pytest.MonkeyPatch,
    invalid_case: str,
) -> None:
    statistics = _module("statistics")
    alternative = statistics.FROZEN_STRATIFIED_ALTERNATIVE

    class CalculationReached(AssertionError):
        pass

    class TupleSubclass(tuple):
        pass

    class CellSubclass(statistics.StratifiedCell):
        pass

    def reject_calculation(*_args: object, **_kwargs: object) -> float:
        raise CalculationReached("invalid DP input reached the expensive calculation")

    monkeypatch.setattr(statistics, "_cell_multinomial_prob", reject_calculation)
    first = alternative[0]
    replacements: dict[str, object] = {
        "missing": alternative[:-1],
        "duplicate": (*alternative[:-1], alternative[0]),
        "foreign_coordinate": (
            replace(first, family="UNDECLARED"),
            *alternative[1:],
        ),
        "wrong_cell_type": (SimpleNamespace(**first.__dict__), *alternative[1:])
        if hasattr(first, "__dict__")
        else (
            SimpleNamespace(
                family=first.family,
                regime=first.regime,
                failure=first.failure,
                n=first.n,
                p10=first.p10,
                p01=first.p01,
            ),
            *alternative[1:],
        ),
        "cell_subclass": (
            CellSubclass(
                first.family,
                first.regime,
                first.failure,
                first.n,
                first.p10,
                first.p01,
            ),
            *alternative[1:],
        ),
        "wrong_n": (replace(first, n=7), *alternative[1:]),
        "bool_n": (replace(first, n=True), *alternative[1:]),
        "negative_probability": (replace(first, p10=-0.01), *alternative[1:]),
        "nan_probability": (replace(first, p10=float("nan")), *alternative[1:]),
        "infinite_probability": (
            replace(first, p10=float("inf")),
            *alternative[1:],
        ),
        "over_one_probability": (replace(first, p10=1.01), *alternative[1:]),
        "probability_sum_over_one": (
            replace(first, p10=0.6, p01=0.5),
            *alternative[1:],
        ),
    }
    if invalid_case == "not_tuple":
        invalid = list(alternative)
    elif invalid_case == "tuple_subclass":
        invalid = TupleSubclass(alternative)
    elif invalid_case == "empty":
        invalid = ()
    else:
        invalid = replacements[invalid_case]
    with pytest.raises((TypeError, ValueError)):
        statistics.stratified_exact_dp_power(invalid)


def test_explicit_54_cell_alternative_and_exact_dp_power_are_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statistics = _module("statistics")
    alternative = statistics.FROZEN_STRATIFIED_ALTERNATIVE

    assert len(alternative) == 54
    assert {(cell.family, cell.regime, cell.failure) for cell in alternative} == set(
        (family, regime, failure)
        for family in FAMILIES
        for regime in REGIMES
        for failure in FAILURES
    )
    assert all(cell.n == 8 for cell in alternative)
    assert all(
        (cell.p10, cell.p01) == (0.375, 0.375)
        for cell in alternative
        if cell.regime == "R0_DIRECT_REFRESH"
    )
    assert all(
        (cell.p10, cell.p01) == (0.4875, 0.2625)
        for cell in alternative
        if cell.regime != "R0_DIRECT_REFRESH"
    )
    assert all(cell.p10 + cell.p01 == pytest.approx(0.75) for cell in alternative)
    weighted_delta = sum(cell.n * (cell.p10 - cell.p01) for cell in alternative) / 432
    assert weighted_delta == pytest.approx(0.15)
    assert statistics.STRATIFIED_ASSUMPTIONS == (
        "conditional_case_independence_within_full_cell",
        "exchangeability_of_c_only_and_f_only_under_cellwise_null",
        "fixed_equal_weight_family_regime_failure_mixture",
    )
    report = statistics.stratified_exact_dp_power(alternative)
    assert report.method == "exact_dynamic_program"
    assert report.total_instances == 432
    assert report.integer_effect_gate == 44
    assert report.applies_integer_margin_gate is True
    assert report.applies_one_sided_exact_mcnemar is True
    assert report.alpha == 0.05
    assert report.power == pytest.approx(0.8868054844443183)
    assert report.power >= 0.80
    null = tuple(replace(cell, p10=cell.p01) for cell in alternative)
    assert statistics.stratified_exact_dp_power(null).power < report.power
    monkeypatch.setattr(
        statistics,
        "joint_primary_accepts",
        lambda *, n10, n01, total: n10 == 0,
    )
    expected_zero_c_only_probability = (1 - 0.375) ** 144 * (1 - 0.4875) ** 288
    assert statistics.stratified_exact_dp_power(alternative).power == pytest.approx(
        expected_zero_c_only_probability,
        rel=1e-12,
        abs=1e-300,
    )


def test_secondary_holm_family_is_closed_stable_and_non_authoritative() -> None:
    statistics = _module("statistics")
    assert statistics.SECONDARY_HYPOTHESIS_IDS == SECONDARY_HYPOTHESIS_IDS
    assert statistics.SECONDARY_ALPHA == 0.05
    raw = {hypothesis_id: 0.5 for hypothesis_id in SECONDARY_HYPOTHESIS_IDS}
    tied = sorted(SECONDARY_HYPOTHESIS_IDS)[:2]
    raw[tied[0]] = 0.001
    raw[tied[1]] = 0.001
    raw[sorted(SECONDARY_HYPOTHESIS_IDS)[2]] = 0.01
    forward = statistics.holm_secondary(raw)
    backward = statistics.holm_secondary(dict(reversed(tuple(raw.items()))))
    assert forward == backward
    assert tuple(item.hypothesis_id for item in forward) == tuple(
        sorted(SECONDARY_HYPOTHESIS_IDS, key=lambda item: (raw[item], item))
    )
    assert all(
        tuple(field.name for field in fields(item))
        == ("hypothesis_id", "raw_p", "adjusted_p", "reject")
        for item in forward
    )
    by_id = {item.hypothesis_id: item for item in forward}
    assert by_id[tied[0]].adjusted_p == pytest.approx(0.012)
    assert by_id[tied[1]].adjusted_p == pytest.approx(0.012)
    assert by_id[tied[0]].reject is True
    assert by_id[tied[1]].reject is True
    assert all(
        left.adjusted_p <= right.adjusted_p for left, right in zip(forward, forward[1:])
    )
    assert all(0.0 <= item.adjusted_p <= 1.0 for item in forward)
    assert forward[-1].adjusted_p == 1.0
    assert statistics.primary_disposition(True, forward) == "MET"
    assert statistics.primary_disposition(False, forward) == "NOT_MET"

    class DictSubclass(dict):
        pass

    class FloatSubclass(float):
        pass

    with pytest.raises(TypeError):
        statistics.holm_secondary(MappingProxyType(raw))
    with pytest.raises(TypeError):
        statistics.holm_secondary(DictSubclass(raw))
    with pytest.raises(ValueError):
        statistics.holm_secondary({key: raw[key] for key in raw if key != tied[0]})
    with pytest.raises(ValueError):
        statistics.holm_secondary({**raw, "family:undeclared": 0.001})
    first_id = sorted(SECONDARY_HYPOTHESIS_IDS)[0]
    for invalid_p in (
        True,
        0,
        FloatSubclass(0.5),
        float("nan"),
        float("inf"),
        -0.001,
        1.001,
    ):
        error = TypeError if type(invalid_p) is not float else ValueError
        with pytest.raises(error):
            statistics.holm_secondary({**raw, first_id: invalid_p})

    ordered_ids = sorted(SECONDARY_HYPOTHESIS_IDS)
    step_down_raw = {hypothesis_id: 0.5 for hypothesis_id in ordered_ids}
    step_down_raw[ordered_ids[0]] = 0.0042
    step_down_raw[ordered_ids[1]] = 0.0043
    step_down = statistics.holm_secondary(step_down_raw)
    assert step_down[0].adjusted_p == pytest.approx(0.0504)
    assert step_down[1].adjusted_p == pytest.approx(0.0504)
    assert step_down[0].reject is False
    assert step_down[1].reject is False

    tie_after_prefix_raw = dict(step_down_raw)
    tie_after_prefix_raw[ordered_ids[2]] = 0.0043
    tie_after_prefix = statistics.holm_secondary(tie_after_prefix_raw)
    assert [item.adjusted_p for item in tie_after_prefix[:3]] == pytest.approx(
        [0.0504, 0.0504, 0.0504]
    )
    assert [item.reject for item in tie_after_prefix[:3]] == [False, False, False]

    equality_raw = {hypothesis_id: 1.0 for hypothesis_id in ordered_ids}
    equality_raw[ordered_ids[0]] = 0.05 / len(ordered_ids)
    equality = statistics.holm_secondary(equality_raw)
    assert equality[0].adjusted_p == pytest.approx(0.05)
    assert equality[0].reject is True


@pytest.mark.parametrize("invalid_primary", (True, False, 1, 0, "MET", object()))
def test_primary_disposition_requires_an_exact_bool(invalid_primary: object) -> None:
    statistics = _module("statistics")
    if type(invalid_primary) is bool:
        expected = "MET" if invalid_primary else "NOT_MET"
        assert statistics.primary_disposition(invalid_primary, ()) == expected
    else:
        with pytest.raises(TypeError):
            statistics.primary_disposition(invalid_primary, ())


def test_every_frozen_automatic_park_condition_is_machine_enforced() -> None:
    evaluator = _module("evaluator")
    readiness = evaluator.D1Readiness.ready_fixture()
    assert evaluator.automatic_park_reasons(readiness) == ()
    assert evaluator.automatic_disposition(readiness) == "PROCEED"
    cases = {
        "parent_child_ids_separable": "PARENT_CHILD_IDS_NOT_SEPARABLE",
        "d1e_freeze_and_immutability_valid": "D1E_FREEZE_OR_IMMUTABILITY_INVALID",
        "fixed_builder_blind_before_materialization": "FIXED_BUILDER_NOT_BLIND",
        "environment_arm_neutral": "ENVIRONMENT_DIFFERS_BY_ARM",
        "matched_information_and_ceilings": "ARM_INFORMATION_OR_CEILING_MISMATCH",
        "restart_information_and_charge_parity": "RESTART_PARITY_MISSING",
        "evaluator_arm_blind": "EVALUATOR_ARM_DEPENDENT",
        "no_hidden_answer_channel": "HIDDEN_OR_MISSING_INFORMATION_ADVANTAGE",
        "prerequisite_chain_verified": "PUBLIC_PREREQUISITE_CHAIN_UNVERIFIED",
        "commit_reveal_generation_enforceable": "GENERATION_INTEGRITY_UNENFORCEABLE",
        "waiting_terminalization_verified": "WAITING_TERMINALIZATION_UNVERIFIED",
        "population_affordable_or_reversioned": "POPULATION_UNAFFORDABLE",
        "no_rescue_rules_intact": "NO_RESCUE_RULES_DRIFTED",
    }
    for field_name, reason in cases.items():
        changed = replace(readiness, **{field_name: False})
        assert evaluator.automatic_park_reasons(changed) == (reason,)
        assert evaluator.automatic_disposition(changed) == "PARK"
    skeptic = replace(readiness, skeptic_proved_same_budget_universal_dag=True)
    assert evaluator.automatic_park_reasons(skeptic) == (
        "SAME_BUDGET_UNIVERSAL_DAG_PROVED",
    )
    assert evaluator.automatic_disposition(skeptic) == "PARK_AS_SCHEDULE_ENGINEERING"


def test_d1e_manifest_is_immutable_environment_only_and_not_combined_d1() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    generator = _module("generator")
    regimes = _module("regimes")
    templates = _module("templates")
    statistics = _module("statistics")
    assert tuple(manifest) == (
        "prereg_id",
        "status",
        "schema_version",
        "stage",
        "claim_class",
        "immutable_after_freeze",
        "combined_d1_writes_forbidden",
        "future_combined_d1_spec_path",
        "future_d2_spec_path",
        "instance_count",
        "episode_count",
        "mechanism",
        "source_files",
        "test_files",
        "runtime_semantics",
        "population_design",
        "timing_contract",
        "budget_ceiling",
        "human_charges",
        "synthetic_rate_units",
        "no_rescue_rules",
        "secondary_hypothesis_ids",
        "required_binding_modes",
    )
    assert manifest["prereg_id"] == "LH-RECOVERY-1A-D1-E-ENVIRONMENT-PRECOMMIT"
    assert manifest["status"] == "IMPLEMENTED_NOT_FROZEN"
    assert manifest["schema_version"] == "lh1a-d1e-source-manifest-v1"
    assert manifest["stage"] == "D1-E"
    assert manifest["claim_class"] == "product-eval-design-only"
    assert manifest["immutable_after_freeze"] is True
    assert manifest["combined_d1_writes_forbidden"] is True
    assert manifest["future_combined_d1_spec_path"] == (
        "docs/research/LH-RECOVERY-1A-COMBINED-D1-PRECOMMIT.yaml"
    )
    assert manifest["future_d2_spec_path"] == (
        "docs/research/LH-RECOVERY-1A-preregistration-spec.yaml"
    )
    assert manifest["future_combined_d1_spec_path"] != MANIFEST_RELATIVE_PATH
    assert manifest["future_d2_spec_path"] != MANIFEST_RELATIVE_PATH
    assert manifest["future_combined_d1_spec_path"] != manifest["future_d2_spec_path"]
    assert manifest["instance_count"] == 432
    assert manifest["episode_count"] == 1728
    assert tuple(manifest["source_files"]) == tuple(
        f"product_evals/lh_recovery_1a/{name}.py" for name in MODULE_NAMES
    )
    assert manifest["test_files"] == ["tests/product_eval/test_lh1a_design.py"]
    mechanism = manifest["mechanism"]
    assert tuple(mechanism) == ("name", "channel_claim", "files")
    assert mechanism["name"] == "LH-RECOVERY-1A D1-E environment source"
    assert mechanism["channel_claim"] == "other(product-eval)"
    assert tuple(mechanism["files"]) == (
        MANIFEST_RELATIVE_PATH,
        *(f"product_evals/lh_recovery_1a/{name}.py" for name in MODULE_NAMES),
        "tests/product_eval/test_lh1a_design.py",
        *RUNTIME_SOURCE_PATHS,
    )
    assert len(set(mechanism["files"])) == 11
    assert all(
        isinstance(path, str)
        and path.strip()
        and not Path(path).is_absolute()
        and ".." not in Path(path).parts
        for path in mechanism["files"]
    )
    assert "fixed_baseline.py" not in json.dumps(manifest, sort_keys=True)
    assert manifest["required_binding_modes"] == {
        "event": "runner_anchored_team_events",
        "permission": "matching_request_and_approval_rows",
        "product": "live_git_head_and_clean_worktree",
        "runner": "live_git_head_and_exported_schema",
        "spine": "verified_prereg_lock_and_result",
    }

    def dataclass_json(value: object) -> dict[str, object]:
        return json.loads(
            json.dumps(
                {field.name: getattr(value, field.name) for field in fields(value)}
            )
        )

    assert manifest["population_design"] == dataclass_json(generator.POPULATION_DESIGN)
    assert manifest["timing_contract"] == dataclass_json(regimes.TIMING_CONTRACT)
    assert manifest["budget_ceiling"] == dataclass_json(templates.BUDGET_CEILINGS["C"])
    assert manifest["human_charges"] == dataclass_json(templates.HUMAN_CHARGES)
    assert manifest["synthetic_rate_units"] == dataclass_json(
        templates.SYNTHETIC_RATE_UNITS
    )
    assert manifest["no_rescue_rules"] == list(NO_RESCUE_RULES)
    assert manifest["secondary_hypothesis_ids"] == list(
        statistics.SECONDARY_HYPOTHESIS_IDS
    )
    raw_manifest = MANIFEST_PATH.read_text(encoding="utf-8")
    forbidden_static_binding = re.compile(
        r"(?i)(?:perm_[0-9a-f]+|spine[-_]e2e[-_]?\d+|"
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|"
        r"(?<![0-9a-f])(?:[0-9a-f]{40}|[0-9a-f]{64})(?![0-9a-f])|"
        r"lh[-_]recovery[-_]1a[^\n\"']*\d{8})"
    )
    assert forbidden_static_binding.search(raw_manifest) is None
    for forbidden_text in (
        "approval_requests.jsonl",
        "approvals.jsonl",
        "handoff.jsonl",
        "messages.jsonl",
        "receipt_ref",
        "runner_head",
        "target_head",
    ):
        assert forbidden_text not in raw_manifest


def test_manifest_declares_live_runtime_source_shape_and_public_semantics() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    generator = _module("generator")
    semantics = manifest["runtime_semantics"]
    assert semantics == {
        "conditional_edges_forbidden_in_d1e_templates": True,
        "edge_condition_consumption": (
            "DECLARED_IN_EDGE_SPEC_BUT_NOT_CONSUMED_BY_EXECUTOR"
        ),
        "provider_capability": "provider.chat",
        "source_paths": list(RUNTIME_SOURCE_PATHS),
        "tool_capability_registry": "WorkspaceSandbox.specs",
        "wait_signal_binding": "CONCRETE_NODE_SIGNAL_NAME_AND_CORRELATION_KEY",
    }
    assert all((REPO_ROOT / path).is_file() for path in RUNTIME_SOURCE_PATHS)

    workflow_source = (REPO_ROOT / RUNTIME_SOURCE_PATHS[0]).read_text(encoding="utf-8")
    execution_source = (REPO_ROOT / RUNTIME_SOURCE_PATHS[1]).read_text(encoding="utf-8")
    task_service_source = (REPO_ROOT / RUNTIME_SOURCE_PATHS[2]).read_text(
        encoding="utf-8"
    )
    assert "class EdgeSpec" in workflow_source and "condition:" in workflow_source
    assert "edge.condition" not in execution_source
    assert "def _ordered_nodes" in execution_source
    assert "node.wait_signal_name" in task_service_source
    assert "node.wait_correlation_key" in task_service_source

    successor = json.loads(SUCCESSOR_PATH.read_text(encoding="utf-8"))
    assert successor["status"] == "TEST_MAINTENANCE_ONLY"
    assert successor["claim_effect"] == "NO_RESULT_CHANGE / NO_CLAIM_UPGRADE"
    assert successor["supersedes_runtime_shape_only"] == MANIFEST_RELATIVE_PATH
    assert (
        successor["frozen_parent_sha256"]
        == hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
    )
    assert successor["tool_capability_registry"] == "DeveloperWorkspaceAdapter.specs"
    assert (
        successor["capability_source"]
        == "domain_packs/developer_agent/workspace_capability.py"
    )
    capability_source = (REPO_ROOT / successor["capability_source"]).read_text(
        encoding="utf-8"
    )
    assert "class DeveloperWorkspaceAdapter" in capability_source
    for capability in (
        "workspace.read",
        "workspace.apply_patch",
        "workspace.run_tests",
    ):
        assert capability in capability_source

    forbidden_keys = {
        "identity_bindings",
        "runner_event_fields",
        "source_bindings",
        "receipt_ref",
        "approval_requests_jsonl_sha256",
        "approvals_jsonl_sha256",
        "handoff_jsonl_sha256",
        "messages_jsonl_sha256",
    }
    assert _all_mapping_keys(manifest).isdisjoint(forbidden_keys)
    assert generator.detect_forbidden_digest_bindings(manifest) == ()


def test_whole_ledger_digest_detection_is_recursive_generic_and_ast_aware() -> None:
    generator = _module("generator")
    _assert_forbidden_digest_detector_core(generator)
    for name in MODULE_NAMES:
        source = (D1E_ROOT / f"{name}.py").read_text(encoding="utf-8")
        assert generator.detect_forbidden_digest_ast(source) == ()


def test_forbidden_pre_d1_artifact_scan_is_recursive_across_arbitrary_roots(
    tmp_path: Path,
    generator_subject: tuple[ModuleType, str],
) -> None:
    generator, _source = generator_subject
    assert generator.FORBIDDEN_PRE_D1_BASENAMES == FORBIDDEN_PRE_D1_BASENAMES
    assert generator.FORBIDDEN_PRE_D1_PATTERNS == FORBIDDEN_PRE_D1_PATTERNS

    source_root = tmp_path / "source"
    docs_root = tmp_path / "docs/research"
    build_run_root = tmp_path / "build-run"
    governance_root = tmp_path / "governance-run"
    source_root.mkdir(parents=True)
    docs_root.mkdir(parents=True)
    build_run_root.mkdir()
    governance_root.mkdir()
    injected_roots = (source_root, docs_root, build_run_root, governance_root)
    for root, relative_path in zip(
        injected_roots,
        (
            "allowed/notes.md",
            "allowed/seed-policy.md",
            "allowed/candidate.txt",
            "allowed/baseline-not-fixed.py",
        ),
    ):
        decoy = root / relative_path
        decoy.parent.mkdir(parents=True)
        decoy.write_text("allowed", encoding="utf-8")
    assert generator.scan_forbidden_pre_d1_artifacts(*injected_roots) == ()

    single_forbidden = source_root / "partial/deep/tree/root_seed.bin"
    single_forbidden.parent.mkdir(parents=True)
    single_forbidden.write_text("forbidden", encoding="utf-8")
    assert generator.scan_forbidden_pre_d1_artifacts(*injected_roots) == (
        str(single_forbidden),
    )
    single_forbidden.unlink()
    assert generator.scan_forbidden_pre_d1_artifacts(*injected_roots) == ()

    injected = set(FORBIDDEN_PRE_D1_BASENAMES) | {
        "root_seed.bin",
        "environment_nonce.txt",
        "reviewer_nonce.commitment",
        "materialized_corpus.json",
        "blind_provider_bank.json",
        "oracle_report.json",
        "sealed-fixed-dag.json",
        "candidate-d1-f.packet",
        "lh1a_d2_prereg.json",
    }
    injected_paths: set[Path] = set()
    for index, basename in enumerate(sorted(injected)):
        target_root = injected_roots[index % len(injected_roots)]
        depth = 1 + ((index // len(injected_roots)) % 3)
        nested_parent = target_root.joinpath(
            *(f"nested-{index}-level-{level}" for level in range(1, depth + 1))
        )
        nested_parent.mkdir(parents=True)
        injected_path = nested_parent / basename
        injected_path.write_text(
            "forbidden",
            encoding="utf-8",
        )
        injected_paths.add(injected_path)
    for duplicate_root, basename in (
        (docs_root, "fixed_baseline.py"),
        (governance_root, "root_seed.bin"),
    ):
        duplicate_path = duplicate_root / "duplicate/deeper" / basename
        duplicate_path.parent.mkdir(parents=True, exist_ok=True)
        duplicate_path.write_text("forbidden duplicate", encoding="utf-8")
        injected_paths.add(duplicate_path)
    assert len(injected_paths) == len(injected) + 2
    assert all(path.parent not in injected_roots for path in injected_paths)
    assert all(
        any(path.is_file() for path in root.rglob("*")) for root in injected_roots
    )
    expected_paths = tuple(sorted(str(path) for path in injected_paths))
    detected = generator.scan_forbidden_pre_d1_artifacts(*injected_roots)
    assert detected == expected_paths

    removed_path = sorted(injected_paths, key=str)[len(injected_paths) // 2]
    removed_path.unlink()
    remaining_paths = tuple(
        sorted(str(path) for path in injected_paths if path != removed_path)
    )
    assert generator.scan_forbidden_pre_d1_artifacts(*injected_roots) == remaining_paths


def test_d1e_source_has_no_early_material_old_identity_or_digest_constants() -> None:
    missing = [name for name in MODULE_NAMES if not (D1E_ROOT / f"{name}.py").is_file()]
    assert missing == []
    forbidden_module_bindings = {
        "ROOT_SEED",
        "CORPUS",
        "ASSIGNMENTS",
        "PROVIDER_BANK",
        "NONCES",
        "ENVIRONMENT_NONCE",
        "REVIEWER_NONCE",
        "FUTURE_ANSWERS",
        "RUNNER_EVENT_FIELDS",
        "MUTABLE_LEDGER_SHA256",
        "PERMISSION_REQUEST_ID",
        "PERMISSION_APPROVAL_ID",
        "PRODUCT_TARGET_HEAD",
        "RUNNER_TARGET_HEAD",
        "SPINE_RESULT_SHA256",
    }
    for basename in FORBIDDEN_PRE_D1_BASENAMES:
        assert not (D1E_ROOT / basename).exists()
    digest_or_row_literal = re.compile(
        r"(?i)(?<![0-9a-f])(?:[0-9a-f]{40}|[0-9a-f]{64})(?![0-9a-f])|perm_[0-9a-f]+"
    )
    predecessor_identity = re.compile(r"(?i)spine[-_]e2e[-_]?\d+")
    uuid_literal = re.compile(
        r"(?i)[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}"
    )
    static_run_identity = re.compile(r"(?i)lh[-_]recovery[-_]1a[^\n\"']*\d{8}")
    for name in MODULE_NAMES:
        path = D1E_ROOT / f"{name}.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assigned = {
            target.id
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets if isinstance(node, ast.Assign) else (node.target,)
            )
            if isinstance(target, ast.Name)
        }
        assert assigned.isdisjoint(forbidden_module_bindings)
        assert digest_or_row_literal.search(source) is None
        assert predecessor_identity.search(source) is None
        assert uuid_literal.search(source) is None
        assert static_run_identity.search(source) is None
        assert "runner_event_fields" not in source.lower()
    evaluator_source = (D1E_ROOT / "evaluator.py").read_text(encoding="utf-8")
    assert "runner event" not in evaluator_source.lower()
    assert "approval_requests.jsonl" not in evaluator_source
    assert "approvals.jsonl" not in evaluator_source
