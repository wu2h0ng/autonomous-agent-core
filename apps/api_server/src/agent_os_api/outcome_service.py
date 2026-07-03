"""Framework-agnostic service layer for the Trusted Loop trigger surfaces.

This module is the single source of truth for the two post-/pre-outcome
behaviors that both the CLI and the FastAPI app expose. It deliberately does
NOT import any web framework so the core guarantees (run -> trace, outcome ->
knowledge version bump) are testable without HTTP.

The runtime is injected (``TrustedLoopRuntime`` from OS Core). These functions
only orchestrate calls into the runtime and read back its in-memory stores;
they contain no domain- or transport-specific logic.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
from collections.abc import Mapping
from typing import Any

from agent_os_contracts import (
    CausalAttributionMethod,
    CausalOutcomeAttribution,
    ConnectorExecutionAudit,
    KnowledgeQuery,
    LifecycleState,
    RunTrace,
    TraceEvent,
)
from agent_os_core.agent_runtime import (
    AgentRunContext,
    AgentRuntime,
    AgentToolCall,
    AgentToolResult,
    AgentTraceWriter,
    CheckpointStorePort,
    RuntimePolicyGate,
    ToolRegistry,
    ToolSpec,
)

REPORT_AUDIENCES = {"internal", "external"}
AGENT_RUNTIME_BLOCK_STATUSES = {"denied", "validation_error"}
AGENT_RUNTIME_ERROR_CODES = {
    "tool_error": "AGENT_RUNTIME_TOOL_ERROR",
    "checkpoint_error": "AGENT_RUNTIME_CHECKPOINT_ERROR",
}
AGENT_RUNTIME_ERROR_MESSAGE = "Agent runtime failed before producing a trusted result."
AGENT_RUNTIME_TRACE_PAYLOAD_KEYS = frozenset(
    {"call_id", "tool_name", "run_id", "status", "error_code"}
)
AGENT_RUNTIME_PRE_LOOP_TRACE_STEPS = frozenset(
    {
        "agent_runtime.invocation_started",
        "agent_runtime.policy_allowed",
        "agent_runtime.tool_started",
    }
)
REDACTED_INFRA_FIELDS = [
    "checked_schemas",
    "checked_tables",
    "bound_parameter_names",
    "limit_value",
    "sql_fingerprint",
]
REDACTED_RESULT_FIELDS = [
    "checked_schemas",
    "checked_tables",
    "metric_dimensions",
    "bound_parameter_names",
    "limit_value",
    "sql_fingerprint",
    "columns",
    "preview_rows",
    "chart_fields",
    "metric_values",
]
KNOWLEDGE_ASSET_LIFECYCLE_TRACE_STEPS = frozenset(
    {
        "knowledge_review_decision",
        "knowledge_publish_decision",
        "knowledge_deprecate_decision",
    }
)


def _causal_attribution_to_payload(
    causal_attribution: CausalOutcomeAttribution | None,
) -> dict[str, Any] | None:
    if causal_attribution is None:
        return None
    payload = asdict(causal_attribution)
    payload["method"] = causal_attribution.method.value
    return payload


def _causal_attribution_from_payload(
    payload: CausalOutcomeAttribution | Mapping[str, Any] | None,
) -> CausalOutcomeAttribution | None:
    if payload is None or isinstance(payload, CausalOutcomeAttribution):
        return payload
    values = dict(payload)
    if not isinstance(values.get("method"), CausalAttributionMethod):
        values["method"] = CausalAttributionMethod(values["method"])
    return CausalOutcomeAttribution(**values)


class TrustedLoopCorrectionRuntimeAdapter:
    """Runtime envelope for correction/value-feedback Trusted Loop channels.

    This adapter belongs to the composition layer: it may hold the operator-side
    adoption writer passed by the API factory, while the underlying AgentRuntime
    and TrustedLoopRuntime remain free of adoption-write authority.
    """

    RECORD_OUTCOME_TOOL_NAME = "trusted_loop.record_outcome"
    ATTEST_ADOPTION_TOOL_NAME = "trusted_loop.attest_adoption"

    def __init__(
        self,
        trusted_loop: Any,
        *,
        adoption_ingest: Any | None = None,
        checkpoint_store: CheckpointStorePort | None = None,
        shell_view: Any | None = None,
        trace_writer: AgentTraceWriter | None = None,
    ) -> None:
        self.trusted_loop = trusted_loop
        self.adoption_ingest = adoption_ingest
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name=self.RECORD_OUTCOME_TOOL_NAME,
                description="Record a Trusted Loop self-report outcome without promotion.",
                required_keys=("trace_id", "outcome"),
                risk_level="R1",
                side_effect_class="self_report_feedback",
                required_permissions=("trusted_loop:record_outcome",),
                preserve_result_on_checkpoint_failure=True,
            ),
            self._record_outcome_tool,
        )
        registry.register_tool(
            ToolSpec(
                name=self.ATTEST_ADOPTION_TOOL_NAME,
                description="Attest realized external adoption through the operator value channel.",
                required_keys=("trace_id", "outcome"),
                risk_level="R2",
                side_effect_class="external_value_attestation",
                required_permissions=("trusted_loop:attest_adoption",),
                preserve_result_on_checkpoint_failure=True,
            ),
            self._attest_adoption_tool,
        )
        self.runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(shell_view=shell_view),
            trace_writer=trace_writer,
            checkpoint_store=checkpoint_store,
        )

    def record_outcome(
        self,
        *,
        context: AgentRunContext,
        trace_id: str,
        outcome: str,
        reviewer: str | None = None,
        metric_deltas: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        return self.runtime.invoke_tool(
            AgentToolCall(
                call_id=f"{self.RECORD_OUTCOME_TOOL_NAME}:{context.run_id or context.trace_id}",
                tool_name=self.RECORD_OUTCOME_TOOL_NAME,
                args={
                    "trace_id": trace_id,
                    "outcome": outcome,
                    "reviewer": reviewer,
                    "metric_deltas": metric_deltas,
                },
            ),
            context,
        )

    def attest_adoption(
        self,
        *,
        context: AgentRunContext,
        trace_id: str,
        outcome: str,
        reviewer: str | None = None,
        metric_deltas: dict[str, Any] | None = None,
        causal_attribution: CausalOutcomeAttribution | None = None,
    ) -> AgentToolResult:
        return self.runtime.invoke_tool(
            AgentToolCall(
                call_id=f"{self.ATTEST_ADOPTION_TOOL_NAME}:{context.run_id or context.trace_id}",
                tool_name=self.ATTEST_ADOPTION_TOOL_NAME,
                args={
                    "trace_id": trace_id,
                    "outcome": outcome,
                    "reviewer": reviewer,
                    "metric_deltas": metric_deltas,
                    "causal_attribution": _causal_attribution_to_payload(causal_attribution),
                },
            ),
            context,
        )

    def _record_outcome_tool(
        self,
        *,
        trace_id: str,
        outcome: str,
        reviewer: str | None = None,
        metric_deltas: dict[str, Any] | None = None,
        context: AgentRunContext,
    ) -> dict[str, Any]:
        del context
        return record_outcome_service(
            self.trusted_loop,
            trace_id=trace_id,
            outcome=outcome,
            reviewer=reviewer,
            metric_deltas=metric_deltas,
        )

    def _attest_adoption_tool(
        self,
        *,
        trace_id: str,
        outcome: str,
        reviewer: str | None = None,
        metric_deltas: dict[str, Any] | None = None,
        causal_attribution: CausalOutcomeAttribution | Mapping[str, Any] | None = None,
        context: AgentRunContext,
    ) -> dict[str, Any]:
        del context
        if self.adoption_ingest is None:
            raise RuntimeError("adoption value channel is not configured")
        return attest_adoption_service(
            self.trusted_loop,
            self.adoption_ingest,
            trace_id=trace_id,
            outcome=outcome,
            reviewer=reviewer,
            metric_deltas=metric_deltas,
            causal_attribution=_causal_attribution_from_payload(causal_attribution),
        )


class InMemoryReportSnapshotStore:
    """Run-local report snapshot store for side-effect-free read projections.

    The Trusted Loop remains the only path that builds evidence. This store only
    keeps already-built user-facing report artifacts so HTTP clients can fetch an
    existing result without re-running SQL, creating approvals, or touching action
    connectors. It is deliberately same-process memory; durable cross-instance
    report reads are provided only by the configured persistence-backed report
    snapshot store.
    """

    def __init__(self) -> None:
        self._by_trace: dict[str, dict[str, dict[str, Any]]] = {}

    def save(self, trace_id: str, snapshots_by_audience: dict[str, dict[str, Any]]) -> None:
        self._by_trace[trace_id] = {
            audience: deepcopy(snapshot)
            for audience, snapshot in snapshots_by_audience.items()
            if audience in REPORT_AUDIENCES
        }

    def get(self, trace_id: str, audience: str) -> dict[str, Any] | None:
        snapshots = self._by_trace.get(trace_id)
        if snapshots is None:
            return None
        snapshot = snapshots.get(audience)
        return deepcopy(snapshot) if snapshot is not None else None


def _preview_rows(rows: tuple[dict[str, Any], ...], *, limit: int = 20) -> list[dict[str, Any]]:
    return [dict(row) for row in rows[:limit]]


def _columns(rows: tuple[dict[str, Any], ...]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for name in row:
            if name not in columns:
                columns.append(name)
    return columns


def _safe_agent_runtime_message(agent_result: Any) -> str:
    return agent_result.error_message or "Agent runtime refused the request."


def _safe_agent_runtime_trace_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {
        key: payload[key]
        for key in sorted(AGENT_RUNTIME_TRACE_PAYLOAD_KEYS)
        if key in payload and payload[key] is not None
    }


def _safe_agent_runtime_events(
    *,
    trace_id: str,
    agent_runtime_adapter: Any,
    knowledge_context_refs: tuple[str, ...] = (),
) -> list[TraceEvent]:
    adapter_runtime = getattr(agent_runtime_adapter, "runtime", None)
    trace_writer = getattr(adapter_runtime, "trace_writer", None)
    raw_events = getattr(trace_writer, "events", ())
    events: list[TraceEvent] = []
    for event in raw_events:
        if (
            not isinstance(event, dict)
            or not isinstance(event.get("step"), str)
            or not event["step"].startswith("agent_runtime.")
        ):
            continue
        payload = _safe_agent_runtime_trace_payload(event.get("payload"))
        if event["step"] == "agent_runtime.tool_succeeded" and knowledge_context_refs:
            payload["knowledge_context_refs"] = list(knowledge_context_refs)
        events.append(TraceEvent(trace_id=trace_id, step=event["step"], payload=payload))
    return events


def _persist_agent_runtime_success_trace(
    runtime: Any,
    *,
    trace_id: str,
    agent_runtime_adapter: Any,
) -> None:
    trace_store = getattr(runtime, "trace_store", None)
    if trace_store is None:
        return
    existing = trace_store.get(trace_id)
    if existing is None:
        return
    runtime_events = _safe_agent_runtime_events(
        trace_id=trace_id,
        agent_runtime_adapter=agent_runtime_adapter,
    )
    if not runtime_events:
        return

    pre_loop_events = tuple(
        event for event in runtime_events if event.step in AGENT_RUNTIME_PRE_LOOP_TRACE_STEPS
    )
    post_loop_events = tuple(
        event for event in runtime_events if event.step not in AGENT_RUNTIME_PRE_LOOP_TRACE_STEPS
    )
    trace_store.save(replace(existing, events=pre_loop_events + existing.events + post_loop_events))


def _persist_agent_runtime_appended_trace(
    runtime: Any,
    *,
    trace_id: str,
    agent_runtime_adapter: Any,
    knowledge_context_refs: tuple[str, ...] = (),
) -> None:
    trace_store = getattr(runtime, "trace_store", None)
    if trace_store is None:
        return
    runtime_events = tuple(
        _safe_agent_runtime_events(
            trace_id=trace_id,
            agent_runtime_adapter=agent_runtime_adapter,
            knowledge_context_refs=knowledge_context_refs,
        )
    )
    if not runtime_events:
        return
    existing = trace_store.get(trace_id)
    if existing is None:
        trace_store.save(RunTrace(trace_id=trace_id, status="ok", events=runtime_events))
        return
    trace_store.save(replace(existing, events=existing.events + runtime_events))


def _knowledge_context_refs_from_output(output: Any) -> tuple[str, ...]:
    if not isinstance(output, dict):
        return ()
    refs = output.get("knowledge_context_refs")
    if not isinstance(refs, list):
        return ()
    return tuple(ref for ref in refs if isinstance(ref, str))


def _persist_agent_runtime_terminal_trace(
    runtime: Any,
    *,
    agent_result: Any,
    agent_context: Any,
    status: str,
    block_message: str | None = None,
) -> None:
    trace_store = getattr(runtime, "trace_store", None)
    if trace_store is None:
        return
    trace_id = agent_result.trace_id or agent_context.trace_id
    event_step = {
        "denied": "agent_runtime.policy_denied",
        "validation_error": "agent_runtime.validation_failed",
        "tool_error": "agent_runtime.tool_failed",
        "checkpoint_error": "agent_runtime.checkpoint_failed",
    }.get(agent_result.status, "agent_runtime.failed")
    events = [
        TraceEvent(
            trace_id=trace_id,
            step=event_step,
            payload={
                "call_id": agent_result.call_id,
                "tool_name": agent_result.tool_name,
                "error_code": agent_result.error_code,
            },
        )
    ]
    if status == "blocked":
        events.append(
            TraceEvent(
                trace_id=trace_id,
                step="blocked",
                payload={
                    "code": agent_result.error_code or agent_result.status,
                    "stage": "agent_runtime",
                    "message": block_message or "Agent runtime refused the request.",
                },
            )
        )
    existing = trace_store.get(trace_id)
    if existing is not None:
        trace_store.save(replace(existing, events=existing.events + tuple(events)))
        return
    trace_store.save(RunTrace(trace_id=trace_id, status=status, events=tuple(events)))


def _primary_metric_value(rows: tuple[dict[str, Any], ...], metric_name: str) -> Any | None:
    if not rows:
        return None
    first = rows[0]
    if metric_name in first:
        return first[metric_name]
    if (
        "value" in first
        and isinstance(first["value"], (int, float))
        and not isinstance(first["value"], bool)
    ):
        return first["value"]
    for value in first.values():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def _chart_fields(
    rows: tuple[dict[str, Any], ...],
    columns: list[str],
    dimensions: tuple[str, ...],
    metric_name: str,
) -> tuple[str, str] | None:
    if not rows:
        return None
    sample = rows[0]
    x_field = next((dimension for dimension in dimensions if dimension in columns), None)
    if x_field is None:
        x_field = next(
            (
                column
                for column in columns
                if not isinstance(sample.get(column), (int, float))
                or isinstance(sample.get(column), bool)
            ),
            None,
        )
    numeric_fields = [
        column
        for column in columns
        if isinstance(sample.get(column), (int, float)) and not isinstance(sample.get(column), bool)
    ]
    if not x_field or not numeric_fields:
        return None
    if metric_name in numeric_fields:
        y_field = metric_name
    elif "value" in numeric_fields:
        y_field = "value"
    else:
        y_field = numeric_fields[0]
    return x_field, y_field


def _business_action_status(proposal: Any, action_result: dict[str, Any]) -> str:
    status = action_result.get("status")
    if not proposal.approval_required and status in {"pending_approval", "awaiting_approval", None}:
        return "proposed"
    return status or "proposed"


def _execution_audit_from_event(event: dict[str, Any]) -> dict[str, Any]:
    """Project connector execution semantics without claiming external exactly-once."""
    return ConnectorExecutionAudit.from_event(event).to_dict()


def _sql_fingerprint(sql: str) -> str:
    return "sha256:" + hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _normalize_report_audience(audience: str) -> str:
    if audience not in REPORT_AUDIENCES:
        raise ValueError(f"Unsupported report audience: {audience}")
    return audience


def _redaction_summary(metric: Any, audience: str) -> dict[str, Any]:
    """Return the audience projection policy for a grounded result.

    ``audience`` is the primary gate. ``data_classification`` only controls how
    much metric data remains visible after the audience ceiling is applied.
    External public projections may show public metric values, dimensions, and
    previews, but still strip physical source/SQL infrastructure.
    """
    data_classification = metric.data_classification.value
    if audience != "external":
        redacted_fields: list[str] = []
        reason = None
    elif data_classification == "public":
        redacted_fields = list(REDACTED_INFRA_FIELDS)
        reason = "external audience cannot view source or SQL infrastructure"
    else:
        redacted_fields = list(REDACTED_RESULT_FIELDS)
        reason = "external audience cannot view non-public result details"
    return {
        "audience": audience,
        "applied": bool(redacted_fields),
        "data_classification": data_classification,
        "redacted_fields": redacted_fields,
        "reason": reason,
    }


def _redacts(redaction: dict[str, Any], field: str) -> bool:
    return field in set(redaction["redacted_fields"])


def _report_evidence_cards(
    evidence: Any,
    columns: list[str],
    *,
    preview_row_count: int,
    redaction: dict[str, Any],
) -> list[dict[str, Any]]:
    metric = evidence.metric_contract
    safety = evidence.sql_safety
    hide_dimensions = _redacts(redaction, "metric_dimensions")
    hide_columns = _redacts(redaction, "columns")
    hide_preview_rows = _redacts(redaction, "preview_rows")
    hide_checked_schemas = _redacts(redaction, "checked_schemas")
    hide_checked_tables = _redacts(redaction, "checked_tables")
    hide_bound_parameter_names = _redacts(redaction, "bound_parameter_names")
    hide_limit_value = _redacts(redaction, "limit_value")
    hide_sql_fingerprint = _redacts(redaction, "sql_fingerprint")
    sql_redacted_fields = [field for field in REDACTED_INFRA_FIELDS if _redacts(redaction, field)]
    return [
        {
            "card_id": "metric_contract",
            "type": "metric_contract",
            "title": f"{metric.display_name} metric contract",
            "evidence_chain_id": evidence.evidence_chain_id,
            "trace_id": evidence.trace_id,
            "derived_from": ["EvidenceChain.metric_contract"],
            "redacted_fields": ["dimensions"] if hide_dimensions else [],
            "metric_name": metric.metric_name,
            "metric_version": metric.version,
            "display_name": metric.display_name,
            "owner": metric.owner,
            "unit": metric.unit,
            "dimensions": [] if hide_dimensions else list(metric.dimensions),
            "data_classification": metric.data_classification.value,
        },
        {
            "card_id": "sql_safety",
            "type": "sql_safety",
            "title": "SQL safety and source boundary",
            "evidence_chain_id": evidence.evidence_chain_id,
            "trace_id": evidence.trace_id,
            "derived_from": ["EvidenceChain.query_plan", "EvidenceChain.sql_safety"],
            "redacted_fields": sql_redacted_fields,
            "query_metric_name": evidence.query_plan.metric_name,
            "sql_safety_allowed": safety.allowed,
            "checked_schemas": [] if hide_checked_schemas else list(safety.checked_schemas),
            "checked_tables": [] if hide_checked_tables else list(safety.checked_tables),
            "bound_parameter_names": (
                [] if hide_bound_parameter_names else list(safety.bound_parameters)
            ),
            "limit_value": None if hide_limit_value else safety.limit_value,
            "sql_fingerprint": (
                None if hide_sql_fingerprint else _sql_fingerprint(evidence.query_plan.sql)
            ),
        },
        {
            "card_id": "query_result",
            "type": "query_result",
            "title": "Grounded query result",
            "evidence_chain_id": evidence.evidence_chain_id,
            "trace_id": evidence.trace_id,
            "derived_from": ["EvidenceChain.query_result"],
            "redacted_fields": [
                field for field in ["columns", "preview_rows"] if _redacts(redaction, field)
            ],
            "row_count": evidence.query_result.row_count,
            "columns": [] if hide_columns else columns,
            "preview_row_count": 0 if hide_preview_rows else preview_row_count,
        },
    ]


def _knowledge_context_rationale(result: Any, *, audience: str) -> list[dict[str, Any]]:
    if audience == "external":
        return []
    proposal_refs = set(getattr(result.action_proposal, "knowledge_context_refs", ()))
    rationale: list[dict[str, Any]] = []
    for related in getattr(result, "related_knowledge", ()):
        asset_id = related.asset.asset_id
        if asset_id not in proposal_refs:
            continue
        score_breakdown = dict(getattr(related, "score_breakdown", {}) or {})
        context_quality_boost = float(score_breakdown.get("context_quality_boost") or 0.0)
        reason_code = (
            "prior_outcome_or_adoption_context"
            if context_quality_boost > 0.0
            else "retrieved_reviewed_context"
        )
        rationale.append(
            {
                "asset_id": asset_id,
                "score": float(related.score),
                "context_quality_boost": context_quality_boost,
                "reason_code": reason_code,
            }
        )
    return rationale


def _build_user_result_artifact(result: Any, *, audience: str = "internal") -> dict[str, Any]:
    """Build the user-facing data-agent result bundle from grounded runtime output.

    This is deliberately a read-side projection over ``TrustedLoopResult``: it
    does not query data, choose actions, or execute connectors. The data path and
    governance decisions remain owned by the Trusted Loop; this layer only
    packages them into analysis/report/dashboard/action surfaces a client can
    render directly.
    """
    evidence = result.evidence_chain
    proposal = result.action_proposal
    action_result = result.action_result or {}
    rows = evidence.query_result.rows
    trace_id = evidence.trace_id
    metric = evidence.metric_contract
    audience = _normalize_report_audience(audience)
    redaction = _redaction_summary(metric, audience)
    knowledge_context_refs = (
        [] if audience == "external" else list(getattr(proposal, "knowledge_context_refs", ()))
    )
    hide_columns = _redacts(redaction, "columns")
    hide_preview_rows = _redacts(redaction, "preview_rows")
    hide_chart_fields = _redacts(redaction, "chart_fields")
    hide_metric_values = _redacts(redaction, "metric_values")
    preview = _preview_rows(rows)
    columns = _columns(rows)
    visible_preview = [] if hide_preview_rows else preview
    visible_columns = [] if hide_columns else columns
    metric_value = None if hide_metric_values else _primary_metric_value(rows, metric.metric_name)
    chart_fields = (
        None
        if hide_chart_fields
        else _chart_fields(rows, columns, metric.dimensions, metric.metric_name)
    )
    widgets = [
        {
            "widget_id": "primary_metric",
            "type": "kpi",
            "title": metric.display_name,
            "value": metric_value,
            "unit": metric.unit,
            "row_count": None,
            "columns": [],
            "preview_rows": [],
            "x_field": None,
            "y_field": None,
            "evidence_chain_id": evidence.evidence_chain_id,
            "redacted_fields": ["value"] if hide_metric_values else [],
        },
    ]
    if chart_fields is not None:
        x_field, y_field = chart_fields
        widgets.append(
            {
                "widget_id": "metric_trend",
                "type": "line_chart",
                "title": f"{metric.display_name} trend",
                "row_count": evidence.query_result.row_count,
                "columns": visible_columns,
                "preview_rows": visible_preview,
                "x_field": x_field,
                "y_field": y_field,
                "evidence_chain_id": evidence.evidence_chain_id,
                "redacted_fields": [],
            }
        )
    widgets.append(
        {
            "widget_id": "result_rows",
            "type": "table",
            "title": "Result rows",
            "row_count": evidence.query_result.row_count,
            "columns": visible_columns,
            "preview_rows": visible_preview,
            "x_field": None,
            "y_field": None,
            "evidence_chain_id": evidence.evidence_chain_id,
            "redacted_fields": [
                field for field in ["columns", "preview_rows"] if _redacts(redaction, field)
            ],
        }
    )

    return {
        "artifact_id": f"artifact-{trace_id}-{audience}",
        "kind": "data_agent_result",
        "title": f"{metric.display_name} analysis result",
        "trace_id": trace_id,
        "evidence_chain_id": evidence.evidence_chain_id,
        "action_proposal_id": proposal.proposal_id,
        "question": evidence.intent.question,
        "metric_name": metric.metric_name,
        "audience": audience,
        "redaction": redaction,
        "analysis": {
            "summary": evidence.conclusion,
            "confidence": evidence.confidence,
            "limitations": list(evidence.limitations),
            "row_count": evidence.query_result.row_count,
            "evidence_chain_id": evidence.evidence_chain_id,
        },
        "report": {
            "title": f"{metric.display_name} evidence-backed report",
            "evidence_cards": _report_evidence_cards(
                evidence,
                columns,
                preview_row_count=len(preview),
                redaction=redaction,
            ),
            "sections": [
                {
                    "heading": "Finding",
                    "body": evidence.conclusion,
                    "items": [],
                },
                {
                    "heading": "Evidence",
                    "body": (
                        f"Metric contract {metric.metric_name} "
                        f"({metric.version}) produced {evidence.query_result.row_count} row(s)."
                    ),
                    "items": [
                        f"trace_id={trace_id}",
                        f"evidence_chain_id={evidence.evidence_chain_id}",
                        f"provider_sql_safety_allowed={evidence.sql_safety.allowed}",
                    ],
                },
                {
                    "heading": "Limitations",
                    "body": None,
                    "items": list(evidence.limitations),
                },
            ],
        },
        "dashboard": {
            "title": f"{metric.display_name} dashboard",
            "widgets": widgets,
        },
        "decision": {
            "recommendation": proposal.recommended_action,
            "reason": proposal.reason,
            "expected_impact": proposal.expected_impact,
            "risk_level": proposal.risk_level.value,
            "approval_required": proposal.approval_required,
            "approver_role": proposal.approver_role,
            "action_proposal_id": proposal.proposal_id,
            "confidence": evidence.confidence,
            "knowledge_context_refs": knowledge_context_refs,
            "knowledge_context_rationale": _knowledge_context_rationale(
                result,
                audience=audience,
            ),
        },
        "business_action": {
            "connector_name": proposal.connector_name,
            "action_type": proposal.action_type,
            "risk_level": proposal.risk_level.value,
            "approval_required": proposal.approval_required,
            "approver_role": proposal.approver_role,
            "status": _business_action_status(proposal, action_result),
            "operation_id": action_result.get("operation_id"),
            "approval_id": action_result.get("approval_id"),
            "evidence_chain_id": evidence.evidence_chain_id,
            "trace_id": trace_id,
            "row_count": evidence.query_result.row_count,
        },
    }


def search_service(
    retriever: Any,
    *,
    text: str,
    metric_name: str | None = None,
    owner: str | None = None,
    k: int = 5,
) -> dict[str, Any]:
    """Search the knowledge memory and return JSON-able, explainable results.

    The real entry point for the KnowledgeRetriever capability (used by the CLI
    ``search`` subcommand). Each result carries its score breakdown (the "why").
    """
    results = retriever.search(KnowledgeQuery(text=text, metric_name=metric_name, owner=owner, k=k))
    return {
        "results": [
            {
                "asset_id": r.asset.asset_id,
                "title": r.asset.title,
                "score": r.score,
                "score_breakdown": r.score_breakdown,
            }
            for r in results
        ]
    }


def run_service(
    runtime: Any,
    *,
    question: str,
    parameters: dict[str, Any],
    audience: str = "internal",
    agent_runtime_adapter: Any | None = None,
    agent_context: Any | None = None,
    report_store: Any | None = None,
) -> dict[str, Any]:
    """Run the Trusted Loop for ``question`` and return a JSON-able summary.

    The ``trace_id`` is taken from ``result.evidence_chain.trace_id`` so callers
    can later attach an outcome to the same trace via :func:`record_outcome_service`.

    Returns ``{"status": "ok", ...}`` on success, or ``{"status": "blocked",
    "block": {...}}`` for an expected business block (unsafe SQL, unknown metric,
    no template, no provider) — a unified, JSON-able failure contract.
    """
    if agent_runtime_adapter is None:
        outcome = runtime.evaluate(question, parameters)
    else:
        if agent_context is None:
            raise ValueError("agent_context is required when agent_runtime_adapter is provided.")
        agent_result = agent_runtime_adapter.evaluate(
            context=agent_context,
            question=question,
            parameters=parameters,
        )
        if agent_result.status != "ok":
            trace_id = agent_result.trace_id or agent_context.trace_id
            if agent_result.status not in AGENT_RUNTIME_BLOCK_STATUSES:
                error_code = AGENT_RUNTIME_ERROR_CODES.get(
                    agent_result.status, "AGENT_RUNTIME_ERROR"
                )
                _persist_agent_runtime_terminal_trace(
                    runtime,
                    agent_result=agent_result,
                    agent_context=agent_context,
                    status="error",
                )
                return {
                    "status": "error",
                    "error": {
                        "code": error_code,
                        "message": AGENT_RUNTIME_ERROR_MESSAGE,
                        "stage": "agent_runtime",
                        "trace_id": trace_id,
                    },
                }
            message = _safe_agent_runtime_message(agent_result)
            _persist_agent_runtime_terminal_trace(
                runtime,
                agent_result=agent_result,
                agent_context=agent_context,
                status="blocked",
                block_message=message,
            )
            return {
                "status": "blocked",
                "block": {
                    "code": agent_result.error_code or agent_result.status,
                    "message": message,
                    "stage": "agent_runtime",
                    "details": [],
                    "trace_id": trace_id,
                },
            }
        outcome = agent_result.output

    if outcome.blocked:
        block = outcome.block
        return {
            "status": "blocked",
            "block": {
                "code": block.code.value,
                "message": block.message,
                "stage": block.stage,
                "details": list(block.details),
                # Refusals are auditable too (AR-20260611): the persisted RunTrace id.
                "trace_id": block.trace_id,
            },
        }

    result = outcome.result
    trace_id = result.evidence_chain.trace_id
    if agent_runtime_adapter is not None:
        _persist_agent_runtime_success_trace(
            runtime,
            trace_id=trace_id,
            agent_runtime_adapter=agent_runtime_adapter,
        )
    asset = runtime.knowledge_store.get_by_trace(trace_id)
    internal_user_result = _build_user_result_artifact(result, audience="internal")
    external_user_result = _build_user_result_artifact(result, audience="external")
    audience = _normalize_report_audience(audience)
    selected_user_result = external_user_result if audience == "external" else internal_user_result
    if report_store is not None:
        report_store.save(
            trace_id,
            {
                "internal": {
                    "trace_id": trace_id,
                    "audience": "internal",
                    "user_result": internal_user_result,
                },
                "external": {
                    "trace_id": trace_id,
                    "audience": "external",
                    "user_result": external_user_result,
                },
            },
        )

    return {
        "status": "ok",
        "trace_id": trace_id,
        "intent": result.intent.metric_name,
        "provider_id": (result.provider_contract.provider_id if result.provider_contract else None),
        "evidence_chain_id": result.evidence_chain.evidence_chain_id,
        "action_proposal_id": result.action_proposal.proposal_id,
        "row_count": result.evidence_chain.query_result.row_count,
        "trace_steps": [event.step for event in result.trace_events],
        "knowledge_asset_id": asset.asset_id if asset is not None else None,
        "knowledge_version": runtime.knowledge_store.version_of(trace_id),
        # Read-side of the learning loop (AR-20260611): prior knowledge recalled
        # for this question, surfaced as advisory, explainable context.
        "related_knowledge": [
            {"asset_id": r.asset.asset_id, "title": r.asset.title, "score": r.score}
            for r in result.related_knowledge
        ],
        "user_result": selected_user_result,
    }


def report_snapshot_service(
    report_store: Any,
    *,
    trace_id: str,
    audience: str = "internal",
) -> dict[str, Any] | None:
    """Return an already-built report projection without re-entering the loop."""
    audience = _normalize_report_audience(audience)
    return report_store.get(trace_id, audience)


def trace_service(trace_store: Any, *, trace_id: str) -> dict[str, Any] | None:
    """Fetch the persisted RunTrace for ``trace_id`` (observability v1, AR-20260611).

    Takes the ``TraceStorePort`` directly (HTTP passes ``runtime.trace_store``;
    the CLI builds a standalone store) and returns a JSON-able dict, or ``None``
    when no run with that trace_id was persisted — the caller decides the
    transport-level not-found shape.
    """
    run_trace = trace_store.get(trace_id)
    if run_trace is None:
        return None
    return {
        "trace_id": run_trace.trace_id,
        "status": run_trace.status,
        "events": [{"step": e.step, "payload": e.payload} for e in run_trace.events],
        "telemetry": [
            {
                "dimension": t.dimension.value,
                "name": t.name,
                "value": t.value,
                "unit": t.unit,
                "attributes": t.attributes,
            }
            for t in run_trace.telemetry_events
        ],
    }


def approve_and_execute_service(
    runtime: Any,
    *,
    approval_id: str,
    reason: str | None = None,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Approve and execute an approval-bound operation by approval id.

    This is the user-facing action execution surface for same-process runtimes:
    the caller supplies only the approval id and an optional reason. The runtime
    owns the pending operation context and still enforces approval status,
    operation fingerprint, SQL Safety, and EvidenceChain completeness before any
    connector write.
    """
    approval, operation_trace = runtime.approve_and_execute_pending_operation(
        approval_id=approval_id,
        reason=reason,
        approved_by=approved_by,
    )
    return approval_execution_response_payload(approval, operation_trace)


