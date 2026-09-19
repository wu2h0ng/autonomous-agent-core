/**
 * Unit tests for the Ink-free TuiController, driven by a scripted fake
 * client. A controller that never hits the frozen semantics (durable
 * completion authority, human-only approval, stall typing) fails here.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { TuiController, STALL_DEFAULT_MS, renderTranscript, toolState } from "../src/controller.js";
import type { ChatMessage } from "../src/controller.js";
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
  getSessionCalls = 0;
  snapshotSequence = 1;
  beginTexts: string[] = [];

  async openSession() {
    return snapshot();
  }
  providerStatusCalls = 0;
  clearCalls = 0;
  configureCalls = 0;
  providerStatusResult: Record<string, unknown> = {
    protocol_version: "1.1",
    configured: false,
    persisted: false,
    key_source: null,
  };
  async providerStatus() {
    this.providerStatusCalls += 1;
    return this.providerStatusResult;
  }
  async configureProvider() {
    this.configureCalls += 1;
    return {
      protocol_version: "1.1",
      configured: true,
      persisted: true,
      key_source: "env",
    };
  }
  async clearProvider() {
    this.clearCalls += 1;
    return {
      protocol_version: "1.1",
      configured: true,
      persisted: false,
      key_source: "env",
    };
  }
  metricsSources: string[] = [];
  metricsResult: Record<string, unknown> = {
    source: "in_process",
    taken_at: "2026-09-18T10:00:00+00:00",
    window_records: 3,
    calls: 2,
    attempts: 3,
    responses: 2,
    failures: 1,
    retries: 1,
    latency: { samples: 3, mean_ms: 20, p50_ms: 10, p90_ms: 40, p95_ms: 40, max_ms: 40 },
    tokens: { input_tokens: 3, output_tokens: 6, total_tokens: 9, usage_samples: 2 },
    failure_categories: [{ code: "RATE_LIMITED", count: 1, retryable: true }],
    rate_limit: {
      rate_limited_attempts: 1,
      retry_after_observed: 0,
      max_retry_after_seconds: null,
      local_waits: 1,
      local_wait_ms_total: 2000,
      local_wait_ms_max: 2000,
      local_rejections: 0,
    },
  };
  metricsFailure: Error | null = null;
  async providerMetrics(source: string) {
    this.metricsSources.push(source);
    if (this.metricsFailure) throw this.metricsFailure;
    return this.metricsResult;
  }
  async getSession() {
    this.getSessionCalls += 1;
    return snapshot({
      event_sequence: this.snapshotSequence,
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
  async beginTurn(_sid: string, text: string) {
    this.beginTexts.push(text);
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
  async correct(
    _sessionId?: string,
    _reason?: string,
    _action?: string,
    _idempotencyKey?: string,
  ) {
    return snapshot({ status: "CORRECTION_HALTED" });
  }
  filesList = [
    { path: "fixture.txt", size: 12, mtime: "2026-09-11T00:00:00Z" },
    { path: "src/a.ts", size: 340, mtime: "2026-09-11T00:00:00Z" },
  ];
  sessionsList: { session_id: string; task_id: string; status: string; permission_mode: string; message_count: number; updated_at: string }[] = [];
  async listSessions() {
    return this.sessionsList;
  }
  async files(taskId: string) {
    assert.equal(taskId, "task:1");
    return this.filesList;
  }
  async overview(taskId: string) {
    assert.equal(taskId, "task:1");
    return {
      task_id: taskId,
      task_status: "ACTIVE",
      run_status: "COMPLETED",
      run_id: "run:1",
      expected_outcome_id: "outcome:1",
      receipt_count: 3,
      session_id: "s:1",
    };
  }
}

test("slash commands: help/status/cost/invalid-mode/unknown", async () => {
  const controller = new TuiController(new FakeClient() as never);
  await controller.submit("/help");
  await controller.submit("/status");
  await controller.submit("/cost");
  await controller.submit("/mode bogus");
  await controller.submit("/frobnicate");
  const text = controller.messages
    .map((m) => (m.panel ? [m.panel.title, ...m.panel.lines].join("\n") : m.content))
    .join("\n");
  assert.match(text, /\/exit/);
  assert.match(text, /session\s+none/);
  assert.match(text, /cost\s+UNKNOWN/);
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

test("REASONING frames are transient and never part of the answer", async () => {
  const client = new FakeClient();
  client.streamScript = [
    frame(1, "turn:1", "REASONING", "think-1"),
    frame(2, "turn:1", "REASONING", "think-2"),
    frame(3, "turn:1", "CHUNK", "answer"),
    frame(4, "turn:1", "STREAM_END"),
  ];
  client.completedTokens = 1;
  const controller = new TuiController(client as never, { pollMs: 1 });
  await controller.submit("q");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(controller.reasoningText, "think-1think-2");
  const assistant = controller.messages
    .filter((m) => m.role === "assistant")
    .map((m) => m.content)
    .join("");
  assert.equal(assistant, "answer");
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

test("stale approval-pending event from a resolved turn never resurrects", async () => {
  // Regression (iteration-9 E2E flake): after /resume the durable cursor
  // starts at 0 and replays an earlier turn's SESSION_APPROVAL_PENDING;
  // without turn binding it hijacks the in-flight turn's state.
  const controller = new TuiController(new FakeClient() as never, { pollMs: 1 });
  (controller as never as { applyDurable: (n: number, e: unknown[]) => void }).applyDurable(1, [
    {
      event_id: "e:old",
      task_id: "task:1",
      event_type: "SESSION_APPROVAL_PENDING",
      payload_json: JSON.stringify({ turn_id: "turn:resolved", preview: "old edit" }),
      occurred_at: new Date().toISOString(),
      sequence: 1,
    },
  ]);
  assert.equal(controller.status, "idle");
  assert.equal(controller.pendingPreview, null);
});

test("/files and /task: session-required, listing, prefix filter, overview", async () => {
  const controller = new TuiController(new FakeClient() as never, { pollMs: 1 });
  await controller.submit("/files");
  assert.match(controller.messages.at(-1)?.content ?? "", /no session yet/);

  await controller.submit("/resume s:1");
  await controller.submit("/files");
  const listing = controller.messages.at(-1)?.content ?? "";
  assert.match(listing, /files \(2\)/);
  assert.match(listing, /fixture\.txt \(12 B\)/);

  await controller.submit("/files src/");
  const filtered = controller.messages.at(-1)?.content ?? "";
  assert.match(filtered, /files \(1\)/);
  assert.ok(!filtered.includes("fixture.txt"));

  await controller.submit("/files nope/");
  assert.match(controller.messages.at(-1)?.content ?? "", /no workspace files matching nope\//);

  await controller.submit("/task");
  const overview = controller.messages.at(-1)?.content ?? "";
  assert.match(overview, /task task:1 · status ACTIVE · run COMPLETED · receipts 3/);
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

test("durable-resolved turn refreshes the authoritative snapshot (iteration-18)", async () => {
  // Regression: when SESSION_TURN_COMPLETED resolves via the durable event
  // drain, stream-side frames already advanced the kernel sequence past the
  // last tracked snapshot. Without a post-turn getSession the next submit
  // sends a stale expected_event_sequence and the kernel rejects it
  // ("expected event sequence 7 does not match current sequence 12").
  const client = new FakeClient();
  client.streamScript = [frame(1, "turn:1", "STREAM_END")];
  client.completedTokens = 3;
  client.snapshotSequence = 12; // kernel advanced past the tracked snapshot
  const controller = new TuiController(client as never, { pollMs: 1 });
  await controller.submit("hello");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(controller.status, "idle");
  assert.ok(client.getSessionCalls >= 1, "no snapshot refresh after durable completion");
  const adopted = (controller as never as { snapshot: SurfaceSessionSnapshot }).snapshot;
  assert.equal(adopted.event_sequence, 12);
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

test("stall: a failing durable drain says why instead of swallowing it", async () => {
  // The drain used to `.catch(() => undefined)`: a permanently failing batch
  // reached the user as the same bare "stalled" as a quiet daemon, with no way
  // to tell "the server is slow" from "we cannot read its answer".
  class RejectingClient extends FakeClient {
    async events(): Promise<never> {
      this.eventsCalls += 1;
      throw new Error("next_sequence must equal the last event sequence");
    }
  }
  const client = new RejectingClient();
  const controller = new TuiController(client as never, {
    stallMs: 30,
    pollMs: 1,
  });
  const internals = controller as never as {
    status: string;
    taskId: string | null;
    turnId: string | null;
    awaitDurableResolution(sessionId: string): Promise<void>;
  };
  internals.status = "streaming";
  internals.taskId = "task:1";
  internals.turnId = "turn:1";
  await internals.awaitDurableResolution("session:1");
  assert.equal(controller.status, "stalled");
  const system = controller.messages
    .filter((message) => message.role === "system")
    .map((message) => message.content);
  assert.ok(
    system.some(
      (line) =>
        line.includes("durable event drain failed") &&
        line.includes("next_sequence must equal the last event sequence"),
    ),
    `the stall must name the drain failure, got: ${JSON.stringify(system)}`,
  );
  assert.ok(
    client.eventsCalls > 1,
    "the drain must keep retrying rather than give up after one failure",
  );
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

test("a stale-cursor correction is retried from a fresh read and lands", async () => {
  // The kernel rejects a correction carrying a stale event cursor (409
  // SurfaceSequenceConflict). The refresh GET and the command POST are two
  // round trips and a running turn keeps appending durable events, so a commit
  // landing between them rejects a correction that was correct when read
  // (measured on a real daemon: 9 of 20 Esc presses mid-turn). The resend must
  // re-read the cursor, and must carry the same idempotency key so it can never
  // apply the operator's single correction twice.
  class StaleOnceClient extends FakeClient {
    calls: string[] = [];
    keys: (string | undefined)[] = [];
    async getSession() {
      this.calls.push("getSession");
      return super.getSession();
    }
    async correct(
      _sid: string,
      _reason: string,
      _action: string,
      key?: string,
    ) {
      this.calls.push("correct");
      this.keys.push(key);
      if (this.calls.filter((call) => call === "correct").length === 1) {
        throw new Error(
          "SurfaceSequenceConflict: expected event sequence 7 does not match current sequence 9",
        );
      }
      return snapshot({ status: "CORRECTION_HALTED" });
    }
  }
  const client = new StaleOnceClient();
  const controller = new TuiController(client as never, {
    pollMs: 1,
    sequenceRetryDelayMs: 1,
  });
  (controller as never as { status: string }).status = "streaming";
  (controller as never as { sessionId: string | null }).sessionId = "s:1";

  assert.equal(await controller.interrupt("escape"), "corrected");

  assert.deepEqual(
    client.calls,
    ["getSession", "correct", "getSession", "correct"],
    "the resend must re-read durable truth first, not reuse the stale cursor",
  );
  assert.equal(client.keys.length, 2);
  assert.equal(
    client.keys[0],
    client.keys[1],
    "one operator intent keeps one idempotency key, so a resend cannot double-apply",
  );
  const messages = controller.messages.map((m) => m.content);
  assert.ok(
    messages.some((text) => text.includes("correction issued")),
    `the absorbed retry must report success, got ${JSON.stringify(messages)}`,
  );
  assert.ok(
    !messages.some((text) => text.includes("correction FAILED")),
    "a correction that landed on the retry is not a failure",
  );
});

test("a correction the kernel keeps rejecting is bounded and reported once", async () => {
  class AlwaysStaleClient extends FakeClient {
    posts = 0;
    async correct(): Promise<never> {
      this.posts += 1;
      throw new Error(
        "SurfaceSequenceConflict: expected event sequence 7 does not match current sequence 12",
      );
    }
  }
  const client = new AlwaysStaleClient();
  const controller = new TuiController(client as never, {
    pollMs: 1,
    sequenceRetryDelayMs: 1,
  });
  (controller as never as { status: string }).status = "streaming";
  (controller as never as { sessionId: string | null }).sessionId = "s:1";

  await assert.rejects(() => controller.interrupt("escape"));

  assert.equal(client.posts, 3, "one attempt plus a bounded two resends, then stop");
  const failed = controller.messages.filter((m) => m.content.includes("correction FAILED"));
  assert.equal(failed.length, 1, "the same failure is reported exactly once");
  assert.match(failed[0]?.content ?? "", /was NOT corrected/);
  assert.ok(
    !controller.messages.some((m) => m.content.includes("correction issued")),
    "a failed correction must not also claim success",
  );
});

test("a successful correction is never resent", async () => {
  const client = new FakeClient();
  let posts = 0;
  const raw = client.correct.bind(client);
  client.correct = (async (...args: Parameters<FakeClient["correct"]>) => {
    posts += 1;
    return raw(...args);
  }) as FakeClient["correct"];
  const controller = new TuiController(client as never, {
    pollMs: 1,
    sequenceRetryDelayMs: 1,
  });
  (controller as never as { status: string }).status = "streaming";
  (controller as never as { sessionId: string | null }).sessionId = "s:1";

  assert.equal(await controller.interrupt("escape"), "corrected");
  assert.equal(posts, 1);
});

test("a repeated Esc joins the correction already in flight", async () => {
  // A held or repeated key used to send one POST and one transcript line per
  // key event: three identical "correction FAILED" lines for one operator
  // decision, and three chances to act on the same intent.
  class SlowStaleClient extends FakeClient {
    posts = 0;
    async correct(): Promise<never> {
      this.posts += 1;
      await new Promise((resolve) => setTimeout(resolve, 20));
      throw new Error(
        "SurfaceSequenceConflict: expected event sequence 7 does not match current sequence 9",
      );
    }
  }
  const client = new SlowStaleClient();
  const controller = new TuiController(client as never, {
    pollMs: 1,
    sequenceRetryDelayMs: 1,
  });
  (controller as never as { status: string }).status = "streaming";
  (controller as never as { sessionId: string | null }).sessionId = "s:1";

  const results = await Promise.allSettled([
    controller.interrupt("escape"),
    controller.interrupt("escape"),
    controller.interrupt("escape"),
  ]);

  assert.deepEqual(
    results.map((r) => r.status),
    ["rejected", "rejected", "rejected"],
  );
  assert.equal(client.posts, 3, "three presses are one intended correction, retried bounded");
  const failed = controller.messages.filter((m) => m.content.includes("correction FAILED"));
  assert.equal(failed.length, 1, "the same failure is noticed once, not three times");
});

test("/mode failure is caught and reported instead of escaping the submit path", async () => {
  // The view fires `void controller.submit(...)`, so a rejection here was an
  // unhandled rejection with nothing in the transcript: the operator kept
  // working under a mode the kernel never set.
  class StaleModeClient extends FakeClient {
    async setPermissionMode(): Promise<never> {
      throw new Error(
        "SurfaceSequenceConflict: expected event sequence 3 does not match current sequence 9",
      );
    }
  }
  const client = new StaleModeClient();
  const controller = new TuiController(client as never, {
    pollMs: 1,
    sequenceRetryDelayMs: 1,
  });
  await controller.submit("open session");
  await new Promise((resolve) => setTimeout(resolve, 10));

  await assert.doesNotReject(() => controller.submit("/mode ACCEPT_IN_WORKSPACE"));

  const messages = controller.messages.map((m) => m.content);
  assert.ok(
    messages.some(
      (text) =>
        text.includes("permission mode change to ACCEPT_IN_WORKSPACE FAILED") &&
        text.includes("still ASK"),
    ),
    `expected an honest failure notice, got ${JSON.stringify(messages)}`,
  );
  assert.equal(controller.mode, "ASK");
});

test("a turn-level failure re-reads durable truth before the next command", async () => {
  // A failed turn is often a stale client cursor (the kernel rejected some
  // command for a sequence the client had not observed). Leaving the old
  // snapshot in place made every following command fail the same way.
  class FailingTurnClient extends FakeClient {
    async beginTurn(): Promise<never> {
      throw new Error(
        "SurfaceSequenceConflict: expected event sequence 1 does not match current sequence 9",
      );
    }
  }
  const client = new FailingTurnClient();
  client.snapshotSequence = 9;
  const controller = new TuiController(client as never, { pollMs: 1 });

  await controller.submit("go");

  assert.equal(controller.status, "idle");
  assert.match(controller.lastError ?? "", /does not match current sequence 9/);
  assert.equal(client.getSessionCalls, 1, "the snapshot must be re-read after the failure");
  assert.equal(controller.currentSnapshot?.event_sequence, 9);
});

test("/doctor: wired probe text is surfaced; unavailable probe is honest", async () => {
  const wired = new TuiController(new FakeClient() as never, {
    doctor: async () => "doctor: all checks passed",
  });
  await wired.submit("/doctor");
  assert.match(wired.messages.at(-1)?.content ?? "", /doctor: all checks passed/);

  const unavailable = new TuiController(new FakeClient() as never);
  await unavailable.submit("/doctor");
  assert.match(unavailable.messages.at(-1)?.content ?? "", /doctor unavailable/);

  const failing = new TuiController(new FakeClient() as never, {
    doctor: async () => {
      throw new Error("probe exploded");
    },
  });
  await failing.submit("/doctor");
  assert.match(failing.messages.at(-1)?.content ?? "", /doctor failed: probe exploded/);
});

test("/metrics: renders the aggregated window; an unavailable source is honest", async () => {
  const client = new FakeClient();
  const controller = new TuiController(client as never);

  await controller.submit("/metrics");
  const panel = controller.messages.at(-1)?.panel;
  assert.ok(panel, "the metrics panel is pushed");
  assert.equal(panel.title, "provider metrics");
  const rendered = panel.lines.join("\n");
  assert.match(rendered, /calls\s+2 \(3 attempts, 1 retried\)/);
  assert.match(rendered, /outcome\s+2 responses, 1 failures/);
  assert.match(rendered, /p50 10\.0ms/);
  assert.match(rendered, /failure\s+RATE_LIMITED x1/);
  assert.equal(client.metricsSources.at(-1), "process", "the default source is the process window");

  await controller.submit("/metrics log");
  assert.equal(client.metricsSources.at(-1), "log");

  await controller.submit("/metrics sideways");
  assert.match(controller.messages.at(-1)?.content ?? "", /usage: \/metrics/);

  client.metricsFailure = new Error("no AGENT_OS_PROVIDER_LOG is set");
  await controller.submit("/metrics log");
  assert.match(controller.messages.at(-1)?.content ?? "", /metrics unavailable: no AGENT_OS_PROVIDER_LOG/);
});

test("/retry and /edit: recall the last operator message", async () => {
  const client = new FakeClient();
  client.streamScript = [frame(1, "turn:1", "STREAM_END")];
  client.completedTokens = 1;
  const controller = new TuiController(client as never, { pollMs: 1, stallMs: 50 });

  await controller.submit("/retry");
  assert.match(controller.messages.at(-1)?.content ?? "", /nothing to retry yet/);
  await controller.submit("/edit");
  assert.match(controller.messages.at(-1)?.content ?? "", /nothing to edit yet/);

  await controller.submit("do the thing");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(controller.lastUserText, "do the thing");

  await controller.submit("/edit");
  assert.equal(controller.hasPendingComposer, true);
  assert.equal(controller.consumePendingComposer(), "do the thing");
  assert.equal(controller.hasPendingComposer, false);
  assert.equal(controller.consumePendingComposer(), null);

  await controller.submit("/retry");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(client.beginTexts.filter((text) => text === "do the thing").length, 2);
});

test("/export: writes the transcript to an explicit path (0600)", async () => {
  const { existsSync, mkdtempSync, readFileSync, statSync, writeFileSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const controller = new TuiController(new FakeClient() as never);
  const push = (controller as never as { push: (m: { role: "user"; content: string }) => void }).push.bind(controller);
  push({ role: "user", content: "hello export" });

  const dir = mkdtempSync(join(tmpdir(), "cli-ts-export-"));
  const path = join(dir, "transcript.md");
  await controller.submit(`/export ${path}`);

  const text = readFileSync(path, "utf8");
  assert.match(text, /# Agent OS transcript/);
  assert.match(text, /hello export/);
  assert.match(text, /cost: UNKNOWN/);
  assert.equal(statSync(path).mode & 0o777, 0o600);
  assert.match(controller.messages.at(-1)?.content ?? "", /transcript exported to/);

  // a pre-existing looser-mode file must be tightened to 0600
  const loose = join(dir, "loose.md");
  writeFileSync(loose, "old", { mode: 0o644 });
  await controller.submit(`/export ${loose}`);
  assert.equal(statSync(loose).mode & 0o777, 0o600);

  // a path containing spaces is preserved (not truncated at the first token)
  const spaced = join(dir, "a b.md");
  await controller.submit(`/export ${spaced}`);
  assert.ok(existsSync(spaced));

  await controller.submit(`/export ${dir}/nope/deep.md`);
  assert.match(controller.messages.at(-1)?.content ?? "", /export failed:/);
});

test("/keys: renders the keymap card", async () => {
  const controller = new TuiController(new FakeClient() as never);
  await controller.submit("/keys");
  const message = controller.messages.at(-1);
  assert.equal(message?.panel?.title, "keyboard");
  assert.ok(message?.panel?.lines.some((line) => line.includes("ctrl-r")));
  assert.ok(message?.panel?.lines.some((line) => line.includes("ctrl-p")));
});

test("/find: searches the in-session transcript", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const push = (controller as never as { push: (m: { role: "user" | "assistant"; content: string }) => void }).push.bind(controller);
  push({ role: "user", content: "hello world" });
  push({ role: "assistant", content: "the world is round" });

  await controller.submit("/find world");
  const listing = controller.messages.at(-1)?.content ?? "";
  assert.match(listing, /2 match\(es\) for "world"/);
  assert.match(listing, /#1/);
  assert.match(listing, /#2/);

  // case-insensitive (the count includes the earlier /find listing message too)
  await controller.submit("/find WORLD");
  const upper = controller.messages.at(-1)?.content ?? "";
  assert.match(upper, /match\(es\) for "WORLD"/);
  assert.match(upper, /#1/);

  await controller.submit("/find zzz");
  assert.match(controller.messages.at(-1)?.content ?? "", /no transcript matches for "zzz"/);

  await controller.submit("/find");
  assert.match(controller.messages.at(-1)?.content ?? "", /usage: \/find/);
});

test("/vim: toggles the vim keymap", async () => {
  const controller = new TuiController(new FakeClient() as never);
  assert.equal(controller.vimMode, false);
  await controller.submit("/vim");
  assert.equal(controller.vimMode, true);
  assert.match(controller.messages.at(-1)?.content ?? "", /vim keymap on/);
  await controller.submit("/vim");
  assert.equal(controller.vimMode, false);
});

test("/resume: prefers the server session list, falls back to local MRU", async () => {
  const client = new FakeClient();
  client.sessionsList = [
    {
      session_id: "session:server",
      task_id: "task:server",
      status: "ACTIVE",
      permission_mode: "ASK",
      message_count: 1,
      updated_at: "2026-09-13T00:00:00Z",
    },
  ];
  const controller = new TuiController(client as never, { pollMs: 1 });
  await controller.submit("/resume");
  const listed = controller.pendingSelector;
  assert.equal(listed?.kind, "resume");
  assert.deepEqual(listed?.items, ["session:server"]);
  assert.equal(listed?.title, "sessions");

  // empty server list -> local MRU fallback
  const localOnly = new FakeClient();
  const fallback = new TuiController(localOnly as never, { pollMs: 1 });
  await fallback.submit("/resume seeded"); // records a recent session
  await fallback.submit("/resume");
  assert.equal(fallback.pendingSelector?.title, "recent sessions (local)");
  assert.ok(fallback.pendingSelector?.items.includes("s:1"));
});

test("/resume is refused while an approval is pending (approval surface stays in front)", async () => {
  // Drives a REAL turn to awaiting_approval. `busy` is false in that state, so
  // a `busy`-based guard would allow the switch and move the approval surface
  // away; the guard must be the turn-state predicate (canStartTurn).
  const client = new FakeClient();
  client.streamScript = [frame(1, "turn:1", "STREAM_END")];
  client.approvalPending = true;
  const controller = new TuiController(client as never, { pollMs: 1 });
  await controller.submit("edit it");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(controller.status, "awaiting_approval");
  assert.equal((controller as never as { busy: boolean }).busy, false);

  const sessionBefore = controller.currentSessionId;
  const countBefore = controller.messages.length;
  await controller.submit("/resume s:other");
  assert.ok(
    controller.messages
      .slice(countBefore)
      .some((m) => m.content.includes("cannot switch sessions")),
    "the refusal must be surfaced to the user",
  );
  assert.equal(controller.currentSessionId, sessionBefore, "no switch while approval pending");
  assert.equal(controller.status, "awaiting_approval", "approval surface preserved");
  assert.equal(controller.pendingPreview, "edit fixture.txt");
});

test("/theme /mode /resume selectors: open, choose, cancel", async () => {
  const client = new FakeClient();
  const controller = new TuiController(client as never, { pollMs: 1 });
  const wait = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 5));

  // helpers return values (not property paths) so assert narrowing cannot
  // collapse controller.pendingSelector to `never` across assertions
  const selKind = (): string => controller.pendingSelector?.kind ?? "";
  const selItems = (): readonly string[] => controller.pendingSelector?.items ?? [];

  // /theme (no arg) opens a selector; choosing applies; cancel clears
  await controller.submit("/theme");
  assert.equal(selKind(), "theme");
  assert.ok(selItems().includes("default"));
  controller.chooseSelector("mono");
  assert.equal(controller.themeName, "mono");
  assert.ok(controller.pendingSelector === null);

  await controller.submit("/theme");
  controller.cancelSelector();
  assert.ok(controller.pendingSelector === null);

  await controller.submit("/theme next");
  assert.notEqual(controller.themeName, "mono");
  await controller.submit("/theme nope");
  assert.match(controller.messages.at(-1)?.content ?? "", /unknown theme nope/);

  // /resume (no arg) opens a selector over locally-seen sessions
  await controller.submit("/resume s:1");
  await controller.submit("/resume");
  assert.equal(selKind(), "resume");
  assert.ok(selItems().includes("s:1"));
  controller.chooseSelector("s:1");
  await wait();
  assert.match(controller.messages.at(-1)?.content ?? "", /resumed session s:1/);

  // /mode (no arg) opens a selector; choosing sets the mode
  await controller.submit("/mode");
  assert.equal(selKind(), "mode");
  assert.deepEqual(selItems(), ["ASK", "ACCEPT_READ_ONLY", "ACCEPT_IN_WORKSPACE"]);
  controller.chooseSelector("ACCEPT_IN_WORKSPACE");
  await wait();
  assert.deepEqual(client.modes, ["ACCEPT_IN_WORKSPACE"]);
  assert.equal(controller.mode, "ACCEPT_IN_WORKSPACE");
});

test("/goal: show / set / clear, and the active goal prefixes every turn", async () => {
  const client = new FakeClient();
  client.streamScript = [frame(1, "turn:1", "STREAM_END")];
  client.completedTokens = 1;
  const controller = new TuiController(client as never, { pollMs: 1, stallMs: 50 });

  await controller.submit("/goal");
  assert.match(controller.messages.at(-1)?.content ?? "", /no session goal set/);

  await controller.submit("/goal ship the parity increment");
  assert.equal(controller.goal, "ship the parity increment");
  assert.match(controller.messages.at(-1)?.content ?? "", /session goal set/);

  await controller.submit("status?");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(client.beginTexts.at(-1), "[session goal] ship the parity increment\n\nstatus?");
  const user = controller.messages.find((m) => m.role === "user");
  assert.match(user?.content ?? "", /^\[session goal\] ship the parity increment/);

  await controller.submit("/goal clear");
  assert.equal(controller.goal, null);
  await controller.submit("plain");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(client.beginTexts.at(-1), "plain");
});

test("input queue: messages during a turn are queued, not refused, and auto-run on commit", async () => {
  const client = new FakeClient();
  client.streamScript = [frame(1, "turn:1", "STREAM_END")];
  client.completedTokens = 1;
  const controller = new TuiController(client as never, { pollMs: 1, stallMs: 50 });
  const internals = controller as never as {
    busy: boolean;
    status: string;
    maybeDrain: () => void;
  };

  internals.busy = true; // a turn is in flight
  await controller.submit("second");
  assert.equal(controller.queuedCount, 1);
  assert.match(controller.messages.at(-1)?.content ?? "", /queued \(#1\)/);

  // turn resolves -> the queue drains and the queued message runs
  internals.busy = false;
  internals.status = "idle";
  internals.maybeDrain();
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.ok(client.beginTexts.includes("second"), "queued message must run after the turn");
  assert.equal(controller.queuedCount, 0);
});

test("/queue: list and clear", async () => {
  const controller = new TuiController(new FakeClient() as never, { pollMs: 1 });
  const internals = controller as never as { busy: boolean };

  await controller.submit("/queue");
  assert.match(controller.messages.at(-1)?.content ?? "", /queue empty/);

  internals.busy = true;
  await controller.submit("alpha");
  await controller.submit("beta");
  await controller.submit("/queue");
  const listing = controller.messages.at(-1)?.content ?? "";
  assert.match(listing, /queued \(2\)/);
  assert.match(listing, /1\. alpha/);
  assert.match(listing, /2\. beta/);

  await controller.submit("/queue clear");
  assert.equal(controller.queuedCount, 0);
  assert.match(controller.messages.at(-1)?.content ?? "", /cleared 2 queued message/);
});

test("input queue: a submit while an approval is pending is queued, never a concurrent turn", async () => {
  const client = new FakeClient();
  const controller = new TuiController(client as never, { pollMs: 1 });
  (controller as never as { status: string }).status = "awaiting_approval";
  await controller.submit("later");
  assert.equal(controller.queuedCount, 1);
  assert.deepEqual(client.beginTexts, []);
});

test("/provider shows persistence + key source; /provider clear removes it", async () => {
  const client = new FakeClient();
  client.providerStatusResult = {
    protocol_version: "1.1",
    configured: true,
    model_id: "deepseek-chat",
    endpoint_class: "openai-compatible",
    base_url: "https://api.deepseek.com/v1",
    credential_ref_id: "credential:local:1",
    persisted: true,
    key_source: "keychain",
  };
  const controller = new TuiController(client as never);
  await controller.submit("/provider");
  const panel = controller.messages.at(-1)?.panel;
  const text = [panel?.title, ...(panel?.lines ?? [])].join("\n");
  assert.match(text, /persisted\s+yes/);
  assert.match(text, /key_source keychain/);
  assert.match(text, /model\s+deepseek-chat/);
  // No secret is present anywhere in the transcript.
  assert.ok(!JSON.stringify(controller.messages).includes("sk-"));

  await controller.submit("/provider clear");
  assert.equal(client.clearCalls, 1);
  assert.match(
    controller.messages.at(-1)?.content ?? "",
    /provider config \+ stored key removed/,
  );
});

test("/provider set without an env key never echoes or stores a key", async () => {
  const client = new FakeClient();
  const controller = new TuiController(client as never);
  const previous = process.env.AGENT_OS_PROVIDER_KEY;
  delete process.env.AGENT_OS_PROVIDER_KEY;
  try {
    await controller.submit("/provider set https://api.example.com/v1 m");
  } finally {
    if (previous !== undefined) process.env.AGENT_OS_PROVIDER_KEY = previous;
  }
  assert.equal(client.configureCalls, 0);
  assert.match(
    controller.messages.at(-1)?.content ?? "",
    /AGENT_OS_PROVIDER_KEY is not set/,
  );
  assert.ok(!JSON.stringify(controller.messages).includes("sk-"));
});

test("/provider set reads the key from env and never echoes it into the transcript", async () => {
  const sentinel = "sk-test-do-not-echo-123";
  const client = new FakeClient();
  const controller = new TuiController(client as never);
  const previous = process.env.AGENT_OS_PROVIDER_KEY;
  process.env.AGENT_OS_PROVIDER_KEY = sentinel;
  try {
    await controller.submit("/provider set https://api.example.com/v1 m");
  } finally {
    if (previous === undefined) delete process.env.AGENT_OS_PROVIDER_KEY;
    else process.env.AGENT_OS_PROVIDER_KEY = previous;
  }
  // The key was present and used, yet must not appear in the transcript.
  assert.equal(client.configureCalls, 1);
  assert.ok(!JSON.stringify(controller.messages).includes(sentinel));
});

/** Durable event helpers for the tool-card projection tests below. Shaped
 * after the real records measured from a live daemon run (S1 audit
 * 2026-09-18, /tmp/p2/s1): the receipt proves the dispatch happened and says
 * nothing about the exit code; the NODE_COMPLETED output is where the tool's
 * own result lives. */
