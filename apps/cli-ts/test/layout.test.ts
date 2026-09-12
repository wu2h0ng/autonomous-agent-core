/**
 * Narrow-terminal layout threshold tests.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { layoutFor } from "../src/layout.js";

test("layoutFor: three tiers with documented boundaries", () => {
  assert.deepEqual(layoutFor(40), {
    narrow: true,
    showDescriptions: false,
    showHints: false,
    footerFields: false,
  });
  assert.deepEqual(layoutFor(59), {
    narrow: true,
    showDescriptions: false,
    showHints: false,
    footerFields: false,
  });
  assert.deepEqual(layoutFor(60), {
    narrow: false,
    showDescriptions: true,
    showHints: false,
    footerFields: false,
  });
  assert.deepEqual(layoutFor(99), {
    narrow: false,
    showDescriptions: true,
    showHints: false,
    footerFields: false,
  });
  assert.deepEqual(layoutFor(100), {
    narrow: false,
    showDescriptions: true,
    showHints: true,
    footerFields: true,
  });
  assert.deepEqual(layoutFor(200), {
    narrow: false,
    showDescriptions: true,
    showHints: true,
    footerFields: true,
  });
});
