#!/usr/bin/env tsx
/**
 * Headless E2E for the cli-ts spike against the hermetic dev daemon.
 * Exits non-zero on any frozen-semantics violation.
 *
 * Phase 1 (`--phase full`, fresh daemon):
 *   1. openSession → subscribe (first) → begin-turn → live CHUNK frames →
 *      STREAM_END → durable snapshot ACTIVE
 *   2. setPermissionMode ASK → ACCEPT_READ_ONLY → ACCEPT_IN_WORKSPACE
 *   3. begin-turn → workspace.edit proposal → WAITING_APPROVAL with
 *      digest-bound pending approval → APPROVE → turn text + ACTIVE,
 *      fixture file actually edited on disk
 *   4. begin-turn via the real TuiController → second edit auto-allowed under
 *      ACCEPT_IN_WORKSPACE (no WAITING_APPROVAL) AND a workspace.edit tool
 *      card projects pending→done from the durable event stream (A#3);
 *      constant-deny or a missing card projection both fail this
 *
 * Phase 2 (`--phase resume`, after daemon restart on the same database):
 *   reloaded descriptor + getSession(same id) returns the durable session
 *   (mode/events preserved); the dead generation's stream binding fails
 *   typed stale (410) — transient frames are never replayable.
 *
 * Usage: tsx scripts/smoke.ts [--descriptor PATH] [--phase full|resume]
 */
import { readFileSync, writeFileSync } from "node:fs";
import {
  SurfaceClient,
  SurfaceStreamStaleError,
} from "../src/client.js";
import { TuiController } from "../src/controller.js";
import { loadRuntimeDescriptor } from "../src/descriptor.js";

function fail(message: string): never {
  console.error(`[smoke] FAIL: ${message}`);
  process.exit(1);
}

async function runTurn(
  client: SurfaceClient,
  sessionId: string,
  text: string,
  binding: { runtime_boot_id: string; stream_id: string },
): Promise<string> {
  const begin = await client.beginTurn(sessionId, text, binding);
  if (begin.stream_id !== binding.stream_id) {
    fail(`begin-turn rebound stream ${begin.stream_id}`);
  }
  let chunks = 0;
  let assembled = "";
  let sawEnd = false;
  for await (const frame of client.followStream(sessionId, binding, { pollMs: 50 })) {
    if (frame.kind === "CHUNK") {
      chunks += 1;
      assembled += (frame.payload as { delta?: string }).delta ?? "";
      if (frame.turn_id !== begin.turn_id) {
        fail(`chunk bound to wrong turn ${frame.turn_id}`);
      }
    } else if (frame.kind === "GAP") {
      console.log(`[smoke]   explicit gap ${frame.gap_from}–${frame.gap_to} (loss honesty)`);
    } else if (frame.kind === "STREAM_END") {
      sawEnd = true;
    }
  }
  if (!sawEnd) fail("stream ended without STREAM_END frame");
  console.log(`[smoke]   turn ${begin.turn_id.slice(0, 16)}…: ${chunks} chunks, ${assembled.length} chars`);
  return assembled;
}