function proposedEvent(seq: number, actionId: string, capabilityId: string, args: string) {
  return {
    event_id: `e:${seq}`,
    task_id: "task:1",
    event_type: "ACTION_PROPOSED",
    payload_json: JSON.stringify({
      action: { action_id: actionId, node_id: `node:${actionId}`, capability_id: capabilityId, arguments_json: args },
    }),
    occurred_at: new Date().toISOString(),
    sequence: seq,
  };
}

function receiptEvent(seq: number, actionId: string, body: Record<string, unknown>) {
  return {
    event_id: `e:${seq}`,
    task_id: "task:1",
    event_type: "ACTION_RECEIPT_RECORDED",
    payload_json: JSON.stringify({ decision: { action_id: actionId }, ...body }),
    occurred_at: new Date().toISOString(),
    sequence: seq,
  };
}

function completedEvent(seq: number, body: Record<string, unknown>) {
  return {
    event_id: `e:${seq}`,
    task_id: "task:1",
    event_type: "NODE_COMPLETED",
    payload_json: JSON.stringify(body),
    occurred_at: new Date().toISOString(),
    sequence: seq,
  };
}

function failedEvent(seq: number, body: Record<string, unknown>) {
  return {
    event_id: `e:${seq}`,
    task_id: "task:1",
    event_type: "NODE_FAILED",
    payload_json: JSON.stringify(body),
    occurred_at: new Date().toISOString(),
    sequence: seq,
  };
}

