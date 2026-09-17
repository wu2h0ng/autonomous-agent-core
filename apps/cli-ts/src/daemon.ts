/**
 * Daemon lifecycle for the terminal client.
 *
 * Mainstream agent CLIs are self-contained: the user types the product name and
 * the agent starts whatever sidecar it needs. Agent OS is a client to a Python
 * governance daemon, so the client resolves the daemon on demand — attaching to
 * a healthy one, or starting one in the background (inheriting the caller's
 * environment so a provider key exported in the shell flows through) — so that
 * `agentos` alone works. Launcher resolution (`resolveDaemonLaunch`) prefers the
 * checkout the caller stands in over any separately installed runtime, so a
 * source checkout never silently talks to a different build or database.
 */
import {
  execFileSync,
  spawn as nodeSpawn,
  type ChildProcess,
} from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { rm } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import {
  DEFAULT_RUNTIME_DESCRIPTOR,
  loadRuntimeDescriptor,
  type RuntimeDescriptor,
} from "./descriptor.js";

export interface DaemonPaths {
  descriptorPath: string;
  workspace: string;
  database: string;
}

export interface DaemonDeps {
  spawn: (command: string, args: string[], options: Record<string, unknown>) => ChildProcess;
  fetch: typeof fetch;
  sleep: (ms: number) => Promise<void>;
  now: () => number;
  resolveLaunch: (env: NodeJS.ProcessEnv) => DaemonLaunchPlan | null;
  matchProcess: (pid: number, descriptorPath: string) => boolean;
}

/** Where a resolved launcher came from; `doctor` reports it to the user. */
export type DaemonLaunchSource =
  | "override"
  | "checkout"
  | "path"
  | "uv";

export interface DaemonLaunchPlan {
  command: string[];
  source: DaemonLaunchSource;
  /**
   * Checkout the command must run in (only for `source: "checkout"`), else null.
   * Distinct from `--workspace`: `uv run` resolves the checkout's workspace
   * packages from this directory, while `--workspace` stays the user's own.
   */
  checkoutRoot: string | null;
}

export interface DaemonResolveDeps {
  hasOnPath: (name: string) => boolean;
  /** Nearest enclosing agent-os checkout of a directory, or null. */
  findCheckout: (startDir: string) => string | null;
  /** Directory the checkout search starts from. */
  cwd: () => string;
}

export function defaultDaemonPaths(workspace: string = process.cwd()): DaemonPaths {
  const home = homedir();
  return {
    descriptorPath:
      process.env.AGENT_OS_RUNTIME_DESCRIPTOR || DEFAULT_RUNTIME_DESCRIPTOR,
    workspace,
    database:
      process.env.AGENT_OS_RUNTIME_DATABASE ||
      join(home, ".agent-os", "agent-os.sqlite3"),
  };
}

const RUNTIME_SCRIPT = "agent-os-runtime";

/** Steady-state readiness poll interval (the long-standing cadence). */
const READY_POLL_MS = 300;
/** Fast interval for the first moments of a cold start. */
const READY_POLL_FAST_MS = 50;
/** How long the fast interval is used before backing off. */
const READY_POLL_FAST_WINDOW_MS = 2000;

/**
 * Resolve how to launch the daemon, or null when no launcher is available.
 *
 * Order, and why: an explicit `AGENT_OS_RUNTIME_CMD` beats everything; next the
 * checkout the caller is standing in, because a separate install of
 * `agent-os-runtime` (e.g. the uv tool install under
 * `~/.local/share/uv/tools/`) is a *different build* that may serve a different
 * kernel against a different database — the client used to prefer it whenever
 * it was on PATH, even inside a source checkout. Only then PATH, then a bare
 * `uv run`, then nothing.
 */
