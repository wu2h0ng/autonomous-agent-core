"""Bounded local Docker executor candidate for SRL falsifier arm workers.

This module is deliberately not wired to ``SrlE2EFalsifierHarness.evaluate_unit``.
It supplies local process isolation and integrity receipts only; it establishes
neither independent scorer custody nor result-run authority.

The shared Docker daemon is trusted local infrastructure in this candidate.
Daemon compromise and independent daemon custody remain explicit P2 gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import select
import secrets
import subprocess
import tempfile
from types import MappingProxyType
from typing import Any, Mapping
import time
import uuid

from agent_os_contracts import canonical_json, content_digest

from .contracts import DecisionCandidate


_MAX_JSON_BYTES = 65_536
_LOCAL_TEMP_BASE = Path("/tmp/agent-os-srl-docker-exec-v1")
_FIXED_IMAGE_REFERENCE = (
    "python@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf"
)
_FIXED_IMAGE_ID = (
    "sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf"
)
_FULL_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REPO_DIGEST = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}\Z")
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
_TRUSTED_FACTORY_TOKEN = object()

_WORKER = b'''from __future__ import annotations
import hashlib
import json
import math
import os
import sys
import time

MAX_BYTES = 65536
KEYS = {"schema_version", "request_id", "public_state_digest", "candidate", "request_digest"}

def reject_constant(value):
    raise ValueError("nonfinite")

raw = sys.stdin.buffer.read(MAX_BYTES + 1)
if len(raw) > MAX_BYTES:
    raise SystemExit(64)
try:
    value = json.loads(raw, parse_constant=reject_constant)
except Exception:
    raise SystemExit(65)
if not isinstance(value, dict) or set(value) != KEYS or value.get("schema_version") != "1.0":
    raise SystemExit(66)
# CPython may synthesize LC_CTYPE in ``os.environ`` after an env-empty exec;
# /proc preserves the environment bytes actually supplied at exec time.
if open("/proc/self/environ", "rb").read():
    raise SystemExit(67)
payload = {
    "schema_version": "1.0",
    "request_id": value["request_id"],
    "request_digest": value["request_digest"],
    "public_state_digest": value["public_state_digest"],
    "candidate": value["candidate"],
}
encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
if len(encoded) > MAX_BYTES:
    raise SystemExit(68)
time.sleep(.1)
sys.stdout.buffer.write(encoded)
'''


class DockerExecutorUnavailable(RuntimeError):
    """The trusted local Docker execution precondition is unavailable."""


class DockerExecutionFailed(RuntimeError):
    """The isolated worker did not return a valid bounded receipt."""


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"finite JSON required; found {value}")


def _validate_finite(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("finite JSON required")
    if isinstance(value, Mapping):
        for child in value.values():
            _validate_finite(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_finite(child)


@dataclass(frozen=True)
class DockerExecutionRequest:
    """Exact proposal-only worker input."""

    request_id: str
    public_state_digest: str
    candidate: DecisionCandidate
    request_digest: str
    schema_version: str = "1.0"

    @classmethod
    def from_json(cls, raw: bytes) -> DockerExecutionRequest:
        if type(raw) is not bytes:
            raise ValueError("Docker worker input must be bytes")
        if len(raw) > _MAX_JSON_BYTES:
            raise ValueError("Docker worker input exceeds 65536 bytes")
        try:
            payload = json.loads(raw, parse_constant=_reject_nonfinite)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Docker worker input must be finite JSON") from None
        if not isinstance(payload, dict):
            raise ValueError("Docker worker input must be an exact object")
        return cls.from_mapping(payload)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> DockerExecutionRequest:
        keys = {
            "schema_version",
            "request_id",
            "public_state_digest",
            "candidate",
            "request_digest",
        }
        if set(payload) != keys:
            raise ValueError("Docker worker input must use the exact schema")
        _validate_finite(payload)
        if payload["schema_version"] != "1.0":
            raise ValueError("Docker worker input schema_version must be 1.0")
        if type(payload["request_id"]) is not str or not payload["request_id"]:
            raise ValueError("request_id must be a nonempty string")
        candidate_raw = payload["candidate"]
        if not isinstance(candidate_raw, Mapping):
            raise ValueError("candidate must be an exact DecisionCandidate object")
        candidate = DecisionCandidate.model_validate(candidate_raw)
        if payload["public_state_digest"] != candidate.public_state_digest:
            raise ValueError("request state must match candidate state")
        supplied_digest = payload["request_digest"]
        digest_payload = dict(payload)
        del digest_payload["request_digest"]
        expected_digest = content_digest(digest_payload)
        if supplied_digest != expected_digest:
            raise ValueError("request_digest does not match exact input")
        instance = cls(
            request_id=payload["request_id"],
            public_state_digest=candidate.public_state_digest,
            candidate=candidate,
            request_digest=expected_digest,
        )
        if len(instance.to_json()) > _MAX_JSON_BYTES:
            raise ValueError("Docker worker input exceeds 65536 bytes")
        return instance

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "public_state_digest": self.public_state_digest,
            "candidate": self.candidate.model_dump(mode="json"),
            "request_digest": self.request_digest,
        }

    def to_json(self) -> bytes:
        return canonical_json(self.to_mapping()).encode("utf-8")


@dataclass(frozen=True)
class DockerPolicyCeiling:
    """Non-extensible execution ceiling minted only by the trusted factory."""

    allowed_image_identity: str
    resolved_image_id: str
    docker_security_args: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    worker_artifact_sha256: str
    timeout_seconds: int
    policy_digest: str


@dataclass(frozen=True)
class DockerExecutionReceipt:
    schema_version: str
    request_id: str
    request_digest: str
    public_state_digest: str
    candidate: DecisionCandidate
    image_identity: str
    resolved_image_id: str
    policy_digest: str
    worker_artifact_sha256: str
    container_id: str
    pre_start_inspect_digest: str
    post_start_inspect_digest: str
    exit_code: int
    stdout_digest: str
    stderr_digest: str
    network_mode: str
    rootfs_read_only: bool
    environment_empty: bool
    no_external_effect: bool
    cleanup_remove_exit_code: int
    cleanup_absent: bool
    cleanup_digest: str
    receipt_digest: str
    local_integrity_hmac: str

    def to_mapping(self, *, exclude_digest: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "request_digest": self.request_digest,
            "public_state_digest": self.public_state_digest,
            "candidate": self.candidate.model_dump(mode="json"),
            "image_identity": self.image_identity,
            "resolved_image_id": self.resolved_image_id,
            "policy_digest": self.policy_digest,
            "worker_artifact_sha256": self.worker_artifact_sha256,
            "container_id": self.container_id,
            "pre_start_inspect_digest": self.pre_start_inspect_digest,
            "post_start_inspect_digest": self.post_start_inspect_digest,
            "exit_code": self.exit_code,
            "stdout_digest": self.stdout_digest,
            "stderr_digest": self.stderr_digest,
            "network_mode": self.network_mode,
            "rootfs_read_only": self.rootfs_read_only,
            "environment_empty": self.environment_empty,
            "no_external_effect": self.no_external_effect,
            "cleanup_remove_exit_code": self.cleanup_remove_exit_code,
            "cleanup_absent": self.cleanup_absent,
            "cleanup_digest": self.cleanup_digest,
        }
        if not exclude_digest:
            payload["receipt_digest"] = self.receipt_digest
            payload["local_integrity_hmac"] = self.local_integrity_hmac
        return payload


def _docker_run(args: list[str], *, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise DockerExecutorUnavailable("Docker CLI/daemon unavailable") from exc


def _resolve_fixed_image() -> tuple[str, str]:
    if not _REPO_DIGEST.fullmatch(_FIXED_IMAGE_REFERENCE):
        raise DockerExecutorUnavailable("fixed Docker repo digest grammar is invalid")
    if not _FULL_IMAGE_ID.fullmatch(_FIXED_IMAGE_ID):
        raise DockerExecutorUnavailable("fixed Docker image ID grammar is invalid")
    inspected = _docker_run(["docker", "image", "inspect", _FIXED_IMAGE_REFERENCE])
    if inspected.returncode != 0:
        raise DockerExecutorUnavailable("allowed immutable Docker image is unavailable")
    try:
        values = json.loads(inspected.stdout)
        if len(values) != 1 or not isinstance(values[0], dict):
            raise ValueError
        resolved_id = values[0]["Id"]
        repo_digests = values[0].get("RepoDigests") or []
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise DockerExecutorUnavailable("Docker image inspection was not exact") from None
    if not isinstance(resolved_id, str) or not _FULL_IMAGE_ID.fullmatch(resolved_id):
        raise DockerExecutorUnavailable("Docker image ID is not a full sha256 identity")
    if resolved_id != _FIXED_IMAGE_ID:
        raise DockerExecutorUnavailable("fixed local Docker image ID binding drifted")
    if _FIXED_IMAGE_REFERENCE not in repo_digests:
        raise DockerExecutorUnavailable("Docker repo digest binding drifted")
    return _FIXED_IMAGE_REFERENCE, _FIXED_IMAGE_ID


def _expected_policy() -> DockerPolicyCeiling:
    identity, resolved_id = _resolve_fixed_image()
    args = (
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "32",
        "--memory", "64m",
        "--memory-swap", "64m",
        "--cpus", "0.5",
        "--ulimit", "fsize=1024:1024",
        "--ulimit", "nofile=64:64",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777",
        "--user", "65532:65532",
        "--log-driver", "none",
    )
    worker_digest = hashlib.sha256(_WORKER).hexdigest()
    policy_payload = {
        "allowed_image_identity": identity,
        "resolved_image_id": resolved_id,
        "docker_security_args": args,
        "environment": (),
        "worker_artifact_sha256": worker_digest,
        "timeout_seconds": 10,
    }
    return DockerPolicyCeiling(
        **policy_payload,
        policy_digest=content_digest(policy_payload),
    )


def trusted_docker_executor() -> DockerArmExecutor:
    """Mint the fixed local policy; callers cannot select image or authority."""

    policy = _expected_policy()
    return DockerArmExecutor(
        policy=policy,
        worker_bytes=_WORKER,
        local_receipt_key=secrets.token_bytes(32),
        _factory_token=_TRUSTED_FACTORY_TOKEN,
    )


class DockerArmExecutor:
    """Execute the fixed pure worker in a disposable no-network container."""

    def __init__(
        self,
        *,
        policy: DockerPolicyCeiling,
        worker_bytes: bytes,
        local_receipt_key: bytes,
        _factory_token: object,
    ) -> None:
        if _factory_token is not _TRUSTED_FACTORY_TOKEN:
            raise TypeError("DockerArmExecutor requires the trusted factory")
        self.policy = policy
        self.worker_bytes = worker_bytes
        self._local_receipt_key = local_receipt_key

    def execute(self, request: DockerExecutionRequest) -> DockerExecutionReceipt:
        request = DockerExecutionRequest.from_mapping(request.to_mapping())
        expected_policy = _expected_policy()
        if self.policy != expected_policy or self.worker_bytes != _WORKER:
            raise DockerExecutionFailed("trusted policy or worker artifact changed")
        if (
            type(self._local_receipt_key) is not bytes
            or len(self._local_receipt_key) != 32
        ):
            raise DockerExecutionFailed("local receipt key is unavailable")
        container_name = f"agent-os-srl-{uuid.uuid4().hex}"
        discovery_label = uuid.uuid4().hex
        container_id = self._create_container(
            container_name=container_name,
            discovery_label=discovery_label,
            expected_policy=expected_policy,
            worker=_WORKER,
        )
        run_error: Exception | None = None
        execution: tuple[bytes, bytes, int, str, str] | None = None
        try:
            pre_digest = self._inspect_policy(container_id, expected_status="created")
            stdout, stderr, exit_code, post_digest = self._start_capped(
                container_id,
                input_bytes=request.to_json(),
                timeout_seconds=expected_policy.timeout_seconds,
            )
            execution = (stdout, stderr, exit_code, pre_digest, post_digest)
        except Exception as exc:
            run_error = exc
        try:
            cleanup = self._cleanup_container(container_id)
        except Exception as cleanup_error:
            if run_error is not None:
                raise cleanup_error from run_error
            raise
        if run_error is not None:
            raise run_error
        if execution is None:
            raise DockerExecutionFailed("Docker execution produced no bounded result")
        stdout, stderr, exit_code, pre_digest, post_digest = execution
        if exit_code != 0:
            raise DockerExecutionFailed(
                f"Docker worker exited unsuccessfully ({exit_code}); "
                f"stderr_sha256={hashlib.sha256(stderr).hexdigest()}"
            )
        worker_payload = self._validate_worker_output(stdout, request)
        cleanup_digest = content_digest(cleanup)
        receipt_payload: dict[str, Any] = {
            **worker_payload,
            "candidate": request.candidate.model_dump(mode="json"),
            "image_identity": expected_policy.allowed_image_identity,
            "resolved_image_id": expected_policy.resolved_image_id,
            "policy_digest": expected_policy.policy_digest,
            "worker_artifact_sha256": expected_policy.worker_artifact_sha256,
            "container_id": container_id,
            "pre_start_inspect_digest": pre_digest,
            "post_start_inspect_digest": post_digest,
            "exit_code": exit_code,
            "stdout_digest": hashlib.sha256(stdout).hexdigest(),
            "stderr_digest": hashlib.sha256(stderr).hexdigest(),
            "network_mode": "none",
            "rootfs_read_only": True,
            "environment_empty": True,
            "no_external_effect": True,
            **cleanup,
            "cleanup_digest": cleanup_digest,
        }
        receipt_digest = content_digest(receipt_payload)
        mac_payload = {**receipt_payload, "receipt_digest": receipt_digest}
        local_mac = hmac.new(
            self._local_receipt_key,
            canonical_json(mac_payload).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        receipt_fields = dict(receipt_payload)
        receipt_fields["candidate"] = request.candidate
        return DockerExecutionReceipt(
            **receipt_fields,
            receipt_digest=receipt_digest,
            local_integrity_hmac=local_mac,
        )

    @staticmethod
    def _create_container(
        *,
        container_name: str,
        discovery_label: str,
        expected_policy: DockerPolicyCeiling,
        worker: bytes,
        arguments: tuple[str, ...] = (),
    ) -> str:
        if _LOCAL_TEMP_BASE.exists() and _LOCAL_TEMP_BASE.is_symlink():
            raise DockerExecutionFailed("fixed Docker temp base cannot be a symlink")
        _LOCAL_TEMP_BASE.mkdir(mode=0o700, parents=True, exist_ok=True)
        _LOCAL_TEMP_BASE.chmod(0o700)
        try:
            with tempfile.TemporaryDirectory(
                prefix="identity-", dir=_LOCAL_TEMP_BASE
            ) as directory:
                cidfile = Path(directory) / "container.cid"
                create = [
                    "docker",
                    "create",
                    "--name",
                    container_name,
                    "--label",
                    f"agent-os.srl-exec={discovery_label}",
                    "--cidfile",
                    str(cidfile),
                    "--pull=never",
                    *expected_policy.docker_security_args,
                    "--interactive",
                    "--entrypoint",
                    "/usr/bin/env",
                    expected_policy.resolved_image_id,
                    "-i",
                    "/usr/local/bin/python",
                    "-c",
                    worker.decode("utf-8"),
                    *arguments,
                ]
                created = _docker_run(create)
                if created.returncode != 0:
                    detail = created.stderr.strip().splitlines()[-1][:240]
                    raise DockerExecutionFailed(
                        f"Docker container creation failed closed: {detail}"
                    )
                if cidfile.is_symlink() or not cidfile.is_file():
                    raise DockerExecutionFailed("Docker cidfile is unavailable")
                if cidfile.stat().st_size > 65:
                    raise DockerExecutionFailed("Docker cidfile exceeds identity cap")
                container_id = cidfile.read_text(encoding="ascii").strip()
                if not _CONTAINER_ID.fullmatch(container_id):
                    raise DockerExecutionFailed("Docker cidfile identity is invalid")
                return container_id
        except Exception as exc:
            DockerArmExecutor._fallback_cleanup(container_name, discovery_label)
            raise exc

    @staticmethod
    def _fallback_cleanup(container_name: str, discovery_label: str) -> None:
        query = [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            f"name=^{container_name}$",
            "--filter",
            f"label=agent-os.srl-exec={discovery_label}",
        ]
        found = _docker_run(query)
        if found.returncode != 0:
            raise DockerExecutionFailed("Docker fallback discovery failed closed")
        identities = tuple(line for line in found.stdout.splitlines() if line)
        if any(not _CONTAINER_ID.fullmatch(identity) for identity in identities):
            raise DockerExecutionFailed("Docker fallback identity is invalid")
        for identity in identities:
            DockerArmExecutor._cleanup_container(identity)
        confirmed = _docker_run(query)
        if confirmed.returncode != 0 or confirmed.stdout.strip():
            raise DockerExecutionFailed("Docker fallback cleanup was not confirmed")

    def verify_local_receipt(self, receipt: DockerExecutionReceipt) -> None:
        """Verify process-local integrity only; this is not independent custody."""

        payload = receipt.to_mapping(exclude_digest=True)
        expected_cleanup_digest = content_digest(
            {
                "cleanup_remove_exit_code": receipt.cleanup_remove_exit_code,
                "cleanup_absent": receipt.cleanup_absent,
            }
        )
        if receipt.cleanup_digest != expected_cleanup_digest:
            raise DockerExecutionFailed("local Docker cleanup receipt integrity failed")
        expected_digest = content_digest(payload)
        mac_payload = {**payload, "receipt_digest": expected_digest}
        expected_mac = hmac.new(
            self._local_receipt_key,
            canonical_json(mac_payload).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if receipt.receipt_digest != expected_digest or not hmac.compare_digest(
            receipt.local_integrity_hmac, expected_mac
        ):
            raise DockerExecutionFailed("local Docker receipt integrity failed")

    def _inspect_policy(
        self,
        container_id: str,
        *,
        expected_status: str,
        expected_worker: bytes = _WORKER,
        expected_arguments: tuple[str, ...] = (),
    ) -> str:
        inspected = _docker_run(["docker", "container", "inspect", container_id])
        try:
            values = json.loads(inspected.stdout)
            value = values[0]
            host = value["HostConfig"]
            config = value["Config"]
            ulimits = {
                item["Name"]: (item["Soft"], item["Hard"])
                for item in host["Ulimits"]
            }
            exact = (
                inspected.returncode == 0,
                len(values) == 1,
                value["Id"] == container_id,
                value["Image"] == _FIXED_IMAGE_ID,
                value["Mounts"] == [],
                host["Binds"] is None,
                host["NetworkMode"] == "none",
                host["ReadonlyRootfs"] is True,
                host["CapDrop"] == ["ALL"],
                host["SecurityOpt"] == ["no-new-privileges"],
                host["PidsLimit"] == 32,
                host["Memory"] == 64 * 1024 * 1024,
                host["MemorySwap"] == 64 * 1024 * 1024,
                host["NanoCpus"] == 500_000_000,
                host["Tmpfs"]
                == {"/tmp": "rw,noexec,nosuid,nodev,size=8m,mode=1777"},
                ulimits == {"fsize": (1024, 1024), "nofile": (64, 64)},
                host["Privileged"] is False,
                host["Devices"] == [],
                host["DeviceRequests"] is None,
                host["PidMode"] == "",
                host["LogConfig"] == {"Type": "none", "Config": {}},
                config["User"] == "65532:65532",
                config["Entrypoint"] == ["/usr/bin/env"],
                config["Cmd"]
                == [
                    "-i",
                    "/usr/local/bin/python",
                    "-c",
                    expected_worker.decode("utf-8"),
                    *expected_arguments,
                ],
                value["State"]["Status"] == expected_status,
            )
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise DockerExecutionFailed("Docker policy inspection was not exact") from None
        if not all(exact):
            raise DockerExecutionFailed("Docker daemon did not preserve policy ceiling")
        return content_digest(value)

    def _start_capped(
        self,
        container_id: str,
        *,
        input_bytes: bytes,
        timeout_seconds: int,
        expected_worker: bytes = _WORKER,
        expected_arguments: tuple[str, ...] = (),
    ) -> tuple[bytes, bytes, int, str]:
        if len(input_bytes) > _MAX_JSON_BYTES:
            raise DockerExecutionFailed("Docker worker input exceeds 65536 bytes")
        input_file = tempfile.TemporaryFile(mode="w+b")
        input_file.write(input_bytes)
        input_file.seek(0)
        deadline = time.monotonic() + timeout_seconds
        try:
            process = subprocess.Popen(
                ["docker", "start", "--attach", "--interactive", container_id],
                stdin=input_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except (FileNotFoundError, OSError) as exc:
            raise DockerExecutorUnavailable("Docker CLI/daemon unavailable") from exc
        finally:
            input_file.close()
        assert process.stdout is not None
        assert process.stderr is not None
        post_digest: str | None = None
        while post_digest is None and time.monotonic() < deadline:
            try:
                post_digest = self._inspect_policy(
                    container_id,
                    expected_status="running",
                    expected_worker=expected_worker,
                    expected_arguments=expected_arguments,
                )
            except DockerExecutionFailed:
                if process.poll() is not None:
                    raise DockerExecutionFailed(
                        "container exited before post-start policy inspection"
                    ) from None
                time.sleep(0.005)
        if post_digest is None:
            self._kill_required(container_id)
            self._terminate_start_client(process)
            raise DockerExecutionFailed("post-start policy inspection timed out")

        streams = {process.stdout.fileno(): bytearray(), process.stderr.fileno(): bytearray()}
        open_fds = set(streams)
        for fd in open_fds:
            os.set_blocking(fd, False)
        while open_fds:
            if time.monotonic() >= deadline:
                self._kill_required(container_id)
                self._terminate_start_client(process)
                raise DockerExecutionFailed("Docker worker timed out and was killed")
            ready, _, _ = select.select(tuple(open_fds), (), (), 0.02)
            for fd in ready:
                chunk = os.read(fd, 8192)
                if not chunk:
                    open_fds.remove(fd)
                    continue
                streams[fd].extend(chunk)
                if sum(len(value) for value in streams.values()) > _MAX_JSON_BYTES:
                    self._kill_required(container_id)
                    self._terminate_start_client(process)
                    raise DockerExecutionFailed(
                        "Docker worker output exceeds 65536 bytes and was killed"
                    )
            if process.poll() is not None and not ready:
                for fd in tuple(open_fds):
                    chunk = os.read(fd, 8192)
                    if chunk:
                        streams[fd].extend(chunk)
                    else:
                        open_fds.remove(fd)
        exit_code = process.wait(timeout=2)
        return (
            bytes(streams[process.stdout.fileno()]),
            bytes(streams[process.stderr.fileno()]),
            exit_code,
            post_digest,
        )

    @staticmethod
    def _terminate_start_client(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired as exc:
            raise DockerExecutionFailed("Docker start client did not terminate") from exc

    @staticmethod
    def _kill_required(container_id: str) -> None:
        killed = _docker_run(["docker", "kill", container_id])
        if killed.returncode == 0:
            return
        inspected = _docker_run(["docker", "container", "inspect", container_id])
        try:
            value = json.loads(inspected.stdout)[0]
            stopped = (
                inspected.returncode == 0
                and value["Id"] == container_id
                and value["State"]["Running"] is False
            )
        except (IndexError, KeyError, TypeError, json.JSONDecodeError):
            stopped = False
        if not stopped:
            raise DockerExecutionFailed("Docker kill failed closed")

    @staticmethod
    def _cleanup_container(container_id: str) -> dict[str, object]:
        removed = _docker_run(["docker", "container", "rm", "--force", container_id])
        absent = _docker_run(["docker", "container", "inspect", container_id])
        payload: dict[str, object] = {
            "cleanup_remove_exit_code": removed.returncode,
            "cleanup_absent": absent.returncode != 0,
        }
        if removed.returncode != 0 or absent.returncode == 0:
            raise DockerExecutionFailed("Docker cleanup failed closed")
        return payload

    @staticmethod
    def _validate_worker_output(
        raw: bytes, request: DockerExecutionRequest
    ) -> dict[str, object]:
        if len(raw) > _MAX_JSON_BYTES:
            raise DockerExecutionFailed("Docker worker output exceeds 65536 bytes")
        try:
            payload = json.loads(raw, parse_constant=_reject_nonfinite)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise DockerExecutionFailed("Docker worker output must be finite JSON") from None
        keys = {
            "schema_version", "request_id", "request_digest",
            "public_state_digest", "candidate",
        }
        if not isinstance(payload, dict) or set(payload) != keys:
            raise DockerExecutionFailed("Docker worker output must use the exact schema")
        expected = {
            "schema_version": "1.0",
            "request_id": request.request_id,
            "request_digest": request.request_digest,
            "public_state_digest": request.public_state_digest,
            "candidate": request.candidate.model_dump(mode="json"),
        }
        if payload != expected:
            raise DockerExecutionFailed("Docker worker output conflicts with exact input")
        return {
            "schema_version": "1.0",
            "request_id": request.request_id,
            "request_digest": request.request_digest,
            "public_state_digest": request.public_state_digest,
        }


__all__ = [
    "DockerArmExecutor",
    "DockerExecutionFailed",
    "DockerExecutionReceipt",
    "DockerExecutionRequest",
    "DockerExecutorUnavailable",
    "DockerPolicyCeiling",
    "trusted_docker_executor",
]


_FIXED_PROBES: Mapping[str, str] = MappingProxyType(
    {
        "host": """import os
