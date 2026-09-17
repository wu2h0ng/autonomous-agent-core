/**
 * Daemon lifecycle tests (dependency-injected): attach to a healthy daemon,
 * auto-start one when the descriptor is missing, and refuse when no launcher
 * exists. No real process is spawned and no real network is used.
 */
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import type { ChildProcess } from "node:child_process";
import {
  daemonHealthy,
  ensureDaemon,
  findCheckoutRoot,
  resolveDaemonCommand,
  resolveDaemonLaunch,
  stopDaemon,
  type DaemonDeps,
  type DaemonLaunchPlan,
  type DaemonLaunchSource,
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

/** A pinned launcher for tests that exercise the lifecycle, not resolution. */
function launch(
  command: string[],
  source: DaemonLaunchSource = "path",
  checkoutRoot: string | null = null,
): DaemonLaunchPlan {
  return { command, source, checkoutRoot };
}

const noCheckout = {
  hasOnPath: () => false,
  findCheckout: () => null,
  cwd: () => "/nowhere",
};

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

test("resolveDaemonLaunch honors override, checkout, PATH, uv, and absence", () => {
  const bothOnPath = (name: string): boolean => name === "agent-os-runtime" || name === "uv";
  const env = {} as NodeJS.ProcessEnv;

  // override outranks everything, including the checkout the caller stands in
  assert.deepEqual(
    resolveDaemonLaunch({ AGENT_OS_RUNTIME_CMD: "python -m x" } as NodeJS.ProcessEnv, {
      hasOnPath: bothOnPath,
      findCheckout: () => "/repo",
      cwd: () => "/repo",
    }),
    launch(["python", "-m", "x"], "override"),
  );

  // the checkout the caller stands in beats a differently-installed runtime on
  // PATH, and carries its root as the spawn directory for `uv run`
  assert.deepEqual(
    resolveDaemonLaunch(env, {
      hasOnPath: bothOnPath,
      findCheckout: () => "/repo",
      cwd: () => "/repo/apps/cli-ts",
    }),
    launch(["uv", "run", "agent-os-runtime"], "checkout", "/repo"),
  );

  // a checkout without `uv` cannot be run from source, so PATH is used again
  assert.deepEqual(
    resolveDaemonLaunch(env, {
      hasOnPath: (name) => name === "agent-os-runtime",
      findCheckout: () => "/repo",
      cwd: () => "/repo",
    }),
    launch(["agent-os-runtime"], "path"),
  );

  // outside any checkout the order is unchanged: PATH, then a bare uv run
  assert.deepEqual(
    resolveDaemonLaunch(env, {
      hasOnPath: bothOnPath,
      findCheckout: () => null,
      cwd: () => "/elsewhere",
    }),
    launch(["agent-os-runtime"], "path"),
  );
  assert.deepEqual(
    resolveDaemonLaunch(env, {
      hasOnPath: (name) => name === "uv",
      findCheckout: () => null,
      cwd: () => "/elsewhere",
    }),
    launch(["uv", "run", "agent-os-runtime"], "uv"),
  );

  // nothing available at all
  assert.equal(resolveDaemonLaunch(env, noCheckout), null);

  // the argv view tracks the same resolution
  assert.deepEqual(
    resolveDaemonCommand(env, { ...noCheckout, hasOnPath: (n) => n === "agent-os-runtime" }),
    ["agent-os-runtime"],
  );
  assert.equal(resolveDaemonCommand(env, noCheckout), null);
});

test("findCheckoutRoot finds this repo's checkout from a nested directory", () => {
  const repoRoot = fileURLToPath(new URL("../../..", import.meta.url));
  const found = findCheckoutRoot(join(repoRoot, "apps", "cli-ts"));
  // `resolve` only normalizes the trailing slash a directory URL leaves behind
  assert.equal(found, resolve(repoRoot));
  assert.ok(found !== null && existsSync(join(found, "pyproject.toml")));
});

test("findCheckoutRoot requires the runtime script and the workspace markers", () => {
  const outer = mkdtempSync(join(tmpdir(), "agent-os-checkout-"));
  const manifest = [
    "[project]",
    'name = "x"',
    "",
    "[project.scripts]",
    'agent-os-runtime = "apps.runtime_daemon.__main__:main"',
    "",
  ].join("\n");
  const nested = join(outer, "apps", "cli-ts");
  mkdirSync(nested, { recursive: true });
  const marker = (text: string): void => writeFileSync(join(outer, "pyproject.toml"), text);

  // markers missing: neither packages/os_core nor uv.lock
  marker(manifest);
  assert.equal(findCheckoutRoot(nested), null);

  // uv.lock alone is enough
  writeFileSync(join(outer, "uv.lock"), "");
  assert.equal(findCheckoutRoot(nested), outer);

  // packages/os_core alone is enough
  rmSync(join(outer, "uv.lock"));
  mkdirSync(join(outer, "packages", "os_core"), { recursive: true });
  assert.equal(findCheckoutRoot(nested), outer);

  // a pyproject that does not declare the runtime script is not a checkout, even
  // when the markers are there (e.g. some other project's uv workspace)
  marker(manifest.replace("agent-os-runtime", "agent-os-something-else"));
  assert.equal(findCheckoutRoot(nested), null);

  // a script declared in another table does not count either
  marker('[project.optional-dependencies]\nagent-os-runtime = ["x"]\n');
  assert.equal(findCheckoutRoot(nested), null);

  rmSync(outer, { recursive: true, force: true });
});

test("findCheckoutRoot prefers the nearest enclosing checkout", () => {
  const outer = mkdtempSync(join(tmpdir(), "agent-os-checkout-"));
  const inner = join(outer, "vendor", "agent-os");
  mkdirSync(inner, { recursive: true });
  const manifest =
    "[project.scripts]\nagent-os-runtime = \"apps.runtime_daemon.__main__:main\"\n";
  for (const root of [outer, inner]) {
    writeFileSync(join(root, "pyproject.toml"), manifest);
    writeFileSync(join(root, "uv.lock"), "");
  }
  const deep = join(inner, "apps", "cli-ts");
  mkdirSync(deep, { recursive: true });
  assert.equal(findCheckoutRoot(deep), inner);
  rmSync(outer, { recursive: true, force: true });
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
        resolveLaunch: () => launch(["agent-os-runtime"]),
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

test("ensureDaemon spawns a checkout launcher in the checkout, not the workspace", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  const checkout = await mkdtemp(join(tmpdir(), "agent-os-checkout-"));
  try {
    const descriptorPath = join(dir, "runtime.json");
    const spawns: { argv: string[]; cwd: unknown }[] = [];
    const spawn = ((command: string, args: string[], options: Record<string, unknown>) => {
      spawns.push({ argv: [command, ...args], cwd: options["cwd"] });
      return fakeChild(() => writeFileSync(descriptorPath, descriptorJson()));
    }) as DaemonDeps["spawn"];
    const options = { descriptorPath, workspace: dir, database: join(dir, "db") };

    // `uv run` must stand in the checkout to resolve the local workspace
    // packages; --workspace keeps pointing at the user's directory.
    await ensureDaemon(options, {
      fetch: okFetch,
      spawn,
      sleep: async () => {},
      resolveLaunch: () => launch(["uv", "run", "agent-os-runtime"], "checkout", checkout),
    });
    assert.equal(spawns[0]?.cwd, checkout);
    assert.notEqual(spawns[0]?.cwd, dir);
    const argv = spawns[0]?.argv ?? [];
    assert.equal(argv[argv.indexOf("--workspace") + 1], dir);

    // A PATH-resolved runtime keeps the previous spawn directory.
    await rm(descriptorPath, { force: true });
    await ensureDaemon(options, {
      fetch: okFetch,
      spawn,
      sleep: async () => {},
      resolveLaunch: () => launch(["agent-os-runtime"], "path"),
    });
    assert.equal(spawns[1]?.cwd, dir);
  } finally {
    await rm(dir, { recursive: true, force: true });
    await rm(checkout, { recursive: true, force: true });
  }
});

test("ensureDaemon fails closed without a launcher or with auto-start off", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  try {
    const descriptorPath = join(dir, "runtime.json");
    await assert.rejects(
      ensureDaemon(
        { descriptorPath, workspace: dir, database: join(dir, "db") },
        { fetch: okFetch, resolveLaunch: () => null },
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

test("ensureDaemon polls fast during a cold start and then backs off", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  try {
    const descriptorPath = join(dir, "runtime.json");
    const sleeps: number[] = [];
    let clock = 0;
    await assert.rejects(
      ensureDaemon(
        { descriptorPath, workspace: dir, database: join(dir, "db"), timeoutSeconds: 3 },
        {
          fetch: okFetch,
          spawn: (() => fakeChild()) as DaemonDeps["spawn"],
          sleep: async (ms) => {
            sleeps.push(ms);
            clock += ms;
          },
          now: () => clock,
          resolveLaunch: () => launch(["agent-os-runtime"]),
        },
      ),
      /did not become ready/,
    );
    // A cold start is over in well under a second, so the first polls must not
    // wait the steady-state 300ms; a revert to a flat 300ms fails this.
    assert.ok(sleeps.length > 3, `the ready poll must run: ${sleeps.join(",")}`);
    assert.ok(
      sleeps.slice(0, 3).every((ms) => ms === 50),
      `fast first polls: ${sleeps.join(",")}`,
    );
    // Past the window it backs off, so a half-dead daemon is not hammered.
    assert.ok(sleeps.includes(300), `backs off: ${sleeps.join(",")}`);
    assert.equal(sleeps[sleeps.length - 1], 300);
  } finally {
    await rm(dir, { recursive: true, force: true });
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
        resolveLaunch: () => launch(["agent-os-runtime"]),
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
          resolveLaunch: () => launch(["agent-os-runtime"]),
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
          resolveLaunch: () => launch(["/nonexistent/agent-os-runtime"]),
        },
      ),
      /failed to start daemon/,
    );
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
