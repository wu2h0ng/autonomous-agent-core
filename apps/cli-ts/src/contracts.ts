/**
 * Wire contracts for the Agent OS surface protocol v1.2.
 *
 * Mirror of packages/contracts/src/agent_os_contracts/surface.py (M2 frozen).
 * TS client is a protocol client only: it never mints turn ids, never holds
 * governance state, and treats transient frames as display state.
 */
import { z } from "zod";

export const SURFACE_PROTOCOL_VERSION = "1.2" as const;

/** The oldest minor this build still negotiates with (mirrors the Python floor). */
export const SURFACE_PROTOCOL_MIN_SUPPORTED = "1.1" as const;

/**
 * The versions a reader at `SURFACE_PROTOCOL_VERSION` accepts from a runtime.
 *
 * Ordered: a MINOR step is additive, so a runtime one minor behind still speaks
 * a shape this client knows and its response must parse. Bounded to the declared
 * minors — a foreign MAJOR and an undeclared version are outside the set, so
 * this is a closed enumeration, never tolerance for an arbitrary version. The
 * Python side states the same rule as `surface_protocol_readable_versions`.
 */
export const SURFACE_PROTOCOL_READABLE_VERSIONS = [
  SURFACE_PROTOCOL_MIN_SUPPORTED,
  SURFACE_PROTOCOL_VERSION,
] as const;

export const SurfaceProtocolVersionSchema = z.enum(
  SURFACE_PROTOCOL_READABLE_VERSIONS,
);

const NonEmptyStr = z.string().min(1);

export const PermissionModeSchema = z.enum([
  "ASK",
  "ACCEPT_READ_ONLY",
  "ACCEPT_IN_WORKSPACE",
]);
export type PermissionMode = z.infer<typeof PermissionModeSchema>;

export const SurfaceClientRefSchema = z.object({
  client_id: NonEmptyStr,
  client_type: z.enum(["DESKTOP", "CLI", "TEST"]),
  principal_id: NonEmptyStr,
  tenant_id: NonEmptyStr,
  workspace_id: NonEmptyStr,
  device_id: NonEmptyStr,
});
export type SurfaceClientRef = z.infer<typeof SurfaceClientRefSchema>;

export const SessionRefSchema = z.object({
  session_id: NonEmptyStr,
  task_id: NonEmptyStr,
  run_id: NonEmptyStr,
  tenant_id: NonEmptyStr,
  workspace_id: NonEmptyStr,
});

export const SurfaceSessionStatusSchema = z.enum([
  "ACTIVE",
  "WAITING_APPROVAL",
  "PAUSED",
  "CORRECTION_HALTED",
  "CLOSED",
]);
export type SurfaceSessionStatus = z.infer<typeof SurfaceSessionStatusSchema>;

export const PendingSurfaceApprovalSchema = z.object({
  action_digest: NonEmptyStr,
  capability_id: NonEmptyStr,
  proposal_id: NonEmptyStr,
  preview: NonEmptyStr,
  requested_at: NonEmptyStr,
});
export type PendingSurfaceApproval = z.infer<typeof PendingSurfaceApprovalSchema>;

export const SurfaceSessionSnapshotSchema = z.object({
  protocol_version: SurfaceProtocolVersionSchema,
  session: SessionRefSchema,
  envelope_id: NonEmptyStr,
  expected_outcome_id: NonEmptyStr,
  status: SurfaceSessionStatusSchema,
  event_sequence: z.number().int().nonnegative(),
  message_count: z.number().int().nonnegative(),
  pending_approval: PendingSurfaceApprovalSchema.nullable().optional(),
  permission_mode: PermissionModeSchema.default("ASK"),
  updated_at: NonEmptyStr,
});
export type SurfaceSessionSnapshot = z.infer<typeof SurfaceSessionSnapshotSchema>;

export const SurfaceSessionSummarySchema = z.object({
  session_id: NonEmptyStr,
  task_id: NonEmptyStr,
  status: SurfaceSessionStatusSchema,
  permission_mode: PermissionModeSchema.default("ASK"),
  message_count: z.number().int().nonnegative(),
  updated_at: NonEmptyStr,
  awaiting_approval: z.boolean().default(false),
});
export type SurfaceSessionSummary = z.infer<typeof SurfaceSessionSummarySchema>;

