/**
 * Build the single-file binary: `bun build --compile`.
 *
 * A compiled binary has no `package.json` next to it, so `agentVersion()` used to
 * fall back to `0.0.0` (measured on a real build). The version is therefore baked
 * in with `--define`, which is also what keeps `--version` honest for a user who
 * installed nothing but the binary.
 *
 *     bun run scripts/compile.ts [outfile]
 */
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const pkg = JSON.parse(
  readFileSync(fileURLToPath(new URL("../package.json", import.meta.url)), "utf8"),
) as { version: string };

const outfile = process.argv[2] ?? "dist/noem";
console.log(`compiling noem ${pkg.version} -> ${outfile}`);

const done = spawnSync(
  "bun",
  [
    "build",
    "--compile",
    "src/cli.tsx",
    "--outfile",
    outfile,
    // Baked in so `--version` works without package.json (see src/version.ts).
    "--define",
    `__NOEM_VERSION__=${JSON.stringify(pkg.version)}`,
  ],
  { stdio: "inherit" },
);

process.exit(done.status ?? 1);
