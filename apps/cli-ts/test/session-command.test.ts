/**
 * Headless `agent-os session` command: show/pause/resume/correct call the
 * surface protocol and print JSON. Hermetic (stub daemon + descriptor).
 */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { runSessionCommand } from "../src/session-command.js";

function snapshot(sessionId: string, overrides: Record<string, unknown> = {}) {
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
    event_sequence: 3,
    message_count: 2,
    pending_approval: null,
    permission_mode: "ASK",
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

async function withServer(
  handler: (
    path: string,
    method: string,
    body: unknown,
  ) => { status: number; json?: unknown; sse?: string },
  run: (descriptorPath: string) => Promise<void>,
): Promise<void> {
  const server = createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      try {
        const result = handler(req.url ?? "", req.method ?? "GET", raw ? JSON.parse(raw) : {});
        res.statusCode = result.status;
        if (result.sse !== undefined) {
          // The durable events endpoint is SSE, not JSON: a JSON body would be
          // parsed as zero events and a client that "found no turn" would look
          // identical to one that read an empty stream.
          res.setHeader("content-type", "text/event-stream");
          res.end(result.sse);
          return;
        }
        res.setHeader("content-type", "application/json");
        res.end(JSON.stringify(result.json));
      } catch (cause) {
        // Always answer so a failed assertion surfaces as a client error
        // rather than a hung fetch.
        res.statusCode = 500;
        res.end(JSON.stringify({ error: String(cause) }));
      }
    });
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const address = server.address();
  if (address === null || typeof address === "string") throw new Error("no address");
  const path = join(tmpdir(), `agent-os-desc-${Date.now()}-${Math.random()}.json`);
  await writeFile(
    path,
    JSON.stringify({
      protocol_version: "1.1",
      pid: 1,
      boot_id: "boot:test",
      host: "127.0.0.1",
      port: address.port,
      bearer_token: "test-token",
      database_path: "/tmp/db",
      workspace_path: "/tmp/ws",
      created_at: new Date().toISOString(),
    }),
  );
  try {
    await run(path);
  } finally {
    server.close();
    await rm(path, { force: true });
  }
}

function capture<T>(run: () => Promise<T>): Promise<{ result: T; out: string; err: string }> {
  const outWrite = process.stdout.write.bind(process.stdout);
  const errWrite = process.stderr.write.bind(process.stderr);
  let out = "";
  let err = "";
  process.stdout.write = ((c: string) => ((out += c), true)) as typeof process.stdout.write;
  process.stderr.write = ((c: string) => ((err += c), true)) as typeof process.stderr.write;
  return run()
    .then((result) => ({ result, out, err }))
    .finally(() => {
      process.stdout.write = outWrite;
      process.stderr.write = errWrite;
    });
}

test("session show prints snapshot fields", async () => {
  await withServer(
    (path, method) => {
      assert.equal(method, "GET");
      assert.equal(path, "/v1/surface/sessions/s:1");
      return { status: 200, json: snapshot("s:1") };
    },
    async (descriptorPath) => {
      const { result, out } = await capture(() =>
        runSessionCommand({ descriptorPath, args: ["show", "s:1"] }),
      );
      assert.equal(result, 0);
      const parsed = JSON.parse(out);
      assert.equal(parsed.session_id, "s:1");
      assert.equal(parsed.status, "ACTIVE");
      assert.equal(parsed.event_sequence, 3);
      assert.equal(parsed.message_count, 2);
    },
  );
});