export const SurfaceSessionListResponseSchema = z.object({
  protocol_version: SurfaceProtocolVersionSchema,
  sessions: z.array(SurfaceSessionSummarySchema).default([]),
  next_cursor: NonEmptyStr.nullable().optional(),
});
export type SurfaceSessionListResponse = z.infer<typeof SurfaceSessionListResponseSchema>;

export const ProviderMessageSchema = z
  .object({
    role: z.enum(["SYSTEM", "USER", "ASSISTANT", "TOOL"]),
  })
  .passthrough();
export type ProviderMessage = z.infer<typeof ProviderMessageSchema>;

export const SurfaceTurnResponseSchema = z.object({
  protocol_version: SurfaceProtocolVersionSchema,
  snapshot: SurfaceSessionSnapshotSchema,
  turn_id: NonEmptyStr.nullable().optional(),
  text: NonEmptyStr,
  steps: z.array(ProviderMessageSchema).default([]),
  stop_reason: NonEmptyStr,
  total_tokens: z.number().int().nonnegative(),
});
export type SurfaceTurnResponse = z.infer<typeof SurfaceTurnResponseSchema>;

export const SurfaceStreamBindingSchema = z.object({
  runtime_boot_id: NonEmptyStr,
  stream_id: NonEmptyStr,
});
export type SurfaceStreamBinding = z.infer<typeof SurfaceStreamBindingSchema>;

export const SurfaceBeginTurnResponseSchema = z.object({
  protocol_version: SurfaceProtocolVersionSchema.default(SURFACE_PROTOCOL_VERSION),
  turn_id: NonEmptyStr,
  stream_id: NonEmptyStr,
});
export type SurfaceBeginTurnResponse = z.infer<typeof SurfaceBeginTurnResponseSchema>;

export const SurfaceStreamSubscriptionSchema = z.object({
  protocol_version: SurfaceProtocolVersionSchema.default(SURFACE_PROTOCOL_VERSION),
  runtime_boot_id: NonEmptyStr,
  stream_id: NonEmptyStr,
});
export type SurfaceStreamSubscription = z.infer<typeof SurfaceStreamSubscriptionSchema>;

/** Mirror of `RecoveredUnknownTurn` (surface.py): the typed, durable record of
 * a dead turn the operator closed as an unknown outcome. Never a success claim
 * — the completion it belongs to carries `stop_reason: unknown_requires_review`. */
export const RecoveredUnknownTurnSchema = z.object({
  turn_id: NonEmptyStr,
  session_id: NonEmptyStr,
  reason_code: z.literal("TURN_OWNER_PROCESS_GONE"),
  declared_by: NonEmptyStr,
  declared_at: NonEmptyStr,
  reason: NonEmptyStr,
  owner_runtime_boot_id: NonEmptyStr.nullable().optional(),
  owner_runtime_pid: z.number().int().positive().nullable().optional(),
  recovered_by_runtime_boot_id: NonEmptyStr,
  recovered_by_runtime_pid: z.number().int().positive(),
  started_event_id: NonEmptyStr,
  started_sequence: z.number().int().positive(),
  counters_recorded: z.boolean().default(false),
});
export type RecoveredUnknownTurn = z.infer<typeof RecoveredUnknownTurnSchema>;

export const SurfaceTurnRecoveryResponseSchema = z.object({
  protocol_version: z.literal(SURFACE_PROTOCOL_VERSION).default(SURFACE_PROTOCOL_VERSION),
  snapshot: SurfaceSessionSnapshotSchema,
  recovery: RecoveredUnknownTurnSchema,
  notice: NonEmptyStr,
});
export type SurfaceTurnRecoveryResponse = z.infer<
  typeof SurfaceTurnRecoveryResponseSchema
>;

export const SurfaceStreamFrameSchema = z
  .object({
    kind: z.enum(["CHUNK", "GAP", "STREAM_END", "REASONING"]),
    runtime_boot_id: NonEmptyStr,
    stream_id: NonEmptyStr,
    turn_id: NonEmptyStr.nullable().optional(),
    frame_sequence: z.number().int().nonnegative(),
    gap_from: z.number().int().nonnegative().nullable().optional(),
    gap_to: z.number().int().nonnegative().nullable().optional(),
    payload: z.record(z.string(), z.unknown()).default({}),
  })
  .superRefine((frame, ctx) => {
    if (frame.kind === "GAP") {
      if (frame.turn_id != null) {
        ctx.addIssue({ code: "custom", message: "gap frames are never turn-bound" });
      }
      if (frame.gap_from == null || frame.gap_to == null) {
        ctx.addIssue({ code: "custom", message: "gap frames require gap_from/gap_to" });
      }
    } else if (frame.turn_id == null) {
      ctx.addIssue({ code: "custom", message: `${frame.kind} frames require turn binding` });
    }
  });
