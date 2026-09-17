/** @jsxImportSource @opentui/react */
/**
 * Bun-only render harness: does a real `y`/`n` keystroke actually hand the
 * decision to the controller?
 *
 * Why this is a fixture and not a test file: rendering `<App>` needs OpenTUI's
 * native renderer, and only bun has the FFI for it (under node, `@opentui/core`
 * resolves to the stub whose `CliRenderer` throws "OpenTUI native FFI is not
 * available for this runtime"). `npm test` runs under plain node, so
 * `test/opentui-approval-action.test.tsx` spawns THIS file with bun, prints its
 * output on failure and fails if it exits non-zero.
 *
 * The gap it closes: `App`'s approval branch (`if (owner.action === "approve")
 * void controller.approve()`) is the only place a routed approval action becomes
 * a decision. Turning that branch into a no-op left the whole suite green —
 * `opentui-viewkeys.test.ts` only asserts the ROUTING decision, and the Ink-era
 * assertion that a real `y` produced exactly one approval was deleted with Ink.
 * The controller is a real `TuiController`; `approve`/`reject`/`submit` are
 * spied on its public API, so the assertion is "this keystroke reached the
 * approver", not "some function ran".
 *
 * Exits explicitly in every path: a failed assertion thrown out of the top level
 * would leave the renderer's stdin/timers alive, so the process would hang
 * instead of reporting the failure.
 *
 * Run directly:  bun run test/fixtures/opentui-approval-key.harness.tsx
 */
import assert from "node:assert/strict";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../../src/opentui/app.js";
import { TuiController } from "../../src/controller.js";
import type { SurfaceClient } from "../../src/client.js";
import type { SurfaceSessionSnapshot } from "../../src/contracts.js";

/** Only `fetchAgentTree` would touch the client, and both panels are off. */
const client = {} as unknown as SurfaceClient;

/** How long a view frame or a keystroke effect may take before we give up. */
const SETTLE_BUDGET_MS = 5_000;

const PENDING: SurfaceSessionSnapshot = {
  protocol_version: "1.1",
  session: {
    session_id: "s:1",
    task_id: "task:1",
    run_id: "run:1",
    tenant_id: "tenant:local",
    workspace_id: "workspace:local",
  },
  envelope_id: "env:1",
  expected_outcome_id: "outcome:1",
  status: "WAITING_APPROVAL",
  event_sequence: 7,
  message_count: 1,
  pending_approval: {
    action_digest: "digest-abc",
    capability_id: "workspace.edit",
    proposal_id: "p:1",
    preview: "edit fixture.txt",
    requested_at: "2026-09-17T00:00:00Z",
  },
  permission_mode: "ASK",
  updated_at: "2026-09-17T00:00:00Z",
};

async function main(): Promise<void> {
  const controller = new TuiController(client);
  const approved: string[] = [];
  const rejected: string[] = [];
  const submitted: string[] = [];
  controller.approve = async (): Promise<void> => {
    approved.push("approve");
  };
  controller.reject = async (): Promise<void> => {
    rejected.push("reject");
  };
  controller.submit = async (value: string): Promise<boolean> => {
    submitted.push(value);
    return true;
  };
  // The routing decision reads the public `status`; the approval BOX reads the
  // snapshot. Both are set so the key is pressed while the approval prompt is
  // genuinely on screen (the same direct state poke the retired Ink test used).
  controller.status = "awaiting_approval";
  (controller as unknown as { snapshot: SurfaceSessionSnapshot }).snapshot = PENDING;

  const setup = await testRender(
    <App
      controller={controller}
      workspace="."
      branch={null}
      version="0.1.0"
      model={null}
      client={client}
      withPanels={false}
      withAgents={false}
    />,
    { width: 100, height: 24 },
  );

  /** One render pass plus a quiet-frames check; the view's own effects need
   * frames, so a keystroke is never asserted against a single capture. */
  const drain = async (): Promise<void> => {
    await setup.flush({ maxPasses: 40 });
    await setup.waitForVisualIdle({ quietFrames: 2, maxFrames: 120 }).catch(() => undefined);
    await setup.flush({ maxPasses: 40 });
  };
  /**
   * Wait on the wall clock, not a pass count: under `npm test` (30 test files
   * rendering at once) the view's first frames can land after a fixed number of
   * passes, which made a fixed settle flaky.
   */
  const until = async (done: () => boolean): Promise<void> => {
    const deadline = Date.now() + SETTLE_BUDGET_MS;
    while (!done() && Date.now() < deadline) {
      await drain();
      if (!done()) await new Promise((resolve) => setTimeout(resolve, 10));
    }
  };

  try {
    await until(() => setup.captureCharFrame().includes("[y] approve · [n] reject"));
    const frame = setup.captureCharFrame();
    assert.match(
      frame,
      /human approval required — workspace\.edit/,
      `the approval prompt must be on screen before the keys are pressed; frame was:\n${frame}`,
    );
    assert.match(frame, /\[y\] approve · \[n\] reject/, "the y/n hint must be on screen");

    setup.mockInput.pressKey("y");
    await until(() => approved.length > 0);
    assert.deepEqual(approved, ["approve"], "`y` must call controller.approve() exactly once");
    assert.deepEqual(rejected, [], "`y` must not reject");
    assert.deepEqual(submitted, [], "the `y` keystroke must never become a submitted prompt");

    setup.mockInput.pressKey("n");
    await until(() => rejected.length > 0);
    assert.deepEqual(rejected, ["reject"], "`n` must call controller.reject() exactly once");
    assert.deepEqual(approved, ["approve"], "`n` must not approve");

    // Control: an unrelated key in the same layer changes nothing. Without this,
    // "approve on any key" would satisfy every assertion above.
    setup.mockInput.pressKey("x");
    await drain();
    assert.deepEqual(approved, ["approve"], "an unrelated key must not approve");
    assert.deepEqual(rejected, ["reject"], "an unrelated key must not reject");
    assert.deepEqual(submitted, [], "an unrelated key must not submit");
  } finally {
    setup.renderer.destroy();
  }
  console.log("OPENTUI_APPROVAL_KEY_HARNESS: PASS (y -> approve, n -> reject, other keys inert)");
}

try {
  await main();
  process.exit(0);
} catch (error) {
  console.error("OPENTUI_APPROVAL_KEY_HARNESS: FAIL");
  console.error(error instanceof Error ? (error.stack ?? error.message) : String(error));
  process.exit(1);
}
