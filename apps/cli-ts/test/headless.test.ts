/**
 * Headless mode tests: frozen exit-code table and output formats, driven by a
 * scripted fake client through the real TuiController (frozen semantics are
 * inherited, not reimplemented).
 */
import assert from "node:assert/strict";
import test from "node:test";
import { HEADLESS_EXIT, runHeadless } from "../src/headless.js";
import type {
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

class StubClient {
  chunks: string[] = [];
  stopReason: string | null = null;
  tokens = 10;
  approvalPending = false;
  /** Durable refusal records this turn's drain returns (defect b). */
  denials: Record<string, unknown>[] = [];

  async openSession() {
    return snapshot();
  }
  async getSession() {
    return snapshot({
      status: this.approvalPending ? "WAITING_APPROVAL" : "ACTIVE",
      ...(this.approvalPending
        ? {
            pending_approval: {
              action_digest: "digest-x",
              capability_id: "workspace.shell",
              proposal_id: "p:1",
              preview: "run rm -rf /",
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
  async *followStream(): AsyncIterable<SurfaceStreamFrame> {
    let seq = 0;
    for (const chunk of this.chunks) {
      seq += 1;
      yield {
        kind: "CHUNK",
        runtime_boot_id: "boot:1",
        stream_id: "stream:1",
        turn_id: "turn:1",
        frame_sequence: seq,
        payload: { delta: chunk },
      };
    }
    yield {
      kind: "STREAM_END",
      runtime_boot_id: "boot:1",
      stream_id: "stream:1",
      turn_id: "turn:1",
      frame_sequence: seq + 1,
      payload: {},
    };
  }
  async events(_taskId: string, after: number) {
    const events = [];
    if (this.approvalPending) {
      events.push({
        event_id: "e:ap",
        task_id: "task:1",
        event_type: "SESSION_APPROVAL_PENDING",
        payload_json: JSON.stringify({ preview: "run rm -rf /" }),
        occurred_at: new Date().toISOString(),
        sequence: after + 1,
      });
    } else if (this.tokens > 0) {
      const tokens = this.tokens;
      this.tokens = 0;
      // A refusal is recorded durably BEFORE the turn completes (the kernel
      // records the verdict while the proposal is being decided), so the deny
      // event and the completion arrive in the same batch, in sequence order.
      this.denials.forEach((denial, index) => {
        events.push({
          event_id: `e:deny:${index}`,
          task_id: "task:1",
          event_type: "POLICY_VERDICT_RECORDED",
          payload_json: JSON.stringify(denial),
          occurred_at: new Date().toISOString(),
          sequence: after + 1 + index,
        });
      });
      events.push({
        event_id: "e:tc",
        task_id: "task:1",
        event_type: "SESSION_TURN_COMPLETED",
        payload_json: JSON.stringify({
          turn_id: "turn:1",
          total_tokens: tokens,
          ...(this.stopReason !== null
            ? { stop_reason: this.stopReason, steps: 25 }
            : {}),
        }),
        occurred_at: new Date().toISOString(),
        sequence: after + 1 + events.length,
      });
    }
    return { task_id: "task:1", after_sequence: after, next_sequence: after + events.length, events };
  }
  async setPermissionMode() {
    return snapshot();
  }
  async decideApproval() {
    throw new Error("headless never approves");
  }
  async correct() {
    return snapshot({ status: "CORRECTION_HALTED" });
  }
}

function capture(): { stdout: (s: string) => void; stderr: (s: string) => void; out: string[]; err: string[] } {
  const out: string[] = [];
  const err: string[] = [];
  return { stdout: (s) => out.push(s), stderr: (s) => err.push(s), out, err };
}

test("headless success: exit 0, assembled text on stdout, json shape", async () => {
  const client = new StubClient();
  client.chunks = ["hel", "lo"];
  const io = capture();
  const code = await runHeadless(client as never, { prompt: "hi", outputFormat: "json" }, io);
  assert.equal(code, HEADLESS_EXIT.OK);
  const payload = JSON.parse(io.out.join("")) as Record<string, unknown>;
  assert.equal(payload["type"], "result");
  assert.equal(payload["subtype"], "success");
  assert.equal(payload["text"], "hello");
  assert.equal(payload["stop_reason"], "completed");
  assert.equal(payload["total_tokens"], 10);
  assert.equal(payload["is_error"], false);
  assert.equal(payload["session_id"], "s:1");
});

test("headless stream-json: NDJSON init + per-delta lines + result", async () => {
  const client = new StubClient();
  client.chunks = ["hel", "lo"];
  const io = capture();
  const code = await runHeadless(client as never, { prompt: "hi", outputFormat: "stream-json" }, io);
  assert.equal(code, HEADLESS_EXIT.OK);
  const lines = io.out.join("").trim().split("\n").map((l) => JSON.parse(l) as Record<string, unknown>);
  assert.equal(lines[0]?.["type"], "system");
  assert.equal(lines[0]?.["subtype"], "init");
  assert.equal(lines[0]?.["session_id"], "s:1");
  const deltas = lines.filter((l) => l["type"] === "assistant").map((l) => l["delta"]);
  assert.deepEqual(deltas, ["hel", "lo"]);
  const resultLine = lines.at(-1);
  assert.equal(resultLine?.["type"], "result");
  assert.equal(resultLine?.["subtype"], "success");
  assert.equal(resultLine?.["text"], "hello");
  // session lifecycle is carried by the init line; stderr stays empty
  assert.equal(io.err.join(""), "");
});

test("headless text mode: text on stdout only, notices on stderr", async () => {
  const client = new StubClient();
  client.chunks = ["answer"];
  const io = capture();
  const code = await runHeadless(client as never, { prompt: "hi" }, io);
  assert.equal(code, HEADLESS_EXIT.OK);
  assert.equal(io.out.join(""), "answer\n");
  // session lifecycle notices go to stderr, never stdout
  assert.match(io.err.join(""), /^⏵ session s:1 opened\n$/);
});

test("headless approval: fail-closed exit 2, no auto-approve", async () => {
  const client = new StubClient();
  client.approvalPending = true;
  const io = capture();
  const code = await runHeadless(client as never, { prompt: "do it", outputFormat: "json" }, io);
  assert.equal(code, HEADLESS_EXIT.APPROVAL_REQUIRED);
  const payload = JSON.parse(io.out.join("")) as Record<string, unknown>;
  assert.equal(payload["subtype"], "approval_required");
  assert.match(String(payload["stop_reason"]), /workspace\.shell/);
  assert.equal(payload["is_error"], true);
});

test("headless non-completed stop: exit 3, reason verbatim, tokens counted", async () => {
  const client = new StubClient();
  client.chunks = ["partial"];
  client.stopReason = "budget_exceeded";
  const io = capture();
  const code = await runHeadless(client as never, { prompt: "hi", outputFormat: "json" }, io);
  assert.equal(code, HEADLESS_EXIT.NOT_COMPLETED);
  const payload = JSON.parse(io.out.join("")) as Record<string, unknown>;
  assert.equal(payload["subtype"], "not_completed");
  assert.equal(payload["stop_reason"], "budget_exceeded");
  assert.equal(payload["total_tokens"], 10);
  assert.equal(payload["text"], "partial");
});

test("headless transport error: exit 1", async () => {
  const client = new StubClient();
  client.openSession = async () => {
    throw new Error("connection refused");
  };
  const io = capture();
  const code = await runHeadless(client as never, { prompt: "hi", outputFormat: "json" }, io);
  assert.equal(code, HEADLESS_EXIT.ERROR);
  const payload = JSON.parse(io.out.join("")) as Record<string, unknown>;
  assert.equal(payload["subtype"], "error");
  assert.match(String(payload["stop_reason"]), /connection refused/);
});

test("headless refuses to report success when the kernel denied the action (defect b)", async () => {
  // The kernel refuses a rule-denied edit before it is proposed, so the turn
  // itself completes normally and the model can answer "done" while the file is
  // untouched. Exit 0 / subtype success for that was the defect: a script (or a
  // caller) had no way to tell "applied" from "refused and never executed".
  const client = new StubClient();
  client.chunks = ["done, fixture.txt is fixed"];
  client.denials = [
    {
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
      arguments_json: JSON.stringify({ path: "fixture.txt" }),
      reason: "denied by an operator permission rule",
    },
  ];
  const io = capture();
  const code = await runHeadless(client as never, { prompt: "fix fixture.txt", outputFormat: "json" }, io);

  assert.notEqual(code, HEADLESS_EXIT.OK);
  assert.equal(code, HEADLESS_EXIT.DENIED);
  const payload = JSON.parse(io.out.join("")) as Record<string, unknown>;
  assert.equal(payload["subtype"], "denied");
  assert.equal(payload["is_error"], true);
  assert.equal(payload["stop_reason"], "denied_by_rule:rule-1");
  // The turn really did complete and its tokens were counted: the refusal is
  // reported as a refusal, never as a fabricated failure of the transport.
  assert.equal(payload["total_tokens"], 10);
  assert.equal(payload["text"], "done, fixture.txt is fixed");
});

test("headless text mode says which action was refused, on stderr", async () => {
  const client = new StubClient();
  client.chunks = ["all done"];
  client.denials = [
    {
      verdict: "DENY",
      basis: "out_of_allowlist",
      mode_event_id: null,
      capability_id: "workspace.exfiltrate",
      risk_tier: null,
      action_digest: "digest-x",
      proposal_id: "call-x",
      arguments_json: JSON.stringify({ path: "secrets.txt" }),
      reason: "capability is outside the frozen session allowlist",
    },
  ];
  const io = capture();
  const code = await runHeadless(client as never, { prompt: "exfiltrate", outputFormat: "text" }, io);
  assert.equal(code, HEADLESS_EXIT.DENIED);
  assert.match(io.err.join(""), /refused: workspace\.exfiltrate · denied:out_of_allowlist/);
  assert.match(io.err.join(""), /NOT executed/);
  assert.match(io.err.join(""), /noem: denied \(denied:out_of_allowlist\)/);
});

test("a refused action is not reported as success on a later clean turn", async () => {
  // Turn-scoped: the previous turn's refusal must not poison a later turn that
  // was not denied (a persistent flag would be its own lie).
  const client = new StubClient();
  client.chunks = ["first"];
  client.denials = [
    {
      verdict: "DENY",
      basis: "rule",
      rule_id: "rule-1",
      rule_reason: "deploy freeze",
      capability_id: "workspace.edit",
      action_id: "a:edit",
      node_id: "node:a:edit",
      arguments_json: "{}",
      reason: "denied by an operator permission rule",
    },
  ];
  const io = capture();
  assert.equal(
    await runHeadless(client as never, { prompt: "first", outputFormat: "json" }, io),
    HEADLESS_EXIT.DENIED,
  );
  const first = JSON.parse(io.out.join("")) as Record<string, unknown>;
  assert.match(String(first["stop_reason"]), /denied_by_rule:rule-1/);

  const clean = capture();
  client.denials = [];
  client.chunks = ["second"];
  client.tokens = 7;
  assert.equal(
    await runHeadless(client as never, { prompt: "second", outputFormat: "json" }, clean),
    HEADLESS_EXIT.OK,
  );
  assert.equal((JSON.parse(clean.out.join("")) as Record<string, unknown>)["subtype"], "success");
});
