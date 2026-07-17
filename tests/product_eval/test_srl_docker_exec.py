"""RED tests for the local, effect-free Docker arm executor candidate."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import threading

import pytest

from agent_os_contracts import content_digest
from product_evals.srl_e2e_falsifier import docker_exec as docker_module
from product_evals.srl_e2e_falsifier.contracts import (
    CandidateKind,
    DecisionCandidate,
    decision_candidate_digest,
)
from product_evals.srl_e2e_falsifier.docker_exec import (
    DockerExecutionRequest,
    DockerExecutionFailed,
    DockerExecutorUnavailable,
    trusted_docker_executor,
    _run_fixed_policy_probe,
)


def _candidate() -> DecisionCandidate:
    payload = {
        "schema_version": "1.0",
        "candidate_id": "candidate:docker-pure-worker",
        "candidate_kind": CandidateKind.NONE.value,
        "public_state_digest": "a" * 64,
        "no_external_effect": True,
        "desired_outcome": None,
        "acceptance_criteria": (),
        "missing_input_kind": None,
        "minimum_question": None,
        "created_at": datetime(2026, 7, 17, tzinfo=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
    }
    payload["candidate_digest"] = decision_candidate_digest(payload)
    return DecisionCandidate.model_validate(payload)


def _request() -> DockerExecutionRequest:
    candidate = _candidate()
    payload = {
        "schema_version": "1.0",
        "request_id": "docker-request:1",
        "public_state_digest": candidate.public_state_digest,
        "candidate": candidate.model_dump(mode="json"),
    }
    payload["request_digest"] = content_digest(payload)
    return DockerExecutionRequest.from_mapping(payload)


def test_factory_forbids_caller_selected_image() -> None:
    with pytest.raises(TypeError):
        trusted_docker_executor(allowed_image="python:3.12-slim")  # type: ignore[call-arg]


def test_input_schema_rejects_unknown_nonfinite_and_oversized_values() -> None:
    request = _request()
    payload = request.to_mapping()
    payload["unknown"] = True
    with pytest.raises(ValueError, match="exact schema"):
        DockerExecutionRequest.from_mapping(payload)

    raw = json.dumps(request.to_mapping()).replace('"schema_version": "1.0"', '"schema_version": NaN')
    with pytest.raises(ValueError, match="finite JSON"):
        DockerExecutionRequest.from_json(raw.encode())

    with pytest.raises(ValueError, match="input exceeds"):
        DockerExecutionRequest.from_json(b" " * 65_537)


def test_policy_ceiling_is_fixed_and_contains_no_host_authority() -> None:
    executor = trusted_docker_executor()
    args = executor.execution_ceiling.docker_security_args
    joined = " ".join(args)
    for required in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--pids-limit 32",
        "--memory 64m",
        "--memory-swap 64m",
        "--cpus 0.5",
        "--ulimit fsize=1024:1024",
        "--ulimit nofile=64:64",
        "--tmpfs /tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777",
        "--user 65532:65532",
        "--log-driver none",
    ):
        assert required in joined
    for forbidden in (
        "--privileged",
        "/var/run/docker.sock",
        "--device",
        "--pid host",
        "--network host",
        "--env-file",
        "--mount",
    ):
        assert forbidden not in joined
    assert executor.execution_ceiling.environment == ()
    assert executor.execution_ceiling.worker_artifact_sha256 == hashlib.sha256(
        executor.worker_bytes
    ).hexdigest()


def test_real_pure_worker_success_is_exactly_bound_and_container_removed() -> None:
    executor = trusted_docker_executor()
    request = _request()
    receipt = executor.execute(request)
    assert receipt.request_digest == request.request_digest
    assert receipt.candidate == request.candidate
    assert receipt.image_identity == executor.execution_ceiling.allowed_image_identity
    assert receipt.image_identity == (
        "python@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf"
    )
    assert receipt.resolved_image_id == "sha256:" + receipt.image_identity.rsplit(":", 1)[1]
    assert receipt.network_mode == "none"
    assert receipt.rootfs_read_only is True
    assert receipt.environment_empty is True
    assert receipt.no_external_effect is True
    assert (
        receipt.worker_artifact_sha256
        == executor.execution_ceiling.worker_artifact_sha256
    )
    assert receipt.receipt_digest == content_digest(
        receipt.to_mapping(exclude_digest=True)
    )
    executor.verify_local_receipt(receipt)
    assert receipt.cleanup_absent is True
    assert receipt.cleanup_remove_exit_code == 0
    assert receipt.exit_code == 0
    assert len(receipt.container_id) == 64
    assert receipt.pre_start_inspect_digest != receipt.post_start_inspect_digest
    assert receipt.cleanup_digest == content_digest(
        {"cleanup_remove_exit_code": 0, "cleanup_absent": True}
    )
    assert not subprocess.run(
        ["docker", "container", "inspect", receipt.container_id],
        capture_output=True,
        check=False,
    ).returncode == 0


def test_missing_daemon_or_image_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", unavailable)
    with pytest.raises(DockerExecutorUnavailable, match="Docker CLI/daemon unavailable"):
        trusted_docker_executor()


def _assert_removed(name: str) -> None:
    assert subprocess.run(
        ["docker", "container", "inspect", name],
        capture_output=True,
        check=False,
    ).returncode != 0


def test_real_no_network_blocks_connection_to_live_host_listener() -> None:
    executor = trusted_docker_executor()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(1.0)
    accepted: list[bool] = []

    def accept_once() -> None:
        try:
            connection, _ = listener.accept()
        except TimeoutError:
            return
        connection.close()
        accepted.append(True)

    # Unsandboxed control proves this is a real reachable listener.
    control = socket.create_connection(listener.getsockname(), timeout=1)
    control.close()
    first, _ = listener.accept()
    first.close()
    thread = threading.Thread(target=accept_once)
    thread.start()
    completed, name = _run_fixed_policy_probe(
        executor,
        "network",
        arguments=("host.docker.internal", str(listener.getsockname()[1])),
    )
    thread.join(timeout=2)
    listener.close()
    assert completed.returncode == 0
    assert completed.stdout.strip() == b"blocked"
    assert accepted == []
    _assert_removed(name)


def test_real_host_workspace_home_and_environment_are_absent() -> None:
    executor = trusted_docker_executor()
    completed, name = _run_fixed_policy_probe(executor, "host")
    assert completed.returncode == 0
    assert completed.stdout.splitlines() == [b"0", b"write-denied", b"0"]
    _assert_removed(name)


def test_real_pid_memory_and_tmpfs_limits_fail_closed() -> None:
    executor = trusted_docker_executor()
    pids, pids_name = _run_fixed_policy_probe(executor, "pids")
    assert pids.returncode == 0
    assert int(pids.stdout) < 32
    _assert_removed(pids_name)

    memory, memory_name = _run_fixed_policy_probe(executor, "memory")
    assert memory.returncode != 0
    assert b"unexpected" not in memory.stdout
    _assert_removed(memory_name)

    tmpfs, tmpfs_name = _run_fixed_policy_probe(executor, "tmpfs")
    assert tmpfs.returncode == 0
    assert tmpfs.stdout.strip() == b"capped"
    _assert_removed(tmpfs_name)


def test_output_cap_rejects_before_receipt_parse() -> None:
    executor = trusted_docker_executor()
    with pytest.raises(DockerExecutionFailed, match="output exceeds"):
        executor._validate_worker_output(b"x" * 65_537, _request())
    with pytest.raises(DockerExecutionFailed, match="output exceeds"):
        _run_fixed_policy_probe(executor, "output")


def test_policy_worker_and_receipt_mutation_fail_closed() -> None:
    executor = trusted_docker_executor()
    mutated = replace(
        executor.execution_ceiling,
        docker_security_args=executor.execution_ceiling.docker_security_args
        + ("--privileged",),
    )
    object.__setattr__(executor, "execution_ceiling", mutated)
    with pytest.raises(DockerExecutionFailed, match="policy or worker"):
        executor.execute(_request())

    worker_mutated = trusted_docker_executor()
    object.__setattr__(worker_mutated, "worker_bytes", b"print('owned')")
    with pytest.raises(DockerExecutionFailed, match="policy or worker"):
        worker_mutated.execute(_request())

    receipt_executor = trusted_docker_executor()
    receipt = receipt_executor.execute(_request())
    tampered = replace(receipt, stdout_digest="b" * 64)
    with pytest.raises(DockerExecutionFailed, match="receipt integrity"):
        receipt_executor.verify_local_receipt(tampered)


def test_cleanup_failure_cannot_return_success(monkeypatch: pytest.MonkeyPatch) -> None:
    original = docker_module._docker_run

    def fail_remove(
        args: list[str], *, timeout: int = 10
    ) -> subprocess.CompletedProcess[str]:
        if args[:4] == ["docker", "container", "rm", "--force"]:
            return subprocess.CompletedProcess(args, 1, "", "simulated cleanup failure")
        return original(args, timeout=timeout)

    monkeypatch.setattr(docker_module, "_docker_run", fail_remove)
    with pytest.raises(DockerExecutionFailed, match="cleanup failed"):
        trusted_docker_executor().execute(_request())
    monkeypatch.undo()
    leaked = subprocess.run(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--filter",
            "name=agent-os-srl-",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    if leaked:
        subprocess.run(
            ["docker", "container", "rm", "--force", *leaked],
            check=True,
            capture_output=True,
        )


def test_container_name_change_cannot_redirect_id_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = docker_module._docker_run
    renamed = False

    def rename_after_create(
        args: list[str], *, timeout: int = 10
    ) -> subprocess.CompletedProcess[str]:
        nonlocal renamed
        result = original(args, timeout=timeout)
        if args[:2] == ["docker", "create"] and result.returncode == 0:
            container_id = result.stdout.strip()
            subprocess.run(
                ["docker", "container", "rename", container_id, f"renamed-{container_id[:12]}"],
                check=True,
                capture_output=True,
            )
            renamed = True
        return result

    monkeypatch.setattr(docker_module, "_docker_run", rename_after_create)
    receipt = trusted_docker_executor().execute(_request())
    assert renamed is True
    assert receipt.cleanup_absent is True


def test_malformed_create_stdout_uses_exact_cidfile_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = docker_module._docker_run

    def corrupt_stdout(
        args: list[str], *, timeout: int = 10
    ) -> subprocess.CompletedProcess[str]:
        result = original(args, timeout=timeout)
        if args[:2] == ["docker", "create"] and result.returncode == 0:
            return subprocess.CompletedProcess(
                args, result.returncode, "malformed stdout\n", result.stderr
            )
        return result

    monkeypatch.setattr(docker_module, "_docker_run", corrupt_stdout)
    receipt = trusted_docker_executor().execute(_request())
    assert len(receipt.container_id) == 64
    assert receipt.cleanup_absent is True


def test_nonreading_worker_cannot_block_stdin_or_escape_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_popen = docker_module.subprocess.Popen
    observed_file_stdin: list[bool] = []

    def observe_stdin(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        command = args[0] if args else None
        if (
            isinstance(command, list)
            and command[:2] == ["docker", "start"]
        ):
            stdin = kwargs.get("stdin")
            observed_file_stdin.append(
                stdin is not subprocess.PIPE and hasattr(stdin, "fileno")
            )
        return original_popen(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(docker_module.subprocess, "Popen", observe_stdin)
    with pytest.raises(DockerExecutionFailed, match="timed out and was killed"):
        _run_fixed_policy_probe(trusted_docker_executor(), "stdin_timeout")
    assert observed_file_stdin == [True]
    remaining = subprocess.run(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--filter",
            "name=agent-os-srl-probe-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert remaining.stdout.strip() == ""


def test_invalid_cidfile_uses_name_label_fallback_and_leaves_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = docker_module._docker_run

    def corrupt_cidfile(
        args: list[str], *, timeout: int = 10
    ) -> subprocess.CompletedProcess[str]:
        result = original(args, timeout=timeout)
        if args[:2] == ["docker", "create"] and result.returncode == 0:
            cidfile = Path(args[args.index("--cidfile") + 1])
            cidfile.write_text("not-a-container-id\n", encoding="ascii")
        return result

    monkeypatch.setattr(docker_module, "_docker_run", corrupt_cidfile)
    with pytest.raises(DockerExecutionFailed, match="cidfile identity is invalid"):
        trusted_docker_executor().execute(_request())
    remaining = subprocess.run(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--filter",
            "name=agent-os-srl-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert remaining.stdout.strip() == ""
