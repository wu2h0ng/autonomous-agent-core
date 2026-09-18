/**
 * `/trace` — the durable record of one governed turn, as spans.
 *
 * What these tests protect, in order of importance:
 *
 * 1. the panel renders what the projection says and nothing else: a turn the log
 *    never closed, an unresolved dispatch and an undetermined effect must read as
 *    missing evidence rather than as a complete-looking timeline;
 * 2. the panel never prints content. The payload is a projection (ids, enums,
 *    sequences), but the renderer must not become the leak: a payload that
 *    additionally carries a prompt, a completion or a credential must not put any
 *    of them on screen (the daemon's own leak test is in
 *    tests/product/test_turn_trace.py);
 * 3. the client reads the route as a plain GET with `turn_id` only when asked,
 *    and rejects a body that is not a trace instead of rendering half of it.
 */
import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import test from "node:test";
import { SurfaceClient } from "../src/client.js";
import { TuiController, tracePanel } from "../src/controller.js";
import type { RuntimeDescriptor } from "../src/descriptor.js";
import type { TurnTrace } from "../src/contracts.js";

const TOKEN = "test-token";

function trace(overrides: Partial<TurnTrace> = {}): TurnTrace {
  return {
    schema_version: "1.0",
    task_id: "task:1",
    session_id: "s:1",
    turn_id: "turn:1",
    state: "COMPLETE",
    stop_reason: "completed",
    started_sequence: 9,
    started_at: "2026-09-18T10:00:00+00:00",
    ended_sequence: 24,
    ended_at: "2026-09-18T10:00:05+00:00",
    records_scanned: 24,
    first_sequence: 1,
    last_sequence: 24,
    spans: [
      {
        span_id: "TURN:turn:1:9",
        kind: "TURN",
        status: "COMPLETED",
        started_by: "TURN_STARTED",
        started_sequence: 9,
        started_at: "2026-09-18T10:00:00+00:00",
        ended_by: "TURN_COMPLETED",
        ended_sequence: 24,
        ended_at: "2026-09-18T10:00:05+00:00",
        link: "ROOT",
        parent_span_id: "TURN:turn:1:9",
        session_id: "s:1",
        turn_id: "turn:1",
        reason_codes: [],
        stop_reason: "completed",
        event_sequences: [9, 24],
      },
      {
        span_id: "CAPABILITY_DISPATCH:action:1:12",
        kind: "CAPABILITY_DISPATCH",
        status: "REJECTED",
        started_by: "ACTION_PROPOSED",
        started_sequence: 12,
        started_at: "2026-09-18T10:00:02+00:00",
        ended_by: "APPROVAL_REJECTED",
        ended_sequence: 13,
        ended_at: "2026-09-18T10:00:02.5+00:00",
        link: "ACTION_ID",
        parent_span_id: "TURN:turn:1:9",
        session_id: "s:1",
        turn_id: "turn:1",
        capability_id: "workspace.edit",
        reason_codes: [],
        event_sequences: [12, 13],
      },
      {
        span_id: "POLICY_VERDICT:digest:29",
        kind: "POLICY_VERDICT",
        status: "DENIED",
        started_by: "POLICY_VERDICT_RECORDED",
        started_sequence: 29,
        started_at: "2026-09-18T10:00:06+00:00",
        ended_by: "POLICY_VERDICT_RECORDED",
        ended_sequence: 29,
        ended_at: "2026-09-18T10:00:06+00:00",
        link: "SEQUENCE_WINDOW",
        parent_span_id: "TURN:turn:1:9",
        session_id: "s:1",
        turn_id: "turn:1",
        capability_id: "data_agent.run_sql",
        verdict: "DENY",
        basis: "out_of_allowlist",
        reason_codes: [],
        event_sequences: [29],
      },
    ],
    gaps: [],
    ...overrides,
  };
}

