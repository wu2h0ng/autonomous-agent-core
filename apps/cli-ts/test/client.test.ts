/**
 * Hermetic contract tests for the TS SurfaceClient against a mock server
 * that speaks surface protocol v1.1 wire shapes (recorded from the M2 frozen
 * contracts). A constant/shape-breaking server must fail these tests.
 */
import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import test from "node:test";
import { SurfaceClient, SurfaceClientAuthenticationError, SurfaceStreamStaleError } from "../src/client.js";
import { SURFACE_PROTOCOL_VERSION } from "../src/contracts.js";
import type { RuntimeDescriptor } from "../src/descriptor.js";

const TOKEN = "test-token";

function snapshot(sessionId: string, sequence: number) {
  return {
    protocol_version: "1.1",
    session: {
      session_id: sessionId,
      task_id: "task:1",
      run_id: "run:1",
      tenant_id: "tenant:local",
      workspace_id: "workspace:local",
    },
    envelope_id: "env:1",
    expected_outcome_id: "outcome:1",
    status: "ACTIVE",
    event_sequence: sequence,
    message_count: sequence,
    pending_approval: null,
    permission_mode: "ASK",
    updated_at: new Date().toISOString(),
  };
}

async function withServer(
  handler: (req: { url: string; method: string; body?: string; auth: string | null }) => {
    status: number;
    json?: unknown;
    sse?: string;
  },
  run: (client: SurfaceClient) => Promise<void>,
): Promise<void> {
  const server: Server = createServer((req, res) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      const result = handler({
        url: req.url ?? "",
        method: req.method ?? "",
        auth: req.headers.authorization ?? null,
        ...(body ? { body } : {}),
      });
      res.statusCode = result.status;
      if (result.sse !== undefined) {
        res.setHeader("content-type", "text/event-stream");
        res.end(result.sse);
      } else {
        res.setHeader("content-type", "application/json");
        res.end(JSON.stringify(result.json ?? {}));
      }
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (address === null || typeof address === "string") throw new Error("no address");
  const descriptor = {
    protocol_version: "1.1",
    pid: 1,
    boot_id: "boot:test",
    host: "127.0.0.1",
    port: address.port,
    bearer_token: TOKEN,
    database_path: "/tmp/db",
    workspace_path: "/tmp/ws",
    created_at: new Date().toISOString(),
    baseUrl: `http://127.0.0.1:${address.port}`,
  } as RuntimeDescriptor;
  try {
    await run(new SurfaceClient(descriptor));
  } finally {
    server.close();
  }
}

test("openSession sends protocol version + bearer and tracks sequence", async () => {
  await withServer(
    (req) => {
      assert.equal(req.auth, `Bearer ${TOKEN}`);
      const command = JSON.parse(req.body ?? "{}");
      // Compared against the declared constant, not a literal: pinning a
      // version here is what made the 1.1 -> 1.2 bump a test edit instead of a
      // contract change.
      assert.equal(command.protocol_version, SURFACE_PROTOCOL_VERSION);
      assert.equal(command.client.client_type, "CLI");
      assert.ok(command.idempotency_key.length > 0);
      return { status: 200, json: { snapshot: snapshot("s:1", 3) } };
    },
    async (client) => {
      const snap = await client.openSession("hello");
      assert.equal(snap.session.session_id, "s:1");
      assert.equal(snap.event_sequence, 3);
    },
  );
});

test("401 maps to authentication error without leaking the token", async () => {
  await withServer(
    () => ({ status: 401, json: { message: "bad token" } }),
    async (client) => {
      await assert.rejects(
        () => client.openSession("hello"),
        (error: unknown) => {
          assert.ok(error instanceof SurfaceClientAuthenticationError);
          assert.ok(!error.message.includes(TOKEN));
          return true;
        },
      );
    },
  );
});

test("begin-turn carries the pre-subscribed stream binding", async () => {
  await withServer(
    (req) => {
      if (req.url?.endsWith("/streams")) {
        return {
          status: 200,
          json: {
            subscription: {
              protocol_version: "1.1",
              runtime_boot_id: "boot:1",
              stream_id: "stream:1",
            },
          },
        };
      }
      if (req.url?.endsWith("/begin-turn")) {
        const command = JSON.parse(req.body ?? "{}");
        assert.deepEqual(command.stream, { runtime_boot_id: "boot:1", stream_id: "stream:1" });
        assert.equal(command.expected_event_sequence, 0);
        return {
          status: 200,
          json: { begin_turn: { protocol_version: "1.1", turn_id: "turn:1", stream_id: "stream:1" } },
        };
      }
      throw new Error(`unexpected ${req.url}`);
    },
    async (client) => {
      const sub = await client.subscribeStream("s:1");
      const begin = await client.beginTurn("s:1", "do it", {
        runtime_boot_id: sub.runtime_boot_id,
        stream_id: sub.stream_id,
      });
      assert.equal(begin.turn_id, "turn:1");
    },
  );
});

test("stream frames decode chunks + cursor; 410 maps to stale error", async () => {
  const sseBody = [
    `event: frame`,
    `data: ${JSON.stringify({ kind: "CHUNK", runtime_boot_id: "boot:1", stream_id: "stream:1", turn_id: "turn:1", frame_sequence: 1, payload: { text: "he" } })}`,
    ``,
    `event: frame`,
    `data: ${JSON.stringify({ kind: "CHUNK", runtime_boot_id: "boot:1", stream_id: "stream:1", turn_id: "turn:1", frame_sequence: 2, payload: { text: "llo" } })}`,
    ``,
    `event: cursor`,
    `data: ${JSON.stringify({ next_sequence: 2 })}`,
    ``,
  ].join("\n");

  await withServer(
    (req) => {
      if (req.url?.includes("after=0")) return { status: 200, sse: sseBody };
      if (req.url?.includes("after=2")) {
        return {
          status: 200,
          sse: `event: frame\ndata: ${JSON.stringify({ kind: "STREAM_END", runtime_boot_id: "boot:1", stream_id: "stream:1", turn_id: "turn:1", frame_sequence: 3, payload: {} })}\n\nevent: cursor\ndata: {"next_sequence": 3}\n\n`,
        };
      }
      throw new Error(`unexpected ${req.url}`);
    },
    async (client) => {
      const binding = { runtime_boot_id: "boot:1", stream_id: "stream:1" };
      let text = "";
      let ended = false;
      for await (const frame of client.followStream("s:1", binding, { pollMs: 1 })) {
        if (frame.kind === "CHUNK") text += (frame.payload as { text: string }).text;
        if (frame.kind === "STREAM_END") ended = true;
      }
      assert.equal(text, "hello");
      assert.ok(ended);
    },
  );

  await withServer(
    () => ({ status: 410, json: { message: "stream gone" } }),
    async (client) => {
      await assert.rejects(
        () =>
          client.streamFrames("s:1", { runtime_boot_id: "boot:dead", stream_id: "stream:old" }, 0, 0),
        SurfaceStreamStaleError,
      );
    },
  );
});

test("gap frame contract: turn-bound gap is rejected client-side", async () => {
  const badGap = `event: frame\ndata: ${JSON.stringify({ kind: "GAP", runtime_boot_id: "boot:1", stream_id: "stream:1", turn_id: "turn:1", frame_sequence: 5, gap_from: 2, gap_to: 4, payload: {} })}\n\nevent: cursor\ndata: {"next_sequence": 5}\n\n`;
  await withServer(
    () => ({ status: 200, sse: badGap }),
    async (client) => {
      await assert.rejects(() =>
        client.streamFrames("s:1", { runtime_boot_id: "boot:1", stream_id: "stream:1" }, 0, 0),
      );
    },
  );
});

test("followStream persists the cursor per binding: a second turn never replays turn-1 frames", async () => {
  const requests: string[] = [];
  const frame = (seq: number, turn: string, kind: string) =>
    `event: frame\ndata: ${JSON.stringify({ kind, runtime_boot_id: "boot:1", stream_id: "stream:1", turn_id: turn, frame_sequence: seq, payload: kind === "CHUNK" ? { delta: `t1-${seq}` } : {} })}\n\n`;
  await withServer(
    (req) => {
      requests.push(req.url ?? "");
      if (req.url?.includes("after=0")) {
        return { status: 200, sse: frame(1, "turn:1", "CHUNK") + frame(2, "turn:1", "STREAM_END") + `event: cursor\ndata: {"next_sequence": 2}\n\n` };
      }
      if (req.url?.includes("after=2")) {
        return { status: 200, sse: frame(3, "turn:2", "CHUNK") + frame(4, "turn:2", "STREAM_END") + `event: cursor\ndata: {"next_sequence": 4}\n\n` };
      }
      throw new Error(`unexpected ${req.url}`);
    },
    async (client) => {
      const binding = { runtime_boot_id: "boot:1", stream_id: "stream:1" };
      const turn1: string[] = [];
      for await (const f of client.followStream("s:1", binding, { pollMs: 1 })) turn1.push(f.turn_id ?? "");
      assert.deepEqual(turn1, ["turn:1", "turn:1"]);
      const turn2: string[] = [];
      for await (const f of client.followStream("s:1", binding, { pollMs: 1 })) turn2.push(f.turn_id ?? "");
      assert.deepEqual(turn2, ["turn:2", "turn:2"]);
      assert.ok(requests[1]?.includes("after=2"), "second followStream must resume at the persisted cursor");
    },
  );
});

test("providerStatus reads the redacted provider status", async () => {
  await withServer(
    (req) => {
      assert.equal(req.method, "GET");
      assert.equal(req.url, "/v1/surface/provider");
      return {
        status: 200,
        json: {
          provider: {
            protocol_version: "1.1",
            configured: true,
            provider_id: "openai-compatible",
            model_id: "deepseek-chat",
            endpoint_class: "openai-compatible",
            credential_ref_id: "credential:local:1",
            base_url: "https://api.deepseek.com/v1",
          },
        },
      };
    },
    async (client) => {
      const status = await client.providerStatus();
      assert.equal(status.configured, true);
      assert.equal(status.model_id, "deepseek-chat");
      assert.equal(status.base_url, "https://api.deepseek.com/v1");
    },
  );
});

test("configureProvider posts the command and never echoes the key", async () => {
  const secret = "sk-test-do-not-echo";
  await withServer(
    (req) => {
      assert.equal(req.method, "POST");
      assert.equal(req.url, "/v1/surface/provider");
      const body = JSON.parse(req.body ?? "{}") as Record<string, unknown>;
      assert.equal(body.base_url, "https://api.deepseek.com/v1");
      assert.equal(body.model, "deepseek-chat");
      assert.equal(body.api_key, secret);
      assert.equal(body.endpoint_class, "openai-compatible");
      return {
        status: 200,
        json: {
          provider: {
            protocol_version: "1.1",
            configured: true,
            provider_id: "openai-compatible",
            model_id: "deepseek-chat",
            endpoint_class: "openai-compatible",
            credential_ref_id: "credential:local:1",
            base_url: "https://api.deepseek.com/v1",
          },
        },
      };
    },
    async (client) => {
      const status = await client.configureProvider({
        baseUrl: "https://api.deepseek.com/v1",
        model: "deepseek-chat",
        apiKey: secret,
      });
      assert.equal(status.configured, true);
      assert.ok(!JSON.stringify(status).includes(secret));
    },
  );
});

test("clearProvider posts to the provider clear route", async () => {
  await withServer(
    (req) => {
      assert.equal(req.method, "POST");
      assert.equal(req.url, "/v1/surface/provider/clear");
      return {
        status: 200,
        json: {
          provider: {
            protocol_version: "1.1",
            configured: true,
            persisted: false,
            key_source: "env",
          },
        },
      };
    },
    async (client) => {
      const status = await client.clearProvider();
      assert.equal(status.persisted, false);
    },
  );
});

test("providerMetrics reads the aggregated, content-free window", async () => {
  const payload = {
    schema_version: "1.0",
    source: "log_file",
    taken_at: new Date().toISOString(),
    window_records: 3,
    calls: 2,
    attempts: 3,
    responses: 2,
    failures: 1,
    retries: 1,
    latency: { samples: 3, mean_ms: 20, p50_ms: 10, p90_ms: 40, p95_ms: 40, max_ms: 40 },
    tokens: { input_tokens: 3, output_tokens: 6, total_tokens: 9, usage_samples: 2 },
    failure_categories: [{ code: "RATE_LIMITED", count: 1, retryable: true }],
    rate_limit: {
      rate_limited_attempts: 1,
      retry_after_observed: 1,
      max_retry_after_seconds: 2,
      local_waits: 1,
      local_wait_ms_total: 2000,
      local_wait_ms_max: 2000,
      local_rejections: 0,
    },
  };
  await withServer(
    (req) => {
      assert.equal(req.method, "GET");
      assert.equal(req.url, "/v1/surface/observability/metrics?source=log");
      assert.equal(req.body, undefined, "the metrics read is a plain GET");
      assert.equal(req.auth, `Bearer ${TOKEN}`);
      return { status: 200, json: { metrics: payload } };
    },
    async (client) => {
      const metrics = await client.providerMetrics("log");
      assert.equal(metrics.source, "log_file");
      assert.equal(metrics.attempts, 3);
      assert.equal(metrics.failure_categories[0]?.code, "RATE_LIMITED");
      assert.equal(metrics.rate_limit.local_waits, 1);
    },
  );
});

test("providerMetrics defaults to the process window and rejects a malformed body", async () => {
  await withServer(
    (req) => {
      assert.equal(req.url, "/v1/surface/observability/metrics?source=process");
      return { status: 200, json: { metrics: { source: "in_process" } } };
    },
    async (client) => {
      await assert.rejects(() => client.providerMetrics());
    },
  );
});

test("getReadOnly issues a GET with no body (read-only projections only)", async () => {
  const seen: { method: string; body?: string; auth: string | null }[] = [];
  await withServer(
    (req) => {
      seen.push({ method: req.method, ...(req.body ? { body: req.body } : {}), auth: req.auth });
      return { status: 200, json: { mandates: [] } };
    },
    async (client) => {
      const body = await client.getReadOnly("/v1/mandates");
      assert.deepEqual(body, { mandates: [] });
    },
  );
  assert.equal(seen[0]?.method, "GET");
  assert.equal(seen[0]?.body, undefined);
  assert.equal(seen[0]?.auth, `Bearer ${TOKEN}`);
});

function childRollup(sessionId: string) {
  return {
    protocol_version: "1.2",
    session_id: sessionId,
    children_included_in_totals: true,
    turns: [
      {
        parent_session_id: sessionId,
        parent_turn_id: "turn-1",
        children: [
          {
            spawn_id: "spawn-1",
            child_session_id: "child-1",
            child_task_id: "ctask-1",
            agent_type: "explorer",
            description: "d",
            status: "stopped",
            steps: 0,
            tokens: 0,
            stop_reason: null,
          },
        ],
      },
    ],
    in_flight: [
      { spawn_id: "spawn-1", child_session_id: "child-1", parent_turn_id: "turn-1" },
    ],
    orphaned: [],
    buried: [],
  };
}

test("childAgents GETs the roll-up and exposes the in-flight (stoppable) set", async () => {
  const seen: { method: string; url: string; body?: string }[] = [];
  await withServer(
    (req) => {
      seen.push({ method: req.method, url: req.url, ...(req.body ? { body: req.body } : {}) });
      return { status: 200, json: childRollup("parent-1") };
    },
    async (client) => {
      const rollup = await client.childAgents("parent-1");
      assert.equal(rollup.session_id, "parent-1");
      assert.equal(rollup.in_flight[0]?.child_session_id, "child-1");
      assert.equal(rollup.turns[0]?.children[0]?.child_session_id, "child-1");
    },
  );
  assert.equal(seen[0]?.method, "GET");
  assert.equal(seen[0]?.url, "/v1/surface/sessions/parent-1/children");
  assert.equal(seen[0]?.body, undefined);
});

test("stopChildAgent POSTs the per-child stop command with route scope + idempotency key", async () => {
  const seen: { method: string; url: string; body?: string }[] = [];
  await withServer(
    (req) => {
      seen.push({ method: req.method, url: req.url, ...(req.body ? { body: req.body } : {}) });
      return { status: 200, json: childRollup("parent-1") };
    },
    async (client) => {
      const rollup = await client.stopChildAgent("parent-1", "child-1");
      assert.equal(rollup.session_id, "parent-1");
    },
  );
  assert.equal(seen[0]?.method, "POST");
  assert.equal(seen[0]?.url, "/v1/surface/sessions/parent-1/children/stop");
  const body = JSON.parse(seen[0]?.body ?? "{}") as Record<string, unknown>;
  assert.equal(body.session_id, "parent-1");
  assert.equal(body.child_session_id, "child-1");
  assert.equal(body.reason, "stopped_by_operator");
  assert.equal(typeof body.idempotency_key, "string");
  assert.equal(typeof body.requested_at, "string");
  assert.equal(body.protocol_version, SURFACE_PROTOCOL_VERSION);
  const clientRef = body.client as Record<string, unknown>;
  assert.equal(clientRef.client_type, "CLI");
  assert.equal(clientRef.principal_id, "user:local");
  assert.equal(clientRef.tenant_id, "tenant:local");
  assert.equal(clientRef.workspace_id, "workspace:local");
  assert.equal(typeof clientRef.client_id, "string");
  assert.equal(typeof clientRef.device_id, "string");
});

const TASK_ID = "task:1";

function durableEvent(sequence: number, taskId = TASK_ID) {
  return {
    event_id: `event:${sequence}`,
    task_id: taskId,
    event_type: "SESSION_MESSAGE_RECORDED",
    payload_json: "{}",
    occurred_at: "2026-08-12T00:00:00+00:00",
    sequence,
  };
}

function eventFrame(event: ReturnType<typeof durableEvent>): string {
  return `id: ${event.sequence}\nevent: ${event.event_type}\ndata: ${JSON.stringify(event)}\n\n`;
}

function cursorFrame(nextSequence: number, terminate = true): string {
  return `event: cursor\ndata: ${JSON.stringify({ next_sequence: nextSequence })}${terminate ? "\n\n" : ""}`;
}

/** The contract messages the Python model raises, mirrored verbatim in TS. */
const NEXT_SEQUENCE_MESSAGE =
  "surface next_sequence must equal the last event sequence or after_sequence";
const INCREASING_MESSAGE =
  "surface event sequences must strictly increase above after_sequence";
const OWNERSHIP_MESSAGE = "surface events must belong to the requested task";

function contractMessages(error: unknown): string {
  const issues = (error as { issues?: Array<{ message: string }> } | null)?.issues ?? [];
  return issues.map((issue) => issue.message).join(" | ");
}

test("durable events batch: a cursor that disagrees with its events is rejected", async () => {
  // Corpus shape 11_cursor_then_event_midframe: the cursor claims 5 while the
  // batch only carries event 2. Python raises ValidationError here; accepting it
  // would let the caller resume from a window that never existed.
  const sse = cursorFrame(5) + eventFrame(durableEvent(2));
  await withServer(
    (req) => {
      assert.equal(req.url, `/v1/surface/tasks/${TASK_ID}/events?after=0&wait_ms=0`);
      return { status: 200, sse };
    },
    async (client) => {
      await assert.rejects(
        () => client.events(TASK_ID, 0, 0),
        (error: unknown) => {
          assert.equal((error as Error).name, "ZodError");
          assert.ok(contractMessages(error).includes(NEXT_SEQUENCE_MESSAGE));
          return true;
        },
      );
    },
  );
});

test("durable events batch: a cursor-only frame cannot advance with no events", async () => {
  // Corpus shape 04_cursor_half_frame: cursor 7, no events, after 0. Python
  // raises ValidationError; a client that trusts the cursor re-requests an
  // empty window forever at the wrong position.
  await withServer(
    () => ({ status: 200, sse: cursorFrame(7, false) }),
    async (client) => {
      await assert.rejects(
        () => client.events(TASK_ID, 0, 0),
        (error: unknown) => {
          assert.ok(contractMessages(error).includes(NEXT_SEQUENCE_MESSAGE));
          return true;
        },
      );
    },
  );
});

test("durable events batch: events at or below after_sequence are rejected", async () => {
  await withServer(
    () => ({ status: 200, sse: eventFrame(durableEvent(3)) + cursorFrame(3) }),
    async (client) => {
      await assert.rejects(
        () => client.events(TASK_ID, 3, 0),
        (error: unknown) => {
          assert.ok(contractMessages(error).includes(INCREASING_MESSAGE));
          return true;
        },
      );
    },
  );
});

test("durable events batch: an event owned by another task is rejected", async () => {
  await withServer(
    () => ({ status: 200, sse: eventFrame(durableEvent(1, "task:other")) + cursorFrame(1) }),
    async (client) => {
      await assert.rejects(
        () => client.events(TASK_ID, 0, 0),
        (error: unknown) => {
          assert.ok(contractMessages(error).includes(OWNERSHIP_MESSAGE));
          return true;
        },
      );
    },
  );
});

test("durable events batch: a consistent batch still decodes unchanged", async () => {
  // Positive control for the new validation: the frozen wire shape (event 1 +
  // cursor 1) and an empty batch at the read cursor must both keep working.
  await withServer(
    () => ({ status: 200, sse: eventFrame(durableEvent(1)) + cursorFrame(1) }),
    async (client) => {
      const batch = await client.events(TASK_ID, 0, 0);
      assert.equal(batch.next_sequence, 1);
      assert.deepEqual(
        batch.events.map((event) => event.sequence),
        [1],
      );
    },
  );

  await withServer(
    () => ({ status: 200, sse: `${cursorFrame(4)}\n` }),
    async (client) => {
      const batch = await client.events(TASK_ID, 4, 0);
      assert.equal(batch.after_sequence, 4);
      assert.equal(batch.next_sequence, 4);
      assert.deepEqual(batch.events, []);
    },
  );
});
