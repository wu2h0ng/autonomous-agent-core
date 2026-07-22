from __future__ import annotations

import enum
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from agent_os_contracts import (
    HelpBudget,
    HelpBurdenReceipt,
    SrlEnvironmentEvent,
    SrlHelpRequest,
)


class ArmRole(str, enum.Enum):
    """Experimental arm identity for R-SRL-1."""

    BASELINE_SCHEDULED = "baseline_scheduled"
    BASELINE_USER_DRIVEN = "baseline_user_driven"
    SRL = "srl"
    ABLATION_PERSISTENT_STATE = "ablation_persistent_state"


@dataclass(frozen=True)
class ArmEnvelope:
    """Capability envelope for a single experimental arm.

    Baseline arms receive equivalent read access to public bytes but may not
    emit SRL-internal structures.  Arm 3 (SRL) may use the full structured
    vocabulary.
    """

    role: ArmRole
    allowed_srl_type_names: set[str] = field(default_factory=set)
    can_use_srl_structures: bool = False


SRL_INTERNAL_TYPE_NAMES: frozenset[str] = frozenset(
    {
        "SrlRelevanceAssessment",
        "SrlEnvironmentEvent",
        "SrlOperationalProjectionRef",
        "SrlRelevanceDisposition",
        "SrlHelpRequest",
        "SrlHelpResponse",
        "SrlHelpResponseKind",
        "StandingMission",
        "Mandate",
        "MandateEnvelope",
        "MandateRatificationReceipt",
        "AgentInstanceRef",
        "Commitment",
        "Goal",
        "Program",
        "Task",
    }
)


def _default_arm_envelopes() -> dict[str, ArmEnvelope]:
    """Return the canonical R-SRL-1 four-arm envelope mapping."""
    all_srl = set(SRL_INTERNAL_TYPE_NAMES)
    return {
        "arm1": ArmEnvelope(
            role=ArmRole.BASELINE_SCHEDULED,
            allowed_srl_type_names=set(),
            can_use_srl_structures=False,
        ),
        "arm2": ArmEnvelope(
            role=ArmRole.BASELINE_USER_DRIVEN,
            allowed_srl_type_names=set(),
            can_use_srl_structures=False,
        ),
        "arm3": ArmEnvelope(
            role=ArmRole.SRL,
            allowed_srl_type_names=all_srl,
            can_use_srl_structures=True,
        ),
        "arm4": ArmEnvelope(
            role=ArmRole.ABLATION_PERSISTENT_STATE,
            allowed_srl_type_names=set(),
            can_use_srl_structures=False,
        ),
    }


CANONICAL_ARM_IDS: frozenset[str] = frozenset(_default_arm_envelopes())


def _validate_matched_arm_budgets(budgets: dict[str, ArmBudget]) -> None:
    """Require four-arm scoring configurations to use identical budgets."""
    if len(budgets) <= 1:
        return
    configured = set(budgets)
    if configured != CANONICAL_ARM_IDS:
        missing = sorted(CANONICAL_ARM_IDS - configured)
        extra = sorted(configured - CANONICAL_ARM_IDS)
        raise ValueError(
            "R-SRL scoring budgets must configure exactly arm1-arm4; "
            f"missing={missing}, extra={extra}"
        )
    first_arm = "arm1"
    expected = budgets[first_arm]
    mismatched = sorted(
        arm_id for arm_id, budget in budgets.items() if budget != expected
    )
    if mismatched:
        raise ValueError(
            "R-SRL scoring budgets must be identical across arm1-arm4; "
            f"mismatched={mismatched}"
        )


