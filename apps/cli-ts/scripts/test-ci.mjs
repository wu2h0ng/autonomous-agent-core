#!/usr/bin/env node
/**
 * CI entry point for the cli-ts suite: one bounded process per test file.
 *
 * `npm test` runs the whole file list inside one `node --test` invocation, which
 * on a runner that hangs produces no attribution at all - the job simply sits
 * until its 20-minute wall clock fires, and the log's last line is whichever test
 * happened to pass last. That is exactly what happened on the Linux runner.
 *
 * Here every test file gets its own process and its own deadline, and the file's
 * name is printed before it runs, so a hang is reported as "this file timed out"
 * instead of as an anonymous cancelled job. Any failure or timeout is summarised
 * at the end and the exit code is non-zero.
 */
import { spawn } from "node:child_process";
import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const PACKAGE_ROOT = fileURLToPath(new URL("..", import.meta.url));
const PER_FILE_TIMEOUT_MS = Number(process.env.TEST_FILE_TIMEOUT_MS ?? 180_000);

const files = readdirSync(new URL("../test", import.meta.url))
  .filter((name) => /\.test\.tsx?$/.test(name))
  .sort()
  .map((name) => `test/${name}`);

if (files.length === 0) {
  console.error("no test files found under test/");
  process.exit(1);
}

function run(file) {
  return new Promise((resolve) => {
    const child = spawn(
      process.execPath,
      ["--import", "tsx", "--test", file],
      { cwd: PACKAGE_ROOT, stdio: "inherit" },
    );
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      resolve({ file, code: 124, timedOut: true });
    }, PER_FILE_TIMEOUT_MS);
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

const failures = [];
for (const file of files) {
  console.log(`\n=== ${file}`);
  const result = await run(file);
  if (result.timedOut) {
    console.error(`=== ${file}: TIMED OUT after ${PER_FILE_TIMEOUT_MS} ms`);
    failures.push(`${file} (timeout)`);
  } else if (result.code !== 0) {
    failures.push(`${file} (exit ${result.code}${result.signal ? ` signalled ${result.signal}` : ""})`);
  }
}

console.log(`\n=== ran ${files.length} test files`);
if (failures.length > 0) {
  console.error(`=== ${failures.length} failing file(s):`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log("=== all test files passed");
