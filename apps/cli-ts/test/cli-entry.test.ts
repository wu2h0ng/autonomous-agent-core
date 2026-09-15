/** --version/--help print without starting the daemon (no descriptor needed). */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
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