export type SurfaceStreamFrame = z.infer<typeof SurfaceStreamFrameSchema>;

export const SurfaceStreamBatchSchema = z.object({
  protocol_version: SurfaceProtocolVersionSchema.default(SURFACE_PROTOCOL_VERSION),
  session_id: NonEmptyStr,
  after_sequence: z.number().int().nonnegative(),
  next_sequence: z.number().int().nonnegative(),
  frames: z.array(SurfaceStreamFrameSchema).default([]),
});
export type SurfaceStreamBatch = z.infer<typeof SurfaceStreamBatchSchema>;

export const TaskEventSchema = z.object({
  event_id: NonEmptyStr,
  task_id: NonEmptyStr,
  event_type: NonEmptyStr,
  payload_json: NonEmptyStr,
  occurred_at: NonEmptyStr,
  correlation_id: NonEmptyStr.nullable().optional(),
  causation_id: NonEmptyStr.nullable().optional(),
  sequence: z.number().int().positive(),
});
export type TaskEvent = z.infer<typeof TaskEventSchema>;

export const SurfaceEventBatchSchema = z
  .object({
    task_id: NonEmptyStr,
    after_sequence: z.number().int().nonnegative(),
    next_sequence: z.number().int().nonnegative(),
    events: z.array(TaskEventSchema).default([]),
  })
  .superRefine((batch, ctx) => {
    // Mirror of SurfaceEventBatch._validate_event_ownership_and_sequence
    // (packages/contracts/src/agent_os_contracts/surface.py): a batch that
    // contradicts its own resume cursor is a protocol error, never a silently
    // accepted one, because callers resume from `next_sequence` — accepting it
    // either skips events or re-requests a window that was already applied.
    let previousSequence = batch.after_sequence;
    for (const event of batch.events) {
      if (event.task_id !== batch.task_id) {
        ctx.addIssue({
          code: "custom",
          message: "surface events must belong to the requested task",
        });
        return;
      }
      if (event.sequence <= previousSequence) {
        ctx.addIssue({
          code: "custom",
          message: "surface event sequences must strictly increase above after_sequence",
        });
        return;
      }
      previousSequence = event.sequence;
    }
    if (batch.next_sequence !== previousSequence) {
      ctx.addIssue({
        code: "custom",
        message: "surface next_sequence must equal the last event sequence or after_sequence",
      });
    }
  });
export type SurfaceEventBatch = z.infer<typeof SurfaceEventBatchSchema>;

export const SurfaceFileEntrySchema = z.object({
  path: NonEmptyStr,
  size: z.number().int().nonnegative(),
  mtime: NonEmptyStr,
});
export type SurfaceFileEntry = z.infer<typeof SurfaceFileEntrySchema>;

export const SurfaceTaskOverviewSchema = z.object({
  task_id: NonEmptyStr,
  task_status: NonEmptyStr,
  run_status: NonEmptyStr,
  run_id: z.string().default(""),
  expected_outcome_id: z.string().default(""),
  receipt_count: z.number().int().nonnegative(),
  session_id: z.string().default(""),
});
export type SurfaceTaskOverview = z.infer<typeof SurfaceTaskOverviewSchema>;

/** Command payloads (client → server). */
export interface SurfaceOpenSessionCommand {
  protocol_version: typeof SURFACE_PROTOCOL_VERSION;
  client: SurfaceClientRef;
  statement: string;
  idempotency_key: string;
  requested_at: string;
}

export interface SurfaceBeginTurnCommand {
  protocol_version: typeof SURFACE_PROTOCOL_VERSION;
  client: SurfaceClientRef;
  session_id: string;
  text: string;
  stream: SurfaceStreamBinding;
  expected_event_sequence: number;
  idempotency_key: string;
  requested_at: string;
}

export interface SurfaceSetPermissionModeCommand {
  protocol_version: typeof SURFACE_PROTOCOL_VERSION;
  client: SurfaceClientRef;
  session_id: string;
  mode: PermissionMode;
  expected_event_sequence: number;
  idempotency_key: string;
  requested_at: string;
}