export function resolveDaemonLaunch(
  env: NodeJS.ProcessEnv = process.env,
  deps: Partial<DaemonResolveDeps> = {},
): DaemonLaunchPlan | null {
  const hasOnPath = deps.hasOnPath ?? defaultHasOnPath;
  const findCheckout = deps.findCheckout ?? findCheckoutRoot;
  const cwd = deps.cwd ?? ((): string => process.cwd());
  const override = env.AGENT_OS_RUNTIME_CMD;
  if (override && override.trim()) {
    return {
      command: override.trim().split(/\s+/),
      source: "override",
      checkoutRoot: null,
    };
  }
  // `uv run` only resolves the checkout's workspace packages when it runs *in*
  // that checkout, so the checkout is also the plan's spawn cwd.
  const checkout = findCheckout(cwd());
  if (checkout !== null && hasOnPath("uv")) {
    return {
      command: ["uv", "run", RUNTIME_SCRIPT],
      source: "checkout",
      checkoutRoot: checkout,
    };
  }
  if (hasOnPath(RUNTIME_SCRIPT)) {
    return { command: [RUNTIME_SCRIPT], source: "path", checkoutRoot: null };
  }
  if (hasOnPath("uv")) {
    return {
      command: ["uv", "run", RUNTIME_SCRIPT],
      source: "uv",
      checkoutRoot: null,
    };
  }
  return null;
}

/** argv-only view of `resolveDaemonLaunch`, for callers that need just that. */
export function resolveDaemonCommand(
  env: NodeJS.ProcessEnv = process.env,
  deps: Partial<DaemonResolveDeps> = {},
): string[] | null {
  return resolveDaemonLaunch(env, deps)?.command ?? null;
}

function defaultHasOnPath(name: string): boolean {
  const path = process.env.PATH || "";
  for (const dir of path.split(":")) {
    if (dir && existsSync(join(dir, name))) return true;
  }
  return false;
}

/**
 * Nearest ancestor of `startDir` that is this repo's checkout: a `pyproject.toml`
 * declaring the `agent-os-runtime` console script, plus the workspace markers
 * (`packages/os_core` or `uv.lock`) that let `uv run` build the local packages
 * instead of falling back to an installed tool. Returns null outside a checkout.
 */