def approval_execution_response_payload(approval: Any, operation_trace: Any) -> dict[str, Any]:
    """Project approval execution contracts into the stable HTTP/CLI response shape."""
    final_event = operation_trace.events[-1] if operation_trace.events else {}
    return {
        "approval_id": approval.approval_id,
        "approval_status": approval.status,
        "approved_by": approval.approved_by,
        "proposal_id": operation_trace.proposal_id,
        "operation_trace_id": operation_trace.trace_id,
        "operation_id": operation_trace.operation_id,
        "state": operation_trace.state.value,
        "evidence_chain_id": operation_trace.evidence_chain_id,
        "connector_name": final_event.get("connector_name"),
        "action_type": final_event.get("action_type"),
        "action_result_status": final_event.get("status"),
        "idempotency_key": final_event.get("idempotency_key"),
        "execution_audit": _execution_audit_from_event(dict(final_event)),
        "events": [dict(event) for event in operation_trace.events],
    }


def _knowledge_context_refs_for_trace(runtime: Any, trace_id: str) -> list[str]:
    trace_store = getattr(runtime, "trace_store", None)
    persisted_trace = trace_store.get(trace_id) if trace_store is not None else None
    if persisted_trace is None:
        return []
    for event in reversed(persisted_trace.events):
        if event.step != "action_proposal":
            continue
        refs = event.payload.get("knowledge_context_refs")
        if not isinstance(refs, list):
            return []
        return [ref for ref in refs if isinstance(ref, str)]
    return []


