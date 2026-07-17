from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .canonical import canonical_json, content_digest
from .catalogue import VisibleProbeCandidate
from .contracts import ProbeObservation, ProbeRequest, PublicEnvironmentDescriptor
from .scoring_contracts import (
    ChallengeCatalogue,
    ChallengePrediction,
    DiscoveryScoreBundle,
    ScoringContractError,
    StatefulTestIR,
)
from .selector import (
    PROBABILITY_SCALE,
    CandidateProbe,
    HypothesisPrediction,
    HypothesisWeight,
    OutcomeLikelihood,
    SelectorValidationError,
    select_probe,
)


ACTOR_REQUEST_SCHEMA = "active-discovery-actor-request/v1"
_ALLOWED_PROJECTION = {
    "schema_version": ACTOR_REQUEST_SCHEMA,
    "top_level_fields": [
        "schema_version",
        "public_descriptor",
        "legal_probe_payloads",
        "prefix_observations",
        "transcript_prefix_digest",
    ],
    "transport": "canonical-json-utf8-stdin-stdout",
}
ALLOWED_PROJECTION_DIGEST = content_digest(
    "active-actor-allowed-projection/v1", _ALLOWED_PROJECTION
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTOR_ORACLE_FIELD_TOKENS = frozenset(
    {"config", "family", "groundtruth", "hidden", "oracle", "referee", "score", "secret", "strength"}
)
_OBSERVATION_ORACLE_TOKENS = frozenset(
    {*_ACTOR_ORACLE_FIELD_TOKENS, "prediction", "truth"}
)
_FILESYSTEM_POLICY = "EXTERNALLY_ATTESTED_NO_HOST_READ_WRITE"
_NETWORK_POLICY = "EXTERNALLY_ATTESTED_NONE"
_ENVIRONMENT_POLICY = "EMPTY"
_MAX_REQUEST_BYTES = 1_000_000
_MAX_RESPONSE_BYTES = 1_000_000
_FIXED_IMAGE_REFERENCE = (
    "python@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf"
)
_FIXED_IMAGE_ID = (
    "sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf"
)
_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_FACTORY_TOKEN = object()


class ActorLoopError(ValueError):
    """The actor escaped its serialized public behavior contract."""


def _closed(raw: Mapping[str, Any], fields: frozenset[str], label: str) -> None:
    unknown = set(raw) - fields
    missing = fields - set(raw)
    if unknown:
        raise ActorLoopError(f"{label} has unknown fields: {sorted(unknown)}")
    if missing:
        raise ActorLoopError(f"{label} is missing fields: {sorted(missing)}")


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ActorLoopError(f"{field} must be a non-empty NUL-free string")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ActorLoopError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _bytes_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_digest(path: str) -> str:
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file():
        raise ActorLoopError("actor executable must resolve to a regular file")
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"[^a-z0-9]", "", normalized)


def _contains_forbidden(value: str, tokens: frozenset[str]) -> bool:
    normalized = _normalized_token(value)
    return any(token in normalized for token in tokens)


