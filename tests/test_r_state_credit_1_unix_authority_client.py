from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import stat
import struct
import subprocess
import shutil
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias, cast

import pytest

from experiments.r_state_credit_1.execution_bridge import (
    ExecutionAdmission,
    ExecutionBridgeViolation,
    ReceiptKind,
    ReservationClaimReceipt,
    canonical_json,
)
from experiments.r_state_credit_1.unix_authority_client import UnixAuthorityClient


TOKEN = bytes(range(32))
PROTOCOL = "r-state-authority-v1"
BROKER = "workflow-authority-broker-1"
SERVER_NONCE = "5" * 64
MAX_FRAME = 64 * 1024
_OPENSSL_LOCATOR = shutil.which("openssl")
assert _OPENSSL_LOCATOR is not None
_OPENSSL_BINARY = Path(_OPENSSL_LOCATOR).resolve()


def _openssl_binary() -> Path:
    return _OPENSSL_BINARY


def _socket_path(label: str) -> Path:
    path = (
        Path(tempfile.gettempdir()) / f"rs-{os.getpid()}-{label}-{os.urandom(4).hex()}"
    )
    path.unlink(missing_ok=True)
    return path


def _read_exact(stream: socket.socket, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = stream.recv(remaining)
        if not chunk:
            raise EOFError("truncated")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_frame(stream: socket.socket) -> bytes:
    size = struct.unpack(">I", _read_exact(stream, 4))[0]
    assert 0 < size <= MAX_FRAME
    return _read_exact(stream, size)


def _sign(private_key: Path, payload: dict[str, object]) -> bytes:
    unsigned = canonical_json(payload).encode()
    message_path = private_key.parent / "message-to-sign.bin"
    message_path.write_bytes(unsigned)
    completed = subprocess.run(
        [
            str(_openssl_binary()),
            "pkeyutl",
            "-sign",
            "-inkey",
            str(private_key),
            "-rawin",
            "-in",
            str(message_path),
        ],
        capture_output=True,
        check=True,
    )
    return completed.stdout


def _response(
    request: dict[str, object],
    payload: object,
    private_key: Path,
    public_key_sha256: str,
) -> bytes:
    response = {
        "protocol_version": PROTOCOL,
        "broker_id": BROKER,
        "request_id": request["request_id"],
        "op": request["op"],
        "status": "OK",
        "run_id": request["run_id"],
        "envelope_sha256": request["envelope_sha256"],
        "reservation_id": request["reservation_id"],
        "attempt_epoch": request["attempt_epoch"],
        "cas_epoch": request["cas_epoch"],
        "client_nonce": request["client_nonce"],
        "payload": payload,
        "server_nonce_sha256": SERVER_NONCE,
        "response_public_key_sha256": public_key_sha256,
        "request_sha256": hashlib.sha256(canonical_json(request).encode()).hexdigest(),
    }
    response["signature_b64"] = base64.b64encode(_sign(private_key, response)).decode()
    return canonical_json(response).encode()


_WireReply: TypeAlias = bytes | tuple[int, bytes]


class _Server:
    def __init__(
        self,
        path: Path,
        handlers: list[Callable[[dict[str, object]], _WireReply]],
        require_request_eof: bool = False,
    ) -> None:
        self.path = path
        self.handlers = handlers
        self.require_request_eof = require_request_eof
        self.requests: list[dict[str, object]] = []
        self.error: BaseException | None = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> _Server:
        self.thread.start()
        assert self.ready.wait(5)
        return self

    def __exit__(self, *args: object) -> None:
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()
        if self.error is not None:
            raise self.error

    def _run(self) -> None:
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.path))
            listener.listen()
            self.ready.set()
            for handler in self.handlers:
                connection, _ = listener.accept()
                with connection:
                    encoded = _read_frame(connection)
                    request = json.loads(encoded)
                    assert encoded == canonical_json(request).encode()
                    self.requests.append(request)
                    if self.require_request_eof:
                        assert connection.recv(1) == b""
                    reply = handler(request)
                    declared_size, body = (
                        reply if isinstance(reply, tuple) else (len(reply), reply)
                    )
                    try:
                        connection.sendall(struct.pack(">I", declared_size) + body)
                    except BrokenPipeError:
                        # Expected when the client rejects an oversized header
                        # before the fixture can finish writing the body.
                        pass
        except BaseException as exc:  # pragma: no cover - surfaced by __exit__
            self.error = exc
        finally:
            self.ready.set()
            listener.close()
            self.path.unlink(missing_ok=True)