def _knowledge_asset_lifecycle_event_count(
    persisted_trace: RunTrace | None,
    *,
    asset_id: str,
) -> int:
    if persisted_trace is None:
        return 0
    return sum(
        1
        for event in persisted_trace.events
        if event.step in KNOWLEDGE_ASSET_LIFECYCLE_TRACE_STEPS
        and event.payload.get("asset_id") == asset_id
    )


def _knowledge_asset_latest_lifecycle_event_summary(
    persisted_trace: RunTrace | None,
    *,
    asset_id: str,
) -> dict[str, Any] | None:
    if persisted_trace is None:
        return None
    for event in reversed(persisted_trace.events):
        if event.step not in KNOWLEDGE_ASSET_LIFECYCLE_TRACE_STEPS:
            continue
        payload = event.payload
        if payload.get("asset_id") != asset_id:
            continue
        return {
            "trace_id": event.trace_id,
            "step": event.step,
            "asset_id": payload.get("asset_id"),
            "action": payload.get("action"),
            "previous_state": payload.get("previous_state"),
            "state": payload.get("state"),
            "knowledge_version": payload.get("knowledge_version"),
            "reason_present": bool(payload.get("reason_present")),
        }
    return None


def _knowledge_asset_usage_event_projection(
    event: TraceEvent,
    *,
    asset_id: str,
    include_tool_name: bool,
) -> dict[str, Any] | None:
    payload = event.payload
    refs = payload.get("knowledge_context_refs")
    if not isinstance(refs, list) or asset_id not in refs:
        return None
    safe_refs = [ref for ref in refs if isinstance(ref, str)]
    if event.step == "action_proposal":
        usage_kind = "proposal_context"
        tool_name = None
    elif event.step == "agent_runtime.tool_succeeded":
        usage_kind = "correction_context"
        tool_name = payload.get("tool_name")
        if tool_name not in {
            TrustedLoopCorrectionRuntimeAdapter.RECORD_OUTCOME_TOOL_NAME,
            TrustedLoopCorrectionRuntimeAdapter.ATTEST_ADOPTION_TOOL_NAME,
        }:
            return None
    else:
        return None

    projected = {
        "trace_id": event.trace_id,
        "step": event.step,
        "usage_kind": usage_kind,
        "asset_id": asset_id,
        "knowledge_context_refs": safe_refs,
    }
    if include_tool_name:
        projected["tool_name"] = tool_name
    return projected


