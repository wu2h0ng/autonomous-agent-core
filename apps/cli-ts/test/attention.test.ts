/**
 * Attention-signal tests.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { attentionFor, attentionSequence } from "../src/attention.js";

test("attentionFor: approval, completion, failure, and no-op transitions", () => {
  assert.equal(attentionFor("streaming", "awaiting_approval", null), "approval");
  assert.equal(attentionFor("streaming", "idle", "completed"), "turn_done");
  assert.equal(attentionFor("stalled", "idle", null), "turn_done");
  assert.equal(attentionFor("streaming", "idle", "max_steps"), "error");
  // exception-failed turn: lastStopReason is null but lastError is set
  assert.equal(attentionFor("streaming", "idle", null, "boom"), "error");
  assert.equal(attentionFor("stalled", "idle", null, "socket reset"), "error");
  assert.equal(attentionFor("idle", "idle", "completed"), null);
  assert.equal(attentionFor("idle", "streaming", null), null);
});

test("attentionSequence: bell by default, opt-in OSC notification, disableable", () => {
  assert.equal(attentionSequence(null), "");
  assert.equal(attentionSequence("turn_done"), "\u0007");
  assert.equal(attentionSequence("turn_done", { bell: false }), "");
  assert.equal(attentionSequence("approval", { notify: true }), "\u0007\u001b]9;Agent OS: approval required\u0007");
  assert.equal(attentionSequence("error", { bell: false, notify: false }), "");
});
