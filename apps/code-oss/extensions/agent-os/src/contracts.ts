export const SURFACE_PROTOCOL_VERSION = '1.0';

export interface RuntimeDescriptor {
  protocol_version: string;
  host: '127.0.0.1' | '::1';
  port: number;
  bearer_token: string;
  workspace_path: string;
}

export interface SessionSnapshot {
  protocol_version: string;
  session: { session_id: string; task_id: string; run_id: string };
  status: string;
  event_sequence: number;
  pending_approval: null | { capability_id: string; action_digest: string; preview: string };
}

export interface TurnResponse {
  protocol_version: string;
  snapshot: SessionSnapshot;
  text: string;
  stop_reason: string;
}

