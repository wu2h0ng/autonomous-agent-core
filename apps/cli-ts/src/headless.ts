/**
 * Headless one-shot mode (`-p/--print`) — the non-interactive sibling of the
 * Ink TUI, reusing TuiController so every frozen semantic (durable completion
 * authority, fail-closed approvals, typed stall) applies unchanged.
 *
 * Frozen exit-code table (mainstream parity: claude -p / codex exec):
 *   0  turn completed
 *   1  transport / contract / general error
 *   2  turn ended awaiting approval (fail-closed: a human must decide in the TUI)
 *   3  turn ended without stop_reason "completed" (max_steps, budget_exceeded,
 *      loop_detected, provider_failure:*, stalled, …) — tokens still counted
 *
 * Output formats: text (assistant text on stdout, notices on stderr) and
 * json (single result object on stdout).
 */

import type { SurfaceClient } from "./client.js";
import { TuiController } from "./controller.js";

export const HEADLESS_EXIT = {
  OK: 0,
  ERROR: 1,
  APPROVAL_REQUIRED: 2,
  NOT_COMPLETED: 3,
} as const;

export type HeadlessOutputFormat = "text" | "json";

export interface HeadlessOptions {
  prompt: string;
  sessionId?: string | undefined;
  outputFormat?: HeadlessOutputFormat | undefined;
  /** Quiet-stream threshold before the typed stalled state; headless maps it
   * to exit 3 rather than waiting forever. Default 60s (TUI default is 30s). */
  stallMs?: number | undefined;
}

export interface HeadlessResult {
  type: "result";
  subtype: "success" | "approval_required" | "not_completed" | "error";
  session_id: string | null;
  text: string;
  stop_reason: string | null;
  total_tokens: number;
  is_error: boolean;
}

export async function runHeadless(
  client: SurfaceClient,
  options: HeadlessOptions,
  out: { stdout: (s: string) => void; stderr: (s: string) => void } = {
    stdout: (s) => process.stdout.write(s),
    stderr: (s) => process.stderr.write(s),
  },
): Promise<number> {
  const controller = new TuiController(client, {
    stallMs: options.stallMs ?? 60_000,
    pollMs: 100,
  });

  if (options.sessionId) {
    await controller.submit(`/resume ${options.sessionId}`);
  }

  const baseline = controller.messages.length;
  try {
    await controller.runTurn(options.prompt);
  } catch (cause) {
    return emit(result("error", controller, "", (cause as Error).message), 1, options, out);
  }

  const fresh = controller.messages.slice(baseline);
  const text = fresh
    .filter((m) => m.role === "assistant")
    .map((m) => m.content)
    .join("");
  // Turn-scoped system notices (stop reason, gaps) go to stderr in text mode.
  for (const message of fresh.filter((m) => m.role === "system")) {
    if (options.outputFormat !== "json") out.stderr(`⏵ ${message.content}\n`);
  }

  if (controller.status === "awaiting_approval") {
    // The durable event path returns before a snapshot refresh; fetch the
    // pending approval explicitly so the reason names the real capability.
    const fresh3 = controller.currentSessionId
      ? await client.getSession(controller.currentSessionId)
      : null;
    const capability =
      fresh3?.pending_approval?.capability_id ??
      controller.currentSnapshot?.pending_approval?.capability_id ??
      "unknown";
    return emit(
      result("approval_required", controller, text, `approval required: ${capability}`),
      HEADLESS_EXIT.APPROVAL_REQUIRED,
      options,
      out,
    );
  }
  if (controller.status === "stalled") {
    return emit(
      result("not_completed", controller, text, "stalled"),
      HEADLESS_EXIT.NOT_COMPLETED,
      options,
      out,
    );
  }
  if (controller.lastStopReason && controller.lastStopReason !== "completed") {
    return emit(
      result("not_completed", controller, text, controller.lastStopReason),
      HEADLESS_EXIT.NOT_COMPLETED,
      options,
      out,
    );
  }
  if (controller.lastError) {
    return emit(result("error", controller, text, controller.lastError), HEADLESS_EXIT.ERROR, options, out);
  }
  return emit(result("success", controller, text, "completed"), HEADLESS_EXIT.OK, options, out);
}

function result(
  subtype: HeadlessResult["subtype"],
  controller: TuiController,
  text: string,
  stopReason: string | null,
): HeadlessResult {
  return {
    type: "result",
    subtype,
    session_id: controller.currentSessionId,
    text,
    stop_reason: subtype === "success" ? "completed" : stopReason,
    total_tokens: controller.tokensTotal,
    is_error: subtype !== "success",
  };
}

function emit(
  payload: HeadlessResult,
  exitCode: number,
  options: HeadlessOptions,
  out: { stdout: (s: string) => void; stderr: (s: string) => void },
): number {
  if (options.outputFormat === "json") {
    out.stdout(`${JSON.stringify(payload)}\n`);
  } else {
    if (payload.text) out.stdout(payload.text.endsWith("\n") ? payload.text : `${payload.text}\n`);
    if (payload.is_error) out.stderr(`agent-os-ts: ${payload.subtype} (${payload.stop_reason ?? ""})\n`);
  }
  return exitCode;
}