@pytest.fixture
def keypair(tmp_path: Path) -> tuple[Path, Path, str]:
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    subprocess.run(
        [
            str(_openssl_binary()),
            "genpkey",
            "-algorithm",
            "ED25519",
            "-out",
            str(private_key),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            str(_openssl_binary()),
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        ],
        check=True,
        capture_output=True,
    )
    digest = hashlib.sha256(public_key.read_bytes()).hexdigest()
    return private_key, public_key, digest


def _admission(
    public_key_sha256: str,
    *,
    verifier_binary_path: Path | None = None,
    verifier_binary_sha256: str | None = None,
) -> ExecutionAdmission:
    verifier = verifier_binary_path or _openssl_binary()
    isolation_binding = {
        "schema_version": "r-state-credit-1-isolation-binding-v2",
        "interpreter_path": "/usr/bin/python3",
        "interpreter_sha256": "4" * 64,
        "sandbox_profile_sha256": "3" * 64,
        "required_deny_set_sha256": "2" * 64,
        "authority_public_key_sha256": public_key_sha256,
        "child_command_sha256": "1" * 64,
        "verifier_binary_path": str(verifier),
        "verifier_binary_sha256": verifier_binary_sha256
        or hashlib.sha256(verifier.read_bytes()).hexdigest(),
    }
    mapping: dict[str, object] = {
        "schema_version": "r-state-credit-1-execution-admission-v4",
        "route_id": "R-STATE-CREDIT-1",
        "run_id": "run-authority-client-1",
        "freeze_subject_digest": "a" * 64,
        "freeze_receipt_id": "freeze-1",
        "run_authorization_receipt_id": "run-auth-1",
        "mechanism_head": "96eb79e1292d6b8f36ad990d3f97c554a9c33f3b",
        "execution_code_head": "7" * 40,
        "active_manifest_sha256": "b" * 64,
        "provider_binding": {
            "provider_id": "volcengine-ark-agent-plan",
            "base_url_profile": "https://ark.cn-beijing.volces.com/api/plan/v3",
            "model_id": "glm-5-2-260617",
            "model_revision": "glm-5-2-260617",
            "credential_env_ref": "ARK_API_KEY",
            "canary_receipt_sha256": "c" * 64,
        },
        "c7_binding": {
            "owner_id": "c7-owner:security",
            "policy_sha256": "d" * 64,
            "correction_epoch": "epoch-1",
        },
        "authority_binding": {
            "broker_id": BROKER,
            "protocol_version": PROTOCOL,
            "response_public_key_sha256": public_key_sha256,
            "server_nonce_sha256": SERVER_NONCE,
            "isolation_binding_sha256": hashlib.sha256(
                canonical_json(isolation_binding).encode()
            ).hexdigest(),
        },
        "isolation_binding": isolation_binding,
        "workflow_reservation": {
            "reservation_id": "reservation-1",
            "reservation_token_sha256": hashlib.sha256(TOKEN).hexdigest(),
            "attempt_epoch": 2,
            "cas_epoch": 3,
        },
        "components": {
            "executor_sha256": "e" * 64,
            "scorer_sha256": "f" * 64,
            "integrity_sha256": "1" * 64,
        },
        "budget": {
            "max_provider_calls": 2240,
            "max_total_input_tokens": 1,
            "max_total_output_tokens": 1,
            "max_total_tokens": 2,
            "max_input_tokens_per_call": 1,
            "max_output_tokens_per_call": 1,
            "max_total_tokens_per_call": 2,
        },
        "six_receipt_digests": {
            kind.value: str(index) * 64
            for index, kind in enumerate(ReceiptKind, start=2)
        },
        "envelope_core_sha256": "0" * 64,
        "envelope_sha256": "0" * 64,
    }
    core = dict(mapping)
    core.pop("envelope_core_sha256")
    core.pop("envelope_sha256")
    receipts = dict(cast(dict[str, str], core["six_receipt_digests"]))
    receipts.pop(ReceiptKind.RUN_AUTHORIZATION.value)
    core["six_receipt_digests"] = receipts
    mapping["envelope_core_sha256"] = hashlib.sha256(
        canonical_json(core).encode()
    ).hexdigest()
    final = dict(mapping)
    final.pop("envelope_sha256")
    mapping["envelope_sha256"] = hashlib.sha256(
        canonical_json(final).encode()
    ).hexdigest()
    return ExecutionAdmission.from_mapping(mapping)


