// Typed Surface HTTP/SSE client for the Wave 2a renderer.
//
// Mirrors apps/cli/surface_client.py semantics: every success is parsed
// through the matching closed contract, the protocol version is checked on
// every response, HTTP errors map to closed typed errors, and the per-session
// event sequence is tracked for commands. The bearer token is supplied by the
// Rust layer and never stored in webview-local storage.

export const SURFACE_PROTOCOL_VERSION = "1.1";

export class SurfaceProtocolMismatch extends Error {}
export class SurfaceClientAuthenticationError extends Error {}
export class SurfaceClientConnectionError extends Error {}
export class SurfaceHttpError extends Error {
  statusCode: number;
  constructor(statusCode: number, message: string) {
    super(message);
    this.statusCode = statusCode;
  }
}

export interface FetchLike {
  (input: string, init?: {
    method?: string;
    headers?: Record<string, string>;
    body?: string;
  }): Promise<{ ok: boolean; status: number; text(): Promise<string> }>;
}

export interface SessionRef {
  session_id: string;
  task_id: string;
  run_id: string;
  tenant_id: string;
  workspace_id: string;
}

export interface PendingApproval {
  action_digest: string;
  capability_id: string;
  proposal_id: string;
  preview: string;
  requested_at: string;
}

export interface SessionSnapshot {
  protocol_version: string;
  session: SessionRef;
  envelope_id: string;
  expected_outcome_id: string;
  status: string;
  event_sequence: number;
  message_count: number;
  pending_approval: PendingApproval | null;
  updated_at: string;
}

export interface TurnResponse {
  protocol_version: string;
  snapshot: SessionSnapshot;
  turn_id: string | null;
  text: string;
  steps: unknown[];
  stop_reason: string;
  total_tokens: number;
}

export interface SurfaceEvent {
  sequence: number;
  event_type: string;
  payload_json: string;
}

export interface EventBatch {
  protocol_version: string;
  task_id: string;
  after_sequence: number;
  next_sequence: number;
  events: SurfaceEvent[];
}

/**
 * Mirror of SurfaceEventBatch._validate_event_ownership_and_sequence
 * (packages/contracts/src/agent_os_contracts/surface.py): the resume cursor in
 * a durable event batch must agree with the events that batch carries. Callers
 * (agent_thread) resume from `next_sequence`, so accepting a self-contradictory
 * batch silently skips events or re-requests an already-applied window.
 */
function checkEventSequence(
  afterSequence: number,
  nextSequence: number,
  events: readonly SurfaceEvent[],
): void {
  let previousSequence = afterSequence;
  for (const event of events) {
    if (event.sequence <= previousSequence) {
      throw new SurfaceProtocolMismatch(
        "surface event sequences must strictly increase above after_sequence",
      );
    }
    previousSequence = event.sequence;
  }
  if (nextSequence !== previousSequence) {
    throw new SurfaceProtocolMismatch(
      "surface next_sequence must equal the last event sequence or after_sequence",
    );
  }
}

export interface ConflictProjection {
  protocol_version: string;
  action_id: string;
  lease_id: string;
  disposition: "REPLAN" | "CONFLICT" | "CANCEL";
  reason: string;
  write_scope_uris: string[];
  relevant_event_ids: string[];
  suggested_action: "REPLAN" | "REVIEW_DIFF" | "NONE";
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function checkProtocol(value: Record<string, unknown>): void {
  if (value.protocol_version !== SURFACE_PROTOCOL_VERSION) {
    throw new SurfaceProtocolMismatch(
      `local runtime protocol is not ${SURFACE_PROTOCOL_VERSION}`,
    );
  }
}

function checkSnapshot(value: Record<string, unknown>): SessionSnapshot {
  checkProtocol(value);
  if (!isObject(value.session) || typeof value.session.session_id !== "string") {
    throw new SurfaceProtocolMismatch("local runtime returned no session snapshot");
  }
  const session = value.session as unknown as SessionRef;
  const pending = isObject(value.pending_approval)
    ? (value.pending_approval as unknown as PendingApproval)
    : null;
  return {
    protocol_version: value.protocol_version as string,
    session,
    envelope_id: value.envelope_id as string,
    expected_outcome_id: value.expected_outcome_id as string,
    status: value.status as string,
    event_sequence: value.event_sequence as number,
    message_count: value.message_count as number,
    pending_approval: pending,
    updated_at: value.updated_at as string,
  };
}

function checkTurn(value: Record<string, unknown>): TurnResponse {
  checkProtocol(value);
  if (!isObject(value.snapshot)) {
    throw new SurfaceProtocolMismatch("local runtime returned no turn response");
  }
  return {
    protocol_version: value.protocol_version as string,
    snapshot: checkSnapshot(value.snapshot as Record<string, unknown>),
    turn_id: value.turn_id === null ? null : (value.turn_id as string),
    text: value.text as string,
    steps: Array.isArray(value.steps) ? (value.steps as unknown[]) : [],
    stop_reason: value.stop_reason as string,
    total_tokens: value.total_tokens as number,
  };
}

export class SurfaceClient {
  private baseUrl: string;
  private token: string;
  private fetchImpl: FetchLike;
  private sequences: Map<string, number> = new Map();

