/**
 * Ink-free TUI controller — all interaction logic, zero rendering imports.
 * Mirrors the former Python TUI controller semantics (path B, deleted 2026-09-15):
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
import { helpLines } from "./commands.js";
import { diffLines } from "./diffview.js";
import { DEFAULT_THEME_NAME, nextTheme, THEMES, themeNames } from "./theme.js";
import { chmodSync, statSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import type {
  PermissionMode,
  ProviderMetricsSnapshot,
  SurfaceFileEntry,
  SurfaceSessionSnapshot,
  SurfaceStreamBinding,
  TaskEvent,
  TraceSpan,
  TurnTrace,
} from "./contracts.js";

export const STALL_DEFAULT_MS = 30_000;

/** Bounded refresh-and-resend budget for a command the kernel rejected with a
 * stale event cursor, and the pause between attempts. */
export const SEQUENCE_RETRY_LIMIT = 2;
export const SEQUENCE_RETRY_DELAY_MS = 40;

/**
 * True when the kernel rejected a command because the client's tracked
 * `expected_event_sequence` no longer matches durable truth
 * (`SurfaceSequenceConflict`, HTTP 409) — the one rejection a fresh read can
 * fix.
 *
 * Only this rejection is retryable. HTTP 409 is overloaded on the surface
 * (`surface_routes._surface_error_status` maps `SurfaceIdempotencyConflict` and
 * `InvalidTransitionError` to 409 too), and the transport keeps only the
 * message, so the match is on the kernel's frozen wording
 * (`surface_runtime._require_sequence`). Everything else surfaces unchanged.
 */
export function isSequenceConflict(cause: unknown): boolean {
  const message = cause instanceof Error ? cause.message : String(cause);
  return (
    message.includes("SurfaceSequenceConflict") ||
    message.includes("does not match current sequence")
  );
}

/** Kernel sentinel for "no error" (`agent_os_contracts.authority.NO_ERROR_CODE`).
 * Every receipt carries it; it must never render as an error. */
export const NO_ERROR_CODE = "error:none";

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
  /** Durable outcome summary (effect / error code / artifact count, plus the
   * tool-reported exit code and error), rendered on the tool card, in
   * `formatToolDetail` and in `/export`. */
  resultSummary?: string;
  /** Exit code the tool itself reported (durable `NODE_COMPLETED.output.
   * exit_code`, e.g. `workspace.run_tests`/`workspace.shell`). This is the
   * TOOL's result, not the dispatch's: a receipt `SUCCEEDED` with `exit_code 1`
   * means "the command ran and exited non-zero", and the card must not render
   * it as an unqualified success. */
  exitCode?: number;
  /** Error text the tool itself reported (`NODE_COMPLETED.output.error`). */
  errorText?: string;
}

/** Operator-facing state of a tool card: the receipt's dispatch status refined
 * by the tool's own result. The receipt keeps its own semantics — `failed` is
 * still exactly "the dispatch did not succeed" (`ReceiptStatus` FAILED /
 * CANCELLED / COMPENSATED); `error` is the extra case the receipt cannot
 * express, "confirmed dispatch, non-zero exit or tool-reported error". */
export function toolState(
  tool: ToolCall,
): "pending" | "done" | "failed" | "error" {
  if (tool.status === "failed") return "failed";
  if (tool.status !== "done") return "pending";
  if (tool.errorText !== undefined) return "error";
  return tool.exitCode !== undefined && tool.exitCode !== 0 ? "error" : "done";
}

export interface TodoItem {
  id: string;
  content: string;
  status: "pending" | "in_progress" | "done";
}