export function findCheckoutRoot(
  startDir: string,
  exists: (path: string) => boolean = existsSync,
  readFile: (path: string) => string | null = readFileOrNull,
): string | null {
  let dir = startDir;
  for (;;) {
    const manifest = readFile(join(dir, "pyproject.toml"));
    if (
      manifest !== null &&
      declaresConsoleScript(manifest, RUNTIME_SCRIPT) &&
      (exists(join(dir, "packages", "os_core")) || exists(join(dir, "uv.lock")))
    ) {
      return dir;
    }
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

function readFileOrNull(path: string): string | null {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

/** True when the TOML text assigns `name` inside a `[project.scripts]` table. */
function declaresConsoleScript(toml: string, name: string): boolean {
  let section = "";
  for (const rawLine of toml.split("\n")) {
    const line = rawLine.trim();
    if (line.startsWith("[")) {
      section = line.replace(/\s+/g, "");
      continue;
    }
    if (section !== "[project.scripts]") continue;
    if (line.split("=")[0]?.trim() === name) return true;
  }
  return false;
}

async function tryLoad(descriptorPath: string): Promise<RuntimeDescriptor | null> {
  try {
    return await loadRuntimeDescriptor(descriptorPath);
  } catch {
    return null;
  }
}

/** A daemon is healthy when its surface API answers an authenticated request. */
export async function daemonHealthy(
  descriptor: RuntimeDescriptor,
  fetchImpl: typeof fetch = fetch,
): Promise<boolean> {
  try {
    const response = await fetchImpl(
      `${descriptor.baseUrl}/v1/surface/sessions?limit=1`,
      { headers: { Authorization: `Bearer ${descriptor.bearer_token}` } },
    );
    return response.status === 200;
  } catch {
    return false;
  }
}

export interface EnsureDaemonOptions {
  descriptorPath: string;
  workspace: string;
  database: string;
  autoStart?: boolean;
  timeoutSeconds?: number;
}

/**
 * Attach to a healthy daemon, or start one in the background and wait until it
 * is ready. Throws when auto-start is disabled/unavailable or the daemon never
 * becomes ready.
 */
export async function ensureDaemon(
  options: EnsureDaemonOptions,
  deps?: Partial<DaemonDeps>,
): Promise<{ descriptor: RuntimeDescriptor; started: boolean }> {
  const resolved: DaemonDeps = {
    spawn: nodeSpawn as DaemonDeps["spawn"],
    fetch,
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now: Date.now,
    resolveLaunch: resolveDaemonLaunch,
    matchProcess: processMatchesDescriptor,
    ...deps,
  };
  const existing = await tryLoad(options.descriptorPath);
  if (existing && (await daemonHealthy(existing, resolved.fetch))) {
    return { descriptor: existing, started: false };
  }
  if (options.autoStart === false) {
    throw new Error(
      `no running daemon at ${options.descriptorPath}; start one or enable auto-start`,
    );
  }
  const launch = resolved.resolveLaunch(process.env);
  if (launch === null) {
    throw new Error(
      "no daemon launcher found; install agent-os-runtime, run from the repo with uv, " +
        "or set AGENT_OS_RUNTIME_CMD",
    );
  }
  // Stop a still-alive stale daemon before respawning, but only when the pid
  // is verified to be this runtime (never blind-kill a recycled pid).
  if (
    existing &&
    resolved.matchProcess(existing.pid, options.descriptorPath)
  ) {
    killPid(existing.pid);
  }
  await rm(options.descriptorPath, { force: true });
  const child = resolved.spawn(
    launch.command[0] as string,
    [
      ...launch.command.slice(1),
      "--workspace",
      options.workspace,
      "--database",
      options.database,
      "--descriptor",
      options.descriptorPath,
    ],
    {
      detached: true,
      stdio: "ignore",
      env: process.env,
      // Spawn cwd, NOT the workspace: `uv run` must stand in the checkout to
      // resolve that checkout's workspace packages. `--workspace` above stays
      // the user's own directory, which is a different thing.
      cwd: launch.checkoutRoot ?? options.workspace,
    },
  );
  try {
    await new Promise<void>((resolve, reject) => {
      child.once?.("spawn", () => resolve());
      child.once?.("error", (error: Error) => reject(error));
    });
  } catch (cause) {
    throw new Error(
      `failed to start daemon (${(cause as Error).message}); set ` +
        "AGENT_OS_RUNTIME_CMD or start it manually",
    );
  }
  child.unref?.();
  // Poll quickly while a cold start is plausible: the daemon is ready in well
  // under a second here (measured ~400ms for both launchers), and a flat 300ms
  // sleep made the client hand back ~200ms *after* readiness (measured 610ms
  // total). Past the window it backs off to the old cadence, so a slow or
  // half-dead daemon is not hammered for the whole timeout.
  const startedAt = resolved.now();
  const deadline = startedAt + (options.timeoutSeconds ?? 20) * 1000;
  const fastUntil = startedAt + READY_POLL_FAST_WINDOW_MS;
  while (resolved.now() < deadline) {
    await resolved.sleep(
      resolved.now() < fastUntil ? READY_POLL_FAST_MS : READY_POLL_MS,
    );
    const descriptor = await tryLoad(options.descriptorPath);
    if (descriptor && (await daemonHealthy(descriptor, resolved.fetch))) {
      return { descriptor, started: true };
    }
  }
  throw new Error(
    "daemon did not become ready in time; verify the provider configuration " +
      "or start it manually with `agentos daemon start`",
  );
}

/** True when the pid runs this runtime with our registry descriptor argument. */
function processMatchesDescriptor(pid: number, descriptorPath: string): boolean {
  try {
    const out = execFileSync("ps", ["-p", String(pid), "-o", "command="], {
      encoding: "utf8",
    });
    return out.includes(descriptorPath);
  } catch {
    return false;
  }
}

function killPid(pid: number): void {
  try {
    process.kill(pid, "SIGTERM");
  } catch {
    // already gone
  }
}

/** Stop the daemon referenced by a descriptor and remove the descriptor. */
export async function stopDaemon(descriptorPath: string): Promise<boolean> {
  const descriptor = await tryLoad(descriptorPath);
  if (descriptor === null) return false;
  if (!processMatchesDescriptor(descriptor.pid, descriptorPath)) {
    // Do not blind-kill a recycled pid; drop the stale descriptor only.
    await rm(descriptorPath, { force: true });
    return false;
  }
  killPid(descriptor.pid);
  await rm(descriptorPath, { force: true });
  return true;
}
