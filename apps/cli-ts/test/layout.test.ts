/**
 * Narrow-terminal layout threshold tests.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { COMPOSER_MIN_ROWS, composerRows, layoutFor } from "../src/layout.js";

test("layoutFor: three tiers with documented boundaries", () => {
  assert.deepEqual(layoutFor(40), {
    narrow: true,
    showDescriptions: false,
    footerFields: false,
  });
  assert.deepEqual(layoutFor(59), {
    narrow: true,
    showDescriptions: false,
    footerFields: false,
  });
  assert.deepEqual(layoutFor(60), {
    narrow: false,
    showDescriptions: true,
    footerFields: false,
  });
  assert.deepEqual(layoutFor(99), {
    narrow: false,
    showDescriptions: true,
    footerFields: false,
  });
  assert.deepEqual(layoutFor(100), {
    narrow: false,
    showDescriptions: true,
    footerFields: true,
  });
  assert.deepEqual(layoutFor(200), {
    narrow: false,
    showDescriptions: true,
    footerFields: true,
  });
});

test("composerRows grows with the draft and is bounded on both ends", () => {
  // An empty draft keeps the original five-row box (three visible lines).
  assert.equal(composerRows("", 44), COMPOSER_MIN_ROWS);
  assert.equal(composerRows("one line", 44), COMPOSER_MIN_ROWS);
  // One row per draft line plus the two border rows.
  assert.equal(composerRows("a\nb\nc", 44), COMPOSER_MIN_ROWS);
  assert.equal(composerRows("a\nb\nc\nd\ne\nf", 44), 8);
  // Never larger than a third of the screen, and never larger than the cap.
  assert.equal(composerRows("x\n".repeat(40) + "x", 44), 12);
  assert.equal(composerRows("x\n".repeat(40) + "x", 12), COMPOSER_MIN_ROWS);
  // A short terminal still gets a usable composer.
  assert.equal(composerRows("a\nb\nc\nd\ne\nf\ng", 9), COMPOSER_MIN_ROWS);
});
