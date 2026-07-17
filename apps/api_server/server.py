from __future__ import annotations

import json
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

from agent_os_contracts import HelpRequest, TaskDraftProposal
from agent_os_core import (
    CandidateConcurrentWrite,
    CandidateEvaluationDenied,
    CandidateEvaluationNotFound,
    CandidateEvaluationScopeMismatch,
    CandidatePromotionDenied,
    CandidatePromotionNotFound,
    CandidatePromotionScopeMismatch,
    CandidateIdempotencyConflict,
    CandidateProvenanceError,
    CandidateScopeMismatch,
    CandidateSealingDenied,
    TaskConfigurationConflict,
    TaskConfigurationDenied,
    TaskConfigurationDrift,
    TaskConfigurationNotBound,
    TaskConfigurationNotFound,
    TaskConfigurationScopeMismatch,
    MandateWorkspaceNotFound,
    MandateWorkspaceConflict,
    MandateWorkspacePersistenceConflict,
    TaskNotFoundError,
)

from .app import AgentOSApplication


INDEX = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
PREVIEW_ZH = Path(__file__).with_name("preview-zh.html").read_bytes()


def _match_situated_proposal(path: str) -> str | None:
    """Return trace_id on exact match, None otherwise.

    Rejects trailing slash, leading extra slash, empty trace, extra segments,
    nonempty query/fragment, and any percent-encoded trace segment at the HTTP
    boundary.
    """
    parsed = urlparse(path)
    if parsed.query or parsed.fragment:
        return None
    raw_path = parsed.path
    prefix = "/api/situated/data-agent-reports/"
    suffix = "/proposal"
    if not raw_path.startswith(prefix) or not raw_path.endswith(suffix):
        return None
    middle = raw_path[len(prefix) : -len(suffix)]
    if not middle or "/" in middle:
        return None
    if "%" in middle:
        return None
    return middle


def _uses_generic_http_idempotency(path: str) -> bool:
    if _match_situated_proposal(path) is not None:
        return False
    parsed_path = urlparse(path).path
    if parsed_path == "/v1/mandates":
        return False
    return not parsed_path.endswith(
        (
            "/domain-candidates:seal",
            "/evaluations:record",
            "/promotions:decide",
            "/configuration-snapshots:seal",
            "/start",
            "/run",
        )
    )


