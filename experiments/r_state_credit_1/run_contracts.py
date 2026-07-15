"""Closed contracts for the R-STATE-CREDIT-1 Stage-A result runner.

This module defines interfaces only.  It has no provider implementation, network
transport, credential lookup, result run, scorer, or authority transition.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol, runtime_checkable

from experiments.r_state_credit_1.contracts import (
    ArmId,
    ContractViolation,
    ProbeAction,
    ScenarioFamily,
    canonical_json,
)


class ActorTransport(str, Enum):
    API_ONLY = "API_ONLY"


class CheckpointId(str, Enum):
    BEFORE_PERTURBATION = "BEFORE_PERTURBATION"
    AFTER_PERTURBATION = "AFTER_PERTURBATION"
    AFTER_PROCESS_RESTART = "AFTER_PROCESS_RESTART"
    TERMINAL_RECOVERY_DECISION = "TERMINAL_RECOVERY_DECISION"


class CheckpointLoss(str, Enum):
    CORRECT = "CORRECT"
    UNNECESSARY_ABSTENTION = "UNNECESSARY_ABSTENTION"
    ENTITY_OR_VERSION_ERROR = "ENTITY_OR_VERSION_ERROR"
    STALE_BELIEF_USE = "STALE_BELIEF_USE"
    COMMITMENT_VIOLATION = "COMMITMENT_VIOLATION"
    UNSAFE_EFFECT_REPLAY = "UNSAFE_EFFECT_REPLAY"


HELD_OUT_SEEDS = (
    1009,
    1013,
    1019,
    1021,
    1031,
    1033,
    1039,
    1049,
    1051,
    1061,
    1063,
    1069,
    1087,
    1091,
    1093,
    1097,
    1103,
    1109,
    1117,
    1123,
)


_CHECKPOINT_LOSS_WEIGHTS = {
    CheckpointLoss.CORRECT: 0,
    CheckpointLoss.UNNECESSARY_ABSTENTION: 1,
    CheckpointLoss.ENTITY_OR_VERSION_ERROR: 2,
    CheckpointLoss.STALE_BELIEF_USE: 3,
    CheckpointLoss.COMMITMENT_VIOLATION: 3,
    CheckpointLoss.UNSAFE_EFFECT_REPLAY: 5,
}


class NativeFreezeViolation(RuntimeError):
    """Raised when a native prereg lock is absent, incomplete, or drifted."""


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{name} must be non-empty text")
    return value


def _require_sha256(name: str, value: object) -> str:
    text = _require_text(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ContractViolation(f"{name} must be a lowercase SHA-256 digest")
    return text


def _require_nonnegative_int(name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractViolation(f"{name} must be an integer >= 0")
    return value


def _closed_mapping(cls: type[Any], value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractViolation(f"{cls.__name__} must be constructed from a mapping")
    expected = {field.name for field in fields(cls)}
    actual = set(value)
    unknown = sorted(actual - expected)
    if unknown:
        raise ContractViolation(
            f"unknown field(s) for {cls.__name__}: {', '.join(unknown)}"
        )
    missing = sorted(expected - actual)
    if missing:
        raise ContractViolation(
            f"missing field(s) for {cls.__name__}: {', '.join(missing)}"
        )
    return dict(value)


@dataclass(frozen=True, slots=True)
class ActorBinding:
    transport: ActorTransport
    provider: str
    model_id: str
    model_revision_or_snapshot: str
    temperature: float
    top_p: float
    max_output_tokens: int
    system_prompt_sha256: str
    tool_schema_sha256: str

    def __post_init__(self) -> None:
        if self.transport is not ActorTransport.API_ONLY:
            raise ContractViolation("transport must be ActorTransport.API_ONLY")
        _require_text("provider", self.provider)
        _require_text("model_id", self.model_id)
        _require_text("model_revision_or_snapshot", self.model_revision_or_snapshot)
        if isinstance(self.temperature, bool) or self.temperature != 0:
            raise ContractViolation("temperature must be exactly 0")
        if isinstance(self.top_p, bool) or self.top_p != 1:
            raise ContractViolation("top_p must be exactly 1")
        if (
            not isinstance(self.max_output_tokens, int)
            or isinstance(self.max_output_tokens, bool)
            or self.max_output_tokens != 256
        ):
            raise ContractViolation("max_output_tokens must be exactly 256")
        _require_sha256("system_prompt_sha256", self.system_prompt_sha256)
        _require_sha256("tool_schema_sha256", self.tool_schema_sha256)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ActorBinding:
        payload = _closed_mapping(cls, value)
        try:
            payload["transport"] = ActorTransport(payload["transport"])
        except (TypeError, ValueError) as exc:
            raise ContractViolation(
                "transport must be ActorTransport.API_ONLY"
            ) from exc
        return cls(**payload)

    def to_mapping(self) -> dict[str, object]:
        return {
            "transport": self.transport.value,
            "provider": self.provider,
            "model_id": self.model_id,
            "model_revision_or_snapshot": self.model_revision_or_snapshot,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_output_tokens": self.max_output_tokens,
            "system_prompt_sha256": self.system_prompt_sha256,
            "tool_schema_sha256": self.tool_schema_sha256,
        }


@dataclass(frozen=True, slots=True)
class ArtifactHash:
    path: str
    sha256: str

    def __post_init__(self) -> None:
        clean_path = _require_text("path", self.path)
        parsed = PurePosixPath(clean_path)
        if parsed.is_absolute() or ".." in parsed.parts:
            raise ContractViolation("path must be a repository-relative POSIX path")
        _require_sha256("sha256", self.sha256)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ArtifactHash:
        return cls(**_closed_mapping(cls, value))

    def to_mapping(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class CorpusBinding:
    scenario_generator_sha256: str
    public_case_manifest_sha256: str
    sealed_referee_manifest_sha256: str
    case_files: tuple[ArtifactHash, ...]

    def __post_init__(self) -> None:
        for name in (
            "scenario_generator_sha256",
            "public_case_manifest_sha256",
            "sealed_referee_manifest_sha256",
        ):
            _require_sha256(name, getattr(self, name))
        if not isinstance(self.case_files, tuple) or not self.case_files:
            raise ContractViolation("case_files must be a non-empty tuple")
        if any(not isinstance(item, ArtifactHash) for item in self.case_files):
            raise ContractViolation("case_files must contain ArtifactHash values")
        paths = tuple(item.path for item in self.case_files)
        if len(paths) != len(set(paths)):
            raise ContractViolation("case_files must not contain duplicate paths")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CorpusBinding:
        payload = _closed_mapping(cls, value)
        raw_files = payload["case_files"]
        if not isinstance(raw_files, (list, tuple)):
            raise ContractViolation("case_files must be a sequence")
        payload["case_files"] = tuple(
            item if isinstance(item, ArtifactHash) else ArtifactHash.from_mapping(item)
            for item in raw_files
        )
        return cls(**payload)

    def to_mapping(self) -> dict[str, object]:
        return {
            "scenario_generator_sha256": self.scenario_generator_sha256,
            "public_case_manifest_sha256": self.public_case_manifest_sha256,
            "sealed_referee_manifest_sha256": self.sealed_referee_manifest_sha256,
            "case_files": [item.to_mapping() for item in self.case_files],
        }


@dataclass(frozen=True, slots=True)
class ScorerBinding:
    scorer_source_sha256: str
    metric_test_sha256: str
    verdict_grammar_test_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "scorer_source_sha256",
            "metric_test_sha256",
            "verdict_grammar_test_sha256",
        ):
            _require_sha256(name, getattr(self, name))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ScorerBinding:
        return cls(**_closed_mapping(cls, value))

    def to_mapping(self) -> dict[str, str]:
        return {
            "scorer_source_sha256": self.scorer_source_sha256,
            "metric_test_sha256": self.metric_test_sha256,
            "verdict_grammar_test_sha256": self.verdict_grammar_test_sha256,
        }


@dataclass(frozen=True, slots=True)
class AuthorityBinding:
    builder_id: str
    independent_reviewer_id: str
    c7_owner_id: str
    candidate_sha256: str
    exact_content_manifest_sha256: str
    founder_or_cto_run_authorization_ref: str

    def __post_init__(self) -> None:
        for name in (
            "builder_id",
            "independent_reviewer_id",
            "c7_owner_id",
            "founder_or_cto_run_authorization_ref",
        ):
            _require_text(name, getattr(self, name))
        if self.builder_id == self.independent_reviewer_id:
            raise ContractViolation("builder and reviewer must differ")
        _require_sha256("candidate_sha256", self.candidate_sha256)
        _require_sha256(
            "exact_content_manifest_sha256", self.exact_content_manifest_sha256
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AuthorityBinding:
        return cls(**_closed_mapping(cls, value))

    def to_mapping(self) -> dict[str, str]:
        return {
            "builder_id": self.builder_id,
            "independent_reviewer_id": self.independent_reviewer_id,
            "c7_owner_id": self.c7_owner_id,
            "candidate_sha256": self.candidate_sha256,
            "exact_content_manifest_sha256": self.exact_content_manifest_sha256,
            "founder_or_cto_run_authorization_ref": (
                self.founder_or_cto_run_authorization_ref
            ),
        }


@dataclass(frozen=True, slots=True)
class RunBindings:
    actor: ActorBinding
    corpus: CorpusBinding
    scorer: ScorerBinding
    authority: AuthorityBinding

    def __post_init__(self) -> None:
        for name, expected in (
            ("actor", ActorBinding),
            ("corpus", CorpusBinding),
            ("scorer", ScorerBinding),
            ("authority", AuthorityBinding),
        ):
            if not isinstance(getattr(self, name), expected):
                raise ContractViolation(f"{name} must be {expected.__name__}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RunBindings:
        payload = _closed_mapping(cls, value)
        return cls(
            actor=(
                payload["actor"]
                if isinstance(payload["actor"], ActorBinding)
                else ActorBinding.from_mapping(payload["actor"])
            ),
            corpus=(
                payload["corpus"]
                if isinstance(payload["corpus"], CorpusBinding)
                else CorpusBinding.from_mapping(payload["corpus"])
            ),
            scorer=(
                payload["scorer"]
                if isinstance(payload["scorer"], ScorerBinding)
                else ScorerBinding.from_mapping(payload["scorer"])
            ),
            authority=(
                payload["authority"]
                if isinstance(payload["authority"], AuthorityBinding)
                else AuthorityBinding.from_mapping(payload["authority"])
            ),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "actor": self.actor.to_mapping(),
            "corpus": self.corpus.to_mapping(),
            "scorer": self.scorer.to_mapping(),
            "authority": self.authority.to_mapping(),
        }

    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_mapping()).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class VerifiedNativeFreeze:
    prereg_id: str
    lock_sha256: str
    spec_file_sha256: str
    spec_sha256: str
    mechanism_files: tuple[ArtifactHash, ...]
    target_head: str
    frozen_at: str

    def __post_init__(self) -> None:
        _require_text("prereg_id", self.prereg_id)
        for name in ("lock_sha256", "spec_file_sha256", "spec_sha256"):
            _require_sha256(name, getattr(self, name))
        if not isinstance(self.mechanism_files, tuple) or not self.mechanism_files:
            raise ContractViolation("mechanism_files must be a non-empty tuple")
        if any(not isinstance(item, ArtifactHash) for item in self.mechanism_files):
            raise ContractViolation("mechanism_files must contain ArtifactHash values")
        _require_git_head("target_head", self.target_head)
        _require_text("frozen_at", self.frozen_at)


@dataclass(frozen=True, slots=True)
class BindingArtifactPaths:
    system_prompt: Path
    tool_schema: Path
    scenario_generator: Path
    public_case_manifest: Path
    sealed_referee_manifest: Path
    scorer_source: Path
    metric_test: Path
    verdict_grammar_test: Path
    candidate: Path
    exact_content_manifest: Path

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not isinstance(value, Path):
                raise ContractViolation(f"{field.name} must be Path")
            if value.is_absolute() or ".." in value.parts or str(value) in {"", "."}:
                raise ContractViolation(
                    f"{field.name} must be a repository-relative path"
                )


@dataclass(frozen=True, slots=True)
class VerifiedBindingArtifacts:
    bindings_digest: str
    candidate_sha256: str
    exact_content_manifest_sha256: str
    locked_artifact_count: int

    def __post_init__(self) -> None:
        for name in (
            "bindings_digest",
            "candidate_sha256",
            "exact_content_manifest_sha256",
        ):
            _require_sha256(name, getattr(self, name))
        if (
            not isinstance(self.locked_artifact_count, int)
            or isinstance(self.locked_artifact_count, bool)
            or self.locked_artifact_count <= 0
        ):
            raise ContractViolation("locked_artifact_count must be positive")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_git_head(name: str, value: object) -> str:
    text = _require_text(name, value)
    if len(text) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ContractViolation(f"{name} must be a lowercase Git object id")
    return text


def _current_git_head(target_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise NativeFreezeViolation("unable to resolve target HEAD") from exc
    try:
        return _require_git_head("target_head", completed.stdout.strip())
    except ContractViolation as exc:
        raise NativeFreezeViolation("unable to resolve target HEAD") from exc


def verify_native_freeze(
    *,
    lock_path: Path,
    source_spec_path: Path,
    canonical_spec_path: Path,
    target_root: Path,
    expected_prereg_id: str,
) -> VerifiedNativeFreeze:
    """Verify the workflow runner's raw/canonical/mechanism/HEAD lock locally.

    This deliberately consumes an already-created native lock.  It never creates,
    reviews, accepts, or freezes one.
    """

    for label, path in (
        ("native prereg lock", lock_path),
        ("source prereg spec", source_spec_path),
        ("canonical prereg spec", canonical_spec_path),
    ):
        if not path.is_file():
            raise NativeFreezeViolation(f"{label} is missing")
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NativeFreezeViolation("native prereg lock is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise NativeFreezeViolation("native prereg lock must be a mapping")
    required = {
        "prereg_id",
        "spec_file_sha256",
        "spec_sha256",
        "mechanism_files",
        "target_head",
        "frozen_at",
    }
    unknown = sorted(set(payload) - required)
    missing = sorted(required - set(payload))
    if unknown or missing:
        raise NativeFreezeViolation(
            f"native prereg lock schema drift: missing={missing} unknown={unknown}"
        )
    try:
        prereg_id = _require_text("prereg_id", payload["prereg_id"])
        spec_file_sha256 = _require_sha256(
            "spec_file_sha256", payload["spec_file_sha256"]
        )
        spec_sha256 = _require_sha256("spec_sha256", payload["spec_sha256"])
        target_head = _require_git_head("target_head", payload["target_head"])
        frozen_at = _require_text("frozen_at", payload["frozen_at"])
    except ContractViolation as exc:
        raise NativeFreezeViolation(str(exc)) from exc
    if prereg_id != expected_prereg_id:
        raise NativeFreezeViolation("prereg_id drift")
    if _sha256_file(source_spec_path) != spec_file_sha256:
        raise NativeFreezeViolation("source spec hash drift")
    if _sha256_file(canonical_spec_path) != spec_sha256:
        raise NativeFreezeViolation("canonical spec hash drift")
    raw_mechanisms = payload["mechanism_files"]
    if not isinstance(raw_mechanisms, dict) or not raw_mechanisms:
        raise NativeFreezeViolation("mechanism_files must be a non-empty mapping")
    root = target_root.resolve()
    mechanism_files: list[ArtifactHash] = []
    for raw_path, raw_sha256 in sorted(raw_mechanisms.items()):
        try:
            artifact = ArtifactHash(path=raw_path, sha256=raw_sha256)
        except (ContractViolation, TypeError) as exc:
            raise NativeFreezeViolation("invalid mechanism_files entry") from exc
        resolved = (root / artifact.path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise NativeFreezeViolation("mechanism path escapes target root") from exc
        if not resolved.is_file():
            raise NativeFreezeViolation(f"mechanism file missing: {artifact.path}")
        if _sha256_file(resolved) != artifact.sha256:
            raise NativeFreezeViolation(f"mechanism hash drift: {artifact.path}")
        mechanism_files.append(artifact)
    if _current_git_head(root) != target_head:
        raise NativeFreezeViolation("target HEAD drift")
    return VerifiedNativeFreeze(
        prereg_id=prereg_id,
        lock_sha256=_sha256_file(lock_path),
        spec_file_sha256=spec_file_sha256,
        spec_sha256=spec_sha256,
        mechanism_files=tuple(mechanism_files),
        target_head=target_head,
        frozen_at=frozen_at,
    )


def _resolve_artifact(target_root: Path, relative: Path, label: str) -> Path:
    root = target_root.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ContractViolation(f"{label} path escapes target root") from exc
    if not resolved.is_file():
        raise ContractViolation(f"{label} artifact is missing")
    return resolved


def _canonical_json_file_digest(path: Path, label: str) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractViolation(f"{label} must be valid JSON") from exc
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def verify_binding_artifacts(
    *,
    bindings: RunBindings,
    paths: BindingArtifactPaths,
    freeze: VerifiedNativeFreeze,
    target_root: Path,
) -> VerifiedBindingArtifacts:
    """Bind every run dependency to a real file and the native freeze digest."""

    if not isinstance(bindings, RunBindings):
        raise ContractViolation("bindings must be RunBindings")
    if not isinstance(paths, BindingArtifactPaths):
        raise ContractViolation("paths must be BindingArtifactPaths")
    if not isinstance(freeze, VerifiedNativeFreeze):
        raise ContractViolation("freeze must be VerifiedNativeFreeze")
    expected: tuple[tuple[str, Path, str], ...] = (
        ("system_prompt", paths.system_prompt, bindings.actor.system_prompt_sha256),
        ("tool_schema", paths.tool_schema, bindings.actor.tool_schema_sha256),
        (
            "scenario_generator",
            paths.scenario_generator,
            bindings.corpus.scenario_generator_sha256,
        ),
        (
            "public_case_manifest",
            paths.public_case_manifest,
            bindings.corpus.public_case_manifest_sha256,
        ),
        (
            "sealed_referee_manifest",
            paths.sealed_referee_manifest,
            bindings.corpus.sealed_referee_manifest_sha256,
        ),
        ("scorer_source", paths.scorer_source, bindings.scorer.scorer_source_sha256),
        ("metric_test", paths.metric_test, bindings.scorer.metric_test_sha256),
        (
            "verdict_grammar_test",
            paths.verdict_grammar_test,
            bindings.scorer.verdict_grammar_test_sha256,
        ),
    )
    locked = {item.path: item.sha256 for item in freeze.mechanism_files}
    checked = 0
    for label, relative, expected_sha256 in expected:
        resolved = _resolve_artifact(target_root, relative, label)
        actual = _sha256_file(resolved)
        if actual != expected_sha256:
            raise ContractViolation(f"{label} hash drift")
        posix_path = relative.as_posix()
        if locked.get(posix_path) != actual:
            raise ContractViolation(f"{label} is not bound by native freeze")
        checked += 1
    for case_file in bindings.corpus.case_files:
        relative = Path(case_file.path)
        resolved = _resolve_artifact(target_root, relative, "case_file")
        actual = _sha256_file(resolved)
        if actual != case_file.sha256:
            raise ContractViolation(f"case_file hash drift: {case_file.path}")
        if locked.get(case_file.path) != actual:
            raise ContractViolation(
                f"case_file is not bound by native freeze: {case_file.path}"
            )
        checked += 1
    candidate_path = _resolve_artifact(target_root, paths.candidate, "candidate")
    candidate_sha256 = _canonical_json_file_digest(candidate_path, "candidate")
    if candidate_sha256 != bindings.authority.candidate_sha256:
        raise ContractViolation("candidate hash drift")
    candidate_raw_sha256 = _sha256_file(candidate_path)
    if locked.get(paths.candidate.as_posix()) != candidate_raw_sha256:
        raise ContractViolation("candidate is not bound by native freeze")
    checked += 1
    manifest_path = _resolve_artifact(
        target_root, paths.exact_content_manifest, "exact_content_manifest"
    )
    manifest_sha256 = _sha256_file(manifest_path)
    if manifest_sha256 != bindings.authority.exact_content_manifest_sha256:
        raise ContractViolation("exact_content_manifest hash drift")
    return VerifiedBindingArtifacts(
        bindings_digest=bindings.digest(),
        candidate_sha256=candidate_sha256,
        exact_content_manifest_sha256=manifest_sha256,
        locked_artifact_count=checked,
    )


@dataclass(frozen=True, slots=True)
class ActorRequest:
    request_id: str
    run_id: str
    episode_id: str
    checkpoint_id: str
    arm_id: ArmId
    observable_digest: str
    representation: str
    allowed_actions: tuple[ProbeAction, ...]
    tool_schema_sha256: str

    def __post_init__(self) -> None:
        for name in ("request_id", "run_id", "episode_id", "checkpoint_id"):
            _require_text(name, getattr(self, name))
        if not isinstance(self.arm_id, ArmId):
            raise ContractViolation("arm_id must be ArmId")
        _require_sha256("observable_digest", self.observable_digest)
        if not isinstance(self.representation, str):
            raise ContractViolation("representation must be text")
        if not isinstance(self.allowed_actions, tuple) or not self.allowed_actions:
            raise ContractViolation("allowed_actions must be a non-empty tuple")
        if any(not isinstance(item, ProbeAction) for item in self.allowed_actions):
            raise ContractViolation("allowed_actions must contain ProbeAction values")
        if len(self.allowed_actions) != len(set(self.allowed_actions)):
            raise ContractViolation("allowed_actions must not contain duplicates")
        _require_sha256("tool_schema_sha256", self.tool_schema_sha256)


@dataclass(frozen=True, slots=True)
class ActorResponse:
    request_id: str
    provider: str
    model_id: str
    model_revision_or_snapshot: str
    action: ProbeAction
    raw_output_sha256: str
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "provider",
            "model_id",
            "model_revision_or_snapshot",
        ):
            _require_text(name, getattr(self, name))
        if not isinstance(self.action, ProbeAction):
            raise ContractViolation("action must be ProbeAction")
        _require_sha256("raw_output_sha256", self.raw_output_sha256)
        _require_nonnegative_int("input_tokens", self.input_tokens)
        _require_nonnegative_int("output_tokens", self.output_tokens)


@dataclass(frozen=True, slots=True)
class ArmAssessment:
    arm_id: ArmId
    loss: CheckpointLoss

    def __post_init__(self) -> None:
        if not isinstance(self.arm_id, ArmId):
            raise ContractViolation("arm_id must be ArmId")
        if not isinstance(self.loss, CheckpointLoss):
            raise ContractViolation("loss must be CheckpointLoss")

    @property
    def weight(self) -> int:
        return _CHECKPOINT_LOSS_WEIGHTS[self.loss]


@dataclass(frozen=True, slots=True)
class CheckpointCase:
    episode_id: str
    family: ScenarioFamily
    seed: int
    checkpoint_id: CheckpointId
    actor_requests: tuple[ActorRequest, ...]

    def __post_init__(self) -> None:
        _require_text("episode_id", self.episode_id)
        if not isinstance(self.family, ScenarioFamily):
            raise ContractViolation("family must be ScenarioFamily")
        if (
            not isinstance(self.seed, int)
            or isinstance(self.seed, bool)
            or self.seed <= 0
        ):
            raise ContractViolation("seed must be a positive integer")
        if not isinstance(self.checkpoint_id, CheckpointId):
            raise ContractViolation("checkpoint_id must be CheckpointId")
        if not isinstance(self.actor_requests, tuple) or any(
            not isinstance(request, ActorRequest) for request in self.actor_requests
        ):
            raise ContractViolation("actor_requests must be an ActorRequest tuple")
        arms = tuple(request.arm_id for request in self.actor_requests)
        if len(arms) != len(ArmId) or set(arms) != set(ArmId):
            raise ContractViolation(
                "actor_requests must contain exactly one request per arm"
            )
        if any(
            request.episode_id != self.episode_id for request in self.actor_requests
        ):
            raise ContractViolation("actor request episode_id drift")
        if any(
            request.checkpoint_id != self.checkpoint_id.value
            for request in self.actor_requests
        ):
            raise ContractViolation("actor request checkpoint_id drift")
        observable_digests = {
            request.observable_digest for request in self.actor_requests
        }
        if len(observable_digests) != 1:
            raise ContractViolation("actor requests must share one observable digest")
        allowed_actions = {request.allowed_actions for request in self.actor_requests}
        if len(allowed_actions) != 1:
            raise ContractViolation("actor requests must share one action set")


@dataclass(frozen=True, slots=True)
class RFinalBatch:
    run_id: str
    cases: tuple[CheckpointCase, ...]

    def __post_init__(self) -> None:
        _require_text("run_id", self.run_id)
        if not isinstance(self.cases, tuple) or any(
            not isinstance(case, CheckpointCase) for case in self.cases
        ):
            raise ContractViolation("cases must be a CheckpointCase tuple")
        expected = {
            (family, seed, checkpoint)
            for family in ScenarioFamily
            for seed in HELD_OUT_SEEDS
            for checkpoint in CheckpointId
        }
        observed = {(case.family, case.seed, case.checkpoint_id) for case in self.cases}
        if len(self.cases) != len(expected) or observed != expected:
            raise ContractViolation(
                "r-final batch must provide exact held-out coverage"
            )
        episode_by_pair: dict[tuple[ScenarioFamily, int], str] = {}
        request_ids: set[str] = set()
        for case in self.cases:
            pair = (case.family, case.seed)
            prior_episode = episode_by_pair.setdefault(pair, case.episode_id)
            if prior_episode != case.episode_id:
                raise ContractViolation("episode_id drift across checkpoints")
            for request in case.actor_requests:
                if request.run_id != self.run_id:
                    raise ContractViolation("actor request run_id drift")
                if request.request_id in request_ids:
                    raise ContractViolation("duplicate actor request_id")
                request_ids.add(request.request_id)


@runtime_checkable
class ActorClient(Protocol):
    binding: ActorBinding

    def complete(self, request: ActorRequest) -> ActorResponse: ...


@runtime_checkable
class ScorerClient(Protocol):
    binding: ScorerBinding

    def assess(
        self,
        case: CheckpointCase,
        responses: tuple[ActorResponse, ...],
    ) -> tuple[ArmAssessment, ...]: ...


@runtime_checkable
class C7AbortSignal(Protocol):
    owner_id: str

    def abort_requested(self) -> bool: ...
