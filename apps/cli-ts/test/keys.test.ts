/**
 * Keybinding dispatch tests (keys.ts is a pure function — no Ink needed).
 * Invariants: Esc never triggers a durable REJECT; Ctrl-L mirrors /clear.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { TuiController } from "../src/controller.js";
import { handleGlobalKey } from "../src/keys.js";

function controllerWith(status: string): {
  controller: TuiController;
  state: { interrupts: number };
} {
  const controller = new TuiController({} as never);
  (controller as never as { status: string }).status = status;
  const state = { interrupts: 0 };
  controller.interrupt = async () => {
    state.interrupts += 1;
    return status === "idle" ? "closed" : "corrected";
  };
  return { controller, state };
}

test("esc during streaming issues a correction; esc never rejects an approval", () => {
  const streaming = controllerWith("streaming");
  assert.equal(handleGlobalKey(streaming.controller, "", { escape: true }), true);
  assert.equal(streaming.state.interrupts, 1);

  const approval = controllerWith("awaiting_approval");
  assert.equal(handleGlobalKey(approval.controller, "", { escape: true }), true);
  assert.equal(approval.state.interrupts, 0); // consumed, but no interrupt, no reject
  assert.equal(approval.controller.status, "awaiting_approval");

  const idle = controllerWith("idle");
  assert.equal(handleGlobalKey(idle.controller, "", { escape: true }), true);
  assert.equal(idle.state.interrupts, 0);
});

test("ctrl-c closes when idle, corrects when streaming", () => {
  const idle = controllerWith("idle");
  assert.equal(handleGlobalKey(idle.controller, "c", { ctrl: true }), true);

  const streaming = controllerWith("streaming");
  assert.equal(handleGlobalKey(streaming.controller, "c", { ctrl: true }), true);
  assert.equal(streaming.state.interrupts, 1);
});

test("ctrl-l clears the view; unrelated keys fall through", () => {
  const { controller } = controllerWith("idle");
  const internals = controller as never as {
    push: (m: { role: "system"; content: string }) => void;
  };
  internals.push({ role: "system", content: "old" });
  assert.equal(handleGlobalKey(controller, "l", { ctrl: true }), true);
  assert.equal(controller.messages.length, 1); // only the cleared notice
  assert.match(controller.messages[0]?.content ?? "", /view cleared/);

  assert.equal(handleGlobalKey(controller, "x", {}), false);
});

test("ctrl-x requests an operator stop and is consumed; plain x falls through", () => {
  const { controller } = controllerWith("streaming");
  const calls: string[] = [];
  controller.stopTurn = async (source = "ctrl-x") => {
    calls.push(source);
    return "stopped";
  };
  assert.equal(handleGlobalKey(controller, "x", { ctrl: true }), true);
  assert.deepEqual(calls, ["ctrl-x"], "ctrl-x must reach the stop path, not the composer");

  // A plain `x` is composer text (and vim's delete-forward in normal mode):
  // the stop key must never be reachable from a bare letter.
  assert.equal(handleGlobalKey(controller, "x", {}), false);
  assert.equal(calls.length, 1);
});

test("/clear: resets view and refuses mid-turn", async () => {
  const controller = new TuiController({} as never);
  const internals = controller as never as {
    push: (m: { role: "system"; content: string }) => void;
    busy: boolean;
  };
  internals.push({ role: "system", content: "one" });
  internals.push({ role: "system", content: "two" });
  await controller.submit("/clear");
  assert.equal(controller.messages.length, 1);
  assert.equal(controller.finalizedIndex, 0); // notice is still mutable until the next push
  assert.match(controller.messages[0]?.content ?? "", /local view only/);

  internals.busy = true;
  await controller.submit("/clear");
  assert.match(controller.messages.at(-1)?.content ?? "", /refused/);
});
