/**
 * Headless session administration (`noem session ...`), mirroring the
 * former Python `session-show` / `session-pause` / `session-resume` /
 * `session-correct` subcommands. Read/control only; durable truth stays in the
 * task event stream.
 */
import { SurfaceClient, SurfaceHttpError } from "./client.js";
import { loadRuntimeDescriptor } from "./descriptor.js";

export interface SessionCommandOptions {
  descriptorPath?: string | undefined;
  args: string[];
}

const SUBCOMMANDS = new Set(["show", "pause", "resume", "correct"]);

/** Bounded refresh-and-resend budget for a stale-cursor rejection. */
const CONTROL_RETRY_LIMIT = 2;
const CONTROL_RETRY_DELAY_MS = 40;

/** See `isSequenceConflict` in controller.ts (kept local so the headless
 * session path stays free of the full controller import): the surface transport
 * keeps only the kernel's message, and HTTP 409 is shared with non-retryable
 * conflicts. */
function isSequenceConflict(cause: unknown): boolean {
  const message = cause instanceof Error ? cause.message : String(cause);
  return (
    message.includes("SurfaceSequenceConflict") ||
    message.includes("does not match current sequence")
  );
}

function failureText(cause: unknown): string {
  const message = cause instanceof Error ? cause.message : String(cause);
  const status = cause instanceof SurfaceHttpError ? ` (HTTP ${cause.statusCode})` : "";
  return `${message}${status}`;
}

/**
 * Issue a control command (pause / resume / correction) with the event cursor
 * read from durable truth.
 *
 * `expected_event_sequence` is tracked per client instance and starts empty, so
 * a fresh `noem session ...` process sent `0` and the kernel answered
 * `expected event sequence 0 does not match current sequence N` (409) — the
 * emergency pause/correct from a shell could never take effect. The cursor must
 * therefore be refreshed first, and re-read before every resend: the refresh
 * and the command are two round trips, and the kernel appends durable events in
 * between, so even a correct refresh can be stale by the time the command
 * arrives.
 *
 * The idempotency key is minted once per invocation and reused across resends,
 * so a resend cannot apply the same operator command twice.
 */
async function sendControlCommand(
  client: SurfaceClient,
  sessionId: string,
  reason: string,
  action: "pause" | "resume" | "correction",
  idempotencyKey: string,
): Promise<{ status: string }> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= CONTROL_RETRY_LIMIT; attempt += 1) {
    await client.getSession(sessionId);
    try {
      return await client.correct(sessionId, reason, action, idempotencyKey);
    } catch (cause) {
      lastError = cause;
      if (!isSequenceConflict(cause)) throw cause;
      if (attempt < CONTROL_RETRY_LIMIT) {
        await new Promise((resolve) => setTimeout(resolve, CONTROL_RETRY_DELAY_MS));
      }
    }
  }
  throw lastError;
}

/**
 * The operator's reason text: everything after the session id, minus the CLI's
 * own flags.
 *
 * The reason is durable evidence (`CORRECTION_WRITTEN.reason`), and the flags
 * are not. Measured 2026-09-18: `noem session correct <id> "why" --descriptor
 * /tmp/x.json` recorded the reason as `why --descriptor /tmp/x.json`, and
 * `noem session pause <id> --descriptor /tmp/x.json` lost the default reason to
 * the flag text entirely.
 */
function reasonFrom(args: readonly string[]): string {
  const kept: string[] = [];
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index] as string;
    if (arg === "--descriptor") {
      index += 1; // the flag and its value are transport, never a reason
      continue;
    }
    kept.push(arg);
  }
  return kept.join(" ").trim();
}

export async function runSessionCommand(
  options: SessionCommandOptions,
): Promise<number> {
  const sub = (options.args[0] ?? "show").toLowerCase();
  const sessionId = options.args[1];
  const reason = reasonFrom(options.args.slice(2));
  if (!SUBCOMMANDS.has(sub)) {
    process.stderr.write(
      `noem: unknown session subcommand ${sub} (show | pause | resume | correct)\n`,
    );
    return 1;
  }
  if (!sessionId) {
    process.stderr.write(
      `usage: noem session ${sub} <session-id>${sub === "show" ? "" : " [reason]"}\n`,
    );
    return 1;
  }
  try {
    const descriptor = await loadRuntimeDescriptor(options.descriptorPath);
    const client = new SurfaceClient(descriptor);
    if (sub === "show") {
      const snapshot = await client.getSession(sessionId);
      process.stdout.write(
        `${JSON.stringify(
          {
            session_id: snapshot.session.session_id,
            status: snapshot.status,
            event_sequence: snapshot.event_sequence,
            message_count: snapshot.message_count,
          },
          null,
          2,
        )}\n`,
      );
      return 0;
    }
    const action = (
      sub === "correct" ? "correction" : sub
    ) as "pause" | "resume" | "correction";
    const snapshot = await sendControlCommand(
      client,
      sessionId,
      reason || (sub === "pause" ? "paused by user" : sub === "resume" ? "resumed by user" : "operator correction"),
      action,
      `cli-ts-session-${action}:${sessionId}:${Date.now()}`,
    );
    process.stdout.write(
      `${JSON.stringify({ session_id: sessionId, status: snapshot.status }, null, 2)}\n`,
    );
    // A resume that leaves the session unusable is not a success. Measured
    // 2026-09-18 on a real daemon: `noem session resume` against a
    // CORRECTION_HALTED session answered 200 with `{"status":
    // "CORRECTION_HALTED"}` and exit 0, while every later turn was refused by
    // the kernel — an exit-0 for an operation that changed nothing the operator
    // can use.
    if (action === "resume" && snapshot.status !== "ACTIVE") {
      process.stderr.write(
        `noem session resume: the kernel still reports ${snapshot.status} — this session cannot accept turns. ` +
          (snapshot.status === "CORRECTION_HALTED"
            ? "A correction halts the task and voids its sealed configuration; no terminal command restores it (start a new session).\n"
            : "The Run is not runnable (resume the correction or the pause first).\n"),
      );
      return 1;
    }
    return 0;
  } catch (cause) {
    // Non-zero exit and the reason on stderr: an operator scripting an emergency
    // pause must be able to tell "the kernel did not take it" from success.
    process.stderr.write(
      `noem session ${sub}: ${failureText(cause)} — the ${sub} was NOT applied to ${sessionId}\n`,
    );
    return 1;
  }
}
