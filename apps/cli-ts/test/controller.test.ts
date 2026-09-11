/**
 * Unit tests for the Ink-free TuiController, driven by a scripted fake
 * client. A controller that never hits the frozen semantics (durable
 * completion authority, human-only approval, stall typing) fails here.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { TuiController, STALL_DEFAULT_MS } from "../src/controller.js";
import type {
  PermissionMode,
  SurfaceSessionSnapshot,
  SurfaceStreamFrame,
} from "../src/contracts.js";

function snapshot(overrides: Partial<SurfaceSessionSnapshot> = {}): SurfaceSessionSnapshot {
  return {
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
    status: "ACTIVE",
    event_sequence: 1,
    message_count: 0,
    pending_approval: null,
    permission_mode: "ASK",
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function frame(seq: number, turn: string, kind: string, delta = ""): SurfaceStreamFrame {
  return {
    kind: kind as SurfaceStreamFrame["kind"],
    runtime_boot_id: "boot:1",
    stream_id: "stream:1",
    turn_id: turn,
    frame_sequence: seq,
    payload: delta ? { delta } : {},
  };
}

class FakeClient {
  eventsCalls = 0;
  approvals: string[] = [];
  modes: PermissionMode[] = [];
  completedTokens = 0;
  completedStopReason: string | null = null;
  completedSteps = 0;
  approvalPending = false;
  streamScript: SurfaceStreamFrame[] = [];

  async openSession() {
    return snapshot();
  }
  async getSession() {
    return snapshot({
      status: this.approvalPending ? "WAITING_APPROVAL" : "ACTIVE",
      ...(this.approvalPending
        ? {
            pending_approval: {
              action_digest: "digest-abc",
              capability_id: "workspace.edit",
              proposal_id: "p:1",
              preview: "edit fixture.txt",
              requested_at: new Date().toISOString(),
            },
          }
        : {}),
    });
  }
  async subscribeStream() {
    return { protocol_version: "1.1", runtime_boot_id: "boot:1", stream_id: "stream:1" };
  }
  async beginTurn() {
    return { protocol_version: "1.1", turn_id: "turn:1", stream_id: "stream:1" };
  }
  async *followStream() {
    for (const f of this.streamScript) yield f;
  }
  async events(_taskId: string, after: number) {
    this.eventsCalls += 1;
    const events = [];
    if (this.approvalPending) {
      events.push({
        event_id: "e:ap",
        task_id: "task:1",
        event_type: "SESSION_APPROVAL_PENDING",
        payload_json: JSON.stringify({ preview: "edit fixture.txt" }),
        occurred_at: new Date().toISOString(),
        sequence: after + 1,
      });
    } else if (this.completedTokens > 0) {
      const tokens = this.completedTokens;
      this.completedTokens = 0;
      events.push({
        event_id: "e:tc",
        task_id: "task:1",
        event_type: "SESSION_TURN_COMPLETED",
        payload_json: JSON.stringify({
          turn_id: "turn:1",
          total_tokens: tokens,
          ...(this.completedStopReason !== null
            ? { stop_reason: this.completedStopReason, steps: this.completedSteps }
            : {}),
        }),
        occurred_at: new Date().toISOString(),
        sequence: after + 1,
      });
      this.completedStopReason = null;
    }
    return {
      task_id: "task:1",
      after_sequence: after,
      next_sequence: after + events.length,
      events,
    };
  }
  async setPermissionMode(_sid: string, mode: PermissionMode) {
    this.modes.push(mode);
    return snapshot({ permission_mode: mode, event_sequence: 2 });
  }
  async decideApproval(_sid: string, digest: string, disposition: "APPROVE" | "REJECT") {
    this.approvals.push(`${disposition}:${digest}`);
    this.approvalPending = false;
    return {
      protocol_version: "1.1",
      snapshot: snapshot(),
      turn_id: "turn:1",
      text: disposition === "APPROVE" ? "edit applied" : "",
      steps: [],
      stop_reason: "completed",
      total_tokens: 12,
    };
  }
  async correct() {
    return snapshot({ status: "CORRECTION_HALTED" });
  }
}

test("slash commands: help/status/cost/invalid-mode/unknown", async () => {
  const controller = new TuiController(new FakeClient() as never);
  await controller.submit("/help");
  await controller.submit("/status");
  await controller.submit("/cost");
  await controller.submit("/mode bogus");
  await controller.submit("/frobnicate");
  const text = controller.messages.map((m) => m.content).join("\n");
  assert.match(text, /\/exit/);
  assert.match(text, /session none/);
  assert.match(text, /cost UNKNOWN/);
  assert.match(text, /invalid mode bogus/);
  assert.match(text, /unknown command: \/frobnicate/);
});

test("streaming turn: chunks assemble; durable completion adds exact tokens", async () => {
  const client = new FakeClient();
  client.streamScript = [
    frame(1, "turn:1", "CHUNK", "he"),
    frame(2, "turn:1", "CHUNK", "llo"),
    frame(3, "turn:1", "STREAM_END"),
  ];
  client.completedTokens = 42;
  const controller = new TuiController(client as never, { pollMs: 1 });
  await controller.submit("hello");
  // fire-and-forget durable drain resolves on microtasks
  await new Promise((resolve) => setTimeout(resolve, 10));
  const assistant = controller.messages.filter((m) => m.role === "assistant");
  assert.equal(assistant.map((m) => m.content).join(""), "hello");
  assert.equal(controller.tokensTotal, 42);
  assert.equal(controller.turns, 1);
  assert.equal(controller.status, "idle");
});

test("non-completed stop_reason surfaces verbatim (max_steps is not success)", async () => {
  const client = new FakeClient();
  client.streamScript = [frame(1, "turn:1", "STREAM_END")];
  client.completedTokens = 7;
  client.completedStopReason = "max_steps";
  client.completedSteps = 25;
  const controller = new TuiController(client as never, { pollMs: 1 });
  await controller.submit("loop forever");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(controller.status, "idle");
  assert.equal(controller.tokensTotal, 7); // tokens still counted exactly
  assert.equal(controller.lastStopReason, "max_steps");
  const system = controller.messages.filter((m) => m.role === "system").map((m) => m.content);
  assert.ok(
    system.some((c) => c.includes("turn ended: max_steps (25 steps")),
    `expected a typed stop notice, got: ${system.join(" | ")}`,
  );
});

test("completed stop_reason stays quiet (no false alarm on success)", async () => {
  const client = new FakeClient();
  client.streamScript = [frame(1, "turn:1", "STREAM_END")];
  client.completedTokens = 5;
  client.completedStopReason = "completed";
  const controller = new TuiController(client as never, { pollMs: 1 });
  await controller.submit("fine");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(controller.lastStopReason, "completed");
  const system = controller.messages.filter((m) => m.role === "system").map((m) => m.content);
  assert.ok(!system.some((c) => c.includes("turn ended:")), "no notice on success");
});

test("completion event for another turn is ignored", async () => {
  const controller = new TuiController(new FakeClient() as never, { pollMs: 1 });
  (controller as never as { applyDurable: (n: number, e: unknown[]) => void }).applyDurable(1, [
    {
      event_id: "e:x",
      task_id: "task:1",
      event_type: "SESSION_TURN_COMPLETED",
      payload_json: JSON.stringify({ turn_id: "turn:other", total_tokens: 99 }),
      occurred_at: new Date().toISOString(),
      sequence: 1,
    },
  ]);
  assert.equal(controller.tokensTotal, 0);
  assert.equal(controller.turns, 0);
});

test("approval pending → human approve → tokens + continuation text", async () => {
  const client = new FakeClient();
  client.streamScript = [frame(1, "turn:1", "STREAM_END")];
  client.approvalPending = true;
  const controller = new TuiController(client as never, { pollMs: 1 });
  await controller.submit("edit it");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(controller.status, "awaiting_approval");
  await controller.approve();
  assert.deepEqual(client.approvals, ["APPROVE:digest-abc"]);
  assert.equal(controller.status, "idle");
  assert.equal(controller.tokensTotal, 12);
  assert.ok(controller.messages.some((m) => m.content === "edit applied"));
});

test("stall: quiet stream past threshold renders the typed transient state", () => {
  let now = 1_000;
  const controller = new TuiController(new FakeClient() as never, {
    clock: () => now,
  });
  (controller as never as { status: string }).status = "streaming";
  (controller as never as { lastActivity: number | null }).lastActivity = now;
  now += STALL_DEFAULT_MS + 1;
  controller.tick();
  assert.equal(controller.status, "stalled");
});

test("mode command refreshes then sets (operator-only path)", async () => {
  const client = new FakeClient();
  client.streamScript = [frame(1, "turn:1", "STREAM_END")];
  client.completedTokens = 1;
  const controller = new TuiController(client as never, { pollMs: 1 });
  await controller.submit("open session");
  await new Promise((resolve) => setTimeout(resolve, 10));
  await controller.submit("/mode ACCEPT_IN_WORKSPACE");
  assert.deepEqual(client.modes, ["ACCEPT_IN_WORKSPACE"]);
  assert.equal(controller.mode, "ACCEPT_IN_WORKSPACE");
});

test("ctrl-c during streaming issues a correction, not a silent kill", async () => {
  const client = new FakeClient();
  const controller = new TuiController(client as never, { pollMs: 1 });
  (controller as never as { status: string; sessionId: string }).status = "streaming";
  (controller as never as { sessionId: string | null }).sessionId = "s:1";
  const result = await controller.interrupt();
  assert.equal(result, "corrected");
  assert.equal(controller.status, "idle");
  assert.ok(controller.messages.some((m) => m.content.includes("correction issued")));
});
