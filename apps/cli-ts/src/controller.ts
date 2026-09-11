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

export interface ToolCall {
  actionId: string;
  capabilityId: string;
  argsSummary: string;
  /** Full arguments as received — projections (todo panel) parse from this,
   * never from the truncated summary. */
  argsJson: string;
  status: "pending" | "done" | "failed";
}

export interface TodoItem {
  id: string;
  content: string;
  status: "pending" | "in_progress" | "done";
}

/** Capability whose latest successful call defines the visible task list
 * (GC-SESSION-TODO-WRITE-2026-09-11; tier-1 internal scratchpad, pending
 * gate — the projection is inert until the capability exists). */
export const TODO_CAPABILITY = "session.todo_write";

/** Defensive parse of a todo_write arguments payload. Returns null on any
 * shape violation — a malformed list renders as no panel, never guessed. */
export function parseTodoItems(argsJson: string): TodoItem[] | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(argsJson);
  } catch {
    return null;
  }
  const todos = (parsed as { todos?: unknown } | null)?.todos;
  if (!Array.isArray(todos)) return null;
  const items: TodoItem[] = [];
  for (const raw of todos) {
    const todo = raw as { id?: unknown; content?: unknown; status?: unknown };
    if (typeof todo?.content !== "string" || !todo.content) return null;
    if (todo.status !== "pending" && todo.status !== "in_progress" && todo.status !== "done") {
      return null;
    }
    items.push({
      id: typeof todo.id === "string" && todo.id ? todo.id : `todo-${items.length + 1}`,
      content: todo.content,
      status: todo.status,
    });
  }
  return items;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  interrupted?: boolean;
  tool?: ToolCall;
}