def _knowledge_asset_latest_usage_event_summary(
    runtime: Any,
    *,
    asset_id: str,
) -> dict[str, Any] | None:
    trace_store = getattr(runtime, "trace_store", None)
    all_traces = getattr(trace_store, "all_traces", None)
    traces = all_traces() if callable(all_traces) else ()

    latest: dict[str, Any] | None = None
    for run_trace in traces:
        for event in run_trace.events:
            projected = _knowledge_asset_usage_event_projection(
                event,
                asset_id=asset_id,
                include_tool_name=False,
            )
            if projected is not None:
                latest = projected
    return latest


def record_outcome_service(
    runtime: Any,
    *,
    trace_id: str,
    outcome: str,
    reviewer: str | None = None,
    metric_deltas: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a runtime SELF-REPORT for ``trace_id`` (observation only).

    Delegates to ``runtime.record_outcome`` (which builds+stores a self-report
    ``FeedbackEvent``). P5.1b (ADR-0001 / AR-20260614): a self-report does NOT
    promote knowledge — ``knowledge_version`` is reported unchanged. Value-driven
    promotion requires realized external value via :func:`attest_adoption_service`.

    For an unknown trace the feedback is still recorded, but no knowledge asset
    is fabricated: ``knowledge_asset_id`` is ``None`` and ``knowledge_version``
    is ``0``.
    """
    feedback = runtime.record_outcome(
        trace_id=trace_id,
        outcome=outcome,
        reviewer=reviewer,
        metric_deltas=metric_deltas,
    )
    asset = runtime.knowledge_store.get_by_trace(trace_id)

    return {
        "feedback_id": feedback.feedback_id,
        "trace_id": trace_id,
        "outcome": outcome,
        "reviewer": reviewer,
        "knowledge_asset_id": asset.asset_id if asset is not None else None,
        "knowledge_version": runtime.knowledge_store.version_of(trace_id),
        "knowledge_context_refs": _knowledge_context_refs_for_trace(runtime, trace_id),
    }


def knowledge_review_queue_service(runtime: Any) -> dict[str, Any]:
    """Return DRAFT KnowledgeAsset candidates awaiting human review.

    P1-05 starts as a read-only queue over the existing Trusted Loop knowledge
    store. It must not create assets, promote versions, or infer realized value.
    """
    items: list[dict[str, Any]] = []
    for asset in runtime.knowledge_store.all_assets():
        if asset.state.value != "draft":
            continue
        source_trace_id = asset.source_trace_id
        items.append(
            {
                "asset_id": asset.asset_id,
                "title": asset.title,
                "asset_type": asset.asset_type,
                "source_trace_id": source_trace_id,
                "owner": asset.owner,
                "state": asset.state.value,
                "outcome": asset.outcome,
                "result_weight": asset.result_weight,
                "knowledge_version": (
                    runtime.knowledge_store.version_of(source_trace_id)
                    if source_trace_id is not None
                    else 0
                ),
            }
        )

    return {
        "status": "ok",
        "review_state": "draft",
        "count": len(items),
        "items": items,
    }


def knowledge_asset_catalog_service(
    runtime: Any,
    *,
    lifecycle_state: str | None = None,
    quality_status: str | None = None,
    review_priority: str | None = None,
    recommended_review_action: str | None = None,
    review_rationale_code: str | None = None,
    order_by: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Return an internal, read-only KnowledgeAsset lifecycle catalog.

    The catalog is an operator visibility surface over existing assets. It must
    not create assets, mutate lifecycle state, promote value, or expose anything
    through external report principals.
    """
    normalized_state = lifecycle_state.strip().lower() if lifecycle_state else None
    if normalized_state in {None, ""}:
        allowed_states = {LifecycleState.ACTIVE, LifecycleState.PUBLISHED}
        catalog_state = "active,published"
    elif normalized_state == "all":
        allowed_states = None
        catalog_state = "all"
    else:
        try:
            requested = LifecycleState(normalized_state)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported KnowledgeAsset lifecycle filter: {lifecycle_state}"
            ) from exc
        allowed_states = {requested}
        catalog_state = requested.value

    quality_status_filter = _normalize_knowledge_asset_quality_status_filter(quality_status)
    review_priority_filter = _normalize_knowledge_asset_review_priority_filter(review_priority)
    recommended_review_action_filter = _normalize_knowledge_asset_recommended_action_filter(
        recommended_review_action
    )
    review_rationale_code_filter = _normalize_knowledge_asset_review_rationale_code_filter(
        review_rationale_code
    )
    order_by_filter = _normalize_knowledge_asset_catalog_order_by(order_by)
    limit_filter = _normalize_knowledge_asset_quality_summary_limit(limit)
    offset_filter = _normalize_knowledge_asset_quality_summary_offset(offset)

    items: list[dict[str, Any]] = []
    for asset in runtime.knowledge_store.all_assets():
        if allowed_states is not None and asset.state not in allowed_states:
            continue
        source_trace_id = asset.source_trace_id
        quality = knowledge_asset_decision_quality_service(runtime, asset_id=asset.asset_id)
        quality_status = _knowledge_asset_quality_status(quality)
        derived_review_priority = _KNOWLEDGE_ASSET_REVIEW_PRIORITY_BY_STATUS[quality_status]
        derived_recommended_action = _KNOWLEDGE_ASSET_RECOMMENDED_ACTION_BY_STATUS[quality_status]
        derived_review_rationale_codes = list(
            _KNOWLEDGE_ASSET_REVIEW_RATIONALE_CODES_BY_STATUS[quality_status]
        )
        if quality_status_filter is not None and quality_status != quality_status_filter:
            continue
        if review_priority_filter is not None and derived_review_priority != review_priority_filter:
            continue
        if (
            recommended_review_action_filter is not None
            and derived_recommended_action != recommended_review_action_filter
        ):
            continue
        if (
            review_rationale_code_filter is not None
            and review_rationale_code_filter not in derived_review_rationale_codes
        ):
            continue
        trace_store = getattr(runtime, "trace_store", None)
        persisted_trace = (
            trace_store.get(source_trace_id) if trace_store and source_trace_id else None
        )
        items.append(
            {
                "asset_id": asset.asset_id,
                "title": asset.title,
                "asset_type": asset.asset_type,
                "source_trace_id": source_trace_id,
                "owner": asset.owner,
                "state": asset.state.value,
                "outcome": asset.outcome,
                "result_weight": asset.result_weight,
                "knowledge_version": (
                    runtime.knowledge_store.version_of(source_trace_id)
                    if source_trace_id is not None
                    else 0
                ),
                "lifecycle_event_count": _knowledge_asset_lifecycle_event_count(
                    persisted_trace,
                    asset_id=asset.asset_id,
                ),
                "latest_lifecycle_event": _knowledge_asset_latest_lifecycle_event_summary(
                    persisted_trace,
                    asset_id=asset.asset_id,
                ),
                "latest_usage_event": _knowledge_asset_latest_usage_event_summary(
                    runtime,
                    asset_id=asset.asset_id,
                ),
                "proposal_usage_count": quality["proposal_usage_count"],
                "correction_usage_count": quality["correction_usage_count"],
                "outcome_correction_count": quality["outcome_correction_count"],
                "adoption_correction_count": quality["adoption_correction_count"],
                "distinct_usage_trace_count": quality["distinct_usage_trace_count"],
                "quality_status": quality_status,
                "review_priority": derived_review_priority,
                "recommended_review_action": derived_recommended_action,
                "review_rationale_codes": derived_review_rationale_codes,
            }
        )

    if order_by_filter == "quality_status":
        items.sort(
            key=lambda item: (
                _KNOWLEDGE_ASSET_QUALITY_STATUS_ORDER[item["quality_status"]],
                item["asset_id"],
                item["source_trace_id"] or "",
            )
        )
    elif order_by_filter == "recommended_review_action":
        items.sort(
            key=lambda item: (
                _KNOWLEDGE_ASSET_RECOMMENDED_ACTION_ORDER[item["recommended_review_action"]],
                item["asset_id"],
                item["source_trace_id"] or "",
            )
        )
    elif order_by_filter == "review_priority":
        items.sort(
            key=lambda item: (
                _KNOWLEDGE_ASSET_REVIEW_PRIORITY_ORDER[item["review_priority"]],
                item["asset_id"],
                item["source_trace_id"] or "",
            )
        )
    elif order_by_filter == "review_rationale_code":
        items.sort(
            key=lambda item: (
                min(
                    _KNOWLEDGE_ASSET_REVIEW_RATIONALE_CODE_ORDER[code]
                    for code in item["review_rationale_codes"]
                ),
                item["asset_id"],
                item["source_trace_id"] or "",
            )
        )

    total_count = len(items)
    if limit_filter is None:
        page_items = items[offset_filter:]
    else:
        page_items = items[offset_filter : offset_filter + limit_filter]

    return {
        "status": "ok",
        "catalog_state": catalog_state,
        "quality_status_filter": quality_status_filter,
        "review_priority_filter": review_priority_filter,
        "recommended_review_action_filter": recommended_review_action_filter,
        "review_rationale_code_filter": review_rationale_code_filter,
        "order_by": order_by_filter,
        "limit": limit_filter,
        "offset": offset_filter,
        "total_count": total_count,
        "has_more": offset_filter + len(page_items) < total_count,
        "quality_status_counts": _knowledge_asset_quality_summary_counts(
            page_items,
            field="quality_status",
            allowed_values=[
                "unused",
                "proposal_only",
                "outcome_observed",
                "adoption_observed",
            ],
        ),
        "review_priority_counts": _knowledge_asset_quality_summary_counts(
            page_items,
            field="review_priority",
            allowed_values=["high", "medium", "low"],
        ),
        "recommended_review_action_counts": _knowledge_asset_quality_summary_counts(
            page_items,
            field="recommended_review_action",
            allowed_values=[
                "review_or_reject",
                "collect_outcome_feedback",
                "monitor_for_adoption",
                "consider_publish",
            ],
        ),
        "review_rationale_code_counts": _knowledge_asset_quality_summary_rationale_counts(
            page_items
        ),
        "count": len(page_items),
        "items": page_items,
    }