/** The durable refusal record a DENY leaves (kernel `_record_policy_verdict`).
 * Shaped after the real payload: a refused action is never proposed, dispatched
 * or receipted, so this is the ONLY trace of it. */
function verdictEvent(seq: number, body: Record<string, unknown>) {
  return {
    event_id: `e:${seq}`,
    task_id: "task:1",
    event_type: "POLICY_VERDICT_RECORDED",
    payload_json: JSON.stringify(body),
    occurred_at: new Date().toISOString(),
    sequence: seq,
  };
}

function ruleDenial(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    verdict: "DENY",
    basis: "rule",
    mode_event_id: null,
    rule_id: "rule-1",
    rule_reason: "deploy freeze",
    capability_id: "workspace.edit",
    risk_tier: 2,
    action_digest: "digest-1",
    action_id: "a:edit",
    node_id: "node:a:edit",
    arguments_json: JSON.stringify({
      path: "fixture.txt",
      old_string: "stable\n",
      new_string: "fixed\n",
    }),
    reason: "denied by an operator permission rule",
    ...overrides,
  };
}

function applyDurable(
  controller: TuiController,
): (next: number, events: unknown[]) => void {
  const internal = controller as never as {
    applyDurable: (next: number, events: unknown[]) => void;
  };
  return internal.applyDurable.bind(controller);
}

