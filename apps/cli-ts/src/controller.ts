/**
 * Ink-free TUI controller — all interaction logic, zero rendering imports.
 * Mirrors apps/cli/tui_controller.py semantics (M2 frozen):
 *
 * - subscription-first, one in-flight turn (TURN_IN_PROGRESS is server-side;
 *   the controller never submits while a turn is uncommitted);
 * - transient frames are display state; the durable event stream is
 *   authoritative for turn completion (tokens) and approval pending;
 * - stall detection is a transient client state with a 30s default
 *   (STALL_DEFAULT_MS), never inferred completion;
 * - permission modes are operator-only; approvals are human-only;
 * - cost honesty (E3): tokens are exact; cost renders UNKNOWN (no pricing
 *   source exists on the wire).
 */

import type { SurfaceClient } from "./client.js";
import { SurfaceStreamStaleError } from "./client.js";
import type {
  PermissionMode,
  SurfaceSessionSnapshot,
  SurfaceStreamBinding,
  TaskEvent,
} from "./contracts.js";

export const STALL_DEFAULT_MS = 30_000;

export type ControllerStatus =
  | "idle"
  | "streaming"
  | "awaiting_approval"
  | "stalled"
  | "closed";

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  interrupted?: boolean;
}

export const MODE_ORDER: PermissionMode[] = [
  "ASK",
  "ACCEPT_READ_ONLY",
  "ACCEPT_IN_WORKSPACE",
];

const SLASH_HELP: readonly string[] = [
  "/exit                quit (Ctrl-C during a turn issues a correction first)",
  "/status              session id, status, permission mode, event sequence",
  "/cost                exact token totals; cost is UNKNOWN (no pricing source)",
  "/mode [MODE]         show or set permission mode (ASK | ACCEPT_READ_ONLY | ACCEPT_IN_WORKSPACE)",
  "/resume <session-id> attach to an existing durable session",
  "/help                this list",
];

export interface ControllerDeps {
  clock?: () => number;
  stallMs?: number;
  pollMs?: number;
}

export class TuiController {
  status: ControllerStatus = "idle";
  readonly messages: ChatMessage[] = [];
  mode: PermissionMode = "ASK";
  tokensTotal = 0;
  turns = 0;
  pendingPreview: string | null = null;
  lastError: string | null = null;

  private sessionId: string | null = null;
  private taskId: string | null = null;
  private snapshot: SurfaceSessionSnapshot | null = null;
  private stream: SurfaceStreamBinding | null = null;
  private turnId: string | null = null;
  private durableCursor = 0;
  private lastActivity: number | null = null;
  private readonly listeners = new Set<() => void>();
  private readonly clock: () => number;
  private readonly stallMs: number;
  private readonly pollMs: number;
  private busy = false;

  constructor(
    private readonly client: SurfaceClient,
    deps: ControllerDeps = {},
  ) {
    this.clock = deps.clock ?? (() => Date.now());
    this.stallMs = deps.stallMs ?? STALL_DEFAULT_MS;
    this.pollMs = deps.pollMs ?? 100;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }

  get currentSnapshot(): SurfaceSessionSnapshot | null {
    return this.snapshot;
  }

  get currentSessionId(): string | null {
    return this.sessionId;
  }

  private push(message: ChatMessage): void {
    this.messages.push(message);
    this.emit();
  }

  private appendAssistant(delta: string): void {
    const last = this.messages[this.messages.length - 1];
    if (last && last.role === "assistant") {
      last.content += delta;
    } else {
      this.messages.push({ role: "assistant", content: delta });
    }
    this.emit();
  }

  /** Slash dispatch. Returns true when input was a command (handled). */
  async submit(input: string): Promise<boolean> {
    const text = input.trim();
    if (!text) return true;
    if (!text.startsWith("/")) {
      await this.runTurn(text);
      return true;
    }
    const [command, ...rest] = text.split(/\s+/);
    switch (command) {
      case "/exit":
        this.status = "closed";
        this.emit();
        return true;
      case "/help":
        for (const line of SLASH_HELP) this.push({ role: "system", content: line });
        return true;
      case "/status":
        this.push({ role: "system", content: this.statusLine() });
        return true;
      case "/cost":
        this.push({
          role: "system",
          content: `tokens ${this.tokensTotal} (exact) · cost UNKNOWN (no pricing source) · turns ${this.turns}`,
        });
        return true;
      case "/mode":
        await this.modeCommand(rest[0]);
        return true;
      case "/resume":
        await this.resumeCommand(rest[0]);
        return true;
      default:
        this.push({ role: "system", content: `unknown command: ${command} (see /help)` });
        return true;
    }
  }