path='/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/pyproject.toml'
print(int(os.path.exists(path)))
try:
 open(path, 'ab').write(b'x')
 print('write-open')
except OSError:
 print('write-denied')
print(int(bool(open('/proc/self/environ','rb').read())))
""",
        "pids": """import os,time
n=0
for _ in range(100):
 try: pid=os.fork()
 except OSError: break
 if pid == 0:
  time.sleep(.2); os._exit(0)
 n += 1
print(n)
""",
        "memory": "bytearray(96 * 1024 * 1024); print('unexpected')",
        "tmpfs": """try:
 open('/tmp/cap', 'wb').write(b'x' * (12 * 1024 * 1024))
 print('unexpected')
except OSError:
 print('capped')
""",
        "network": """import socket,sys
s=socket.socket(); s.settimeout(.3)
try: s.connect((sys.argv[1], int(sys.argv[2]))); print('connected')
except OSError: print('blocked')
""",
        "output": """import os
chunk=b'x'*8192
for _ in range(128): os.write(1, chunk)
""",
        "stdin_timeout": "import time; time.sleep(20)",
    }
)


def _run_fixed_policy_probe(
    executor: DockerArmExecutor,
    probe: str,
    *,
    arguments: tuple[str, ...] = (),
) -> tuple[subprocess.CompletedProcess[bytes], str]:
    """Test-only fixed allowlist; never accepts caller code or extra Docker args."""

    source = _FIXED_PROBES.get(probe)
    if source is None:
        raise ValueError("unknown fixed Docker policy probe")
    if probe == "network":
        if len(arguments) != 2 or not arguments[1].isdigit():
            raise ValueError("network probe requires a fixed host and numeric port")
    elif arguments:
        raise ValueError("fixed Docker policy probe forbids arguments")
    container_id = executor._create_container(
        container_name=f"agent-os-srl-probe-{uuid.uuid4().hex}",
        discovery_label=uuid.uuid4().hex,
        expected_policy=executor.policy,
        worker=source.encode("utf-8"),
        arguments=arguments,
    )
    try:
        executor._inspect_policy(
            container_id,
            expected_status="created",
            expected_worker=source.encode("utf-8"),
            expected_arguments=arguments,
        )
        if probe == "output":
            executor._start_capped(
                container_id,
                input_bytes=b"",
                timeout_seconds=10,
                expected_worker=source.encode("utf-8"),
                expected_arguments=arguments,
            )
            raise DockerExecutionFailed("output flood unexpectedly passed hard cap")
        if probe == "stdin_timeout":
            executor._start_capped(
                container_id,
                input_bytes=b"x" * _MAX_JSON_BYTES,
                timeout_seconds=1,
                expected_worker=source.encode("utf-8"),
                expected_arguments=arguments,
            )
            raise DockerExecutionFailed("stdin timeout probe unexpectedly completed")
        completed = subprocess.run(
            ["docker", "start", "--attach", container_id],
            check=False,
            capture_output=True,
            timeout=10,
        )
        return completed, container_id
    finally:
        executor._cleanup_container(container_id)
