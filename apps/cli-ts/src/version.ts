/**
 * Package version.
 *
 * Read from `package.json` next to the source tree / compiled bundle, with one
 * important exception: a `bun build --compile` single-file binary has no
 * `package.json` next to it, so the on-disk read fails and the version silently
 * degraded to `0.0.0` (measured). The build therefore bakes the version in via
 * `--define __NOEM_VERSION__='"<version>"'` (see `scripts/compile.ts`), and that
 * value wins when present.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

declare const __NOEM_VERSION__: string | undefined;

/** Build-time constant; `typeof` on an undeclared identifier is safe. */
function embeddedVersion(): string | null {
  try {
    return typeof __NOEM_VERSION__ === "string" ? __NOEM_VERSION__ : null;
  } catch {
    return null;
  }
}

export function agentVersion(): string {
  const embedded = embeddedVersion();
  if (embedded !== null) return embedded;
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    const raw = readFileSync(join(here, "..", "package.json"), "utf8");
    const parsed = JSON.parse(raw) as { version?: unknown };
    return typeof parsed.version === "string" ? parsed.version : "0.0.0";
  } catch {
    return "0.0.0";
  }
}
