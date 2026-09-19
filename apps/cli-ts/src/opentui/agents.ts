/**
 * P3a pure agent-tree builder (no renderer/network import -> Node-testable).
 *
 * Hierarchy is derived from existing read-only projections only:
 *   mandate -> task (MandateTaskLink) -> session (SurfaceSessionSummary.task_id)
 *
 * The terminal never renders mandate mission/statement text or credentials —
 * rows carry identifiers, kind and status only (AB §4/G5).
 */
export type AgentRowKind = "mandate" | "task" | "session" | "child" | "group";

/** One child agent row, flattened from the parent session's roll-up.
 * `in_flight` is the runtime liveness signal, NOT the conservative attribution
 * status (an unfinished child is reported `stopped` in the roll-up). */
export interface ChildRowInput {
  parent_session_id: string;
  spawn_id: string;
  child_session_id: string;
  agent_type: string;
  status: string;
  steps: number;
  tokens: number;
  stop_reason: string | null;
  in_flight: boolean;
}

export interface AgentTreeInput {
  mandates: readonly { mandate_id: string; status: string }[];
  links: readonly { mandate_id: string; task_id: string }[];
  sessions: readonly {
    session_id: string;
    task_id: string;
    status: string;
    /** Read-only projection of the durable pending approval (never inferred). */
    hasPendingApproval?: boolean;
  }[];
  /** Child agents, keyed by their parent session id. */
  children?: readonly ChildRowInput[];
}

export interface AgentRow {
  depth: number;
  kind: AgentRowKind;
  id: string;
  status: string;
  /** Only ever true for a session row whose projection reported a pending approval. */
  pendingApproval?: boolean;
  /** Child rows only: the parent session (the route scope for a stop). */
  parentSessionId?: string;
  /** Child rows only: liveness - true while the child is actually executing. */
  inFlight?: boolean;
  steps?: number;
  tokens?: number;
  stopReason?: string | null;
  /** Child rows only: wall-clock ms this child has been observed in flight.
   * Populated by the TUI (client-side first-seen), never by the roll-up; a
   * child that has not been observed yet omits it rather than showing 0. */
  elapsedMs?: number;
}

export interface AgentTree {
  rows: AgentRow[];
  /** True when a cap hid part of the tree (the UI must say so, not silently drop). */
  truncated: boolean;
}

export const AGENT_TREE_MAX_ROWS = 500;

/** Code-point comparison: locale-independent, so the tree is identical on
 * every machine (localeCompare would vary with the runtime locale). */
