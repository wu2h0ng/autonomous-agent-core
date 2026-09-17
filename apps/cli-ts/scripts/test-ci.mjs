#!/usr/bin/env node
/**
 * CI entry point for the cli-ts suite: one bounded process per test file, inside a
 * bounded suite.
 *
 * `npm test` runs the whole file list inside one `node --test` invocation, which
 * on a runner that hangs produces no attribution at all - the job simply sits
 * until its 20-minute wall clock fires, and the log's last line is whichever test
 * happened to pass last. That is exactly what happened on the Linux runner. Here
 * every test file gets its own process and its own deadline, and the file's name
 * is printed before it runs, so a hang is reported as "this file timed out"
 * instead of as an anonymous cancelled job.
 *
 * Two things this file must NOT get wrong, both of them the same class of bug -
 * "the gate says it ran the suite and it did not":
 *
 * 1. WHICH FILES. The list is read from `scripts.test` (the list `npm test`
 *    itself runs) and is cross-checked against a RECURSIVE scan of `test/`. A
 *    single-level `readdirSync` silently skipped `test/<subdir>/x.test.ts`: the
 *    file was on disk, registered in scripts.test, run by `npm test`, asserted by
 *    test/test-list-guard.test.ts (which scans recursively) - and never executed
 *    by CI. The same criterion as that guard, and a hard failure when the two
 *    sides disagree in either direction.
 *
 * 2. HOW LONG. A per-file deadline is only a hang detector while the whole step fits in the
 *    job's own `timeout-minutes`: 34 files x 180 s is 102 minutes of permitted wall clock
 *    inside a 20-minute job, so seven hung files still ended as an anonymous cancellation
 *    (TEST_FILE_TIMEOUT_MS was checked by nothing at all). The bound that fixes it is the
 *    SUITE budget, not a smaller per-file deadline: every file gets
 *    `min(TEST_FILE_TIMEOUT_MS, time left in TEST_SUITE_BUDGET_MS)`, the run stops at the
 *    budget, and files it never reached are reported as failures. Deriving the per-file
 *    deadline as `budget / file count` instead (21 s for 34 files) was tried and withdrawn:
 *    under load a healthy `test/controller.test.ts` exceeded it and was reported as a hang,
 *    which is a worse failure than the one it fixes. Both knobs are bounded, and an override
 *    outside the enforced range is REJECTED (never clamped), because silently clamping is how
 *    a knob that is documented as a bound stops being one.
 *
 * `--list` prints the resolved plan as JSON (files, deadlines, budget) without
 * running anything; tests/product/test_ci_gate_wiring.py drives it to assert
 * these invariants against the workflow and against the files on disk.
 */
import { spawn } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const PACKAGE_ROOT = fileURLToPath(new URL("..", import.meta.url));
const TEST_DIR = join(PACKAGE_ROOT, "test");

// The enforced defaults: a per-file deadline (how long one hung file may block, and what it
// is killed and reported as) and a suite budget (the wall clock the whole loop shares).
const DEFAULTS = { perFileTimeoutMs: 180_000, suiteBudgetMs: 720_000 };
// Hard bounds. The suite budget must stay well inside the cli-ts job's
// `timeout-minutes: 20` (1200 s) so the install/typecheck/install-smoke steps still have
// room; the ceiling below leaves a 300 s reserve, asserted by the wiring test.
// The budget's floor is 1 ms ON PURPOSE: it is a probe value, not a CI setting -- the wiring
// test runs the entry point with `TEST_SUITE_BUDGET_MS=1` to prove the budget is enforced
// (nothing runs, every file is reported as never-run, the exit is non-zero). Clamping the
// floor up to a "sensible" minute would make that proof impossible.
const BOUNDS = {
  perFileTimeoutMs: { min: 5_000, max: 300_000 },
  suiteBudgetMs: { min: 1, max: 900_000 },
};
// `test/`-scoped *.test.ts(x) paths, the same entry grammar
// test/test-list-guard.test.ts matches `scripts.test` with.
const ENTRY = /(?:^|\s)(test\/[A-Za-z0-9._/-]+\.test\.tsx?)(?=\s|$)/g;

function readBoundedMs(name, fallback, bounds) {
  const raw = process.env[name];
  if (raw === undefined || raw.trim() === "") return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < bounds.min || value > bounds.max) {
    console.error(
      `${name}=${JSON.stringify(raw)} is outside the enforced range ` +
        `${bounds.min}..${bounds.max} ms. An unbounded deadline is how a hang turns ` +
        `into an anonymously cancelled job, so this value is rejected rather than ` +
        `clamped to the nearest bound.`,
    );
    process.exit(1);
  }
  return value;
}

/** Every *.test.ts(x) under dir, at any depth - the criterion the guard uses. */
function filesOnDisk(dir, prefix = "test") {
  const found = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const relative = `${prefix}/${entry.name}`;
    if (entry.isDirectory()) found.push(...filesOnDisk(join(dir, entry.name), relative));
    else if (/\.test\.tsx?$/.test(entry.name)) found.push(relative);
  }
  return found;
}

/** The test/*.test.ts(x) paths `scripts.test` names, in the order it names them. */
function filesRegistered(script) {
  return [...script.matchAll(ENTRY)].map((match) => match[1]);
}

const manifest = JSON.parse(readFileSync(join(PACKAGE_ROOT, "package.json"), "utf8"));
const registered = filesRegistered(manifest.scripts?.test ?? "");
const onDisk = filesOnDisk(TEST_DIR);

