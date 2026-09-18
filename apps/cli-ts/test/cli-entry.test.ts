/** --version/--help print without starting the daemon (no descriptor needed). */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

function run(args: string[]): { code: number | null; out: string; home: string } {
  const home = mkdtempSync(join(tmpdir(), "agent-os-cli-home-"));
  const result = spawnSync(
    process.execPath,
    ["--import", "tsx", "src/cli.tsx", ...args],
    { encoding: "utf8", env: { ...process.env, HOME: home } },
  );
  return { code: result.status, out: `${result.stdout}${result.stderr}`, home };
}

test("--version prints and exits without a daemon", () => {
  const { code, out, home } = run(["--version"]);
  try {
    assert.equal(code, 0);
    assert.match(out.trim(), /^\d+\.\d+\.\d+$/);
    assert.ok(!existsSync(join(home, ".agent-os", "runtime.json")));
    // Bypass-detecting: this suite runs under plain node, which has no native
    // FFI, so these view-free paths only keep working while the full-screen view
    // stays a LAZY import in cli.tsx. Make it a static import and this fails.
    assert.ok(
      !out.includes("native FFI"),
      "cli.tsx must not load the view for view-free paths",
    );
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test("--help prints usage without a daemon", () => {
  const { code, out, home } = run(["--help"]);
  try {
    assert.equal(code, 0);
    assert.match(out, /usage:/);
    assert.ok(!existsSync(join(home, ".agent-os", "runtime.json")));
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test("package registers the noem bin with legacy aliases", () => {
  const pkg = JSON.parse(
    readFileSync(new URL("../package.json", import.meta.url), "utf8"),
  ) as { bin?: Record<string, string> };
  const bins = Object.keys(pkg.bin ?? {});
  assert.ok(bins.includes("noem"), "noem must be a registered bin");
  assert.deepEqual(
    bins.filter((name) => name !== "noem").sort(),
    ["agent-os", "agent-os-ts", "agentos"],
  );
});