test("tracePanel renders each span with its durable basis and status", () => {
  const panel = tracePanel(trace());
  assert.equal(panel.title, "turn trace");
  const rendered = panel.lines.join("\n");
  assert.match(rendered, /turn\s+turn:1\s+COMPLETE/);
  assert.match(rendered, /stop\s+completed/);
  assert.match(rendered, /window\s+records 1\.\.24 \(24 scanned, 3 span\(s\), 0 gap\(s\)\)/);
  assert.match(rendered, /#9 TURN COMPLETED/);
  assert.match(rendered, /#12 CAPABILITY_DISPATCH REJECTED\s+workspace\.edit/);
  // A denial is never dropped, and a positionally-linked span says so.
  assert.match(rendered, /#29 POLICY_VERDICT DENIED\s+data_agent\.run_sql DENY basis=out_of_allowlist \(positional\)/);
  assert.match(rendered, /note\s+1 span\(s\) placed by sequence window only/);
});

test("tracePanel states an open turn and every gap instead of closing them", () => {
  const panel = tracePanel(
    trace({
      state: "OPEN",
      stop_reason: null,
      ended_sequence: null,
      ended_at: null,
      spans: [
        {
          ...trace().spans[0]!,
          status: "OPEN",
          ended_by: "OPEN_NO_TERMINAL_RECORD",
          ended_sequence: null,
          ended_at: null,
          stop_reason: null,
        },
      ],
      gaps: [
        {
          kind: "TURN_OPEN",
          sequence: 9,
          subject: "turn:1",
          detail: "the durable log holds no SESSION_TURN_COMPLETED for this turn",
        },
        {
          kind: "EFFECT_UNDETERMINED",
          sequence: 15,
          subject: "action:1",
          detail: "the dispatched effect is UNKNOWN in durable truth",
        },
      ],
    }),
  );
  const rendered = panel.lines.join("\n");
  assert.match(rendered, /turn\s+turn:1\s+OPEN/);
  assert.match(rendered, /stop\s+unknown \(no SESSION_TURN_COMPLETED in the log\)/);
  assert.match(rendered, /gap\s+TURN_OPEN @9\s+.*\[turn:1\]/);
  assert.match(rendered, /gap\s+EFFECT_UNDETERMINED @15/);
});

test("tracePanel prints only projection fields, never payload content", () => {
  // A hostile payload: every content-bearing key the durable records do carry,
  // smuggled alongside the projection the daemon actually sends.
  const hostile = {
    ...trace(),
    user_text: "SECRET-PROMPT-TEXT",
    preview: "SECRET-PREVIEW-TEXT",
    api_key: "sk-DEADBEEF",
    spans: trace().spans.map((span) => ({
      ...span,
      text: "SECRET-COMPLETION-TEXT",
      arguments_json: '{"path":"/etc/passwd"}',
    })),
  };
  const rendered = tracePanel(hostile as TurnTrace).lines.join("\n");

  for (const secret of [
    "SECRET-PROMPT-TEXT",
    "SECRET-PREVIEW-TEXT",
    "sk-DEADBEEF",
    "SECRET-COMPLETION-TEXT",
    "/etc/passwd",
  ]) {
    assert.equal(rendered.includes(secret), false, `${secret} must not be rendered`);
  }
});

test("tracePanel bounds its rows rather than dumping an unbounded timeline", () => {
  const spans = Array.from({ length: 45 }, (_unused, index) => ({
    ...trace().spans[0]!,
    span_id: `TURN:turn:1:${index + 1}`,
    started_sequence: index + 1,
  }));
  const panel = tracePanel(trace({ spans }));
  const rendered = panel.lines.join("\n");
  assert.match(rendered, /… 5 more span\(s\) not shown/);
  assert.equal(panel.lines.filter((line) => /^span\s+#/.test(line)).length, 40);
});

async function withServer(
  handler: (req: { url: string; method: string; body?: string }) => {
    status: number;
    json?: unknown;
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
        ...(body ? { body } : {}),
      });
      res.statusCode = result.status;
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify(result.json));
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
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

test("turnTrace is a plain GET of the session's trace, with turn_id only when given", async () => {
  await withServer(
    (req) => {
      assert.equal(req.method, "GET");
      assert.equal(req.body, undefined, "the trace read sends no body");
      assert.equal(req.url, "/v1/surface/sessions/s%3A1/trace");
      return { status: 200, json: { trace: trace({ state: "OPEN", stop_reason: null }) } };
    },
    async (client) => {
      const projected = await client.turnTrace("s:1");
      assert.equal(projected.state, "OPEN");
      assert.equal(projected.spans.length, 3);
    },
  );

  await withServer(
    (req) => {
      assert.equal(req.url, "/v1/surface/sessions/s%3A1/trace?turn_id=turn%3A1");
      return { status: 200, json: { trace: trace() } };
    },
    async (client) => {
      const projected = await client.turnTrace("s:1", "turn:1");
      assert.equal(projected.turn_id, "turn:1");
    },
  );
});

test("turnTrace rejects a body that is not a trace instead of rendering part of it", async () => {
  await withServer(
    () => ({ status: 200, json: { trace: { turn_id: "turn:1" } } }),
    async (client) => {
      await assert.rejects(() => client.turnTrace("s:1"));
    },
  );
});

test("turnTrace surfaces the daemon's typed 404 for an unknown turn", async () => {
  await withServer(
    () => ({
      status: 404,
      json: { error: "TurnTraceNotFoundError", message: "session 's:1' has no turn 'turn:nope'" },
    }),
    async (client) => {
      await assert.rejects(
        () => client.turnTrace("s:1", "turn:nope"),
        /has no turn 'turn:nope'/,
      );
    },
  );
});

test("/trace renders the last turn's spans; a failure is reported, not faked", async () => {
  const calls: (string | undefined)[] = [];
  let failure: Error | null = null;
  const client = {
    async turnTrace(_sessionId: string, turnId?: string) {
      calls.push(turnId);
      if (failure) throw failure;
      return trace();
    },
  };
  const controller = new TuiController(client as never);

  await controller.submit("/trace");
  assert.match(
    controller.messages.at(-1)?.content ?? "",
    /no session: \/trace needs an open session/,
  );

  (controller as never as { sessionId: string | null }).sessionId = "s:1";
  await controller.submit("/trace");
  const panel = controller.messages.at(-1)?.panel;
  assert.ok(panel, "the trace panel is pushed");
  assert.equal(panel.title, "turn trace");
  assert.equal(calls.at(-1), undefined, "no turn id means the most recent turn");

  await controller.submit("/trace turn:1");
  assert.equal(calls.at(-1), "turn:1");

  failure = new Error("session 's:1' has no turn 'turn:nope'");
  await controller.submit("/trace turn:nope");
  assert.match(
    controller.messages.at(-1)?.content ?? "",
    /trace unavailable: session 's:1' has no turn 'turn:nope'/,
  );
});
