/**
 * Daemon lifecycle tests (dependency-injected): attach to a healthy daemon,
 * auto-start one when the descriptor is missing, and refuse when no launcher
 * exists. No real process is spawned and no real network is used.
 */
import assert from "node:assert/strict";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import type { ChildProcess } from "node:child_process";
import {
  daemonHealthy,
  danglingShimRepairHint,
  detectDanglingPathShim,
  ensureDaemon,
  findCheckoutRoot,
  resolveDaemonCandidates,
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

/** A fake launcher that dies the way a broken checkout's launcher does. */
function fakeExitingChild(exitCode: number): ChildProcess {
  const child = {
    unref() {},
    once(event: string, cb: (arg?: unknown, extra?: unknown) => void) {
      if (event === "exit") cb(exitCode, null);
      if (event === "spawn") cb();
      return child;
    },
  };
  return child as unknown as ChildProcess;
}

test("resolveDaemonCandidates orders the checkout, PATH and uv launchers", () => {
  const bothOnPath = (name: string): boolean =>
    name === "agent-os-runtime" || name === "uv";
  assert.deepEqual(
    resolveDaemonCandidates({} as NodeJS.ProcessEnv, {
      hasOnPath: bothOnPath,
      findCheckout: () => "/repo",
      cwd: () => "/repo",
    }),
    [
      launch(["uv", "run", "agent-os-runtime"], "checkout", "/repo"),
      launch(["agent-os-runtime"], "path"),
      launch(["uv", "run", "agent-os-runtime"], "uv"),
    ],
  );
  // AGENT_OS_RUNTIME_CMD is the ONLY candidate: the user named that command, so
  // quietly starting a different runtime instead would betray the promise the
  // override makes.
  assert.deepEqual(
    resolveDaemonCandidates(
      { AGENT_OS_RUNTIME_CMD: "python -m x" } as NodeJS.ProcessEnv,
      { hasOnPath: bothOnPath, findCheckout: () => "/repo", cwd: () => "/repo" },
    ),
    [launch(["python", "-m", "x"], "override")],
  );
  assert.deepEqual(resolveDaemonCandidates({} as NodeJS.ProcessEnv, noCheckout), []);
});

test("ensureDaemon falls back when the preferred launcher dies before readiness", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  try {
    const descriptorPath = join(dir, "runtime.json");
    const checkoutLog = join(dir, "daemon-launch-checkout.log");
    const pathLog = join(dir, "daemon-launch-path.log");
    const spawned: string[] = [];
    const warnings: string[] = [];
    let clock = 0;
    const spawn = ((command: string, args: string[]) => {
      spawned.push([command, ...args].join(" "));
      if (command === "uv") {
        // What a real broken checkout does: `uv run` exits 2 within
        // milliseconds and puts the reason on stderr (measured 0.016s with a
        // malformed uv.lock).
        writeFileSync(checkoutLog, "key with no value, expected `=`\n");
        return fakeExitingChild(2);
      }
      return fakeChild(() => writeFileSync(descriptorPath, descriptorJson()));
    }) as DaemonDeps["spawn"];
    const result = await ensureDaemon(
      { descriptorPath, workspace: dir, database: join(dir, "db") },
      {
        fetch: okFetch,
        spawn,
        sleep: async (ms) => {
          clock += ms;
        },
        now: () => clock,
        warn: (message) => warnings.push(message),
        resolveLaunch: () => [
          launch(["uv", "run", "agent-os-runtime"], "checkout", "/broken/checkout"),
          launch(["agent-os-runtime"], "path"),
        ],
      },
    );
    assert.equal(result.started, true);
    assert.equal(result.descriptor.port, 12345);
    assert.equal(spawned.length, 2, "the next candidate must be tried");
    assert.match(spawned[0] ?? "", /^uv run agent-os-runtime --workspace /);
    assert.match(spawned[1] ?? "", /^agent-os-runtime --workspace /);
    // The failure was detected, not waited out: a blind wait would burn the
    // whole 20s deadline before ever reaching the PATH launcher.
    assert.ok(clock < 2000, `fell back only after ${clock}ms`);
    // And the fallback is visible: what failed, where its output went, what took
    // over. Silence here is what made the original regression mysterious.
    assert.equal(warnings.length, 1);
    const warning = warnings[0] ?? "";
    assert.match(
      warning,
      /checkout launcher "uv run agent-os-runtime" \(checkout \/broken\/checkout\): exited 2 after 0\.00s/,
    );
    assert.match(warning, /daemon-launch-checkout\.log/);
    assert.match(warning, /falling back to "agent-os-runtime" \(PATH\)/);
    // the dead launcher's output is kept for the user; the live one's is not
    assert.ok(existsSync(checkoutLog), "the failed launcher's output must be kept");
    assert.ok(!existsSync(pathLog), "the successful launcher needs no capture file");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("ensureDaemon refuses when every launcher fails, quoting stderr but never secrets", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  try {
    const descriptorPath = join(dir, "runtime.json");
    const pathLog = join(dir, "daemon-launch-path.log");
    const TOKEN = "descriptor-token-must-never-be-printed";
    let clock = 0;
    const spawn = ((command: string) => {
      if (command === "uv") {
        writeFileSync(
          join(dir, "daemon-launch-checkout.log"),
          "error: Failed to parse `uv.lock`\nkey with no value, expected `=`\n",
        );
        return fakeExitingChild(2);
      }
      // A launcher that wrote a descriptor (so its token is on disk) and echoed
      // that token before it died.
      writeFileSync(
        descriptorPath,
        JSON.stringify({
          protocol_version: "1.1",
          pid: 5151,
          boot_id: "boot:dead",
          host: "127.0.0.1",
          port: 12399,
          bearer_token: TOKEN,
          database_path: "/tmp/db",
          workspace_path: "/tmp/ws",
          created_at: new Date().toISOString(),
        }),
      );
      writeFileSync(pathLog, `starting with token ${TOKEN}\nfatal: could not bind\n`);
      return fakeExitingChild(3);
    }) as DaemonDeps["spawn"];
    await assert.rejects(
      ensureDaemon(
        { descriptorPath, workspace: dir, database: join(dir, "db"), timeoutSeconds: 5 },
        {
          fetch: badFetch,
          spawn,
          sleep: async (ms) => {
            clock += ms;
          },
          now: () => clock,
          warn: () => {},
          resolveLaunch: () => [
            launch(["uv", "run", "agent-os-runtime"], "checkout", "/broken/checkout"),
            launch(["agent-os-runtime"], "path"),
          ],
        },
      ),
      (error: Error) => {
        assert.match(error.message, /did not become ready in time/);
        // the real cause, from the launcher's own stderr, for every candidate
        assert.match(error.message, /key with no value, expected `=`/);
        assert.match(error.message, /fatal: could not bind/);
        assert.match(error.message, /exited 2 after 0\.00s/);
        assert.match(error.message, /exited 3 after 0\.00s/);
        assert.match(error.message, /full output: .*daemon-launch-path\.log/);
        assert.ok(
          !error.message.includes(TOKEN),
          `the descriptor token leaked: ${error.message}`,
        );
        return true;
      },
    );
    // the retained capture is redacted too, not only the message
    const kept = readFileSync(pathLog, "utf8");
    assert.ok(!kept.includes(TOKEN), `the token leaked into ${pathLog}: ${kept}`);
    assert.match(kept, /fatal: could not bind/);
    // one deadline covers the whole chain, fallbacks included
    assert.ok(clock <= 5000, `the chain must fit one deadline: ${clock}ms`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("ensureDaemon captures a live launcher's stderr, not only its exit code", async () => {
  // The DEFAULT spawn is used on purpose: only a real process can prove the
  // launcher's stderr is wired to the capture file. A fake that writes the file
  // itself passes even with `stdio: "ignore"` — which is exactly the defect.
  const dir = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  try {
    const descriptorPath = join(dir, "runtime.json");
    const log = join(dir, "daemon-launch-path.log");
    await assert.rejects(
      ensureDaemon(
        { descriptorPath, workspace: dir, database: join(dir, "db"), timeoutSeconds: 10 },
        {
          fetch: okFetch,
          resolveLaunch: () => [
            launch(["/bin/sh", "-c", 'echo "boom: could not bind" >&2; exit 7'], "path"),
          ],
        },
      ),
      (error: Error) => {
        assert.match(error.message, /boom: could not bind/);
        assert.match(error.message, /exited 7 after 0\.0\ds/);
        return true;
      },
    );
    assert.match(readFileSync(log, "utf8"), /boom: could not bind/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("ensureDaemon still quotes a launcher's stderr when the descriptor dir is absent", async () => {
  const outer = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  const keptFiles: string[] = [];
  try {
    // A machine that has never run the daemon: the descriptor's directory does
    // not exist yet, so the capture cannot sit beside it. Dropping the cause
    // there is the same defect in a different state.
    const descriptorPath = join(outer, "missing", "runtime.json");
    await assert.rejects(
      ensureDaemon(
        { descriptorPath, workspace: outer, database: join(outer, "db"), timeoutSeconds: 10 },
        {
          fetch: okFetch,
          resolveLaunch: () => [
            launch(["/bin/sh", "-c", 'echo "boom: no runtime here" >&2; exit 7'], "path"),
          ],
        },
      ),
      (error: Error) => {
        assert.match(error.message, /boom: no runtime here/);
        const found = /full output: (.*)$/m.exec(error.message)?.[1];
        assert.ok(found, `no retained capture named: ${error.message}`);
        keptFiles.push(found);
        return true;
      },
    );
    const keptFile = keptFiles[0];
    assert.ok(keptFile !== undefined, "the capture must be reported");
    assert.match(readFileSync(keptFile, "utf8"), /boom: no runtime here/);
  } finally {
    for (const kept of keptFiles) {
      await rm(dirname(kept), { recursive: true, force: true });
    }
    await rm(outer, { recursive: true, force: true });
  }
});

test("ensureDaemon keeps AGENT_OS_RUNTIME_CMD above the whole fallback chain", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-os-daemon-"));
  const previous = process.env.AGENT_OS_RUNTIME_CMD;
  process.env.AGENT_OS_RUNTIME_CMD = "uv run agent-os-runtime";
  try {
    const descriptorPath = join(dir, "runtime.json");
    const spawned: string[] = [];
    const warnings: string[] = [];
    let clock = 0;
    // No injected launcher resolution here: the real resolver runs against
    // process.env, so this proves the override outranks a checkout, PATH and uv
    // that are all available on this machine.
    await assert.rejects(
      ensureDaemon(
        { descriptorPath, workspace: dir, database: join(dir, "db"), timeoutSeconds: 5 },
        {
          fetch: okFetch,
          spawn: ((command: string, args: string[]) => {
            spawned.push([command, ...args].join(" "));
            return fakeExitingChild(2);
          }) as DaemonDeps["spawn"],
          sleep: async (ms) => {
            clock += ms;
          },
          now: () => clock,
          warn: (message) => warnings.push(message),
        },
      ),
      /did not become ready/,
    );
    assert.equal(spawned.length, 1, "the override is the only candidate");
    assert.match(spawned[0] ?? "", /^uv run agent-os-runtime --workspace /);
    assert.deepEqual(warnings, [], "an explicit command is not a hint to fall back from");
  } finally {
    if (previous === undefined) delete process.env.AGENT_OS_RUNTIME_CMD;
    else process.env.AGENT_OS_RUNTIME_CMD = previous;
    await rm(dir, { recursive: true, force: true });
  }
});


// --- Bug 2026-09-19: dangling PATH shim detection ---------------------------
// A `uv tool install` whose shims landed in ~/.local/bin while UV_TOOL_DIR pointed
// at a temp dir leaves a symlink whose target vanishes after cleanup. The launcher
// must distinguish that from "nothing on PATH" and surface an actionable repair.

test("detectDanglingPathShim reports a broken symlink on PATH, null otherwise", async () => {
  const dir = await mkdtemp(join(tmpdir(), "dangling-shim-"));
  try {
    // A working (real) executable named agent-os-runtime: not dangling.
    mkdirSync(join(dir, "goodbin"));
    writeFileSync(join(dir, "goodbin", "agent-os-runtime"), "#!/bin/sh\ntrue\n");
    // A broken symlink pointing at a deleted target.
    mkdirSync(join(dir, "badbin"));
    symlinkSync(join(dir, "deleted-target"), join(dir, "badbin", "agent-os-runtime"));

    const pathWithDangling = join(dir, "badbin") + ":" + join(dir, "goodbin");
    const found = detectDanglingPathShim("agent-os-runtime", pathWithDangling);
    assert.ok(found, "should detect the dangling shim");
    assert.equal(found!.shim, join(dir, "badbin", "agent-os-runtime"));
    assert.equal(found!.target, join(dir, "deleted-target"));

    // Only a working shim: nothing dangling.
    assert.equal(
      detectDanglingPathShim("agent-os-runtime", join(dir, "goodbin")),
      null,
    );
    // No such entry at all: null.
    assert.equal(detectDanglingPathShim("does-not-exist", join(dir, "goodbin")), null);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("danglingShimRepairHint gives the reinstall command, null when healthy", async () => {
  const dir = await mkdtemp(join(tmpdir(), "dangling-hint-"));
  try {
    mkdirSync(join(dir, "bin"));
    symlinkSync(join(dir, "gone"), join(dir, "bin", "agent-os-runtime"));
    const hint = danglingShimRepairHint("agent-os-runtime", join(dir, "bin"));
    assert.ok(hint && hint.includes("uv tool install . --force --reinstall"));
    assert.ok(hint!.includes("broken symlink"));

    // Healthy (real) entry: no hint.
    rmSync(join(dir, "bin", "agent-os-runtime"));
    writeFileSync(join(dir, "bin", "agent-os-runtime"), "x");
    assert.equal(danglingShimRepairHint("agent-os-runtime", join(dir, "bin")), null);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