async function full(client: SurfaceClient, descriptorPath: string): Promise<void> {
  const opened = await client.openSession("cli-ts spike smoke session");
  const sessionId = opened.session.session_id;
  console.log(`[smoke] session opened: ${sessionId}`);

  const subscription = await client.subscribeStream(sessionId);
  const binding = {
    runtime_boot_id: subscription.runtime_boot_id,
    stream_id: subscription.stream_id,
  };
  console.log(`[smoke] stream subscribed (subscription-first): ${binding.stream_id}`);

  // 1. plain streaming turn
  const text1 = await runTurn(client, sessionId, "smoke turn 1", binding);
  if (!text1.includes("终端流式验证通过")) fail("turn 1 assembled text mismatch");
  const snap1 = await client.getSession(sessionId);
  if (snap1.status !== "ACTIVE") fail(`after turn 1 status=${snap1.status}`);
  console.log("[smoke] turn 1 PASS: streaming + durable commit consistent");

  // 2. permission mode cycle (operator-only command)
  const modeSnap = await client.setPermissionMode(sessionId, "ACCEPT_READ_ONLY");
  if (modeSnap.permission_mode !== "ACCEPT_READ_ONLY") fail("mode did not switch");
  console.log("[smoke] mode switch PASS: ASK → ACCEPT_READ_ONLY");

  // 3. approval flow: edit proposal → WAITING_APPROVAL → human APPROVE
  await runTurn(client, sessionId, "smoke turn 2 (edit)", binding);
  const snap2 = await client.getSession(sessionId);
  if (snap2.status !== "WAITING_APPROVAL" || !snap2.pending_approval) {
    fail(`turn 2 expected WAITING_APPROVAL, got ${snap2.status}`);
  }
  const pending = snap2.pending_approval;
  console.log(`[smoke] approval pending: ${pending.capability_id} digest=${pending.action_digest.slice(0, 12)}…`);
  const decided = await client.decideApproval(sessionId, pending.action_digest, "APPROVE", "smoke approve");
  if (decided.snapshot.status !== "ACTIVE") fail(`after approve status=${decided.snapshot.status}`);
  if (!decided.text.includes("edit applied")) fail(`approval resume text mismatch: "${decided.text}"`);
  const fixture = readFileSync(
    `${(await loadRuntimeDescriptor(descriptorPath)).workspace_path}/fixture.txt`,
    "utf8",
  );
  if (!fixture.includes("(edited)")) fail("fixture.txt was not actually edited");
  console.log("[smoke] turn 2 PASS: digest-bound approval, edit applied on disk");

  // 4. auto-allow under ACCEPT_IN_WORKSPACE driven through the real
  //    TuiController — positive path (constant-deny fails) AND proof that
  //    tool cards project from the durable ACTION_PROPOSED /
  //    ACTION_RECEIPT_RECORDED events against the live daemon (A#3 closure).
  await client.setPermissionMode(sessionId, "ACCEPT_IN_WORKSPACE");
  const controller = new TuiController(client, { pollMs: 50 });
  await controller.submit(`/resume ${sessionId}`);
  await controller.runTurn("smoke turn 3 (edit)");
  if (controller.status !== "idle") {
    fail(`turn 3 controller ended in status=${controller.status}`);
  }
  const snap3 = await client.getSession(sessionId);
  if (snap3.status === "WAITING_APPROVAL") {
    fail("turn 3 edit was NOT auto-allowed under ACCEPT_IN_WORKSPACE");
  }
  const assistantText = controller.messages
    .filter((m) => m.role === "assistant")
    .map((m) => m.content)
    .join("");
  if (!assistantText.includes("second edit applied")) {
    fail(`turn 3 text mismatch: "${assistantText}"`);
  }
  // The durable drain is fire-and-forget; allow a short settle window for the
  // receipt event to land before asserting the card's final state.
  const settleDeadline = Date.now() + 3000;
  let card = controller.messages.find(
    (m) => m.tool?.capabilityId === "workspace.edit" && m.tool.status === "done",
  );
  while (!card && Date.now() < settleDeadline) {
    await new Promise((resolve) => setTimeout(resolve, 50));
    card = controller.messages.find(
      (m) => m.tool?.capabilityId === "workspace.edit" && m.tool.status === "done",
    );
  }
  if (!card?.tool) {
    const seen = controller.messages
      .filter((m) => m.tool)
      .map((m) => `${m.tool!.capabilityId}:${m.tool!.status}`)
      .join(", ");
    fail(`no done workspace.edit tool card projected (seen: ${seen || "none"})`);
  }
  if (!card.tool.argsSummary.includes("fixture.txt")) {
    fail(`tool card args summary mismatch: "${card.tool.argsSummary}"`);
  }
  console.log(
    `[smoke]   tool card PASS: ${card.tool.capabilityId} → done (args: ${card.tool.argsSummary})`,
  );
  const fixture2 = readFileSync(
    `${(await loadRuntimeDescriptor(descriptorPath)).workspace_path}/fixture.txt`,
    "utf8",
  );
  if (!fixture2.includes("(edited twice)")) fail("second edit was not auto-applied");
  console.log("[smoke] turn 3 PASS: tier-2 in-sandbox auto-allow + tool card projected");

  writeFileSync(
    `${descriptorPath}.state.json`,
    JSON.stringify({ sessionId, binding, eventSequence: snap3.event_sequence }),
  );
  console.log(`[smoke] full phase PASS (events=${snap3.event_sequence}, messages=${snap3.message_count})`);
}

async function resume(descriptorPath: string): Promise<void> {
  const state = JSON.parse(readFileSync(`${descriptorPath}.state.json`, "utf8")) as {
    sessionId: string;
    binding: { runtime_boot_id: string; stream_id: string };
    eventSequence: number;
  };
  const descriptor = await loadRuntimeDescriptor(descriptorPath);
  const client = new SurfaceClient(descriptor);

  const snapshot = await client.getSession(state.sessionId);
  if (snapshot.permission_mode !== "ACCEPT_IN_WORKSPACE") {
    fail(`resume: mode lost across restart (got ${snapshot.permission_mode})`);
  }
  if (snapshot.event_sequence < state.eventSequence) {
    fail(`resume: event sequence regressed ${state.eventSequence} → ${snapshot.event_sequence}`);
  }
  console.log(
    `[smoke] resume PASS: session durable across daemon restart ` +
      `(status=${snapshot.status}, mode=${snapshot.permission_mode}, events=${snapshot.event_sequence})`,
  );

  try {
    await client.streamFrames(state.sessionId, state.binding, 0, 0);
    fail("resume: dead-generation stream binding was accepted");
  } catch (error) {
    if (error instanceof SurfaceStreamStaleError) {
      console.log("[smoke] resume PASS: stale generation rejected typed (410 STREAM_GONE)");
    } else {
      throw error;
    }
  }
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const descriptorFlag = args.indexOf("--descriptor");
  const phaseFlag = args.indexOf("--phase");
  const descriptorPath = descriptorFlag >= 0 ? args[descriptorFlag + 1]! : undefined;
  const phase = phaseFlag >= 0 ? args[phaseFlag + 1] : "full";
  const descriptor = await loadRuntimeDescriptor(descriptorPath);
  const client = new SurfaceClient(descriptor);
  if (phase === "resume") {
    await resume(descriptorPath ?? "");
  } else {
    await full(client, descriptorPath ?? "");
  }
  console.log("[smoke] PASS");
}

main().catch((cause: unknown) => {
  console.error(`[smoke] ERROR: ${(cause as Error).message}`);
  process.exit(1);
});
