/**
 * Input history tests (mainstream composer ergonomics: ↑/↓ recall, Ctrl-R
 * reverse search). Pure class — no Ink, no terminal.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { InputHistory } from "../src/history.js";

test("add: ignores blank input and collapses consecutive duplicates", () => {
  const history = new InputHistory();
  history.add("  ");
  history.add("first");
  history.add("first");
  history.add("second");
  assert.equal(history.size, 2);
});

test("prev/next: recall in order and restore the live draft at the end", () => {
  const history = new InputHistory();
  history.add("one");
  history.add("two");
  assert.equal(history.prev("draft"), "two");
  assert.equal(history.prev("draft"), "one");
  assert.equal(history.prev("draft"), "one"); // oldest: stay put
  assert.equal(history.next(), "two");
  assert.equal(history.next(), "draft"); // past newest → live draft
  assert.equal(history.next(), "draft");
});

test("prev on empty history returns the current draft unchanged", () => {
  const history = new InputHistory();
  assert.equal(history.prev("typed"), "typed");
  assert.equal(history.next(), "");
});

test("add after navigation resets the cursor to the newest entry", () => {
  const history = new InputHistory();
  history.add("one");
  history.add("two");
  assert.equal(history.prev("draft"), "two");
  history.add("three");
  assert.equal(history.prev("x"), "three");
});

test("search: reverse chronological, case-insensitive, filtered and deduped", () => {
  const history = new InputHistory();
  history.add("run tests");
  history.add("git status");
  history.add("run build");
  history.add("run tests"); // duplicate non-consecutive stays in history…
  const hits = history.search("RUN");
  assert.deepEqual(hits, ["run tests", "run build", "git status"].filter((e) => e.includes("run")));
  // …but search returns each distinct entry once, newest first
  assert.deepEqual(new Set(hits).size, hits.length);
  assert.deepEqual(history.search(""), ["run tests", "run build", "git status"]);
});

test("reset clears everything", () => {
  const history = new InputHistory();
  history.add("one");
  history.reset();
  assert.equal(history.size, 0);
  assert.equal(history.prev("x"), "x");
});
