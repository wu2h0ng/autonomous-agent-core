/**
 * P3a read-only tree source: joins existing read-only projections into the
 * agent tree. NO governance operation, NO write, NO new contract.
 *
 *   GET /v1/mandates                     -> mandate projections
 *   GET /v1/mandates/{id}/task-links     -> mandate -> task
 *   GET /v1/surface/sessions             -> session -> task (SurfaceClient.listSessions)
 *
 * Parsing is deliberately lenient (only the fields the tree needs) so an
 * unrelated server-side projection change degrades to fewer rows instead of
 * crashing the terminal. Failures are reported as a note, never thrown.
 */
import { z } from "zod";
import { buildAgentTree, type AgentTree, type ChildRowInput } from "./agents.js";
import type { SurfaceClient } from "../client.js";

const MandateRowSchema = z
  .object({
    mandate: z.object({
      mandate_id: z.string().min(1),
      status: z.string().min(1),
    }),
  })
  .passthrough();

const MandatesResponseSchema = z
  .object({ mandates: z.array(MandateRowSchema) })
  .passthrough();

const TaskLinkRowSchema = z
  .object({ mandate_id: z.string().min(1), task_id: z.string().min(1) })
  .passthrough();

/** Bound the fan-out: one link request per mandate, capped. */
export const AGENT_TREE_MAX_MANDATES = 20;

/** Bound the fan-out for child roll-ups: one GET per parent session. */
export const AGENT_TREE_MAX_CHILD_SESSIONS = 30;

export interface AgentTreeResult extends AgentTree {
  note: string | null;
}

export async function fetchAgentTree(
  client: SurfaceClient,
  maxMandates = AGENT_TREE_MAX_MANDATES,
): Promise<AgentTreeResult> {
  let mandates: { mandate_id: string; status: string }[] = [];
  const notes: string[] = [];
  try {
    const parsed = MandatesResponseSchema.parse(await client.getReadOnly("/v1/mandates"));
    mandates = parsed.mandates.map((row) => ({
      mandate_id: row.mandate.mandate_id,
      status: row.mandate.status,
    }));
  } catch {
    return { rows: [], truncated: false, note: "(mandate projection unavailable)" };
  }
  // Deterministic subset: sort by id before capping so the same mandates are
  // chosen on every run (server order is not guaranteed stable).
  mandates.sort((a, b) => (a.mandate_id < b.mandate_id ? -1 : a.mandate_id > b.mandate_id ? 1 : 0));
  if (mandates.length > maxMandates) {
    notes.push(`mandates truncated at ${maxMandates}/${mandates.length}`);
    mandates = mandates.slice(0, maxMandates);
  }

  const links: { mandate_id: string; task_id: string }[] = [];
  for (const mandate of mandates) {
    try {
      const raw = await client.getReadOnly(
        `/v1/mandates/${encodeURIComponent(mandate.mandate_id)}/task-links`,
      );
      const body = raw as { task_links?: unknown };
      const list = Array.isArray(body?.task_links) ? body.task_links : [];
      for (const entry of list) {
        const link = TaskLinkRowSchema.safeParse(entry);
        if (link.success) links.push(link.data);
      }
    } catch {
      notes.push(`task-links unavailable for ${mandate.mandate_id}`);
    }
  }

  let sessions: {
    session_id: string;
    task_id: string;
    status: string;
    hasPendingApproval: boolean;
  }[] = [];
  try {
    sessions = (await client.listSessions(100)).map((session) => ({
      session_id: session.session_id,
      task_id: session.task_id,
      status: session.status,
      hasPendingApproval: session.awaiting_approval === true,
    }));
  } catch {
    notes.push("session listing unavailable");
  }

  // Child roll-ups, one bounded GET per parent session (lenient: a failed or
  // unparseable roll-up degrades to a note, never crashes the tree). Liveness
  // comes from `in_flight`, not the conservative per-child attribution status.
  const children: ChildRowInput[] = [];
  const childSessions = sessions.slice(0, AGENT_TREE_MAX_CHILD_SESSIONS);
  if (sessions.length > AGENT_TREE_MAX_CHILD_SESSIONS) {
    notes.push(
      `child agents truncated at ${AGENT_TREE_MAX_CHILD_SESSIONS}/${sessions.length} sessions`,
    );
  }
  for (const parent of childSessions) {
    try {
      const rollup = await client.childAgents(parent.session_id);
      const live = new Set(rollup.in_flight.map((entry) => entry.child_session_id));
      for (const turn of rollup.turns) {
        for (const child of turn.children) {
          children.push({
            parent_session_id: rollup.session_id,
            spawn_id: child.spawn_id,
            child_session_id: child.child_session_id,
            agent_type: child.agent_type,
            status: child.status,
            steps: child.steps,
            tokens: child.tokens,
            stop_reason: child.stop_reason ?? null,
            in_flight: live.has(child.child_session_id),
          });
        }
      }
    } catch {
      notes.push(`child roll-up unavailable for ${parent.session_id}`);
    }
  }

  const tree = buildAgentTree({ mandates, links, sessions, children });
  return { ...tree, note: notes.length > 0 ? notes.join("; ") : null };
}