test("session pause refreshes the event cursor before posting the pause route", async () => {
  const calls: string[] = [];
  await withServer(
    (path, method, body) => {
      calls.push(`${method} ${path}`);
      if (method === "GET") {
        assert.equal(path, "/v1/surface/sessions/s:1");
        return { status: 200, json: snapshot("s:1") };
      }
      assert.equal(method, "POST");
      assert.equal(path, "/v1/surface/sessions/s:1/pause");
      assert.equal((body as { reason?: string }).reason, "hold on");
      // The cursor must come from durable truth read in THIS process: a fresh
      // client starts with an empty map and would send 0, which the kernel
      // rejects with 409 (that is why `noem session pause` never took effect).
      assert.equal(
        (body as { expected_event_sequence?: number }).expected_event_sequence,
        3,
      );
      return { status: 200, json: { snapshot: snapshot("s:1") } };
    },
    async (descriptorPath) => {
      const { result, out } = await capture(() =>
        runSessionCommand({ descriptorPath, args: ["pause", "s:1", "hold", "on"] }),
      );
      assert.equal(result, 0);
      assert.equal(JSON.parse(out).status, "ACTIVE");
      assert.deepEqual(calls, [
        "GET /v1/surface/sessions/s:1",
        "POST /v1/surface/sessions/s:1/pause",
      ]);
    },
  );
});

test("session requires a session id and a known subcommand", async () => {
  assert.equal((await capture(() => runSessionCommand({ args: ["show"] }))).result, 1);
  assert.equal(
    (await capture(() => runSessionCommand({ args: ["frobnicate", "s:1"] }))).result,
    1,
  );
});

test("session correct posts the correction route with the default reason", async () => {
  await withServer(
    (path, method, body) => {
      if (method === "GET") return { status: 200, json: snapshot("s:1") };
      assert.equal(method, "POST");
      assert.equal(path, "/v1/surface/sessions/s:1/correction");
      assert.equal((body as { reason?: string }).reason, "operator correction");
      return { status: 200, json: { snapshot: snapshot("s:1") } };
    },
    async (descriptorPath) => {
      const { result } = await capture(() =>
        runSessionCommand({ descriptorPath, args: ["correct", "s:1"] }),
      );
      assert.equal(result, 0);
    },
  );
});

test("session resume resends from a fresh read when the cursor went stale", async () => {
  // The refresh and the command are two round trips: a durable event landing
  // between them makes the command's cursor stale even though the refresh was
  // correct when it was read. The resend must re-read, never reuse or guess.
  const posted: { expected_event_sequence?: number }[] = [];
  let reads = 0;
  await withServer(
    (path, method, body) => {
      if (method === "GET") {
        reads += 1;
        return { status: 200, json: snapshot("s:1", { event_sequence: 9 + 2 * reads }) };
      }
      assert.equal(path, "/v1/surface/sessions/s:1/resume");
      posted.push(body as { expected_event_sequence?: number });
      if (posted.length === 1) {
        return {
          status: 409,
          json: { message: "expected event sequence 11 does not match current sequence 13" },
        };
      }
      return { status: 200, json: { snapshot: snapshot("s:1", { status: "ACTIVE" }) } };
    },
    async (descriptorPath) => {
      const { result, out, err } = await capture(() =>
        runSessionCommand({ descriptorPath, args: ["resume", "s:1", "go"] }),
      );
      assert.equal(result, 0);
      assert.equal(JSON.parse(out).status, "ACTIVE");
      assert.equal(err, "");
      assert.equal(posted.length, 2, "the stale-cursor rejection must be retried");
      assert.deepEqual(
        posted.map((p) => p.expected_event_sequence),
        [11, 13],
        "the resend must carry a freshly read cursor, not the stale one",
      );
    },
  );
});

test("a control command the kernel keeps rejecting exits non-zero and says so", async () => {
  await withServer(
    (path, method) => {
      if (method === "GET") return { status: 200, json: snapshot("s:1") };
      assert.equal(path, "/v1/surface/sessions/s:1/correction");
      return {
        status: 409,
        json: { message: "expected event sequence 3 does not match current sequence 9" },
      };
    },
    async (descriptorPath) => {
      const { result, out, err } = await capture(() =>
        runSessionCommand({ descriptorPath, args: ["correct", "s:1", "stop"] }),
      );
      assert.equal(result, 1, "a correction that did not land must exit non-zero");
      assert.equal(out, "", "nothing may be printed as if the kernel had taken it");
      assert.match(err, /does not match current sequence 9/);
      assert.match(err, /HTTP 409/);
      assert.match(err, /the correct was NOT applied to s:1/);
    },
  );
});