test("a non-zero tool exit code is not rendered as a plain success (S1 defect)", () => {
  const controller = new TuiController({} as never);
  const apply = applyDurable(controller);
  apply(1, [proposedEvent(1, "a:run", "workspace.run_tests", '{"command":"python -m pytest"}')]);
  apply(2, [
    receiptEvent(2, "a:run", {
      receipt: {
        action_id: "a:run",
        status: "SUCCEEDED",
        error_code: "error:none",
        output_artifact_ids: ["artifact:deadbeef"],
      },
    }),
  ]);

  // Receipt only: the dispatch is confirmed and nothing says the tests failed.
  assert.equal(controller.messages[0]?.tool?.status, "done");
  assert.equal(toolState(controller.messages[0]!.tool!), "done");

  // The tool's own result (measured shape: {"exit_code":1,"artifact_ids":[…]}).
  apply(3, [
    completedEvent(3, {
      action_id: "a:run",
      node_id: "node:a:run",
      agent_loop_dynamic_action: true,
      output: { exit_code: 1, digest: "deadbeef", artifact_ids: ["artifact:deadbeef"] },
    }),
  ]);
  const tool = controller.messages[0]?.tool;
  // The receipt's dispatch status is NOT rewritten...
  assert.equal(tool?.status, "done");
  // ...but the card is no longer indistinguishable from a passing run.
  assert.equal(tool?.exitCode, 1);
  assert.equal(toolState(tool!), "error");
  assert.match(tool?.resultSummary ?? "", /exit 1/);
  assert.match(tool?.resultSummary ?? "", /artifacts 1/);

  // /export must report the failure too, with a state that is not "done".
  const exported = renderTranscript(controller.messages, {
    sessionId: "s:1",
    mode: "ASK",
    tokens: 0,
    goal: null,
  });
  assert.match(exported, /- tool \[error\] workspace\.run_tests \(python -m pytest\) — exit 1/);
  assert.ok(!exported.includes("tool [done] workspace.run_tests"), "the failing run must not export as [done]");
});