  private statusLine(): string {
    const id = this.sessionId ?? "none";
    const events = this.snapshot?.event_sequence ?? 0;
    return `session ${id} · status ${this.status} · mode ${this.mode} · events ${events} · turns ${this.turns}`;
  }

  private async modeCommand(arg: string | undefined): Promise<void> {
    if (arg) {
      const mode = arg.toUpperCase();
      if (!(MODE_ORDER as string[]).includes(mode)) {
        this.push({ role: "system", content: `invalid mode ${arg}; expected ${MODE_ORDER.join(" | ")}` });
        return;
      }
    }
    if (!this.sessionId) {
      this.push({ role: "system", content: "no session yet; send a message first" });
      return;
    }
    if (!arg) {
      this.push({ role: "system", content: `permission mode: ${this.mode}` });
      return;
    }
    const mode = arg.toUpperCase() as PermissionMode;
    // Refresh the tracked event sequence first: durable progress learned via
    // events() does not advance the client's per-session command cursor.
    const fresh = await this.client.getSession(this.sessionId);
    this.mode = fresh.permission_mode;
    const updated = await this.client.setPermissionMode(this.sessionId, mode as PermissionMode);
    this.mode = updated.permission_mode;
    this.snapshot = updated;
    this.push({ role: "system", content: `permission mode → ${this.mode}` });
  }

  private async resumeCommand(arg: string | undefined): Promise<void> {
    if (!arg) {
      this.push({ role: "system", content: "usage: /resume <session-id>" });
      return;
    }
    if (this.busy) {
      this.push({ role: "system", content: "turn in progress; cannot resume now" });
      return;
    }
    const snapshot = await this.client.getSession(arg);
    this.adoptSnapshot(snapshot);
    this.push({
      role: "system",
      content: `resumed session ${snapshot.session.session_id} (status ${snapshot.status}, mode ${snapshot.permission_mode})`,
    });
  }

  private adoptSnapshot(snapshot: SurfaceSessionSnapshot): void {
    this.snapshot = snapshot;
    this.sessionId = snapshot.session.session_id;
    this.taskId = snapshot.session.task_id;
    this.mode = snapshot.permission_mode;
    this.stream = null;
    this.emit();
  }

  async runTurn(text: string): Promise<void> {
    if (this.busy) {
      this.push({ role: "system", content: "turn in progress; input is not queued (frozen TURN_IN_PROGRESS semantics)" });
      return;
    }
    this.busy = true;
    this.lastError = null;
    try {
      if (!this.sessionId) {
        const opened = await this.client.openSession("cli-ts session");
        this.adoptSnapshot(opened);
        this.push({ role: "system", content: `session ${this.sessionId} opened` });
      }
      const sessionId = this.sessionId!;
      if (!this.stream) {
        const subscription = await this.client.subscribeStream(sessionId);
        this.stream = {
          runtime_boot_id: subscription.runtime_boot_id,
          stream_id: subscription.stream_id,
        };
      }
      const binding = this.stream;
      this.push({ role: "user", content: text });
      this.status = "streaming";
      this.lastActivity = this.clock();
      this.emit();

      const begin = await this.client.beginTurn(sessionId, text, binding);
      this.turnId = begin.turn_id;

      for await (const frame of this.client.followStream(sessionId, binding, { pollMs: this.pollMs })) {
        this.lastActivity = this.clock();
        if (frame.kind === "CHUNK") {
          this.appendAssistant((frame.payload as { delta?: string }).delta ?? "");
        } else if (frame.kind === "GAP") {
          const last = this.messages[this.messages.length - 1];
          if (last && last.role === "assistant") last.interrupted = true;
          this.push({
            role: "system",
            content: `[gap: frames ${frame.gap_from}–${frame.gap_to} lost; content not fabricated]`,
          });
        }
        // STREAM_END is transient; the durable turn commit finalizes below.
        this.drainDurable();
      }
      await this.awaitDurableResolution(sessionId);
    } catch (cause) {
      if (cause instanceof SurfaceStreamStaleError) {
        this.stream = null;
        this.lastError = "stream generation stale; resubscribed on next turn";
        if (this.sessionId) {
          this.adoptSnapshot(await this.client.getSession(this.sessionId));
        }
        this.status = "idle";
      } else {
        this.lastError = (cause as Error).message;
        this.status = "idle";
      }
      this.emit();
    } finally {
      this.busy = false;
    }
  }