test("a resume that leaves the session halted exits non-zero and names the state", async () => {
  // Measured on a real daemon (2026-09-18): `noem session resume` against a
  // CORRECTION_HALTED session answered 200 with status CORRECTION_HALTED and
  // exit 0, while every following turn was refused by the kernel. An operator
  // scripting recovery from the shell could not tell that from a success.
  await withServer(
    (path, method) => {
      if (method === "GET") {
        return { status: 200, json: snapshot("s:1", { status: "CORRECTION_HALTED" }) };
      }
      assert.equal(path, "/v1/surface/sessions/s:1/resume");
      return { status: 200, json: { snapshot: snapshot("s:1", { status: "CORRECTION_HALTED" }) } };
    },
    async (descriptorPath) => {
      const { result, out, err } = await capture(() =>
        runSessionCommand({ descriptorPath, args: ["resume", "s:1"] }),
      );
      assert.equal(result, 1, "a resume that cannot make the session usable is not a success");
      // The kernel's own status is still reported (it is durable truth, not a
      // failure to read).
      assert.equal(JSON.parse(out).status, "CORRECTION_HALTED");
      assert.match(err, /still reports CORRECTION_HALTED/);
      assert.match(err, /cannot accept turns/);
    },
  );
});

test("a successful resume still exits zero", async () => {
  await withServer(
    (path, method) => {
      if (method === "GET") return { status: 200, json: snapshot("s:1") };
      assert.equal(path, "/v1/surface/sessions/s:1/resume");
      return { status: 200, json: { snapshot: snapshot("s:1", { status: "ACTIVE" }) } };
    },
    async (descriptorPath) => {
      const { result, err } = await capture(() =>
        runSessionCommand({ descriptorPath, args: ["resume", "s:1"] }),
      );
      assert.equal(result, 0);
      assert.equal(err, "");
    },
  );
});

test("CLI flags never become part of the durable correction reason", async () => {
  // The reason lands in `CORRECTION_WRITTEN.reason` (durable evidence), so the
  // transport flags must not be smuggled into it.
  const reasons: string[] = [];
  await withServer(
    (path, method, body) => {
      if (method === "GET") return { status: 200, json: snapshot("s:1") };
      reasons.push((body as { reason?: string }).reason ?? "");
      return { status: 200, json: { snapshot: snapshot("s:1") } };
    },
    async (descriptorPath) => {
      await capture(() =>
        runSessionCommand({
          descriptorPath,
          args: ["correct", "s:1", "operator", "interrupt", "--descriptor", descriptorPath],
        }),
      );
      await capture(() =>
        runSessionCommand({
          descriptorPath,
          args: ["pause", "s:1", "--descriptor", descriptorPath],
        }),
      );
    },
  );
  assert.deepEqual(reasons, ["operator interrupt", "paused by user"]);
});

/** Durable events as the events endpoint really sends them (SSE). */
function eventsSse(
  entries: { event_type: string; payload: Record<string, unknown> }[],
): string {
  const lines: string[] = [];
  entries.forEach((entry, index) => {
    const sequence = index + 1;
    lines.push(
      `id: ${sequence}`,
      `event: ${entry.event_type}`,
      `data: ${JSON.stringify({
        event_id: `e:${sequence}`,
        task_id: "task:1",
        event_type: entry.event_type,
        payload_json: JSON.stringify(entry.payload),
        occurred_at: "2026-09-19T00:00:00Z",
        correlation_id: "run:1",
        sequence,
      })}`,
      "",
    );
  });
  lines.push("event: cursor", `data: ${JSON.stringify({ next_sequence: entries.length })}`, "");
  return lines.join("\n");
}

const DEAD_TURN_EVENTS = [
  { event_type: "SESSION_TURN_STARTED", payload: { turn_id: "turn:dead", session_id: "s:1" } },
];

