/**
 * Private runtime descriptor loading (~/.agent-os/runtime.json by default).
 * The descriptor is the client's only route into daemon-owned state; the
 * bearer token never leaves this process and is never logged.
 */
import { readFile } from "node:fs/promises";
import { homedir, hostname } from "node:os";
import { join } from "node:path";
import { z } from "zod";

export const DEFAULT_RUNTIME_DESCRIPTOR = join(homedir(), ".agent-os", "runtime.json");

const RuntimeDescriptorSchema = z.object({
  protocol_version: z.literal("1.1"),
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
    throw new Error(
      `runtime descriptor not found at ${path}; start the daemon first (noem daemon start / scripts/dev_daemon.py)`,
    );
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`runtime descriptor at ${path} is not valid JSON`);
  }
  const descriptor = RuntimeDescriptorSchema.parse(parsed);
  return { ...descriptor, baseUrl: `http://${descriptor.host}:${descriptor.port}` };
}

export function localHostname(): string {
  return hostname() || "local";
}
