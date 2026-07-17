"""Production subprocess entry point for one admitted R-STATE execution."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from experiments.r_state_credit_1.action_grammar import ALL_ACTIONS
from experiments.r_state_credit_1.actor_interface import ActorRequest
from experiments.r_state_credit_1.execution_bridge import (
    ARK_BASE_URL_PROFILE,
    ARK_CREDENTIAL_ENV_REF,
    ARK_MODEL_SNAPSHOT,
    EXPECTED_PROVIDER_CALLS,
    ExecutionAdmission,
    ExecutionBridge,
    ExecutionBridgeViolation,
    ExecutionReceipt,
    ReceiptKind,
    WorkspaceProbe,
    assert_raw_only,
    canonical_json,
    component_digests,
)
from experiments.r_state_credit_1.recast_provider_actor import (
    ProviderActor,
    ProviderBinding,
    ProviderNotReady,
)
from experiments.r_state_credit_1.unix_authority_client import UnixAuthorityClient


ARK_RESPONSES_URL = f"{ARK_BASE_URL_PROFILE}/responses"
MAX_PROVIDER_RESPONSE_BYTES = 1024 * 1024
MAX_STDOUT_BYTES = 16_384
ARK_ACTION_INSTRUCTION = (
    "Return only one canonical JSON object with exactly the keys action and notes. "
    "Use no markdown, code fence, prefix, suffix, or explanation. action must be one "
    "of the supplied valid_actions; notes must be null or a non-empty string."
)
_HEX = frozenset("0123456789abcdef")
_RAW_TOP_FIELDS = {
    "schema_version",
    "artifact_class",
    "state",
    "run_id",
    "envelope_sha256",
    "run_authorization_receipt_sha256",
    "usage",
    "ordered_provider_receipt_sha256",
    "raw_metrics",
    "rows",
}
_RAW_ROW_FIELDS = {
    "run_id",
    "call_index",
    "episode_id",
    "family",
    "seed",
    "checkpoint_id",
    "arm_id",
    "actor_request_sha256",
    "provider_request_sha256",
    "provider_receipt_id",
    "provider_receipt_sha256",
    "provider_response_sha256",
    "raw_output_sha256",
    "model_revision",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cost_status",
    "cost_amount_microunits",
    "cost_currency",
    "latency_ms",
    "timeout_seconds",
    "action",
    "loss_code",
    "loss_weight",
}
_USAGE_FIELDS = {
    "provider_calls",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cost_status",
    "cost_amount_microunits",
    "cost_currency",
}
_TERMINAL_FIELDS = {
    "schema_version",
    "state",
    "claim_id",
    "reservation_token_sha256",
    "attempt_epoch",
    "cas_epoch",
    "artifact_sha256",
    "run_id",
    "envelope_sha256",
    "row_count",
    "raw_sha256",
}
_TERMINAL_ACK_FIELDS = {
    "schema_version",
    "state",
    "claim_id",
    "terminal_intent_sha256",
    "registry_verified",
}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _closed(value: object, expected: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ExecutionBridgeViolation(f"{label} must use the closed field set")
    return cast(dict[str, object], value)


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX for character in value)
    ):
        raise ExecutionBridgeViolation(f"{label} must be a lowercase SHA-256")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExecutionBridgeViolation(f"{label} must be non-empty text")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ExecutionBridgeViolation(f"{label} must be a non-negative integer")
    return value


def _regular_bytes(path: Path, label: str, maximum: int | None = None) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ExecutionBridgeViolation(f"{label} is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ExecutionBridgeViolation(f"{label} must be a regular non-symlink file")
    if maximum is not None and metadata.st_size > maximum:
        raise ExecutionBridgeViolation(f"{label} exceeds its size limit")
    try:
        encoded = path.read_bytes()
    except OSError as exc:
        raise ExecutionBridgeViolation(f"{label} cannot be read") from exc
    if maximum is not None and len(encoded) > maximum:
        raise ExecutionBridgeViolation(f"{label} exceeds its size limit")
    return encoded


def _canonical_line(path: Path, label: str) -> tuple[bytes, dict[str, object]]:
    encoded = _regular_bytes(path, label)
    try:
        raw = json.loads(encoded)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExecutionBridgeViolation(f"{label} must be JSON") from exc
    if not isinstance(raw, dict) or encoded != (canonical_json(raw) + "\n").encode():
        raise ExecutionBridgeViolation(f"{label} must be canonical JSON plus LF")
    return encoded, cast(dict[str, object], raw)


@dataclass(frozen=True, slots=True)
class ResponsesHttpResponse:
    status: int
    body: bytes

    def __post_init__(self) -> None:
        if (
            not isinstance(self.status, int)
            or isinstance(self.status, bool)
            or not 100 <= self.status <= 599
            or not isinstance(self.body, bytes)
            or len(self.body) > MAX_PROVIDER_RESPONSE_BYTES
        ):
            raise ProviderNotReady("provider HTTP response contract drift")


class ResponsesHttpTransport(Protocol):
    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> ResponsesHttpResponse: ...


class StdlibResponsesHttpTransport:
    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> ResponsesHttpResponse:
        if url != ARK_RESPONSES_URL:
            raise ProviderNotReady("ARK Responses URL drift")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - exact pinned HTTPS URL checked above
                response_body = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
                if len(response_body) > MAX_PROVIDER_RESPONSE_BYTES:
                    raise ProviderNotReady("provider response exceeds 1MiB")
                return ResponsesHttpResponse(int(response.status), response_body)
        except urllib.error.HTTPError as exc:
            exc.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
            raise ProviderNotReady(f"provider HTTP status {exc.code}") from exc
        except (OSError, TimeoutError) as exc:
            raise ProviderNotReady("provider transport failed") from exc


class ArkSixActionTransport:
    """Strict stdlib transport for the immutable six-action Ark snapshot."""

    def __init__(
        self,
        *,
        http_transport: ResponsesHttpTransport | None = None,
        environ: Mapping[str, str] | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ProviderNotReady("provider timeout must be positive")
        self._http = http_transport or StdlibResponsesHttpTransport()
        self._environ = os.environ if environ is None else environ
        self._timeout_seconds = timeout_seconds

    def _request_body(self, request: ActorRequest) -> bytes:
        actor_input = canonical_json(
            {
                "instruction": ARK_ACTION_INSTRUCTION,
                "request": request.to_mapping(),
                "response_contract": {
                    "action": [action.value for action in ALL_ACTIONS],
                    "notes": "null-or-nonempty-string",
                },
            }
        )
        return canonical_json(
            {
                "input": actor_input,
                "max_output_tokens": 256,
                "model": ARK_MODEL_SNAPSHOT,
                "stream": False,
                "temperature": 0,
                "top_p": 1,
            }
        ).encode()

    def complete(self, request: ActorRequest) -> dict[str, object]:
        if (
            not isinstance(request, ActorRequest)
            or request.valid_actions != ALL_ACTIONS
        ):
            raise ProviderNotReady("six-action request contract drift")
        credential = self._environ.get(ARK_CREDENTIAL_ENV_REF)
        if not isinstance(credential, str) or not credential:
            raise ProviderNotReady("ARK_API_KEY is missing")
        request_body = self._request_body(request)
        started = time.monotonic_ns()
        response = self._http.post(
            url=ARK_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {credential}",
                "Content-Type": "application/json",
            },
            body=request_body,
            timeout_seconds=self._timeout_seconds,
        )
        if not 200 <= response.status < 300:
            raise ProviderNotReady("provider did not return HTTP success")
        try:
            payload = json.loads(response.body)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ProviderNotReady("provider response is not JSON") from exc
        top = _closed(
            payload,
            {
                "caching",
                "created_at",
                "id",
                "max_output_tokens",
                "model",
                "object",
                "output",
                "service_tier",
                "status",
                "store",
                "temperature",
                "top_p",
                "usage",
            },
            "provider response",
        )
        if (
            top["model"] != ARK_MODEL_SNAPSHOT
            or top["status"] != "completed"
            or top["object"] != "response"
        ):
            raise ProviderNotReady("provider revision/status drift")
        receipt_id = _text(top["id"], "provider receipt id")
        output = top["output"]
        if not isinstance(output, list) or len(output) != 2:
            raise ProviderNotReady(
                "provider output must contain reasoning then one message"
            )
        reasoning = _closed(
            output[0], {"id", "status", "summary", "type"}, "provider reasoning"
        )
        if (
            reasoning["type"] != "reasoning"
            or reasoning["status"] != "completed"
            or not isinstance(reasoning["summary"], list)
        ):
            raise ProviderNotReady("provider reasoning topology drift")
        message = _closed(
            output[1],
            {"id", "type", "role", "status", "content"},
            "provider message",
        )
        if (
            message["type"] != "message"
            or message["role"] != "assistant"
            or message["status"] != "completed"
        ):
            raise ProviderNotReady("provider message identity/status drift")
        content = message["content"]
        if not isinstance(content, list) or len(content) != 1:
            raise ProviderNotReady("provider message must contain one output_text")
        output_text = _closed(content[0], {"type", "text"}, "provider output_text")
        if output_text["type"] != "output_text" or not isinstance(
            output_text["text"], str
        ):
            raise ProviderNotReady("provider output_text drift")
        try:
            action_payload = json.loads(output_text["text"])
        except json.JSONDecodeError as exc:
            raise ProviderNotReady("provider action output is not JSON") from exc
        action = _closed(action_payload, {"action", "notes"}, "provider action")
        if output_text["text"] != canonical_json(action):
            raise ProviderNotReady("provider action output must be canonical JSON")
        if action["action"] not in {candidate.value for candidate in ALL_ACTIONS}:
            raise ProviderNotReady("provider action is outside six-action grammar")
        notes = action["notes"]
        if notes is not None and (not isinstance(notes, str) or not notes.strip()):
            raise ProviderNotReady("provider notes contract drift")
        if not isinstance(top["usage"], dict):
            raise ProviderNotReady("provider usage schema drift")
        usage_fields = {
            "input_tokens",
            "input_tokens_details",
            "output_tokens",
            "output_tokens_details",
            "total_tokens",
        }
        if set(top["usage"]) not in (usage_fields, usage_fields | {"cost"}):
            raise ProviderNotReady("provider usage schema drift")
        usage = cast(dict[str, object], top["usage"])
        input_tokens = _nonnegative_int(usage["input_tokens"], "input_tokens")
        output_tokens = _nonnegative_int(usage["output_tokens"], "output_tokens")
        if _nonnegative_int(usage["total_tokens"], "total_tokens") != (
            input_tokens + output_tokens
        ):
            raise ProviderNotReady("provider total token usage drift")
        raw_cost = usage.get("cost")
        if raw_cost is None:
            cost_status = "UNAVAILABLE_NOT_GUESSED"
            cost_amount: int | None = None
            cost_currency: str | None = None
        else:
            cost = _closed(
                raw_cost,
                {"status", "amount_microunits", "currency"},
                "provider cost",
            )
            if cost["status"] != "PROVIDER_REPORTED":
                raise ProviderNotReady("provider cost status drift")
            cost_status = "PROVIDER_REPORTED"
            cost_amount = _nonnegative_int(
                cost["amount_microunits"], "provider cost amount"
            )
            cost_currency = _text(cost["currency"], "provider cost currency")
        actor_request_sha256 = _sha256(request.to_canonical_json().encode())
        provider_request_sha256 = _sha256(request_body)
        provider_response_sha256 = _sha256(response.body)
        raw_output_sha256 = _sha256(output_text["text"].encode())
        latency_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
        return {
            "action": action["action"],
            "notes": notes,
            "provider_receipt_id": receipt_id,
            "model_revision": ARK_MODEL_SNAPSHOT,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_status": cost_status,
            "cost_amount_microunits": cost_amount,
            "cost_currency": cost_currency,
            "actor_request_sha256": actor_request_sha256,
            "provider_request_sha256": provider_request_sha256,
            "provider_response_sha256": provider_response_sha256,
            "raw_output_sha256": raw_output_sha256,
            "latency_ms": latency_ms,
            "timeout_seconds": self._timeout_seconds,
        }


class GitWorkspaceProbe:
    """Bind execution to one clean sealed checkout and exact component bytes."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _git(self, *arguments: str) -> str:
        try:
            completed = subprocess.run(
                ["git", *arguments],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ExecutionBridgeViolation("sealed Git workspace check failed") from exc
        return completed.stdout.strip()

    def admit(
        self,
        mechanism_head: str,
        execution_code_head: str,
        expected_components: dict[str, str],
    ) -> str:
        del mechanism_head
        head = self._git("rev-parse", "HEAD")
        if head != execution_code_head:
            raise ExecutionBridgeViolation("sealed checkout HEAD drift")
        if self._git("status", "--porcelain"):
            raise ExecutionBridgeViolation("sealed checkout is dirty")
        if component_digests(self.root) != expected_components:
            raise ExecutionBridgeViolation("sealed checkout component drift")
        return head

    def revalidate(self, anchor_head: str, expected_components: dict[str, str]) -> None:
        if (
            self._git("rev-parse", "HEAD") != anchor_head
            or component_digests(self.root) != expected_components
        ):
            raise ExecutionBridgeViolation("sealed checkout changed during execution")


def _publish_usage_ledger(path: Path, encoded: bytes) -> str:
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise ExecutionBridgeViolation("usage ledger parent is unavailable") from exc
    if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
        raise ExecutionBridgeViolation("usage ledger parent must be a real directory")
    if path.exists() or path.is_symlink():
        raise ExecutionBridgeViolation("usage ledger output already exists")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ExecutionBridgeViolation("usage ledger output cannot be created") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise ExecutionBridgeViolation("usage ledger output write failed") from exc
    return _sha256(encoded)


def validate_and_publish_result(
    *,
    admission: ExecutionAdmission,
    execution_receipt: ExecutionReceipt,
    terminal_intent_path: Path,
    terminal_ack_path: Path,
    usage_ledger_path: Path,
) -> dict[str, object]:
    if usage_ledger_path.exists() or usage_ledger_path.is_symlink():
        raise ExecutionBridgeViolation("usage ledger output already exists")
    raw_bytes = _regular_bytes(execution_receipt.raw_path, "sealed raw result")
    raw_sha256 = _sha256(raw_bytes)
    if raw_sha256 != execution_receipt.raw_sha256:
        raise ExecutionBridgeViolation("raw result digest changed after execution")
    try:
        raw_json = json.loads(raw_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExecutionBridgeViolation("sealed raw result must be JSON") from exc
    if raw_bytes != (canonical_json(raw_json) + "\n").encode():
        raise ExecutionBridgeViolation(
            "sealed raw result must be canonical JSON plus LF"
        )
    raw = _closed(raw_json, _RAW_TOP_FIELDS, "sealed raw result")
    assert_raw_only(raw)
    rows = raw["rows"]
    if not isinstance(rows, list) or len(rows) != EXPECTED_PROVIDER_CALLS:
        raise ExecutionBridgeViolation(
            "sealed raw result must contain exactly 2240 rows"
        )
    if execution_receipt.row_count != EXPECTED_PROVIDER_CALLS:
        raise ExecutionBridgeViolation("execution receipt must bind exactly 2240 rows")
    if (
        raw["schema_version"] != "r-state-credit-1-execution-raw-v1"
        or raw["artifact_class"] != "RAW_EXECUTION"
        or raw["state"] != "SEALED_RAW"
        or raw["run_id"] != admission.run_id
        or raw["envelope_sha256"] != admission.envelope_sha256
        or raw["run_authorization_receipt_sha256"]
        != admission.six_receipt_digests[ReceiptKind.RUN_AUTHORIZATION]
    ):
        raise ExecutionBridgeViolation("sealed raw result binding drift")
    ordered = raw["ordered_provider_receipt_sha256"]
    if not isinstance(ordered, list) or len(ordered) != EXPECTED_PROVIDER_CALLS:
        raise ExecutionBridgeViolation("ordered provider receipt coverage drift")
    usage = _closed(raw["usage"], _USAGE_FIELDS, "sealed raw usage")
    token_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    aggregate_cost_status: str | None = None
    aggregate_cost_amount: int | None = None
    aggregate_cost_currency: str | None = None
    receipt_ids: set[str] = set()
    receipt_digests: set[str] = set()
    ledger_lines: list[bytes] = []
    reservation = admission.workflow_reservation
    for offset, row_value in enumerate(rows):
        row = _closed(row_value, _RAW_ROW_FIELDS, "sealed raw row")
        expected_call_index = offset + 1
        if (
            row["call_index"] != expected_call_index
            or row["run_id"] != admission.run_id
        ):
            raise ExecutionBridgeViolation("sealed raw row order/run drift")
        receipt_id = _text(row["provider_receipt_id"], "provider receipt id")
        receipt_digest = _digest(
            row["provider_receipt_sha256"], "provider receipt digest"
        )
        if receipt_id in receipt_ids or receipt_digest in receipt_digests:
            raise ExecutionBridgeViolation("provider receipts must be globally unique")
        receipt_ids.add(receipt_id)
        receipt_digests.add(receipt_digest)
        if ordered[offset] != receipt_digest:
            raise ExecutionBridgeViolation("ordered provider receipt digest drift")
        if row["model_revision"] != ARK_MODEL_SNAPSHOT:
            raise ExecutionBridgeViolation("provider model revision drift")
        amounts = {
            "input_tokens": _nonnegative_int(row["input_tokens"], "row input_tokens"),
            "output_tokens": _nonnegative_int(
                row["output_tokens"], "row output_tokens"
            ),
            "total_tokens": _nonnegative_int(row["total_tokens"], "row total_tokens"),
        }
        if (
            amounts["total_tokens"]
            != amounts["input_tokens"] + amounts["output_tokens"]
        ):
            raise ExecutionBridgeViolation("sealed raw row total token drift")
        for name, amount in amounts.items():
            token_totals[name] += amount
        cost_status = _text(row["cost_status"], "row cost_status")
        if cost_status not in {"PROVIDER_REPORTED", "UNAVAILABLE_NOT_GUESSED"}:
            raise ExecutionBridgeViolation("sealed raw row cost status drift")
        if aggregate_cost_status is not None and aggregate_cost_status != cost_status:
            raise ExecutionBridgeViolation("mixed provider cost status is forbidden")
        aggregate_cost_status = cost_status
        cost_amount = row["cost_amount_microunits"]
        cost_currency = row["cost_currency"]
        if cost_status == "UNAVAILABLE_NOT_GUESSED":
            if cost_amount is not None or cost_currency is not None:
                raise ExecutionBridgeViolation("unknown provider cost must remain null")
        else:
            amount = _nonnegative_int(cost_amount, "row cost_amount_microunits")
            currency = _text(cost_currency, "row cost_currency")
            if (
                aggregate_cost_currency is not None
                and aggregate_cost_currency != currency
            ):
                raise ExecutionBridgeViolation(
                    "mixed provider cost currency is forbidden"
                )
            aggregate_cost_currency = currency
            aggregate_cost_amount = (aggregate_cost_amount or 0) + amount
        for digest_field in (
            "actor_request_sha256",
            "provider_request_sha256",
            "provider_response_sha256",
            "raw_output_sha256",
        ):
            _digest(row[digest_field], f"row {digest_field}")
        _nonnegative_int(row["latency_ms"], "row latency_ms")
        timeout_seconds = row["timeout_seconds"]
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
        ):
            raise ExecutionBridgeViolation("row timeout_seconds must be positive")
        ledger_row = {
            "call_index": offset,
            "run_id": admission.run_id,
            "reservation_id": reservation.reservation_id,
            "reservation_token_sha256": reservation.reservation_token_sha256,
            "attempt_epoch": reservation.attempt_epoch,
            "cas_epoch": reservation.cas_epoch,
            **amounts,
            "cost_status": cost_status,
            "cost_amount_microunits": cost_amount,
            "cost_currency": cost_currency,
            "provider_receipt_sha256": receipt_digest,
        }
        ledger_lines.append((canonical_json(ledger_row) + "\n").encode())
    expected_usage = {
        "provider_calls": EXPECTED_PROVIDER_CALLS,
        **token_totals,
        "cost_status": aggregate_cost_status,
        "cost_amount_microunits": aggregate_cost_amount,
        "cost_currency": aggregate_cost_currency,
    }
    if usage != expected_usage:
        raise ExecutionBridgeViolation("sealed raw usage aggregate drift")

    terminal_bytes, terminal = _canonical_line(terminal_intent_path, "terminal intent")
    terminal = _closed(terminal, _TERMINAL_FIELDS, "terminal intent")
    if (
        terminal["schema_version"] != "r-state-credit-1-terminal-intent-v1"
        or terminal["state"] != "SEALED_RAW"
        or terminal["run_id"] != admission.run_id
        or terminal["envelope_sha256"] != admission.envelope_sha256
        or terminal["row_count"] != EXPECTED_PROVIDER_CALLS
        or terminal["raw_sha256"] != raw_sha256
        or terminal["artifact_sha256"] != raw_sha256
        or terminal["reservation_token_sha256"] != reservation.reservation_token_sha256
        or terminal["attempt_epoch"] != reservation.attempt_epoch
        or terminal["cas_epoch"] != reservation.cas_epoch
    ):
        raise ExecutionBridgeViolation("terminal intent/raw binding drift")
    _text(terminal["claim_id"], "terminal claim_id")
    _digest(terminal["raw_sha256"], "terminal raw_sha256")
    ack_bytes, ack = _canonical_line(terminal_ack_path, "terminal ack")
    del ack_bytes
    ack = _closed(ack, _TERMINAL_ACK_FIELDS, "terminal ack")
    if (
        ack["schema_version"] != "r-state-credit-1-terminal-ack-v1"
        or ack["state"] != "SEALED_RAW"
        or ack["claim_id"] != terminal["claim_id"]
        or ack["terminal_intent_sha256"] != _sha256(terminal_bytes)
        or ack["registry_verified"] is not True
    ):
        raise ExecutionBridgeViolation("terminal ack binding drift")

    usage_bytes = b"".join(ledger_lines)
    usage_sha256 = _publish_usage_ledger(usage_ledger_path, usage_bytes)
    return {
        "schema_version": "r-state-credit-1-subprocess-result-v1",
        "run_id": admission.run_id,
        "status": "SEALED_RAW_RESULT",
        "raw_result_sha256": raw_sha256,
        "row_count": EXPECTED_PROVIDER_CALLS,
        "provider_calls": EXPECTED_PROVIDER_CALLS,
        "input_tokens": token_totals["input_tokens"],
        "output_tokens": token_totals["output_tokens"],
        "total_tokens": token_totals["total_tokens"],
        "cost_status": aggregate_cost_status,
        "cost_amount_microunits": aggregate_cost_amount,
        "cost_currency": aggregate_cost_currency,
        "usage_ledger_sha256": usage_sha256,
        "reservation_id": reservation.reservation_id,
        "reservation_token_sha256": reservation.reservation_token_sha256,
        "attempt_epoch": reservation.attempt_epoch,
        "cas_epoch": reservation.cas_epoch,
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="r-state-credit-1-execute")
    parser.add_argument("--admission", required=True, type=Path)
    parser.add_argument("--receipt-dir", required=True, type=Path)
    parser.add_argument("--active-manifest", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--authority-socket", required=True, type=Path)
    parser.add_argument("--authority-public-key", required=True, type=Path)
    parser.add_argument("--reservation-token-fd", required=True, type=int)
    parser.add_argument("--usage-ledger", required=True, type=Path)
    parsed = parser.parse_args(tuple(argv))
    if parsed.reservation_token_fd < 3:
        parser.error("--reservation-token-fd must be an inherited non-stdio FD")
    return parsed


def _load_receipts(directory: Path) -> dict[ReceiptKind, bytes]:
    try:
        metadata = directory.lstat()
    except OSError as exc:
        raise ExecutionBridgeViolation("receipt directory is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ExecutionBridgeViolation("receipt directory must be a real directory")
    expected = {f"{kind.value}.json" for kind in ReceiptKind}
    if {entry.name for entry in directory.iterdir()} != expected:
        raise ExecutionBridgeViolation("receipt directory must contain exact six files")
    return {
        kind: _regular_bytes(
            directory / f"{kind.value}.json", f"{kind.value} receipt", 64 * 1024
        )
        for kind in ReceiptKind
    }


def canonical_child_command() -> tuple[str, ...]:
    """Return the actual process command sealed by Workflow authority."""
    original = tuple(sys.orig_argv)
    if len(original) < 2:
        raise ExecutionBridgeViolation("runtime child command is unavailable")
    interpreter = str(Path(original[0]).resolve())
    if interpreter != str(Path(sys.executable).resolve()):
        raise ExecutionBridgeViolation("runtime command interpreter drift")
    return (interpreter, *original[1:])


def _verify_runtime_isolation(admission: ExecutionAdmission) -> None:
    interpreter = Path(sys.executable).resolve()
    binding = admission.isolation_binding
    if binding.interpreter_path != str(interpreter):
        raise ExecutionBridgeViolation("runtime interpreter path drift")
    interpreter_bytes = _regular_bytes(
        interpreter, "runtime interpreter", 1024 * 1024 * 1024
    )
    if _sha256(interpreter_bytes) != binding.interpreter_sha256:
        raise ExecutionBridgeViolation("runtime interpreter digest drift")
    command_sha256 = _sha256(canonical_json(list(canonical_child_command())).encode())
    if command_sha256 != binding.child_command_sha256:
        raise ExecutionBridgeViolation("runtime child command digest drift")


def _production_actor(_: ExecutionAdmission) -> ProviderActor:
    action_digest = _sha256(
        json.dumps(
            [action.value for action in ALL_ACTIONS], separators=(",", ":")
        ).encode()
    )
    return ProviderActor(
        ProviderBinding(
            provider_id="volcengine-ark-agent-plan",
            model_id=ARK_MODEL_SNAPSHOT,
            model_revision=ARK_MODEL_SNAPSHOT,
            revision_confirmed=True,
            transport="API_ONLY",
            action_grammar_sha256=action_digest,
        ),
        ArkSixActionTransport(),
    )


def _execute(
    arguments: argparse.Namespace,
    *,
    actor_factory: Callable[[ExecutionAdmission], ProviderActor] | None,
) -> dict[str, object]:
    root = Path.cwd()
    admission_bytes = _regular_bytes(
        arguments.admission, "execution admission", 1024 * 1024
    )
    admission = ExecutionAdmission.from_canonical_json(admission_bytes)
    _verify_runtime_isolation(admission)
    receipts = _load_receipts(arguments.receipt_dir)
    _regular_bytes(arguments.active_manifest, "active manifest", 8 * 1024 * 1024)
    _regular_bytes(arguments.authority_public_key, "authority public key", 64 * 1024)
    try:
        run_metadata = arguments.run_dir.lstat()
    except OSError as exc:
        raise ExecutionBridgeViolation("run directory is unavailable") from exc
    if stat.S_ISLNK(run_metadata.st_mode) or not stat.S_ISDIR(run_metadata.st_mode):
        raise ExecutionBridgeViolation("run directory must be a real directory")
    if arguments.authority_socket.is_symlink():
        raise ExecutionBridgeViolation("authority socket locator must not be a symlink")
    authority = UnixAuthorityClient(
        admission=admission,
        socket_path=arguments.authority_socket,
        response_public_key_path=arguments.authority_public_key,
        reservation_token_fd=arguments.reservation_token_fd,
    )
    actor = (actor_factory or _production_actor)(admission)
    if not isinstance(actor, ProviderActor):
        raise ExecutionBridgeViolation("actor factory must return ProviderActor")
    bridge = ExecutionBridge(
        root=root,
        active_manifest=arguments.active_manifest,
        run_dir=arguments.run_dir,
        receipt_documents=receipts,
        receipt_verifier=authority,
        workspace_probe=cast(WorkspaceProbe, GitWorkspaceProbe(root)),
        c7=authority,
        actor=actor,
    )
    execution_receipt = bridge.execute(admission)
    return validate_and_publish_result(
        admission=admission,
        execution_receipt=execution_receipt,
        terminal_intent_path=arguments.run_dir / "execution.terminal-intent.json",
        terminal_ack_path=arguments.run_dir / "execution.terminal-ack.json",
        usage_ledger_path=arguments.usage_ledger,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    actor_factory: Callable[[ExecutionAdmission], ProviderActor] | None = None,
) -> int:
    arguments = _parse_args(sys.argv[1:] if argv is None else argv)
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            result = _execute(arguments, actor_factory=actor_factory)
        if captured.getvalue():
            raise ExecutionBridgeViolation("execution dependency wrote forged stdout")
        encoded = (canonical_json(result) + "\n").encode()
        if len(encoded) > MAX_STDOUT_BYTES:
            raise ExecutionBridgeViolation(
                "strict subprocess result exceeds stdout limit"
            )
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
        return 0
    except Exception as exc:
        diagnostic = {
            "error_code": type(exc).__name__,
            "message": str(exc),
            "schema_version": "r-state-credit-1-execution-error-v1",
        }
        sys.stderr.buffer.write((canonical_json(diagnostic) + "\n").encode())
        sys.stderr.buffer.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
