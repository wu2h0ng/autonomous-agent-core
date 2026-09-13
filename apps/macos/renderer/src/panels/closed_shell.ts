// Closed shells for Wave 3 integrations (Chrome Live, Embedded Web, Gmail,
// Calendar). They render Surface state only and MUST never call external
// services; the panel logic asserts zero connectivity.

export type ClosedIntegrationId =
  | "chrome-live"
  | "embedded-web"
  | "gmail"
  | "calendar";

export const CLOSED_INTEGRATIONS: Record<
  ClosedIntegrationId,
  { title: string; wave: string }
> = {
  "chrome-live": { title: "Chrome Live", wave: "Wave 3" },
  "embedded-web": { title: "Embedded Web", wave: "Wave 3" },
  gmail: { title: "Gmail", wave: "Wave 3" },
  calendar: { title: "Calendar", wave: "Wave 3" },
};

export interface ClosedShellState {
  panel_id: ClosedIntegrationId;
  title: string;
  message: string;
  session_status: string | null;
}

/** Pure view state; performs no I/O of any kind. */
export function closedShellState(
  panelId: ClosedIntegrationId,
  sessionStatus: string | null,
): ClosedShellState {
  const integration = CLOSED_INTEGRATIONS[panelId];
  return {
    panel_id: panelId,
    title: integration.title,
    message: `integration pending (${integration.wave})`,
    session_status: sessionStatus,
  };
}
