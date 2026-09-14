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

function snapshot(sessionId: string) {
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
  };
}

async function withServer(
  handler: (path: string, method: string, body: unknown) => { status: number; json: unknown },
  run: (descriptorPath: string) => Promise<void>,
): Promise<void> {
  const server = createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      const result = handler(req.url ?? "", req.method ?? "GET", raw ? JSON.parse(raw) : {});
      res.statusCode = result.status;
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify(result.json));
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
    },
  );
});

test("session pause posts the pause route with a reason", async () => {
  await withServer(
    (path, method, body) => {
      assert.equal(method, "POST");
      assert.equal(path, "/v1/surface/sessions/s:1/pause");
      assert.equal((body as { reason?: string }).reason, "hold on");
      return { status: 200, json: { snapshot: snapshot("s:1") } };
    },
    async (descriptorPath) => {
      const { result, out } = await capture(() =>
        runSessionCommand({ descriptorPath, args: ["pause", "s:1", "hold", "on"] }),
      );
      assert.equal(result, 0);
      assert.equal(JSON.parse(out).status, "ACTIVE");
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