  /** After STREAM_END the durable record is authoritative: wait for the
   * turn-completed or approval-pending event; on silence past the stall
   * threshold render the single typed stalled state (never inferred
   * completion). */
  private async awaitDurableResolution(sessionId: string): Promise<void> {
    const deadline = this.clock() + this.stallMs;
    for (;;) {
      this.drainDurable();
      if (this.status === "idle" || this.status === "awaiting_approval") return;
      if (this.clock() > deadline) {
        this.status = "stalled"; // transient; only durable state may overrule
        this.emit();
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, this.pollMs));
      // Refresh snapshot so approval pending is visible even if the event
      // drain ordering raced the snapshot projection.
      this.snapshot = await this.client.getSession(sessionId);
      if (this.snapshot.status === "WAITING_APPROVAL") {
        this.status = "awaiting_approval";
        this.pendingPreview = this.snapshot.pending_approval?.preview ?? null;
        this.emit();
        return;
      }
      if (this.snapshot.status === "ACTIVE" && this.turnId === null) {
        this.status = "idle";
        this.emit();
        return;
      }
    }
  }

  private drainDurable(): void {
    if (!this.taskId) return;
    // events() is sync-looking here for simplicity of the state machine:
    // the async fetch is fire-and-forget; results apply on the next tick.
    void this.client
      .events(this.taskId, this.durableCursor)
      .then((batch) => this.applyDurable(batch.next_sequence, batch.events))
      .catch(() => undefined);
  }

  private applyDurable(nextSequence: number, events: readonly TaskEvent[]): void {
    this.durableCursor = nextSequence;
    for (const event of events) {
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(event.payload_json) as Record<string, unknown>;
      } catch {
        continue;
      }
      if (event.event_type === "SESSION_TURN_COMPLETED") {
        if (payload["turn_id"] !== this.turnId) continue;
        this.tokensTotal += Number(payload["total_tokens"] ?? 0);
        this.turns += 1;
        this.status = "idle";
        this.turnId = null;
        this.emit();
      } else if (event.event_type === "SESSION_APPROVAL_PENDING") {
        this.pendingPreview = String(payload["preview"] ?? "");
        this.status = "awaiting_approval";
        this.emit();
      }
    }
  }

  /** Stall detection while streaming: quiet stream beyond the threshold. */
  tick(): void {
    if (this.status !== "streaming" || this.lastActivity === null) return;
    if (this.clock() - this.lastActivity > this.stallMs) {
      this.status = "stalled";
      this.emit();
    }
  }

  async approve(): Promise<void> {
    await this.decide("APPROVE");
  }

  async reject(): Promise<void> {
    await this.decide("REJECT");
  }

  private async decide(disposition: "APPROVE" | "REJECT"): Promise<void> {
    if (this.status !== "awaiting_approval") throw new Error("no pending approval");
    if (!this.sessionId) throw new Error("no session");
    const snapshot = await this.client.getSession(this.sessionId);
    const pending = snapshot.pending_approval;
    if (!pending) throw new Error("pending approval vanished");
    const turn = await this.client.decideApproval(
      this.sessionId,
      pending.action_digest,
      disposition,
      `${disposition.toLowerCase()} via cli-ts`,
    );
    this.snapshot = turn.snapshot;
    this.push({ role: "system", content: `${disposition}: ${pending.capability_id}` });
    if (turn.text.trim()) this.push({ role: "assistant", content: turn.text });
    if (turn.total_tokens > 0) this.tokensTotal += turn.total_tokens;
    this.status = "idle";
    this.pendingPreview = null;
    this.emit();
  }

  /** Ctrl-C semantics: correction during activity, close when idle. */
  async interrupt(): Promise<"corrected" | "closed"> {
    if (this.sessionId && (this.status === "streaming" || this.status === "stalled")) {
      await this.client.correct(this.sessionId, "operator interrupt (ctrl-c)");
      this.push({ role: "system", content: "correction issued (operator interrupt)" });
      this.status = "idle";
      this.emit();
      return "corrected";
    }
    this.status = "closed";
    this.emit();
    return "closed";
  }
}