def knowledge_asset_detail_service(
    runtime: Any,
    *,
    asset_id: str,
) -> dict[str, Any]:
    """Return safe, read-only metadata for a single KnowledgeAsset."""
    target = None
    for asset in runtime.knowledge_store.all_assets():
        if asset.asset_id == asset_id:
            target = asset
            break

    if target is None:
        raise KeyError(asset_id)

    source_trace_id = target.source_trace_id
    trace_store = getattr(runtime, "trace_store", None)
    persisted_trace = trace_store.get(source_trace_id) if trace_store and source_trace_id else None
    quality = knowledge_asset_decision_quality_service(runtime, asset_id=target.asset_id)
    quality_status = _knowledge_asset_quality_status(quality)
    return {
        "status": "ok",
        "asset_id": target.asset_id,
        "title": target.title,
        "asset_type": target.asset_type,
        "source_trace_id": source_trace_id,
        "owner": target.owner,
        "state": target.state.value,
        "outcome": target.outcome,
        "result_weight": target.result_weight,
        "knowledge_version": (
            runtime.knowledge_store.version_of(source_trace_id)
            if source_trace_id is not None
            else 0
        ),
        "has_source_trace": persisted_trace is not None,
        "lifecycle_event_count": _knowledge_asset_lifecycle_event_count(
            persisted_trace,
            asset_id=target.asset_id,
        ),
        "latest_lifecycle_event": _knowledge_asset_latest_lifecycle_event_summary(
            persisted_trace,
            asset_id=target.asset_id,
        ),
        "latest_usage_event": _knowledge_asset_latest_usage_event_summary(
            runtime,
            asset_id=target.asset_id,
        ),
        "proposal_usage_count": quality["proposal_usage_count"],
        "correction_usage_count": quality["correction_usage_count"],
        "outcome_correction_count": quality["outcome_correction_count"],
        "adoption_correction_count": quality["adoption_correction_count"],
        "distinct_usage_trace_count": quality["distinct_usage_trace_count"],
        "quality_status": quality_status,
        "review_priority": _KNOWLEDGE_ASSET_REVIEW_PRIORITY_BY_STATUS[quality_status],
        "recommended_review_action": _KNOWLEDGE_ASSET_RECOMMENDED_ACTION_BY_STATUS[quality_status],
        "review_rationale_codes": list(
            _KNOWLEDGE_ASSET_REVIEW_RATIONALE_CODES_BY_STATUS[quality_status]
        ),
    }