if (registered.length === 0) {
  console.error(
    "apps/cli-ts/package.json scripts.test names no test/*.test.ts(x) entry - the parse " +
      "itself is broken, and CI would otherwise run nothing and exit 0.",
  );
  process.exit(1);
}

const deduped = [...new Set(registered)];
const notRegistered = [...new Set(onDisk)].filter((file) => !deduped.includes(file)).sort();
const notOnDisk = deduped.filter((file) => !onDisk.includes(file)).sort();
if (notRegistered.length > 0 || notOnDisk.length > 0) {
  console.error(
    `apps/cli-ts/package.json scripts.test and the files under test/ disagree ` +
      `(registered=${deduped.length}, onDisk=${new Set(onDisk).size}). A file only one side ` +
      `knows about is run by one entry point and skipped by the other:`,
  );
  if (notRegistered.length > 0) {
    console.error(`  on disk but NOT in scripts.test (npm test would never run them):`);
    for (const file of notRegistered) console.error(`    ${file}`);
  }
  if (notOnDisk.length > 0) {
    console.error(`  in scripts.test but missing on disk:`);
    for (const file of notOnDisk) console.error(`    ${file}`);
  }
  process.exit(1);
}

const files = deduped;
const perFileMs = readBoundedMs(
  "TEST_FILE_TIMEOUT_MS",
  DEFAULTS.perFileTimeoutMs,
  BOUNDS.perFileTimeoutMs,
);
const suiteBudgetMs = readBoundedMs(
  "TEST_SUITE_BUDGET_MS",
  DEFAULTS.suiteBudgetMs,
  BOUNDS.suiteBudgetMs,
);

// The per-file deadline is NOT the suite budget divided by the file count. That derivation
// was tried and withdrawn on measurement (2026-09-18, this tree): 34 files over a 720 s budget
// gives every file 21.2 s, and under load -- the Linux runner's cli-ts job runs in parallel
// with the 2700-case Python job, and this machine showed the same effect at load average 8 --
// a healthy `test/controller.test.ts` took longer than that and was reported as a hang. A
// deadline that fires on a healthy file is worse than no deadline: it turns contention into a
// red gate. So the per-file deadline stays a hang detector with real headroom (180 s for a
// file that takes ~7 s), and the JOB-LEVEL bound comes from the suite budget below: the loop
// gives each file `min(perFileMs, remaining budget)`, so the sum cannot exceed the budget no
// matter how many files hang, and the files it never reached are reported as failures rather
// than quietly skipped.
const worstCaseSuiteMs = Math.min(files.length * perFileMs, suiteBudgetMs);

const plan = {
  packageRoot: PACKAGE_ROOT,
  files,
  fileCount: files.length,
  perFileTimeoutMs: perFileMs,
  suiteBudgetMs,
  worstCaseSuiteMs,
};

if (process.argv.includes("--list")) {
  console.log(JSON.stringify(plan, null, 2));
  process.exit(0);
}

console.log(
  `=== ${files.length} test files, ${perFileMs} ms deadline each, ${suiteBudgetMs} ms for the ` +
    `suite (worst case ${worstCaseSuiteMs} ms)`,
);
if (files.length * perFileMs > suiteBudgetMs) {
  console.log(
    `=== note: ${files.length} files x ${perFileMs} ms would be ${files.length * perFileMs} ms, ` +
      `so the suite budget is what bounds this step: a run that spends ${suiteBudgetMs} ms is ` +
      `stopped there and its remaining files are reported as never-run failures.`,
  );
}

function run(file, timeoutMs) {
  return new Promise((resolve) => {
    const child = spawn(
      process.execPath,
      ["--import", "tsx", "--test", file],
      { cwd: PACKAGE_ROOT, stdio: "inherit" },
    );
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      resolve({ file, code: 124, timedOut: true, timeoutMs });
    }, timeoutMs);
    child.on("exit", (code, signal) => {
      clearTimeout(timer);
      resolve({
        file,
        code: code ?? 1,
        timedOut: false,
        signal: signal ?? null,
      });
    });
  });
}

const startedAt = Date.now();
const deadline = startedAt + suiteBudgetMs;
const failures = [];
for (const file of files) {
  console.log(`\n=== ${file}`);
  const remaining = deadline - Date.now();
  if (remaining <= 0) {
    console.error(
      `=== ${file}: NOT RUN - the ${suiteBudgetMs} ms suite budget was already spent. This ` +
        `file is reported as a failure rather than skipped: a suite that runs out of budget ` +
        `part way through must not report success.`,
    );
    failures.push(`${file} (budget exhausted, never ran)`);
    continue;
  }
  const result = await run(file, Math.min(perFileMs, remaining));
  if (result.timedOut) {
    console.error(`=== ${file}: TIMED OUT after ${result.timeoutMs} ms`);
    failures.push(`${file} (timeout after ${result.timeoutMs} ms)`);
  } else if (result.code !== 0) {
    failures.push(`${file} (exit ${result.code}${result.signal ? ` signalled ${result.signal}` : ""})`);
  }
}

console.log(
  `\n=== ran ${files.length} test files in ${Math.round((Date.now() - startedAt) / 1000)} s ` +
    `(budget ${suiteBudgetMs} ms, per file ${perFileMs} ms)`,
);
if (failures.length > 0) {
  console.error(`=== ${failures.length} failing file(s):`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log("=== all test files passed");
