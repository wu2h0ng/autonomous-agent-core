"""Container-backed tests capability for benchmark chain runs (ADR-0056).

BenchmarkContainerSandbox is a WorkspaceSandbox subclass: read, apply_patch,
compensation and artifact.write are inherited UNCHANGED; only the
workspace.run_tests path is overridden. Instead of an allowlisted host
pytest subprocess, the tests node executes the task's pinned f2p (then
curated p2p) node ids inside the locked-down per-task container via
ContainerRunner.run_verifier — third-party historic code never runs on the
host (ADR-0056 decision 2). The emitted test report mirrors the base
schema_version "test-report.v1" artifact exactly (same keys, same
content-addressed artifact write) so the existing evaluate node consumes
it without any changes: exit_code is the first failing phase exit or 0,
stdout/stderr concatenate the phases with a marker line, and a non-zero
f2p phase skips p2p (mirroring benchmark_verifier semantics).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from .benchmark_container import ContainerResult
from .benchmark_task import build_verifier_argv
from .capability import CapabilityDenied, WorkspaceSandbox


class ContainerVerifierRunner(Protocol):
    """Structural runner for in-container verifier calls.

    ContainerRunner satisfies this in production; tests inject scripted
    fakes. (Structural typing keeps the sandbox constructor honest without
    subclassing the docker runner.)
    """

    def run_verifier(
        self,
        image_tag: str,
        *,
        work_dir: Path,
        argv: list[str],
        timeout_seconds: int,
        env_allowlist: tuple[str, ...] = (),
    ) -> ContainerResult: ...


class BenchmarkContainerSandbox(WorkspaceSandbox):
    """WorkspaceSandbox whose tests node runs inside the task container.

    The pinned f2p/p2p node ids and the per-task verifier timeout come from
    the frozen task manifest, NOT from capability arguments — the
    allowlisted ``command`` argument is still validated fail-closed but the
    real argv is always ``python -m pytest <pinned ids...>`` built by
    build_verifier_argv (ADR-0056 decision 6).
    """

    def __init__(
        self,
        root: str | Path,
        image_tag: str,
        f2p_node_ids: tuple[str, ...],
        p2p_node_ids: tuple[str, ...],
        timeout_seconds: int,
        container_runner: ContainerVerifierRunner,
        artifacts: str | Path | None = None,
        idempotency_store: object | None = None,
    ) -> None:
        super().__init__(
            root, artifacts=artifacts, idempotency_store=idempotency_store
        )
        # build_verifier_argv validates ids and timeout (fail closed).
        self._f2p_argv = build_verifier_argv(
            f2p_node_ids, timeout_seconds=timeout_seconds
        )
        self._p2p_argv = (
            build_verifier_argv(p2p_node_ids, timeout_seconds=timeout_seconds)
            if p2p_node_ids
            else None
        )
        self.image_tag = image_tag
        self.f2p_node_ids = f2p_node_ids
        self.p2p_node_ids = p2p_node_ids
        self.timeout_seconds = timeout_seconds
        self.container_runner = container_runner

    def _run_tests(
        self, args: dict[str, object], action_key: str
    ) -> dict[str, object]:
        command = str(args.get("command", ""))
        allowed = {"pytest", "python -m pytest", "python3 -m pytest"}
        if command not in allowed:
            raise CapabilityDenied(
                "only the allowlisted test commands are permitted"
            )
        phases: list[tuple[str, list[str], ContainerResult]] = []
        f2p_result = self.container_runner.run_verifier(
            self.image_tag,
            work_dir=self.root,
            argv=list(self._f2p_argv),
            timeout_seconds=self.timeout_seconds,
        )
        phases.append(("f2p", list(self._f2p_argv), f2p_result))
        exit_code = f2p_result.exit_code
        if exit_code == 0 and self._p2p_argv is not None:
            p2p_result = self.container_runner.run_verifier(
                self.image_tag,
                work_dir=self.root,
                argv=list(self._p2p_argv),
                timeout_seconds=self.timeout_seconds,
            )
            phases.append(("p2p", list(self._p2p_argv), p2p_result))
            exit_code = p2p_result.exit_code
        report = {
            "schema_version": "test-report.v1",
            "action_key_sha256": _sha256(action_key.encode("utf-8")),
            "command": " && ".join(
                " ".join(argv) for _, argv, _ in phases
            ),
            "exit_code": exit_code,
            "stdout": "".join(
                _phase_block(name, argv, result.stdout)
                for name, argv, result in phases
            ),
            "stderr": "".join(
                _phase_block(name, argv, result.stderr)
                for name, argv, result in phases
            ),
        }
        output = _canonical_json_bytes(report)
        digest = _sha256(output)
        artifact = self.artifacts / digest
        if not artifact.exists():
            artifact.write_bytes(output)
        return {
            "exit_code": exit_code,
            "artifact_ids": (f"artifact:{digest}",),
            "digest": digest,
        }


def _phase_block(name: str, argv: list[str], text: str) -> str:
    block = f"=== phase {name}: {' '.join(argv)} ===\n{text}"
    return block if block.endswith("\n") else block + "\n"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
