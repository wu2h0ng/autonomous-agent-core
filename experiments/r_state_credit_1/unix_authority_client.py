"""Pinned Unix-socket client for the external R-STATE authority broker."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import socket
import stat
import struct
import subprocess
import tempfile
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import cast

from experiments.r_state_credit_1.execution_bridge import (
    ExecutionAdmission,
    ExecutionBridgeViolation,
    ReceiptKind,
    ReceiptVerification,
    ReservationClaimReceipt,
    ReservationTerminalReceipt,
    canonical_json,
)


MAX_FRAME_BYTES = 64 * 1024
_RESPONSE_FIELDS = {
    "protocol_version",
    "broker_id",
    "request_id",
    "op",
    "status",
    "run_id",
    "envelope_sha256",
    "reservation_id",
    "attempt_epoch",
    "cas_epoch",
    "client_nonce",
    "payload",
    "server_nonce_sha256",
    "response_public_key_sha256",
    "request_sha256",
    "signature_b64",
}
_CLAIM_FIELDS = {
    "registry_verified",
    "claimed",
    "claim_id",
    "reservation_id",
    "reservation_token_sha256",
    "attempt_epoch",
    "cas_epoch",
    "run_id",
    "envelope_sha256",
    "claimant_nonce_sha256",
}
_TERMINAL_FIELDS = {
    "registry_verified",
    "claim_id",
    "state",
    "terminal_sha256",
    "terminalized",
}
_VERIFICATION_FIELDS = {
    "registry_verified",
    "principal_id",
    "role",
    "purpose",
    "subject_sha256",
    "artifact_sha256",
}
_HEX = frozenset("0123456789abcdef")


def _closed(value: object, expected: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ExecutionBridgeViolation(f"{label} must use the closed field set")
    return cast(dict[str, object], value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExecutionBridgeViolation(f"{label} must be non-empty text")
    return value


def _sha(value: object, label: str) -> str:
    result = _text(value, label)
    if len(result) != 64 or any(char not in _HEX for char in result):
        raise ExecutionBridgeViolation(f"{label} must be a lowercase SHA-256")
    return result


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ExecutionBridgeViolation(f"{label} must be a positive integer")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ExecutionBridgeViolation(f"{label} must be bool")
    return value


class UnixAuthorityClient:
    """AuthorityVerifier and C7Probe backed by a signed local broker."""

    def __init__(
        self,
        *,
        admission: ExecutionAdmission,
        socket_path: Path,
        response_public_key_path: Path,
        reservation_token_fd: int,
        verifier_binary_path: Path,
        verifier_binary_sha256: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ExecutionBridgeViolation("authority timeout must be positive")
        try:
            token = os.read(reservation_token_fd, 33)
        except OSError as exc:
            raise ExecutionBridgeViolation(
                "reservation token FD is unreadable"
            ) from exc
        finally:
            try:
                os.close(reservation_token_fd)
            except OSError:
                pass
        if len(token) != 32 or hashlib.sha256(token).hexdigest() != (
            admission.workflow_reservation.reservation_token_sha256
        ):
            raise ExecutionBridgeViolation("reservation token digest drift")
        self._reservation_token = token
        self._admission = admission
        self._socket_path = socket_path
        self._timeout_seconds = timeout_seconds
        self.owner_id = admission.c7_binding.owner_id
        self.policy_sha256 = admission.c7_binding.policy_sha256
        self.correction_epoch = admission.c7_binding.correction_epoch
        self._last_c7_epoch = 0
        self._last_abort_requested: bool | None = None
        self._claimant_nonces: dict[str, str] = {}
        isolation = admission.isolation_binding
        if (
            str(verifier_binary_path) != isolation.verifier_binary_path
            or verifier_binary_sha256 != isolation.verifier_binary_sha256
        ):
            raise ExecutionBridgeViolation("signed verifier binary binding drift")
        self._verifier_binary_path = verifier_binary_path
        self._verifier_binary_sha256 = _sha(
            verifier_binary_sha256, "verifier binary SHA-256"
        )
        self._verify_verifier_binary()

        try:
            public_key = response_public_key_path.read_bytes()
        except OSError as exc:
            raise ExecutionBridgeViolation(
                "authority public key is unavailable"
            ) from exc
        if (
            hashlib.sha256(public_key).hexdigest()
            != admission.authority_binding.response_public_key_sha256
        ):
            raise ExecutionBridgeViolation("authority public key digest drift")
        self._public_key = public_key

    def _open_verified_verifier_binary(self) -> int:
        path = self._verifier_binary_path
        if not path.is_absolute():
            raise ExecutionBridgeViolation("verifier binary path must be absolute")
        try:
            path_stat = path.lstat()
        except OSError as exc:
            raise ExecutionBridgeViolation("verifier binary is unavailable") from exc
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise ExecutionBridgeViolation(
                "verifier binary must be a real non-symlink file"
            )
        if path_stat.st_mode & 0o111 == 0:
            raise ExecutionBridgeViolation("verifier binary must be executable")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ExecutionBridgeViolation(
                "verifier binary secure open failed"
            ) from exc
        try:
            opened_stat = os.fstat(descriptor)
            if not stat.S_ISREG(opened_stat.st_mode) or (
                opened_stat.st_dev,
                opened_stat.st_ino,
            ) != (path_stat.st_dev, path_stat.st_ino):
                raise ExecutionBridgeViolation("verifier binary identity drift")
            digest = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            final_stat = os.fstat(descriptor)
            if (
                final_stat.st_size != opened_stat.st_size
                or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
                or final_stat.st_ctime_ns != opened_stat.st_ctime_ns
            ):
                raise ExecutionBridgeViolation("verifier binary changed during hashing")
            if digest.hexdigest() != self._verifier_binary_sha256:
                raise ExecutionBridgeViolation("verifier binary digest drift")
            os.lseek(descriptor, 0, os.SEEK_SET)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _verify_verifier_binary(self) -> None:
        descriptor = self._open_verified_verifier_binary()
        os.close(descriptor)

    @contextmanager
    def _private_verifier_copy(self) -> Iterator[Path]:
        source = self._open_verified_verifier_binary()
        try:
            with tempfile.TemporaryDirectory(
                prefix="r-state-verifier-copy-"
            ) as raw_directory:
                directory = Path(raw_directory)
                directory.chmod(0o700)
                if stat.S_IMODE(directory.lstat().st_mode) != 0o700:
                    raise ExecutionBridgeViolation(
                        "private verifier directory mode drift"
                    )
                destination = directory / f"verifier-{secrets.token_hex(16)}"
                flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                try:
                    output = os.open(destination, flags, 0o600)
                except OSError as exc:
                    raise ExecutionBridgeViolation(
                        "private verifier copy creation failed"
                    ) from exc
                copied_digest = hashlib.sha256()
                try:
                    while True:
                        chunk = os.read(source, 1024 * 1024)
                        if not chunk:
                            break
                        copied_digest.update(chunk)
                        view = memoryview(chunk)
                        while view:
                            written = os.write(output, view)
                            if written <= 0:
                                raise ExecutionBridgeViolation(
                                    "private verifier copy write failed"
                                )
                            view = view[written:]
                    os.fsync(output)
                    os.fchmod(output, 0o500)
                    os.fsync(output)
                finally:
                    os.close(output)
                if copied_digest.hexdigest() != self._verifier_binary_sha256:
                    raise ExecutionBridgeViolation("private verifier copy digest drift")
                copied_stat = destination.lstat()
                if (
                    not stat.S_ISREG(copied_stat.st_mode)
                    or stat.S_ISLNK(copied_stat.st_mode)
                    or stat.S_IMODE(copied_stat.st_mode) != 0o500
                ):
                    raise ExecutionBridgeViolation("private verifier copy mode drift")
                reopened = os.open(
                    destination,
                    os.O_RDONLY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                )
                try:
                    confirmed_digest = hashlib.sha256()
                    while True:
                        chunk = os.read(reopened, 1024 * 1024)
                        if not chunk:
                            break
                        confirmed_digest.update(chunk)
                finally:
                    os.close(reopened)
                if confirmed_digest.hexdigest() != self._verifier_binary_sha256:
                    raise ExecutionBridgeViolation(
                        "private verifier confirmation digest drift"
                    )
                yield destination
        finally:
            os.close(source)

    def _read_exact(self, stream: socket.socket, count: int) -> bytes:
        chunks: list[bytes] = []
        remaining = count
        while remaining:
            try:
                chunk = stream.recv(remaining)
            except OSError as exc:
                raise ExecutionBridgeViolation(
                    "authority response read failed"
                ) from exc
            if not chunk:
                raise ExecutionBridgeViolation("authority response frame is truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _verify_ed25519(self, message: bytes, signature: bytes) -> None:
        try:
            with (
                self._private_verifier_copy() as verifier,
                tempfile.TemporaryDirectory(prefix="r-state-authority-verify-") as raw,
            ):
                directory = Path(raw)
                public_key = directory / "response-public.pem"
                signature_path = directory / "response.sig"
                message_path = directory / "response-message.bin"
                public_key.write_bytes(self._public_key)
                signature_path.write_bytes(signature)
                message_path.write_bytes(message)
                completed = subprocess.run(
                    [
                        str(verifier),
                        "pkeyutl",
                        "-verify",
                        "-pubin",
                        "-inkey",
                        str(public_key),
                        "-rawin",
                        "-in",
                        str(message_path),
                        "-sigfile",
                        str(signature_path),
                    ],
                    capture_output=True,
                    check=False,
                    timeout=self._timeout_seconds,
                    env={"LC_ALL": "C"},
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ExecutionBridgeViolation(
                "authority Ed25519 verification unavailable"
            ) from exc
        if completed.returncode != 0:
            raise ExecutionBridgeViolation("authority response signature is invalid")

    def _request(self, op: str, payload: object) -> object:
        binding = self._admission.authority_binding
        reservation = self._admission.workflow_reservation
        request: dict[str, object] = {
            "protocol_version": binding.protocol_version,
            "broker_id": binding.broker_id,
            "request_id": secrets.token_hex(32),
            "op": op,
            "run_id": self._admission.run_id,
            "envelope_sha256": self._admission.envelope_sha256,
            "reservation_id": reservation.reservation_id,
            "attempt_epoch": reservation.attempt_epoch,
            "cas_epoch": reservation.cas_epoch,
            "client_nonce": secrets.token_hex(32),
            "payload": payload,
        }
        request["request_hmac_sha256"] = hmac.new(
            self._reservation_token,
            canonical_json(request).encode(),
            hashlib.sha256,
        ).hexdigest()
        _sha(request["request_id"], "authority request_id")
        encoded = canonical_json(request).encode()
        request_sha256 = hashlib.sha256(encoded).hexdigest()
        if not encoded or len(encoded) > MAX_FRAME_BYTES:
            raise ExecutionBridgeViolation("authority request exceeds 64KiB")

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(self._timeout_seconds)
                stream.connect(str(self._socket_path))
                stream.sendall(struct.pack(">I", len(encoded)) + encoded)
                stream.shutdown(socket.SHUT_WR)
                size = struct.unpack(">I", self._read_exact(stream, 4))[0]
                if not 0 < size <= MAX_FRAME_BYTES:
                    raise ExecutionBridgeViolation("authority response exceeds 64KiB")
                response_bytes = self._read_exact(stream, size)
                if stream.recv(1):
                    raise ExecutionBridgeViolation(
                        "authority response has trailing bytes"
                    )
        except ExecutionBridgeViolation:
            raise
        except OSError as exc:
            raise ExecutionBridgeViolation("authority broker transport failed") from exc

        try:
            response_raw = json.loads(response_bytes)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ExecutionBridgeViolation("authority response must be JSON") from exc
        if canonical_json(response_raw).encode() != response_bytes:
            raise ExecutionBridgeViolation("authority response must be canonical JSON")
        response = _closed(response_raw, _RESPONSE_FIELDS, "authority response")
        _sha(response["request_id"], "response request_id")
        _sha(response["request_sha256"], "response request_sha256")
        signature_b64 = _text(response["signature_b64"], "response signature_b64")
        try:
            signature = base64.b64decode(signature_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ExecutionBridgeViolation(
                "response signature must be strict base64"
            ) from exc
        if not signature or base64.b64encode(signature).decode() != signature_b64:
            raise ExecutionBridgeViolation(
                "response signature must be canonical base64"
            )
        unsigned = dict(response)
        unsigned.pop("signature_b64")
        self._verify_ed25519(canonical_json(unsigned).encode(), signature)

        echoes = {
            "protocol_version": binding.protocol_version,
            "broker_id": binding.broker_id,
            "request_id": request["request_id"],
            "op": op,
            "run_id": self._admission.run_id,
            "envelope_sha256": self._admission.envelope_sha256,
            "reservation_id": reservation.reservation_id,
            "attempt_epoch": reservation.attempt_epoch,
            "cas_epoch": reservation.cas_epoch,
            "client_nonce": request["client_nonce"],
            "server_nonce_sha256": binding.server_nonce_sha256,
            "response_public_key_sha256": binding.response_public_key_sha256,
            "request_sha256": request_sha256,
        }
        if any(response[name] != expected for name, expected in echoes.items()):
            raise ExecutionBridgeViolation("authority response echo binding drift")
        if response["status"] != "OK":
            raise ExecutionBridgeViolation("authority broker rejected operation")
        return response["payload"]

    def verify(self, kind: ReceiptKind, receipt_bytes: bytes) -> ReceiptVerification:
        if not isinstance(kind, ReceiptKind) or not isinstance(receipt_bytes, bytes):
            raise ExecutionBridgeViolation("receipt verification input is invalid")
        payload = self._request(
            "VERIFY_RECEIPT",
            {
                "kind": kind.value,
                "receipt_b64": base64.b64encode(receipt_bytes).decode(),
            },
        )
        raw = _closed(payload, _VERIFICATION_FIELDS, "receipt verification")
        result = ReceiptVerification(
            registry_verified=_boolean(
                raw["registry_verified"], "receipt registry_verified"
            ),
            principal_id=_text(raw["principal_id"], "receipt principal_id"),
            role=_text(raw["role"], "receipt role"),
            purpose=_text(raw["purpose"], "receipt purpose"),
            subject_sha256=_sha(raw["subject_sha256"], "receipt subject_sha256"),
            artifact_sha256=_sha(raw["artifact_sha256"], "receipt artifact_sha256"),
        )
        if result.artifact_sha256 != hashlib.sha256(receipt_bytes).hexdigest():
            raise ExecutionBridgeViolation("receipt artifact digest drift")
        return result

    def _claim_payload(self, payload: object) -> ReservationClaimReceipt:
        raw = _closed(payload, _CLAIM_FIELDS, "reservation claim receipt")
        result = ReservationClaimReceipt(
            registry_verified=_boolean(
                raw["registry_verified"], "claim registry_verified"
            ),
            claimed=_boolean(raw["claimed"], "claim claimed"),
            claim_id=_text(raw["claim_id"], "claim_id"),
            reservation_id=_text(raw["reservation_id"], "claim reservation_id"),
            reservation_token_sha256=_sha(
                raw["reservation_token_sha256"], "claim reservation_token_sha256"
            ),
            attempt_epoch=_positive_int(raw["attempt_epoch"], "claim attempt_epoch"),
            cas_epoch=_positive_int(raw["cas_epoch"], "claim cas_epoch"),
            run_id=_text(raw["run_id"], "claim run_id"),
            envelope_sha256=_sha(raw["envelope_sha256"], "claim envelope_sha256"),
            claimant_nonce_sha256=_sha(
                raw["claimant_nonce_sha256"], "claim claimant_nonce_sha256"
            ),
        )
        if result.registry_verified and result.claimed:
            self._claimant_nonces[result.claim_id] = result.claimant_nonce_sha256
        return result

    def _assert_call_binding(
        self,
        reservation: dict[str, object],
        run_id: str,
        envelope_sha256: str,
    ) -> None:
        if (
            reservation != self._admission.workflow_reservation.to_mapping()
            or run_id != self._admission.run_id
            or envelope_sha256 != self._admission.envelope_sha256
        ):
            raise ExecutionBridgeViolation("authority call binding drift")

    def claim(
        self,
        reservation: dict[str, object],
        run_id: str,
        envelope_sha256: str,
        claimant_nonce_sha256: str,
    ) -> ReservationClaimReceipt:
        self._assert_call_binding(reservation, run_id, envelope_sha256)
        nonce = _sha(claimant_nonce_sha256, "claimant_nonce_sha256")
        return self._claim_payload(
            self._request("CLAIM", {"claimant_nonce_sha256": nonce})
        )

    def query_claim(
        self,
        reservation: dict[str, object],
        run_id: str,
        envelope_sha256: str,
        claimant_nonce_sha256: str,
    ) -> ReservationClaimReceipt | None:
        self._assert_call_binding(reservation, run_id, envelope_sha256)
        nonce = _sha(claimant_nonce_sha256, "claimant_nonce_sha256")
        payload = self._request("QUERY_CLAIM", {"claimant_nonce_sha256": nonce})
        return None if payload is None else self._claim_payload(payload)

    def abort_requested(self) -> bool:
        payload = self._request(
            "C7",
            {
                "owner_id": self.owner_id,
                "policy_sha256": self.policy_sha256,
                "correction_epoch": self.correction_epoch,
            },
        )
        raw = _closed(
            payload,
            {
                "abort_requested",
                "owner_id",
                "policy_sha256",
                "correction_epoch",
                "c7_epoch",
            },
            "C7 response",
        )
        if (
            raw["owner_id"] != self.owner_id
            or raw["policy_sha256"] != self.policy_sha256
            or raw["correction_epoch"] != self.correction_epoch
        ):
            raise ExecutionBridgeViolation("C7 response binding drift")
        epoch = _positive_int(raw["c7_epoch"], "c7_epoch")
        if epoch < self._last_c7_epoch:
            raise ExecutionBridgeViolation("C7 epoch regressed")
        abort_requested = _boolean(raw["abort_requested"], "abort_requested")
        if self._last_abort_requested is True and not abort_requested:
            raise ExecutionBridgeViolation("C7 abort cannot be cleared")
        if (
            epoch == self._last_c7_epoch
            and self._last_abort_requested is not None
            and abort_requested != self._last_abort_requested
        ):
            raise ExecutionBridgeViolation("C7 state drift inside one epoch")
        self._last_c7_epoch = epoch
        self._last_abort_requested = abort_requested
        return abort_requested

    def _terminal_payload(self, payload: object) -> ReservationTerminalReceipt:
        raw = _closed(payload, _TERMINAL_FIELDS, "reservation terminal receipt")
        return ReservationTerminalReceipt(
            registry_verified=_boolean(
                raw["registry_verified"], "terminal registry_verified"
            ),
            claim_id=_text(raw["claim_id"], "terminal claim_id"),
            state=_text(raw["state"], "terminal state"),
            terminal_sha256=_sha(raw["terminal_sha256"], "terminal_sha256"),
            terminalized=_boolean(raw["terminalized"], "terminalized"),
        )

    def terminalize(
        self,
        claim: ReservationClaimReceipt,
        state: str,
        terminal_sha256: str,
    ) -> ReservationTerminalReceipt:
        if not isinstance(claim, ReservationClaimReceipt):
            raise ExecutionBridgeViolation("terminal claim must be typed")
        expected = self._admission.workflow_reservation
        if (
            not claim.registry_verified
            or not claim.claimed
            or claim.reservation_id != expected.reservation_id
            or claim.reservation_token_sha256 != expected.reservation_token_sha256
            or claim.attempt_epoch != expected.attempt_epoch
            or claim.cas_epoch != expected.cas_epoch
            or claim.run_id != self._admission.run_id
            or claim.envelope_sha256 != self._admission.envelope_sha256
            or self._claimant_nonces.get(claim.claim_id) != claim.claimant_nonce_sha256
        ):
            raise ExecutionBridgeViolation("terminal claim binding drift")
        return self._terminal_payload(
            self._request(
                "TERMINALIZE",
                {
                    "claim_id": _text(claim.claim_id, "terminal claim_id"),
                    "claimant_nonce_sha256": _sha(
                        claim.claimant_nonce_sha256, "claimant_nonce_sha256"
                    ),
                    "state": _text(state, "terminal state"),
                    "terminal_sha256": _sha(terminal_sha256, "terminal_sha256"),
                },
            )
        )

    def query_terminal(self, claim_id: str) -> ReservationTerminalReceipt | None:
        normalized_claim_id = _text(claim_id, "claim_id")
        claimant_nonce = self._claimant_nonces.get(normalized_claim_id)
        if claimant_nonce is None:
            raise ExecutionBridgeViolation("terminal claim binding is unavailable")
        payload = self._request(
            "QUERY_TERMINAL",
            {
                "claim_id": normalized_claim_id,
                "claimant_nonce_sha256": claimant_nonce,
            },
        )
        return None if payload is None else self._terminal_payload(payload)