test("a passing tool exit code keeps the card and /export unchanged", () => {
  const controller = new TuiController({} as never);
  const apply = applyDurable(controller);
  apply(1, [proposedEvent(1, "a:ok", "workspace.run_tests", '{"command":"python -m pytest"}')]);
  apply(2, [
    receiptEvent(2, "a:ok", {
      receipt: { action_id: "a:ok", status: "SUCCEEDED", error_code: "error:none", output_artifact_ids: ["artifact:1"] },
    }),
  ]);
  apply(3, [
    completedEvent(3, {
      action_id: "a:ok",
      output: { exit_code: 0, artifact_ids: ["artifact:1"] },
    }),
  ]);
  const tool = controller.messages[0]?.tool;
  assert.equal(toolState(tool!), "done");
  assert.equal(tool?.exitCode, 0);
  assert.equal(tool?.resultSummary, "artifacts 1", "exit 0 adds no failure text");
});

test("a tool-reported error string is surfaced, and a failed dispatch stays failed", () => {
  const controller = new TuiController({} as never);
  const apply = applyDurable(controller);

  apply(1, [proposedEvent(1, "a:err", "workspace.run_tests", "{}")]);
  apply(2, [
    receiptEvent(2, "a:err", { receipt: { action_id: "a:err", status: "SUCCEEDED" } }),
  ]);
  apply(3, [completedEvent(3, { action_id: "a:err", output: { error: "CapabilityDenied: nope" } })]);
  assert.equal(toolState(controller.messages[0]!.tool!), "error");
  assert.match(controller.messages[0]?.tool?.resultSummary ?? "", /error CapabilityDenied: nope/);

  // A receipt FAILED is still the dispatch failure it always was — the exit
  // code path must not relabel or overwrite it.
  apply(4, [proposedEvent(4, "a:bad", "workspace.shell", "{}")]);
  apply(5, [receiptEvent(5, "a:bad", { receipt: { action_id: "a:bad", status: "FAILED", error_code: "error:timeout" } })]);
  apply(6, [completedEvent(6, { action_id: "a:bad", output: { error: "late output" } })]);
  const failed = controller.messages[1]!.tool!;
  assert.equal(failed.status, "failed");
  assert.equal(toolState(failed), "failed");
  assert.match(failed.resultSummary ?? "", /error error:timeout/);
});

