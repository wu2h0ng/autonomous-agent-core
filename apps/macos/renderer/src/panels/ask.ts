// Ask posture (Wave 2c): a question mode with NO external effect by default.
// Upgrading to Work is the only way out, and it goes through the existing
// Surface open_session command — nothing else.

import type { SurfaceClient } from "../surface_client";

export type AskPhase = "idle" | "ask" | "upgrading" | "work";

export interface AskState {
  phase: AskPhase;
  question: string;
  session_id: string | null;
}

export const initialAskState: AskState = {
  phase: "idle",
  question: "",
  session_id: null,
};

/** Ask mode: pure state transition, performs zero I/O. */
export function askTransition(state: AskState, event: "start" | "cancel"): AskState {
  switch (event) {
    case "start":
      return { ...state, phase: "ask" };
    case "cancel":
      return { ...state, phase: "idle", question: "" };
  }
}

/**
 * Upgrade to Work: opens a session via the protocol and returns the new
 * state. The ONLY effect is the open_session call; callers must not perform
 * any other I/O in this path.
 */
export async function upgradeToWork(
  client: SurfaceClient,
  state: AskState,
): Promise<AskState> {
  if (state.phase !== "ask" || state.question.trim() === "") {
    throw new Error("upgrade requires an active ask with a non-empty question");
  }
  const opened = await client.openSession(state.question);
  return {
    phase: "work",
    question: state.question,
    session_id: opened.session.session_id,
  };
}
