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
 * Exit: 0 all pass, 1 any failure.
 */

import { SURFACE_PROTOCOL_VERSION } from "./contracts.js";
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

export interface DoctorReport {
  checks: DoctorCheck[];
  ok: boolean;
}

type FetchLike = (
  url: string,
  init: { method: string; headers: Record<string, string> },
) => Promise<{ status: number; json: () => Promise<unknown> }>;

const PROBE_SESSION = "doctor-probe-nonexistent";

export async function runDoctor(
  descriptorPath?: string,
  fetchImpl?: FetchLike,
): Promise<DoctorReport> {
  const checks: DoctorCheck[] = [];
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
    return { checks, ok: false };
  }

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
    return { checks, ok: false };
  }
  checks.push({ name: "reachable", ok: true, detail: `${descriptor.baseUrl} (HTTP ${status})` });

  if (status === 401 || status === 403) {
    checks.push({
      name: "auth",
      ok: false,
      detail: `HTTP ${status} — token rejected; restart the daemon to mint a fresh descriptor`,
    });
    checks.push({ name: "protocol", ok: false, detail: "skipped (auth failed)" });
    return { checks, ok: false };
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

  return { checks, ok: checks.every((check) => check.ok) };
}

export function renderDoctorText(report: DoctorReport): string {
  const lines = report.checks.map(
    (check) => `${check.ok ? "✓" : "✗"} ${check.name}: ${check.detail}`,
  );
  lines.push(report.ok ? "doctor: all checks passed" : "doctor: FAILURES present — see ✗ lines");
  return `${lines.join("\n")}\n`;
}