def _client(
    admission: ExecutionAdmission,
    socket_path: Path,
    public_key: Path,
) -> UnixAuthorityClient:
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, TOKEN)
    finally:
        os.close(write_fd)
    return UnixAuthorityClient(
        admission=admission,
        socket_path=socket_path,
        response_public_key_path=public_key,
        reservation_token_fd=read_fd,
        verifier_binary_path=Path(admission.isolation_binding.verifier_binary_path),
        verifier_binary_sha256=admission.isolation_binding.verifier_binary_sha256,
    )


def test_client_implements_all_authority_and_c7_operations(
    tmp_path: Path,
    keypair: tuple[Path, Path, str],
) -> None:
    private_key, public_key, public_digest = keypair
    admission = _admission(public_digest)
    socket_path = _socket_path("ok")
    receipt_bytes = b'{"receipt":"exact"}'
    claim_payload = {
        "registry_verified": True,
        "claimed": True,
        "claim_id": "claim-1",
        "reservation_id": "reservation-1",
        "reservation_token_sha256": hashlib.sha256(TOKEN).hexdigest(),
        "attempt_epoch": 2,
        "cas_epoch": 3,
        "run_id": admission.run_id,
        "envelope_sha256": admission.envelope_sha256,
        "claimant_nonce_sha256": "9" * 64,
    }
    terminal_payload = {
        "registry_verified": True,
        "claim_id": "claim-1",
        "state": "SEALED_RAW",
        "terminal_sha256": "8" * 64,
        "terminalized": True,
    }
    payloads: list[object] = [
        {
            "registry_verified": True,
            "principal_id": "registry:c7",
            "role": "c7-owner",
            "purpose": "C7_BINDING_ACCEPTANCE",
            "subject_sha256": "7" * 64,
            "artifact_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        },
        None,
        claim_payload,
        {
            "abort_requested": False,
            "owner_id": admission.c7_binding.owner_id,
            "policy_sha256": admission.c7_binding.policy_sha256,
            "correction_epoch": admission.c7_binding.correction_epoch,
            "c7_epoch": 4,
        },
        None,
        terminal_payload,
    ]
    handlers = [
        lambda request, payload=payload: _response(
            request, payload, private_key, public_digest
        )
        for payload in payloads
    ]
    with _Server(socket_path, handlers) as server:
        client = _client(admission, socket_path, public_key)
        verified = client.verify(ReceiptKind.C7, receipt_bytes)
        assert verified.principal_id == "registry:c7"
        assert (
            client.query_claim(
                admission.workflow_reservation.to_mapping(),
                admission.run_id,
                admission.envelope_sha256,
                "9" * 64,
            )
            is None
        )
        claim = client.claim(
            admission.workflow_reservation.to_mapping(),
            admission.run_id,
            admission.envelope_sha256,
            "9" * 64,
        )
        assert claim.claim_id == "claim-1"
        assert client.abort_requested() is False
        assert client.query_terminal("claim-1") is None
        terminal = client.terminalize(claim, "SEALED_RAW", "8" * 64)
        assert terminal.terminalized is True

    assert [request["op"] for request in server.requests] == [
        "VERIFY_RECEIPT",
        "QUERY_CLAIM",
        "CLAIM",
        "C7",
        "QUERY_TERMINAL",
        "TERMINALIZE",
    ]
    for request in server.requests:
        signature = cast(str, request.pop("request_hmac_sha256"))
        assert hmac.compare_digest(
            signature,
            hmac.new(
                TOKEN, canonical_json(request).encode(), hashlib.sha256
            ).hexdigest(),
        )
        assert request["run_id"] == admission.run_id
        assert request["envelope_sha256"] == admission.envelope_sha256
        assert len(cast(str, request["request_id"])) == 64
        assert all(
            character in "0123456789abcdef"
            for character in cast(str, request["request_id"])
        )


@pytest.mark.parametrize(
    "attack",
    [
        "bad_signature",
        "replayed_client_nonce",
        "cross_run",
        "extra_field",
        "truncated_frame",
        "oversized_frame",
        "server_nonce_drift",
        "public_key_hash_drift",
        "zero_frame",
        "trailing_frame",
        "request_digest_drift",
    ],
)
def test_client_fails_closed_on_signed_response_or_frame_attack(
    tmp_path: Path,
    keypair: tuple[Path, Path, str],
    attack: str,
) -> None:
    private_key, public_key, public_digest = keypair
    admission = _admission(public_digest)
    socket_path = _socket_path(attack[:8])

    def handler(request: dict[str, object]) -> _WireReply:
        encoded = _response(
            request,
            {
                "abort_requested": False,
                "owner_id": admission.c7_binding.owner_id,
                "policy_sha256": admission.c7_binding.policy_sha256,
                "correction_epoch": admission.c7_binding.correction_epoch,
                "c7_epoch": 4,
            },
            private_key,
            public_digest,
        )
        response = json.loads(encoded)
        if attack == "bad_signature":
            response["signature_b64"] = base64.b64encode(b"forged").decode()
        elif attack == "replayed_client_nonce":
            response["client_nonce"] = "0" * 64
        elif attack == "cross_run":
            response["run_id"] = "other-run"
        elif attack == "extra_field":
            response["unexpected"] = True
        elif attack == "server_nonce_drift":
            response["server_nonce_sha256"] = "0" * 64
        elif attack == "public_key_hash_drift":
            response["response_public_key_sha256"] = "0" * 64
        elif attack == "request_digest_drift":
            response["request_sha256"] = "0" * 64
        elif attack == "truncated_frame":
            return len(encoded), encoded[:-1]
        elif attack == "oversized_frame":
            return MAX_FRAME + 1, b""
        elif attack == "zero_frame":
            return 0, b""
        elif attack == "trailing_frame":
            return len(encoded), encoded + struct.pack(">I", 2) + b"{}"
        if attack != "bad_signature":
            response.pop("signature_b64")
            response["signature_b64"] = base64.b64encode(
                _sign(private_key, response)
            ).decode()
        return canonical_json(response).encode()

    with _Server(socket_path, [handler]):
        client = _client(admission, socket_path, public_key)
        with pytest.raises(ExecutionBridgeViolation):
            client.abort_requested()


def test_public_key_and_token_are_pinned_not_trusted_by_locator(
    tmp_path: Path,
    keypair: tuple[Path, Path, str],
) -> None:
    _private_key, public_key, public_digest = keypair
    admission = _admission(public_digest)
    socket_path = _socket_path("missing")

    wrong = tmp_path / "wrong.pem"
    wrong.write_bytes(public_key.read_bytes() + b"\n")
    with pytest.raises(ExecutionBridgeViolation, match="public key digest"):
        _client(admission, socket_path, wrong)

    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"wrong-token")
    os.close(write_fd)
    with pytest.raises(ExecutionBridgeViolation, match="reservation token digest"):
        UnixAuthorityClient(
            admission=admission,
            socket_path=socket_path,
            response_public_key_path=public_key,
            reservation_token_fd=read_fd,
            verifier_binary_path=Path(admission.isolation_binding.verifier_binary_path),
            verifier_binary_sha256=(admission.isolation_binding.verifier_binary_sha256),
        )


