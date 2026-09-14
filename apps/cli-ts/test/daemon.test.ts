/**
 * Daemon lifecycle tests (dependency-injected): attach to a healthy daemon,
 * auto-start one when the descriptor is missing, and refuse when no launcher
 * exists. No real process is spawned and no real network is used.
 */
import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { ChildProcess } from "node:child_process";
import {
  daemonHealthy,
  ensureDaemon,
  resolveDaemonCommand,
  stopDaemon,
  type DaemonDeps,
} from "../src/daemon.js";
import { runDaemonCommand } from "../src/daemon-command.js";

function fakeChild(onSpawn: () => void = () => {}): ChildProcess {
  const child = {
    unref() {},
    once(event: string, cb: (arg?: unknown) => void) {
      if (event === "spawn") {
        onSpawn();
        cb();
      }
      return child;
    },
  };
  return child as unknown as ChildProcess;
}

function descriptorJson(port = 12345) {
  return JSON.stringify({
    protocol_version: "1.1",
    pid: 4242,
    boot_id: "boot:test",
    host: "127.0.0.1",
    port,
    bearer_token: "token",
    database_path: "/tmp/db",
    workspace_path: "/tmp/ws",
    created_at: new Date().toISOString(),
  });
}

const okFetch = (async () => ({ status: 200 })) as unknown as typeof fetch;
const badFetch = (async () => ({ status: 401 })) as unknown as typeof fetch;

test("resolveDaemonCommand honors override, PATH, and absence", () => {
  assert.deepEqual(
    resolveDaemonCommand({ AGENT_OS_RUNTIME_CMD: "python -m x" } as NodeJS.ProcessEnv, () => false),
    ["python", "-m", "x"],
  );
  assert.deepEqual(
    resolveDaemonCommand({} as NodeJS.ProcessEnv, (n) => n === "agent-os-runtime"),
    ["agent-os-runtime"],
  );
  assert.deepEqual(
    resolveDaemonCommand({} as NodeJS.ProcessEnv, (n) => n === "uv"),
    ["uv", "run", "agent-os-runtime"],
  );
  assert.equal(resolveDaemonCommand({} as NodeJS.ProcessEnv, () => false), null);
});

test("daemonHealthy reflects the authenticated surface response", async () => {
  const descriptor = JSON.parse(descriptorJson());
  descriptor.baseUrl = "http://127.0.0.1:1";
  assert.equal(await daemonHealthy(descriptor, okFetch), true);
  assert.equal(await daemonHealthy(descriptor, badFetch), false);
  const throwing = (async () => {
    throw new Error("unreachable");
  }) as unknown as typeof fetch;
  assert.equal(await daemonHealthy(descriptor, throwing), false);
});

