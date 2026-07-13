"""Frozen OpenAI-compatible provider replay server for qualified SPINE evaluations."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator, Mapping

_SCHEMA = "agent-os-provider-call-ledger-v1"
_DUMMY_BEARER = "spine-e2e-1-local-dummy"
_HEX = frozenset("0123456789abcdef")
_LEDGER_FIELDS = {
    "schema_version",
    "ordinal",
    "request_digest",
    "accepted",
    "reason",
    "chain_context_sha256",
    "previous_record_sha256",
    "record_sha256",
}
_REJECTED_REASONS = frozenset(
    {
        "METHOD_NOT_ALLOWED",
        "PATH_NOT_FOUND",
        "UNAUTHORIZED",
        "UNSUPPORTED_MEDIA_TYPE",
        "INVALID_JSON",
        "UNKNOWN_REQUEST_DIGEST",
        "EXPECTED_CALLS_EXCEEDED",
    }
)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_nonfinite(token: str) -> object:
    raise ValueError(f"non-finite JSON number: {token}")


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("value is not canonical JSON") from exc


def request_body_digest(body: Mapping[str, object]) -> str:
    if not isinstance(body, Mapping):
        raise ValueError("request body must be a mapping")
    return hashlib.sha256(_canonical_bytes(dict(body))).hexdigest()


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _HEX for character in value)
    )


def _genesis(context: str) -> str:
    return hashlib.sha256(_SCHEMA.encode() + b"\0" + bytes.fromhex(context)).hexdigest()


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _ledger_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _read_ledger(path: Path, context: str) -> list[dict[str, object]]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    if not raw:
        return []
    if not raw.endswith(b"\n") or raw.startswith(b"\n") or b"\n\n" in raw:
        raise ValueError("invalid ledger framing")
    records: list[dict[str, object]] = []
    previous = _genesis(context)
    for ordinal, line in enumerate(raw.splitlines()):
        try:
            value = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid ledger JSON") from exc
        if not isinstance(value, dict) or set(value) != _LEDGER_FIELDS:
            raise ValueError("non-exact provider ledger schema")
        if (
            value["schema_version"] != _SCHEMA
            or type(value["ordinal"]) is not int
            or value["ordinal"] != ordinal
            or value["chain_context_sha256"] != context
            or value["previous_record_sha256"] != previous
            or type(value["accepted"]) is not bool
            or not isinstance(value["reason"], str)
            or not value["reason"]
            or (value["accepted"] is True) != (value["reason"] == "ACCEPTED")
            or (value["accepted"] is False and value["reason"] not in _REJECTED_REASONS)
            or not _valid_digest(value["request_digest"])
            or not _valid_digest(value["record_sha256"])
        ):
            raise ValueError("invalid provider ledger record")
        unsigned = {key: item for key, item in value.items() if key != "record_sha256"}
        if (
            hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()
            != value["record_sha256"]
        ):
            raise ValueError("provider ledger record digest mismatch")
        previous = value["record_sha256"]
        records.append(value)
    return records


def _append_ledger(path: Path, record: dict[str, object]) -> None:
    data = _canonical_bytes(record) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    created = not path.exists()
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    original_size = os.lseek(descriptor, 0, os.SEEK_END)
    try:
        written = os.write(descriptor, data)
        if written != len(data):
            raise OSError("short durable write")
        os.fsync(descriptor)
    except BaseException:
        os.ftruncate(descriptor, original_size)
        os.fsync(descriptor)
        os.close(descriptor)
        _fsync_parent(path)
        raise
    else:
        os.close(descriptor)
        if created:
            _fsync_parent(path)


class FrozenProviderServer:
    def __init__(
        self,
        bank_path: Path,
        *,
        ledger_path: Path,
        context_sha256: str,
        expected_bearer: str = _DUMMY_BEARER,
    ) -> None:
        if not _valid_digest(context_sha256):
            raise ValueError("invalid context_sha256")
        if not isinstance(expected_bearer, str) or not expected_bearer:
            raise ValueError("invalid expected_bearer")
        self.bank_path = Path(bank_path)
        self.ledger_path = Path(ledger_path)
        self.context_sha256 = context_sha256
        self._expected_bearer = expected_bearer
        self._entries = self._load_bank()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.base_url = ""
        with _ledger_lock(self.ledger_path):
            self._validate_known_ledger(
                _read_ledger(self.ledger_path, self.context_sha256)
            )

    def _load_bank(self) -> dict[str, dict[str, object]]:
        try:
            value = json.loads(
                self.bank_path.read_bytes(), object_pairs_hook=_reject_duplicate_keys
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid provider bank") from exc
        if not isinstance(value, dict) or set(value) != {"entries"}:
            raise ValueError("invalid provider bank schema")
        entries = value["entries"]
        if not isinstance(entries, list) or len(entries) != 12:
            raise ValueError("invalid provider bank entries")
        indexed: dict[str, dict[str, object]] = {}
        case_ids: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "case_id",
                "request",
                "digest",
                "expected_calls",
                "response",
            }:
                raise ValueError("invalid provider bank entry")
            request = entry["request"]
            digest = entry["digest"]
            case_id = entry["case_id"]
            if not isinstance(case_id, str) or not case_id or case_id in case_ids:
                raise ValueError("invalid provider bank case ids")
            if digest in indexed:
                raise ValueError("duplicate request digest")
            if (
                not isinstance(request, dict)
                or request_body_digest(request) != digest
                or type(entry["expected_calls"]) is not int
                or entry["expected_calls"] != 2
            ):
                raise ValueError("invalid provider bank entry")
            self._validate_response(entry["response"], request)
            case_ids.add(case_id)
            indexed[digest] = entry
        return indexed

    @staticmethod
    def _validate_response(response: object, request: dict[str, object]) -> None:
        try:
            if not isinstance(response, dict) or set(response) != {
                "id",
                "model",
                "choices",
                "usage",
            }:
                raise ValueError
            if (
                not isinstance(response["id"], str)
                or not response["id"]
                or response["model"] != request["model"]
            ):
                raise ValueError
            choices = response["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError
            choice = choices[0]
            if not isinstance(choice, dict) or set(choice) != {
                "index",
                "message",
                "finish_reason",
            }:
                raise ValueError
            if (
                type(choice["index"]) is not int
                or choice["index"] != 0
                or choice["finish_reason"] != "tool_calls"
            ):
                raise ValueError
            message = choice["message"]
            if not isinstance(message, dict) or set(message) != {
                "role",
                "content",
                "tool_calls",
            }:
                raise ValueError
            if message["role"] != "assistant" or message["content"] is not None:
                raise ValueError
            tool_calls = message["tool_calls"]
            if not isinstance(tool_calls, list) or len(tool_calls) != 1:
                raise ValueError
            call = tool_calls[0]
            if not isinstance(call, dict) or set(call) != {"id", "type", "function"}:
                raise ValueError
            function = call["function"]
            if (
                not isinstance(call["id"], str)
                or not call["id"]
                or call["type"] != "function"
                or not isinstance(function, dict)
                or set(function) != {"name", "arguments"}
                or function["name"] != "workspace__apply_patch"
                or not isinstance(function["arguments"], str)
            ):
                raise ValueError
            arguments = json.loads(
                function["arguments"],
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite,
            )
            if (
                not isinstance(arguments, dict)
                or set(arguments) != {"path", "content"}
                or arguments["path"] != "subject.py"
                or not isinstance(arguments["content"], str)
            ):
                raise ValueError
            usage = response["usage"]
            if not isinstance(usage, dict) or set(usage) != {
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
            }:
                raise ValueError
            if any(type(usage[key]) is not int or usage[key] < 0 for key in usage):
                raise ValueError
            if (
                usage["total_tokens"]
                != usage["prompt_tokens"] + usage["completion_tokens"]
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("invalid provider response") from exc

    def _validate_known_ledger(self, records: list[dict[str, object]]) -> None:
        counts = {digest: 0 for digest in self._entries}
        for record in records:
            digest = record["request_digest"]
            if record["accepted"]:
                if digest not in counts or record["reason"] != "ACCEPTED":
                    raise ValueError("invalid accepted provider ledger record")
                counts[digest] += 1
                if counts[digest] > self._entries[digest]["expected_calls"]:
                    raise ValueError("accepted provider call count exceeded")

    def start(self) -> None:
        if self._httpd is not None:
            raise ValueError("provider server already started")
        with _ledger_lock(self.ledger_path):
            self._validate_known_ledger(
                _read_ledger(self.ledger_path, self.context_sha256)
            )
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                owner._handle(self)

            def do_GET(self) -> None:
                owner._reject_without_body(self, 405, "METHOD_NOT_ALLOWED")

            do_PUT = do_GET
            do_DELETE = do_GET
            do_PATCH = do_GET
            do_HEAD = do_GET
            do_OPTIONS = do_GET
            do_TRACE = do_GET
            do_CONNECT = do_GET

            def __getattr__(self, name: str) -> object:
                if name.startswith("do_"):
                    return lambda: owner._reject_without_body(
                        self, 405, "METHOD_NOT_ALLOWED"
                    )
                raise AttributeError(name)

            def log_message(self, format: str, *args: object) -> None:
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        host, port = self._httpd.server_address
        self.base_url = f"http://{host}:{port}/v1"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def _read_body(self, handler: BaseHTTPRequestHandler) -> tuple[object, str]:
        try:
            length = int(handler.headers.get("Content-Length", "0"))
            raw = handler.rfile.read(length)
            body = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite,
            )
            if not isinstance(body, dict):
                raise ValueError
            return body, request_body_digest(body)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            digest = hashlib.sha256(raw if "raw" in locals() else b"").hexdigest()
            return None, digest

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        body, digest = self._read_body(handler)
        content_type = handler.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if handler.path != "/v1/chat/completions":
            self._record_and_reply(handler, digest, False, "PATH_NOT_FOUND", 404)
        elif handler.headers.get("Authorization") != f"Bearer {self._expected_bearer}":
            self._record_and_reply(handler, digest, False, "UNAUTHORIZED", 401)
        elif media_type != "application/json":
            self._record_and_reply(
                handler, digest, False, "UNSUPPORTED_MEDIA_TYPE", 415
            )
        elif body is None:
            self._record_and_reply(handler, digest, False, "INVALID_JSON", 400)
        else:
            self._serve_digest(handler, digest)

    def _serve_digest(self, handler: BaseHTTPRequestHandler, digest: str) -> None:
        with _ledger_lock(self.ledger_path):
            records = _read_ledger(self.ledger_path, self.context_sha256)
            self._validate_known_ledger(records)
            entry = self._entries.get(digest)
            if entry is None:
                self._append_and_reply_locked(
                    handler, records, digest, False, "UNKNOWN_REQUEST_DIGEST", 422
                )
                return
            accepted = sum(
                record["accepted"] is True and record["request_digest"] == digest
                for record in records
            )
            if accepted >= entry["expected_calls"]:
                self._append_and_reply_locked(
                    handler, records, digest, False, "EXPECTED_CALLS_EXCEEDED", 409
                )
                return
            self._append_and_reply_locked(
                handler, records, digest, True, "ACCEPTED", 200, entry["response"]
            )

    def _record_and_reply(
        self,
        handler: BaseHTTPRequestHandler,
        digest: str,
        accepted: bool,
        reason: str,
        status: int,
    ) -> None:
        with _ledger_lock(self.ledger_path):
            records = _read_ledger(self.ledger_path, self.context_sha256)
            self._validate_known_ledger(records)
            self._append_and_reply_locked(
                handler, records, digest, accepted, reason, status
            )

    def _append_and_reply_locked(
        self,
        handler: BaseHTTPRequestHandler,
        records: list[dict[str, object]],
        digest: str,
        accepted: bool,
        reason: str,
        status: int,
        payload: object | None = None,
    ) -> None:
        unsigned: dict[str, object] = {
            "schema_version": _SCHEMA,
            "ordinal": len(records),
            "request_digest": digest,
            "accepted": accepted,
            "reason": reason,
            "chain_context_sha256": self.context_sha256,
            "previous_record_sha256": (
                records[-1]["record_sha256"]
                if records
                else _genesis(self.context_sha256)
            ),
        }
        record = {
            **unsigned,
            "record_sha256": hashlib.sha256(_canonical_bytes(unsigned)).hexdigest(),
        }
        try:
            _append_ledger(self.ledger_path, record)
        except OSError:
            self._reply(handler, 500, {"error": "DURABLE_LEDGER_WRITE_FAILED"})
            return
        self._reply(
            handler, status, payload if payload is not None else {"error": reason}
        )

    def _reject_without_body(
        self, handler: BaseHTTPRequestHandler, status: int, reason: str
    ) -> None:
        digest = hashlib.sha256(b"").hexdigest()
        self._record_and_reply(handler, digest, False, reason, status)

    @staticmethod
    def _reply(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
        data = _canonical_bytes(payload)
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    def close(self, *, validate_counts: bool = True) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._httpd = None
            self._thread = None
        if validate_counts:
            with _ledger_lock(self.ledger_path):
                records = _read_ledger(self.ledger_path, self.context_sha256)
                self._validate_known_ledger(records)
                counts = {
                    digest: sum(
                        record["accepted"] is True
                        and record["request_digest"] == digest
                        for record in records
                    )
                    for digest in self._entries
                }
                expected = {
                    digest: entry["expected_calls"]
                    for digest, entry in self._entries.items()
                }
                if counts != expected:
                    raise ValueError("CALL_COUNT_MISMATCH")
