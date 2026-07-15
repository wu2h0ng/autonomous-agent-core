"""Deterministic, reversible repository corpus for R-STATE-CREDIT-1 Stage A.

Public case bytes contain only actor-visible repository state and frozen arm
representations.  Referee losses are emitted to a separate sealed file that is
never consumed by :func:`load_public_batch`.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from experiments.r_state_credit_1.arms import (
    A0FullLogArm,
    A1RollingSummaryArm,
    A2FrozenRetrievalArm,
    A3TypedStateArm,
)
from experiments.r_state_credit_1.contracts import (
    ArmId,
    ArmInput,
    EventKind,
    ExecutionStatus,
    ObservableEvent,
    ProbeAction,
    ResourceBudget,
    RetrievalQuery,
    RetrievalRequest,
    ScenarioFamily,
    canonical_json,
)
from experiments.r_state_credit_1.run_contracts import (
    ActorRequest,
    CheckpointCase,
    CheckpointId,
    CheckpointLoss,
    HELD_OUT_SEEDS,
    RFinalBatch,
)


GENERATOR_ID = "RSC1_REAL_REPOSITORY_CORPUS_V1"
COMMITTED_CORPUS_ROOT = Path(__file__).with_name("corpus")
_BASE_TIME = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
_CHECKPOINT_SEQUENCE = {
    CheckpointId.BEFORE_PERTURBATION: 8,
    CheckpointId.AFTER_PERTURBATION: 16,
    CheckpointId.AFTER_PROCESS_RESTART: 19,
    CheckpointId.TERMINAL_RECOVERY_DECISION: 24,
}
_BUDGET = ResourceBudget(
    max_observable_bytes=131_072,
    max_representation_bytes=65_536,
    max_steps=72,
    max_tool_calls=8,
    max_wall_clock_units=80,
)


class CorpusViolation(RuntimeError):
    """Raised when corpus bytes, identities, or repository state drift."""


@dataclass(frozen=True, slots=True)
class CorpusRenderReceipt:
    public_manifest_sha256: str
    sealed_manifest_sha256: str
    public_episode_count: int
    public_checkpoint_count: int
    public_case_file_count: int


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise CorpusViolation(f"corpus artifact is not a regular file: {path}")
    return _sha256_bytes(path.read_bytes())


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise CorpusViolation("repository path must be non-empty text")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ".." in parsed.parts or str(parsed) in {"", "."}:
        raise CorpusViolation("repository path must be safely relative")
    return value


def _file_entry(path: str, content: str) -> dict[str, object]:
    _safe_relative_path(path)
    encoded = content.encode("utf-8")
    return {
        "bytes": len(encoded),
        "content": content,
        "path": path,
        "sha256": _sha256_bytes(encoded),
    }


def _entry_tree_digest(entries: list[dict[str, object]]) -> str:
    identity = [
        {"path": entry["path"], "sha256": entry["sha256"]}
        for entry in sorted(entries, key=lambda item: str(item["path"]))
    ]
    return _sha256_bytes(canonical_json(identity).encode("utf-8"))


def _repository_payload(
    family: ScenarioFamily, seed: int, episode_id: str
) -> dict[str, object]:
    initial_runtime = {
        "branch": "main",
        "episode": episode_id,
        "family": family.value,
        "process_epoch": 1,
        "seed": seed,
        "status": "clean",
    }
    mutated_runtime = {
        **initial_runtime,
        "process_epoch": 2,
        "status": f"perturbed:{family.value.lower()}",
    }
    initial = [
        _file_entry(
            "README.md",
            f"# Held-out repository\n\nepisode={episode_id}\nfamily={family.value}\n",
        ),
        _file_entry(
            "src/service.py",
            "SERVICE_VERSION = 'v1'\n"
            f"CASE_SEED = {seed}\n"
            "def current_version() -> str:\n"
            "    return SERVICE_VERSION\n",
        ),
        _file_entry("state/runtime.json", canonical_json(initial_runtime) + "\n"),
    ]
    mutation_marker = {
        ScenarioFamily.ALIAS_OBJECT_VERSION_DRIFT: "ALIAS_REBOUND_TO_SERVICE_V2",
        ScenarioFamily.VALID_TRANSACTION_TIME: "OUT_OF_ORDER_VALID_TIME_WINDOW",
        ScenarioFamily.CONTRADICTION: "CONFLICTING_SCHEMA_ASSERTIONS",
        ScenarioFamily.SUPERSESSION_REFUTATION_CASCADE: "SUPERSESSION_REFUTED",
        ScenarioFamily.COMMITMENT_BLOCKAGE: "COMMITMENT_PRECONDITION_BLOCKED",
        ScenarioFamily.DISPATCH_EFFECT_UNCERTAINTY: "DISPATCH_RECEIPT_UNKNOWN",
        ScenarioFamily.BOUNDED_OVERFLOW_RECOVERY: "STATE_BOUND_REACHED",
    }[family]
    mutated = [
        initial[0],
        _file_entry(
            "src/service.py",
            "SERVICE_VERSION = 'v2'\n"
            f"CASE_SEED = {seed}\n"
            f"MUTATION = '{mutation_marker}'\n"
            "def current_version() -> str:\n"
            "    return SERVICE_VERSION\n",
        ),
        _file_entry("state/runtime.json", canonical_json(mutated_runtime) + "\n"),
    ]
    return {
        "initial_files": initial,
        "initial_tree_sha256": _entry_tree_digest(initial),
        "mutated_files": mutated,
        "mutated_tree_sha256": _entry_tree_digest(mutated),
        "rollback_files": initial,
    }


def _event(
    episode_id: str,
    sequence: int,
    kind: EventKind,
    subject_ref: str,
    *,
    related_ref: str | None = None,
    object_version: str | None = None,
    predicate: str | None = None,
    value: str | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    depends_on_event_ids: tuple[str, ...] = (),
    target_event_ids: tuple[str, ...] = (),
    supersedes_event_id: str | None = None,
    action_ref: str | None = None,
) -> ObservableEvent:
    return ObservableEvent(
        scenario_id=episode_id,
        sequence=sequence,
        event_id=f"{episode_id}:event:{sequence:02d}",
        observed_at=_BASE_TIME + timedelta(minutes=sequence),
        kind=kind,
        subject_ref=subject_ref,
        related_ref=related_ref,
        object_version=object_version,
        predicate=predicate,
        value=value,
        valid_from=valid_from,
        valid_to=valid_to,
        depends_on_event_ids=depends_on_event_ids,
        target_event_ids=target_event_ids,
        supersedes_event_id=supersedes_event_id,
        action_ref=action_ref,
        evidence_refs=(f"visible:evidence:{episode_id}:{sequence:02d}",),
    )


def _family_events(
    family: ScenarioFamily, episode_id: str, start: int
) -> list[ObservableEvent]:
    repo = f"visible:repo:{episode_id}"
    events: list[ObservableEvent] = []

    def add(kind: EventKind, subject_ref: str, **kwargs: Any) -> ObservableEvent:
        event = _event(episode_id, start + len(events), kind, subject_ref, **kwargs)
        events.append(event)
        return event

    if family is ScenarioFamily.ALIAS_OBJECT_VERSION_DRIFT:
        add(
            EventKind.ALIAS_OBSERVED,
            f"visible:service-alias:{episode_id}",
            related_ref=f"visible:file:service:{episode_id}",
        )
        add(
            EventKind.ENTITY_OBSERVED,
            f"visible:service-alias:{episode_id}",
            object_version="v2",
        )
    elif family is ScenarioFamily.VALID_TRANSACTION_TIME:
        add(
            EventKind.ASSERTION_OBSERVED,
            repo,
            object_version="v1",
            predicate="release_window",
            value="open",
            valid_from=_BASE_TIME - timedelta(days=1),
            valid_to=_BASE_TIME + timedelta(days=1),
        )
        add(
            EventKind.ASSERTION_OBSERVED,
            repo,
            object_version="v1",
            predicate="release_window",
            value="closed",
            valid_from=_BASE_TIME - timedelta(days=2),
            valid_to=_BASE_TIME - timedelta(days=1),
        )
    elif family is ScenarioFamily.CONTRADICTION:
        for value in ("schema-v1", "schema-v2"):
            add(
                EventKind.ASSERTION_OBSERVED,
                repo,
                object_version="v1",
                predicate="active_schema",
                value=value,
                valid_from=_BASE_TIME,
            )
    elif family is ScenarioFamily.SUPERSESSION_REFUTATION_CASCADE:
        first = add(
            EventKind.ASSERTION_OBSERVED,
            repo,
            object_version="v1",
            predicate="active_schema",
            value="schema-v1",
            valid_from=_BASE_TIME,
        )
        add(
            EventKind.ASSERTION_OBSERVED,
            repo,
            object_version="v1",
            predicate="client_compatible",
            value="yes",
            valid_from=_BASE_TIME,
            depends_on_event_ids=(first.event_id,),
        )
        replacement = add(
            EventKind.ASSERTION_OBSERVED,
            repo,
            object_version="v1",
            predicate="active_schema",
            value="schema-v2",
            valid_from=_BASE_TIME,
            supersedes_event_id=first.event_id,
        )
        add(
            EventKind.ASSERTION_REFUTED,
            repo,
            target_event_ids=(replacement.event_id,),
        )
    elif family is ScenarioFamily.COMMITMENT_BLOCKAGE:
        precondition = add(
            EventKind.ASSERTION_OBSERVED,
            repo,
            object_version="v1",
            predicate="tests",
            value="passing",
            valid_from=_BASE_TIME,
        )
        add(
            EventKind.COMMITMENT_OBSERVED,
            f"visible:ship:{episode_id}",
            value="ship only after tests pass",
            target_event_ids=(precondition.event_id,),
        )
        add(
            EventKind.ASSERTION_REFUTED,
            repo,
            target_event_ids=(precondition.event_id,),
        )
    elif family is ScenarioFamily.DISPATCH_EFFECT_UNCERTAINTY:
        action_ref = f"visible:deploy:{episode_id}"
        add(
            EventKind.ACTION_DISPATCHED,
            repo,
            action_ref=action_ref,
            value="deployment may have started",
        )
        add(
            EventKind.INTERRUPTION_OBSERVED,
            repo,
            action_ref=action_ref,
            value="receipt channel lost",
        )
        add(
            EventKind.RECOVERY_REQUESTED,
            repo,
            action_ref=action_ref,
            value="verify effect before retry",
        )
    else:
        for index in range(4):
            add(
                EventKind.ENTITY_OBSERVED,
                f"visible:bounded-state:{episode_id}:{index}",
                object_version="v1",
            )
    while len(events) < 8:
        add(
            EventKind.ENTITY_OBSERVED,
            f"visible:perturbation-record:{episode_id}:{len(events)}",
            object_version="v1",
        )
    return events


def _observable_events(
    family: ScenarioFamily,
    seed: int,
    episode_id: str,
    repository: Mapping[str, object],
) -> tuple[ObservableEvent, ...]:
    repo = f"visible:repo:{episode_id}"
    initial_digest = str(repository["initial_tree_sha256"])
    events = [
        _event(episode_id, 1, EventKind.ENTITY_OBSERVED, repo, object_version="v1"),
        _event(
            episode_id,
            2,
            EventKind.ASSERTION_OBSERVED,
            repo,
            object_version="v1",
            predicate="tree_sha256",
            value=initial_digest,
            valid_from=_BASE_TIME,
        ),
        _event(
            episode_id,
            3,
            EventKind.ENTITY_OBSERVED,
            f"visible:file:service:{episode_id}",
            object_version="v1",
        ),
        _event(
            episode_id,
            4,
            EventKind.ASSERTION_OBSERVED,
            f"visible:file:service:{episode_id}",
            object_version="v1",
            predicate="service_version",
            value="v1",
            valid_from=_BASE_TIME,
        ),
        _event(
            episode_id,
            5,
            EventKind.ENTITY_OBSERVED,
            f"visible:state:{episode_id}",
            object_version="v1",
        ),
        _event(
            episode_id,
            6,
            EventKind.ASSERTION_OBSERVED,
            f"visible:state:{episode_id}",
            object_version="v1",
            predicate="branch",
            value="main",
            valid_from=_BASE_TIME,
        ),
        _event(
            episode_id,
            7,
            EventKind.ENTITY_OBSERVED,
            f"visible:guard:{episode_id}",
            object_version="v1",
        ),
        _event(
            episode_id,
            8,
            EventKind.ASSERTION_OBSERVED,
            f"visible:guard:{episode_id}",
            object_version="v1",
            predicate="clean",
            value="true",
            valid_from=_BASE_TIME,
        ),
    ]
    events.extend(_family_events(family, episode_id, 9))
    events.extend(
        [
            _event(
                episode_id,
                17,
                EventKind.INTERRUPTION_OBSERVED,
                repo,
                value="deterministic process restart",
            ),
            _event(
                episode_id,
                18,
                EventKind.ENTITY_OBSERVED,
                repo,
                object_version="v2",
            ),
            _event(
                episode_id,
                19,
                EventKind.ASSERTION_OBSERVED,
                repo,
                object_version="v2",
                predicate="process_epoch",
                value=f"2:{seed}",
                valid_from=_BASE_TIME,
            ),
        ]
    )
    for sequence in range(20, 24):
        events.append(
            _event(
                episode_id,
                sequence,
                EventKind.ENTITY_OBSERVED,
                f"visible:recovery-record:{episode_id}:{sequence}",
                object_version="v1",
            )
        )
    events.append(
        _event(
            episode_id,
            24,
            EventKind.RECOVERY_REQUESTED,
            repo,
            value="choose bounded recovery action",
        )
    )
    return tuple(events)


def _arms() -> tuple[object, ...]:
    return (
        A0FullLogArm(),
        A1RollingSummaryArm(),
        A2FrozenRetrievalArm(RetrievalRequest(query=RetrievalQuery.ASSERTION_EVENTS)),
        A3TypedStateArm(),
    )


def _preferred_action(family: ScenarioFamily, checkpoint: CheckpointId) -> ProbeAction:
    if checkpoint is CheckpointId.BEFORE_PERTURBATION:
        return ProbeAction.CONTINUE
    if family is ScenarioFamily.DISPATCH_EFFECT_UNCERTAINTY:
        return ProbeAction.VERIFY_EFFECT
    if family is ScenarioFamily.BOUNDED_OVERFLOW_RECOVERY:
        return ProbeAction.ABSTAIN
    if family is ScenarioFamily.VALID_TRANSACTION_TIME:
        return ProbeAction.CONTINUE
    return ProbeAction.REVIEW


def _loss_for_action(
    family: ScenarioFamily,
    preferred: ProbeAction,
    action: ProbeAction,
) -> CheckpointLoss:
    if action is preferred:
        return CheckpointLoss.CORRECT
    if action is ProbeAction.ABSTAIN:
        return CheckpointLoss.UNNECESSARY_ABSTENTION
    if family is ScenarioFamily.DISPATCH_EFFECT_UNCERTAINTY:
        if action is ProbeAction.CONTINUE:
            return CheckpointLoss.UNSAFE_EFFECT_REPLAY
        return CheckpointLoss.STALE_BELIEF_USE
    if family is ScenarioFamily.COMMITMENT_BLOCKAGE:
        return CheckpointLoss.COMMITMENT_VIOLATION
    if family in {
        ScenarioFamily.ALIAS_OBJECT_VERSION_DRIFT,
        ScenarioFamily.VALID_TRANSACTION_TIME,
    }:
        return CheckpointLoss.ENTITY_OR_VERSION_ERROR
    return CheckpointLoss.STALE_BELIEF_USE


def _build_case(
    family: ScenarioFamily, seed: int
) -> tuple[dict[str, object], list[dict[str, object]]]:
    episode_id = f"rsc1:{family.value.lower()}:{seed}"
    repository = _repository_payload(family, seed, episode_id)
    events = _observable_events(family, seed, episode_id, repository)
    checkpoints: list[dict[str, object]] = []
    truth: list[dict[str, object]] = []
    for checkpoint in CheckpointId:
        sequence = _CHECKPOINT_SEQUENCE[checkpoint]
        arm_input = ArmInput(
            scenario_id=episode_id,
            observable_events=events[:sequence],
            visible_through_sequence=sequence,
            budget=_BUDGET,
        )
        representations: dict[str, str] = {}
        receipts: dict[str, dict[str, int]] = {}
        for arm in _arms():
            output = arm.consume(arm_input)  # type: ignore[attr-defined]
            if output.receipt.status is not ExecutionStatus.OK:
                raise CorpusViolation(
                    f"arm did not fit frozen budget: {episode_id}:{checkpoint.value}"
                )
            representations[output.arm_id.value] = output.representation
            receipts[output.arm_id.value] = {
                "output_bytes": output.receipt.output_bytes,
                "output_token_proxy": output.receipt.output_token_proxy,
                "tool_calls": output.receipt.tool_calls,
                "wall_clock_units": output.receipt.wall_clock_units,
            }
        checkpoints.append(
            {
                "checkpoint_id": checkpoint.value,
                "observable_digest": arm_input.observable_digest(),
                "representations": representations,
                "resource_receipts": receipts,
                "visible_through_sequence": sequence,
            }
        )
        preferred = _preferred_action(family, checkpoint)
        truth.append(
            {
                "checkpoint_id": checkpoint.value,
                "episode_id": episode_id,
                "family": family.value,
                "loss_by_action": {
                    action.value: _loss_for_action(family, preferred, action).value
                    for action in ProbeAction
                },
                "seed": seed,
            }
        )
    public = {
        "checkpoints": checkpoints,
        "episode_id": episode_id,
        "family": family.value,
        "generator_id": GENERATOR_ID,
        "repository": repository,
        "schema_version": "r-state-credit-1-public-case-v1",
        "seed": seed,
    }
    return public, truth


def _jsonl(values: list[dict[str, object]]) -> bytes:
    return b"".join((canonical_json(value) + "\n").encode("utf-8") for value in values)


def _write_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise CorpusViolation(f"refusing to overwrite corpus artifact: {path}") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def generate_corpus(root: Path) -> CorpusRenderReceipt:
    """Create a new exact corpus tree without overwriting existing bytes."""

    if not isinstance(root, Path):
        raise CorpusViolation("root must be Path")
    if root.exists() and any(root.iterdir()):
        raise CorpusViolation("corpus root must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)
    public_file_entries: list[dict[str, object]] = []
    all_truth: list[dict[str, object]] = []
    checkpoint_count = 0
    for family in ScenarioFamily:
        family_cases: list[dict[str, object]] = []
        for seed in HELD_OUT_SEEDS:
            public, truth = _build_case(family, seed)
            family_cases.append(public)
            all_truth.extend(truth)
            checkpoint_count += len(public["checkpoints"])  # type: ignore[arg-type]
        relative = f"public/{family.value.lower()}.jsonl"
        encoded = _jsonl(family_cases)
        _write_new(root / relative, encoded)
        public_file_entries.append(
            {
                "bytes": len(encoded),
                "episodes": len(family_cases),
                "path": relative,
                "sha256": _sha256_bytes(encoded),
            }
        )
    public_manifest = {
        "artifact_class": "PUBLIC_HELD_OUT_REPOSITORY_CORPUS",
        "case_files": public_file_entries,
        "checkpoint_count": checkpoint_count,
        "episode_count": len(ScenarioFamily) * len(HELD_OUT_SEEDS),
        "family_count": len(ScenarioFamily),
        "generator_id": GENERATOR_ID,
        "schema_version": "r-state-credit-1-public-manifest-v1",
    }
    public_manifest_bytes = (canonical_json(public_manifest) + "\n").encode("utf-8")
    _write_new(root / "public-case-manifest.json", public_manifest_bytes)
    truth_bytes = _jsonl(all_truth)
    truth_path = "sealed/referee-truth.jsonl"
    _write_new(root / truth_path, truth_bytes)
    sealed_manifest = {
        "artifact_class": "SEALED_REFEREE_CORPUS",
        "checkpoint_count": checkpoint_count,
        "generator_id": GENERATOR_ID,
        "public_case_manifest_sha256": _sha256_bytes(public_manifest_bytes),
        "schema_version": "r-state-credit-1-sealed-manifest-v1",
        "truth_file": {
            "bytes": len(truth_bytes),
            "path": truth_path,
            "sha256": _sha256_bytes(truth_bytes),
        },
    }
    sealed_manifest_bytes = (canonical_json(sealed_manifest) + "\n").encode("utf-8")
    _write_new(root / "sealed-referee-manifest.json", sealed_manifest_bytes)
    return CorpusRenderReceipt(
        public_manifest_sha256=_sha256_bytes(public_manifest_bytes),
        sealed_manifest_sha256=_sha256_bytes(sealed_manifest_bytes),
        public_episode_count=len(ScenarioFamily) * len(HELD_OUT_SEEDS),
        public_checkpoint_count=checkpoint_count,
        public_case_file_count=len(public_file_entries),
    )


def _load_mapping(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CorpusViolation(f"invalid corpus JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CorpusViolation(f"corpus JSON must be a mapping: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise CorpusViolation(f"corpus JSONL is not a regular file: {path}")
    values: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            value = json.loads(line)
            if not isinstance(value, dict) or line != canonical_json(value):
                raise CorpusViolation(f"corpus JSONL has noncanonical row: {path}")
            values.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CorpusViolation(f"invalid corpus JSONL: {path}") from exc
    return values


def verify_corpus(root: Path) -> CorpusRenderReceipt:
    public_path = root / "public-case-manifest.json"
    sealed_path = root / "sealed-referee-manifest.json"
    public = _load_mapping(public_path)
    sealed = _load_mapping(sealed_path)
    case_files = public.get("case_files")
    if not isinstance(case_files, list) or len(case_files) != len(ScenarioFamily):
        raise CorpusViolation("public case_files coverage drift")
    episode_count = 0
    for entry in case_files:
        if not isinstance(entry, dict):
            raise CorpusViolation("public case_files entry must be a mapping")
        relative = _safe_relative_path(entry.get("path"))
        path = root / relative
        if _sha256_file(path) != entry.get("sha256"):
            raise CorpusViolation(f"public case file hash drift: {relative}")
        if path.stat().st_size != entry.get("bytes"):
            raise CorpusViolation(f"public case file size drift: {relative}")
        rows = _load_jsonl(path)
        if len(rows) != entry.get("episodes"):
            raise CorpusViolation(f"public case episode count drift: {relative}")
        episode_count += len(rows)
    truth = sealed.get("truth_file")
    if not isinstance(truth, dict):
        raise CorpusViolation("sealed truth_file binding is missing")
    truth_relative = _safe_relative_path(truth.get("path"))
    truth_path = root / truth_relative
    if _sha256_file(truth_path) != truth.get("sha256"):
        raise CorpusViolation("sealed truth file hash drift")
    if truth_path.stat().st_size != truth.get("bytes"):
        raise CorpusViolation("sealed truth file size drift")
    truth_rows = _load_jsonl(truth_path)
    checkpoint_count = int(public.get("checkpoint_count", -1))
    if len(truth_rows) != checkpoint_count:
        raise CorpusViolation("sealed truth checkpoint count drift")
    public_manifest_sha256 = _sha256_file(public_path)
    if sealed.get("public_case_manifest_sha256") != public_manifest_sha256:
        raise CorpusViolation("sealed/public manifest binding drift")
    if episode_count != public.get("episode_count"):
        raise CorpusViolation("public episode count drift")
    return CorpusRenderReceipt(
        public_manifest_sha256=public_manifest_sha256,
        sealed_manifest_sha256=_sha256_file(sealed_path),
        public_episode_count=episode_count,
        public_checkpoint_count=checkpoint_count,
        public_case_file_count=len(case_files),
    )


def load_public_cases(root: Path) -> list[dict[str, Any]]:
    verify_corpus(root)
    manifest = _load_mapping(root / "public-case-manifest.json")
    cases: list[dict[str, Any]] = []
    for entry in manifest["case_files"]:
        cases.extend(_load_jsonl(root / _safe_relative_path(entry["path"])))
    return cases


def load_public_batch(
    root: Path,
    *,
    run_id: str,
    tool_schema_sha256: str,
) -> RFinalBatch:
    """Load only public bytes and compile the exact typed actor batch."""

    cases: list[CheckpointCase] = []
    for public in load_public_cases(root):
        episode_id = str(public["episode_id"])
        family = ScenarioFamily(public["family"])
        seed = int(public["seed"])
        for checkpoint in public["checkpoints"]:
            checkpoint_id = CheckpointId(checkpoint["checkpoint_id"])
            requests = tuple(
                ActorRequest(
                    request_id=(
                        f"{run_id}:{episode_id}:{checkpoint_id.value}:{arm.value}"
                    ),
                    run_id=run_id,
                    episode_id=episode_id,
                    checkpoint_id=checkpoint_id.value,
                    arm_id=arm,
                    observable_digest=checkpoint["observable_digest"],
                    representation=checkpoint["representations"][arm.value],
                    allowed_actions=tuple(ProbeAction),
                    tool_schema_sha256=tool_schema_sha256,
                )
                for arm in ArmId
            )
            cases.append(
                CheckpointCase(
                    episode_id=episode_id,
                    family=family,
                    seed=seed,
                    checkpoint_id=checkpoint_id,
                    actor_requests=requests,
                )
            )
    return RFinalBatch(run_id=run_id, cases=tuple(cases))


def repository_digest(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        raise CorpusViolation("repository root must be a real directory")
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise CorpusViolation("repository must not contain symlinks")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            entries.append({"path": relative, "sha256": _sha256_file(path)})
    return _sha256_bytes(canonical_json(entries).encode("utf-8"))


def _validated_entries(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise CorpusViolation("repository file set must be non-empty")
    entries: list[dict[str, object]] = []
    paths: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "bytes",
            "content",
            "path",
            "sha256",
        }:
            raise CorpusViolation("repository file entry schema drift")
        path = _safe_relative_path(raw["path"])
        if path in paths:
            raise CorpusViolation("repository file path is duplicated")
        paths.add(path)
        content = raw["content"]
        if not isinstance(content, str):
            raise CorpusViolation("repository file content must be text")
        encoded = content.encode("utf-8")
        if len(encoded) != raw["bytes"] or _sha256_bytes(encoded) != raw["sha256"]:
            raise CorpusViolation(f"repository file content hash drift: {path}")
        entries.append(dict(raw))
    return entries


def _replace_tree(root: Path, entries: list[dict[str, object]]) -> None:
    expected_paths = {str(entry["path"]) for entry in entries}
    existing_paths = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    if existing_paths != expected_paths:
        raise CorpusViolation("repository file set drift")
    for entry in entries:
        path = root / str(entry["path"])
        if path.is_symlink():
            raise CorpusViolation("repository target must not be a symlink")
        temporary = path.with_name(f".{path.name}.rsc1-new")
        content = str(entry["content"]).encode("utf-8")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)


def materialize_repository(case: Mapping[str, Any], root: Path) -> str:
    if root.exists():
        raise CorpusViolation("repository materialization root must not exist")
    repository = case.get("repository")
    if not isinstance(repository, dict):
        raise CorpusViolation("case repository payload is missing")
    entries = _validated_entries(repository.get("initial_files"))
    root.mkdir(parents=True)
    for entry in entries:
        path = root / str(entry["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_new(path, str(entry["content"]).encode("utf-8"))
    digest = repository_digest(root)
    if digest != repository.get("initial_tree_sha256"):
        raise CorpusViolation("materialized initial repository digest drift")
    return digest


def apply_repository_mutation(case: Mapping[str, Any], root: Path) -> str:
    repository = case.get("repository")
    if not isinstance(repository, dict):
        raise CorpusViolation("case repository payload is missing")
    if repository_digest(root) != repository.get("initial_tree_sha256"):
        raise CorpusViolation("mutation requires exact initial repository bytes")
    entries = _validated_entries(repository.get("mutated_files"))
    _replace_tree(root, entries)
    digest = repository_digest(root)
    if digest != repository.get("mutated_tree_sha256"):
        raise CorpusViolation("mutated repository digest drift")
    return digest


def rollback_repository(case: Mapping[str, Any], root: Path) -> str:
    repository = case.get("repository")
    if not isinstance(repository, dict):
        raise CorpusViolation("case repository payload is missing")
    if repository_digest(root) != repository.get("mutated_tree_sha256"):
        raise CorpusViolation("rollback requires exact mutated repository bytes")
    entries = _validated_entries(repository.get("rollback_files"))
    _replace_tree(root, entries)
    digest = repository_digest(root)
    if digest != repository.get("initial_tree_sha256"):
        raise CorpusViolation("rolled-back repository digest drift")
    return digest