test("tool result binding: ignores foreign actions, tolerates node-only completions and junk", () => {
  const controller = new TuiController({} as never);
  const apply = applyDurable(controller);
  apply(1, [proposedEvent(1, "a:1", "workspace.run_tests", "{}")]);
  apply(2, [receiptEvent(2, "a:1", { receipt: { action_id: "a:1", status: "SUCCEEDED" } })]);

  // An action id this card does not own must not mutate it.
  apply(3, [completedEvent(3, { action_id: "a:other", output: { exit_code: 7 } })]);
  assert.equal(controller.messages[0]?.tool?.exitCode, undefined);
  // Junk shapes: no output, non-object output, non-integer exit code, bool.
  apply(4, [completedEvent(4, { action_id: "a:1" })]);
  apply(5, [completedEvent(5, { action_id: "a:1", output: "boom" })]);
  apply(6, [completedEvent(6, { action_id: "a:1", output: { exit_code: "1" } })]);
  apply(7, [completedEvent(7, { action_id: "a:1", output: { exit_code: true } })]);
  assert.equal(controller.messages[0]?.tool?.exitCode, undefined);
  assert.equal(toolState(controller.messages[0]!.tool!), "done");

  // Older/other emitters may carry only node_id — the node key still binds.
  apply(8, [completedEvent(8, { node_id: "node:a:1", output: { exit_code: 2 } })]);
  assert.equal(controller.messages[0]?.tool?.exitCode, 2);
  assert.match(controller.messages[0]?.tool?.resultSummary ?? "", /exit 2/);
});

