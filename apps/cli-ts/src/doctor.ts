/**
 * `doctor` — read-only environment self-check (mainstream parity: claude
 * doctor / codex doctor). Never mutates runtime state: the server probe is a
 * GET for a deliberately nonexistent session id, which exercises routing,
 * auth and protocol headers without creating anything.
 *
 * Checks, in order:
 *   1. descriptor     runtime.json found and parseable (token never printed)
 *   2. reachable      base_url answers HTTP at all
 *   3. auth           bearer token accepted (401 = fail; typed 404 = pass)
 *   4. protocol       server speaks the same surface protocol major version
 *
 * Identity lines (`notes`) come first and never affect `ok`/the exit code: which
 * launcher would be started, where it came from — a runtime resolved outside the
 * checkout the caller stands in is warned about, because that is how a client
 * ends up on a different build and a different database without the user seeing
 * it — plus the pid/port/database/workspace the descriptor actually names. The
 * launcher line is printed even when the descriptor is missing, which is exactly
 * the state in which auto-start used to pick up a foreign runtime.
 *
 * Exit: 0 all pass, 1 any failure.
 */

import { SURFACE_PROTOCOL_VERSION } from "./contracts.js";
import {
  findCheckoutRoot,
  resolveDaemonLaunch,
  type DaemonResolveDeps,
} from "./daemon.js";
import {
  DEFAULT_RUNTIME_DESCRIPTOR,
  loadRuntimeDescriptor,
  type RuntimeDescriptor,
} from "./descriptor.js";

export interface DoctorCheck {
  name: string;
  ok: boolean;
  detail: string;
}

/** Informational identity line; `warn` marks a likely-wrong kernel. */
export interface DoctorNote {
  level: "info" | "warn";
  text: string;
}

export interface DoctorReport {
  checks: DoctorCheck[];
  notes: DoctorNote[];
  ok: boolean;
}

export interface DoctorOptions {
  /** Env used for launcher resolution (defaults to `process.env`). */
  env?: NodeJS.ProcessEnv;
  /** Injectable launcher resolution, so callers/tests can pin it. */
  resolve?: Partial<DaemonResolveDeps>;
}

type FetchLike = (
  url: string,
  init: { method: string; headers: Record<string, string> },
) => Promise<{ status: number; json: () => Promise<unknown> }>;

const PROBE_SESSION = "doctor-probe-nonexistent";

/**
 * Which launcher a daemon would be started with, and where it came from. Marked
 * `warn` when the caller stands in a checkout but the resolution points
 * elsewhere (PATH install, `uv run` fallback or AGENT_OS_RUNTIME_CMD): that
 * daemon is not this checkout and may be a different build with a different
 * database.
 */
function launcherNotes(
  env: NodeJS.ProcessEnv,
  deps: Partial<DaemonResolveDeps>,
): DoctorNote[] {
  const cwd = (deps.cwd ?? ((): string => process.cwd()))();
  const checkout = (deps.findCheckout ?? findCheckoutRoot)(cwd);
  const plan = resolveDaemonLaunch(env, deps);
  if (plan === null) {
    return [
      {
        level: "warn",
        text:
          `launcher: none — no checkout with agent-os-runtime at or above ${cwd}, ` +
          "no agent-os-runtime on PATH, no uv; set AGENT_OS_RUNTIME_CMD",
      },
    ];
  }
  const argv = plan.command.join(" ");
  if (plan.source === "checkout" && plan.checkoutRoot !== null) {
    return [
      {
        level: "info",
        text:
          `launcher: ${argv} — from the checkout at ${plan.checkoutRoot} (this ` +
          "checkout); a daemon it starts runs there, while --workspace stays your directory",
      },
    ];
  }
  const origin =
    plan.source === "override"
      ? "AGENT_OS_RUNTIME_CMD"
      : plan.source === "path"
        ? "agent-os-runtime on PATH"
        : "uv run fallback (no checkout found)";
  return [
    {
      level: checkout === null ? "info" : "warn",
      text:
        checkout === null
          ? `launcher: ${argv} — ${origin}, NOT this checkout (no checkout at or above ${cwd})`
          : `launcher: ${argv} — ${origin}, NOT this checkout (${checkout}); ` +
            "a daemon it starts may be a different build and may use a different database",
    },
  ];
}

