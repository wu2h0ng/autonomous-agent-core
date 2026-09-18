/**
 * Private runtime descriptor loading (~/.agent-os/runtime.json by default).
 * The descriptor is the client's only route into daemon-owned state; the
 * bearer token never leaves this process and is never logged.
 */
import { readFile } from "node:fs/promises";
import { homedir, hostname } from "node:os";
import { join } from "node:path";
import { z } from "zod";

import {
  SURFACE_PROTOCOL_READABLE_VERSIONS,
  SURFACE_PROTOCOL_VERSION,
  SurfaceProtocolVersionSchema,
} from "./contracts.js";

export const DEFAULT_RUNTIME_DESCRIPTOR = join(homedir(), ".agent-os", "runtime.json");

/** Shape of a `MAJOR.MINOR` version, mirroring `parse_surface_protocol_version`. */
const PROTOCOL_VERSION_SHAPE = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;

/** The path holds no descriptor: there is no daemon to attach to. */
export class RuntimeDescriptorNotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RuntimeDescriptorNotFoundError";
  }
}

/**
 * The descriptor is readable but names a surface protocol version this client
 * does not read.
 *
 * Typed because the reaction is not "start a daemon": the descriptor was written
 * by another build, which is probably still RUNNING, and this file is that
 * daemon's only handle. Replacing it would strand a live daemon; the caller must
 * stop and say so instead.
 */
export class SurfaceProtocolSkewError extends Error {
  constructor(
    message: string,
    readonly clientVersion: string,
    readonly serverVersion: string,
  ) {
    super(message);
    this.name = "SurfaceProtocolSkewError";
  }
}

const RuntimeDescriptorSchema = z.object({
  // Ordered acceptance, not a pin: a descriptor written by a runtime one minor
  // behind still names a version this client reads (see SURFACE_PROTOCOL_READABLE_VERSIONS).
  protocol_version: SurfaceProtocolVersionSchema,
  pid: z.number().int().positive(),
  boot_id: z.string().min(1),
  host: z.literal("127.0.0.1"),
  port: z.number().int().min(1).max(65535),
  bearer_token: z.string().min(1),
  database_path: z.string().min(1),
  workspace_path: z.string().min(1),
  created_at: z.string().min(1),
});

export type RuntimeDescriptor = z.infer<typeof RuntimeDescriptorSchema> & {
  baseUrl: string;
};

export async function loadRuntimeDescriptor(
  path: string = DEFAULT_RUNTIME_DESCRIPTOR,
): Promise<RuntimeDescriptor> {
  let raw: string;
  try {
    raw = await readFile(path, "utf8");
  } catch {
    throw new RuntimeDescriptorNotFoundError(
      `runtime descriptor not found at ${path}; start the daemon first (noem daemon start / scripts/dev_daemon.py)`,
    );
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`runtime descriptor at ${path} is not valid JSON`);
  }
  const declared =
    typeof parsed === "object" && parsed !== null
      ? (parsed as { protocol_version?: unknown }).protocol_version
      : undefined;
  if (
    typeof declared === "string" &&
    PROTOCOL_VERSION_SHAPE.test(declared) &&
    !(SURFACE_PROTOCOL_READABLE_VERSIONS as readonly string[]).includes(declared)
  ) {
    // Reported as the version skew it is, before the schema dump: a well-formed
    // version outside the declared set is a build mismatch, and the operator
    // needs to know which side is older, not which field zod disliked.
    throw new SurfaceProtocolSkewError(
      `runtime descriptor at ${path} speaks surface protocol ${declared}, which this ` +
        `client ${SURFACE_PROTOCOL_VERSION} does not read (reads ` +
        `${SURFACE_PROTOCOL_READABLE_VERSIONS.join(", ")}); this is a version skew, not ` +
        `a corrupt descriptor — upgrade the older side, or delete the descriptor if no ` +
        `daemon is running`,
      SURFACE_PROTOCOL_VERSION,
      declared,
    );
  }
  const descriptor = RuntimeDescriptorSchema.parse(parsed);
  return { ...descriptor, baseUrl: `http://${descriptor.host}:${descriptor.port}` };
}

export function localHostname(): string {
  return hostname() || "local";
}
