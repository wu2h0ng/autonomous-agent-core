/**
 * Headless `agent-os-ts provider` argument/credential handling. These fail
 * before any daemon connection, so they are hermetic. The command must never
 * print or persist the API key.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { runProviderCommand } from "../src/provider-command.js";

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
  assert.match(err, /usage: agent-os-ts provider set/);
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
    assert.match(err, /AGENT_OS_PROVIDER_KEY is not set/);
    assert.ok(!out.includes("sk-") && !err.includes("sk-"));
  } finally {
    if (previous !== undefined) process.env.AGENT_OS_PROVIDER_KEY = previous;
  }
});
