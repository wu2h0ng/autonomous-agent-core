/**
 * Doctor self-check tests: each check's pass/fail path, and the invariant
 * that the bearer token never appears in any rendered output.
 */
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { renderDoctorText, runDoctor } from "../src/doctor.js";

const SECRET = "doctor-test-secret-token";

function descriptorFile(): string {
  const dir = mkdtempSync(join(tmpdir(), "cli-ts-doctor-"));
  const path = join(dir, "runtime.json");
  writeFileSync(
    path,
    JSON.stringify({
      protocol_version: "1.1",
      pid: 1234,
      boot_id: "boot:x",
      host: "127.0.0.1",
      port: 59999,
      bearer_token: SECRET,
      database_path: "/tmp/db.sqlite3",
      workspace_path: "/tmp/ws",
      created_at: new Date().toISOString(),
    }),
  );
  return path;
}

function fakeFetch(status: number, body: unknown) {
  const calls: { url: string; auth: string | undefined }[] = [];
  const fn = async (url: string, init: { headers: Record<string, string> }) => {
    calls.push({ url, auth: init.headers["Authorization"] });
    return { status, json: async () => body };
  };
  return { fn, calls };
}

test("doctor: all checks pass on typed 404 with matching protocol", async () => {
  const { fn, calls } = fakeFetch(404, { protocol_version: "1.1", error: "not found" });
  const report = await runDoctor(descriptorFile(), fn as never);
  assert.equal(report.ok, true);
  assert.deepEqual(report.checks.map((c) => c.name), ["descriptor", "reachable", "auth", "protocol"]);
  assert.ok(report.checks.every((c) => c.ok));
  // the probe carries the bearer token but never creates state
  assert.equal(calls[0]?.auth, `Bearer ${SECRET}`);
  assert.match(calls[0]?.url ?? "", /doctor-probe-nonexistent$/);
  // the token never leaks into rendered output
  assert.ok(!renderDoctorText(report).includes(SECRET));
});

test("doctor: missing descriptor fails fast without network", async () => {
  let fetched = false;
  const report = await runDoctor("/nonexistent/runtime.json", (async () => {
    fetched = true;
    return { status: 200, json: async () => null };
  }) as never);
  assert.equal(report.ok, false);
  assert.equal(report.checks.length, 1);
  assert.equal(report.checks[0]?.name, "descriptor");
  assert.equal(fetched, false);
});

test("doctor: 401 is an auth failure with actionable detail", async () => {
  const { fn } = fakeFetch(401, { error: "unauthorized" });
  const report = await runDoctor(descriptorFile(), fn as never);
  assert.equal(report.ok, false);
  assert.equal(report.checks.find((c) => c.name === "auth")?.ok, false);
  assert.equal(report.checks.find((c) => c.name === "protocol")?.ok, false);
  assert.match(renderDoctorText(report), /token rejected/);
});

test("doctor: unreachable daemon marks dependent checks skipped", async () => {
  const report = await runDoctor(descriptorFile(), (async () => {
    throw new Error("fetch failed");
  }) as never);
  assert.equal(report.ok, false);
  assert.equal(report.checks.find((c) => c.name === "reachable")?.ok, false);
  assert.match(report.checks.find((c) => c.name === "auth")?.detail ?? "", /skipped/);
});

test("doctor: protocol major mismatch is flagged", async () => {
  const { fn } = fakeFetch(404, { protocol_version: "2.0" });
  const report = await runDoctor(descriptorFile(), fn as never);
  assert.equal(report.ok, false);
  assert.match(renderDoctorText(report), /MAJOR MISMATCH/);
});
