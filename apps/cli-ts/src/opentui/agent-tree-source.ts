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
import { buildAgentTree, type AgentTree } from "./agents.js";
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
  if (mandates.length > maxMandates) {
    notes.push(`showing ${maxMandates}/${mandates.length} mandates`);
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

  let sessions: { session_id: string; task_id: string; status: string }[] = [];
  try {
    sessions = (await client.listSessions(100)).map((session) => ({
      session_id: session.session_id,
      task_id: session.task_id,
      status: session.status,
    }));
  } catch {
    notes.push("session listing unavailable");
  }

  const tree = buildAgentTree({ mandates, links, sessions });
  return { ...tree, note: notes.length > 0 ? notes.join("; ") : null };
}
