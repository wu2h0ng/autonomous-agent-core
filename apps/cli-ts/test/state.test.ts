/**
 * Local state persistence tests (temp dir; no real HOME touched).
 */
import assert from "node:assert/strict";
import { mkdtempSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { DEFAULT_STATE, loadState, saveState, stateFilePath } from "../src/state.js";

function tempPath(): string {
  return join(mkdtempSync(join(tmpdir(), "cli-ts-state-")), "cli-ts-state.json");
}

test("save/load round-trips and writes 0600", () => {
  const path = tempPath();
  assert.equal(saveState(path, { history: ["a", "b"], theme: "ansi", goal: "ship it", vim: true }), true);
  assert.deepEqual(loadState(path), { history: ["a", "b"], theme: "ansi", goal: "ship it", vim: true });
  assert.equal(statSync(path).mode & 0o777, 0o600);
});

test("missing or corrupt state falls back to defaults (never throws)", () => {
  assert.deepEqual(loadState(tempPath()), DEFAULT_STATE);
  const path = tempPath();
  writeFileSync(path, "{not json", "utf8");
  assert.deepEqual(loadState(path), DEFAULT_STATE);
  writeFileSync(path, JSON.stringify({ history: [1, "ok", null], theme: "", goal: 7 }), "utf8");
  assert.deepEqual(loadState(path), { history: ["ok"], theme: "default", goal: null, vim: false });
});

test("history is capped to the most recent 200 entries", () => {
  const path = tempPath();
  const history = Array.from({ length: 250 }, (_, index) => `m${index}`);
  saveState(path, { history, theme: "default", goal: null, vim: false });
  const loaded = loadState(path);
  assert.equal(loaded.history.length, 200);
  assert.equal(loaded.history[0], "m50");
  assert.equal(loaded.history.at(-1), "m249");

  // load-path cap is independent of save-path cap: write an oversized file
  // directly and assert loadState still caps.
  writeFileSync(
    path,
    JSON.stringify({ history: Array.from({ length: 260 }, (_, i) => `d${i}`), theme: "ansi", goal: null, vim: false }),
    "utf8",
  );
  const direct = loadState(path);
  assert.equal(direct.history.length, 200);
  assert.equal(direct.history[0], "d60");
  assert.equal(direct.history.at(-1), "d259");
});

test("stateFilePath honors AGENT_OS_CLI_STATE and HOME overrides", () => {
  assert.equal(stateFilePath({ AGENT_OS_CLI_STATE: "/tmp/x.json" } as NodeJS.ProcessEnv), "/tmp/x.json");
  assert.equal(stateFilePath({ HOME: "/home/u" } as NodeJS.ProcessEnv), "/home/u/.agent-os/cli-ts-state.json");
});

test("saveState never throws on an unwritable path", () => {
  assert.equal(saveState("/proc/definitely/not/writable.json", DEFAULT_STATE), false);
});