/** Overlay selector request: controller supplies items, App renders + routes. */
export interface PendingSelector {
  kind: "resume" | "theme" | "mode";
  title: string;
  items: string[];
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

export interface MessagePanel {
  title: string;
  lines: string[];
}

function formatMilliseconds(value: number | null | undefined): string {
  return value === null || value === undefined ? "n/a" : `${value.toFixed(1)}ms`;
}

/**
 * `/metrics` card: the aggregated provider boundary.
 *
 * Counts and codes only — the payload has no prompt or completion text, so
 * there is nothing here to redact. A window with no timed attempt says so
 * instead of printing a zero latency (`0.0ms` would be a made-up measurement).
 */
export function metricsPanel(metrics: ProviderMetricsSnapshot): MessagePanel {
  const lines = [
    `source   ${metrics.source} (${metrics.window_records} attempts in the window)`,
    `calls    ${metrics.calls} (${metrics.attempts} attempts, ${metrics.retries} retried)`,
    `outcome  ${metrics.responses} responses, ${metrics.failures} failures`,
  ];
  if (metrics.latency.samples > 0) {
    lines.push(
      `latency  p50 ${formatMilliseconds(metrics.latency.p50_ms)}  p90 ${formatMilliseconds(
        metrics.latency.p90_ms,
      )}  max ${formatMilliseconds(metrics.latency.max_ms)}`,
      `tokens   ${metrics.tokens.total_tokens} (in ${metrics.tokens.input_tokens} / out ${metrics.tokens.output_tokens})`,
    );
  } else {
    lines.push(
      "latency  no timed attempt in the window",
      `tokens   ${metrics.tokens.total_tokens} (no usage reported yet)`,
    );
  }
  const rate = metrics.rate_limit;
  lines.push(
    `rate     server 429s ${rate.rate_limited_attempts}` +
      (rate.max_retry_after_seconds === null || rate.max_retry_after_seconds === undefined
        ? ""
        : ` (max Retry-After ${rate.max_retry_after_seconds}s)`) +
      `; local waits ${rate.local_waits} (${rate.local_wait_ms_total.toFixed(0)}ms); local refusals ${rate.local_rejections}`,
  );
  for (const category of metrics.failure_categories) {
    lines.push(`failure  ${category.code} x${category.count}`);
  }
  if (metrics.window_truncated) {
    lines.push("window   truncated: older attempts were dropped from the window");
  }
  if ((metrics.ignored_lines ?? 0) > 0) {
    lines.push(`window   ${metrics.ignored_lines} unusable log line(s) ignored`);
  }
  return { title: "provider metrics", lines };
}

/** How many span/gap rows a trace card prints before it says how many it left
 * out. A panel is not a dump: the full record is the trace route's JSON. */
const MAX_TRACE_ROWS = 40;

/** The durable id that identifies a span to an operator, never its content. */
function traceSpanSubject(span: TraceSpan): string {
  const parts: string[] = [];
  if (span.capability_id) parts.push(span.capability_id);
  else if (span.node_id) parts.push(span.node_id);
  if (span.verdict) parts.push(span.verdict);
  if (span.disposition) parts.push(span.disposition);
  if (span.effect_state) parts.push(span.effect_state);
  if (span.basis) parts.push(`basis=${span.basis}`);
  if (span.link === "SEQUENCE_WINDOW") parts.push("(positional)");
  return parts.length > 0 ? `  ${parts.join(" ")}` : "";
}

/**
 * `/trace` card: the durable event log of one turn, as spans.
 *
 * Structure and causation only — the projection carries no prompt, completion,
 * argument payload or approval preview, so there is nothing to redact here. An
 * `OPEN` state and every gap are rendered as such: a turn the log never closed,
 * a dispatch with no terminal record and an undetermined effect must read as
 * missing evidence, never as a complete-looking timeline.
 */
export function tracePanel(trace: TurnTrace): MessagePanel {
  const lines = [
    `turn     ${trace.turn_id}  ${trace.state}`,
    `stop     ${trace.stop_reason ?? "unknown (no SESSION_TURN_COMPLETED in the log)"}`,
    `window   records ${trace.first_sequence}..${trace.last_sequence} (${trace.records_scanned} scanned, ${trace.spans.length} span(s), ${trace.gaps.length} gap(s))`,
  ];
  const positional = trace.spans.filter((span) => span.link === "SEQUENCE_WINDOW").length;
  for (const span of trace.spans.slice(0, MAX_TRACE_ROWS)) {
    lines.push(
      `span     #${span.started_sequence} ${span.kind} ${span.status}${traceSpanSubject(span)}`,
    );
  }
  if (trace.spans.length > MAX_TRACE_ROWS) {
    lines.push(
      `span     … ${trace.spans.length - MAX_TRACE_ROWS} more span(s) not shown (the trace route returns the full projection)`,
    );
  }
  for (const gap of trace.gaps.slice(0, MAX_TRACE_ROWS)) {
    const anchor = gap.sequence === null || gap.sequence === undefined ? "" : ` @${gap.sequence}`;
    lines.push(
      `gap      ${gap.kind}${anchor}  ${gap.detail}` +
        (gap.subject === null || gap.subject === undefined ? "" : ` [${gap.subject}]`),
    );
  }
  if (trace.gaps.length > MAX_TRACE_ROWS) {
    lines.push(`gap      … ${trace.gaps.length - MAX_TRACE_ROWS} more gap(s) not shown`);
  }
  if (positional > 0) {
    lines.push(
      `note     ${positional} span(s) placed by sequence window only: no durable id joins them to this turn`,
    );
  }
  return { title: "turn trace", lines };
}

export interface SearchHit {
  index: number;
  text: string;
}

/** Case-insensitive transcript search over message text, panels and tools. */
export function searchMessages(messages: readonly ChatMessage[], query: string): SearchHit[] {
  const needle = query.toLowerCase();
  if (!needle) return [];
  const hits: SearchHit[] = [];
  messages.forEach((message, position) => {
    const haystack = [
      message.content,
      message.panel ? [message.panel.title, ...message.panel.lines].join("\n") : "",
      message.tool
        ? `${message.tool.capabilityId} ${message.tool.argsSummary} ${message.tool.resultSummary ?? ""}`
        : "",
    ].join("\n");
    if (!haystack.toLowerCase().includes(needle)) return;
    const line = haystack.split("\n").find((entry) => entry.toLowerCase().includes(needle)) ?? haystack;
    hits.push({ index: position + 1, text: line.length > 80 ? `${line.slice(0, 80)}…` : line });
  });
  return hits;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  interrupted?: boolean;
  tool?: ToolCall;
  /** Optional bordered card rendered instead of an inline text line. */
  panel?: MessagePanel;
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

/** Diff lines for an edit-style tool call (old_string/new_string present). */
function toolDiff(argsJson: string): string[] | null {
  let args: Record<string, unknown>;
  try {
    args = JSON.parse(argsJson) as Record<string, unknown>;
  } catch {
    return null;
  }
  const oldText = args["old_string"];
  const newText = args["new_string"];
  if (typeof oldText !== "string" || typeof newText !== "string") return null;
  return diffLines(oldText, newText).map((line) => {
    const marker = line.kind === "del" ? "-" : line.kind === "add" ? "+" : " ";
    return `  ${marker} ${line.text}`;
  });
}

/** Multi-line detail block for one tool call: action, status, durable result,
 * pretty-printed arguments and an inline diff for edit-style calls. Never
 * throws on malformed arguments — the raw JSON is shown verbatim instead.
 *
 * NOTE (S1 audit 2026-09-18): no view calls this yet — the Ctrl-O panel was
 * never wired, and the `/keys` card no longer advertises a binding for it. */
export function formatToolDetail(tool: ToolCall): string[] {
  let pretty = tool.argsJson;
  try {
    pretty = JSON.stringify(JSON.parse(tool.argsJson), null, 2);
  } catch {
    // keep raw
  }
  const lines = [
    `action   ${tool.actionId}`,
    `status   ${tool.status}`,
    `state    ${toolState(tool)}`,
  ];
  if (tool.resultSummary) lines.push(`result   ${tool.resultSummary}`);
  lines.push(...pretty.split("\n").map((line) => `  ${line}`));
  const diff = toolDiff(tool.argsJson);
  if (diff) lines.push("diff", ...diff);
  return lines;
}

export const MODE_ORDER: PermissionMode[] = [
  "ASK",
  "ACCEPT_READ_ONLY",
  "ACCEPT_IN_WORKSPACE",
];

/** Render the in-session transcript to Markdown (for `/export`). */
export function renderTranscript(
  messages: readonly ChatMessage[],
  meta: { sessionId: string | null; mode: string; tokens: number; goal: string | null },
): string {
  const lines = [
    "# Agent OS transcript",
    "",
    `session: ${meta.sessionId ?? "none"}`,
    `mode: ${meta.mode}`,
    `tokens: ${meta.tokens} (exact)`,
    `cost: UNKNOWN (no pricing source)`,
    `goal: ${meta.goal ?? "none"}`,
    "",
    "---",
    "",
  ];
  for (const message of messages) {
    if (message.panel) {
      lines.push(`## ${message.panel.title}`, ...message.panel.lines, "");
      continue;
    }
    if (message.tool) {
      const result = message.tool.resultSummary ? ` — ${message.tool.resultSummary}` : "";
      lines.push(`- tool [${toolState(message.tool)}] ${message.tool.capabilityId} (${message.tool.argsSummary})${result}`, "");
      continue;
    }
    lines.push(`**${message.role}**: ${message.content}`, "");
  }
  return lines.join("\n");
}

export interface ControllerDeps {
  clock?: () => number;
  stallMs?: number;
  pollMs?: number;
  /** Pause between refresh-and-resend attempts after a stale-cursor rejection. */
  sequenceRetryDelayMs?: number;
  /** Observer for streamed assistant deltas (headless stream-json). Pure
   * notification — never feeds back into controller state. */
  onDelta?: (delta: string) => void;
  /** Read-only self-check reporter for the in-TUI `/doctor` command. */
  doctor?: () => Promise<string>;
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
  /** Persistent session objective (Codex-style `/goal`). Client-scoped: while
   * set it is prefixed onto every outgoing turn as an explicit context block
   * and rendered in the footer, so the effect is never silent. */
  goal: string | null = null;
  /** Active render theme (operator-only `/theme`). */
  themeName: string = DEFAULT_THEME_NAME;
  /** Vim keymap toggle (`/vim`; operator-only, persisted locally). */
  vimMode = false;
  /** Open overlay selector, if any (mainstream `/resume` `/theme` `/mode`). */
  pendingSelector: PendingSelector | null = null;
  /** Locally observed session ids, most-recent first (no sessions-list
   * endpoint exists yet, so `/resume` can only offer what this client saw). */
  recentSessions: string[] = [];
  /** Last operator message submitted as a turn (for `/retry` and `/edit`).
   * Client-side only; never a message-level rollback (M2 non-target). */
  lastUserText: string | null = null;
  /** Set by `/edit`; App moves it into the composer and clears it. */
  private pendingComposerText: string | null = null;
  /** Client-side pre-submit queue (D2 adjudication 2026-09-11: steering must
   * be a "next turn" queue, never a change to frozen TURN_IN_PROGRESS). One
   * turn is still in flight at a time; queued messages run on resolution. */
  private readonly queue: string[] = [];
  /** Last turn's transient provider reasoning (display-only; never durable,
   * never part of the assistant message). Reset at the start of each turn. */
  reasoningText = "";
  lastError: string | null = null;

  private sessionId: string | null = null;
  private taskId: string | null = null;
  private snapshot: SurfaceSessionSnapshot | null = null;
  private filesCache: SurfaceFileEntry[] | null = null;
  private stream: SurfaceStreamBinding | null = null;
  private turnId: string | null = null;
  private durableCursor = 0;
  /** Why the last durable drain failed, cleared by the next good batch. */
  private lastDurableError: string | null = null;
  private lastActivity: number | null = null;
  private readonly toolIndex = new Map<string, number>();
  /** Message index by proposed action node id — the fallback key for
   * NODE_COMPLETED payloads that carry no action_id. */
  private readonly nodeIndex = new Map<string, number>();
  private readonly listeners = new Set<() => void>();
  private readonly clock: () => number;
  private readonly stallMs: number;
  private readonly pollMs: number;
  private readonly onDelta: ((delta: string) => void) | undefined;
  private readonly doctor: (() => Promise<string>) | undefined;
  private readonly sequenceRetryDelayMs: number;
  /** The correction currently being sent, if any. Esc is a physical key: a
   * held or repeated press must not fan out into one POST per key event. */
  private interruptInFlight: Promise<"corrected" | "closed"> | null = null;
  private busy = false;

  constructor(
    private readonly client: SurfaceClient,
    deps: ControllerDeps = {},
  ) {
    this.clock = deps.clock ?? (() => Date.now());
    this.stallMs = deps.stallMs ?? STALL_DEFAULT_MS;
    this.pollMs = deps.pollMs ?? 100;
    this.onDelta = deps.onDelta;
    this.doctor = deps.doctor;
    this.sequenceRetryDelayMs = deps.sequenceRetryDelayMs ?? SEQUENCE_RETRY_DELAY_MS;
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

  get queuedCount(): number {
    return this.queue.length;
  }

  /** Snapshot of queued messages (for `/queue`). */
  get queuedMessages(): readonly string[] {
    return this.queue;
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
    this.onDelta?.(delta);
    this.emit();
  }

  /** Slash dispatch. Returns true when input was a command (handled). */
  async submit(input: string): Promise<boolean> {
    const text = input.trim();
    if (!text) return true;
    if (!text.startsWith("/")) {
      await this.enqueueOrRun(text);
      return true;
    }
    const [command, ...rest] = text.split(/\s+/);
    switch (command) {
      case "/exit":
        this.status = "closed";
        this.emit();
        return true;
      case "/help":
        for (const line of helpLines()) this.push({ role: "system", content: line });
        return true;
      case "/status":
        this.push({ role: "system", content: "", panel: this.statusPanel() });
        return true;
      case "/cost":
        this.push({ role: "system", content: "", panel: this.costPanel() });
        return true;
      case "/metrics":
        await this.metricsCommand(rest);
        return true;
      case "/trace":
        await this.traceCommand(rest);
        return true;
      case "/provider":
        await this.providerCommand(rest);
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
      case "/goal":
        this.goalCommand(rest.join(" ").trim());
        return true;
      case "/theme":
        this.themeCommand(rest[0]);
        return true;
      case "/vim":
        this.vimMode = !this.vimMode;
        this.push({
          role: "system",
          content: `vim keymap ${this.vimMode ? "on (Esc → normal, i/a to insert)" : "off"}`,
        });
        this.emit();
        return true;
      case "/queue":
        this.queueCommand(rest[0]);
        return true;
      case "/doctor":
        await this.doctorCommand();
        return true;
      case "/retry":
        await this.retryCommand();
        return true;
      case "/find":
        this.findCommand(rest.join(" ").trim());
        return true;
      case "/keys":
        this.push({ role: "system", content: "", panel: this.keysPanel() });
        return true;
      case "/export":
        this.exportCommand(rest.join(" ").trim() || undefined);
        return true;
      case "/edit":
        this.editCommand();
        return true;
      case "/clear":
        this.clearView();
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

  /** `/status` card. */
  private statusPanel(): MessagePanel {
    return {
      title: "session status",
      lines: [
        `session  ${this.sessionId ?? "none"}`,
        `status   ${this.status}`,
        `mode     ${this.mode}`,
        `events   ${this.snapshot?.event_sequence ?? 0}`,
        `turns    ${this.turns}`,
      ],
    };
  }

  /** `/metrics` — the aggregated provider boundary (read-only). `log` reads the
   * operator's own provider log on the daemon (AGENT_OS_PROVIDER_LOG) instead of
   * the running process's window; an unavailable source is reported as such
   * rather than rendered as an empty panel. */
  private async metricsCommand(rest: string[]): Promise<void> {
    const source = (rest[0] ?? "process").toLowerCase();
    if (source !== "process" && source !== "log") {
      this.push({ role: "system", content: "usage: /metrics [process|log]" });
      return;
    }
    try {
      const metrics = await this.client.providerMetrics(source);
      this.push({ role: "system", content: "", panel: metricsPanel(metrics) });
    } catch (error) {
      this.push({
        role: "system",
        content: `metrics unavailable: ${(error as Error).message}`,
      });
    }
  }

  /** `/trace` — the durable record of one turn, as spans (read-only).
   *
   * Without an argument it traces the session's most recently started turn, so
   * "what did the turn that just ran actually do" needs no id. An unknown turn
   * is reported as unavailable rather than rendered as an empty timeline. */
  private async traceCommand(rest: string[]): Promise<void> {
    if (!this.sessionId) {
      this.push({ role: "system", content: "no session: /trace needs an open session" });
      return;
    }
    const turnId = rest[0];
    try {
      const trace = await this.client.turnTrace(this.sessionId, turnId);
      this.push({ role: "system", content: "", panel: tracePanel(trace) });
    } catch (error) {
      this.push({
        role: "system",
        content: `trace unavailable: ${(error as Error).message}`,
      });
    }
  }

  /** `/cost` card. Tokens are cumulative session usage; the provider does not
   * expose a context-window size, so none is invented. */
  private costPanel(): MessagePanel {
    return {
      title: "usage (cost honesty)",
      lines: [
        `tokens   ${this.tokensTotal} (exact, cumulative session usage)`,
        `turns    ${this.turns}`,
        `window   not provided by the provider (context usage unknown)`,
        `cost     UNKNOWN (no pricing source)`,
      ],
    };
  }

  /** `/provider` — show the redacted live provider status, or configure it.
   * The API key is read from AGENT_OS_PROVIDER_KEY in the CLI environment, so
   * it is never typed into the composer (and thus never written to history,
   * state or the transcript). */
  private async providerCommand(rest: string[]): Promise<void> {
    try {
      const sub = rest[0]?.toLowerCase();
      if (sub === "clear") {
        const status = await this.client.clearProvider();
        this.push({
          role: "system",
          content:
            `provider config + stored key removed (persisted=${status.persisted}); ` +
            "the running daemon keeps its current provider until restart",
        });
        this.emit();
        return;
      }
      if (sub !== "set") {
        const status = await this.client.providerStatus();
        const provenance = [
          `persisted  ${status.persisted ? "yes" : "no"}`,
          `key_source ${status.key_source ?? "none"}`,
        ];
        this.push({
          role: "system",
          content: "",
          panel: {
            title: "provider",
            lines: status.configured
              ? [
                  "status     configured",
                  `model      ${status.model_id ?? "?"}`,
                  `endpoint   ${status.endpoint_class ?? "?"}`,
                  `base_url   ${status.base_url ?? "?"}`,
                  `credential ${status.credential_ref_id ?? "?"}`,
                  ...provenance,
                ]
              : [
                  "status     not configured",
                  ...provenance,
                  "usage      /provider set <base-url> <model> [endpoint-class]",
                  "(export AGENT_OS_PROVIDER_KEY in the CLI environment first)",
                ],
          },
        });
        return;
      }
      const [, baseUrl, model, endpointClass] = rest;
      if (!baseUrl || !model) {
        this.push({
          role: "system",
          content: "usage: /provider set <base-url> <model> [endpoint-class]",
        });
        return;
      }
      const apiKey = process.env.AGENT_OS_PROVIDER_KEY;
      if (!apiKey) {
        this.push({
          role: "system",
          content:
            "AGENT_OS_PROVIDER_KEY is not set in the CLI environment; export it " +
            "there, then retry (the key is never typed into the composer).",
        });
        return;
      }
      const status = await this.client.configureProvider({
        baseUrl,
        model,
        apiKey,
        ...(endpointClass ? { endpointClass } : {}),
      });
      this.push({
        role: "system",
        content:
          `provider configured: model ${status.model_id ?? "?"} · ` +
          `endpoint ${status.endpoint_class ?? "?"} · base_url ${status.base_url ?? "?"}`,
      });
      this.emit();
    } catch (cause) {
      this.push({
        role: "system",
        content: `provider command failed: ${(cause as Error).message}`,
      });
    }
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
      this.pendingSelector = { kind: "mode", title: "permission mode", items: [...MODE_ORDER] };
      this.emit();
      return;
    }
    const mode = arg.toUpperCase() as PermissionMode;
    const sessionId = this.sessionId;
    // Same two round trips as a correction (refresh, then command), so the same
    // stale-cursor rejection is possible here and is handled the same way. The
    // failure is caught here rather than left to the caller: the submit path in
    // the view is fire-and-forget, so a rejection used to escape as an
    // unhandled rejection with no trace in the transcript, and an operator who
    // does not know the mode did not change will act on the wrong one.
    try {
      const updated = await this.controlWithRetry(sessionId, () =>
        this.client.setPermissionMode(sessionId, mode, `cli-ts-mode:${randomUUID()}`),
      );
      this.mode = updated.permission_mode;
      this.snapshot = updated;
      this.push({ role: "system", content: `permission mode → ${this.mode}` });
    } catch (cause) {
      const current = this.snapshot?.permission_mode ?? this.mode;
      this.mode = current;
      this.push({
        role: "system",
        content:
          `permission mode change to ${mode} FAILED (${(cause as Error).message}) — ` +
          `still ${current}; the kernel did not change it`,
      });
    }
  }

  /** `/export [path]` — write the in-session transcript (0600, explicit path). */
  private exportCommand(pathArg: string | undefined): void {
    const stamp = new Date(this.clock()).toISOString().replace(/[:.]/g, "-");
    const path = pathArg?.trim() ? pathArg.trim() : `noem-transcript-${stamp}.md`;
    try {
      writeFileSync(
        path,
        renderTranscript(this.messages, {
          sessionId: this.sessionId,
          mode: this.mode,
          tokens: this.tokensTotal,
          goal: this.goal,
        }),
        { encoding: "utf8", mode: 0o600 },
      );
      // `mode` only applies on create; a pre-existing file keeps its mode.
      // Enforce 0600 and verify before promising it to the operator.
      chmodSync(path, 0o600);
      if ((statSync(path).mode & 0o777) !== 0o600) {
        throw new Error("could not set 0600 on the exported file");
      }
      this.push({
        role: "system",
        content: `transcript exported to ${path} (0600; it may contain sensitive content)`,
      });
    } catch (cause) {
      this.push({ role: "system", content: `export failed: ${(cause as Error).message}` });
    }
  }

  /** `/keys` card — one place with the keymap (discoverability). */
  private keysPanel(): MessagePanel {
    return {
      title: "keyboard",
      lines: [
        "enter submit · ctrl-j newline · ctrl-g $EDITOR",
        "backspace/delete delete backward · ctrl-d delete forward",
        "↑/↓ or ctrl-p/ctrl-n history · ctrl-r reverse search",
        "ctrl-a/ctrl-e line start/end",
        "esc correction · ctrl-c exit · ctrl-l clear view",
        "/ palette · @ file mention · /vim vim keymap (dd/dw/cw)",
      ],
    };
  }

  /** `/find <query>` — search the in-session transcript (view only). */
  private findCommand(query: string): void {
    if (!query) {
      this.push({ role: "system", content: "usage: /find <query>" });
      return;
    }
    const hits = searchMessages(this.messages, query);
    if (hits.length === 0) {
      this.push({ role: "system", content: `no transcript matches for "${query}"` });
      return;
    }
    this.push({
      role: "system",
      content:
        `${hits.length} match(es) for "${query}":\n` +
        hits.map((hit) => `  #${hit.index}  ${hit.text}`).join("\n"),
    });
  }

  /** `/retry` — re-submit the last operator message as a fresh governed turn. */
  private async retryCommand(): Promise<void> {
    if (!this.lastUserText) {
      this.push({ role: "system", content: "nothing to retry yet" });
      return;
    }
    await this.enqueueOrRun(this.lastUserText);
  }

  /** `/edit` — load the last operator message into the composer for editing. */
  private editCommand(): void {
    if (!this.lastUserText) {
      this.push({ role: "system", content: "nothing to edit yet" });
      return;
    }
    this.pendingComposerText = this.lastUserText;
    this.push({ role: "system", content: "loaded the last message into the composer (edit, then Enter)" });
    this.emit();
  }

  /** App consumes this once to seed the composer (`/edit`). */
  consumePendingComposer(): string | null {
    const text = this.pendingComposerText;
    this.pendingComposerText = null;
    return text;
  }

  get hasPendingComposer(): boolean {
    return this.pendingComposerText !== null;
  }

  /** `/theme` — show the active theme, cycle with `next`, or select by name. */
  private themeCommand(arg: string | undefined): void {
    if (!arg) {
      this.pendingSelector = { kind: "theme", title: "theme", items: themeNames() };
      this.emit();
      return;
    }
    if (arg.toLowerCase() === "next") {
      this.themeName = nextTheme(this.themeName);
      this.push({ role: "system", content: `theme → ${this.themeName}` });
      return;
    }
    const name = arg.toLowerCase();
    if (!Object.prototype.hasOwnProperty.call(THEMES, name)) {
      this.push({
        role: "system",
        content: `unknown theme ${arg}; available: ${themeNames().join(", ")}`,
      });
      return;
    }
    this.themeName = name;
    this.push({ role: "system", content: `theme → ${this.themeName}` });
  }

  /** `/doctor` — run the read-only self-check and show it in the transcript. */
  private async doctorCommand(): Promise<void> {
    if (!this.doctor) {
      this.push({ role: "system", content: "doctor unavailable (no probe wired)" });
      return;
    }
    try {
      const text = (await this.doctor()).trim();
      this.push({ role: "system", content: text || "doctor: no output" });
    } catch (cause) {
      this.push({ role: "system", content: `doctor failed: ${(cause as Error).message}` });
    }
  }

  /** `/queue` — list or clear the client-side pre-submit queue. */
  private queueCommand(arg: string | undefined): void {
    if (arg?.toLowerCase() === "clear") {
      const cleared = this.queue.length;
      this.queue.length = 0;
      this.push({ role: "system", content: `cleared ${cleared} queued message(s)` });
      this.emit();
      return;
    }
    if (this.queue.length === 0) {
      this.push({ role: "system", content: "queue empty (messages sent while a turn is in flight are queued)" });
      return;
    }
    this.push({
      role: "system",
      content:
        `queued (${this.queue.length}):\n` +
        this.queue.map((message, index) => `  ${index + 1}. ${message}`).join("\n") +
        `\n/queue clear to discard`,
    });
  }

  /** Resolve the open overlay selector (App calls on Enter / number key). */
  chooseSelector(value: string): void {
    const selector = this.pendingSelector;
    if (!selector) return;
    this.pendingSelector = null;
    switch (selector.kind) {
      case "theme":
        if (Object.prototype.hasOwnProperty.call(THEMES, value)) {
          this.themeName = value;
          this.push({ role: "system", content: `theme → ${this.themeName}` });
        }
        break;
      case "mode":
        void this.modeCommand(value);
        break;
      case "resume":
        void this.resumeCommand(value);
        break;
    }
    this.emit();
  }

  cancelSelector(): void {
    if (!this.pendingSelector) return;
    this.pendingSelector = null;
    this.emit();
  }

  private async resumeCommand(arg: string | undefined): Promise<void> {
    if (!arg) {
      let items: string[] = [];
      try {
        const listed = await this.client.listSessions();
        items = listed.map((session) => session.session_id);
      } catch {
        items = [];
      }
      const fromLocal = items.length === 0;
      if (fromLocal) items = [...this.recentSessions];
      if (items.length === 0) {
        this.push({ role: "system", content: "no sessions; usage: /resume <session-id>" });
        return;
      }
      this.pendingSelector = {
        kind: "resume",
        title: fromLocal ? "recent sessions (local)" : "sessions",
        items,
      };
      this.emit();
      return;
    }
    // Allow picking a recent session by 1-based index.
    const index = Number(arg);
    const target =
      Number.isInteger(index) && index >= 1 && index <= this.recentSessions.length
        ? (this.recentSessions[index - 1] as string)
        : arg;
    // Guard on the single "may a new turn start" predicate, not on `busy`:
    // `busy` is cleared when a turn parks on an approval, so a `busy` check
    // would let a switch move the approval surface out of view.
    if (!this.canStartTurn()) {
      this.push({
        role: "system",
        content: "cannot switch sessions while a turn or approval is pending",
      });
      return;
    }
    const snapshot = await this.client.getSession(target);
    this.adoptSnapshot(snapshot);
    this.push({
      role: "system",
      content: `resumed session ${snapshot.session.session_id} (status ${snapshot.status}, mode ${snapshot.permission_mode})`,
    });
  }

  /** Bounded workspace file list, fetched once per session and cached for
   * `@` mention completion. Read-only; returns [] before a session exists.
   *
   * An EMPTY result is deliberately not cached: the first fetch can legitimately
   * happen before the workspace has any listable file (or before the task is
   * fully bound), and caching [] would disable `@` mentions for the rest of the
   * session. Non-empty results are cached as before. */
  async workspaceFiles(): Promise<SurfaceFileEntry[]> {
    if (this.filesCache && this.filesCache.length > 0) return this.filesCache;
    if (!this.taskId) return [];
    try {
      const files = await this.client.files(this.taskId);
      if (files.length > 0) this.filesCache = files;
      return files;
    } catch {
      return [];
    }
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

  /** `/goal` — show, set or clear the persistent session objective. Not a
   * kernel capability: it lives in the client and is re-emitted as an
   * explicit context prefix per turn (honest about being session-scoped). */
  private goalCommand(arg: string): void {
    if (!arg) {
      this.push({
        role: "system",
        content: this.goal
          ? `session goal: ${this.goal}`
          : "no session goal set; usage: /goal <objective> | /goal clear",
      });
      return;
    }
    if (arg.toLowerCase() === "clear") {
      this.goal = null;
      this.push({ role: "system", content: "session goal cleared" });
      return;
    }
    this.goal = arg;
    this.push({
      role: "system",
      content: `session goal set (included as context in each turn): ${arg}`,
    });
  }

  /** Clear the LOCAL view only: messages, finalized cursor, tool index.
   * Durable session state (history, tokens, mode) is server-side and
   * untouched — the notice says so, because unlike mainstream /clear this
   * does NOT reset the model's context (no /compact yet). Refused while a
   * turn is in flight (clearing mid-stream would split the live message). */
  clearView(): void {
    if (this.busy) {
      this.push({ role: "system", content: "turn in progress; /clear refused (view would split the live message)" });
      return;
    }
    this.messages.length = 0;
    this.toolIndex.clear();
    this.nodeIndex.clear();
    this.finalizedIndex = 0;
    this.pendingPreview = null;
    this.push({
      role: "system",
      content: "view cleared (local view only — durable session context unchanged)",
    });
  }

  private adoptSnapshot(snapshot: SurfaceSessionSnapshot): void {
    this.snapshot = snapshot;
    this.sessionId = snapshot.session.session_id;
    this.taskId = snapshot.session.task_id;
    this.mode = snapshot.permission_mode;
    this.stream = null;
    this.filesCache = null;
    this.recentSessions = [
      snapshot.session.session_id,
      ...this.recentSessions.filter((id) => id !== snapshot.session.session_id),
    ].slice(0, 10);
    this.emit();
  }

  /** Open a session up-front when none exists. runTurn calls this lazily;
   * headless stream-json calls it eagerly so the init line carries the
   * session id before the first delta. */
  async ensureSession(): Promise<void> {
    if (this.sessionId) return;
    const opened = await this.client.openSession("cli-ts session");
    this.adoptSnapshot(opened);
    this.push({ role: "system", content: `session ${this.sessionId} opened` });
  }

  /**
   * Send a control command (correction, permission mode) with a bounded
   * refresh-and-resend loop.
   *
   * `expected_event_sequence` is read from the client's last observed snapshot,
   * and a running turn keeps appending durable events. The refresh GET and the
   * command POST are two round trips, so a commit landing between them rejects
   * the command with 409 `SurfaceSequenceConflict` even though the refresh was
   * correct when it was read (measured on a real daemon: 9 stale-cursor
   * rejections across 20 Esc presses mid-turn). Resending from a *fresh* read is
   * the only sound fix — the cursor is derived from durable truth, never
   * guessed or fudged forward.
   *
   * Each attempt re-reads; only a stale-cursor rejection is retried, and the
   * caller's idempotency key is reused across attempts so a resend can never
   * re-apply a command that already landed (the kernel refuses a digest
   * mismatch under a claimed key instead of executing twice).
   */
  private async controlWithRetry<T>(
    sessionId: string,
    send: () => Promise<T>,
  ): Promise<T> {
    let lastError: unknown;
    for (let attempt = 0; attempt <= SEQUENCE_RETRY_LIMIT; attempt += 1) {
      this.snapshot = await this.client.getSession(sessionId);
      try {
        return await send();
      } catch (cause) {
        lastError = cause;
        if (!isSequenceConflict(cause)) throw cause;
        if (attempt < SEQUENCE_RETRY_LIMIT) {
          await new Promise((resolve) => setTimeout(resolve, this.sequenceRetryDelayMs));
        }
      }
    }
    throw lastError;
  }

  /** Single predicate for "a new turn may start now" — used by both the
   * submit router and the queue drain so they can never disagree. */
  private canStartTurn(): boolean {
    return (
      !this.busy &&
      this.status !== "awaiting_approval" &&
      this.status !== "streaming" &&
      this.status !== "stalled" &&
      this.status !== "closed"
    );
  }

  /** Route a normal message: run it now, or queue it behind the in-flight
   * turn / pending approval (never a second concurrent turn). */
  private async enqueueOrRun(text: string): Promise<void> {
    if (!this.canStartTurn()) {
      this.queue.push(text);
      this.push({
        role: "system",
        content: `queued (#${this.queue.length}) — will send when the current turn ends`,
      });
      this.emit();
      return;
    }
    await this.runTurn(text);
  }

  /** Start the next queued message once the turn/approval has resolved. */
  private maybeDrain(): void {
    if (this.queue.length === 0) return;
    if (!this.canStartTurn()) return;
    const next = this.queue.shift();
    if (next !== undefined) void this.runTurn(next);
  }

  async runTurn(text: string): Promise<void> {
    if (this.busy) {
      this.push({ role: "system", content: "turn already in progress" });
      return;
    }
    this.lastUserText = text;
    this.busy = true;
    this.lastError = null;
    this.lastStopReason = null;
    try {
      await this.ensureSession();
      const sessionId = this.sessionId!;
      if (!this.stream) {
        const subscription = await this.client.subscribeStream(sessionId);
        this.stream = {
          runtime_boot_id: subscription.runtime_boot_id,
          stream_id: subscription.stream_id,
        };
      }
      const binding = this.stream;
      const outgoing = this.goal ? `[session goal] ${this.goal}\n\n${text}` : text;
      this.reasoningText = "";
      this.push({ role: "user", content: outgoing });
      this.status = "streaming";
      this.lastActivity = this.clock();
      this.emit();

      const begin = await this.client.beginTurn(sessionId, outgoing, binding);
      this.turnId = begin.turn_id;

      for await (const frame of this.client.followStream(sessionId, binding, { pollMs: this.pollMs })) {
        this.lastActivity = this.clock();
        if (frame.kind === "CHUNK") {
          this.appendAssistant((frame.payload as { delta?: string }).delta ?? "");
        } else if (frame.kind === "REASONING") {
          // Transient reasoning: display-only, never appended to the answer.
          this.reasoningText += (frame.payload as { delta?: string }).delta ?? "";
          this.emit();
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
        // A turn-level failure is often itself a stale cursor (the kernel
        // rejected begin-turn/some command for an event sequence the client had
        // not seen). Re-read durable truth before the next command, otherwise
        // every following command fails the same way. The refresh must not
        // replace the real error, so a failing read is ignored here.
        if (this.sessionId) {
          try {
            this.adoptSnapshot(await this.client.getSession(this.sessionId));
          } catch {
            /* the turn error above stays the reported one */
          }
        }
      }
      this.emit();
    } finally {
      this.busy = false;
      this.maybeDrain();
    }
  }

  /** After STREAM_END the durable record is authoritative: wait for the
   * turn-completed or approval-pending event; on silence past the stall
   * threshold render the single typed stalled state (never inferred
   * completion). */
  private async awaitDurableResolution(sessionId: string): Promise<void> {
    const deadline = this.clock() + this.stallMs;
    // A stall has two very different causes - the daemon is quiet, or the drain
    // itself keeps failing - and the swallowed rejection made them look alike.
    this.lastDurableError = null;
    for (;;) {
      this.drainDurable();
      if (this.status === "idle" || this.status === "awaiting_approval") {
        // Turn resolved via durable events. Refresh the authoritative
        // snapshot so the client's expected_event_sequence matches the
        // kernel: stream-side frames advanced the session sequence beyond
        // the last tracked snapshot, and the next command would otherwise
        // be rejected with a sequence mismatch (iteration-18 pty finding).
        this.adoptSnapshot(await this.client.getSession(sessionId));
        this.emit();
        return;
      }
      if (this.clock() > deadline) {
        this.status = "stalled"; // transient; only durable state may overrule
        this.push({
          role: "system",
          content:
            this.lastDurableError === null
              ? `no durable resolution within ${this.stallMs}ms — the daemon has not reported this turn's outcome yet, so the result is unknown (try /retry or /status)`
              : `durable event drain failed: ${this.lastDurableError} — the cursor stays at ${this.durableCursor} so nothing is skipped, but this turn's outcome is unknown (try /retry or /status)`,
        });
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
      .then((batch) => {
        this.lastDurableError = null;
        this.applyDurable(batch.next_sequence, batch.events);
      })
      .catch((cause: unknown) => {
        // Fail-closed: a batch we could not read must not advance the cursor.
        // The rejection used to be discarded, which made "the drain is broken"
        // indistinguishable from "the daemon is quiet" - keep the reason so the
        // stall can say which one it is.
        this.lastDurableError =
          cause instanceof Error ? cause.message : String(cause);
      });
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
      } else if (event.event_type === "NODE_COMPLETED") {
        this.applyToolCompletion(payload);
      } else if (event.event_type === "NODE_FAILED") {
        this.applyToolFailure(payload);
      }
    }
  }

  /** Tool card projection from the durable event stream (read-only view of
   * ACTION_PROPOSED / ACTION_RECEIPT_RECORDED / NODE_COMPLETED; no governance
   * state here). */
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
    const nodeId = String(action["node_id"] ?? "");
    if (nodeId) this.nodeIndex.set(nodeId, this.messages.length);
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
    const parts: string[] = [];
    const effect = payload["effect"] as Record<string, unknown> | undefined;
    // Top-level `effect` is emitted by the kernel only for compensatable
    // edits (workspace.edit/apply_patch, SUCCEEDED): task_service.py:1548.
    if (effect && typeof effect["path"] === "string") {
      const applied =
        typeof effect["applied_sha256"] === "string"
          ? String(effect["applied_sha256"]).slice(0, 12)
          : "";
      parts.push(`effect ${effect["path"]}${applied ? ` · applied ${applied}…` : ""}`);
    }
    const errorCode = String(receipt?.["error_code"] ?? "");
    if (errorCode && errorCode !== NO_ERROR_CODE) parts.push(`error ${errorCode}`);
    const artifacts = receipt?.["output_artifact_ids"];
    if (Array.isArray(artifacts) && artifacts.length > 0) parts.push(`artifacts ${artifacts.length}`);
    // Only SUCCEEDED is a success; FAILED/CANCELLED/COMPENSATED are failures;
    // DISPATCHED/ACKNOWLEDGED/UNKNOWN are not-yet-confirmed (pending), never ✓.
    const toolStatus: ToolCall["status"] =
      status === "SUCCEEDED"
        ? "done"
        : status === "FAILED" || status === "CANCELLED" || status === "COMPENSATED"
          ? "failed"
          : "pending";
    message.tool = {
      ...message.tool,
      status: toolStatus,
      ...(parts.length > 0 ? { resultSummary: parts.join(" · ") } : {}),
    };
    this.emit();
  }

  /** Tool-reported result, from the durable `NODE_COMPLETED` output.
   *
   * The receipt proves the dispatch ran and its effect is known; the OUTPUT is
   * where the tool's own result lives (`workspace.run_tests` answers
   * `{exit_code, artifact_ids, digest}`, `workspace.shell` adds stdout/stderr).
   * A non-zero exit is a failure the operator must see — the card used to show
   * the same `✓` for a passing and a failing test run (S1 audit). The receipt
   * is not reinterpreted: `status` stays `done`, and the exit code is carried as
   * its own fact. */
  private applyToolCompletion(payload: Record<string, unknown>): void {
    const actionId = String(payload["action_id"] ?? "");
    const nodeId = String(payload["node_id"] ?? "");
    const index =
      (actionId ? this.toolIndex.get(actionId) : undefined) ??
      (nodeId ? this.nodeIndex.get(nodeId) : undefined);
    if (index === undefined) return;
    const message = this.messages[index];
    const tool = message?.tool;
    if (!tool) return;
    const output = payload["output"];
    if (typeof output !== "object" || output === null) return;
    const record = output as Record<string, unknown>;
    const rawExit = record["exit_code"];
    // A bool is an int in JS: reject it, the kernel's exit code is a number.
    const exitCode =
      typeof rawExit === "boolean" || typeof rawExit !== "number" || !Number.isInteger(rawExit)
        ? undefined
        : rawExit;
    const rawError = record["error"];
    const errorText = typeof rawError === "string" && rawError ? rawError : undefined;
    if (exitCode === undefined && errorText === undefined) return;
    const parts: string[] = [];
    // exit 0 is a pass, already implied by the confirmed status; only the
    // non-zero exit is news. The error text (if any) is always news.
    if (exitCode !== undefined && exitCode !== 0) parts.push(`exit ${exitCode}`);
    if (errorText !== undefined) {
      parts.push(`error ${errorText.length > 120 ? `${errorText.slice(0, 120)}…` : errorText}`);
    }
    message.tool = {
      ...tool,
      ...(exitCode === undefined ? {} : { exitCode }),
      ...(errorText === undefined ? {} : { errorText }),
      ...(parts.length === 0
        ? {}
        : { resultSummary: [...parts, tool.resultSummary].filter(Boolean).join(" · ") }),
    };
    this.emit();
  }

  /** A tool call that sealed nothing: refused before dispatch (so no receipt
   * exists, because nothing was dispatched) or otherwise produced no result.
   * The durable failure event carries the reason, so the card converges to
   * `failed` instead of waiting for a result that will never come — the card
   * used to sit at `⏵ pending` forever and `/export` said `tool [pending]`
   * (round-3 audit). Assigned rather than appended, because the durable event
   * can be replayed into the projection more than once. */
  private applyToolFailure(payload: Record<string, unknown>): void {
    const actionId = String(payload["action_id"] ?? "");
    const nodeId = String(payload["node_id"] ?? "");
    const index =
      (actionId ? this.toolIndex.get(actionId) : undefined) ??
      (nodeId ? this.nodeIndex.get(nodeId) : undefined);
    if (index === undefined) return;
    const message = this.messages[index];
    const tool = message?.tool;
    if (!tool) return;
    const rawError = payload["error"];
    const errorText = typeof rawError === "string" && rawError ? rawError : undefined;
    if (errorText === undefined) return;
    const bounded =
      errorText.length > 120 ? `${errorText.slice(0, 120)}…` : errorText;
    message.tool = {
      ...tool,
      status: "failed",
      errorText,
      resultSummary: `error ${bounded}`,
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
    if (disposition === "REJECT") {
      // The model is told the operator refused, but the card kept rendering its
      // pending state forever - on the surface the operator is looking at when
      // they press n. Rejecting is a resolution, so the card has to show one.
      this.resolveRejectedCard(pending.capability_id);
    }
    this.status = "idle";
    this.pendingPreview = null;
    this.finalizeAll();
    this.maybeDrain();
  }

  /** The newest still-pending card for this capability, marked as rejected.
   *
   * Keyed by capability rather than by action id because the pending approval
   * carries a digest, not the id the card was created with; the newest pending
   * card for that capability is the one being decided. */
  private resolveRejectedCard(capabilityId: string): void {
    for (let index = this.messages.length - 1; index >= 0; index -= 1) {
      const message = this.messages[index];
      const tool = message?.tool;
      if (message === undefined || tool === undefined) continue;
      if (tool.capabilityId !== capabilityId) continue;
      if (tool.status !== "pending") continue;
      message.tool = {
        ...tool,
        status: "failed",
        errorText: "rejected by the operator",
        resultSummary: "rejected by the operator",
      };
      this.emit();
      return;
    }
  }

  /** Ctrl-C semantics: correction during activity, close when idle.
   *
   * One intent, one correction: while a correction is in flight, further Esc /
   * Ctrl-C presses join it instead of starting another. A held or repeated key
   * used to send one POST and one transcript line per key event — three
   * identical "correction FAILED" lines and three requests for one operator
   * decision. */
  async interrupt(source: "ctrl-c" | "escape" = "ctrl-c"): Promise<"corrected" | "closed"> {
    if (this.interruptInFlight) return this.interruptInFlight;
    const attempt = this.runInterrupt(source);
    this.interruptInFlight = attempt;
    try {
      return await attempt;
    } finally {
      this.interruptInFlight = null;
    }
  }

  private async runInterrupt(source: "ctrl-c" | "escape"): Promise<"corrected" | "closed"> {
    if (this.sessionId && (this.status === "streaming" || this.status === "stalled")) {
      const sessionId = this.sessionId;
      // One idempotency key for the operator's single intent, reused across the
      // bounded resends below: if a correction did land and its response we
      // never saw, the kernel answers from its idempotency record (or refuses a
      // digest mismatch) instead of applying it a second time.
      const idempotencyKey = `cli-ts-correction:${randomUUID()}`;
      try {
        await this.controlWithRetry(sessionId, () =>
          this.client.correct(
            sessionId,
            `operator interrupt (${source})`,
            "correction",
            idempotencyKey,
          ),
        );
      } catch (cause) {
        // Say so, loudly, on the surface the operator is looking at. Esc must not
        // be a silent no-op: a correction that did not land is worse than none,
        // because the operator stops watching a run they think they redirected.
        this.push({
          role: "system",
          content:
            `correction FAILED (${cause instanceof Error ? cause.message : String(cause)}) — ` +
            "the run was NOT corrected; retry, or check /status and /task",
        });
        this.emit();
        throw cause;
      }
      this.push({ role: "system", content: "correction issued (operator interrupt)" });
      this.status = "idle";
      this.finalizeAll();
      this.maybeDrain();
      return "corrected";
    }
    this.status = "closed";
    this.emit();
    return "closed";
  }
}