def test_verifier_binary_path_hash_and_symlink_fail_closed(
    tmp_path: Path,
    keypair: tuple[Path, Path, str],
) -> None:
    _private_key, public_key, public_digest = keypair
    real_binary = _openssl_binary()

    wrong_hash = _admission(public_digest, verifier_binary_sha256="0" * 64)
    with pytest.raises(ExecutionBridgeViolation, match="verifier binary digest"):
        _client(wrong_hash, _socket_path("wrong-verifier-hash"), public_key)

    symlink = tmp_path / "openssl-link"
    symlink.symlink_to(real_binary)
    symlink_admission = _admission(
        public_digest,
        verifier_binary_path=symlink,
        verifier_binary_sha256=hashlib.sha256(real_binary.read_bytes()).hexdigest(),
    )
    with pytest.raises(ExecutionBridgeViolation, match="real non-symlink"):
        _client(symlink_admission, _socket_path("symlink-verifier"), public_key)

    read_fd, write_fd = os.pipe()
    os.write(write_fd, TOKEN)
    os.close(write_fd)
    with pytest.raises(ExecutionBridgeViolation, match="signed verifier.*drift"):
        UnixAuthorityClient(
            admission=_admission(public_digest),
            socket_path=_socket_path("verifier-path-drift"),
            response_public_key_path=public_key,
            reservation_token_fd=read_fd,
            verifier_binary_path=tmp_path / "different-openssl",
            verifier_binary_sha256=hashlib.sha256(real_binary.read_bytes()).hexdigest(),
        )