def _model_dump_tree(obj: Any) -> Any:
    """Recursively convert pydantic models into plain dict/list primitives."""
    if hasattr(obj, "model_dump"):
        return _model_dump_tree(obj.model_dump())
    if hasattr(obj, "dict"):
        return _model_dump_tree(obj.dict())
    if isinstance(obj, dict):
        return {k: _model_dump_tree(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_model_dump_tree(item) for item in obj]
    return obj


def _contains_srl_type_name(obj: Any, names: set[str]) -> bool:
    """Return True if any dict key or string value exactly matches a type name."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str) and key in names:
                return True
            if _contains_srl_type_name(value, names):
                return True
        return False
    if isinstance(obj, list):
        return any(_contains_srl_type_name(item, names) for item in obj)
    if isinstance(obj, str):
        return obj in names
    return False


@dataclass(frozen=True)
class FrozenUnit:
    unit_id: str
    repository_lineage: str
    arm_budget_seconds: int
    counts_toward_gate: bool
    manifest: dict[str, str]
    build_commands: tuple[tuple[str, ...], ...]
    snapshot_path: Path
    mission_path: Path
    events_path: Path
    expected_outcomes_path: Path


@dataclass(frozen=True)
class ArmBudget:
    max_llm_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_retries: int
    max_tool_invocations: int
    max_wall_seconds: float


@dataclass(frozen=True)
class BudgetEntry:
    """Immutable charge entry for the arm/unit budget ledger.

    ``kind`` is one of the canonical budget dimensions; ``amount`` is the
    quantity to add (calls, tokens, retries, tool invocations, or elapsed
    wall seconds).
    """

    kind: Literal[
        "llm_call",
        "input_tokens",
        "output_tokens",
        "retry",
        "tool_invocation",
        "wall_seconds",
    ]
    amount: int | float

    @classmethod
    def llm_call(cls, calls: int = 1) -> BudgetEntry:
        return cls(kind="llm_call", amount=calls)

    @classmethod
    def input_tokens(cls, tokens: int) -> BudgetEntry:
        return cls(kind="input_tokens", amount=tokens)

    @classmethod
    def output_tokens(cls, tokens: int) -> BudgetEntry:
        return cls(kind="output_tokens", amount=tokens)

    @classmethod
    def retry(cls, retries: int = 1) -> BudgetEntry:
        return cls(kind="retry", amount=retries)

    @classmethod
    def tool_invocation(cls, invocations: int = 1) -> BudgetEntry:
        return cls(kind="tool_invocation", amount=invocations)

    @classmethod
    def wall_seconds(cls, seconds: float) -> BudgetEntry:
        return cls(kind="wall_seconds", amount=seconds)


class BudgetExceeded(Exception):
    """Raised when an arm/unit exceeds its frozen budget."""


@dataclass(frozen=True)
class TestReport:
    test_path: str
    passed: bool
    artifact_ref: str
    stdout: str
    stderr: str


@dataclass(frozen=True)
class TestResult:
    exit_code: int
    stdout: str
    stderr: str
    reports: tuple[TestReport, ...]


@dataclass(frozen=True)
class BuildResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class RestartState:
    """Serializable snapshot of SRL runtime state used for restart equivalence.

    Fields are intentionally primitive (digests, tuples, ISO strings) so the
    comparator can be deterministic across export/import cycles.
    """

    commitment_portfolio_digest: str
    active_goals: tuple[str, ...]
    pending_help_request_ids: tuple[str, ...]
    pending_help_request_expiry: tuple[str, ...]
    belief_checksums: tuple[str, ...]


def _parse_digest(value: str) -> tuple[str, str]:
    """Return (algorithm, hex_digest) from manifest entries.

    Supports both ``sha256:<hex>`` and bare hex strings.
    """
    text = str(value).strip()
    if ":" in text:
        algorithm, _, digest = text.partition(":")
        return algorithm.lower(), digest.strip()
    return "sha256", text


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_build_commands(raw: dict[str, Any], unit_file: Path) -> tuple[tuple[str, ...], ...]:
    commands = raw.get("build_commands", [["python", "-m", "compileall", "."]])
    if not isinstance(commands, list) or not commands:
        raise ValueError(f"unit.yaml build_commands must be a non-empty list: {unit_file}")
    parsed: list[tuple[str, ...]] = []
    for command in commands:
        if not isinstance(command, list) or not command:
            raise ValueError(
                f"unit.yaml build_commands entries must be non-empty lists: {unit_file}"
            )
        if not all(isinstance(part, str) and part for part in command):
            raise ValueError(
                f"unit.yaml build_commands entries must contain non-empty strings: {unit_file}"
            )
        parsed.append(tuple(command))
    return tuple(parsed)


def load_frozen_unit(unit_dir: Path) -> FrozenUnit:
    unit_file = unit_dir / "unit.yaml"
    if not unit_file.is_file():
        raise FileNotFoundError(f"missing unit.yaml in {unit_dir}")

    raw: dict[str, Any] = yaml.safe_load(unit_file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"unit.yaml must contain a mapping: {unit_file}")

    manifest = raw.get("manifest", {})
    if not isinstance(manifest, dict):
        raise ValueError(f"unit.yaml manifest must be a mapping: {unit_file}")
    if "counts_toward_gate" not in raw or not isinstance(
        raw["counts_toward_gate"], bool
    ):
        raise ValueError(
            f"unit.yaml counts_toward_gate must be an explicit boolean: {unit_file}"
        )

    snapshot_name = raw.get("snapshot_file", "snapshot.yaml")
    mission_name = raw.get("mission_file", "mission.yaml")
    events_name = raw.get("events_file", "events.yaml")
    expected_outcomes_name = raw.get("expected_outcomes_file", "expected_outcomes.yaml")

    snapshot_path = unit_dir / snapshot_name
    mission_path = unit_dir / mission_name
    events_path = unit_dir / events_name
    expected_outcomes_path = unit_dir / expected_outcomes_name

    for path in (snapshot_path, mission_path, events_path, expected_outcomes_path):
        if not path.is_file():
            raise FileNotFoundError(f"manifest references missing file: {path}")

    return FrozenUnit(
        unit_id=raw["unit_id"],
        repository_lineage=raw["repository_lineage"],
        arm_budget_seconds=int(raw["arm_budget_seconds"]),
        counts_toward_gate=raw["counts_toward_gate"],
        manifest={str(k): str(v) for k, v in manifest.items()},
        build_commands=_load_build_commands(raw, unit_file),
        snapshot_path=snapshot_path,
        mission_path=mission_path,
        events_path=events_path,
        expected_outcomes_path=expected_outcomes_path,
    )


def verify_manifest(unit: FrozenUnit) -> bool:
    for filename, expected_raw in unit.manifest.items():
        algorithm, expected_digest = _parse_digest(expected_raw)
        if algorithm != "sha256":
            raise ValueError(
                f"unsupported digest algorithm '{algorithm}' for {filename}"
            )
        path = unit.snapshot_path if filename == unit.snapshot_path.name else None
        path = path or (
            unit.mission_path if filename == unit.mission_path.name else None
        )
        path = path or (unit.events_path if filename == unit.events_path.name else None)
        path = path or (
            unit.expected_outcomes_path
            if filename == unit.expected_outcomes_path.name
            else None
        )
        if path is None:
            # Allow manifest entries for files not tracked by FrozenUnit (e.g. per-file sha256 sidecars).
            path = unit.snapshot_path.parent / filename
            if not path.is_file():
                raise FileNotFoundError(f"manifest entry not found: {filename}")
        actual_digest = _sha256_file(path)
        if actual_digest != expected_digest:
            raise ValueError(
                f"manifest mismatch for {filename}: expected {expected_digest}, got {actual_digest}"
            )
    return True


def _load_expected_outcome_map(expected_outcomes_path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(expected_outcomes_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"expected_outcomes.yaml must contain a mapping: {expected_outcomes_path}"
        )
    return raw


def validate_expected_outcomes_repo_consistency(
    unit: FrozenUnit, repo_files: dict[str, bytes]
) -> None:
    """Validate expected test selectors against frozen repository bytes."""
    expected_outcomes = _load_expected_outcome_map(unit.expected_outcomes_path)
    for event_id, expected in expected_outcomes.items():
        if not isinstance(expected, dict):
            raise ValueError(
                f"expected outcome for {event_id} must be a mapping: "
                f"{unit.expected_outcomes_path}"
            )
        test_path = expected.get("test_path")
        if test_path is None:
            continue
        if not isinstance(test_path, str) or not test_path:
            raise ValueError(
                f"expected outcome {event_id} test_path must be a non-empty string"
            )
        file_part = test_path.split("::", 1)[0]
        if _is_dangerous_path(file_part):
            raise PermissionError(
                f"expected outcome {event_id} test_path is not allowed: {test_path}"
            )
        if "::" not in test_path:
            raise ValueError(
                f"expected outcome {event_id} test_path must include a selector: "
                f"{test_path}"
            )
        selector = test_path.split("::", 1)[1]
        if file_part not in repo_files:
            raise FileNotFoundError(
                f"expected outcome {event_id} references missing repo test file: "
                f"{file_part}"
            )
        selector_name = selector.rsplit(".", 1)[-1]
        if not selector_name:
            raise ValueError(
                f"expected outcome {event_id} test_path selector is empty: {test_path}"
            )
        content = repo_files[file_part].decode("utf-8", errors="ignore")
        if f"def {selector_name}" not in content:
            raise ValueError(
                f"expected outcome {event_id} references missing test selector "
                f"{selector_name!r} in {file_part}"
            )


def load_events(events_path: Path) -> tuple[SrlEnvironmentEvent, ...]:
    raw: list[Any] = yaml.safe_load(events_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"events.yaml must contain a list: {events_path}")
    events = tuple(SrlEnvironmentEvent.model_validate(item) for item in raw)
    _validate_public_event_classes(events, events_path)
    return events


_FORBIDDEN_PUBLIC_EVENT_CLASS_TOKENS: frozenset[str] = frozenset(
    {
        "BELIEF",
        "COMMITMENT",
        "CONFLICT",
        "DECOY",
        "HELP",
        "INTERFACE",
        "MANDATORY",
        "MUST",
        "RESTART",
        "SCORE",
        "SCORER",
        "TEST",
        "UNCERTAINTY",
        "VERIFIED",
    }
)


def _validate_public_event_classes(
    events: tuple[SrlEnvironmentEvent, ...], events_path: Path
) -> None:
    """Ensure public event classes do not leak hidden scorer semantics."""
    for event in events:
        event_class = event.event_class.upper()
        leaked = sorted(
            token
            for token in _FORBIDDEN_PUBLIC_EVENT_CLASS_TOKENS
            if token in event_class
        )
        if leaked:
            raise ValueError(
                f"events.yaml event_class leaks hidden scorer semantics for "
                f"{event.event_id} in {events_path}: {event.event_class!r}"
            )


def _is_dangerous_path(path: str) -> bool:
    """Reject traversal and sensitive filenames."""
    if path.startswith("/") or ".." in path.split("/"):
        return True
    parts = Path(path).parts
    lowered = {p.lower() for p in parts}
    if "expected_outcomes" in lowered or "expected_outcomes.yaml" in lowered:
        return True
    if any(p.startswith("_log") or p.startswith(".") for p in parts):
        return True
    return False


def _is_runtime_residue_path(path: Path) -> bool:
    """Return True for test/build cache files excluded from arm workdirs."""
    parts = path.parts
    if any(part in {".pytest_cache", "__pycache__"} for part in parts):
        return True
    return path.suffix in {".pyc", ".pyo"}


def _validate_pytest_selector(selector: str) -> None:
    """Reject selector values that can alter pytest behavior or escape the repo."""
    if not selector:
        raise ValueError("pytest selector must not be empty")
    if selector.startswith("-"):
        raise PermissionError(f"pytest selector option is not allowed: {selector}")
    path_part = selector.split("::", 1)[0]
    if _is_dangerous_path(path_part):
        raise PermissionError(f"pytest selector path is not allowed: {selector}")


def _normalize_build_command(command: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if not command:
        raise ValueError("build command must not be empty")
    normalized = list(command)
    if Path(normalized[0]).name.startswith("python"):
        normalized[0] = "python"
    return tuple(normalized)


def _runtime_build_command(command: tuple[str, ...]) -> list[str]:
    if command and command[0] == "python":
        return [sys.executable, *command[1:]]
    return list(command)


class BudgetLedger:
    """Matched-arm budget ledger for R-SRL-1.

    Tracks LLM calls, tokens, retries, tool invocations and wall time per
    arm/unit.  Charges are cumulative; crossing any frozen budget dimension
    raises ``BudgetExceeded`` so the caller can mark the unit ``INVALID``.
    """

    def __init__(self, budgets: dict[str, ArmBudget]):
        self._budgets = dict(budgets)
        # Per (arm_id, unit_id) usage counters.
        self._usage: dict[tuple[str, str], dict[str, int | float]] = {}
        # Per (arm_id, unit_id) first-charge timestamp for wall-time accounting.
        self._start_times: dict[tuple[str, str], float] = {}

    def _ensure_slot(self, arm_id: str, unit_id: str) -> None:
        key = (arm_id, unit_id)
        if key not in self._usage:
            self._usage[key] = {
                "llm_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "retries": 0,
                "tool_invocations": 0,
                "wall_seconds": 0.0,
            }
        self._start_times.setdefault(key, time.monotonic())

    def _effective_wall_seconds(self, arm_id: str, unit_id: str) -> float:
        """Return max of charged wall seconds and real elapsed wall time."""
        key = (arm_id, unit_id)
        elapsed = time.monotonic() - self._start_times[key]
        return max(self._usage[key]["wall_seconds"], elapsed)

    def check_wall_time(self, arm_id: str, unit_id: str) -> None:
        """Raise BudgetExceeded if elapsed wall time has reached the budget."""
        self._ensure_slot(arm_id, unit_id)
        if arm_id not in self._budgets:
            return
        budget = self._budget_for(arm_id)
        effective = self._effective_wall_seconds(arm_id, unit_id)
        if effective >= budget.max_wall_seconds:
            raise BudgetExceeded(
                f"arm {arm_id} unit {unit_id} wall-clock budget exceeded: "
                f"{effective} >= {budget.max_wall_seconds}"
            )

    def _budget_for(self, arm_id: str) -> ArmBudget:
        if arm_id not in self._budgets:
            raise ValueError(f"no budget configured for arm_id: {arm_id}")
        return self._budgets[arm_id]

    def _check_budget(
        self,
        arm_id: str,
        unit_id: str,
        key: str,
        limit: int | float,
        used: int | float,
        amount: int | float,
    ) -> None:
        if used + amount > limit:
            raise BudgetExceeded(
                f"arm {arm_id} unit {unit_id} would exceed {key} budget: "
                f"{used} + {amount} > {limit}"
            )

    def charge(self, arm_id: str, unit_id: str, entry: BudgetEntry) -> None:
        """Apply a budget charge and hard-stop on any exceeded dimension."""
        self._ensure_slot(arm_id, unit_id)
        budget = self._budget_for(arm_id)
        usage = self._usage[(arm_id, unit_id)]
        effective_wall = self._effective_wall_seconds(arm_id, unit_id)
        if effective_wall >= budget.max_wall_seconds:
            raise BudgetExceeded(
                f"arm {arm_id} unit {unit_id} wall-clock budget exceeded: "
                f"{effective_wall} >= {budget.max_wall_seconds}"
            )

        mapping: dict[str, tuple[str, str, int | float]] = {
            "llm_call": ("llm_calls", "max_llm_calls", budget.max_llm_calls),
            "input_tokens": (
                "input_tokens",
                "max_input_tokens",
                budget.max_input_tokens,
            ),
            "output_tokens": (
                "output_tokens",
                "max_output_tokens",
                budget.max_output_tokens,
            ),
            "retry": ("retries", "max_retries", budget.max_retries),
            "tool_invocation": (
                "tool_invocations",
                "max_tool_invocations",
                budget.max_tool_invocations,
            ),
            "wall_seconds": (
                "wall_seconds",
                "max_wall_seconds",
                budget.max_wall_seconds,
            ),
        }
        usage_key, _budget_key, limit = mapping[entry.kind]
        used = effective_wall if entry.kind == "wall_seconds" else usage[usage_key]
        self._check_budget(arm_id, unit_id, usage_key, limit, used, entry.amount)
        usage[usage_key] = usage[usage_key] + entry.amount  # type: ignore[assignment]

    def remaining_wall_seconds(self, arm_id: str, unit_id: str) -> float:
        """Return remaining wall-time budget for the arm/unit."""
        self._ensure_slot(arm_id, unit_id)
        budget = self._budget_for(arm_id)
        return max(
            0.0,
            budget.max_wall_seconds - self._effective_wall_seconds(arm_id, unit_id),
        )

    def get_budget_summary(self, arm_id: str, unit_id: str) -> dict[str, Any]:
        """Return budget limits, current usage and remaining per dimension."""
        self._ensure_slot(arm_id, unit_id)
        budget = self._budget_for(arm_id)
        usage = self._usage[(arm_id, unit_id)]
        effective_wall = self._effective_wall_seconds(arm_id, unit_id)
        return {
            "budget": {
                "max_llm_calls": budget.max_llm_calls,
                "max_input_tokens": budget.max_input_tokens,
                "max_output_tokens": budget.max_output_tokens,
                "max_retries": budget.max_retries,
                "max_tool_invocations": budget.max_tool_invocations,
                "max_wall_seconds": budget.max_wall_seconds,
            },
            "used": dict(usage),
            "remaining": {
                "llm_calls": budget.max_llm_calls - usage["llm_calls"],
                "input_tokens": budget.max_input_tokens - usage["input_tokens"],
                "output_tokens": budget.max_output_tokens - usage["output_tokens"],
                "retries": budget.max_retries - usage["retries"],
                "tool_invocations": budget.max_tool_invocations
                - usage["tool_invocations"],
                "wall_seconds": max(0.0, budget.max_wall_seconds - effective_wall),
            },
        }


@dataclass
class _HelpRecord:
    """Internal mutable record pairing a help request with its resolution state."""

    request: SrlHelpRequest
    operator_minutes_estimate: int
    resolved_at: datetime | None = None


class HelpBurdenLedger:
    """Tracks help request burden per arm/unit/window against a frozen budget.

    The ledger records ``SrlHelpRequest`` envelopes together with an explicit
    operator-minute estimate supplied by the arm or an external rater.  Per-window
    burden metrics are computed on demand from the caller-supplied window bounds.
    """

    def __init__(self, budget: HelpBudget):
        self._budget = budget
        self._records: dict[tuple[str, str], list[_HelpRecord]] = {}

    def _ensure_slot(self, arm_id: str, unit_id: str) -> list[_HelpRecord]:
        key = (arm_id, unit_id)
        if key not in self._records:
            self._records[key] = []
        return self._records[key]

    def record(
        self,
        arm_id: str,
        unit_id: str,
        request: SrlHelpRequest,
        operator_minutes_estimate: int,
    ) -> None:
        """Store a help request and its operator-minute estimate."""
        records = self._ensure_slot(arm_id, unit_id)
        records.append(
            _HelpRecord(
                request=request,
                operator_minutes_estimate=operator_minutes_estimate,
            )
        )

    def resolve(
        self,
        arm_id: str,
        unit_id: str,
        help_request_id: str,
        resolved_at: datetime,
    ) -> bool:
        """Mark a previously recorded help request as resolved."""
        records = self._records.get((arm_id, unit_id), [])
        for record in records:
            if record.request.help_request_id == help_request_id:
                record.resolved_at = resolved_at
                return True
        return False

    def get_receipt(
        self,
        arm_id: str,
        unit_id: str,
        window_index: int,
        receipt_id: str,
        mandate_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> HelpBurdenReceipt:
        """Return a burden receipt for the requested window.

        ``window_index`` is an opaque identifier carried on the receipt; the
        actual window boundaries are ``window_start`` (inclusive) and
        ``window_end`` (exclusive).
        """
        _ = window_index
        records = self._records.get((arm_id, unit_id), [])
        window_records = [
            record
            for record in records
            if window_start <= record.request.requested_at < window_end
        ]

        request_count = len(window_records)
        operator_minutes = sum(
            record.operator_minutes_estimate for record in window_records
        )

        seen_unknowns: set[tuple[str, ...]] = set()
        repeated_count = 0
        for record in window_records:
            unknowns = record.request.unknowns
            if unknowns in seen_unknowns:
                repeated_count += 1
            seen_unknowns.add(unknowns)
        repeated_question_rate = (
            repeated_count / request_count if request_count > 0 else 0.0
        )

        longest_wait = 0
        for record in window_records:
            requested_at = record.request.requested_at
            if record.resolved_at is not None:
                wait_seconds = int((record.resolved_at - requested_at).total_seconds())
            else:
                wait_seconds = int((window_end - requested_at).total_seconds())
            if wait_seconds > longest_wait:
                longest_wait = wait_seconds

        exceeded = (
            request_count > self._budget.max_requests_per_window
            or operator_minutes > self._budget.max_operator_minutes_per_window
            or repeated_question_rate > self._budget.max_repeated_question_rate
            or longest_wait > self._budget.max_unresolved_wait_seconds
        )

        if exceeded:
            return HelpBurdenReceipt(
                receipt_id=receipt_id,
                mandate_id=mandate_id,
                window_start=window_start,
                window_end=window_end,
                request_count=request_count,
                operator_minutes=operator_minutes,
                repeated_question_rate=repeated_question_rate,
                longest_unresolved_wait_seconds=longest_wait,
                status="EXCEEDED",
            )
        return HelpBurdenReceipt(
            receipt_id=receipt_id,
            mandate_id=mandate_id,
            window_start=window_start,
            window_end=window_end,
            request_count=request_count,
            operator_minutes=operator_minutes,
            repeated_question_rate=repeated_question_rate,
            longest_unresolved_wait_seconds=longest_wait,
            status="WITHIN_BUDGET",
        )


class RsrlEventGateway:
    """In-memory event gateway for R-SRL-1 units.

    Enforces public-state contract: arms receive the same event ledger and
    repository bytes, but cannot read ``expected_outcomes.yaml`` or access
    another arm's runtime logs.  Per-arm capability envelopes prevent
    baseline arms from emitting SRL-internal structures.
    """

    def __init__(
        self,
        units_root: Path,
        arm_budgets: dict[str, ArmBudget] | None = None,
        arm_envelopes: dict[str, ArmEnvelope] | None = None,
        help_budget: HelpBudget | None = None,
    ):
        self.units_root = Path(units_root)
        self._units: dict[str, FrozenUnit] = {}
        self._events: dict[str, tuple[SrlEnvironmentEvent, ...]] = {}
        self._repo_files: dict[str, dict[str, bytes]] = {}
        self._actions: dict[tuple[str, str], list[dict]] = {}
        self._help_requests: dict[tuple[str, str], list[SrlHelpRequest]] = {}
        self._help_request_event_ids: dict[tuple[str, str], dict[str, str]] = {}
        self._test_reports: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._build_results: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._restart_comparisons: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        matched_budgets = arm_budgets or {}
        _validate_matched_arm_budgets(matched_budgets)
        self._ledger = BudgetLedger(matched_budgets)
        self._arm_envelopes = dict(arm_envelopes or _default_arm_envelopes())
        self._help_ledger: HelpBurdenLedger | None = (
            HelpBurdenLedger(help_budget) if help_budget is not None else None
        )
        self._load_units()

    def _load_units(self) -> None:
        for unit_dir in sorted(self.units_root.iterdir()):
            if not unit_dir.is_dir():
                continue
            unit = load_frozen_unit(unit_dir)
            verify_manifest(unit)
            repo_files = self._load_repo_files(unit_dir)
            validate_expected_outcomes_repo_consistency(unit, repo_files)
            self._units[unit.unit_id] = unit
            self._events[unit.unit_id] = load_events(unit.events_path)
            self._repo_files[unit.unit_id] = repo_files

    def _load_repo_files(self, unit_dir: Path) -> dict[str, bytes]:
        repo_dir = unit_dir / "repo"
        files: dict[str, bytes] = {}
        if repo_dir.is_dir():
            for path in sorted(repo_dir.rglob("*")):
                if path.is_file():
                    rel = path.relative_to(repo_dir).as_posix()
                    files[rel] = path.read_bytes()
        return files

    def _get_envelope(self, arm_id: str) -> ArmEnvelope:
        """Return the envelope for ``arm_id`` or raise if it is unconfigured."""
        if arm_id not in self._arm_envelopes:
            raise ValueError(f"no arm envelope configured for arm_id: {arm_id}")
        return self._arm_envelopes[arm_id]

    def _enforce_arm_envelope(self, arm_id: str, payload: Any) -> None:
        """Reject baseline-arm payloads that contain SRL-internal type names."""
        envelope = self._get_envelope(arm_id)
        if envelope.can_use_srl_structures:
            return
        blocked = SRL_INTERNAL_TYPE_NAMES - envelope.allowed_srl_type_names
        if not blocked:
            return
        plain = _model_dump_tree(payload)
        if _contains_srl_type_name(plain, set(blocked)):
            raise PermissionError(
                f"arm {arm_id} ({envelope.role.value}) is not permitted to emit "
                "SRL-internal structures"
            )

    def list_events(self, arm_id: str, unit_id: str) -> tuple[SrlEnvironmentEvent, ...]:
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        self._ledger.check_wall_time(arm_id, unit_id)
        return self._events.get(unit_id, ())

    def _repo_dir(self, unit_id: str) -> Path:
        unit = self._units.get(unit_id)
        if unit is None:
            raise ValueError(f"unknown unit_id: {unit_id}")
        return unit.snapshot_path.parent / "repo"

    def _materialize_repo_workdir(self, unit_id: str, destination: Path) -> Path:
        """Materialize a clean per-run repository workdir from verified bytes."""
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        repo_files = self._repo_files.get(unit_id)
        if repo_files is None:
            raise FileNotFoundError(f"repository snapshot not found for {unit_id}")
        repo_dir = destination / "repo"
        repo_dir.mkdir(parents=True, exist_ok=False)
        for rel_path, content in sorted(repo_files.items()):
            rel = Path(rel_path)
            if _is_runtime_residue_path(rel):
                continue
            target = repo_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        return repo_dir

    def read_repository(self, arm_id: str, unit_id: str, path: str) -> bytes:
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        if _is_dangerous_path(path):
            raise PermissionError(f"access denied to path: {path}")
        self._ledger.check_wall_time(arm_id, unit_id)
        files = self._repo_files.get(unit_id, {})
        if path not in files:
            raise FileNotFoundError(f"repository path not found: {path}")
        # Small fixed charge for repository reads (tokens + tool invocation).
        self._ledger.charge(arm_id, unit_id, BudgetEntry.input_tokens(10))
        self._ledger.charge(arm_id, unit_id, BudgetEntry.tool_invocation())
        return files[path]

    def run_tests(self, arm_id: str, unit_id: str, selector: str) -> TestResult:
        """Run pytest against ``selector`` in the unit repository snapshot.

        Records the structured result and a durable test report in the arm run
        artifact.  Counts as one tool invocation plus small token overhead.
        """
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        _validate_pytest_selector(selector)
        self._ledger.check_wall_time(arm_id, unit_id)
        # Charge before executing so a depleted budget aborts before work.
        self._ledger.charge(arm_id, unit_id, BudgetEntry.tool_invocation())
        self._ledger.charge(arm_id, unit_id, BudgetEntry.input_tokens(50))

        cmd = [sys.executable, "-m", "pytest", "-q", selector]
        with tempfile.TemporaryDirectory(prefix=f"r-srl-{unit_id}-{arm_id}-") as tmp:
            repo_dir = self._materialize_repo_workdir(unit_id, Path(tmp))
            completed = subprocess.run(
                cmd,
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=self._ledger.remaining_wall_seconds(arm_id, unit_id),
            )

        artifact_ref = f"report:{selector}"
        passed = completed.returncode == 0
        report = TestReport(
            test_path=selector,
            passed=passed,
            artifact_ref=artifact_ref,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        self._test_reports.setdefault((arm_id, unit_id), []).append(
            {
                "test_path": selector,
                "passed": passed,
                "artifact_ref": artifact_ref,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
        return TestResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            reports=(report,),
        )

    def run_build(
        self,
        arm_id: str,
        unit_id: str,
        build_command: list[str] | None = None,
    ) -> BuildResult:
        """Run the configured build command in the unit repository snapshot.

        Defaults to ``python -m compileall .``.  Records the result under the
        arm run artifact and counts as one tool invocation.
        """
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        cmd = (
            list(build_command)
            if build_command
            else _runtime_build_command(self._units[unit_id].build_commands[0])
        )
        normalized_cmd = _normalize_build_command(cmd)
        allowed = set(self._units[unit_id].build_commands)
        if normalized_cmd not in allowed:
            raise PermissionError(
                f"build command is not in the frozen allowlist for {unit_id}: {normalized_cmd!r}"
            )
        cmd = _runtime_build_command(normalized_cmd)

        self._ledger.check_wall_time(arm_id, unit_id)
        self._ledger.charge(arm_id, unit_id, BudgetEntry.tool_invocation())
        self._ledger.charge(arm_id, unit_id, BudgetEntry.input_tokens(50))
        with tempfile.TemporaryDirectory(prefix=f"r-srl-{unit_id}-{arm_id}-") as tmp:
            repo_dir = self._materialize_repo_workdir(unit_id, Path(tmp))
            completed = subprocess.run(
                cmd,
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=self._ledger.remaining_wall_seconds(arm_id, unit_id),
            )
        artifact_ref = f"build:{cmd[0]}"
        self._build_results.setdefault((arm_id, unit_id), []).append(
            {
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "artifact_ref": artifact_ref,
            }
        )
        return BuildResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def emit_help_request(
        self,
        arm_id: str,
        unit_id: str,
        request: SrlHelpRequest,
        operator_minutes_estimate: int = 1,
        event_id: str | None = None,
    ) -> None:
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        self._ledger.check_wall_time(arm_id, unit_id)
        # Baseline arms may emit a plain SrlHelpRequest envelope, but any
        # SRL-internal type name embedded inside the payload is rejected.
        self._enforce_arm_envelope(arm_id, request)
        self._help_requests.setdefault((arm_id, unit_id), []).append(request)
        if event_id is not None:
            self._require_known_event_id(unit_id, event_id)
            self._help_request_event_ids.setdefault((arm_id, unit_id), {})[
                request.help_request_id
            ] = event_id
        if self._help_ledger is not None:
            self._help_ledger.record(
                arm_id, unit_id, request, operator_minutes_estimate
            )

    def resolve_help_request(
        self,
        arm_id: str,
        unit_id: str,
        help_request_id: str,
        resolved_at: datetime,
    ) -> bool:
        """Mark a help request as resolved in the burden ledger."""
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        if self._help_ledger is None:
            return False
        return self._help_ledger.resolve(arm_id, unit_id, help_request_id, resolved_at)

    def get_help_burden_receipt(
        self,
        arm_id: str,
        unit_id: str,
        window_index: int,
        receipt_id: str,
        mandate_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> HelpBurdenReceipt:
        """Return the burden receipt for the requested window."""
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        if self._help_ledger is not None:
            return self._help_ledger.get_receipt(
                arm_id,
                unit_id,
                window_index,
                receipt_id,
                mandate_id,
                window_start,
                window_end,
            )
        return HelpBurdenReceipt(
            receipt_id=receipt_id,
            mandate_id=mandate_id,
            window_start=window_start,
            window_end=window_end,
            request_count=0,
            operator_minutes=0,
            repeated_question_rate=0.0,
            longest_unresolved_wait_seconds=0,
            status="WITHIN_BUDGET",
        )

    def record_action(self, arm_id: str, unit_id: str, action: dict) -> None:
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        if not isinstance(action, dict):
            raise TypeError("action must be a dict")
        self._ledger.check_wall_time(arm_id, unit_id)
        self._enforce_arm_envelope(arm_id, action)
        self._actions.setdefault((arm_id, unit_id), []).append(action)

    def record_restart_comparison(
        self,
        arm_id: str,
        unit_id: str,
        event_id: str,
        comparison: dict[str, Any],
    ) -> None:
        """Record a restart comparator result under a concrete event id."""
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        self._require_known_event_id(unit_id, event_id)
        if not isinstance(comparison.get("equivalent"), bool):
            raise ValueError("restart comparison requires boolean equivalent")
        differences = comparison.get("differences", [])
        if not isinstance(differences, list):
            raise ValueError("restart comparison differences must be a list")
        self._ledger.check_wall_time(arm_id, unit_id)
        self._restart_comparisons.setdefault((arm_id, unit_id), {})[event_id] = dict(
            comparison
        )

    def charge(self, arm_id: str, unit_id: str, entry: BudgetEntry) -> None:
        """Apply a budget charge to the arm/unit ledger."""
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        self._ledger.check_wall_time(arm_id, unit_id)
        self._ledger.charge(arm_id, unit_id, entry)

    def get_budget_summary(self, arm_id: str, unit_id: str) -> dict[str, Any]:
        """Return budget limits, usage and remaining per dimension."""
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        return self._ledger.get_budget_summary(arm_id, unit_id)

    def export_state(self, arm_id: str, unit_id: str) -> RestartState:
        """Export a deterministic RestartState for the arm/unit.

        Since the harness does not yet embed a real SRL Runtime, the state is
        derived from recorded actions and help requests.
        """
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        self._ledger.check_wall_time(arm_id, unit_id)
        actions = self._actions.get((arm_id, unit_id), [])
        help_requests = self._help_requests.get((arm_id, unit_id), [])

        resolved_ids: set[str] = set()
        if self._help_ledger is not None:
            for record in self._help_ledger._records.get((arm_id, unit_id), []):
                if record.resolved_at is not None:
                    resolved_ids.add(record.request.help_request_id)

        pending = [
            req for req in help_requests if req.help_request_id not in resolved_ids
        ]

        canonical_actions = json.dumps(actions, sort_keys=True, default=str)
        commitment_portfolio_digest = hashlib.sha256(
            canonical_actions.encode("utf-8")
        ).hexdigest()

        active_goals = tuple(
            str(action["goal"]) for action in actions if "goal" in action
        )

        pending_help_request_ids = tuple(req.help_request_id for req in pending)
        pending_help_request_expiry = tuple(
            req.expires_at.isoformat() for req in pending
        )

        last_checkpoint_index = -1
        for index, action in enumerate(actions):
            if action.get("kind") == "checkpoint":
                last_checkpoint_index = index
        belief_actions = (
            actions
            if last_checkpoint_index == -1
            else actions[last_checkpoint_index + 1 :]
        )
        belief_checksums = tuple(
            hashlib.sha256(
                json.dumps(action, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            for action in belief_actions
        )

        return RestartState(
            commitment_portfolio_digest=commitment_portfolio_digest,
            active_goals=active_goals,
            pending_help_request_ids=pending_help_request_ids,
            pending_help_request_expiry=pending_help_request_expiry,
            belief_checksums=belief_checksums,
        )

    def compare_state(
        self,
        pre_state: RestartState,
        post_state: RestartState,
        expected_delta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compare pre- and post-restart states with a ground-truth delta.

        ``expected_delta`` may append pending help-request ids/expiry tuples or
        belief checksums to ``pre_state`` before comparison.
        """
        delta = dict(expected_delta or {})
        adjusted = RestartState(
            commitment_portfolio_digest=pre_state.commitment_portfolio_digest,
            active_goals=pre_state.active_goals,
            pending_help_request_ids=pre_state.pending_help_request_ids
            + tuple(delta.get("pending_help_request_ids", ())),
            pending_help_request_expiry=pre_state.pending_help_request_expiry
            + tuple(delta.get("pending_help_request_expiry", ())),
            belief_checksums=pre_state.belief_checksums
            + tuple(delta.get("belief_checksums", ())),
        )

        differences: list[str] = []
        for field_name in (
            "commitment_portfolio_digest",
            "active_goals",
            "pending_help_request_ids",
            "pending_help_request_expiry",
            "belief_checksums",
        ):
            left = getattr(adjusted, field_name)
            right = getattr(post_state, field_name)
            if left != right:
                differences.append(f"{field_name}: expected {left!r}, got {right!r}")

        return {"equivalent": not differences, "differences": differences}

    def _require_known_event_id(self, unit_id: str, event_id: str) -> None:
        known = {event.event_id for event in self._events.get(unit_id, ())}
        if event_id not in known:
            raise ValueError(f"unknown event_id for unit {unit_id}: {event_id}")

    def build_scorer_artifact(self, arm_id: str, unit_id: str) -> dict[str, Any]:
        """Build the durable artifact shape consumed by the hidden scorer.

        This is the explicit gateway-to-scorer adapter.  It converts runtime
        logs into the event-keyed fields expected by ``RsrlHiddenEvaluator`` and
        materializes evidence refs in ``artifact_bundle`` so the deterministic
        outcome validator can fail closed on missing artifacts.
        """
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        key = (arm_id, unit_id)
        actions_by_event: dict[str, list[dict[str, Any]]] = {}
        file_modifications: dict[str, list[str]] = {}
        artifact_bundle: dict[str, Any] = {}

        for action in self._actions.get(key, []):
            event_id = action.get("event_id")
            if not isinstance(event_id, str):
                continue
            self._require_known_event_id(unit_id, event_id)
            actions_by_event.setdefault(event_id, []).append(action)
            if isinstance(action.get("path"), str):
                file_modifications.setdefault(event_id, []).append(str(action["path"]))

            kind = action.get("kind")
            raw_payload = action.get("payload")
            payload = raw_payload if isinstance(raw_payload, dict) else {}
            if kind == "interface_call":
                artifact_bundle[f"interface:{event_id}:matched_call"] = action
                artifact_bundle[f"interface:{event_id}:no_forbidden_call"] = True
            elif kind == "constraint_resolution":
                artifact_bundle[f"conflict:{event_id}:constraint_matched"] = action
                artifact_bundle[f"conflict:{event_id}:no_forbidden_kind"] = True
            elif kind in {"uncertainty_note", "risk_assessment"} and payload.get(
                "statement"
            ):
                artifact_bundle[f"uncertainty:{event_id}:accepted_statement"] = action
            elif kind == "belief_correction":
                artifact_bundle[f"belief:{event_id}:correction"] = action
            elif kind == "commitment_complete":
                artifact_bundle[f"commitment:{event_id}:on_time"] = action

        help_by_event: dict[str, list[dict[str, Any]]] = {}
        help_event_ids = self._help_request_event_ids.get(key, {})
        for request in self._help_requests.get(key, []):
            event_id = help_event_ids.get(request.help_request_id)
            if event_id is None:
                continue
            self._require_known_event_id(unit_id, event_id)
            request_payload = _model_dump_tree(request)
            help_by_event.setdefault(event_id, []).append(request_payload)
            artifact_bundle[f"help:{event_id}:request"] = request_payload

        restart_comparisons = dict(self._restart_comparisons.get(key, {}))
        for event_id, comparison in restart_comparisons.items():
            self._require_known_event_id(unit_id, event_id)
            artifact_bundle[f"restart:{event_id}:comparison"] = comparison

        test_reports = list(self._test_reports.get(key, []))
        for report in test_reports:
            artifact_ref = report.get("artifact_ref")
            if isinstance(artifact_ref, str) and artifact_ref:
                artifact_bundle[artifact_ref] = report

        event_ids = {event.event_id for event in self._events.get(unit_id, ())}
        touched_events = (
            set(actions_by_event)
            | set(help_by_event)
            | set(file_modifications)
            | set(restart_comparisons)
        )
        for event_id in sorted(event_ids - touched_events):
            artifact_bundle[f"decoy:{event_id}:no_work_spawned"] = True
        artifact_bundle["decoy:no_work_spawned"] = True

        return {
            "unit_id": unit_id,
            "arm_id": arm_id,
            "actions": actions_by_event,
            "help_requests": help_by_event,
            "file_modifications": file_modifications,
            "restart_comparisons": restart_comparisons,
            "test_reports": test_reports,
            "build_results": list(self._build_results.get(key, [])),
            "artifact_bundle": artifact_bundle,
        }

    def finalize_unit(self, arm_id: str, unit_id: str) -> dict:
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        scorer_artifact = self.build_scorer_artifact(arm_id, unit_id)
        return {
            "unit_id": unit_id,
            "arm_id": arm_id,
            "event_count": len(self._events.get(unit_id, ())),
            "action_count": len(self._actions.get((arm_id, unit_id), [])),
            "help_request_count": len(self._help_requests.get((arm_id, unit_id), [])),
            "repository_files": sorted(self._repo_files.get(unit_id, {}).keys()),
            "test_reports": list(self._test_reports.get((arm_id, unit_id), [])),
            "build_results": list(self._build_results.get((arm_id, unit_id), [])),
            "scorer_artifact": scorer_artifact,
        }
