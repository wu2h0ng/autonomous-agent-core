/**
 * P3a pure agent-tree builder (no renderer/network import -> Node-testable).
 *
 * Hierarchy is derived from existing read-only projections only:
 *   mandate -> task (MandateTaskLink) -> session (SurfaceSessionSummary.task_id)
 *
 * The terminal never renders mandate mission/statement text or credentials —
 * rows carry identifiers, kind and status only (AB §4/G5).
 */
export type AgentRowKind = "mandate" | "task" | "session" | "group";

export interface AgentTreeInput {
  mandates: readonly { mandate_id: string; status: string }[];
  links: readonly { mandate_id: string; task_id: string }[];
  sessions: readonly { session_id: string; task_id: string; status: string }[];
}

export interface AgentRow {
  depth: number;
  kind: AgentRowKind;
  id: string;
  status: string;
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

  const rows: AgentRow[] = [];
  const push = (row: AgentRow): void => {
    rows.push(row);
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
      });
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
          : "≡";
  const status = row.status === "" ? "" : `  ${row.status}`;
  return `${indent}${marker} ${row.id}${status}`;
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