function compareIds(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function byId<T extends { [k: string]: unknown }>(key: string) {
  return (a: T, b: T): number => compareIds(String(a[key]), String(b[key]));
}

/**
 * Deterministic: mandates, tasks and sessions are sorted and grouped; sessions
 * whose task is unknown land in an explicit "(unlinked task)" group; tasks with
 * no sessions still appear (with status "-"). Missing data degrades to fewer
 * rows, never throws.
 */
export function buildAgentTree(
  input: AgentTreeInput,
  maxRows = AGENT_TREE_MAX_ROWS,
): AgentTree {
  const mandates = [...input.mandates].sort(byId("mandate_id"));
  const linksByMandate = new Map<string, string[]>();
  const knownTasks = new Set<string>();
  for (const link of input.links) {
    const tasks = linksByMandate.get(link.mandate_id) ?? [];
    tasks.push(link.task_id);
    linksByMandate.set(link.mandate_id, tasks);
    knownTasks.add(link.task_id);
  }
  const sessionsByTask = new Map<string, AgentTreeInput["sessions"][number][]>();
  for (const session of input.sessions) {
    const list = sessionsByTask.get(session.task_id) ?? [];
    list.push(session);
    sessionsByTask.set(session.task_id, list);
  }
  const childrenByParent = new Map<string, ChildRowInput[]>();
  for (const child of input.children ?? []) {
    const list = childrenByParent.get(child.parent_session_id) ?? [];
    list.push(child);
    childrenByParent.set(child.parent_session_id, list);
  }

  const rows: AgentRow[] = [];
  const push = (row: AgentRow): void => {
    rows.push(row);
  };
  const pushChildren = (parentSessionId: string, depth: number): void => {
    const children = [...(childrenByParent.get(parentSessionId) ?? [])].sort(
      (a, b) => compareIds(a.spawn_id, b.spawn_id),
    );
    for (const child of children) {
      push({
        depth,
        kind: "child",
        id: child.child_session_id,
        status: child.in_flight ? "running" : child.status,
        parentSessionId,
        inFlight: child.in_flight,
        steps: child.steps,
        tokens: child.tokens,
        stopReason: child.stop_reason,
      });
    }
  };
  const pushTask = (taskId: string, depth: number): void => {
    const sessions = [...(sessionsByTask.get(taskId) ?? [])].sort(
      byId("session_id"),
    );
    push({
      depth,
      kind: "task",
      id: taskId,
      status: sessions.length > 0 ? `${sessions.length} session(s)` : "-",
    });
    for (const session of sessions) {
      push({
        depth: depth + 1,
        kind: "session",
        id: session.session_id,
        status: session.status,
        pendingApproval: session.hasPendingApproval === true,
      });
      pushChildren(session.session_id, depth + 2);
    }
  };

  for (const mandate of mandates) {
    const tasks = [...new Set(linksByMandate.get(mandate.mandate_id) ?? [])].sort();
    push({ depth: 0, kind: "mandate", id: mandate.mandate_id, status: mandate.status });
    for (const task of tasks) pushTask(task, 1);
  }

  const orphanTasks = new Set<string>();
  for (const session of input.sessions) {
    if (!knownTasks.has(session.task_id)) orphanTasks.add(session.task_id);
  }
  if (orphanTasks.size > 0) {
    push({ depth: 0, kind: "group", id: "(unlinked task)", status: "" });
    for (const task of [...orphanTasks].sort()) pushTask(task, 1);
  }

  if (rows.length <= maxRows) return { rows, truncated: false };
  return { rows: rows.slice(0, maxRows), truncated: true };
}

/** Render one tree row; `depth` is expressed with a fixed indent. */
export function agentRowLine(row: AgentRow): string {
  const indent = "  ".repeat(row.depth);
  const marker =
    row.kind === "mandate"
      ? "◆"
      : row.kind === "task"
        ? "▸"
        : row.kind === "session"
          ? "•"
          : row.kind === "child"
            ? "◦"
            : "≡";
  const flag = row.pendingApproval === true ? "  !pending approval" : "";
  if (row.kind === "child") {
    const live = row.inFlight === true ? "  !running" : "";
    const counters =
      typeof row.steps === "number" && typeof row.tokens === "number"
        ? `  ${row.steps} step(s) · ${row.tokens} tok`
        : "";
    const reason =
      !row.inFlight && row.stopReason ? `  (${row.stopReason})` : "";
    // Elapsed is shown only for a child this terminal has OBSERVED in flight
    // (the roll-up carries no clock). A child we have not yet seen running
    // omits it rather than lying with "0s".
    const elapsed =
      row.inFlight === true && typeof row.elapsedMs === "number"
        ? `  ${formatElapsed(row.elapsedMs)}`
        : "";
    return `${indent}${marker} ${row.id}  ${row.status}${counters}${reason}${elapsed}${live}`;
  }
  const status = row.status === "" ? "" : `  ${row.status}`;
  return `${indent}${marker} ${row.id}${status}${flag}`;
}

/** Compact elapsed label: "12s" / "1m05s" / "1h02m". Rounds DOWN to whole
 * seconds so the label does not flicker between "59s" and "1m00s" mid-second. */
export function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes}m${String(seconds).padStart(2, "0")}s`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return `${hours}h${String(restMinutes).padStart(2, "0")}m`;
}

/** Clamp a row cursor to the current tree (rows change on every refresh). */
export function clampCursor(cursor: number, rowCount: number): number {
  if (rowCount <= 0) return 0;
  return Math.min(Math.max(cursor, 0), rowCount - 1);
}

export function moveCursor(cursor: number, delta: number, rowCount: number): number {
  return clampCursor(cursor + delta, rowCount);
}

/** Only `session` rows are resumable; anything else must not trigger a switch. */
export function resumableSessionId(
  rows: readonly AgentRow[],
  cursor: number,
): string | null {
  const row = rows[clampCursor(cursor, rows.length)];
  return row !== undefined && row.kind === "session" ? row.id : null;
}

/** A per-child stop target: only an in-flight child row is stoppable. The
 * parent session is the route scope; terminal/not-a-child rows return null so
 * the key falls through instead of issuing a meaningless request. */
export interface ChildStopTarget {
  parentSessionId: string;
  childSessionId: string;
}

export function stopTargetAtRow(
  rows: readonly AgentRow[],
  cursor: number,
): ChildStopTarget | null {
  const row = rows[clampCursor(cursor, rows.length)];
  if (
    row !== undefined &&
    row.kind === "child" &&
    row.inFlight === true &&
    typeof row.parentSessionId === "string"
  ) {
    return { parentSessionId: row.parentSessionId, childSessionId: row.id };
  }
  return null;
}

/** Stable identity of a row, so a refresh can keep the same row highlighted
 * instead of the same index (rows can be inserted/removed by a refresh). */
export function cursorKey(rows: readonly AgentRow[], cursor: number): string | null {
  const row = rows[clampCursor(cursor, rows.length)];
  return row === undefined ? null : `${row.kind}:${row.id}`;
}

export function repositionCursor(
  rows: readonly AgentRow[],
  previousKey: string | null,
  fallback: number,
): number {
  if (previousKey !== null) {
    const index = rows.findIndex((row) => `${row.kind}:${row.id}` === previousKey);
    if (index >= 0) return index;
  }
  return clampCursor(fallback, rows.length);
}

export type EnterPlan =
  | { kind: "resume"; sessionId: string }
  | { kind: "submit"; text: string }
  | { kind: "none" };

/**
 * Decide what Enter means for the current panel/cursor/composer text. Pure so
 * the routing (which is otherwise only wired inside the renderer) is testable.
 *   agents panel + session row -> switch session (reuses /resume)
 *   agents panel + other row  -> fall through to the composer (no silent no-op)
 *   any other panel           -> submit the composer
 */
export function planEnter(
  activePanel: string,
  rows: readonly AgentRow[],
  cursor: number,
  input: string,
): EnterPlan {
  if (activePanel === "agents") {
    const sessionId = resumableSessionId(rows, cursor);
    if (sessionId !== null) return { kind: "resume", sessionId };
  }
  const text = input.trim();
  return text === "" ? { kind: "none" } : { kind: "submit", text };
}
