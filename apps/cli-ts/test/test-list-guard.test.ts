/**
 * Is every test file on disk actually registered in `scripts.test`?
 *
 * The gap this closes (verified by the independent review): `npm test` runs
 * `node --import tsx --test <explicit list>`, so a test file that nobody adds to
 * that list never runs — and nothing went red when the two files this PR added
 * to the list were dropped from it. Whole files of coverage could be deleted or
 * silently unregistered with the suite still green.
 *
 * Both directions are checked: a file on disk but missing from the script, and
 * a path the script names but that no longer exists.
 */
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const PACKAGE_ROOT = fileURLToPath(new URL("..", import.meta.url));
const TEST_DIR = join(PACKAGE_ROOT, "test");
const ENTRY = /(?:^|\s)(test\/[A-Za-z0-9._/-]+\.test\.tsx?)(?=\s|$)/g;

function filesOnDisk(dir: string, prefix = "test"): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const relative = `${prefix}/${entry.name}`;
    if (entry.isDirectory()) found.push(...filesOnDisk(join(dir, entry.name), relative));
    else if (/\.test\.tsx?$/.test(entry.name)) found.push(relative);
  }
  return found;
}

function filesInScript(script: string): string[] {
  return [...script.matchAll(ENTRY)].map((match) => match[1] as string);
}

test("scripts.test lists exactly the test files that exist on disk", () => {
  const manifest = JSON.parse(readFileSync(join(PACKAGE_ROOT, "package.json"), "utf8")) as {
    scripts?: Record<string, string>;
  };
  const script = manifest.scripts?.["test"];
  if (typeof script !== "string" || script.trim() === "") {
    throw new Error("apps/cli-ts/package.json has no non-empty scripts.test — nothing would run");
  }

  const registered = [...new Set(filesInScript(script))].sort();
  const onDisk = [...new Set(filesOnDisk(TEST_DIR))].sort();

  assert.ok(onDisk.length > 0, `no *.test.ts(x) found under ${TEST_DIR} — the disk scan itself is broken`);
  assert.ok(registered.length > 0, "scripts.test names no test/*.test.ts(x) entry — the parse itself is broken");

  const notRegistered = onDisk.filter((file) => !registered.includes(file));
  const notOnDisk = registered.filter((file) => !onDisk.includes(file));
  const diff = [
    notRegistered.length > 0
      ? `  on disk but NOT in scripts.test (would never run):\n${notRegistered.map((f) => `    ${f}`).join("\n")}`
      : "",
    notOnDisk.length > 0
      ? `  in scripts.test but missing on disk:\n${notOnDisk.map((f) => `    ${f}`).join("\n")}`
      : "",
  ]
    .filter((line) => line !== "")
    .join("\n");

  assert.ok(
    notRegistered.length === 0 && notOnDisk.length === 0,
    `apps/cli-ts/package.json scripts.test and the files under test/ disagree` +
      ` (registered=${registered.length}, onDisk=${onDisk.length}):\n${diff}\n` +
      `A file absent from scripts.test is never executed, so add it to the list (or delete the file).`,
  );
});