test("ensureDaemon attaches to a healthy daemon without spawning", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  try {
    const descriptorPath = join(dir, "runtime.json");
    await writeFile(descriptorPath, descriptorJson());
    let spawned = false;
    const result = await ensureDaemon(
      { descriptorPath, workspace: dir, database: join(dir, "db") },
      {
        fetch: okFetch,
        spawn: (() => {
          spawned = true;
          return fakeChild();
        }) as DaemonDeps["spawn"],
      },
    );
    assert.equal(result.started, false);
    assert.equal(spawned, false);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("ensureDaemon auto-starts and waits for a ready descriptor", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  try {
    const descriptorPath = join(dir, "runtime.json");
    const calls: string[][] = [];
    const spawn = ((command: string, args: string[]) => {
      calls.push([command, ...args]);
      // Simulate the daemon writing its descriptor before it becomes healthy.
      return fakeChild(() => writeFileSync(descriptorPath, descriptorJson()));
    }) as DaemonDeps["spawn"];
    const result = await ensureDaemon(
      { descriptorPath, workspace: dir, database: join(dir, "db") },
      {
        fetch: okFetch,
        spawn,
        sleep: async () => {},
        resolveCommand: () => ["agent-os-runtime"],
      },
    );
    assert.equal(result.started, true);
    assert.equal(calls.length, 1);
    const argv = calls[0] ?? [];
    assert.ok(argv.includes("--workspace"));
    assert.ok(argv.includes("--database"));
    assert.ok(argv.includes("--descriptor"));
    assert.ok(argv.includes(descriptorPath));
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("ensureDaemon fails closed without a launcher or with auto-start off", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  try {
    const descriptorPath = join(dir, "runtime.json");
    await assert.rejects(
      ensureDaemon(
        { descriptorPath, workspace: dir, database: join(dir, "db") },
        { fetch: okFetch, resolveCommand: () => null },
      ),
      /no daemon launcher/,
    );
    await assert.rejects(
      ensureDaemon(
        { descriptorPath, workspace: dir, database: join(dir, "db"), autoStart: false },
        { fetch: okFetch },
      ),
      /auto-start/,
    );
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("stopDaemon returns false when there is no descriptor", async () => {
  assert.equal(await stopDaemon("/tmp/agent-os-does-not-exist.json"), false);
});

test("runDaemonCommand rejects unknown subcommands and reports status", async () => {
  assert.equal(await runDaemonCommand({ args: ["frobnicate"] }), 1);
  const previous = process.env.AGENT_OS_RUNTIME_DESCRIPTOR;
  process.env.AGENT_OS_RUNTIME_DESCRIPTOR = "/tmp/agent-os-missing-descriptor.json";
  try {
    const code = await runDaemonCommand({ args: ["status"] });
    assert.equal(code, 1);
  } finally {
    if (previous === undefined) delete process.env.AGENT_OS_RUNTIME_DESCRIPTOR;
    else process.env.AGENT_OS_RUNTIME_DESCRIPTOR = previous;
  }
});

test("ensureDaemon respawns over an unhealthy stale descriptor", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  try {
    const descriptorPath = join(dir, "runtime.json");
    await writeFile(descriptorPath, descriptorJson());
    let calls = 0;
    const fetchImpl = (async () => ({ status: calls++ === 0 ? 401 : 200 })) as unknown as typeof fetch;
    let spawned = 0;
    const result = await ensureDaemon(
      { descriptorPath, workspace: dir, database: join(dir, "db") },
      {
        fetch: fetchImpl,
        spawn: (() => {
          spawned += 1;
          return fakeChild(() => writeFileSync(descriptorPath, descriptorJson(12000)));
        }) as DaemonDeps["spawn"],
        sleep: async () => {},
        resolveCommand: () => ["agent-os-runtime"],
        matchProcess: () => false,
      },
    );
    assert.equal(result.started, true);
    assert.equal(spawned, 1);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("ensureDaemon times out when the descriptor never becomes ready", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  try {
    const descriptorPath = join(dir, "runtime.json");
    let clock = 0;
    await assert.rejects(
      ensureDaemon(
        { descriptorPath, workspace: dir, database: join(dir, "db"), timeoutSeconds: 5 },
        {
          fetch: okFetch,
          spawn: (() => fakeChild()) as DaemonDeps["spawn"],
          sleep: async () => {},
          now: () => (clock += 1000),
          resolveCommand: () => ["agent-os-runtime"],
        },
      ),
      /did not become ready/,
    );
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("ensureDaemon fails closed when the launcher errors", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  try {
    const descriptorPath = join(dir, "runtime.json");
    const errorChild = {
      unref() {},
      once(event: string, cb: (arg?: unknown) => void) {
        if (event === "error") cb(new Error("spawn ENOENT"));
        return errorChild;
      },
    } as unknown as ChildProcess;
    await assert.rejects(
      ensureDaemon(
        { descriptorPath, workspace: dir, database: join(dir, "db") },
        {
          fetch: okFetch,
          spawn: (() => errorChild) as DaemonDeps["spawn"],
          resolveCommand: () => ["/nonexistent/agent-os-runtime"],
        },
      ),
      /failed to start daemon/,
    );
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
