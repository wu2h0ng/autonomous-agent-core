// Evidence and Approval panel logic: pending approval rendering and the
// exact-digest approve/reject actions. Pure logic (client injected).

import type {
  PendingApproval,
  SessionSnapshot,
  SurfaceClient,
  TurnResponse,
} from "../surface_client";

export type ApprovalDisposition = "APPROVE" | "REJECT";

export function pendingApproval(snapshot: SessionSnapshot): PendingApproval | null {
  return snapshot.pending_approval;
}

/** Submit the exact pending digest; never fabricates or rewrites it. */
export async function decidePendingApproval(
  client: SurfaceClient,
  sessionId: string,
  pending: PendingApproval,
  disposition: ApprovalDisposition,
  reason: string,
): Promise<TurnResponse> {
  return client.decideApproval(
    sessionId,
    pending.action_digest,
    disposition,
    reason,
  );
}