def test_verifier_binary_bytes_are_rechecked_before_every_signature(
    tmp_path: Path,
    keypair: tuple[Path, Path, str],
) -> None:
    _private_key, public_key, public_digest = keypair
    verifier = tmp_path / "openssl-copy"
    shutil.copy2(_openssl_binary(), verifier)
    verifier.chmod(verifier.stat().st_mode | stat.S_IWUSR)
    admission = _admission(public_digest, verifier_binary_path=verifier)
    client = _client(admission, _socket_path("verifier-drift"), public_key)

    verifier.write_bytes(verifier.read_bytes() + b"drift")

    with pytest.raises(ExecutionBridgeViolation, match="verifier binary digest"):
        client._verify_ed25519(b"message", b"signature")


def test_path_replacement_cannot_change_signed_verifier(
    tmp_path: Path,
    keypair: tuple[Path, Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, public_key, public_digest = keypair
    fake_directory = tmp_path / "fake-path"
    fake_directory.mkdir()
    fake_openssl = fake_directory / "openssl"
    fake_openssl.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    fake_openssl.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_directory))
    admission = _admission(public_digest)
    socket_path = _socket_path("path-replacement")

    def handler(request: dict[str, object]) -> bytes:
        return _response(
            request,
            {
                "abort_requested": False,
                "owner_id": admission.c7_binding.owner_id,
                "policy_sha256": admission.c7_binding.policy_sha256,
                "correction_epoch": admission.c7_binding.correction_epoch,
                "c7_epoch": 1,
            },
            private_key,
            public_digest,
        )

    with _Server(socket_path, [handler]):
        assert _client(admission, socket_path, public_key).abort_requested() is False


