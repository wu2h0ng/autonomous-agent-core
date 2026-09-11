/**
 * segmentPreview tests: the kernel's frozen workspace.edit preview shape
 * splits into old/new segments; every deviation fails soft to plain.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { segmentPreview } from "../src/diff.js";

test("workspace.edit preview splits into header/old/new segments", () => {
  // exact frozen shape from agent_loop.py::_action_preview
  const preview = "edit fixture.txt\n--- old ---\nalpha\nbeta\n--- new ---\ngamma";
  const segments = segmentPreview(preview);
  assert.deepEqual(segments, [
    { text: "edit fixture.txt", tone: "plain" },
    { text: "alpha\nbeta", tone: "old" },
    { text: "gamma", tone: "new" },
  ]);
});

test("non-diff previews stay plain (shell command, replace, empty)", () => {
  assert.deepEqual(segmentPreview("run command: npm test"), [
    { text: "run command: npm test", tone: "plain" },
  ]);
  assert.deepEqual(segmentPreview(""), [{ text: "", tone: "plain" }]);
  // lone old marker without new marker is not a diff
  assert.deepEqual(segmentPreview("--- old ---\norphan"), [
    { text: "--- old ---\norphan", tone: "plain" },
  ]);
  // reversed order is not a diff
  assert.deepEqual(segmentPreview("--- new ---\nx\n--- old ---\ny"), [
    { text: "--- new ---\nx\n--- old ---\ny", tone: "plain" },
  ]);
});

test("content containing marker-like text mid-line is not misparsed", () => {
  const preview = "edit f\n--- old ---\ntalks about --- new --- inline\n--- new ---\nreal";
  const segments = segmentPreview(preview);
  const oldSeg = segments.find((s) => s.tone === "old");
  assert.ok(oldSeg?.text.includes("talks about --- new --- inline"));
});
