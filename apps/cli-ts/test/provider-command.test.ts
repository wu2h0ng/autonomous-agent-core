/**
 * Headless `agent-os-ts provider` argument/credential handling. These fail
 * before any daemon connection, so they are hermetic. The command must never
 * print or persist the API key.
 */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { runProviderCommand } from "../src/provider-command.js";

async function withDescriptorServer(
  handler: (path: string, body: unknown) => { status: number; json: unknown },
  run: (descriptorPath: string) => Promise<void>,
): Promise<void> {
  const server = createServer((req, res) => {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => {
      const result = handler(req.url ?? "", raw ? JSON.parse(raw) : {});
      res.statusCode = result.status;
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify(result.json));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (address === null || typeof address === "string") throw new Error("no address");
  const path = join(tmpdir(), `agent-os-descriptor-${Date.now()}-${Math.random()}.json`);
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
  process.stdout.write = ((chunk: string) => {
    out += chunk;
    return true;
  }) as typeof process.stdout.write;
  process.stderr.write = ((chunk: string) => {
    err += chunk;
    return true;
  }) as typeof process.stderr.write;
  return run()
    .then((result) => ({ result, out, err }))
    .finally(() => {
      process.stdout.write = outWrite;
      process.stderr.write = errWrite;
    });
}

test("unknown provider subcommand exits 1 with usage", async () => {
  const { result, err } = await capture(() =>
    runProviderCommand({ args: ["frobnicate"] }),
  );
  assert.equal(result, 1);
  assert.match(err, /unknown provider subcommand/);
});

test("provider set requires --base-url and --model before connecting", async () => {
  const { result, err } = await capture(() =>
    runProviderCommand({ args: ["set", "--model", "m"] }),
  );
  assert.equal(result, 1);
  assert.match(err, /usage: noem provider set/);
});

test("provider set without AGENT_OS_PROVIDER_KEY never echoes a key", async () => {
  const previous = process.env.AGENT_OS_PROVIDER_KEY;
  delete process.env.AGENT_OS_PROVIDER_KEY;
  try {
    const { result, out, err } = await capture(() =>
      runProviderCommand({
        args: ["set", "--base-url", "https://api.example.com/v1", "--model", "m"],
      }),
    );
    assert.equal(result, 1);
    assert.match(err, /no provider key available|key-stdin/);
    assert.ok(!out.includes("sk-") && !err.includes("sk-"));
  } finally {
    if (previous !== undefined) process.env.AGENT_OS_PROVIDER_KEY = previous;
  }
});

test("provider set sends the key to the daemon but never prints it", async () => {
  const sentinel = "sk-test-do-not-echo-456";
  const previous = process.env.AGENT_OS_PROVIDER_KEY;
  process.env.AGENT_OS_PROVIDER_KEY = sentinel;
  let sentBody = "";
  try {
    await withDescriptorServer(
      (_path, body) => {
        sentBody = JSON.stringify(body);
        return {
          status: 200,
          json: {
            provider: {
              protocol_version: "1.1",
              configured: true,
              model_id: "m",
              endpoint_class: "openai-compatible",
              base_url: "https://api.example.com/v1",
              persisted: true,
              key_source: "env",
            },
          },
        };
      },
      async (descriptorPath) => {
        const { result, out, err } = await capture(() =>
          runProviderCommand({
            descriptorPath,
            args: ["set", "--base-url", "https://api.example.com/v1", "--model", "m"],
          }),
        );
        assert.equal(result, 0);
        assert.ok(!out.includes(sentinel));
        assert.ok(!err.includes(sentinel));
      },
    );
  } finally {
    if (previous === undefined) delete process.env.AGENT_OS_PROVIDER_KEY;
    else process.env.AGENT_OS_PROVIDER_KEY = previous;
  }
  // The key IS transmitted (as designed) — this makes the no-echo assertions meaningful.
  assert.ok(sentBody.includes(sentinel));
});

test("provider set refuses --api-key on argv (history/process-leak hard line)", async () => {
  const sentinel = "sk-argv-leak-999";
  const { result, err } = await capture(() =>
    runProviderCommand({
      args: ["set", "--base-url", "https://api.example.com/v1", "--model", "m", "--api-key", sentinel],
    }),
  );
  assert.equal(result, 1);
  assert.match(err, /do not pass --api-key/);
  // The rejected argv value must not itself be echoed.
  assert.ok(!err.includes(sentinel));
});

test("provider set refuses --api-key=value too", async () => {
  const { result, err } = await capture(() =>
    runProviderCommand({
      args: ["set", "--base-url", "https://api.example.com/v1", "--model", "m", "--api-key=sk-inline-leak"],
    }),
  );
  assert.equal(result, 1);
  assert.match(err, /do not pass --api-key/);
});

test("--key-stdin path: the injected pipe key is sent to the daemon, never printed", async () => {
  const sentinel = "sk-stdin-pipe-777";
  let sentBody = "";
  await withDescriptorServer(
    (_path, body) => {
      sentBody = JSON.stringify(body);
      return {
        status: 200,
        json: {
          provider: {
            protocol_version: "1.1",
            configured: true,
            model_id: "m",
            endpoint_class: "openai-compatible",
            base_url: "https://api.example.com/v1",
            persisted: true,
            key_source: "keychain",
          },
        },
      };
    },
    async (descriptorPath) => {
      const { result, out, err } = await capture(() =>
        runProviderCommand({
          descriptorPath,
          args: ["set", "--base-url", "https://api.example.com/v1", "--model", "m", "--key-stdin"],
          // Hermetic stand-in for the piped stdin the flag implies.
          keyProvider: async () => sentinel,
        }),
      );
      assert.equal(result, 0);
      assert.ok(!out.includes(sentinel));
      assert.ok(!err.includes(sentinel));
    },
  );
  assert.ok(sentBody.includes(sentinel));
});