def test_client_half_closes_request_before_reading_signed_response(
    tmp_path: Path,
    keypair: tuple[Path, Path, str],
) -> None:
    private_key, public_key, public_digest = keypair
    admission = _admission(public_digest)
    socket_path = _socket_path("half-close")

    def handler(request: dict[str, object]) -> bytes:
        return _response(
            request,
            {
                "abort_requested": False,
                "owner_id": admission.c7_binding.owner_id,
                "policy_sha256": admission.c7_binding.policy_sha256,
                "correction_epoch": admission.c7_binding.correction_epoch,
                "c7_epoch": 1,
            },
            private_key,
            public_digest,
        )

    with _Server(socket_path, [handler], require_request_eof=True):
        client = _client(admission, socket_path, public_key)
        assert client.abort_requested() is False


@pytest.mark.parametrize("second_epoch", [1, 2])
def test_c7_abort_is_sticky_and_cannot_be_cleared_by_a_signed_response(
    tmp_path: Path,
    keypair: tuple[Path, Path, str],
    second_epoch: int,
) -> None:
    private_key, public_key, public_digest = keypair
    admission = _admission(public_digest)
    socket_path = _socket_path(f"sticky-{second_epoch}")

    def c7_response(request: dict[str, object], abort: bool, epoch: int) -> bytes:
        return _response(
            request,
            {
                "abort_requested": abort,
                "owner_id": admission.c7_binding.owner_id,
                "policy_sha256": admission.c7_binding.policy_sha256,
                "correction_epoch": admission.c7_binding.correction_epoch,
                "c7_epoch": epoch,
            },
            private_key,
            public_digest,
        )

    handlers = [
        lambda request: c7_response(request, True, 1),
        lambda request: c7_response(request, False, second_epoch),
    ]
    with _Server(socket_path, handlers):
        client = _client(admission, socket_path, public_key)
        assert client.abort_requested() is True
        with pytest.raises(ExecutionBridgeViolation, match="cannot be cleared"):
            client.abort_requested()


def test_c7_state_cannot_change_inside_one_signed_epoch(
    tmp_path: Path,
    keypair: tuple[Path, Path, str],
) -> None:
    private_key, public_key, public_digest = keypair
    admission = _admission(public_digest)
    socket_path = _socket_path("epoch-drift")

    def response(request: dict[str, object], abort: bool) -> bytes:
        return _response(
            request,
            {
                "abort_requested": abort,
                "owner_id": admission.c7_binding.owner_id,
                "policy_sha256": admission.c7_binding.policy_sha256,
                "correction_epoch": admission.c7_binding.correction_epoch,
                "c7_epoch": 7,
            },
            private_key,
            public_digest,
        )

    with _Server(
        socket_path,
        [
            lambda request: response(request, False),
            lambda request: response(request, True),
        ],
    ):
        client = _client(admission, socket_path, public_key)
        assert client.abort_requested() is False
        with pytest.raises(ExecutionBridgeViolation, match="state drift"):
            client.abort_requested()


def test_terminalize_rejects_a_claim_from_another_run_before_transport(
    tmp_path: Path,
    keypair: tuple[Path, Path, str],
) -> None:
    _private_key, public_key, public_digest = keypair
    admission = _admission(public_digest)
    client = _client(admission, _socket_path("no-server"), public_key)
    foreign_claim = ReservationClaimReceipt(
        registry_verified=True,
        claimed=True,
        claim_id="foreign-claim",
        reservation_id=admission.workflow_reservation.reservation_id,
        reservation_token_sha256=(
            admission.workflow_reservation.reservation_token_sha256
        ),
        attempt_epoch=admission.workflow_reservation.attempt_epoch,
        cas_epoch=admission.workflow_reservation.cas_epoch,
        run_id="different-run",
        envelope_sha256=admission.envelope_sha256,
        claimant_nonce_sha256="9" * 64,
    )

    with pytest.raises(ExecutionBridgeViolation, match="claim binding"):
        client.terminalize(foreign_claim, "SEALED_RAW", "8" * 64)
