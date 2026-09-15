/**
 * Headless session administration (`noem session ...`), mirroring the
 * former Python `session-show` / `session-pause` / `session-resume` /
 * `session-correct` subcommands. Read/control only; durable truth stays in the
 * task event stream.
 */
import { SurfaceClient } from "./client.js";
import { loadRuntimeDescriptor } from "./descriptor.js";

export interface SessionCommandOptions {
  descriptorPath?: string | undefined;
  args: string[];
}

const SUBCOMMANDS = new Set(["show", "pause", "resume", "correct"]);

export async function runSessionCommand(
  options: SessionCommandOptions,
): Promise<number> {
  const sub = (options.args[0] ?? "show").toLowerCase();
  const sessionId = options.args[1];
  const reason = options.args.slice(2).join(" ").trim();
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
    const snapshot = await client.correct(
      sessionId,
      reason || (sub === "pause" ? "paused by user" : sub === "resume" ? "resumed by user" : "operator correction"),
      action,
    );
    process.stdout.write(
      `${JSON.stringify({ session_id: sessionId, status: snapshot.status }, null, 2)}\n`,
    );
    return 0;
  } catch (cause) {
    process.stderr.write(`noem session: ${(cause as Error).message}\n`);
    return 1;
  }
}