export interface SurfaceApprovalCommand {
  protocol_version: typeof SURFACE_PROTOCOL_VERSION;
  client: SurfaceClientRef;
  session_id: string;
  action_digest: string;
  disposition: "APPROVE" | "REJECT";
  reason: string;
  expected_event_sequence: number;
  idempotency_key: string;
  requested_at: string;
}

export interface SurfaceCorrectionCommand {
  protocol_version: typeof SURFACE_PROTOCOL_VERSION;
  client: SurfaceClientRef;
  session_id: string;
  reason: string;
  expected_event_sequence: number;
  idempotency_key: string;
  requested_at: string;
}

/** Redacted live provider configuration (never the credential value). */
export const SurfaceProviderStatusSchema = z.object({
  protocol_version: SurfaceProtocolVersionSchema.optional(),
  configured: z.boolean(),
  provider_id: NonEmptyStr.nullable().optional(),
  model_id: NonEmptyStr.nullable().optional(),
  endpoint_class: NonEmptyStr.nullable().optional(),
  credential_ref_id: NonEmptyStr.nullable().optional(),
  base_url: NonEmptyStr.nullable().optional(),
  persisted: z.boolean().optional(),
  key_source: z.enum(["keychain", "env", "none"]).nullable().optional(),
});
export type SurfaceProviderStatus = z.infer<typeof SurfaceProviderStatusSchema>;

/**
 * Aggregated provider boundary (`GET /v1/surface/observability/metrics`).
 *
 * Content-free by construction: the kernel aggregates call counts, latency,
 * token totals and failure codes, so there is no field here that can carry a
 * prompt, a completion or a credential. Fields the kernel sends as optional
 * (a partial/older payload) stay optional so an older daemon degrades instead
 * of failing the whole panel.
 */
export const ProviderMetricsSnapshotSchema = z.object({
  schema_version: z.literal("1.0").optional(),
  source: z.enum(["in_process", "log_file"]),
  taken_at: z.string(),
  window_started_at: z.string().nullable().optional(),
  window_ended_at: z.string().nullable().optional(),
  window_records: z.number().int().nonnegative(),
  window_truncated: z.boolean().optional(),
  ignored_lines: z.number().int().nonnegative().optional(),
  calls: z.number().int().nonnegative(),
  attempts: z.number().int().nonnegative(),
  responses: z.number().int().nonnegative(),
  failures: z.number().int().nonnegative(),
  retries: z.number().int().nonnegative(),
  latency: z.object({
    samples: z.number().int().nonnegative(),
    mean_ms: z.number().nullable().optional(),
    p50_ms: z.number().nullable().optional(),
    p90_ms: z.number().nullable().optional(),
    p95_ms: z.number().nullable().optional(),
    max_ms: z.number().nullable().optional(),
  }),
  tokens: z.object({
    input_tokens: z.number().int().nonnegative(),
    output_tokens: z.number().int().nonnegative(),
    total_tokens: z.number().int().nonnegative(),
    usage_samples: z.number().int().nonnegative(),
  }),
  failure_categories: z
    .array(
      z.object({
        code: z.string(),
        count: z.number().int().nonnegative(),
        retryable: z.boolean(),
      }),
    )
    .default([]),
  rate_limit: z.object({
    rate_limited_attempts: z.number().int().nonnegative(),
    retry_after_observed: z.number().int().nonnegative(),
    max_retry_after_seconds: z.number().nullable().optional(),
    local_waits: z.number().int().nonnegative(),
    local_wait_ms_total: z.number().nonnegative(),
    local_wait_ms_max: z.number().nonnegative(),
    local_rejections: z.number().int().nonnegative(),
  }),
});
export type ProviderMetricsSnapshot = z.infer<typeof ProviderMetricsSnapshotSchema>;

/**
 * Trace of one governed turn (`GET /v1/surface/sessions/{id}/trace`).
 *
 * A derived, read-only projection of the durable Task event stream: the sequence
 * of what actually happened, with the durable record kind that opened and closed
 * each span (`started_by`/`ended_by`), the ids that link it to the turn (`link`)
 * and the exact records it was built from (`event_sequences`). It carries no
 * prompt, completion, argument payload, approval preview or credential — only
 * ids, enums, sequences and timestamps.
 *
 * `state: "OPEN"` means the durable log holds no `SESSION_TURN_COMPLETED` for the
 * turn; `gaps` states every hole the projection found instead of closing it up.
 * Optional fields degrade rather than fail the panel on an older daemon.
 */
