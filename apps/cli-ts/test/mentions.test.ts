/**
 * @file mention parsing/completion tests.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { activeMention, applyMention, filterMentions } from "../src/mentions.js";

test("activeMention: detects a token only at a word boundary", () => {
  assert.deepEqual(activeMention("see @src/a", 10), { start: 4, end: 10, query: "src/a" });
  assert.deepEqual(activeMention("@", 1), { start: 0, end: 1, query: "" });
  assert.equal(activeMention("mail me@host", 12), null); // email-ish, no boundary
  assert.equal(activeMention("no mention here", 15), null);
  assert.deepEqual(activeMention("@a @b", 5), { start: 3, end: 5, query: "b" });
});

test("filterMentions: empty query lists shallow files, substring ranks", () => {
  const paths = ["src/a.ts", "src/deep/b.ts", "README.md", "src/ab.ts"];
  assert.deepEqual(filterMentions(paths, ""), ["src/a.ts", "README.md", "src/ab.ts", "src/deep/b.ts"]);
  assert.deepEqual(filterMentions(paths, "ab"), ["src/ab.ts"]);
  assert.deepEqual(filterMentions(paths, "src/"), ["src/a.ts", "src/ab.ts", "src/deep/b.ts"]);
  assert.deepEqual(filterMentions(paths, "zzz"), []);
  assert.equal(filterMentions(paths, "s", 2).length, 2);
});

test("applyMention: replaces the token and appends a trailing space", () => {
  const result = applyMention("see @src", 8, "src/a.ts");
  assert.equal(result.value, "see @src/a.ts ");
  assert.equal(result.cursor, "see @src/a.ts ".length);
  // no active token: unchanged
  assert.deepEqual(applyMention("plain", 5, "x"), { value: "plain", cursor: 5 });
});
