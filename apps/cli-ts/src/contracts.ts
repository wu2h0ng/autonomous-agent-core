/**
 * Wire contracts for the Agent OS surface protocol v1.1.
 *
 * Mirror of packages/contracts/src/agent_os_contracts/surface.py (M2 frozen).
 * TS client is a protocol client only: it never mints turn ids, never holds
 * governance state, and treats transient frames as display state.
 */
import { z } from "zod";

export const SURFACE_PROTOCOL_VERSION = "1.1" as const;

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
  protocol_version: z.literal(SURFACE_PROTOCOL_VERSION),
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
});
export type SurfaceSessionSummary = z.infer<typeof SurfaceSessionSummarySchema>;

export const SurfaceSessionListResponseSchema = z.object({
  protocol_version: z.literal(SURFACE_PROTOCOL_VERSION),
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
  protocol_version: z.literal(SURFACE_PROTOCOL_VERSION),
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
  protocol_version: z.literal(SURFACE_PROTOCOL_VERSION).default(SURFACE_PROTOCOL_VERSION),
  turn_id: NonEmptyStr,
  stream_id: NonEmptyStr,
});
export type SurfaceBeginTurnResponse = z.infer<typeof SurfaceBeginTurnResponseSchema>;

export const SurfaceStreamSubscriptionSchema = z.object({
  protocol_version: z.literal(SURFACE_PROTOCOL_VERSION).default(SURFACE_PROTOCOL_VERSION),
  runtime_boot_id: NonEmptyStr,
  stream_id: NonEmptyStr,
});
export type SurfaceStreamSubscription = z.infer<typeof SurfaceStreamSubscriptionSchema>;

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
  protocol_version: z.literal(SURFACE_PROTOCOL_VERSION).default(SURFACE_PROTOCOL_VERSION),
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

export const SurfaceEventBatchSchema = z.object({
  task_id: NonEmptyStr,
  after_sequence: z.number().int().nonnegative(),
  next_sequence: z.number().int().nonnegative(),
  events: z.array(TaskEventSchema).default([]),
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