test("toolState: pending/unknown receipts never render as a success", () => {
  const base = {
    actionId: "a:1",
    capabilityId: "workspace.run_tests",
    argsSummary: "",
    argsJson: "{}",
  };
  assert.equal(toolState({ ...base, status: "pending" }), "pending");
  assert.equal(toolState({ ...base, status: "done" }), "done");
  assert.equal(toolState({ ...base, status: "done", exitCode: 0 }), "done");
  assert.equal(toolState({ ...base, status: "done", exitCode: 3 }), "error");
  assert.equal(toolState({ ...base, status: "done", errorText: "x" }), "error");
  assert.equal(toolState({ ...base, status: "failed" }), "failed");
});

test("/keys no longer advertises an unwired Ctrl-O panel (S1 audit)", async () => {
  const controller = new TuiController(new FakeClient() as never);
  await controller.submit("/keys");
  const lines = controller.messages.at(-1)?.panel?.lines ?? [];
  const text = lines.join("\n");
  assert.match(text, /ctrl-r reverse search/, "the wired bindings stay advertised");
  assert.ok(!/ctrl-o/.test(text), "Ctrl-O has no handler anywhere in src/");
  assert.ok(!/ctrl-t/.test(text), "Ctrl-T has no handler anywhere in src/");
  // The panel it pointed at is unreachable, so the reason must not be the
  // now-removed help line either: the tool card carries the result instead.
  const card: ChatMessage = {
    role: "system",
    content: "",
    tool: {
      actionId: "a:1",
      capabilityId: "workspace.run_tests",
      argsSummary: "python -m pytest",
      argsJson: "{}",
      status: "done",
      exitCode: 1,
      resultSummary: "exit 1",
    },
  };
  assert.match(renderTranscript([card], { sessionId: null, mode: "ASK", tokens: 0, goal: null }), /exit 1/);
});

test("a tool call that sealed nothing converges to failed, not pending (round-3 defect)", () => {
  // A preflight refusal never dispatches, so no receipt and no NODE_COMPLETED
  // exist; before this mapping the card sat at ⏵ pending forever and /export
  // said `tool [pending]`, which is the operator-side half of S3's read-only
  // refusal.
  const controller = new TuiController({} as never);
  const apply = applyDurable(controller);
  const reason =
    "CapabilityDenied: locked.txt is read-only (mode 0444); a workspace write keeps " +
    "a file's permission bits, so the patch is refused -- make the file writable and apply the patch again";
  apply(1, [proposedEvent(1, "a:edit", "workspace.edit", '{"path":"locked.txt"}')]);
  assert.equal(controller.messages[0]?.tool?.status, "pending");

  apply(2, [
    failedEvent(2, {
      action_id: "a:edit",
      node_id: "node:a:edit",
      capability_id: "workspace.edit",
      error: reason,
      exception: "CapabilityDenied",
    }),
  ]);

  const tool = controller.messages[0]?.tool;
  assert.equal(tool?.status, "failed");
  assert.equal(tool?.errorText, reason);
  assert.match(tool?.resultSummary ?? "", /^error CapabilityDenied: locked\.txt is read-only/);
  const rendered = renderTranscript(controller.messages, {
    sessionId: null,
    mode: "ASK",
    tokens: 0,
    goal: null,
  });
  assert.match(rendered, /failed/);
  assert.match(rendered, /read-only \(mode 0444\)/);

  // Replay: the durable event is applied again on a later drain and must not
  // double the summary.
  const summary = tool?.resultSummary;
  apply(3, [
    failedEvent(3, { action_id: "a:edit", node_id: "node:a:edit", error: reason }),
  ]);
  assert.equal(controller.messages[0]?.tool?.resultSummary, summary);
});

test("a permission DENY reaches the operator as a failed card (defect b)", () => {
  // The kernel refuses the action before proposing it, so no ACTION_PROPOSED,
  // no receipt and no completion ever exist — the durable verdict is the ONLY
  // trace. Before this projection the transcript showed nothing at all while
  // headless reported success, so this test is also the bypass detector: delete
  // the POLICY_VERDICT_RECORDED branch and it goes red.
  const controller = new TuiController({} as never);
  const apply = applyDurable(controller);

  apply(1, [verdictEvent(1, ruleDenial())]);

  const tool = controller.messages[0]?.tool;
  assert.ok(tool, "the refusal must produce a card");
  assert.equal(tool?.status, "failed");
  assert.equal(toolState(tool!), "failed");
  assert.equal(tool?.capabilityId, "workspace.edit");
  assert.equal(tool?.argsSummary, "fixture.txt", "the card names what was attempted");
  assert.match(tool?.resultSummary ?? "", /denied by rule rule-1/);
  assert.match(tool?.resultSummary ?? "", /deploy freeze/);
  // A refusal is not a proposal: never pending, never approvable.
  assert.notEqual(toolState(tool!), "pending");

  const rendered = renderTranscript(controller.messages, {
    sessionId: "s:1",
    mode: "ASK",
    tokens: 0,
    goal: null,
  });
  assert.match(rendered, /- tool \[failed\] workspace\.edit \(fixture\.txt\)/);
  assert.match(rendered, /denied by rule rule-1/);
  assert.ok(!rendered.includes("[pending]"), "a refusal must not export as pending");

  assert.equal(controller.policyDenials.length, 1);
  assert.equal(controller.policyDenials[0]?.basis, "rule");
  assert.equal(controller.policyDenials[0]?.ruleId, "rule-1");

  // Replay of the same durable verdict must not double the card or the count.
  apply(2, [verdictEvent(2, ruleDenial())]);
  assert.equal(controller.messages.length, 1);
  assert.equal(controller.policyDenials.length, 1);
});

test("an out-of-allowlist DENY also produces a failed card", () => {
  const controller = new TuiController({} as never);
  const apply = applyDurable(controller);
  apply(1, [
    verdictEvent(1, {
      verdict: "DENY",
      basis: "out_of_allowlist",
      mode_event_id: null,
      capability_id: "workspace.exfiltrate",
      risk_tier: null,
      action_digest: "digest-x",
      proposal_id: "call-x",
      arguments_json: JSON.stringify({ path: "fixture.txt" }),
      reason: "capability is outside the frozen session allowlist",
    }),
  ]);
  const tool = controller.messages[0]?.tool;
  assert.equal(tool?.status, "failed");
  assert.equal(tool?.capabilityId, "workspace.exfiltrate");
  assert.match(tool?.resultSummary ?? "", /outside the frozen session allowlist/);
  assert.equal(controller.policyDenials[0]?.basis, "out_of_allowlist");
  assert.equal(controller.policyDenials[0]?.ruleId, null);
});

