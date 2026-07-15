"""One-shot raw result runner contract for R-STATE-CREDIT-1 Stage A.

The module has no provider implementation, no corpus or scorer implementation,
and no CLI entry point.  A caller must inject complete, verified bindings plus
typed actor, scorer, and C7 dependencies.  The raw artifact never adjudicates a
verdict.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from experiments.r_state_credit_1.contracts import (
    ArmId,
    ContractViolation,
    canonical_json,
)
from experiments.r_state_credit_1.run_contracts import (
    ArmAssessment,
    ActorClient,
    ActorRequest,
    ActorResponse,
    BindingArtifactPaths,
    C7AbortSignal,
    CheckpointCase,
    CheckpointId,
    CheckpointLoss,
    ExecutionDependencyFailure,
    RFinalBatch,
    RunBindings,
    ScorerClient,
    VerifiedNativeFreeze,
    verify_binding_artifacts,
)


PREREG_ID = "R-STATE-CREDIT-1-STAGE-A-20260715"
EXPERIMENT_ID = "R-STATE-CREDIT-1-STAGE-A"


class RunnerViolation(RuntimeError):
    """Raised when execution would cross a frozen or one-shot boundary."""


class _PostStartC7Abort(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RFinalRunReceipt:
    result_path: Path
    result_sha256: str
    row_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.result_path, Path):
            raise ContractViolation("result_path must be Path")
        if len(self.result_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.result_sha256
        ):
            raise ContractViolation("result_sha256 must be a lowercase SHA-256")
        if (
            not isinstance(self.row_count, int)
            or isinstance(self.row_count, bool)
            or self.row_count <= 0
        ):
            raise ContractViolation("row_count must be positive")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_exclusive_json(path: Path, payload: object) -> None:
    encoded = (canonical_json(payload) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RunnerViolation(
            f"RERUN_FORBIDDEN: artifact already exists: {path.name}"
        ) from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_descriptor = os.open(path.parent, directory_flags)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def verify_raw_result_content_digest(path: Path) -> bool:
    """Verify the raw payload digest without interpreting a scientific verdict."""

    if not isinstance(path, Path) or path.is_symlink() or not path.is_file():
        raise RunnerViolation("raw result path must be a regular non-symlink file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunnerViolation("raw result is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise RunnerViolation("raw result must be a mapping")
    claimed = payload.pop("content_sha256", None)
    if not isinstance(claimed, str):
        raise RunnerViolation("raw result content_sha256 is missing")
    actual = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    if actual != claimed:
        raise RunnerViolation("raw result content_sha256 drift")
    return True


def _abort_requested(c7: C7AbortSignal) -> bool:
    value = c7.abort_requested()
    if not isinstance(value, bool):
        raise RunnerViolation("C7 abort signal must return bool")
    return value


def _validate_dependencies(
    *,
    bindings: RunBindings,
    freeze: VerifiedNativeFreeze,
    batch: RFinalBatch,
    actor: ActorClient,
    scorer: ScorerClient,
    c7: C7AbortSignal,
) -> None:
    if not isinstance(bindings, RunBindings):
        raise RunnerViolation("bindings must be RunBindings")
    if not isinstance(freeze, VerifiedNativeFreeze):
        raise RunnerViolation("freeze must be VerifiedNativeFreeze")
    if freeze.prereg_id != PREREG_ID:
        raise RunnerViolation("native prereg_id drift")
    if not isinstance(batch, RFinalBatch):
        raise RunnerViolation("batch must be RFinalBatch")
    if not isinstance(actor, ActorClient):
        raise RunnerViolation("actor must satisfy ActorClient")
    if actor.binding != bindings.actor:
        raise RunnerViolation("actor binding drift")
    if not isinstance(scorer, ScorerClient):
        raise RunnerViolation("scorer must satisfy ScorerClient")
    if scorer.binding != bindings.scorer:
        raise RunnerViolation("scorer binding drift")
    if not isinstance(c7, C7AbortSignal):
        raise RunnerViolation("c7 must satisfy C7AbortSignal")
    if c7.owner_id != bindings.authority.c7_owner_id:
        raise RunnerViolation("C7 owner binding drift")
    if c7.epoch != bindings.authority.c7_epoch:
        raise RunnerViolation("C7 epoch binding drift")
    if c7.capability_token_sha256 != bindings.authority.c7_capability_token_sha256:
        raise RunnerViolation("C7 capability binding drift")


def _validate_actor_response(
    request: ActorRequest,
    response: object,
    bindings: RunBindings,
) -> ActorResponse:
    if not isinstance(response, ActorResponse):
        raise RunnerViolation("actor returned an untyped response")
    if response.request_id != request.request_id:
        raise RunnerViolation("actor response request_id drift")
    if response.actor_request_sha256 != request.digest():
        raise RunnerViolation("actor response request digest drift")
    if (
        response.provider != bindings.actor.provider
        or response.model_id != bindings.actor.model_id
        or response.model_revision_or_snapshot
        != bindings.actor.model_revision_or_snapshot
    ):
        raise RunnerViolation("actor response identity drift")
    if response.action not in request.allowed_actions:
        raise RunnerViolation("actor response action outside frozen grammar")
    return response


def _case_sort_key(case: CheckpointCase) -> tuple[int, int, int]:
    return (
        list(type(case.family)).index(case.family),
        case.seed,
        list(CheckpointId).index(case.checkpoint_id),
    )


def _terminal_and_raise(
    *,
    terminal_path: Path,
    status: str,
    run_id: str,
    bindings: RunBindings,
    freeze: VerifiedNativeFreeze,
    error: BaseException,
) -> NoReturn:
    _write_exclusive_json(
        terminal_path,
        {
            "schema_version": "r-state-credit-1-rfinal-terminal-v1",
            "status": status,
            "run_id": run_id,
            "bindings_sha256": bindings.digest(),
            "prereg_lock_sha256": freeze.lock_sha256,
        },
    )
    raise error


def execute_r_final_once(
    *,
    run_dir: Path,
    target_root: Path,
    bindings: RunBindings,
    binding_artifact_paths: BindingArtifactPaths,
    freeze: VerifiedNativeFreeze,
    batch: RFinalBatch,
    actor: ActorClient,
    scorer: ScorerClient,
    c7: C7AbortSignal,
) -> RFinalRunReceipt:
    """Execute one exact raw pass or leave a permanent no-rerun marker.

    This function is intentionally not exposed through a CLI.  Result-bearing use
    requires a later lane to supply a native accepted freeze and real bound
    dependencies.  Tests exercise it only with in-memory fakes and temporary files.
    """

    if not isinstance(run_dir, Path) or not isinstance(target_root, Path):
        raise RunnerViolation("run_dir and target_root must be Path")
    _validate_dependencies(
        bindings=bindings,
        freeze=freeze,
        batch=batch,
        actor=actor,
        scorer=scorer,
        c7=c7,
    )
    verified_artifacts = verify_binding_artifacts(
        bindings=bindings,
        paths=binding_artifact_paths,
        freeze=freeze,
        target_root=target_root,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    start_path = run_dir / "rfinal.start.json"
    result_path = run_dir / "rfinal.result.json"
    terminal_path = run_dir / "rfinal.terminal.json"
    if any(path.exists() for path in (start_path, result_path, terminal_path)):
        raise RunnerViolation(
            "RERUN_FORBIDDEN: this run directory already has an execution claim"
        )
    if _abort_requested(c7):
        raise RunnerViolation("C7_ABORT_BEFORE_START")
    _write_exclusive_json(
        start_path,
        {
            "schema_version": "r-state-credit-1-rfinal-start-v1",
            "status": "STARTED_NO_SAME_LOCK_RERUN",
            "experiment_id": EXPERIMENT_ID,
            "prereg_id": PREREG_ID,
            "run_id": batch.run_id,
            "bindings_sha256": verified_artifacts.bindings_digest,
            "prereg_lock_sha256": freeze.lock_sha256,
            "target_head": freeze.target_head,
            "c7_owner_id": bindings.authority.c7_owner_id,
            "c7_epoch": bindings.authority.c7_epoch,
            "c7_capability_token_sha256": (
                bindings.authority.c7_capability_token_sha256
            ),
            "run_authority_ref": (
                bindings.authority.founder_or_cto_run_authorization_ref
            ),
        },
    )
    rows: list[dict[str, object]] = []
    try:
        for case in sorted(batch.cases, key=_case_sort_key):
            responses: list[ActorResponse] = []
            for request in sorted(
                case.actor_requests, key=lambda item: list(ArmId).index(item.arm_id)
            ):
                if request.tool_schema_sha256 != bindings.actor.tool_schema_sha256:
                    raise RunnerViolation("actor request tool-schema drift")
                if _abort_requested(c7):
                    raise _PostStartC7Abort("C7 abort before actor call")
                response = _validate_actor_response(
                    request,
                    actor.complete(request),
                    bindings,
                )
                responses.append(response)
                if _abort_requested(c7):
                    raise _PostStartC7Abort("C7 abort after actor call")
            if _abort_requested(c7):
                raise _PostStartC7Abort("C7 abort before scorer")
            assessments = scorer.assess(case, tuple(responses))
            if not isinstance(assessments, tuple):
                raise RunnerViolation(
                    "scorer returned an untyped assessment collection"
                )
            if any(
                not isinstance(assessment, ArmAssessment) for assessment in assessments
            ):
                raise RunnerViolation("scorer returned an untyped assessment")
            by_arm = {assessment.arm_id: assessment for assessment in assessments}
            if len(assessments) != len(ArmId) or set(by_arm) != set(ArmId):
                raise RunnerViolation(
                    "scorer must return exactly one assessment per arm"
                )
            for request, response in zip(
                sorted(
                    case.actor_requests,
                    key=lambda item: list(ArmId).index(item.arm_id),
                ),
                responses,
                strict=True,
            ):
                assessment = by_arm[request.arm_id]
                rows.append(
                    {
                        "episode_id": case.episode_id,
                        "family": case.family.value,
                        "seed": case.seed,
                        "checkpoint_id": case.checkpoint_id.value,
                        "arm_id": request.arm_id.value,
                        "request_id": request.request_id,
                        "response_id": response.response_id,
                        "observable_digest": request.observable_digest,
                        "action": response.action.value,
                        "model_revision_or_snapshot": (
                            response.model_revision_or_snapshot
                        ),
                        "actor_request_sha256": response.actor_request_sha256,
                        "provider_request_sha256": response.provider_request_sha256,
                        "provider_response_sha256": (response.provider_response_sha256),
                        "raw_output_sha256": response.raw_output_sha256,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "total_tokens": response.usage.total_tokens,
                        "cost_status": response.cost.status.value,
                        "cost_amount_microunits": response.cost.amount_microunits,
                        "cost_currency": response.cost.currency,
                        "latency_ms": response.latency_ms,
                        "timeout_seconds": response.timeout_seconds,
                        "error_code": response.error_code,
                        "timed_out": response.timed_out,
                        "loss_code": assessment.loss.value,
                        "loss_weight": assessment.weight,
                        "unsafe_effect_replay": (
                            assessment.loss is CheckpointLoss.UNSAFE_EFFECT_REPLAY
                        ),
                    }
                )
            if _abort_requested(c7):
                raise _PostStartC7Abort("C7 abort after scorer")
        payload: dict[str, object] = {
            "schema_version": "r-state-credit-1-rfinal-raw-v1",
            "artifact_class": "R_FINAL_RAW",
            "status": "RAW_NOT_ADJUDICATED",
            "experiment_id": EXPERIMENT_ID,
            "prereg_id": PREREG_ID,
            "run_id": batch.run_id,
            "bindings_sha256": verified_artifacts.bindings_digest,
            "prereg_lock_sha256": freeze.lock_sha256,
            "spec_sha256": freeze.spec_sha256,
            "target_head": freeze.target_head,
            "candidate_sha256": verified_artifacts.candidate_sha256,
            "exact_content_manifest_sha256": (
                verified_artifacts.exact_content_manifest_sha256
            ),
            "c7_owner_id": bindings.authority.c7_owner_id,
            "c7_epoch": bindings.authority.c7_epoch,
            "c7_capability_token_sha256": (
                bindings.authority.c7_capability_token_sha256
            ),
            "run_authority_ref": (
                bindings.authority.founder_or_cto_run_authorization_ref
            ),
            "rows": rows,
        }
        payload["content_sha256"] = hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()
        _write_exclusive_json(result_path, payload)
    except _PostStartC7Abort as exc:
        _terminal_and_raise(
            terminal_path=terminal_path,
            status="INVALID_C7_ABORT_NO_SAME_LOCK_RERUN",
            run_id=batch.run_id,
            bindings=bindings,
            freeze=freeze,
            error=RunnerViolation(f"INVALID_C7_ABORT: {exc}"),
        )
    except BaseException as exc:
        status = (
            "INVALID_RUNNER_CONTRACT_NO_SAME_LOCK_RERUN"
            if isinstance(exc, (RunnerViolation, ExecutionDependencyFailure))
            else "INTERRUPTED_NO_SAME_LOCK_RERUN"
        )
        _terminal_and_raise(
            terminal_path=terminal_path,
            status=status,
            run_id=batch.run_id,
            bindings=bindings,
            freeze=freeze,
            error=exc,
        )
    return RFinalRunReceipt(
        result_path=result_path,
        result_sha256=_sha256_file(result_path),
        row_count=len(rows),
    )
