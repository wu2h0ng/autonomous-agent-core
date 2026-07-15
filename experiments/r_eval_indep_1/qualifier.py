"""Hermetic-Python development qualifier for R-EVAL-INDEP-1 Batch-2A.

This module is deliberately a corpus-construction tool, not a result runner.
Candidate source is materialized as bytes and imported only by a fresh
``python -I`` child process.  The isolation boundary protects the coordinator's
Python/import state; it is not an operating-system sandbox for hostile code.
"""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .contracts import CaseTruth, ContractValidationError, MutationClass
from .corpus_contracts import (
    CorpusManifest,
    PublicCaseManifest,
    RefereeCaseManifest,
)
from .corpus_registry import CompiledCase, CompiledCorpus


RUNNER_SOURCE = r'''from __future__ import annotations

import hashlib
import json
import os
import runpy
import sys
from pathlib import Path, PurePosixPath


def fail(message: str) -> None:
    print(json.dumps({"status": "FAIL", "worker_pid": os.getpid(), "detail": message}, sort_keys=True))


def main() -> int:
    root = Path.cwd().resolve(strict=True)
    manifest_path = Path(sys.argv[1]).resolve(strict=True)
    if not manifest_path.is_relative_to(root):
        fail("worker manifest escaped root")
        return 0
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {"schema_version", "runner_sha256", "files", "oracle_relpath"}
    if not isinstance(payload, dict) or set(payload) != expected:
        fail("worker manifest field mismatch")
        return 0
    if payload["schema_version"] != "r-eval-indep-worker-v1":
        fail("worker manifest schema mismatch")
        return 0
    runner_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if runner_digest != payload["runner_sha256"]:
        fail("runner digest mismatch")
        return 0
    files = payload["files"]
    if not isinstance(files, dict) or not files:
        fail("worker file manifest malformed")
        return 0
    for relpath, expected_digest in files.items():
        if not isinstance(relpath, str) or not isinstance(expected_digest, str):
            fail("worker file entry malformed")
            return 0
        path_bits = PurePosixPath(relpath)
        if path_bits.is_absolute() or path_bits.as_posix() != relpath or any(part in {"", ".", ".."} for part in path_bits.parts):
            fail("worker file path malformed")
            return 0
        path = (root / path_bits).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            fail("worker file escaped root")
            return 0
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_digest:
            fail("worker file digest mismatch")
            return 0
    oracle_relpath = payload["oracle_relpath"]
    if oracle_relpath not in files or not oracle_relpath.startswith("referee/"):
        fail("oracle path is not referee-bound")
        return 0
    sys.path.insert(0, str(root / "src"))
    try:
        runpy.run_path(str(root / PurePosixPath(oracle_relpath)), run_name="__main__")
    except BaseException as error:
        detail = f"{type(error).__name__}: {error}"[:512]
        fail(detail)
        return 0
    print(json.dumps({"status": "PASS", "worker_pid": os.getpid(), "detail": "oracle passed"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

RUNNER_BYTES = RUNNER_SOURCE.encode("utf-8")
RUNNER_SHA256 = hashlib.sha256(RUNNER_BYTES).hexdigest()
_CORPUS_TIMEOUT_SECONDS = 1.5
_DEFAULT_OUTPUT_LIMIT = 16_384


class ProcessStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    NONZERO_EXIT = "NONZERO_EXIT"
    PARSE_ERROR = "PARSE_ERROR"
    OUTPUT_LIMIT = "OUTPUT_LIMIT"


class QualificationStatus(str, Enum):
    QUALIFIED_HARMFUL_NOT_EVIDENCE = "QUALIFIED_HARMFUL_NOT_EVIDENCE"
    QUALIFIED_CLEAN_NOT_EVIDENCE = "QUALIFIED_CLEAN_NOT_EVIDENCE"
    REJECTED_BASE_FAILED_NOT_EVIDENCE = "REJECTED_BASE_FAILED_NOT_EVIDENCE"
    REJECTED_MUTANT_SURVIVED_NOT_EVIDENCE = (
        "REJECTED_MUTANT_SURVIVED_NOT_EVIDENCE"
    )
    REJECTED_CLEAN_CONTROL_FAILED_NOT_EVIDENCE = (
        "REJECTED_CLEAN_CONTROL_FAILED_NOT_EVIDENCE"
    )
    REJECTED_INFRASTRUCTURE_NOT_EVIDENCE = (
        "REJECTED_INFRASTRUCTURE_NOT_EVIDENCE"
    )


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    status: ProcessStatus
    worker_pid: int | None
    detail: str
    exit_code: int | None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "worker_pid": self.worker_pid,
            "detail": self.detail,
            "exit_code": self.exit_code,
        }


@dataclass(frozen=True, slots=True)
class CaseQualification:
    case_id: str
    case_truth: CaseTruth
    mutation_class: MutationClass | None
    base: ProcessOutcome
    candidate: ProcessOutcome
    status: QualificationStatus

    @property
    def qualified(self) -> bool:
        return self.status in {
            QualificationStatus.QUALIFIED_HARMFUL_NOT_EVIDENCE,
            QualificationStatus.QUALIFIED_CLEAN_NOT_EVIDENCE,
        }

    def to_mapping(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_truth": self.case_truth.value,
            "mutation_class": (
                None if self.mutation_class is None else self.mutation_class.value
            ),
            "base": self.base.to_mapping(),
            "candidate": self.candidate.to_mapping(),
            "qualification_status": self.status.value,
            "qualified": self.qualified,
            "evidence_status": "NOT_EVIDENCE",
        }


def _normalized_relpath(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ContractValidationError("worker path must be normalized and relative")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ContractValidationError("worker path must be normalized and relative")
    return path.as_posix()


def _write_materialized(root: Path, relpath: str, content: bytes) -> None:
    normalized = _normalized_relpath(relpath)
    target = root / PurePosixPath(normalized)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.5)


def _collect_bounded(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
    output_limit_bytes: int,
) -> tuple[ProcessStatus | None, bytes, int | None]:
    if process.stdout is None:  # pragma: no cover - construction invariant
        raise AssertionError("stdout pipe missing")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output = bytearray()
    deadline = time.monotonic() + timeout_seconds
    forced_status: ProcessStatus | None = None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                forced_status = ProcessStatus.TIMEOUT
                _kill_process_group(process)
                break
            events = selector.select(timeout=min(remaining, 0.05))
            for key, _ in events:
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(chunk)
                if len(output) > output_limit_bytes:
                    forced_status = ProcessStatus.OUTPUT_LIMIT
                    _kill_process_group(process)
                    break
            if forced_status is not None:
                break
            if process.poll() is not None and not selector.get_map():
                break
        if process.poll() is None:
            process.wait(timeout=0.5)
    finally:
        selector.close()
        if process.poll() is None:
            _kill_process_group(process)
        process.stdout.close()
    return forced_status, bytes(output[: output_limit_bytes + 1]), process.returncode


def _parse_outcome(
    forced_status: ProcessStatus | None,
    output: bytes,
    exit_code: int | None,
    expected_worker_pid: int,
) -> ProcessOutcome:
    if forced_status is not None:
        return ProcessOutcome(
            status=forced_status,
            worker_pid=None,
            detail=forced_status.value.lower(),
            exit_code=exit_code,
        )
    if exit_code != 0:
        return ProcessOutcome(
            status=ProcessStatus.NONZERO_EXIT,
            worker_pid=None,
            detail=f"worker exited {exit_code}",
            exit_code=exit_code,
        )
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, value in pairs:
            if key in parsed:
                raise ValueError(f"duplicate JSON key: {key}")
            parsed[key] = value
        return parsed

    try:
        payload = json.loads(
            output.decode("utf-8"), object_pairs_hook=reject_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        return ProcessOutcome(
            status=ProcessStatus.PARSE_ERROR,
            worker_pid=None,
            detail=f"invalid worker response: {type(error).__name__}",
            exit_code=exit_code,
        )
    expected = {"status", "worker_pid", "detail"}
    if not isinstance(payload, Mapping) or set(payload) != expected:
        return ProcessOutcome(
            status=ProcessStatus.PARSE_ERROR,
            worker_pid=None,
            detail="worker response field mismatch",
            exit_code=exit_code,
        )
    status_value = payload.get("status")
    worker_pid = payload.get("worker_pid")
    detail = payload.get("detail")
    if (
        status_value not in {"PASS", "FAIL"}
        or isinstance(worker_pid, bool)
        or not isinstance(worker_pid, int)
        or worker_pid <= 0
        or worker_pid != expected_worker_pid
        or not isinstance(detail, str)
    ):
        return ProcessOutcome(
            status=ProcessStatus.PARSE_ERROR,
            worker_pid=None,
            detail="worker response value mismatch",
            exit_code=exit_code,
        )
    return ProcessOutcome(
        status=ProcessStatus(status_value),
        worker_pid=worker_pid,
        detail=detail,
        exit_code=exit_code,
    )


def _run_variant(
    case: CompiledCase,
    source: bytes,
    *,
    timeout_seconds: float,
    output_limit_bytes: int,
) -> ProcessOutcome:
    with tempfile.TemporaryDirectory(prefix="r-eval-indep-1-") as temp_dir:
        root = Path(temp_dir)
        files: dict[str, bytes] = {
            case.recipe.source.relpath: source,
            case.recipe.public_test.relpath: case.public_test,
            **dict(case.support_files),
            case.recipe.oracle_relpath: case.recipe.oracle_source.encode("utf-8"),
        }
        for relpath, content in files.items():
            _write_materialized(root, relpath, content)
        runner_path = root / "runner.py"
        runner_path.write_bytes(RUNNER_BYTES)
        worker_manifest = {
            "schema_version": "r-eval-indep-worker-v1",
            "runner_sha256": RUNNER_SHA256,
            "files": {
                relpath: hashlib.sha256(content).hexdigest()
                for relpath, content in sorted(files.items())
            },
            "oracle_relpath": case.recipe.oracle_relpath,
        }
        manifest_path = root / "worker_manifest.json"
        manifest_path.write_text(
            json.dumps(worker_manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        environment = {
            "PATH": os.defpath,
            "HOME": temp_dir,
            "TMPDIR": temp_dir,
            "LANG": "C",
            "LC_ALL": "C",
        }
        process = subprocess.Popen(
            [sys.executable, "-I", str(runner_path), str(manifest_path)],
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        forced_status, output, exit_code = _collect_bounded(
            process,
            timeout_seconds=timeout_seconds,
            output_limit_bytes=output_limit_bytes,
        )
        return _parse_outcome(
            forced_status,
            output,
            exit_code,
            expected_worker_pid=process.pid,
        )


def _not_run() -> ProcessOutcome:
    return ProcessOutcome(
        status=ProcessStatus.NOT_RUN,
        worker_pid=None,
        detail="candidate not run because base did not pass",
        exit_code=None,
    )


def qualify_case_dev(
    case: CompiledCase,
    *,
    timeout_seconds: float | None = None,
    output_limit_bytes: int = _DEFAULT_OUTPUT_LIMIT,
) -> CaseQualification:
    """Qualify one pinned case without producing scientific evidence."""

    timeout = case.recipe.timeout_seconds if timeout_seconds is None else timeout_seconds
    if not (0.0 < timeout <= 10.0):
        raise ContractValidationError("timeout_seconds must be in (0, 10]")
    if isinstance(output_limit_bytes, bool) or not isinstance(output_limit_bytes, int):
        raise ContractValidationError("output_limit_bytes must be an integer")
    if not (128 <= output_limit_bytes <= 1_048_576):
        raise ContractValidationError("output_limit_bytes must be in [128, 1048576]")
    base = _run_variant(
        case,
        case.base_source,
        timeout_seconds=timeout,
        output_limit_bytes=output_limit_bytes,
    )
    if base.status is not ProcessStatus.PASS:
        return CaseQualification(
            case_id=case.recipe.case_id,
            case_truth=case.recipe.case_truth,
            mutation_class=case.recipe.mutation_class,
            base=base,
            candidate=_not_run(),
            status=QualificationStatus.REJECTED_BASE_FAILED_NOT_EVIDENCE,
        )
    candidate = _run_variant(
        case,
        case.candidate_source,
        timeout_seconds=timeout,
        output_limit_bytes=output_limit_bytes,
    )
    if candidate.status not in {ProcessStatus.PASS, ProcessStatus.FAIL}:
        status = QualificationStatus.REJECTED_INFRASTRUCTURE_NOT_EVIDENCE
    elif case.recipe.case_truth is CaseTruth.HARMFUL:
        status = (
            QualificationStatus.QUALIFIED_HARMFUL_NOT_EVIDENCE
            if candidate.status is ProcessStatus.FAIL
            else QualificationStatus.REJECTED_MUTANT_SURVIVED_NOT_EVIDENCE
        )
    else:
        status = (
            QualificationStatus.QUALIFIED_CLEAN_NOT_EVIDENCE
            if candidate.status is ProcessStatus.PASS
            else QualificationStatus.REJECTED_CLEAN_CONTROL_FAILED_NOT_EVIDENCE
        )
    return CaseQualification(
        case_id=case.recipe.case_id,
        case_truth=case.recipe.case_truth,
        mutation_class=case.recipe.mutation_class,
        base=base,
        candidate=candidate,
        status=status,
    )


def _verify_compiled_material(
    case: CompiledCase,
    public_manifest: PublicCaseManifest,
    referee_manifest: RefereeCaseManifest,
) -> None:
    recipe = case.recipe
    public = public_manifest
    referee = referee_manifest
    if case.public_manifest.to_mapping() != public.to_mapping():
        raise ContractValidationError("compiled public manifest drift")
    if case.referee_manifest.to_mapping() != referee.to_mapping():
        raise ContractValidationError("compiled referee manifest drift")
    if (
        recipe.case_id != public.case_id
        or recipe.case_id != referee.case_id
        or recipe.source.relpath != public.source_relpath
        or recipe.source.sha256 != public.source_sha256
        or recipe.public_test.relpath != public.test_relpath
        or recipe.public_test.sha256 != public.test_sha256
        or recipe.patch.candidate_sha256 != public.candidate_sha256
        or recipe.patch.patch_sha256 != public.patch_sha256
        or recipe.oracle_relpath != referee.oracle_relpath
        or recipe.oracle_sha256 != referee.oracle_sha256
        or recipe.case_truth is not referee.case_truth
        or recipe.mutation_class is not referee.mutation_class
    ):
        raise ContractValidationError("compiled recipe does not match bound manifests")
    if recipe.timeout_seconds != _CORPUS_TIMEOUT_SECONDS:
        raise ContractValidationError("compiled corpus timeout profile drift")
    support_pins = {ref.relpath: ref.sha256 for ref in recipe.support}
    if support_pins != dict(public.support_sha256):
        raise ContractValidationError("compiled support pins do not match manifest")
    material_digests = {
        "base": hashlib.sha256(case.base_source).hexdigest(),
        "public_test": hashlib.sha256(case.public_test).hexdigest(),
        "candidate": hashlib.sha256(case.candidate_source).hexdigest(),
        "patch": hashlib.sha256(case.candidate_patch).hexdigest(),
        "oracle": hashlib.sha256(recipe.oracle_source.encode("utf-8")).hexdigest(),
    }
    expected_digests = {
        "base": public.source_sha256,
        "public_test": public.test_sha256,
        "candidate": public.candidate_sha256,
        "patch": public.patch_sha256,
        "oracle": referee.oracle_sha256,
    }
    if material_digests != expected_digests:
        raise ContractValidationError("compiled material digest drift")
    if case.candidate_patch.decode("utf-8") != public.candidate_patch:
        raise ContractValidationError("compiled patch bytes do not match public manifest")
    support_material = {
        relpath: hashlib.sha256(content).hexdigest()
        for relpath, content in case.support_files.items()
    }
    if support_material != dict(public.support_sha256):
        raise ContractValidationError("compiled support material digest drift")


def verify_corpus_dev(corpus: CompiledCorpus) -> tuple[CaseQualification, ...]:
    """Verify all development cases; never call a model or result runner."""

    rebuilt = CorpusManifest.from_mapping(corpus.manifest.to_mapping())
    if rebuilt.runner_sha256 != RUNNER_SHA256:
        raise ContractValidationError("corpus runner digest does not match qualifier")
    manifest_ids = [item.case_id for item in rebuilt.public_cases]
    case_ids = [item.recipe.case_id for item in corpus.cases]
    if manifest_ids != case_ids:
        raise ContractValidationError("compiled cases do not match corpus manifest")
    public_by_id = {item.case_id: item for item in rebuilt.public_cases}
    referee_by_id = {item.case_id: item for item in rebuilt.referee_cases}
    for case in corpus.cases:
        _verify_compiled_material(
            case,
            public_by_id[case.recipe.case_id],
            referee_by_id[case.recipe.case_id],
        )
    return tuple(qualify_case_dev(case) for case in corpus.cases)


__all__ = (
    "CaseQualification",
    "ProcessOutcome",
    "ProcessStatus",
    "QualificationStatus",
    "RUNNER_SHA256",
    "RUNNER_SOURCE",
    "qualify_case_dev",
    "verify_corpus_dev",
)
