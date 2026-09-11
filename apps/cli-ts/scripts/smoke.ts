#!/usr/bin/env tsx
/**
 * Headless smoke for the cli-ts spike against the hermetic dev daemon.
 *
 * Walks the frozen E1 order end to end and exits non-zero on any violation:
 *   open session → subscribe stream (first) → begin-turn (bound to the
 *   pre-subscribed stream) → follow CHUNK frames live → STREAM_END →
 *   durable snapshot consistency (status, message_count, event_sequence).
 *
 * Usage: tsx scripts/smoke.ts [--descriptor PATH]
 */
import { SurfaceClient } from "../src/client.js";
import { loadRuntimeDescriptor } from "../src/descriptor.js";

async function main(): Promise<number> {
  const args = process.argv.slice(2);
  const flag = args.indexOf("--descriptor");
  const descriptor = await loadRuntimeDescriptor(flag >= 0 ? args[flag + 1] : undefined);
  const client = new SurfaceClient(descriptor);

  const opened = await client.openSession("cli-ts spike smoke session");
  const sessionId = opened.session.session_id;
  console.log(`[smoke] session opened: ${sessionId}`);

  const subscription = await client.subscribeStream(sessionId);
  console.log(
    `[smoke] stream subscribed: boot=${subscription.runtime_boot_id} stream=${subscription.stream_id}`,
  );

  const binding = {
    runtime_boot_id: subscription.runtime_boot_id,
    stream_id: subscription.stream_id,
  };
  const statement = "smoke: say the scripted line";
  const begin = await client.beginTurn(sessionId, statement, binding);
  if (begin.stream_id !== binding.stream_id) {
    console.error(`[smoke] FAIL: begin-turn rebound stream ${begin.stream_id}`);
    return 1;
  }
  console.log(`[smoke] turn begun: turn=${begin.turn_id}`);

  let chunks = 0;
  let gap = 0;
  let sawEnd = false;
  let assembled = "";
  for await (const frame of client.followStream(sessionId, binding, { pollMs: 50 })) {
    if (frame.kind === "CHUNK") {
      chunks += 1;
      assembled += (frame.payload as { delta?: string }).delta ?? "";
      if (frame.turn_id !== begin.turn_id) {
        console.error(`[smoke] FAIL: chunk bound to wrong turn ${frame.turn_id}`);
        return 1;
      }
    } else if (frame.kind === "GAP") {
      gap += 1;
    } else if (frame.kind === "STREAM_END") {
      sawEnd = true;
    }
  }
  if (!sawEnd || chunks === 0) {
    console.error(`[smoke] FAIL: chunks=${chunks} stream_end=${sawEnd}`);
    return 1;
  }
  console.log(`[smoke] frames: ${chunks} chunks, ${gap} gaps, stream_end seen`);
  console.log(`[smoke] assembled ${assembled.length} chars: "${assembled.slice(0, 72)}…"`);

  const snapshot = await client.getSession(sessionId);
  if (snapshot.status !== "ACTIVE" && snapshot.status !== "WAITING_APPROVAL") {
    console.error(`[smoke] FAIL: unexpected final status ${snapshot.status}`);
    return 1;
  }
  console.log(
    `[smoke] durable snapshot: status=${snapshot.status} mode=${snapshot.permission_mode} ` +
      `events=${snapshot.event_sequence} messages=${snapshot.message_count}`,
  );
  console.log("[smoke] PASS");
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((cause: unknown) => {
    console.error(`[smoke] ERROR: ${(cause as Error).message}`);
    process.exit(1);
  });
