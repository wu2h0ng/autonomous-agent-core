/**
 * Daemon lifecycle for the terminal client.
 *
 * Mainstream agent CLIs are self-contained: the user types the product name and
 * the agent starts whatever sidecar it needs. Agent OS is a client to a Python
 * governance daemon, so the client resolves the daemon on demand — attaching to
 * a healthy one, or starting one in the background (inheriting the caller's
 * environment so a provider key exported in the shell flows through) — so that
 * `agentos` alone works.
 */
import { spawn as nodeSpawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { rm } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
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
  resolveCommand: (env: NodeJS.ProcessEnv) => string[] | null;
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

/** Resolve how to launch the daemon, or null when no launcher is available. */
export function resolveDaemonCommand(
  env: NodeJS.ProcessEnv = process.env,
  hasOnPath: (name: string) => boolean = defaultHasOnPath,
): string[] | null {
  const override = env.AGENT_OS_RUNTIME_CMD;
  if (override && override.trim()) return override.trim().split(/\s+/);
  if (hasOnPath("agent-os-runtime")) return ["agent-os-runtime"];
  if (hasOnPath("uv")) return ["uv", "run", "agent-os-runtime"];
  return null;
}

function defaultHasOnPath(name: string): boolean {
  const path = process.env.PATH || "";
  for (const dir of path.split(":")) {
    if (dir && existsSync(join(dir, name))) return true;
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
    resolveCommand: resolveDaemonCommand,
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
  const command = resolved.resolveCommand(process.env);
  if (command === null) {
    throw new Error(
      "no daemon launcher found; install agent-os-runtime, run from the repo with uv, " +
        "or set AGENT_OS_RUNTIME_CMD",
    );
  }
  await rm(options.descriptorPath, { force: true });
  const child = resolved.spawn(
    command[0] as string,
    [
      ...command.slice(1),
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
      cwd: options.workspace,
    },
  );
  child.unref?.();
  const deadline = Date.now() + (options.timeoutSeconds ?? 20) * 1000;
  while (Date.now() < deadline) {
    await resolved.sleep(300);
    const descriptor = await tryLoad(options.descriptorPath);
    if (descriptor && (await daemonHealthy(descriptor, resolved.fetch))) {
      return { descriptor, started: true };
    }
  }
  throw new Error(
    "daemon did not become ready in time; check the daemon log / provider configuration",
  );
}

/** Stop the daemon referenced by a descriptor and remove the descriptor. */
export async function stopDaemon(descriptorPath: string): Promise<boolean> {
  const descriptor = await tryLoad(descriptorPath);
  if (descriptor === null) return false;
  try {
    process.kill(descriptor.pid, "SIGTERM");
  } catch {
    // already gone
  }
  await rm(descriptorPath, { force: true });
  return true;
}