def _reject_actor_oracle_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ActorLoopError("actor response requires string field names")
            if _contains_forbidden(key, _ACTOR_ORACLE_FIELD_TOKENS):
                raise ActorLoopError(f"oracle-shaped actor field is forbidden: {key}")
            _reject_actor_oracle_fields(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_actor_oracle_fields(nested)


def _reject_observation_content(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str) or _contains_forbidden(
                key, _OBSERVATION_ORACLE_TOKENS
            ):
                raise ActorLoopError("oracle-shaped observation content is forbidden")
            _reject_observation_content(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_observation_content(nested)
    elif isinstance(value, str) and _contains_forbidden(
        value, _OBSERVATION_ORACLE_TOKENS
    ):
        raise ActorLoopError("oracle-shaped observation content is forbidden")


def _public_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in normalized:
        raise ActorLoopError("public observation text must be NUL-free")
    _reject_observation_content(normalized)
    return normalized


@dataclass(frozen=True, slots=True)
class DockerActorPolicy:
    image_identity: str
    resolved_image_id: str
    docker_security_args: tuple[str, ...]
    timeout_seconds: int
    policy_digest: str


@dataclass(frozen=True, slots=True)
class ActorInvocationReceipt:
    container_id: str
    image_identity: str
    resolved_image_id: str
    policy_digest: str
    actor_artifact_digest: str
    allowed_projection_digest: str
    request_digest: str
    response_digest: str
    pre_start_inspect_digest: str
    post_start_inspect_digest: str
    exit_code: int
    network_mode: str
    rootfs_read_only: bool
    cap_drop_all: bool
    no_new_privileges: bool
    cleanup_remove_exit_code: int
    cleanup_absent: bool


@dataclass(frozen=True, slots=True)
class IsolatedActorResponse:
    canonical_response_bytes: bytes
    receipt: ActorInvocationReceipt


def _docker_run(args: list[str], *, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=timeout
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise ActorLoopError("Docker executor is unavailable") from exc
    if len(result.stdout) > _MAX_RESPONSE_BYTES or len(result.stderr) > _MAX_RESPONSE_BYTES:
        raise ActorLoopError("Docker control output exceeded the bounded contract")
    return result


def _resolve_fixed_image() -> tuple[str, str]:
    inspected = _docker_run(["docker", "image", "inspect", _FIXED_IMAGE_REFERENCE])
    if inspected.returncode != 0:
        raise ActorLoopError("fixed Docker image is unavailable")
    try:
        values = json.loads(inspected.stdout)
        resolved = values[0]["Id"]
        repo_digests = values[0]["RepoDigests"]
    except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
        raise ActorLoopError("fixed Docker image inspection is invalid") from exc
    if (
        len(values) != 1
        or resolved != _FIXED_IMAGE_ID
        or _FIXED_IMAGE_REFERENCE not in repo_digests
    ):
        raise ActorLoopError("fixed Docker image identity drifted")
    return _FIXED_IMAGE_REFERENCE, _FIXED_IMAGE_ID


def trusted_docker_actor_port(*, actor_artifact_bytes: bytes) -> DockerActorPort:
    if not isinstance(actor_artifact_bytes, bytes) or not actor_artifact_bytes:
        raise ActorLoopError("actor artifact must be non-empty bytes")
    try:
        actor_artifact_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ActorLoopError("actor artifact must be UTF-8 source bytes") from exc
    identity, resolved = _resolve_fixed_image()
    security_args = (
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "32",
        "--memory", "64m",
        "--memory-swap", "64m",
        "--cpus", "0.5",
        "--ulimit", "fsize=1048576:1048576",
        "--ulimit", "nofile=64:64",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777",
        "--user", "65532:65532",
        "--log-driver", "none",
    )
    payload = {
        "image_identity": identity,
        "resolved_image_id": resolved,
        "docker_security_args": list(security_args),
        "timeout_seconds": 5,
        "allowed_projection_digest": ALLOWED_PROJECTION_DIGEST,
    }
    policy = DockerActorPolicy(
        identity, resolved, security_args, 5, content_digest("docker-actor-policy/v1", payload)
    )
    return DockerActorPort(policy, actor_artifact_bytes, _FACTORY_TOKEN)


class DockerActorPort:
    def __init__(
        self,
        policy: DockerActorPolicy,
        actor_artifact_bytes: bytes,
        factory_token: object,
    ) -> None:
        if factory_token is not _FACTORY_TOKEN:
            raise TypeError("DockerActorPort requires trusted factory")
        self.policy = policy
        self.actor_artifact_bytes = actor_artifact_bytes

    @property
    def docker_security_args(self) -> tuple[str, ...]:
        return self.policy.docker_security_args

    @property
    def resolved_image_id(self) -> str:
        return self.policy.resolved_image_id

    @property
    def actor_artifact_digest(self) -> str:
        return _bytes_digest(self.actor_artifact_bytes)

    @property
    def allowed_projection_digest(self) -> str:
        return ALLOWED_PROJECTION_DIGEST

    @property
    def actor_binding_digest(self) -> str:
        return content_digest(
            "docker-active-actor-binding/v1",
            {
                "policy_digest": self.policy.policy_digest,
                "actor_artifact_digest": self.actor_artifact_digest,
                "allowed_projection_digest": self.allowed_projection_digest,
            },
        )

    def _inspect(self, container_id: str, *, expected_status: str) -> str:
        result = _docker_run(["docker", "container", "inspect", container_id])
        if result.returncode != 0:
            raise ActorLoopError("Docker container inspection failed")
        try:
            values = json.loads(result.stdout)
            value = values[0]
            host = value["HostConfig"]
            status = value["State"]["Status"]
        except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
            raise ActorLoopError("Docker container inspection is invalid") from exc
        if (
            len(values) != 1
            or value["Id"] != container_id
            or value["Image"] != self.policy.resolved_image_id
            or status != expected_status
            or host["NetworkMode"] != "none"
            or host["ReadonlyRootfs"] is not True
            or host.get("CapDrop") != ["ALL"]
            or "no-new-privileges" not in (host.get("SecurityOpt") or [])
            or host["PidsLimit"] != 32
            or host["Memory"] != 64 * 1024 * 1024
            or host["MemorySwap"] != 64 * 1024 * 1024
            or host["NanoCpus"] != 500_000_000
            or value.get("Mounts") != []
            or host.get("Binds") not in (None, [])
        ):
            raise ActorLoopError("Docker runtime policy inspection failed")
        return content_digest("docker-actor-inspect/v1", value)

    def _start_bounded(
        self, container_id: str, request_bytes: bytes
    ) -> tuple[bytes, bytes, int]:
        with tempfile.TemporaryFile() as input_file:
            input_file.write(request_bytes)
            input_file.seek(0)
            process = subprocess.Popen(
                ["docker", "start", "--attach", "--interactive", container_id],
                stdin=input_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            assert process.stdout is not None and process.stderr is not None
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            chunks: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
            deadline = time.monotonic() + self.policy.timeout_seconds
            try:
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    for key, _ in selector.select(min(remaining, 0.1)):
                        data = os.read(key.fd, 65_536)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        target = chunks[key.data]
                        target.extend(data)
                        if len(target) > _MAX_RESPONSE_BYTES:
                            raise ActorLoopError("actor output exceeded the bounded contract")
                return_code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except (TimeoutError, subprocess.TimeoutExpired) as exc:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                _docker_run(["docker", "container", "kill", container_id])
                raise ActorLoopError("Docker actor exceeded wall-time") from exc
            except Exception:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    _docker_run(["docker", "container", "kill", container_id])
                raise
        return bytes(chunks["stdout"]), bytes(chunks["stderr"]), return_code

    def _cleanup(self, container_id: str) -> tuple[int, bool]:
        removed = _docker_run(
            ["docker", "container", "rm", "--force", container_id]
        )
        absent = _docker_run(["docker", "container", "inspect", container_id]).returncode != 0
        if removed.returncode != 0 or not absent:
            raise ActorLoopError("Docker actor cleanup failed closed")
        return removed.returncode, absent

    def invoke(self, request_bytes: bytes) -> IsolatedActorResponse:
        expected = trusted_docker_actor_port(actor_artifact_bytes=self.actor_artifact_bytes)
        if self.policy != expected.policy:
            raise ActorLoopError("Docker actor policy changed")
        if not isinstance(request_bytes, bytes) or not 1 <= len(request_bytes) <= _MAX_REQUEST_BYTES:
            raise ActorLoopError("actor request must be bounded canonical bytes")
        try:
            request = json.loads(request_bytes)
        except json.JSONDecodeError as exc:
            raise ActorLoopError("actor request bytes are invalid JSON") from exc
        if canonical_json(request).encode() != request_bytes:
            raise ActorLoopError("actor request must use canonical JSON bytes")
        name = f"active-actor-{uuid.uuid4().hex}"
        label = uuid.uuid4().hex
        container_id = ""
        run_error: Exception | None = None
        execution: tuple[bytes, bytes, int, str, str] | None = None
        with tempfile.TemporaryDirectory(prefix="active-actor-cid-") as directory:
            cidfile = Path(directory) / "container.cid"
            create = _docker_run(
                [
                    "docker", "create", "--interactive", "--pull", "never", "--cidfile", str(cidfile),
                    "--name", name, "--label", f"active-actor-token={label}",
                    *self.policy.docker_security_args,
                    "--entrypoint", "python", self.policy.image_identity,
                    "-I", "-c", self.actor_artifact_bytes.decode("utf-8"),
                ]
            )
            if create.returncode != 0:
                raise ActorLoopError("Docker actor container creation failed")
            try:
                container_id = cidfile.read_text(encoding="ascii").strip()
            except OSError as exc:
                raise ActorLoopError("Docker actor cidfile is unavailable") from exc
            if _CONTAINER_ID_RE.fullmatch(container_id) is None:
                _docker_run(["docker", "container", "rm", "--force", name])
                raise ActorLoopError("Docker actor cidfile identity is invalid")
            try:
                pre = self._inspect(container_id, expected_status="created")
                stdout, stderr, exit_code = self._start_bounded(container_id, request_bytes)
                post = self._inspect(container_id, expected_status="exited")
                execution = (stdout, stderr, exit_code, pre, post)
            except Exception as exc:
                run_error = exc
            cleanup_code, cleanup_absent = self._cleanup(container_id)
        if run_error is not None:
            raise run_error
        if execution is None:
            raise ActorLoopError("Docker actor produced no execution")
        stdout, stderr, exit_code, pre, post = execution
        if exit_code != 0 or stderr:
            raise ActorLoopError(
                "Docker actor invocation failed closed: "
                f"exit={exit_code},stderr_sha256={_bytes_digest(stderr)}"
            )
        try:
            response = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ActorLoopError("actor response is invalid JSON") from exc
        if canonical_json(response).encode() != stdout:
            raise ActorLoopError("actor response must use canonical JSON bytes")
        receipt = ActorInvocationReceipt(
            container_id=container_id,
            image_identity=self.policy.image_identity,
            resolved_image_id=self.policy.resolved_image_id,
            policy_digest=self.policy.policy_digest,
            actor_artifact_digest=self.actor_artifact_digest,
            allowed_projection_digest=self.allowed_projection_digest,
            request_digest=_bytes_digest(request_bytes),
            response_digest=_bytes_digest(stdout),
            pre_start_inspect_digest=pre,
            post_start_inspect_digest=post,
            exit_code=exit_code,
            network_mode="none",
            rootfs_read_only=True,
            cap_drop_all=True,
            no_new_privileges=True,
            cleanup_remove_exit_code=cleanup_code,
            cleanup_absent=cleanup_absent,
        )
        return IsolatedActorResponse(stdout, receipt)


@dataclass(frozen=True, slots=True)
class PublicProbePayload:
    probe_id: str
    stable_order: int
    operation_id: str
    payload_json: str
    cost_units: int

    def __post_init__(self) -> None:
        _name(self.probe_id, "probe_id")
        _name(self.operation_id, "operation_id")
        if (
            isinstance(self.stable_order, bool)
            or not isinstance(self.stable_order, int)
            or self.stable_order < 0
        ):
            raise ActorLoopError("stable_order must be an integer >= 0")
        if self.cost_units != 1 or isinstance(self.cost_units, bool):
            raise ActorLoopError("active actor supports exact unit-cost probes")
        try:
            payload = json.loads(self.payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ActorLoopError("payload_json must be canonical JSON object text") from exc
        if not isinstance(payload, dict) or canonical_json(payload) != self.payload_json:
            raise ActorLoopError("payload_json must be canonical JSON object text")

    def to_mapping(self) -> dict[str, object]:
        return {
            "probe_id": self.probe_id,
            "stable_order": self.stable_order,
            "operation_id": self.operation_id,
            "payload_json": self.payload_json,
            "cost_units": self.cost_units,
        }


@dataclass(frozen=True, slots=True)
class BehaviorHypothesis:
    hypothesis_id: str
    description: str
    probability_micros: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> BehaviorHypothesis:
        _closed(
            raw,
            frozenset({"hypothesis_id", "description", "probability_micros"}),
            "behavior hypothesis",
        )
        value = cls(raw["hypothesis_id"], raw["description"], raw["probability_micros"])
        _name(value.hypothesis_id, "hypothesis_id")
        _name(value.description, "description")
        if (
            isinstance(value.probability_micros, bool)
            or not isinstance(value.probability_micros, int)
            or not 1 <= value.probability_micros <= PROBABILITY_SCALE
        ):
            raise ActorLoopError("hypothesis probability is invalid")
        return value

    def to_mapping(self) -> dict[str, object]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "description": self.description,
            "probability_micros": self.probability_micros,
        }


@dataclass(frozen=True, slots=True)
class ProbeHypothesisLikelihood:
    probe_id: str
    hypothesis_id: str
    outcomes: tuple[OutcomeLikelihood, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProbeHypothesisLikelihood:
        _closed(
            raw,
            frozenset({"probe_id", "hypothesis_id", "outcomes"}),
            "probe hypothesis likelihood",
        )
        outcomes = raw["outcomes"]
        if not isinstance(outcomes, list):
            raise ActorLoopError("probe likelihood outcomes must be a list")
        parsed: list[OutcomeLikelihood] = []
        try:
            for item in outcomes:
                if not isinstance(item, Mapping):
                    raise ActorLoopError("probe outcome likelihood is invalid")
                _closed(
                    item,
                    frozenset({"outcome_label", "probability_micros"}),
                    "outcome likelihood",
                )
                parsed.append(
                    OutcomeLikelihood(item["outcome_label"], item["probability_micros"])
                )
        except SelectorValidationError as exc:
            raise ActorLoopError("probe outcome likelihood is invalid") from exc
        value = cls(raw["probe_id"], raw["hypothesis_id"], tuple(parsed))
        _name(value.probe_id, "probe_id")
        _name(value.hypothesis_id, "hypothesis_id")
        labels = tuple(item.outcome_label for item in value.outcomes)
        if (
            not value.outcomes
            or len(labels) != len(set(labels))
            or sum(item.probability_micros for item in value.outcomes)
            != PROBABILITY_SCALE
        ):
            raise ActorLoopError("probe likelihood partition is invalid")
        return value

    def to_mapping(self) -> dict[str, object]:
        return {
            "probe_id": self.probe_id,
            "hypothesis_id": self.hypothesis_id,
            "outcomes": [
                {
                    "outcome_label": item.outcome_label,
                    "probability_micros": item.probability_micros,
                }
                for item in self.outcomes
            ],
        }


@dataclass(frozen=True, slots=True)
class EvidenceBinding:
    transcript_prefix_digest: str
    update_disposition: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> EvidenceBinding:
        _closed(
            raw,
            frozenset({"transcript_prefix_digest", "update_disposition"}),
            "evidence binding",
        )
        value = cls(raw["transcript_prefix_digest"], raw["update_disposition"])
        _digest(value.transcript_prefix_digest, "transcript_prefix_digest")
        if value.update_disposition not in {
            "MATERIAL_UPDATE",
            "ABSTAIN_INSUFFICIENT_EVIDENCE",
        }:
            raise ActorLoopError("evidence update disposition is invalid")
        return value

    def to_mapping(self) -> dict[str, str]:
        return {
            "transcript_prefix_digest": self.transcript_prefix_digest,
            "update_disposition": self.update_disposition,
        }


@dataclass(frozen=True, slots=True)
class ActorModelOutput:
    hypotheses: tuple[BehaviorHypothesis, ...]
    probe_likelihoods: tuple[ProbeHypothesisLikelihood, ...]
    selected_probe_id: str
    predictions: tuple[ChallengePrediction, ...]
    test_ir: StatefulTestIR
    evidence_binding: EvidenceBinding

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ActorModelOutput:
        _reject_actor_oracle_fields(raw)
        _closed(
            raw,
            frozenset(
                {
                    "hypotheses",
                    "probe_likelihoods",
                    "selected_probe_id",
                    "predictions",
                    "test_ir",
                    "evidence_binding",
                }
            ),
            "actor model output",
        )
        for field in ("hypotheses", "probe_likelihoods", "predictions"):
            if not isinstance(raw[field], list):
                raise ActorLoopError(f"{field} must be a list")
        if not isinstance(raw["test_ir"], Mapping) or not isinstance(
            raw["evidence_binding"], Mapping
        ):
            raise ActorLoopError("actor nested output is invalid")
        try:
            value = cls(
                hypotheses=tuple(
                    BehaviorHypothesis.from_mapping(item) for item in raw["hypotheses"]
                ),
                probe_likelihoods=tuple(
                    ProbeHypothesisLikelihood.from_mapping(item)
                    for item in raw["probe_likelihoods"]
                ),
                selected_probe_id=raw["selected_probe_id"],
                predictions=tuple(
                    ChallengePrediction.from_mapping(item) for item in raw["predictions"]
                ),
                test_ir=StatefulTestIR.from_mapping(raw["test_ir"]),
                evidence_binding=EvidenceBinding.from_mapping(raw["evidence_binding"]),
            )
        except (ScoringContractError, TypeError) as exc:
            raise ActorLoopError("actor output failed the typed contract") from exc
        _name(value.selected_probe_id, "selected_probe_id")
        ids = tuple(item.hypothesis_id for item in value.hypotheses)
        if (
            len(ids) < 2
            or len(ids) != len(set(ids))
            or sum(item.probability_micros for item in value.hypotheses)
            != PROBABILITY_SCALE
        ):
            raise ActorLoopError("actor requires a normalized competing hypothesis set")
        if not value.probe_likelihoods or not value.predictions:
            raise ActorLoopError("actor output requires likelihoods and predictions")
        return value

    def to_mapping(self) -> dict[str, object]:
        return {
            "hypotheses": [item.to_mapping() for item in self.hypotheses],
            "probe_likelihoods": [item.to_mapping() for item in self.probe_likelihoods],
            "selected_probe_id": self.selected_probe_id,
            "predictions": [item.to_mapping() for item in self.predictions],
            "test_ir": self.test_ir.to_mapping(),
            "evidence_binding": self.evidence_binding.to_mapping(),
        }

    @property
    def evidence_state_digest(self) -> str:
        return content_digest(
            "active-actor-evidence-state/v1",
            {
                "hypotheses": [item.to_mapping() for item in self.hypotheses],
                "predictions": [item.to_mapping() for item in self.predictions],
                "test_ir": self.test_ir.to_mapping(),
            },
        )

    @property
    def posterior_digest(self) -> str:
        return content_digest(
            "active-actor-posterior/v1",
            [item.to_mapping() for item in self.hypotheses],
        )


@dataclass(frozen=True, slots=True)
class ActorLoopReceipt:
    prefix_bundles: tuple[DiscoveryScoreBundle, ...]
    selected_probe_ids: tuple[str, ...]
    observations: tuple[ProbeObservation, ...]
    decision_digests: tuple[str, ...]
    actor_invocation_receipts: tuple[ActorInvocationReceipt, ...]


@dataclass(frozen=True, slots=True)
class HiddenConfigurationPolicyTrace:
    configuration_digest: str
    voi_probe_ids: tuple[str, ...]
    systematic_probe_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.configuration_digest, "configuration_digest")
        if not self.voi_probe_ids or len(self.voi_probe_ids) != len(
            self.systematic_probe_ids
        ):
            raise ActorLoopError("policy traces must have a non-empty matched budget")


@dataclass(frozen=True, slots=True)
class ExhaustiveConfigurationDomainManifest:
    domain_definition_digest: str
    configuration_digests: tuple[str, ...]
    declared_cardinality: int
    enumeration_certificate_digest: str

    @classmethod
    def create(
        cls,
        *,
        domain_definition_digest: str,
        configuration_digests: tuple[str, ...],
        declared_cardinality: int,
        enumeration_certificate_digest: str,
    ) -> ExhaustiveConfigurationDomainManifest:
        _digest(domain_definition_digest, "domain_definition_digest")
        _digest(enumeration_certificate_digest, "enumeration_certificate_digest")
        for item in configuration_digests:
            _digest(item, "configuration_digest")
        if len(configuration_digests) < 2:
            raise ActorLoopError("exhaustive domain requires at least two configurations")
        if (
            isinstance(declared_cardinality, bool)
            or declared_cardinality != len(configuration_digests)
            or len(configuration_digests) != len(set(configuration_digests))
        ):
            raise ActorLoopError("declared cardinality must bind every unique configuration")
        return cls(
            domain_definition_digest,
            tuple(sorted(configuration_digests)),
            declared_cardinality,
            enumeration_certificate_digest,
        )

    @property
    def manifest_digest(self) -> str:
        return content_digest(
            "active-actor-exhaustive-domain/v1",
            {
                "domain_definition_digest": self.domain_definition_digest,
                "configuration_digests": list(self.configuration_digests),
                "declared_cardinality": self.declared_cardinality,
                "enumeration_certificate_digest": self.enumeration_certificate_digest,
            },
        )


@dataclass(frozen=True, slots=True)
class StaticReductionAudit:
    disposition: str
    domain_manifest_digest: str
    all_configurations_equal: bool
    counterexample_configuration_digests: tuple[str, ...]


def audit_static_voi_reduction(
    *,
    manifest: ExhaustiveConfigurationDomainManifest,
    policy_traces: tuple[HiddenConfigurationPolicyTrace, ...],
) -> StaticReductionAudit:
    by_digest = {item.configuration_digest: item for item in policy_traces}
    if (
        len(by_digest) != len(policy_traces)
        or set(by_digest) != set(manifest.configuration_digests)
        or len(policy_traces) != manifest.declared_cardinality
    ):
        raise ActorLoopError("policy traces must cover the exact exhaustive domain")
    counterexamples = tuple(
        digest
        for digest in manifest.configuration_digests
        if by_digest[digest].voi_probe_ids != by_digest[digest].systematic_probe_ids
    )
    return StaticReductionAudit(
        disposition=(
            "NEEDS_INDEPENDENT_DOMAIN_CERTIFICATE"
            if not counterexamples
            else "ACTIVE_ADAPTATION_NOT_STATICALLY_REDUCED"
        ),
        domain_manifest_digest=manifest.manifest_digest,
        all_configurations_equal=not counterexamples,
        counterexample_configuration_digests=counterexamples,
    )


def _descriptor_mapping(descriptor: PublicEnvironmentDescriptor) -> dict[str, object]:
    return {
        "schema_version": "active-discovery-public-descriptor/v1",
        "descriptor_digest": descriptor.descriptor_digest,
        "operation_id": descriptor.operation_id,
        "schema_json": descriptor.schema_json,
        "documentation_fragments": list(descriptor.documentation_fragments),
        "initial_state_digest": descriptor.initial_state_digest,
    }


def _public_observation_mapping(observation: ProbeObservation) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "step_index": observation.step_index,
        "probe_id": observation.probe_id,
        "outcome_label": (
            "STATUS_ZERO" if observation.status_code == 0 else "STATUS_NONZERO"
        ),
        "state_relation": (
            "SAME"
            if observation.before_state_digest == observation.after_state_digest
            else "CHANGED"
        ),
        "before_state_digest": observation.before_state_digest,
        "after_state_digest": observation.after_state_digest,
    }
    payload["public_observation_digest"] = content_digest(
        "active-actor-public-observation/v1", payload
    )
    return payload


def _validate_decision(
    output: ActorModelOutput,
    legal_probes: tuple[PublicProbePayload, ...],
) -> None:
    legal_ids = {item.probe_id for item in legal_probes}
    by_pair = {
        (item.probe_id, item.hypothesis_id): item for item in output.probe_likelihoods
    }
    expected_pairs = {
        (probe.probe_id, hypothesis.hypothesis_id)
        for probe in legal_probes
        for hypothesis in output.hypotheses
    }
    if len(by_pair) != len(output.probe_likelihoods) or set(by_pair) != expected_pairs:
        raise ActorLoopError("likelihoods must cover every legal probe/hypothesis pair")
    if output.selected_probe_id not in legal_ids:
        raise ActorLoopError("actor selected an illegal probe")
    candidates: list[CandidateProbe] = []
    for probe in legal_probes:
        predictions = tuple(
            HypothesisPrediction(
                hypothesis.hypothesis_id,
                by_pair[(probe.probe_id, hypothesis.hypothesis_id)].outcomes,
            )
            for hypothesis in output.hypotheses
        )
        label_sets = {
            frozenset(item.outcome_label for item in prediction.outcomes)
            for prediction in predictions
        }
        if len(label_sets) != 1:
            raise ActorLoopError("hypotheses require one outcome partition per probe")
        candidates.append(
            CandidateProbe(
                probe.probe_id, probe.stable_order, probe.cost_units, predictions
            )
        )
    weights = tuple(
        HypothesisWeight(item.hypothesis_id, item.probability_micros)
        for item in output.hypotheses
    )
    try:
        expected = select_probe(weights, tuple(candidates)).probe_id
    except SelectorValidationError as exc:
        raise ActorLoopError("actor-generated VOI domain is invalid") from exc
    if output.selected_probe_id != expected:
        raise ActorLoopError("actor choice does not match its generated VOI choice")


def _validated_observation(
    observation: ProbeObservation, request: ProbeRequest
) -> ProbeObservation:
    if not isinstance(observation, ProbeObservation):
        raise ActorLoopError("probe executor must return ProbeObservation")
    if (
        observation.episode_id != request.episode_id
        or observation.step_index != request.step_index
        or observation.probe_id != request.probe_id
        or observation.before_state_digest != request.expected_state_digest
    ):
        raise ActorLoopError("probe observation does not bind the exact request")
    try:
        output = json.loads(observation.output_json)
    except json.JSONDecodeError as exc:
        raise ActorLoopError("probe observation output is invalid") from exc
    recreated = ProbeObservation.create(
        episode_id=observation.episode_id,
        step_index=observation.step_index,
        probe_id=observation.probe_id,
        status_code=observation.status_code,
        stdout=observation.stdout,
        stderr=observation.stderr,
        output=output,
        before_state_digest=observation.before_state_digest,
        after_state_digest=observation.after_state_digest,
    )
    if recreated != observation:
        raise ActorLoopError("probe observation is not canonical and self-consistent")
    return observation


def run_actor_loop(
    *,
    experiment_id: str,
    episode_id: str,
    arm_id: str,
    descriptor: PublicEnvironmentDescriptor,
    candidates: tuple[VisibleProbeCandidate, ...],
    challenge_catalogue: ChallengeCatalogue,
    actor_port: DockerActorPort,
    execute_probe: Callable[[ProbeRequest], ProbeObservation],
    probe_budget: int = 4,
) -> ActorLoopReceipt:
    _name(experiment_id, "experiment_id")
    _name(episode_id, "episode_id")
    _name(arm_id, "arm_id")
    if type(actor_port) is not DockerActorPort:
        raise ActorLoopError("actor requires the trusted Docker actor port")
    if challenge_catalogue.instance_public_digest != descriptor.descriptor_digest:
        raise ActorLoopError("challenge catalogue does not bind the public descriptor")
    if probe_budget != 4 or isinstance(probe_budget, bool):
        raise ActorLoopError("successor actor requires the fixed four-probe budget")
    if len(candidates) < probe_budget + 1:
        raise ActorLoopError("k=0..4 decisions require at least five legal probes")
    public_probes = tuple(
        sorted(
            (
                PublicProbePayload(
                    candidate.probe_id,
                    candidate.stable_order,
                    descriptor.operation_id,
                    candidate.payload_json,
                    candidate.cost_units,
                )
                for candidate in candidates
            ),
            key=lambda item: item.stable_order,
        )
    )
    ids = tuple(item.probe_id for item in public_probes)
    orders = tuple(item.stable_order for item in public_probes)
    if len(ids) != len(set(ids)) or len(orders) != len(set(orders)):
        raise ActorLoopError("legal probe ids and stable orders must be unique")

    remaining = list(public_probes)
    observations: list[ProbeObservation] = []
    selected: list[str] = []
    bundles: list[DiscoveryScoreBundle] = []
    decision_digests: list[str] = []
    invocation_receipts: list[ActorInvocationReceipt] = []
    container_ids: set[str] = set()
    parent_digest: str | None = None
    prior_evidence_state_digest: str | None = None
    state_digest = descriptor.initial_state_digest
    for prefix_index in range(probe_budget + 1):
        legal = tuple(remaining)
        public_observations = tuple(
            _public_observation_mapping(item) for item in observations
        )
        transcript_prefix_digest = content_digest(
            "active-actor-public-transcript/v1", list(public_observations)
        )
        request = {
            "schema_version": ACTOR_REQUEST_SCHEMA,
            "public_descriptor": _descriptor_mapping(descriptor),
            "legal_probe_payloads": [item.to_mapping() for item in legal],
            "prefix_observations": list(public_observations),
            "transcript_prefix_digest": transcript_prefix_digest,
        }
        request_bytes = canonical_json(request).encode("utf-8")
        first = actor_port.invoke(request_bytes)
        second = actor_port.invoke(request_bytes)
        if first.receipt.container_id == second.receipt.container_id:
            raise ActorLoopError("determinism replay did not use fresh containers")
        if first.canonical_response_bytes != second.canonical_response_bytes:
            raise ActorLoopError("cold actor is non-deterministic for exact request bytes")
        for invocation in (first.receipt, second.receipt):
            if invocation.container_id in container_ids:
                raise ActorLoopError("Docker actor container identity was reused")
            container_ids.add(invocation.container_id)
            invocation_receipts.append(invocation)
        raw_output = json.loads(first.canonical_response_bytes)
        if not isinstance(raw_output, Mapping):
            raise ActorLoopError("actor response must be an object")
        output = ActorModelOutput.from_mapping(raw_output)
        if output.evidence_binding.transcript_prefix_digest != transcript_prefix_digest:
            raise ActorLoopError("actor transcript evidence binding mismatch")
        if prefix_index == 0:
            if output.evidence_binding.update_disposition != "ABSTAIN_INSUFFICIENT_EVIDENCE":
                raise ActorLoopError("k=0 actor must abstain from evidence update")
        elif output.evidence_binding.update_disposition == "MATERIAL_UPDATE":
            if output.evidence_state_digest == prior_evidence_state_digest:
                raise ActorLoopError("claimed material update ignored transcript evidence")

            counterfactual_observations = [dict(item) for item in public_observations]
            changed = counterfactual_observations[-1]
            changed["outcome_label"] = (
                "STATUS_NONZERO"
                if changed["outcome_label"] == "STATUS_ZERO"
                else "STATUS_ZERO"
            )
            changed_without_digest = dict(changed)
            del changed_without_digest["public_observation_digest"]
            changed["public_observation_digest"] = content_digest(
                "active-actor-public-observation/v1", changed_without_digest
            )
            counterfactual_digest = content_digest(
                "active-actor-public-transcript/v1", counterfactual_observations
            )
            counterfactual_request = {
                **request,
                "prefix_observations": counterfactual_observations,
                "transcript_prefix_digest": counterfactual_digest,
            }
            counterfactual_bytes = canonical_json(counterfactual_request).encode()
            counterfactual_first = actor_port.invoke(counterfactual_bytes)
            counterfactual_second = actor_port.invoke(counterfactual_bytes)
            if (
                counterfactual_first.canonical_response_bytes
                != counterfactual_second.canonical_response_bytes
            ):
                raise ActorLoopError("counterfactual actor replay is non-deterministic")
            for invocation in (
                counterfactual_first.receipt,
                counterfactual_second.receipt,
            ):
                if invocation.container_id in container_ids:
                    raise ActorLoopError("Docker actor container identity was reused")
                container_ids.add(invocation.container_id)
                invocation_receipts.append(invocation)
            counterfactual_raw = json.loads(
                counterfactual_first.canonical_response_bytes
            )
            if not isinstance(counterfactual_raw, Mapping):
                raise ActorLoopError("counterfactual actor response must be an object")
            counterfactual_output = ActorModelOutput.from_mapping(counterfactual_raw)
            if (
                counterfactual_output.evidence_binding.transcript_prefix_digest
                != counterfactual_digest
            ):
                raise ActorLoopError("counterfactual transcript evidence binding mismatch")
            if (
                counterfactual_output.evidence_binding.update_disposition
                == "MATERIAL_UPDATE"
                and counterfactual_output.posterior_digest == output.posterior_digest
            ):
                raise ActorLoopError(
                    "same-length counterfactual produced the same material posterior"
                )
        elif output.evidence_state_digest != prior_evidence_state_digest:
            raise ActorLoopError("abstention cannot mutate the evidence state")
        prior_evidence_state_digest = output.evidence_state_digest
        _validate_decision(output, legal)
        decision_digests.append(
            content_digest("active-actor-decision/v2", output.to_mapping())
        )
        budget_receipt_digest = content_digest(
            "active-actor-budget-prefix/v2",
            {
                "episode_id": episode_id,
                "arm_id": arm_id,
                "consumed_units": prefix_index,
                "request_digest": first.receipt.request_digest,
                "actor_binding_digest": actor_port.actor_binding_digest,
            },
        )
        try:
            bundle = DiscoveryScoreBundle.create(
                experiment_id=experiment_id,
                instance_public_digest=descriptor.descriptor_digest,
                arm_id=arm_id,
                actor_binding_digest=actor_port.actor_binding_digest,
                prefix_index=prefix_index,
                parent_bundle_digest=parent_digest,
                predictions=output.predictions,
                test_ir=output.test_ir,
                transcript_prefix_digest=transcript_prefix_digest,
                consumed_units=prefix_index,
                budget_receipt_digest=budget_receipt_digest,
                catalogue=challenge_catalogue,
            )
        except ScoringContractError as exc:
            raise ActorLoopError("actor bundle failed the closed scoring contract") from exc
        bundles.append(bundle)
        parent_digest = bundle.bundle_digest
        if prefix_index == probe_budget:
            break
        chosen = next(
            probe for probe in remaining if probe.probe_id == output.selected_probe_id
        )
        probe_request = ProbeRequest(
            episode_id=episode_id,
            arm_id=arm_id,
            step_index=prefix_index,
            probe_id=chosen.probe_id,
            operation_id=chosen.operation_id,
            payload_json=chosen.payload_json,
            expected_state_digest=state_digest,
            cost_units=chosen.cost_units,
        )
        observation = _validated_observation(execute_probe(probe_request), probe_request)
        observations.append(observation)
        selected.append(chosen.probe_id)
        state_digest = observation.after_state_digest
        remaining.remove(chosen)
    return ActorLoopReceipt(
        prefix_bundles=tuple(bundles),
        selected_probe_ids=tuple(selected),
        observations=tuple(observations),
        decision_digests=tuple(decision_digests),
        actor_invocation_receipts=tuple(invocation_receipts),
    )