test("session recover names the durable turn and closes it as an unknown outcome", async () => {
  // The operator does not have to know the turn id: it is read from durable
  // truth (started without completed) and bound into the command, which is why
  // there is no "recover everything" sweep.
  const posted: Record<string, unknown>[] = [];
  let recovered = false;
  await withServer(
    (path, method, body) => {
      if (path === "/v1/surface/tasks/task:1/events?after=0&wait_ms=0") {
        return {
          status: 200,
          sse: eventsSse([
            ...DEAD_TURN_EVENTS,
            ...(recovered
              ? [
                  {
                    event_type: "SESSION_TURN_COMPLETED",
                    payload: {
                      turn_id: "turn:dead",
                      session_id: "s:1",
                      stop_reason: "unknown_requires_review",
                      dead_turn_recovery: { turn_id: "turn:dead" },
                    },
                  },
                ]
              : []),
          ]),
        };
      }
      if (method === "GET") return { status: 200, json: snapshot("s:1") };
      assert.equal(path, "/v1/surface/sessions/s:1/recover-turn");
      posted.push(body as Record<string, unknown>);
      recovered = true;
      return {
        status: 200,
        json: {
          recovery: {
            protocol_version: "1.2",
            snapshot: snapshot("s:1"),
            recovery: {
              turn_id: "turn:dead",
              session_id: "s:1",
              reason_code: "TURN_OWNER_PROCESS_GONE",
              declared_by: "user:local",
              declared_at: "2026-09-19T00:00:00Z",
              reason: "the runtime was killed",
              owner_runtime_boot_id: "boot:dead",
              owner_runtime_pid: 4242,
              recovered_by_runtime_boot_id: "boot:new",
              recovered_by_runtime_pid: 5252,
              started_event_id: "e:1",
              started_sequence: 1,
              counters_recorded: false,
            },
            notice: "turn turn:dead was abandoned as an unknown outcome",
          },
        },
      };
    },
    async (descriptorPath) => {
      const { result, out, err } = await capture(() =>
        runSessionCommand({
          descriptorPath,
          args: ["recover", "s:1", "the runtime was killed"],
        }),
      );
      assert.equal(result, 0);
      assert.equal(err, "");
      const parsed = JSON.parse(out) as Record<string, unknown>;
      assert.equal(parsed.recovered, true);
      assert.equal(parsed.turn_id, "turn:dead");
      assert.equal(parsed.stop_reason, "unknown_requires_review");
      assert.equal(parsed.owner_runtime_boot_id, "boot:dead");
    },
  );
  assert.equal(posted.length, 1);
  assert.equal(posted[0]?.turn_id, "turn:dead");
  assert.equal(posted[0]?.reason, "the runtime was killed");
  assert.equal(posted[0]?.expected_event_sequence, 3);
});

test("session recover says so — and does not pretend — when there is nothing to recover", async () => {
  await withServer(
    (path, method) => {
      if (path === "/v1/surface/tasks/task:1/events?after=0&wait_ms=0") {
        return { status: 200, sse: eventsSse([]) };
      }
      if (method === "GET") return { status: 200, json: snapshot("s:1") };
      throw new Error(`recover route must not be called (${path})`);
    },
    async (descriptorPath) => {
      const { result, out, err } = await capture(() =>
        runSessionCommand({ descriptorPath, args: ["recover", "s:1", "just in case"] }),
      );
      assert.equal(result, 0);
      assert.equal(JSON.parse(out).recovered, false);
      assert.match(err, /nothing to recover/);
    },
  );
});

test("session recover requires the operator's reason", async () => {
  // The reason check must happen before anything is read: a missing reason used
  // to fall through to the descriptor lookup and reach the operator's real
  // ~/.agent-os/runtime.json.
  const { result, err } = await capture(() =>
    runSessionCommand({
      descriptorPath: "/nonexistent/descriptor.json",
      args: ["recover", "s:1"],
    }),
  );
  assert.equal(result, 1);
  assert.match(err, /usage: noem session recover/);
});
