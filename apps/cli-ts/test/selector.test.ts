/**
 * Selector model tests.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { moveSelector, numberedChoice, selectorChoice } from "../src/selector.js";

const state = { items: ["a", "b", "c"] as const, index: 0 };

test("moveSelector wraps around both directions", () => {
  assert.equal(moveSelector(state, 1).index, 1);
  assert.equal(moveSelector(state, -1).index, 2);
  assert.equal(moveSelector({ items: ["a"], index: 0 }, 1).index, 0);
  assert.equal(moveSelector({ items: [], index: 5 }, 1).index, 0);
});

test("selectorChoice returns the highlighted item", () => {
  assert.equal(selectorChoice(state), "a");
  assert.equal(selectorChoice({ items: ["a", "b"], index: 1 }), "b");
  assert.equal(selectorChoice({ items: [], index: 0 }), undefined);
});

test("numberedChoice is 1-based and out-of-range safe", () => {
  assert.equal(numberedChoice(state, 1), "a");
  assert.equal(numberedChoice(state, 3), "c");
  assert.equal(numberedChoice(state, 4), undefined);
  assert.equal(numberedChoice(state, 0), undefined);
});
