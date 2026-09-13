/**
 * TypeScript SurfaceClient — the protocol client port of
 * apps/cli/surface_client.py (M2 frozen semantics):
 *
 * - subscription-first: subscribeStream() before any beginTurn();
 * - begin-turn is the only turn_id source; idempotency key per attempt;
 * - expected_event_sequence is tracked from every observed snapshot;
 * - 410 on the stream endpoint maps to SurfaceStreamStaleError (dead
 *   generation) — the caller resubscribes and re-syncs from durable state;
 *   transient frames are never replayable;
 * - 401 maps to SurfaceClientAuthenticationError; the bearer token is never
 *   embedded in error messages.
 */
import { randomUUID } from "node:crypto";
import { z } from "zod";
import {
  SURFACE_PROTOCOL_VERSION,
  SurfaceBeginTurnResponseSchema,
  SurfaceEventBatchSchema,
  SurfaceFileEntrySchema,
  SurfaceSessionListResponseSchema,
  SurfaceSessionSnapshotSchema,
  SurfaceStreamBatchSchema,
  SurfaceStreamFrameSchema,
  SurfaceStreamSubscriptionSchema,
  SurfaceTaskOverviewSchema,
  SurfaceTurnResponseSchema,
  TaskEventSchema,
  type PermissionMode,
  type SurfaceBeginTurnResponse,
  type SurfaceClientRef,
  type SurfaceEventBatch,
  type SurfaceFileEntry,
  type SurfaceSessionSnapshot,
  type SurfaceSessionSummary,
  type SurfaceStreamBatch,
  type SurfaceStreamBinding,
  type SurfaceStreamFrame,
  type SurfaceStreamSubscription,
  type SurfaceTaskOverview,
  type SurfaceTurnResponse,
  type TaskEvent,
} from "./contracts.js";
import { localHostname, type RuntimeDescriptor } from "./descriptor.js";
import { parseSse } from "./sse.js";

export class SurfaceClientError extends Error {}
export class SurfaceProtocolMismatch extends SurfaceClientError {}
export class SurfaceClientAuthenticationError extends SurfaceClientError {}
export class SurfaceClientConnectionError extends SurfaceClientError {}

export class SurfaceHttpError extends SurfaceClientError {
  constructor(
    public readonly statusCode: number,
    message: string,
  ) {
    super(message);
  }
}

/** Dead daemon generation or unknown stream: resubscribe, never replay. */
export class SurfaceStreamStaleError extends SurfaceClientError {}

export class SurfaceClient {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly deviceId = `device:${randomUUID().slice(0, 8)}`;
  private readonly sequences = new Map<string, number>();

  constructor(descriptor: RuntimeDescriptor) {
    this.baseUrl = descriptor.baseUrl;
    this.token = descriptor.bearer_token;
  }

  private clientRef(): SurfaceClientRef {
    return {
      client_id: `cli-ts:${localHostname()}`,
      client_type: "CLI",
      principal_id: "user:local",
      tenant_id: "tenant:local",
      workspace_id: "workspace:local",
      device_id: this.deviceId,
    };
  }

  private now(): string {
    return new Date().toISOString();
  }

  private track(snapshot: SurfaceSessionSnapshot): void {
    this.sequences.set(snapshot.session.session_id, snapshot.event_sequence);
  }

  private sequence(sessionId: string): number {
    return this.sequences.get(sessionId) ?? 0;
  }