  constructor(
    baseUrl: string,
    token: string,
    fetchImpl: FetchLike = (input, init) => fetch(input, init as RequestInit),
  ) {
    this.baseUrl = baseUrl;
    this.token = token;
    this.fetchImpl = fetchImpl;
  }

  baseUrlFor(): string {
    return this.baseUrl;
  }

  tokenFor(): string {
    return this.token;
  }

  private track(sessionId: string, snapshot: SessionSnapshot): void {
    this.sequences.set(sessionId, snapshot.event_sequence);
  }

  private sequence(sessionId: string): number {
    return this.sequences.get(sessionId) ?? 0;
  }

  private async requestJson(
    method: string,
    path: string,
    payload: Record<string, unknown> | null,
  ): Promise<Record<string, unknown>> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.token}`,
      "Content-Type": "application/json",
      "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
    };
    let response;
    try {
      response = await this.fetchImpl(this.baseUrl + path, {
        method,
        headers,
        body: payload === null ? undefined : JSON.stringify(payload),
      });
    } catch (error) {
      throw new SurfaceClientConnectionError(
        `cannot reach the local runtime: ${String(error)}`,
      );
    }
    const raw = await response.text();
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const body = JSON.parse(raw) as Record<string, unknown>;
        if (typeof body.message === "string") message = body.message;
        else if (typeof body.error === "string") message = body.error;
      } catch {
        // non-JSON error body; keep the default message
      }
      if (response.status === 401) {
        throw new SurfaceClientAuthenticationError(message);
      }
      throw new SurfaceHttpError(response.status, message);
    }
    let value: unknown;
    try {
      value = JSON.parse(raw);
    } catch {
      throw new SurfaceProtocolMismatch(
        "local runtime returned a non-JSON response",
      );
    }
    if (!isObject(value)) {
      throw new SurfaceProtocolMismatch(
        "local runtime returned a non-object response",
      );
    }
    return value;
  }

  private clientRef(): Record<string, string> {
    return {
      client_id: "renderer",
      client_type: "DESKTOP",
      principal_id: "user:local",
      tenant_id: "tenant:local",
      workspace_id: "workspace:local",
      device_id: "device:renderer",
    };
  }

  async openSession(statement: string): Promise<SessionSnapshot> {
    const response = await this.requestJson("POST", "/v1/surface/sessions", {
      protocol_version: SURFACE_PROTOCOL_VERSION,
      client: this.clientRef(),
      statement,
      idempotency_key: `renderer-open-${crypto.randomUUID()}`,
      requested_at: new Date().toISOString(),
    });
    const snapshot = isObject(response.snapshot)
      ? checkSnapshot(response.snapshot as Record<string, unknown>)
      : (() => {
          throw new SurfaceProtocolMismatch(
            "local runtime returned no session snapshot",
          );
        })();
    this.track(snapshot.session.session_id, snapshot);
    return snapshot;
  }

  async getSession(sessionId: string): Promise<SessionSnapshot> {
    const response = await this.requestJson(
      "GET",
      `/v1/surface/sessions/${encodeURIComponent(sessionId)}`,
      null,
    );
    const snapshot = checkSnapshot(response);
    this.track(snapshot.session.session_id, snapshot);
    return snapshot;
  }

  async runTurn(sessionId: string, text: string): Promise<TurnResponse> {
    const response = await this.requestJson(
      "POST",
      `/v1/surface/sessions/${encodeURIComponent(sessionId)}/turns`,
      {
        protocol_version: SURFACE_PROTOCOL_VERSION,
        client: this.clientRef(),
        session_id: sessionId,
        text,
        expected_event_sequence: this.sequence(sessionId),
        idempotency_key: `renderer-turn-${crypto.randomUUID()}`,
        requested_at: new Date().toISOString(),
      },
    );
    const turn = isObject(response.turn)
      ? checkTurn(response.turn as Record<string, unknown>)
      : (() => {
          throw new SurfaceProtocolMismatch(
            "local runtime returned no turn response",
          );
        })();
    this.track(turn.snapshot.session.session_id, turn.snapshot);
    return turn;
  }

  async decideApproval(
    sessionId: string,
    actionDigest: string,
    disposition: "APPROVE" | "REJECT",
    reason: string,
  ): Promise<TurnResponse> {
    const response = await this.requestJson(
      "POST",
      `/v1/surface/sessions/${encodeURIComponent(sessionId)}/approvals`,
      {
        protocol_version: SURFACE_PROTOCOL_VERSION,
        client: this.clientRef(),
        session_id: sessionId,
        action_digest: actionDigest,
        disposition,
        reason,
        expected_event_sequence: this.sequence(sessionId),
        idempotency_key: `renderer-approve-${crypto.randomUUID()}`,
        requested_at: new Date().toISOString(),
      },
    );
    const turn = isObject(response.turn)
      ? checkTurn(response.turn as Record<string, unknown>)
      : (() => {
          throw new SurfaceProtocolMismatch(
            "local runtime returned no turn response",
          );
        })();
    this.track(turn.snapshot.session.session_id, turn.snapshot);
    return turn;
  }

  async pause(sessionId: string, reason = "paused by user"): Promise<SessionSnapshot> {
    return this.control(sessionId, "pause", reason);
  }

  async resume(sessionId: string, reason = "resumed by user"): Promise<SessionSnapshot> {
    return this.control(sessionId, "resume", reason);
  }

  async correct(sessionId: string, reason: string): Promise<SessionSnapshot> {
    return this.control(sessionId, "correction", reason);
  }

  private async control(
    sessionId: string,
    action: string,
    reason: string,
  ): Promise<SessionSnapshot> {
    const response = await this.requestJson(
      "POST",
      `/v1/surface/sessions/${encodeURIComponent(sessionId)}/${action}`,
      {
        protocol_version: SURFACE_PROTOCOL_VERSION,
        client: this.clientRef(),
        session_id: sessionId,
        reason,
        expected_event_sequence: this.sequence(sessionId),
        idempotency_key: `renderer-${action}-${crypto.randomUUID()}`,
        requested_at: new Date().toISOString(),
      },
    );
    const snapshot = isObject(response.snapshot)
      ? checkSnapshot(response.snapshot as Record<string, unknown>)
      : (() => {
          throw new SurfaceProtocolMismatch(
            "local runtime returned no session snapshot",
          );
        })();
    this.track(sessionId, snapshot);
    return snapshot;
  }

  async events(
    taskId: string,
    afterSequence = 0,
    waitMs = 0,
  ): Promise<EventBatch> {
    let response;
    try {
      response = await this.fetchImpl(
        `${this.baseUrl}/v1/surface/tasks/${encodeURIComponent(taskId)}/events?after=${afterSequence}&wait_ms=${waitMs}`,
        {
          method: "GET",
          headers: {
            Authorization: `Bearer ${this.token}`,
            "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
          },
        },
      );
    } catch (error) {
      throw new SurfaceClientConnectionError(
        `cannot reach the local runtime: ${String(error)}`,
      );
    }
    const body = await response.text();
    if (!response.ok) {
      if (response.status === 401) {
        throw new SurfaceClientAuthenticationError("local runtime authentication failed");
      }
      throw new SurfaceHttpError(response.status, `HTTP ${response.status}`);
    }
    return parseSse(taskId, afterSequence, body);
  }

  async conflict(sessionId: string): Promise<ConflictProjection | null> {
    let response;
    try {
      response = await this.fetchImpl(
        `${this.baseUrl}/v1/surface/sessions/${encodeURIComponent(sessionId)}/conflict`,
        {
          method: "GET",
          headers: {
            Authorization: `Bearer ${this.token}`,
            "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
          },
        },
      );
    } catch (error) {
      throw new SurfaceClientConnectionError(
        `cannot reach the local runtime: ${String(error)}`,
      );
    }
    const raw = await response.text();
    if (response.status === 404) {
      return null;
    }
    if (!response.ok) {
      throw new SurfaceHttpError(response.status, `HTTP ${response.status}`);
    }
    let value: unknown;
    try {
      value = JSON.parse(raw);
    } catch {
      throw new SurfaceProtocolMismatch(
        "local runtime returned a non-JSON response",
      );
    }
    if (!isObject(value) || !isObject(value.conflict)) {
      throw new SurfaceProtocolMismatch(
        "local runtime returned no conflict projection",
      );
    }
    return checkConflict(value.conflict as Record<string, unknown>);
  }
}

function checkConflict(value: Record<string, unknown>): ConflictProjection {
  checkProtocol(value);
  const disposition = value.disposition;
  const suggested = value.suggested_action;
  if (
    disposition !== "REPLAN" &&
    disposition !== "CONFLICT" &&
    disposition !== "CANCEL"
  ) {
    throw new SurfaceProtocolMismatch("conflict projection has invalid disposition");
  }
  if (
    suggested !== "REPLAN" &&
    suggested !== "REVIEW_DIFF" &&
    suggested !== "NONE"
  ) {
    throw new SurfaceProtocolMismatch("conflict projection has invalid suggested_action");
  }
  return {
    protocol_version: value.protocol_version as string,
    action_id: value.action_id as string,
    lease_id: value.lease_id as string,
    disposition,
    reason: value.reason as string,
    write_scope_uris: Array.isArray(value.write_scope_uris)
      ? (value.write_scope_uris as string[])
      : [],
    relevant_event_ids: Array.isArray(value.relevant_event_ids)
      ? (value.relevant_event_ids as string[])
      : [],
    suggested_action: suggested,
  };
}

export function parseSse(
  taskId: string,
  afterSequence: number,
  body: string,
): EventBatch {
  const events: SurfaceEvent[] = [];
  let currentId: number | null = null;
  const dataLines: string[] = [];
  let inCursor = false;
  let nextSequence = afterSequence;
  const flush = (): void => {
    if (inCursor) {
      const cursor = JSON.parse(dataLines.join("\n")) as {
        next_sequence: number;
      };
      nextSequence = cursor.next_sequence;
      inCursor = false;
    } else if (currentId !== null && dataLines.length > 0) {
      const payload = JSON.parse(dataLines.join("\n")) as {
        event_type: string;
        payload_json: string;
      };
      events.push({
        sequence: currentId,
        event_type: payload.event_type,
        payload_json: payload.payload_json,
      });
    }
    currentId = null;
    dataLines.length = 0;
  };
  for (const line of body.split(/\r?\n/)) {
    if (line.startsWith("id: ")) {
      currentId = Number.parseInt(line.slice(4), 10);
    } else if (line.startsWith("event: cursor")) {
      inCursor = true;
      dataLines.length = 0;
    } else if (line.startsWith("data: ")) {
      dataLines.push(line.slice(6));
    } else if (line === "") {
      flush();
    }
  }
  // EOF flush, mirroring apps/cli/surface_client.py `_decode_sse` and
  // apps/cli-ts/src/sse.ts: a frame is normally terminated by a blank line, but
  // a body that ends mid-frame must be decoded all the same. Dropping the final
  // cursor left next_sequence at after_sequence; a truncated payload still
  // fails closed because JSON.parse rejects it.
  flush();
  checkEventSequence(afterSequence, nextSequence, events);
  return {
    protocol_version: SURFACE_PROTOCOL_VERSION,
    task_id: taskId,
    after_sequence: afterSequence,
    next_sequence: nextSequence,
    events,
  };
}
