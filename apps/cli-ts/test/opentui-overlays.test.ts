/**
 * Parity slice A viewport tests (overlays.ts is pure — no renderer needed).
 * Bypass-detecting: an implementation that ignores `size`, never clamps the
 * cursor, or drops the head/tail counts would fail these.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { sliceWindow } from "../src/opentui/overlays.js";

test("sliceWindow keeps the cursor visible and reports hidden items", () => {
  const items = ["a", "b", "c", "d", "e", "f", "g", "h"];
  const first = sliceWindow(items, 0, 3);
  assert.deepEqual(first.items, ["a", "b", "c"]);
  assert.equal(first.index, 0);
  assert.equal(first.before, 0);
  assert.equal(first.after, 5);

  const middle = sliceWindow(items, 4, 3);
  assert.deepEqual(middle.items, ["d", "e", "f"]);
  assert.equal(middle.index, 1);
  assert.equal(middle.before, 3);
  assert.equal(middle.after, 2);

  const last = sliceWindow(items, 7, 3);
  assert.deepEqual(last.items, ["f", "g", "h"]);
  assert.equal(last.index, 2);
  assert.equal(last.after, 0);
});

test("sliceWindow clamps out-of-range cursors and handles empty/size 0", () => {
  const items = ["a", "b"];
  assert.equal(sliceWindow(items, 99, 5).index, 1);
  assert.equal(sliceWindow(items, -3, 5).index, 0);
  assert.deepEqual(sliceWindow([], 0, 5), { items: [], index: -1, before: 0, after: 0 });
  assert.deepEqual(sliceWindow(items, 0, 0), { items: [], index: -1, before: 0, after: 2 });
  // Size larger than the list shows everything.
  assert.deepEqual(sliceWindow(items, 1, 10).items, ["a", "b"]);
});