test("a mode ALLOW verdict is not an operator-visible card", () => {
  // `POLICY_VERDICT_RECORDED(ALLOW, basis=permission_mode)` is prior session
  // policy, not an outcome: it must not grow a card of its own.
  const controller = new TuiController({} as never);
  const apply = applyDurable(controller);
  apply(1, [
    verdictEvent(1, {
      verdict: "ALLOW",
      basis: "permission_mode",
      mode_event_id: "evt-1",
      rule_id: null,
      capability_id: "workspace.edit",
      risk_tier: 2,
      action_digest: "digest-1",
      action_id: "a:edit",
      node_id: "node:a:edit",
      arguments_json: "{}",
      reason: null,
    }),
  ]);
  assert.equal(controller.messages.length, 0);
  assert.equal(controller.policyDenials.length, 0);
});

test("a DENY for an already-proposed action fails that card instead of adding one", () => {
  // The resume path: the action was escalated (card exists, pending), the
  // operator then added a DENY rule and pressed approve — the kernel refuses and
  // the card must converge to failed rather than stay pending forever.
  const controller = new TuiController({} as never);
  const apply = applyDurable(controller);
  apply(1, [proposedEvent(1, "a:edit", "workspace.edit", '{"path":"fixture.txt"}')]);
  assert.equal(controller.messages[0]?.tool?.status, "pending");

  apply(2, [verdictEvent(2, ruleDenial())]);

  assert.equal(controller.messages.length, 1, "no second card for the same action");
  assert.equal(controller.messages[0]?.tool?.status, "failed");
  assert.match(controller.messages[0]?.tool?.resultSummary ?? "", /denied by rule rule-1/);
  assert.equal(controller.policyDenials.length, 1);
});

test("a resumed session replays a historical DENY as a card without charging it to this turn", async () => {
  // Review regression (PR #75): `POLICY_VERDICT_RECORDED` carries no `turn_id`,
  // and attaching to a session drains from `durableCursor` 0, so the whole
  // history is replayed here. The card must stay (the transcript is rebuilt
  // from that replay) while the turn-scoped `policyDenials` — what headless
  // turns into exit 4 — must not inherit a refusal this client never witnessed.
  const client = new FakeClient();
  client.snapshotSequence = 3; // the session already has history up to seq 3
  const controller = new TuiController(client as never, { pollMs: 1 });
  await controller.submit("/resume s:1");
  const apply = applyDurable(controller);

  apply(3, [verdictEvent(1, ruleDenial())]);
  const card = controller.messages.find((message) => message.tool !== undefined)?.tool;
  assert.equal(card?.status, "failed", "the refusal is history: it keeps its card");
  assert.match(card?.resultSummary ?? "", /denied by rule rule-1/);
  assert.equal(controller.policyDenials.length, 0, "but it is not this turn's refusal");

  // Exact boundary: the watermark's own sequence is history, not this turn.
  apply(3, [
    verdictEvent(3, ruleDenial({ action_id: "a:at-watermark", node_id: "node:a:at-watermark" })),
  ]);
  assert.equal(controller.policyDenials.length, 0);

  // A refusal recorded after the attach IS this turn's.
  apply(4, [
    verdictEvent(4, ruleDenial({ action_id: "a:edit-now", node_id: "node:a:edit-now" })),
  ]);
  assert.equal(controller.policyDenials.length, 1);
  assert.equal(controller.policyDenials[0]?.ruleId, "rule-1");
});

test("switching sessions re-seeds the watermark in the new session's sequence space", async () => {
  // Each task has its own sequence space, so a watermark carried over from a
  // far-advanced session would hide every refusal of a younger one (and
  // vice versa). Re-seeding exactly on session change is what keeps the scoping
  // honest in both directions.
  const client = new FakeClient();
  client.snapshotSequence = 50;
  const controller = new TuiController(client as never, { pollMs: 1 });
  await controller.submit("/resume s:1");
  const apply = applyDurable(controller);
  apply(51, [verdictEvent(51, ruleDenial())]);
  assert.equal(controller.policyDenials.length, 1);

  const snapshotFor = client.getSession.bind(client);
  client.getSession = async () => {
    const base = await snapshotFor();
    return { ...base, event_sequence: 2, session: { ...base.session, session_id: "s:2" } };
  };
  await controller.submit("/resume s:2");
  // The new session's own history is history again...
  apply(2, [
    verdictEvent(1, ruleDenial({ action_id: "a:hist-s2", node_id: "node:a:hist-s2" })),
  ]);
  assert.equal(controller.policyDenials.length, 1, "the new session's history stays history");
  // ...and its young sequence space is counted on its own scale: under a
  // carried-over max() watermark (50) this refusal at seq 3 would be dropped.
  apply(3, [
    verdictEvent(3, ruleDenial({ action_id: "a:edit-s2", node_id: "node:a:edit-s2" })),
  ]);
  assert.equal(
    controller.policyDenials.length,
    2,
    "a refusal after the switch is the new session's, not silently dropped",
  );
});

test("a rejected approval resolves the card instead of leaving it pending", async () => {
  // Rejecting is a resolution: the operator pressed n and the card kept showing
  // its pending state, on the surface they were looking at (round-3 audit).
  const client = new FakeClient();
  client.approvalPending = true;
  const controller = new TuiController(client as never, { pollMs: 1 });
  const apply = applyDurable(controller);
  apply(1, [proposedEvent(1, "a:edit", "workspace.edit", '{"path":"fixture.txt"}')]);
  const internals = controller as never as {
    status: string;
    sessionId: string | null;
  };
  internals.status = "awaiting_approval";
  internals.sessionId = "s:1";

  await controller.reject();

  const tool = controller.messages[0]?.tool;
  assert.equal(tool?.status, "failed");
  assert.equal(tool?.errorText, "rejected by the operator");
  assert.ok(
    controller.messages.some((message) =>
      message.content.includes("REJECT: workspace.edit"),
    ),
    "the transcript must still name what was rejected",
  );
  const rendered = renderTranscript(controller.messages, {
    sessionId: "s:1",
    mode: "ASK",
    tokens: 0,
    goal: null,
  });
  assert.match(rendered, /rejected by the operator/);
});

test("approving does not mark the card rejected", async () => {
  // The other direction: an approval leaves the card to the durable events
  // (receipt + NODE_COMPLETED), which is where its outcome belongs.
  const client = new FakeClient();
  client.approvalPending = true;
  const controller = new TuiController(client as never, { pollMs: 1 });
  const apply = applyDurable(controller);
  apply(1, [proposedEvent(1, "a:edit", "workspace.edit", '{"path":"fixture.txt"}')]);
  const internals = controller as never as {
    status: string;
    sessionId: string | null;
  };
  internals.status = "awaiting_approval";
  internals.sessionId = "s:1";

  await controller.approve();

  assert.equal(controller.messages[0]?.tool?.status, "pending");
  assert.ok(
    controller.messages.some((message) =>
      message.content.includes("APPROVE: workspace.edit"),
    ),
  );
});