/** One-line argument preview for a tool card (path/command first). */
export function summarizeArgs(argumentsJson: string): string {
  let args: Record<string, unknown>;
  try {
    args = JSON.parse(argumentsJson) as Record<string, unknown>;
  } catch {
    return "(unparseable arguments)";
  }
  for (const key of ["path", "command", "pattern", "query", "url"]) {
    const value = args[key];
    if (typeof value === "string" && value) {
      return value.length > 72 ? `${value.slice(0, 72)}…` : value;
    }
  }
  const first = Object.values(args).find((value) => typeof value === "string");
  if (typeof first === "string") {
    return first.length > 72 ? `${first.slice(0, 72)}…` : first;
  }
  return JSON.stringify(args).slice(0, 72);
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
  "/files [PREFIX]      workspace files (bounded read-only listing; optional path filter)",
  "/task                task overview: run status, receipts, outcome binding",
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
  /** Leading messages that will never change again — safe for Ink <Static>.
   * The cursor counts MESSAGES, never physical wrapped rows (M2 lesson). */
  finalizedIndex = 0;
  mode: PermissionMode = "ASK";
  tokensTotal = 0;
  turns = 0;
  pendingPreview: string | null = null;
  /** stop_reason of the most recent completed turn, verbatim from the
   * durable SESSION_TURN_COMPLETED payload ("completed" on success). */
  lastStopReason: string | null = null;
  lastError: string | null = null;

  private sessionId: string | null = null;
  private taskId: string | null = null;
  private snapshot: SurfaceSessionSnapshot | null = null;
  private stream: SurfaceStreamBinding | null = null;
  private turnId: string | null = null;
  private durableCursor = 0;
  private lastActivity: number | null = null;
  private readonly toolIndex = new Map<string, number>();
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

  /** Latest non-failed todo_write list (full-replace semantics), newest card
   * wins; a failed call never overwrites the visible list. Null = no panel. */
  get todoPanel(): TodoItem[] | null {
    for (let i = this.messages.length - 1; i >= 0; i -= 1) {
      const tool = this.messages[i]?.tool;
      if (!tool || tool.capabilityId !== TODO_CAPABILITY || tool.status === "failed") continue;
      const items = parseTodoItems(tool.argsJson);
      if (items) return items;
    }
    return null;
  }

  private push(message: ChatMessage): void {
    // A new message finalizes every earlier message (they can never change).
    this.finalizedIndex = this.messages.length;
    this.messages.push(message);
    this.emit();
  }

  /** Everything on screen is final (turn resolved one way or another). */
  private finalizeAll(): void {
    this.finalizedIndex = this.messages.length;
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
      case "/files":
        await this.filesCommand(rest[0]);
        return true;
      case "/task":
        await this.taskCommand();
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

  /** Bounded workspace listing (server-side depth/noise bounded; client caps
   * the display at 30 entries and always reports the true total). */
  private async filesCommand(prefix: string | undefined): Promise<void> {
    if (!this.taskId) {
      this.push({ role: "system", content: "no session yet; send a message first" });
      return;
    }
    const files = await this.client.files(this.taskId);
    const filtered = prefix ? files.filter((f) => f.path.startsWith(prefix)) : files;
    const shown = filtered.slice(0, 30);
    this.push({
      role: "system",
      content:
        filtered.length === 0
          ? `no workspace files${prefix ? ` matching ${prefix}` : ""}`
          : `files (${filtered.length}${filtered.length > shown.length ? `, showing ${shown.length}` : ""}):\n` +
            shown.map((f) => `  ${f.path} (${f.size} B)`).join("\n"),
    });
  }

  private async taskCommand(): Promise<void> {
    if (!this.taskId) {
      this.push({ role: "system", content: "no session yet; send a message first" });
      return;
    }
    const overview = await this.client.overview(this.taskId);
    this.push({
      role: "system",
      content:
        `task ${overview.task_id} · status ${overview.task_status} · run ${overview.run_status}` +
        ` · receipts ${overview.receipt_count} · outcome ${overview.expected_outcome_id || "none"}`,
    });
  }

  private adoptSnapshot(snapshot: SurfaceSessionSnapshot): void {    this.snapshot = snapshot;
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
    this.lastStopReason = null;
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
        this.finalizeAll();
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
        this.lastStopReason = String(payload["stop_reason"] ?? "completed");
        if (this.lastStopReason !== "completed") {
          // Honest surfacing of frozen kernel stop reasons (max_steps /
          // budget_exceeded / loop_detected / provider_failure:* / …): the
          // turn is over, but not successfully — say so, verbatim.
          const steps = Number(payload["steps"] ?? 0);
          this.push({
            role: "system",
            content: `turn ended: ${this.lastStopReason} (${steps} steps, tokens counted) — not a successful completion`,
          });
        }
        this.status = "idle";
        this.turnId = null;
        this.finalizeAll();
      } else if (event.event_type === "SESSION_APPROVAL_PENDING") {
        // Turn-bound like completion: a replayed pending event from an
        // earlier resolved turn must never resurrect an approval state
        // (E2E flake root cause, iteration-9). Payloads without turn_id
        // (older kernels) are accepted for back-compat.
        if (typeof payload["turn_id"] === "string" && payload["turn_id"] !== this.turnId) continue;
        this.pendingPreview = String(payload["preview"] ?? "");
        this.status = "awaiting_approval";
        this.finalizeAll();
      } else if (event.event_type === "ACTION_PROPOSED") {
        this.applyToolProposed(payload);
      } else if (event.event_type === "ACTION_RECEIPT_RECORDED") {
        this.applyToolReceipt(payload);
      }
    }
  }

  /** Tool card projection from the durable event stream (read-only view of
   * ACTION_PROPOSED / ACTION_RECEIPT_RECORDED; no governance state here). */
  private applyToolProposed(payload: Record<string, unknown>): void {
    const action = payload["action"] as Record<string, unknown> | undefined;
    if (!action) return;
    const actionId = String(action["action_id"] ?? "");
    if (!actionId || this.toolIndex.has(actionId)) return;
    const argsJson = String(action["arguments_json"] ?? "{}");
    const tool: ToolCall = {
      actionId,
      capabilityId: String(action["capability_id"] ?? "unknown"),
      argsSummary: summarizeArgs(argsJson),
      argsJson,
      status: "pending",
    };
    this.toolIndex.set(actionId, this.messages.length);
    this.push({ role: "system", content: "", tool });
  }

  private applyToolReceipt(payload: Record<string, unknown>): void {
    const receipt = payload["receipt"] as Record<string, unknown> | undefined;
    const decision = payload["decision"] as Record<string, unknown> | undefined;
    const actionId = String(receipt?.["action_id"] ?? decision?.["action_id"] ?? "");
    const index = this.toolIndex.get(actionId);
    if (index === undefined) return;
    const message = this.messages[index];
    if (!message?.tool) return;
    const status = String(receipt?.["status"] ?? "");
    message.tool = {
      ...message.tool,
      status: status === "FAILED" || status === "CANCELLED" ? "failed" : "done",
    };
    this.emit();
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
    this.finalizeAll();
  }

  /** Ctrl-C semantics: correction during activity, close when idle. */
  async interrupt(): Promise<"corrected" | "closed"> {
    if (this.sessionId && (this.status === "streaming" || this.status === "stalled")) {
      await this.client.correct(this.sessionId, "operator interrupt (ctrl-c)");
      this.push({ role: "system", content: "correction issued (operator interrupt)" });
      this.status = "idle";
      this.finalizeAll();
      return "corrected";
    }
    this.status = "closed";
    this.emit();
    return "closed";
  }
}
