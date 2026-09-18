/**
 * Doctor self-check tests: each check's pass/fail path, and the invariant
 * that the bearer token never appears in any rendered output.
 */
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  renderDoctorText,
  runDoctor,
  type DoctorOptions,
  type DoctorReport,
} from "../src/doctor.js";

const SECRET = "doctor-test-secret-token";
const CHECKOUT = "/repo/agent-os";

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

/** Launcher resolution pinned to the checkout the caller stands in. */
function insideCheckout(env: NodeJS.ProcessEnv = {}): DoctorOptions {
  return {
    env,
    resolve: {
      hasOnPath: (name) => name === "uv" || name === "agent-os-runtime",
      findCheckout: () => CHECKOUT,
      cwd: () => CHECKOUT,
    },
  };
}

/** Launcher resolution outside any checkout, PATH install present. */
function outsideCheckout(env: NodeJS.ProcessEnv = {}): DoctorOptions {
  return {
    env,
    resolve: {
      hasOnPath: (name) => name === "agent-os-runtime" || name === "uv",
      findCheckout: () => null,
      cwd: () => "/somewhere/else",
    },
  };
}

function launcherNote(report: DoctorReport): string {
  return report.notes.find((note) => note.text.startsWith("launcher:"))?.text ?? "";
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
  const report = await runDoctor(
    "/nonexistent/runtime.json",
    (async () => {
      fetched = true;
      return { status: 200, json: async () => null };
    }) as never,
    insideCheckout(),
  );
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

test("doctor: names the launcher and the checkout it belongs to", async () => {
  const { fn } = fakeFetch(404, { protocol_version: "1.1" });
  const report = await runDoctor(descriptorFile(), fn as never, insideCheckout());
  assert.equal(report.ok, true);
  const note = report.notes.find((n) => n.text.startsWith("launcher:"));
  assert.equal(note?.level, "info");
  assert.match(note?.text ?? "", /uv run agent-os-runtime/);
  assert.match(note?.text ?? "", new RegExp(CHECKOUT.replace(/[/.]/g, "\\$&")));
  assert.match(note?.text ?? "", /this checkout/);
  assert.match(renderDoctorText(report), /^· launcher: /m);
  // identity lines never turn a healthy daemon red, and never leak the token
  assert.ok(report.notes.every((n) => n.level === "info"));
  assert.ok(!renderDoctorText(report).includes(SECRET));
});

test("doctor: warns when the launcher is NOT the checkout the caller stands in", async () => {
  const { fn } = fakeFetch(404, { protocol_version: "1.1" });

  // AGENT_OS_RUNTIME_CMD outranks the checkout: explicit override, still warned
  const override = await runDoctor(
    descriptorFile(),
    fn as never,
    insideCheckout({ AGENT_OS_RUNTIME_CMD: "agent-os-runtime" }),
  );
  const overrideNote = override.notes.find((n) => n.text.startsWith("launcher:"));
  assert.equal(overrideNote?.level, "warn");
  assert.match(overrideNote?.text ?? "", /AGENT_OS_RUNTIME_CMD/);
  assert.match(overrideNote?.text ?? "", /NOT this checkout/);
  assert.match(overrideNote?.text ?? "", new RegExp(CHECKOUT.replace(/[/.]/g, "\\$&")));
  assert.match(renderDoctorText(override), /^! launcher: /m);

  // a checkout with no uv on PATH falls back to the PATH runtime: warned too
  const pathInstall = await runDoctor(descriptorFile(), fn as never, {
    env: {},
    resolve: {
      hasOnPath: (name) => name === "agent-os-runtime",
      findCheckout: () => CHECKOUT,
      cwd: () => CHECKOUT,
    },
  });
  const pathNote = pathInstall.notes.find((n) => n.text.startsWith("launcher:"));
  assert.equal(pathNote?.level, "warn");
  assert.match(pathNote?.text ?? "", /agent-os-runtime on PATH/);
  assert.match(pathNote?.text ?? "", /different database/);

  // outside a checkout the PATH runtime is normal, so the line is informational
  const outside = await runDoctor(descriptorFile(), fn as never, outsideCheckout());
  const outsideNote = outside.notes.find((n) => n.text.startsWith("launcher:"));
  assert.equal(outsideNote?.level, "info");
  assert.match(outsideNote?.text ?? "", /NOT this checkout \(no checkout at or above /);
});

test("doctor: reports the port, database and pid the descriptor names", async () => {
  const { fn } = fakeFetch(404, { protocol_version: "1.1" });
  const report = await runDoctor(descriptorFile(), fn as never, insideCheckout());
  const note = report.notes.find((n) => n.text.startsWith("daemon (from descriptor):"));
  assert.match(note?.text ?? "", /pid 1234/);
  assert.match(note?.text ?? "", /port 59999/);
  assert.match(note?.text ?? "", /database \/tmp\/db\.sqlite3/);
  assert.match(renderDoctorText(report), /port 59999/);
  assert.match(renderDoctorText(report), /database \/tmp\/db\.sqlite3/);
});

test("doctor: prints the launcher line even when the descriptor is missing", async () => {
  // The state in which auto-start used to pick up a foreign runtime: no
  // descriptor at all. The identity line must still be there.
  let fetched = false;
  const report = await runDoctor(
    "/nonexistent/runtime.json",
    (async () => {
      fetched = true;
      return { status: 200, json: async () => null };
    }) as never,
    insideCheckout({ AGENT_OS_RUNTIME_CMD: "agent-os-runtime" }),
  );
  assert.equal(report.ok, false);
  assert.equal(fetched, false);
  const text = renderDoctorText(report);
  assert.match(text, /^! launcher: agent-os-runtime/m);
  assert.match(text, /NOT this checkout/);
  assert.match(text, /✗ descriptor:/);
  // no descriptor means no invented connection facts
  assert.ok(!text.includes("daemon (from descriptor):"));
});

test("doctor: a warned-about launcher never changes ok, so the exit code stays 0", async () => {
  // The contract `cli.tsx` relies on: it maps report.ok to the process exit
  // code, and notes are identity information, never a verdict. A runtime that is
  // NOT the checkout the caller stands in (and is therefore the one auto-start
  // may fall back to) must still leave a healthy daemon green.
  const { fn } = fakeFetch(404, { protocol_version: "1.1" });
  const warned: DoctorOptions[] = [
    insideCheckout({ AGENT_OS_RUNTIME_CMD: "agent-os-runtime" }),
    // a checkout with no uv on PATH: the PATH runtime is the first candidate
    {
      env: {},
      resolve: {
        hasOnPath: (name) => name === "agent-os-runtime",
        findCheckout: () => CHECKOUT,
        cwd: () => CHECKOUT,
      },
    },
  ];
  for (const options of warned) {
    const report = await runDoctor(descriptorFile(), fn as never, options);
    assert.ok(report.notes.some((note) => note.level === "warn"), "expected a warning line");
    assert.ok(report.checks.every((check) => check.ok));
    assert.equal(report.ok, true, renderDoctorText(report));
  }
  // outside this checkout the same non-checkout launcher is merely informational
  const outside = await runDoctor(descriptorFile(), fn as never, outsideCheckout());
  assert.ok(outside.notes.every((note) => note.level === "info"));
  assert.equal(outside.ok, true, renderDoctorText(outside));
});

test("doctor: no launcher at all is reported, without failing the daemon checks", async () => {
  const { fn } = fakeFetch(404, { protocol_version: "1.1" });
  const report = await runDoctor(descriptorFile(), fn as never, {
    env: {},
    resolve: { hasOnPath: () => false, findCheckout: () => null, cwd: () => "/nowhere" },
  });
  assert.equal(report.ok, true);
  const note = report.notes.find((n) => n.text.startsWith("launcher:"));
  assert.equal(note?.level, "warn");
  assert.match(note?.text ?? "", /launcher: none/);
  assert.match(note?.text ?? "", /AGENT_OS_RUNTIME_CMD/);
});