def knowledge_asset_lifecycle_events_service(
    runtime: Any,
    *,
    asset_id: str,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Return safe, read-only lifecycle audit events for a KnowledgeAsset."""
    limit_filter = _normalize_knowledge_asset_quality_summary_limit(limit)
    offset_filter = _normalize_knowledge_asset_quality_summary_offset(offset)
    target = None
    for asset in runtime.knowledge_store.all_assets():
        if asset.asset_id == asset_id:
            target = asset
            break

    if target is None:
        raise KeyError(asset_id)

    source_trace_id = target.source_trace_id
    trace_store = getattr(runtime, "trace_store", None)
    persisted_trace = trace_store.get(source_trace_id) if trace_store and source_trace_id else None
    if persisted_trace is None:
        return {
            "status": "ok",
            "asset_id": target.asset_id,
            "source_trace_id": source_trace_id,
            "has_source_trace": False,
            "count": 0,
            "total_count": 0,
            "has_more": False,
            "limit": limit_filter,
            "offset": offset_filter,
            "events": [],
        }

    projected_events: list[dict[str, Any]] = []
    for event in persisted_trace.events:
        if event.step not in KNOWLEDGE_ASSET_LIFECYCLE_TRACE_STEPS:
            continue
        payload = event.payload
        if payload.get("asset_id") != target.asset_id:
            continue
        projected_events.append(
            {
                "trace_id": event.trace_id,
                "step": event.step,
                "asset_id": payload.get("asset_id"),
                "action": payload.get("action"),
                "previous_state": payload.get("previous_state"),
                "state": payload.get("state"),
                "reviewer": payload.get("reviewer"),
                "knowledge_version": payload.get("knowledge_version"),
                "reason_present": bool(payload.get("reason_present")),
            }
        )

    total_count = len(projected_events)
    if limit_filter is None:
        page_events = projected_events[offset_filter:]
    else:
        page_events = projected_events[offset_filter : offset_filter + limit_filter]

    return {
        "status": "ok",
        "asset_id": target.asset_id,
        "source_trace_id": source_trace_id,
        "has_source_trace": True,
        "count": len(page_events),
        "total_count": total_count,
        "has_more": offset_filter + len(page_events) < total_count,
        "limit": limit_filter,
        "offset": offset_filter,
        "events": page_events,
    }


def knowledge_asset_usage_events_service(
    runtime: Any,
    *,
    asset_id: str,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Return safe, read-only usage audit events for a KnowledgeAsset."""
    limit_filter = _normalize_knowledge_asset_quality_summary_limit(limit)
    offset_filter = _normalize_knowledge_asset_quality_summary_offset(offset)
    target = None
    for asset in runtime.knowledge_store.all_assets():
        if asset.asset_id == asset_id:
            target = asset
            break

    if target is None:
        raise KeyError(asset_id)

    trace_store = getattr(runtime, "trace_store", None)
    all_traces = getattr(trace_store, "all_traces", None)
    traces = all_traces() if callable(all_traces) else ()

    projected_events: list[dict[str, Any]] = []
    for run_trace in traces:
        for event in run_trace.events:
            projected = _knowledge_asset_usage_event_projection(
                event,
                asset_id=asset_id,
                include_tool_name=True,
            )
            if projected is None:
                continue
            projected_events.append(projected)

    total_count = len(projected_events)
    if limit_filter is None:
        page_events = projected_events[offset_filter:]
    else:
        page_events = projected_events[offset_filter : offset_filter + limit_filter]

    return {
        "status": "ok",
        "asset_id": target.asset_id,
        "source_trace_id": target.source_trace_id,
        "count": len(page_events),
        "total_count": total_count,
        "has_more": offset_filter + len(page_events) < total_count,
        "limit": limit_filter,
        "offset": offset_filter,
        "events": page_events,
    }


def knowledge_asset_decision_quality_service(
    runtime: Any,
    *,
    asset_id: str,
) -> dict[str, Any]:
    """Return a safe aggregate of downstream decision-quality usage signals."""
    target = None
    for asset in runtime.knowledge_store.all_assets():
        if asset.asset_id == asset_id:
            target = asset
            break

    if target is None:
        raise KeyError(asset_id)

    trace_store = getattr(runtime, "trace_store", None)
    all_traces = getattr(trace_store, "all_traces", None)
    traces = all_traces() if callable(all_traces) else ()

    proposal_usage_count = 0
    correction_usage_count = 0
    outcome_correction_count = 0
    adoption_correction_count = 0
    usage_trace_ids: list[str] = []
    seen_trace_ids: set[str] = set()

    for run_trace in traces:
        for event in run_trace.events:
            payload = event.payload
            refs = payload.get("knowledge_context_refs")
            if not isinstance(refs, list) or asset_id not in refs:
                continue

            if event.step == "action_proposal":
                proposal_usage_count += 1
            elif event.step == "agent_runtime.tool_succeeded":
                tool_name = payload.get("tool_name")
                if tool_name == TrustedLoopCorrectionRuntimeAdapter.RECORD_OUTCOME_TOOL_NAME:
                    correction_usage_count += 1
                    outcome_correction_count += 1
                elif tool_name == TrustedLoopCorrectionRuntimeAdapter.ATTEST_ADOPTION_TOOL_NAME:
                    correction_usage_count += 1
                    adoption_correction_count += 1
                else:
                    continue
            else:
                continue

            if event.trace_id not in seen_trace_ids:
                seen_trace_ids.add(event.trace_id)
                usage_trace_ids.append(event.trace_id)

    return {
        "status": "ok",
        "asset_id": target.asset_id,
        "source_trace_id": target.source_trace_id,
        "proposal_usage_count": proposal_usage_count,
        "correction_usage_count": correction_usage_count,
        "outcome_correction_count": outcome_correction_count,
        "adoption_correction_count": adoption_correction_count,
        "distinct_usage_trace_count": len(usage_trace_ids),
        "usage_trace_ids": usage_trace_ids,
    }


def _knowledge_asset_quality_status(summary: dict[str, Any]) -> str:
    if summary["adoption_correction_count"] > 0:
        return "adoption_observed"
    if summary["outcome_correction_count"] > 0:
        return "outcome_observed"
    if summary["proposal_usage_count"] > 0:
        return "proposal_only"
    return "unused"


_KNOWLEDGE_ASSET_QUALITY_STATUSES = {
    "unused",
    "proposal_only",
    "outcome_observed",
    "adoption_observed",
}

_KNOWLEDGE_ASSET_REVIEW_PRIORITY_BY_STATUS = {
    "unused": "high",
    "proposal_only": "medium",
    "outcome_observed": "medium",
    "adoption_observed": "high",
}

_KNOWLEDGE_ASSET_RECOMMENDED_ACTION_BY_STATUS = {
    "unused": "review_or_reject",
    "proposal_only": "collect_outcome_feedback",
    "outcome_observed": "monitor_for_adoption",
    "adoption_observed": "consider_publish",
}
_KNOWLEDGE_ASSET_REVIEW_RATIONALE_CODES_BY_STATUS = {
    "unused": ("unused_context_candidate",),
    "proposal_only": ("proposal_context_needs_outcome",),
    "outcome_observed": ("outcome_supported_context",),
    "adoption_observed": ("adoption_supported_context",),
}

_KNOWLEDGE_ASSET_REVIEW_PRIORITIES = set(_KNOWLEDGE_ASSET_REVIEW_PRIORITY_BY_STATUS.values())
_KNOWLEDGE_ASSET_RECOMMENDED_ACTIONS = set(_KNOWLEDGE_ASSET_RECOMMENDED_ACTION_BY_STATUS.values())
_KNOWLEDGE_ASSET_REVIEW_RATIONALE_CODES = {
    code for codes in _KNOWLEDGE_ASSET_REVIEW_RATIONALE_CODES_BY_STATUS.values() for code in codes
}
_KNOWLEDGE_ASSET_CATALOG_ORDER_BY = {
    "quality_status",
    "recommended_review_action",
    "review_priority",
    "review_rationale_code",
}
_KNOWLEDGE_ASSET_QUALITY_SUMMARY_ORDER_BY = {"review_priority"}
_KNOWLEDGE_ASSET_QUALITY_SUMMARY_MAX_LIMIT = 100
_KNOWLEDGE_ASSET_QUALITY_STATUS_ORDER = {
    "unused": 0,
    "proposal_only": 1,
    "outcome_observed": 2,
    "adoption_observed": 3,
}
_KNOWLEDGE_ASSET_REVIEW_PRIORITY_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
}
_KNOWLEDGE_ASSET_RECOMMENDED_ACTION_ORDER = {
    "review_or_reject": 0,
    "collect_outcome_feedback": 1,
    "monitor_for_adoption": 2,
    "consider_publish": 3,
}
_KNOWLEDGE_ASSET_REVIEW_RATIONALE_CODE_ORDER = {
    "unused_context_candidate": 0,
    "proposal_context_needs_outcome": 1,
    "outcome_supported_context": 2,
    "adoption_supported_context": 3,
}


