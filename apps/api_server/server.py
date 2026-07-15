from __future__ import annotations

import json
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

from agent_os_core import (
    CandidateConcurrentWrite,
    CandidateIdempotencyConflict,
    CandidateProvenanceError,
    CandidateScopeMismatch,
    CandidateSealingDenied,
    TaskNotFoundError,
)

from .app import AgentOSApplication


INDEX = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
PREVIEW_ZH = Path(__file__).with_name("preview-zh.html").read_bytes()


def _uses_generic_http_idempotency(path: str) -> bool:
    return not urlparse(path).path.endswith("/domain-candidates:seal")


def _error_status(exc: Exception, *, default: int = 400) -> int:
    if isinstance(exc, (CandidateScopeMismatch, CandidateSealingDenied)):
        return 403
    if isinstance(exc, (CandidateIdempotencyConflict, CandidateConcurrentWrite)):
        return 409
    if isinstance(exc, TaskNotFoundError):
        return 404
    if isinstance(exc, (CandidateProvenanceError, ValidationError, ValueError)):
        return 400
    return default


class Handler(BaseHTTPRequestHandler):
    application: AgentOSApplication

    def _json(self, status: int, payload: object) -> None:
        if (
            self.command == "POST"
            and isinstance(payload, dict)
            and _uses_generic_http_idempotency(self.path)
        ):
            key = self.headers.get("Idempotency-Key")
            if key:
                self.application.store.put_idempotency(
                    self.path, key, payload, datetime.now(timezone.utc).isoformat()
                )
        data = json.dumps(payload, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            data = INDEX.encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path == "/preview-zh":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(PREVIEW_ZH)))
            self.end_headers()
            self.wfile.write(PREVIEW_ZH)
            return
        if parsed.path == "/v1/health":
            self._json(200, {"status": "ok", "product": "Agent OS"})
            return
        if parsed.path == "/v1/tasks":
            self._json(200, {"tasks": self.application.list_tasks()})
            return
        if parsed.path == "/v1/workspace":
            self._json(200, self.application.workspace_status())
            return
        if parsed.path == "/v1/provider":
            self._json(200, self.application.provider_status())
            return
        if parsed.path == "/v1/workflows/validate":
            self._json(405, {"error": "method_not_allowed"})
            return
        prefix = "/v1/tasks/"
        if parsed.path.startswith(prefix):
            try:
                task_id = parsed.path[len(prefix) :]
                if task_id.endswith("/domain-candidates"):
                    task_id = task_id.removesuffix("/domain-candidates").rstrip("/")
                    candidates = self.application.list_domain_candidates(task_id)
                    self._json(
                        200,
                        {
                            "task_id": task_id,
                            "candidates": [
                                candidate.model_dump(mode="json")
                                for candidate in candidates
                            ],
                        },
                    )
                    return
                if task_id.endswith("/events"):
                    task_id = task_id[:-7].rstrip("/")
                    events = self.application.store.read(task_id)
                    data = "".join(
                        f"id: {event.sequence}\nevent: {event.event_type.value}\ndata: {json.dumps(event.model_dump(mode='json'))}\n\n"
                        for event in events
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if task_id.endswith("/workflow"):
                    task_id = task_id[:-9].rstrip("/")
                    task = self.application.tasks.get_task(task_id)
                    if task.workflow is None:
                        raise ValueError("task has no workflow")
                    self._json(
                        200,
                        {
                            "workflow": task.workflow.model_dump(mode="json"),
                            "workflow_digest": task.workflow.canonical_digest(),
                        },
                    )
                    return
                if "/artifacts/" in task_id:
                    task_id, artifact_id = task_id.split("/artifacts/", 1)
                    if artifact_id and not artifact_id.startswith("artifact:"):
                        artifact_id = "artifact:" + artifact_id
                    data = self.application.read_artifact(artifact_id)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if task_id.endswith("/evidence"):
                    task_id = task_id[:-9].rstrip("/")
                    self._json(
                        200,
                        {
                            "task_id": task_id,
                            "evidence": self.application.evidence_json(task_id),
                        },
                    )
                    return
                if task_id.endswith("/recovery"):
                    task_id = task_id[:-9].rstrip("/")
                    self._json(200, self.application.recovery_json(task_id))
                    return
                self._json(200, self.application.task_json(task_id))
            except Exception as exc:
                self._json(
                    _error_status(exc, default=404),
                    {"error": type(exc).__name__, "message": str(exc)},
                )
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            key = self.headers.get("Idempotency-Key")
            if key and _uses_generic_http_idempotency(self.path):
                cached = self.application.store.get_idempotency(self.path, key)
                if cached is not None:
                    self._json(200, cached)
                    return
            body = self._body()
            if parsed.path == "/v1/workflows/validate":
                self._json(200, self.application.validate_workflow(body))
                return
            if parsed.path == "/v1/workspace":
                self._json(200, self.application.attach_workspace(body))
                return
            if parsed.path == "/v1/provider":
                self._json(200, self.application.configure_provider(body))
                return
            if parsed.path == "/v1/tasks":
                task = self.application.create_task(body)
                self._json(201, self.application.task_json(task.task_id))
                return
            parts = parsed.path.strip("/").split("/")
            if (
                len(parts) == 4
                and parts[:2] == ["v1", "tasks"]
                and parts[3] == "domain-candidates:seal"
            ):
                candidate = self.application.seal_domain_candidate(parts[2], body)
                self._json(201, candidate.model_dump(mode="json"))
                return
            if (
                len(parts) == 3
                and parts[:2] == ["v1", "tasks"]
                and parts[2].endswith(":commit")
            ):
                task_id = parts[2][:-7]
                task = self.application.commit_task(task_id, body)
                self._json(200, self.application.task_json(task.task_id))
                return
            if len(parts) == 4 and parts[:2] == ["v1", "tasks"] and parts[3] == "run":
                recover_stale_lease = bool(body.pop("recover_stale_lease", False))
                task = self.application.run_task(
                    parts[2], body, recover_stale_lease=recover_stale_lease
                )
                self._json(200, self.application.task_json(task.task_id))
                return
            if len(parts) == 4 and parts[:2] == ["v1", "tasks"] and parts[3] == "start":
                task = self.application.start_run(parts[2])
                self._json(200, self.application.task_json(task.task_id))
                return
            if (
                len(parts) == 4
                and parts[:2] == ["v1", "tasks"]
                and parts[3] == "approval"
            ):
                task = self.application.record_approval(parts[2], body)
                self._json(200, self.application.task_json(task.task_id))
                return
            if (
                len(parts) == 4
                and parts[:2] == ["v1", "tasks"]
                and parts[3] == "signals"
            ):
                task = self.application.signal_task(parts[2], body)
                self._json(200, self.application.task_json(task.task_id))
                return
            if (
                len(parts) == 4
                and parts[:2] == ["v1", "tasks"]
                and parts[3] == "replan"
            ):
                task = self.application.replan_task(parts[2], body)
                self._json(200, self.application.task_json(task.task_id))
                return
            if (
                len(parts) == 4
                and parts[:2] == ["v1", "tasks"]
                and parts[3] == "compensate"
            ):
                task = self.application.compensate_task(parts[2])
                self._json(200, self.application.task_json(task.task_id))
                return
            if (
                len(parts) == 5
                and parts[:2] == ["v1", "tasks"]
                and parts[3:] == ["correction", "resume"]
            ):
                raw_reason = body.get("reason")
                task = self.application.resume_correction(
                    parts[2],
                    raw_reason if isinstance(raw_reason, str) else "",
                )
                self._json(200, self.application.task_json(task.task_id))
                return
            if (
                len(parts) == 4
                and parts[:2] == ["v1", "tasks"]
                and parts[3] in {"pause", "resume", "cancel", "correction"}
            ):
                operation = parts[3]
                if operation == "pause":
                    task = self.application.pause_task(parts[2])
                elif operation == "resume":
                    task = self.application.resume_task(parts[2])
                elif operation == "cancel":
                    task = self.application.cancel_task(parts[2])
                else:
                    raw_reason = body.get("reason")
                    task = self.application.correct_task(
                        parts[2],
                        raw_reason if isinstance(raw_reason, str) else "",
                    )
                self._json(200, self.application.task_json(task.task_id))
                return
            self._json(404, {"error": "not_found"})
        except Exception as exc:
            self._json(
                _error_status(exc),
                {"error": type(exc).__name__, "message": str(exc)},
            )

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(
    application: AgentOSApplication, host: str = "127.0.0.1", port: int = 8787
) -> None:
    handler = type("AgentOSHandler", (Handler,), {"application": application})
    ThreadingHTTPServer((host, port), handler).serve_forever()
