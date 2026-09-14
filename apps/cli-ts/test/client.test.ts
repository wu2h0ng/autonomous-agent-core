/**
 * Hermetic contract tests for the TS SurfaceClient against a mock server
 * that speaks surface protocol v1.1 wire shapes (recorded from the M2 frozen
 * contracts). A constant/shape-breaking server must fail these tests.
 */
import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import test from "node:test";
import {
  SurfaceClient,
  SurfaceClientAuthenticationError,
  SurfaceStreamStaleError,
} from "../src/client.js";
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
      assert.equal(command.protocol_version, "1.1");
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