def _normalize_knowledge_asset_quality_status_filter(quality_status: str | None) -> str | None:
    if quality_status is None:
        return None
    normalized = quality_status.strip().lower()
    if normalized not in _KNOWLEDGE_ASSET_QUALITY_STATUSES:
        allowed = ", ".join(sorted(_KNOWLEDGE_ASSET_QUALITY_STATUSES))
        raise ValueError(f"Unsupported quality_status filter: {quality_status}. Allowed: {allowed}")
    return normalized


def _normalize_knowledge_asset_review_priority_filter(review_priority: str | None) -> str | None:
    if review_priority is None:
        return None
    normalized = review_priority.strip().lower()
    if normalized not in _KNOWLEDGE_ASSET_REVIEW_PRIORITIES:
        allowed = ", ".join(sorted(_KNOWLEDGE_ASSET_REVIEW_PRIORITIES))
        raise ValueError(
            f"Unsupported review_priority filter: {review_priority}. Allowed: {allowed}"
        )
    return normalized


def _normalize_knowledge_asset_recommended_action_filter(
    recommended_review_action: str | None,
) -> str | None:
    if recommended_review_action is None:
        return None
    normalized = recommended_review_action.strip().lower()
    if normalized not in _KNOWLEDGE_ASSET_RECOMMENDED_ACTIONS:
        allowed = ", ".join(sorted(_KNOWLEDGE_ASSET_RECOMMENDED_ACTIONS))
        raise ValueError(
            "Unsupported recommended_review_action filter: "
            f"{recommended_review_action}. Allowed: {allowed}"
        )
    return normalized


def _normalize_knowledge_asset_review_rationale_code_filter(
    review_rationale_code: str | None,
) -> str | None:
    if review_rationale_code is None:
        return None
    normalized = review_rationale_code.strip().lower()
    if normalized not in _KNOWLEDGE_ASSET_REVIEW_RATIONALE_CODES:
        allowed = ", ".join(sorted(_KNOWLEDGE_ASSET_REVIEW_RATIONALE_CODES))
        raise ValueError(
            f"Unsupported review_rationale_code filter: {review_rationale_code}. Allowed: {allowed}"
        )
    return normalized


def _normalize_knowledge_asset_catalog_order_by(order_by: str | None) -> str | None:
    if order_by is None:
        return None
    normalized = order_by.strip().lower()
    if normalized not in _KNOWLEDGE_ASSET_CATALOG_ORDER_BY:
        allowed = ", ".join(sorted(_KNOWLEDGE_ASSET_CATALOG_ORDER_BY))
        raise ValueError(f"Unsupported order_by: {order_by}. Allowed: {allowed}")
    return normalized


def _normalize_knowledge_asset_quality_summary_order_by(order_by: str | None) -> str | None:
    if order_by is None:
        return None
    normalized = order_by.strip().lower()
    if normalized not in _KNOWLEDGE_ASSET_QUALITY_SUMMARY_ORDER_BY:
        allowed = ", ".join(sorted(_KNOWLEDGE_ASSET_QUALITY_SUMMARY_ORDER_BY))
        raise ValueError(f"Unsupported order_by: {order_by}. Allowed: {allowed}")
    return normalized


def _normalize_knowledge_asset_quality_summary_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    if limit < 1 or limit > _KNOWLEDGE_ASSET_QUALITY_SUMMARY_MAX_LIMIT:
        raise ValueError(
            "Unsupported limit: "
            f"{limit}. Allowed range: 1-{_KNOWLEDGE_ASSET_QUALITY_SUMMARY_MAX_LIMIT}"
        )
    return limit


def _normalize_knowledge_asset_quality_summary_offset(offset: int | None) -> int:
    if offset is None:
        return 0
    if offset < 0:
        raise ValueError(f"Unsupported offset: {offset}. Allowed range: 0 or greater")
    return offset


def _knowledge_asset_quality_summary_counts(
    items: list[dict[str, Any]],
    *,
    field: str,
    allowed_values: list[str],
) -> dict[str, int]:
    counts = {value: 0 for value in allowed_values}
    for item in items:
        counts[item[field]] += 1
    return counts


def _knowledge_asset_quality_summary_rationale_counts(
    items: list[dict[str, Any]],
) -> dict[str, int]:
    counts = {value: 0 for value in _KNOWLEDGE_ASSET_REVIEW_RATIONALE_CODES}
    for item in items:
        for code in item["review_rationale_codes"]:
            counts[code] += 1
    return counts


