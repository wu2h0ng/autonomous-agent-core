/**
 * The descriptor's reverse skew: an already-installed OLDER client meeting a
 * NEWER daemon.
 *
 * The client-side rules above are about reading responses the daemon projected
 * down. This is the other direction, and it cannot be projected away: the client
 * reads the descriptor before it sends anything, so a descriptor written by a
 * build it does not understand is a hard failure at the very first step.
 *
 * Hard is fine; silent is not. Before this section existed, `tryLoad` swallowed
 * the failure and treated "I cannot read this descriptor" as "there is no
 * daemon", so the client deleted the live daemon's descriptor (its only handle)
 * and tried to start a competing daemon over the same database, ending with
 * "daemon did not become ready in time" — a message about the wrong thing, after
 * damage. What is pinned here is the classification the caller depends on:
 *
 *   - absent            → RuntimeDescriptorNotFoundError (start a daemon)
 *   - older-readable    → loads (a 1.2 client still attaches to a 1.1 runtime)
 *   - skewed version    → SurfaceProtocolSkewError, typed, naming both sides
 *   - otherwise corrupt → a schema error, NOT relabelled as a skew
 *
 * The frozen client that is already installed on a machine cannot be retrofitted
 * from here; that limit is stated in the PR body, with the exact operator-visible
 * error, rather than implied to be solved.
 */
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { SURFACE_PROTOCOL_MIN_SUPPORTED, SURFACE_PROTOCOL_VERSION } from "../src/contracts.js";
import {
  RuntimeDescriptorNotFoundError,
  SurfaceProtocolSkewError,
  loadRuntimeDescriptor,
} from "../src/descriptor.js";
import { ensureDaemon } from "../src/daemon.js";

function descriptorPath(overrides: Record<string, unknown> = {}): string {
  const dir = mkdtempSync(join(tmpdir(), "agent-os-descriptor-"));
  const path = join(dir, "runtime.json");
  writeFileSync(
    path,
    JSON.stringify({
      protocol_version: SURFACE_PROTOCOL_VERSION,
      pid: 4242,
      boot_id: "boot:descriptor-skew:1",
      host: "127.0.0.1",
      port: 18787,
      bearer_token: "0".repeat(43),
      database_path: join(dir, "agent-os.sqlite3"),
      workspace_path: dir,
      created_at: "2026-09-18T00:00:00+00:00",
      ...overrides,
    }),
    "utf8",
  );
  return path;
}

test("a descriptor from a runtime one minor behind still loads", () => {
  const path = descriptorPath({ protocol_version: SURFACE_PROTOCOL_MIN_SUPPORTED });

  return loadRuntimeDescriptor(path).then((descriptor) => {
    assert.equal(descriptor.protocol_version, SURFACE_PROTOCOL_MIN_SUPPORTED);
    assert.equal(descriptor.baseUrl, "http://127.0.0.1:18787");
  });
});

test("a missing descriptor is its own error, not a skew", async () => {
  const dir = mkdtempSync(join(tmpdir(), "agent-os-descriptor-"));
  await assert.rejects(loadRuntimeDescriptor(join(dir, "runtime.json")), (error) => {
    assert.ok(error instanceof RuntimeDescriptorNotFoundError, String(error));
    assert.ok(!(error instanceof SurfaceProtocolSkewError));
    return true;
  });
});

test("a descriptor this client cannot read fails typed, naming both sides", async () => {
  for (const version of ["1.0", "1.3", "2.0"]) {
    const path = descriptorPath({ protocol_version: version });
    await assert.rejects(loadRuntimeDescriptor(path), (error) => {
      assert.ok(error instanceof SurfaceProtocolSkewError, `${version}: ${String(error)}`);
      assert.equal(error.serverVersion, version);
      assert.equal(error.clientVersion, SURFACE_PROTOCOL_VERSION);
      assert.match(error.message, new RegExp(version.replace(".", "\\.")));
      assert.match(error.message, /version skew/);
      assert.match(error.message, /1\.1/);
      return true;
    });
  }
});

test("a genuinely broken descriptor is a schema error, never relabelled", async () => {
  // Not a version at all: the honest report is the schema problem.
  await assert.rejects(
    loadRuntimeDescriptor(descriptorPath({ protocol_version: "one.two" })),
    (error) => !(error instanceof SurfaceProtocolSkewError),
  );
  // A readable version with a broken port: still a schema problem.
  await assert.rejects(
    loadRuntimeDescriptor(descriptorPath({ port: 99999 })),
    (error) => !(error instanceof SurfaceProtocolSkewError),
  );
});

test("a skew never deletes the descriptor or starts a competing daemon", async () => {
  const path = descriptorPath({ protocol_version: "1.3" });
  const before = readFileSync(path, "utf8");
  let launchersResolved = 0;

  await assert.rejects(
    ensureDaemon(
      {
        descriptorPath: path,
        workspace: join(path, "..", "workspace"),
        database: join(path, "..", "agent-os.sqlite3"),
        autoStart: true,
      },
      {
        resolveLaunch: () => {
          launchersResolved += 1;
          return null;
        },
      },
    ),
    (error) => {
      assert.ok(error instanceof SurfaceProtocolSkewError, String(error));
      return true;
    },
  );

  assert.equal(launchersResolved, 0, "a skew must not reach daemon launching");
  assert.ok(existsSync(path), "a skew must not delete the descriptor");
  assert.equal(readFileSync(path, "utf8"), before);
  rmSync(path, { force: true });
});