  private headers(json: boolean): Record<string, string> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.token}`,
      "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
    };
    if (json) headers["Content-Type"] = "application/json";
    return headers;
  }

  private async request(method: string, path: string, payload?: unknown): Promise<unknown> {
    let response: Response;
    try {
      response = await fetch(this.baseUrl + path, {
        method,
        headers: this.headers(payload !== undefined),
        body: payload === undefined ? null : JSON.stringify(payload),
      });
    } catch (cause) {
      throw new SurfaceClientConnectionError(
        `cannot reach the local runtime: ${(cause as Error).message}`,
      );
    }
    const raw = await response.text();
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const body = JSON.parse(raw) as { message?: string; error?: string };
        message = body.message ?? body.error ?? message;
      } catch {
        /* non-JSON error body */
      }
      if (response.status === 401) throw new SurfaceClientAuthenticationError(message);
      if (response.status === 410) throw new SurfaceStreamStaleError(message);
      throw new SurfaceHttpError(response.status, message);
    }
    try {
      return JSON.parse(raw);
    } catch {
      throw new SurfaceProtocolMismatch("local runtime returned a non-JSON response");
    }
  }

  private unwrap<T>(value: unknown, key: string, schema: { parse(v: unknown): T }): T {
    if (typeof value !== "object" || value === null) {
      throw new SurfaceProtocolMismatch("local runtime returned a non-object response");
    }
    const inner = (value as Record<string, unknown>)[key];
    if (inner === undefined) {
      throw new SurfaceProtocolMismatch(`local runtime returned no ${key} payload`);
    }
    return schema.parse(inner);
  }

  async openSession(statement: string, idempotencyKey?: string): Promise<SurfaceSessionSnapshot> {
    if (!statement.trim()) throw new Error("statement must be non-empty");
    const response = await this.request("POST", "/v1/surface/sessions", {
      protocol_version: SURFACE_PROTOCOL_VERSION,
      client: this.clientRef(),
      statement,
      idempotency_key: idempotencyKey ?? `cli-ts-open:${randomUUID()}`,
      requested_at: this.now(),
    });
    const snapshot = this.unwrap(response, "snapshot", SurfaceSessionSnapshotSchema);
    this.track(snapshot);
    return snapshot;
  }

  async getSession(sessionId: string): Promise<SurfaceSessionSnapshot> {
    const response = await this.request("GET", `/v1/surface/sessions/${sessionId}`);
    const snapshot = SurfaceSessionSnapshotSchema.parse(response);
    this.track(snapshot);
    return snapshot;
  }

  /** Read-only session listing (C2). Returns [] if the runtime has no
   * sessions; throws on transport/protocol errors so callers can fall back. */
  async listSessions(limit = 50): Promise<SurfaceSessionSummary[]> {
    const query = new URLSearchParams({ limit: String(limit) });
    const response = await this.request("GET", `/v1/surface/sessions?${query.toString()}`);
    return SurfaceSessionListResponseSchema.parse(response).sessions;
  }

  /** Subscription-first: mint a transient stream under the current daemon
   * generation before executing any turn (E1, frozen order). */
  async subscribeStream(sessionId: string): Promise<SurfaceStreamSubscription> {
    const response = await this.request("POST", `/v1/surface/sessions/${sessionId}/streams`);
    return this.unwrap(response, "subscription", SurfaceStreamSubscriptionSchema);
  }

  /** E1 reserve/begin-turn: bind the pre-subscribed stream and return the
   * authoritative {turn_id, stream_id} without blocking on the provider. */
  async beginTurn(
    sessionId: string,
    text: string,
    stream: SurfaceStreamBinding,
    idempotencyKey?: string,
  ): Promise<SurfaceBeginTurnResponse> {
    if (!text.trim()) throw new Error("turn text must be non-empty");
    const response = await this.request("POST", `/v1/surface/sessions/${sessionId}/begin-turn`, {
      protocol_version: SURFACE_PROTOCOL_VERSION,
      client: this.clientRef(),
      session_id: sessionId,
      text,
      stream,
      expected_event_sequence: this.sequence(sessionId),
      idempotency_key: idempotencyKey ?? `cli-ts-turn:${sessionId}:${randomUUID()}`,
      requested_at: this.now(),
    });
    return this.unwrap(response, "begin_turn", SurfaceBeginTurnResponseSchema);
  }

  /** Bounded incremental read of transient display frames (E1). 410 maps to
   * SurfaceStreamStaleError; never replay transient frames. */
  async streamFrames(
    sessionId: string,
    stream: SurfaceStreamBinding,
    afterSequence = 0,
    waitMs = 0,
  ): Promise<SurfaceStreamBatch> {
    return this.streamFramesRaw(sessionId, stream, afterSequence, waitMs);
  }

  async setPermissionMode(
    sessionId: string,
    mode: PermissionMode,
    idempotencyKey?: string,
  ): Promise<SurfaceSessionSnapshot> {
    const response = await this.request("POST", `/v1/surface/sessions/${sessionId}/mode`, {
      protocol_version: SURFACE_PROTOCOL_VERSION,
      client: this.clientRef(),
      session_id: sessionId,
      mode,
      expected_event_sequence: this.sequence(sessionId),
      idempotency_key: idempotencyKey ?? `cli-ts-mode:${randomUUID()}`,
      requested_at: this.now(),
    });
    const snapshot = this.unwrap(response, "snapshot", SurfaceSessionSnapshotSchema);
    this.track(snapshot);
    return snapshot;
  }

  async decideApproval(
    sessionId: string,
    actionDigest: string,
    disposition: "APPROVE" | "REJECT",
    reason: string,
    idempotencyKey?: string,
  ): Promise<SurfaceTurnResponse> {
    if (!actionDigest.trim() || !reason.trim()) {
      throw new Error("action digest and reason must be non-empty");
    }
    const response = await this.request("POST", `/v1/surface/sessions/${sessionId}/approvals`, {
      protocol_version: SURFACE_PROTOCOL_VERSION,
      client: this.clientRef(),
      session_id: sessionId,
      action_digest: actionDigest,
      disposition,
      reason,
      expected_event_sequence: this.sequence(sessionId),
      idempotency_key: idempotencyKey ?? `cli-ts-approve:${randomUUID()}`,
      requested_at: this.now(),
    });
    const turn = this.unwrap(response, "turn", SurfaceTurnResponseSchema);
    this.track(turn.snapshot);
    return turn;
  }

  async correct(
    sessionId: string,
    reason: string,
    action: "pause" | "resume" | "correction" = "correction",
    idempotencyKey?: string,
  ): Promise<SurfaceSessionSnapshot> {
    if (!reason.trim()) throw new Error("reason must be non-empty");
    const response = await this.request("POST", `/v1/surface/sessions/${sessionId}/${action}`, {
      protocol_version: SURFACE_PROTOCOL_VERSION,
      client: this.clientRef(),
      session_id: sessionId,
      reason,
      expected_event_sequence: this.sequence(sessionId),
      idempotency_key: idempotencyKey ?? `cli-ts-${action}:${randomUUID()}`,
      requested_at: this.now(),
    });
    const snapshot = this.unwrap(response, "snapshot", SurfaceSessionSnapshotSchema);
    this.track(snapshot);
    return snapshot;
  }

  private readonly streamCursors = new Map<string, number>();

  /** Poll transient frames until STREAM_END or abort. Yields frames in order;
   * GAP frames are surfaced as-is (explicit loss honesty, never fabricated
   * content). The cursor persists per stream binding across calls, so a
   * later turn on the same stream never replays a prior turn's frames.
   * Throws SurfaceStreamStaleError on dead generations. */
  async *followStream(
    sessionId: string,
    stream: SurfaceStreamBinding,
    opts: { pollMs?: number; waitMs?: number; signal?: AbortSignal } = {},
  ): AsyncGenerator<SurfaceStreamFrame> {
    const pollMs = opts.pollMs ?? 100;
    const waitMs = opts.waitMs ?? 0;
    const cursorKey = `${stream.runtime_boot_id}:${stream.stream_id}`;
    let cursor = this.streamCursors.get(cursorKey) ?? 0;
    for (;;) {
      if (opts.signal?.aborted) return;
      const batch = await this.streamFramesRaw(sessionId, stream, cursor, waitMs);
      cursor = batch.next_sequence;
      this.streamCursors.set(cursorKey, cursor);
      for (const frame of batch.frames) {
        yield frame;
        if (frame.kind === "STREAM_END") return;
      }
      await new Promise((resolve) => setTimeout(resolve, pollMs));
    }
  }

  private async streamFramesRaw(
    sessionId: string,
    stream: SurfaceStreamBinding,
    afterSequence: number,
    waitMs: number,
  ): Promise<SurfaceStreamBatch> {
    const path =
      `/v1/surface/sessions/${sessionId}/stream` +
      `?stream_id=${stream.stream_id}&after=${afterSequence}&wait_ms=${waitMs}`;
    let response: Response;
    try {
      response = await fetch(this.baseUrl + path, {
        method: "GET",
        headers: this.headers(false),
      });
    } catch (cause) {
      throw new SurfaceClientConnectionError(
        `cannot reach the local runtime: ${(cause as Error).message}`,
      );
    }
    const raw = await response.text();
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const body = JSON.parse(raw) as { message?: string; error?: string };
        message = body.message ?? body.error ?? message;
      } catch {
        /* non-JSON error body */
      }
      if (response.status === 401) throw new SurfaceClientAuthenticationError(message);
      if (response.status === 410) throw new SurfaceStreamStaleError(message);
      throw new SurfaceHttpError(response.status, message);
    }
    let nextSequence = afterSequence;
    const frames: SurfaceStreamFrame[] = [];
    for (const message of parseSse(raw)) {
      if (message.event === "cursor") {
        const payload = JSON.parse(message.data) as { next_sequence: number };
        nextSequence = payload.next_sequence;
      } else if (message.data) {
        frames.push(SurfaceStreamFrameSchema.parse(JSON.parse(message.data)));
      }
    }
    return SurfaceStreamBatchSchema.parse({
      session_id: sessionId,
      after_sequence: afterSequence,
      next_sequence: nextSequence,
      frames,
    });
  }

  /** Durable task events (append-only truth): bounded read over the
   * authenticated SSE events endpoint. Used for authoritative turn
   * completion, approval-pending detection and exact token totals. */
  /** Bounded read-only workspace listing (path/size/mtime; no content). */
  async files(taskId: string): Promise<SurfaceFileEntry[]> {
    if (!taskId.trim()) throw new Error("task_id must be non-empty");
    const response = await this.request("GET", `/v1/surface/tasks/${taskId}/files`);
    return this.unwrap(response, "files", z.array(SurfaceFileEntrySchema));
  }

  /** Closed read-only task projection (status/run/receipt counts). */
  async overview(taskId: string): Promise<SurfaceTaskOverview> {
    if (!taskId.trim()) throw new Error("task_id must be non-empty");
    const response = await this.request("GET", `/v1/surface/tasks/${taskId}/overview`);
    return this.unwrap(response, "overview", SurfaceTaskOverviewSchema);
  }

  async events(taskId: string, afterSequence = 0, waitMs = 0): Promise<SurfaceEventBatch> {
    if (!taskId.trim()) throw new Error("task_id must be non-empty");
    let response: Response;
    try {
      response = await fetch(
        this.baseUrl + `/v1/surface/tasks/${taskId}/events?after=${afterSequence}&wait_ms=${waitMs}`,
        { method: "GET", headers: this.headers(false) },
      );
    } catch (cause) {
      throw new SurfaceClientConnectionError(
        `cannot reach the local runtime: ${(cause as Error).message}`,
      );
    }
    const raw = await response.text();
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const body = JSON.parse(raw) as { message?: string; error?: string };
        message = body.message ?? body.error ?? message;
      } catch {
        /* non-JSON error body */
      }
      if (response.status === 401) throw new SurfaceClientAuthenticationError(message);
      if (response.status === 410) throw new SurfaceStreamStaleError(message);
      throw new SurfaceHttpError(response.status, message);
    }
    let nextSequence = afterSequence;
    const events: TaskEvent[] = [];
    for (const message of parseSse(raw)) {
      if (message.event === "cursor") {
        const payload = JSON.parse(message.data) as { next_sequence: number };
        nextSequence = payload.next_sequence;
      } else if (message.data) {
        events.push(TaskEventSchema.parse(JSON.parse(message.data)));
      }
    }
    return SurfaceEventBatchSchema.parse({
      task_id: taskId,
      after_sequence: afterSequence,
      next_sequence: nextSequence,
      events,
    });
  }
}