/** What the descriptor itself names (port, database) — never invented. */
function descriptorNote(
  descriptor: RuntimeDescriptor,
  descriptorPath: string,
): DoctorNote {
  return {
    level: "info",
    text:
      `daemon (from descriptor): pid ${descriptor.pid}, port ${descriptor.port}, ` +
      `database ${descriptor.database_path}, workspace ${descriptor.workspace_path} ` +
      `(descriptor ${descriptorPath})`,
  };
}

export async function runDoctor(
  descriptorPath?: string,
  fetchImpl?: FetchLike,
  options: DoctorOptions = {},
): Promise<DoctorReport> {
  const checks: DoctorCheck[] = [];
  const notes: DoctorNote[] = launcherNotes(
    options.env ?? process.env,
    options.resolve ?? {},
  );
  const doFetch: FetchLike = fetchImpl ?? (fetch as never as FetchLike);
  const resolvedPath = descriptorPath ?? DEFAULT_RUNTIME_DESCRIPTOR;

  // 1. descriptor
  let descriptor: RuntimeDescriptor | null = null;
  try {
    descriptor = await loadRuntimeDescriptor(descriptorPath);
    checks.push({
      name: "descriptor",
      ok: true,
      detail: `${resolvedPath} → ${descriptor.baseUrl} (token loaded, never shown)`,
    });
  } catch (cause) {
    checks.push({ name: "descriptor", ok: false, detail: (cause as Error).message });
    return { checks, notes, ok: false };
  }
  notes.push(descriptorNote(descriptor, resolvedPath));

  // 2./3. reachable + auth + 4. protocol, via one read-only probe
  const url = `${descriptor.baseUrl}/v1/surface/sessions/${PROBE_SESSION}`;
  let status: number;
  let body: unknown;
  try {
    const response = await doFetch(url, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${descriptor.bearer_token}`,
        "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
      },
    });
    status = response.status;
    body = await response.json().catch(() => null);
  } catch (cause) {
    checks.push(
      { name: "reachable", ok: false, detail: `${descriptor.baseUrl} — ${(cause as Error).message}` },
      { name: "auth", ok: false, detail: "skipped (daemon unreachable)" },
      { name: "protocol", ok: false, detail: "skipped (daemon unreachable)" },
    );
    return { checks, notes, ok: false };
  }
  checks.push({ name: "reachable", ok: true, detail: `${descriptor.baseUrl} (HTTP ${status})` });

  if (status === 401 || status === 403) {
    checks.push({
      name: "auth",
      ok: false,
      detail: `HTTP ${status} — token rejected; restart the daemon to mint a fresh descriptor`,
    });
    checks.push({ name: "protocol", ok: false, detail: "skipped (auth failed)" });
    return { checks, notes, ok: false };
  }
  checks.push({ name: "auth", ok: true, detail: "bearer token accepted" });

  const serverVersion =
    body && typeof body === "object" && "protocol_version" in body
      ? String((body as Record<string, unknown>)["protocol_version"])
      : null;
  if (serverVersion === null) {
    // A typed error without a version field still proves the protocol path;
    // report honestly instead of inventing compatibility.
    checks.push({
      name: "protocol",
      ok: status === 404,
      detail:
        status === 404
          ? `typed 404 for unknown session (protocol path ok; version field absent)`
          : `unexpected HTTP ${status} for a nonexistent session`,
    });
  } else {
    const compatible = serverVersion.split(".")[0] === SURFACE_PROTOCOL_VERSION.split(".")[0];
    checks.push({
      name: "protocol",
      ok: compatible,
      detail: `client ${SURFACE_PROTOCOL_VERSION} ↔ server ${serverVersion}${compatible ? "" : " — MAJOR MISMATCH"}`,
    });
  }

  return { checks, notes, ok: checks.every((check) => check.ok) };
}

export function renderDoctorText(report: DoctorReport): string {
  // Identity first: "who am I talking to" is what a user cannot otherwise see.
  const lines = report.notes.map(
    (note) => `${note.level === "warn" ? "!" : "·"} ${note.text}`,
  );
  lines.push(
    ...report.checks.map(
      (check) => `${check.ok ? "✓" : "✗"} ${check.name}: ${check.detail}`,
    ),
  );
  lines.push(report.ok ? "doctor: all checks passed" : "doctor: FAILURES present — see ✗ lines");
  return `${lines.join("\n")}\n`;
}