def _error_status(exc: Exception, *, default: int = 400) -> int:
    if isinstance(
        exc,
        (
            CandidateScopeMismatch,
            CandidateSealingDenied,
            CandidateEvaluationDenied,
            CandidateEvaluationScopeMismatch,
            CandidatePromotionDenied,
            CandidatePromotionScopeMismatch,
            TaskConfigurationDenied,
            TaskConfigurationScopeMismatch,
        ),
    ):
        return 403
    if isinstance(
        exc,
        (
            CandidateIdempotencyConflict,
            CandidateConcurrentWrite,
            TaskConfigurationConflict,
            TaskConfigurationDrift,
            TaskConfigurationNotBound,
            MandateWorkspaceConflict,
            MandateWorkspacePersistenceConflict,
        ),
    ):
        return 409
    if isinstance(
        exc,
        (
            TaskNotFoundError,
            CandidateEvaluationNotFound,
            CandidatePromotionNotFound,
            TaskConfigurationNotFound,
            MandateWorkspaceNotFound,
        ),
    ):
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
        if parsed.path == "/v1/mandates":
            self._json(200, {"mandates": self.application.list_mandate_workspace_records()})
            return
        mandate_prefix = "/v1/mandates/"
        if parsed.path.startswith(mandate_prefix) and not parsed.query:
            mandate_id = parsed.path[len(mandate_prefix) :]
            if mandate_id and "/" not in mandate_id:
                try:
                    self._json(200, self.application.get_mandate_workspace_record(mandate_id))
                except Exception as exc:
                    self._json(
                        _error_status(exc, default=404),
                        {"error": type(exc).__name__, "message": str(exc)},
                    )
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
                parts = parsed.path.strip("/").split("/")
                if (
                    len(parts) == 6
                    and parts[:2] == ["v1", "tasks"]
                    and parts[3] == "runs"
                    and parts[5] == "trajectory"
                    and not parsed.query
                    and not parsed.fragment
                ):
                    projection = self.application.project_task_trajectory(
                        parts[2], parts[4]
                    )
                    self._json(200, projection.model_dump(mode="json"))
                    return
                if (
                    len(parts) in {4, 5}
                    and parts[:2] == ["v1", "tasks"]
                    and parts[3] == "configuration-snapshots"
                ):
                    if len(parts) == 4:
                        snapshots = self.application.list_task_configurations(parts[2])
                        self._json(
                            200,
                            {
                                "task_id": parts[2],
                                "configuration_snapshots": [
                                    snapshot.model_dump(mode="json")
                                    for snapshot in snapshots
                                ],
                            },
                        )
                    else:
                        snapshot = self.application.get_task_configuration(
                            parts[2],
                            parts[4],
                        )
                        self._json(200, snapshot.model_dump(mode="json"))
                    return
                if (
                    len(parts) == 6
                    and parts[:2] == ["v1", "tasks"]
                    and parts[3] == "domain-candidates"
                    and parts[5] == "evaluations"
                ):
                    evaluations = self.application.list_domain_candidate_evaluations(
                        parts[2], parts[4]
                    )
                    self._json(
                        200,
                        {
                            "candidate_task_id": parts[2],
                            "candidate_digest": parts[4],
                            "evaluations": [
                                receipt.model_dump(mode="json")
                                for receipt in evaluations
                            ],
                        },
                    )
                    return
                if (
                    len(parts) == 6
                    and parts[:2] == ["v1", "tasks"]
                    and parts[3] == "domain-candidates"
                    and parts[5] in {"promotions", "domain-priors"}
                ):
                    if parts[5] == "promotions":
                        decisions = self.application.list_domain_candidate_promotions(
                            parts[2], parts[4]
                        )
                        self._json(
                            200,
                            {
                                "candidate_task_id": parts[2],
                                "candidate_digest": parts[4],
                                "promotions": [
                                    decision.model_dump(mode="json")
                                    for decision in decisions
                                ],
                            },
                        )
                    else:
                        priors = self.application.list_domain_candidate_priors(
                            parts[2], parts[4]
                        )
                        self._json(
                            200,
                            {
                                "candidate_task_id": parts[2],
                                "candidate_digest": parts[4],
                                "priors": [
                                    prior.model_dump(mode="json") for prior in priors
                                ],
                            },
                        )
                    return
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
            if parsed.path == "/v1/mandates":
                record = self.application.create_mandate_workspace_record(body)
                self._json(201, record)
                return
            parts = parsed.path.strip("/").split("/")
            if (
                len(parts) == 6
                and parts[:2] == ["v1", "tasks"]
                and parts[3] == "domain-candidates"
                and parts[5] == "evaluations:record"
            ):
                receipt = self.application.record_domain_candidate_evaluation(
                    parts[2], parts[4], body
                )
                self._json(201, receipt.model_dump(mode="json"))
                return
            if (
                len(parts) == 6
                and parts[:2] == ["v1", "tasks"]
                and parts[3] == "domain-candidates"
                and parts[5] == "promotions:decide"
            ):
                result = self.application.decide_domain_candidate_promotion(
                    parts[2], parts[4], body
                )
                self._json(201, result.model_dump(mode="json"))
                return
            if (
                len(parts) == 4
                and parts[:2] == ["v1", "tasks"]
                and parts[3] == "domain-candidates:seal"
            ):
                candidate = self.application.seal_domain_candidate(parts[2], body)
                self._json(201, candidate.model_dump(mode="json"))
                return
            if (
                len(parts) == 4
                and parts[:2] == ["v1", "tasks"]
                and parts[3] == "configuration-snapshots:seal"
            ):
                snapshot = self.application.seal_task_configuration(parts[2], body)
                self._json(201, snapshot.model_dump(mode="json"))
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
                configuration_snapshot_id = body.pop(
                    "configuration_snapshot_id",
                    None,
                )
                if configuration_snapshot_id is not None and (
                    not isinstance(configuration_snapshot_id, str)
                    or not configuration_snapshot_id.strip()
                ):
                    raise ValueError(
                        "configuration_snapshot_id must be a non-empty string"
                    )
                forbidden_configuration_fields = {
                    "configuration_snapshot",
                    "configuration_snapshot_digest",
                    "optional_prior",
                    "prior_binding",
                }
                if forbidden_configuration_fields.intersection(body):
                    raise ValueError(
                        "run accepts configuration_snapshot_id only; authoritative "
                        "configuration content is forbidden"
                    )
                task = self.application.run_task(
                    parts[2],
                    body,
                    configuration_snapshot_id=configuration_snapshot_id,
                    recover_stale_lease=recover_stale_lease,
                )
                self._json(200, self.application.task_json(task.task_id))
                return
            if len(parts) == 4 and parts[:2] == ["v1", "tasks"] and parts[3] == "start":
                if set(body) - {"configuration_snapshot_id"}:
                    raise ValueError("start accepts configuration_snapshot_id only")
                configuration_snapshot_id = body.get("configuration_snapshot_id")
                if configuration_snapshot_id is not None and (
                    not isinstance(configuration_snapshot_id, str)
                    or not configuration_snapshot_id.strip()
                ):
                    raise ValueError(
                        "configuration_snapshot_id must be a non-empty string"
                    )
                task = self.application.start_run(
                    parts[2],
                    configuration_snapshot_id,
                )
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
            trace_id = _match_situated_proposal(self.path)
            if trace_id is not None:
                if body != {}:
                    raise ValueError("proposal body must be an empty object")
                result = self.application.observe_admit_and_propose_data_agent_report(
                    trace_id
                )
                if isinstance(result, TaskDraftProposal):
                    serialized = {
                        "outcome_kind": "TASK_DRAFT",
                        "task_draft": result.model_dump(mode="json"),
                    }
                elif isinstance(result, HelpRequest):
                    serialized = {
                        "outcome_kind": "HELP_REQUEST",
                        "help_request": result.model_dump(mode="json"),
                    }
                elif result is None:
                    serialized = {"outcome_kind": "NO_PROPOSAL"}
                else:
                    raise RuntimeError("unexpected proposal result type")
                self._json(200, serialized)
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
