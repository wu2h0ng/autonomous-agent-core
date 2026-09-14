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
  async correct() {
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