export const TraceSpanSchema = z.object({
  span_id: NonEmptyStr,
  kind: z.enum([
    "TURN",
    "MODEL_CALL",
    "POLICY_VERDICT",
    "POLICY_DECISION",
    "APPROVAL",
    "CAPABILITY_DISPATCH",
  ]),
  status: z.enum([
    "COMPLETED",
    "FAILED",
    "ALLOWED",
    "DENIED",
    "APPROVED",
    "REJECTED",
    "UNDETERMINED",
    "OPEN",
  ]),
  started_by: NonEmptyStr,
  started_sequence: z.number().int().positive(),
  started_at: z.string(),
  ended_by: NonEmptyStr.nullable().optional(),
  ended_sequence: z.number().int().positive().nullable().optional(),
  ended_at: z.string().nullable().optional(),
  link: z.enum([
    "ROOT",
    "TURN_ID",
    "NODE_ID_TURN_PREFIX",
    "ACTION_ID",
    "ACTION_DIGEST",
    "SEQUENCE_WINDOW",
  ]),
  parent_span_id: NonEmptyStr,
  session_id: NonEmptyStr,
  turn_id: NonEmptyStr,
  run_id: NonEmptyStr.nullable().optional(),
  action_id: NonEmptyStr.nullable().optional(),
  action_digest: NonEmptyStr.nullable().optional(),
  node_id: NonEmptyStr.nullable().optional(),
  capability_id: NonEmptyStr.nullable().optional(),
  provider_tool_call_id: NonEmptyStr.nullable().optional(),
  request_id: NonEmptyStr.nullable().optional(),
  response_id: NonEmptyStr.nullable().optional(),
  decision_id: NonEmptyStr.nullable().optional(),
  permit_id: NonEmptyStr.nullable().optional(),
  approval_id: NonEmptyStr.nullable().optional(),
  rule_id: NonEmptyStr.nullable().optional(),
  verdict: NonEmptyStr.nullable().optional(),
  basis: NonEmptyStr.nullable().optional(),
  reason_codes: z.array(NonEmptyStr).default([]),
  disposition: NonEmptyStr.nullable().optional(),
  effect_state: NonEmptyStr.nullable().optional(),
  stop_reason: NonEmptyStr.nullable().optional(),
  event_sequences: z.array(z.number().int().positive()).min(1),
});
export type TraceSpan = z.infer<typeof TraceSpanSchema>;

export const TraceGapSchema = z.object({
  kind: z.enum([
    "TURN_OPEN",
    "DISPATCH_UNRESOLVED",
    "EFFECT_UNDETERMINED",
    "APPROVAL_UNRESOLVED",
    "MODEL_CALL_NOT_RECORDED",
    "MALFORMED_EVENT",
    "SEQUENCE_GAP",
  ]),
  sequence: z.number().int().positive().nullable().optional(),
  subject: NonEmptyStr.nullable().optional(),
  detail: NonEmptyStr,
});
export type TraceGap = z.infer<typeof TraceGapSchema>;

export const TurnTraceSchema = z.object({
  schema_version: z.literal("1.0").optional(),
  task_id: NonEmptyStr,
  session_id: NonEmptyStr,
  turn_id: NonEmptyStr,
  state: z.enum(["COMPLETE", "OPEN"]),
  stop_reason: NonEmptyStr.nullable().optional(),
  started_sequence: z.number().int().positive(),
  started_at: z.string(),
  ended_sequence: z.number().int().positive().nullable().optional(),
  ended_at: z.string().nullable().optional(),
  records_scanned: z.number().int().positive(),
  first_sequence: z.number().int().positive(),
  last_sequence: z.number().int().positive(),
  spans: z.array(TraceSpanSchema).default([]),
  gaps: z.array(TraceGapSchema).default([]),
});
export type TurnTrace = z.infer<typeof TurnTraceSchema>;

export interface SurfaceProviderClearCommand {
  protocol_version: typeof SURFACE_PROTOCOL_VERSION;
  client: SurfaceClientRef;
}

export interface SurfaceProviderConfigureCommand {
  protocol_version: typeof SURFACE_PROTOCOL_VERSION;
  client: SurfaceClientRef;
  base_url: string;
  model: string;
  api_key: string;
  endpoint_class: string;
  temperature?: number;
}