def knowledge_asset_quality_summary_service(
    runtime: Any,
    *,
    quality_status: str | None = None,
    review_priority: str | None = None,
    recommended_review_action: str | None = None,
    review_rationale_code: str | None = None,
    order_by: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Return a safe, read-only quality catalog for all KnowledgeAssets."""
    quality_status_filter = _normalize_knowledge_asset_quality_status_filter(quality_status)
    review_priority_filter = _normalize_knowledge_asset_review_priority_filter(review_priority)
    recommended_review_action_filter = _normalize_knowledge_asset_recommended_action_filter(
        recommended_review_action
    )
    review_rationale_code_filter = _normalize_knowledge_asset_review_rationale_code_filter(
        review_rationale_code
    )
    order_by_filter = _normalize_knowledge_asset_quality_summary_order_by(order_by)
    limit_filter = _normalize_knowledge_asset_quality_summary_limit(limit)
    offset_filter = _normalize_knowledge_asset_quality_summary_offset(offset)
    items: list[dict[str, Any]] = []
    for asset in runtime.knowledge_store.all_assets():
        quality = knowledge_asset_decision_quality_service(runtime, asset_id=asset.asset_id)
        derived_status = _knowledge_asset_quality_status(quality)
        derived_priority = _KNOWLEDGE_ASSET_REVIEW_PRIORITY_BY_STATUS[derived_status]
        derived_action = _KNOWLEDGE_ASSET_RECOMMENDED_ACTION_BY_STATUS[derived_status]
        rationale_codes = list(_KNOWLEDGE_ASSET_REVIEW_RATIONALE_CODES_BY_STATUS[derived_status])
        if quality_status_filter is not None and derived_status != quality_status_filter:
            continue
        if review_priority_filter is not None and derived_priority != review_priority_filter:
            continue
        if (
            recommended_review_action_filter is not None
            and derived_action != recommended_review_action_filter
        ):
            continue
        if (
            review_rationale_code_filter is not None
            and review_rationale_code_filter not in rationale_codes
        ):
            continue
        source_trace_id = asset.source_trace_id
        trace_store = getattr(runtime, "trace_store", None)
        persisted_trace = (
            trace_store.get(source_trace_id) if trace_store and source_trace_id else None
        )
        items.append(
            {
                "asset_id": asset.asset_id,
                "source_trace_id": source_trace_id,
                "state": asset.state.value,
                "lifecycle_event_count": _knowledge_asset_lifecycle_event_count(
                    persisted_trace,
                    asset_id=asset.asset_id,
                ),
                "proposal_usage_count": quality["proposal_usage_count"],
                "correction_usage_count": quality["correction_usage_count"],
                "outcome_correction_count": quality["outcome_correction_count"],
                "adoption_correction_count": quality["adoption_correction_count"],
                "distinct_usage_trace_count": quality["distinct_usage_trace_count"],
                "quality_status": derived_status,
                "review_priority": derived_priority,
                "recommended_review_action": derived_action,
                "review_rationale_codes": rationale_codes,
            }
        )
    if order_by_filter == "review_priority":
        items.sort(
            key=lambda item: (
                _KNOWLEDGE_ASSET_REVIEW_PRIORITY_ORDER[item["review_priority"]],
                item["asset_id"],
                item["source_trace_id"] or "",
            )
        )
    total_count = len(items)
    if limit_filter is None:
        page_items = items[offset_filter:]
    else:
        page_items = items[offset_filter : offset_filter + limit_filter]

    return {
        "status": "ok",
        "quality_status_filter": quality_status_filter,
        "review_priority_filter": review_priority_filter,
        "recommended_review_action_filter": recommended_review_action_filter,
        "review_rationale_code_filter": review_rationale_code_filter,
        "order_by": order_by_filter,
        "limit": limit_filter,
        "offset": offset_filter,
        "total_count": total_count,
        "has_more": offset_filter + len(page_items) < total_count,
        "quality_status_counts": _knowledge_asset_quality_summary_counts(
            page_items,
            field="quality_status",
            allowed_values=[
                "unused",
                "proposal_only",
                "outcome_observed",
                "adoption_observed",
            ],
        ),
        "review_priority_counts": _knowledge_asset_quality_summary_counts(
            page_items,
            field="review_priority",
            allowed_values=["high", "medium", "low"],
        ),
        "recommended_review_action_counts": _knowledge_asset_quality_summary_counts(
            page_items,
            field="recommended_review_action",
            allowed_values=[
                "review_or_reject",
                "collect_outcome_feedback",
                "monitor_for_adoption",
                "consider_publish",
            ],
        ),
        "review_rationale_code_counts": _knowledge_asset_quality_summary_rationale_counts(
            page_items
        ),
        "count": len(page_items),
        "items": page_items,
    }


def knowledge_review_action_service(
    runtime: Any,
    *,
    asset_id: str,
    action: str,
    reviewer: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Apply a bounded human review decision to a DRAFT KnowledgeAsset.

    This review action is intentionally narrower than adoption/value promotion:
    it changes only the lifecycle state of an existing DRAFT candidate. It does
    not record feedback, infer outcome, change result_weight, publish assets, or
    execute business actions.
    """
    normalized_action = action.strip().lower()
    if normalized_action not in {"approve", "reject"}:
        raise ValueError(f"Unsupported knowledge review action: {action}")

    target = None
    for asset in runtime.knowledge_store.all_assets():
        if asset.asset_id == asset_id:
            target = asset
            break

    if target is None:
        raise KeyError(asset_id)

    if target.source_trace_id is None:
        raise ValueError("KnowledgeAsset.source_trace_id is required for review")

    trace_store = getattr(runtime, "trace_store", None)
    persisted_trace = trace_store.get(target.source_trace_id) if trace_store is not None else None
    if persisted_trace is None:
        raise RuntimeError(
            f"KnowledgeAsset '{asset_id}' source trace is not persisted: {target.source_trace_id}"
        )

    if target.state != LifecycleState.DRAFT:
        raise RuntimeError(f"KnowledgeAsset '{asset_id}' is not draft: {target.state.value}")

    next_state = (
        LifecycleState.ACTIVE if normalized_action == "approve" else LifecycleState.DEPRECATED
    )
    reviewed = replace(target, state=next_state)
    runtime.knowledge_store.register_version(reviewed)
    knowledge_version = runtime.knowledge_store.version_of(target.source_trace_id)
    audit_event = TraceEvent(
        trace_id=target.source_trace_id,
        step="knowledge_review_decision",
        payload={
            "asset_id": reviewed.asset_id,
            "action": normalized_action,
            "previous_state": target.state.value,
            "state": reviewed.state.value,
            "reviewer": reviewer,
            "knowledge_version": knowledge_version,
            "reason_present": reason is not None,
        },
    )
    trace_store.save(replace(persisted_trace, events=persisted_trace.events + (audit_event,)))

    return {
        "status": "ok",
        "asset_id": reviewed.asset_id,
        "source_trace_id": reviewed.source_trace_id,
        "action": normalized_action,
        "previous_state": target.state.value,
        "state": reviewed.state.value,
        "reviewer": reviewer,
        "reason": reason,
        "knowledge_version": knowledge_version,
        "result_weight": reviewed.result_weight,
        "outcome": reviewed.outcome,
    }


def knowledge_publish_service(
    runtime: Any,
    *,
    asset_id: str,
    reviewer: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Publish an already reviewed KnowledgeAsset for governed internal reuse.

    Publishing is a lifecycle transition only. It requires prior human approval
    (`active`) and does not infer value, write feedback, or expose asset content
    externally.
    """
    target = None
    for asset in runtime.knowledge_store.all_assets():
        if asset.asset_id == asset_id:
            target = asset
            break

    if target is None:
        raise KeyError(asset_id)

    if target.source_trace_id is None:
        raise ValueError("KnowledgeAsset.source_trace_id is required for publish")

    trace_store = getattr(runtime, "trace_store", None)
    persisted_trace = trace_store.get(target.source_trace_id) if trace_store is not None else None
    if persisted_trace is None:
        raise RuntimeError(
            f"KnowledgeAsset '{asset_id}' source trace is not persisted: {target.source_trace_id}"
        )

    if target.state != LifecycleState.ACTIVE:
        raise RuntimeError(f"KnowledgeAsset '{asset_id}' is not active: {target.state.value}")

    published = replace(target, state=LifecycleState.PUBLISHED)
    runtime.knowledge_store.register_version(published)
    knowledge_version = runtime.knowledge_store.version_of(target.source_trace_id)
    audit_event = TraceEvent(
        trace_id=target.source_trace_id,
        step="knowledge_publish_decision",
        payload={
            "asset_id": published.asset_id,
            "action": "publish",
            "previous_state": target.state.value,
            "state": published.state.value,
            "reviewer": reviewer,
            "knowledge_version": knowledge_version,
            "reason_present": reason is not None,
        },
    )
    trace_store.save(replace(persisted_trace, events=persisted_trace.events + (audit_event,)))

    return {
        "status": "ok",
        "asset_id": published.asset_id,
        "source_trace_id": published.source_trace_id,
        "action": "publish",
        "previous_state": target.state.value,
        "state": published.state.value,
        "reviewer": reviewer,
        "reason": reason,
        "knowledge_version": knowledge_version,
        "result_weight": published.result_weight,
        "outcome": published.outcome,
    }


def knowledge_deprecate_service(
    runtime: Any,
    *,
    asset_id: str,
    reviewer: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Deprecate a reviewed KnowledgeAsset so it is no longer consumed by default.

    Deprecation is the correction counterpart to review/publish: it can only
    retire assets that already passed review (`active`) or internal publish
    (`published`). Draft candidates must still go through the review queue.
    """
    target = None
    for asset in runtime.knowledge_store.all_assets():
        if asset.asset_id == asset_id:
            target = asset
            break

    if target is None:
        raise KeyError(asset_id)

    if target.source_trace_id is None:
        raise ValueError("KnowledgeAsset.source_trace_id is required for deprecate")

    trace_store = getattr(runtime, "trace_store", None)
    persisted_trace = trace_store.get(target.source_trace_id) if trace_store is not None else None
    if persisted_trace is None:
        raise RuntimeError(
            f"KnowledgeAsset '{asset_id}' source trace is not persisted: {target.source_trace_id}"
        )

    if target.state not in {LifecycleState.ACTIVE, LifecycleState.PUBLISHED}:
        raise RuntimeError(
            f"KnowledgeAsset '{asset_id}' is not active or published: {target.state.value}"
        )

    deprecated = replace(target, state=LifecycleState.DEPRECATED)
    runtime.knowledge_store.register_version(deprecated)
    knowledge_version = runtime.knowledge_store.version_of(target.source_trace_id)
    audit_event = TraceEvent(
        trace_id=target.source_trace_id,
        step="knowledge_deprecate_decision",
        payload={
            "asset_id": deprecated.asset_id,
            "action": "deprecate",
            "previous_state": target.state.value,
            "state": deprecated.state.value,
            "reviewer": reviewer,
            "knowledge_version": knowledge_version,
            "reason_present": reason is not None,
        },
    )
    trace_store.save(replace(persisted_trace, events=persisted_trace.events + (audit_event,)))

    return {
        "status": "ok",
        "asset_id": deprecated.asset_id,
        "source_trace_id": deprecated.source_trace_id,
        "action": "deprecate",
        "previous_state": target.state.value,
        "state": deprecated.state.value,
        "reviewer": reviewer,
        "reason": reason,
        "knowledge_version": knowledge_version,
        "result_weight": deprecated.result_weight,
        "outcome": deprecated.outcome,
    }


def attest_adoption_service(
    runtime: Any,
    adoption_ingest: Any,
    *,
    trace_id: str,
    outcome: str,
    reviewer: str | None = None,
    metric_deltas: dict[str, Any] | None = None,
    causal_attribution: CausalOutcomeAttribution | None = None,
) -> dict[str, Any]:
    """Attest REALIZED external value and promote the trace's knowledge (P5.1b).

    The operator-facing value channel and the single source of truth for both the
    CLI and HTTP adoption surfaces. ``adoption_ingest.submit`` records realized
    external adoption (the only path that can mint realized value, P5.1a); then
    ``runtime.promote_from_adoption`` folds it into the trace's KnowledgeAsset
    (version bump). Unlike a self-report, this is what drives knowledge promotion.

    For an unknown trace the adoption is still recorded, but no knowledge asset is
    fabricated: ``knowledge_asset_id`` is ``None`` and ``knowledge_version`` is ``0``.
    """
    adoption = adoption_ingest.submit(
        trace_id=trace_id,
        outcome=outcome,
        reviewer=reviewer,
        metric_deltas=metric_deltas,
        causal_attribution=causal_attribution,
    )
    revised = runtime.promote_from_adoption(trace_id)
    asset = runtime.knowledge_store.get_by_trace(trace_id)

    return {
        "adoption_id": adoption.feedback_id,
        "trace_id": trace_id,
        "outcome": outcome,
        "reviewer": reviewer,
        "knowledge_asset_id": asset.asset_id if asset is not None else None,
        "knowledge_version": runtime.knowledge_store.version_of(trace_id),
        "result_weight": revised.result_weight if revised is not None else None,
        "knowledge_context_refs": _knowledge_context_refs_for_trace(runtime, trace_id),
    }
