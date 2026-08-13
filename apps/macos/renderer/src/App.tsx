import { useEffect, useState } from "react";
import { runtimeConnection } from "./tauri";
import { SurfaceClient, SessionSnapshot, TurnResponse } from "./surface_client";
import { resumeThread, type AgentThreadState } from "./panels/agent_thread";
import {
  decidePendingApproval,
  pendingApproval,
  type ApprovalDisposition,
} from "./panels/evidence_approval";
import { fetchFiles, type FileEntry } from "./panels/files";
import { DEFAULT_TEMPLATE, validateTemplate, type LayoutTemplate } from "./panels/layout";
import { fetchOverview, type TaskOverview } from "./panels/plan_tasks";
import { recentDiffs, type DiffSummary } from "./panels/diff";
import { terminalEvents, type TerminalLine } from "./panels/terminal";
import { closedShellState, type ClosedIntegrationId } from "./panels/closed_shell";

type Phase =
  | { kind: "connecting" }
  | { kind: "ready" }
  | { kind: "error"; message: string };

function closedShellMap(): Record<string, unknown> {
  return { "chrome-live": {}, "embedded-web": {}, gmail: {}, calendar: {} };
}

export function App(): React.JSX.Element {
  const [phase, setPhase] = useState<Phase>({ kind: "connecting" });
  const [client, setClient] = useState<SurfaceClient | null>(null);
  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [thread, setThread] = useState<AgentThreadState | null>(null);
  const [files, setFiles] = useState<FileEntry[] | null>(null);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");
  const [layout, setLayout] = useState<LayoutTemplate>(DEFAULT_TEMPLATE);
  const [overview, setOverview] = useState<TaskOverview | null>(null);
  const [diffs, setDiffs] = useState<DiffSummary[] | null>(null);
  const [terminal, setTerminal] = useState<TerminalLine[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const connection = await runtimeConnection();
        const surface = new SurfaceClient(
          connection.base_url,
          connection.bearer_token,
        );
        if (cancelled) return;
        setClient(surface);
        setPhase({ kind: "ready" });
        setNotice("Runtime connected. Open a session or continue an existing one.");
      } catch (error) {
        if (!cancelled) {
          setPhase({ kind: "error", message: String(error) });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function openSession(): Promise<void> {
    if (client === null) return;
    try {
      const opened = await client.openSession("interactive canvas session");
      setSnapshot(opened);
      setThread(await resumeThread(client, opened.session.task_id, 0));
      setFiles(await fetchFiles(client.baseUrlFor(), client.tokenFor(), opened.session.task_id, fetch));
      setOverview(await fetchOverview(client.baseUrlFor(), client.tokenFor(), opened.session.task_id, fetch));
      const events = await client.events(opened.session.task_id, 0, 0);
      setDiffs(recentDiffs(events.events));
      setTerminal(terminalEvents(events.events));
    } catch (error) {
      setNotice(`error: ${String(error)}`);
    }
  }

  async function sendTurn(): Promise<void> {
    if (client === null || snapshot === null || draft.trim() === "") return;
    try {
      const response = await client.runTurn(snapshot.session.session_id, draft);
      setSnapshot(response.snapshot);
      setDraft("");
      if (response.snapshot.pending_approval !== null) {
        setNotice(
          `approval required for ${response.snapshot.pending_approval.capability_id}`,
        );
      } else {
        setNotice(response.text || `[${response.stop_reason}]`);
      }
      setThread(await resumeThread(client, snapshot.session.task_id, thread?.nextSequence ?? 0));
    } catch (error) {
      setNotice(`error: ${String(error)}`);
    }
  }

  async function decideApproval(disposition: ApprovalDisposition): Promise<void> {
    if (client === null || snapshot === null) return;
    const pending = pendingApproval(snapshot);
    if (pending === null) return;
    try {
      const response = await decidePendingApproval(
        client,
        snapshot.session.session_id,
        pending,
        disposition,
        disposition === "APPROVE" ? "approved from canvas" : "rejected from canvas",
      );
      setSnapshot(response.snapshot);
      setNotice(response.text || `[${response.stop_reason}]`);
    } catch (error) {
      setNotice(`error: ${String(error)}`);
    }
  }

  if (phase.kind === "connecting") {
    return <main>Connecting to the local runtime…</main>;
  }
  if (phase.kind === "error") {
    return <main>Runtime unavailable: {phase.message}</main>;
  }

  return (
    <main style={{ display: "flex", height: "100vh", fontFamily: "system-ui" }}>
      <nav style={{ width: 180, borderRight: "1px solid #ccc", padding: 12 }}>
        <h2>Workspaces</h2>
        <button onClick={openSession}>New session</button>
        <select
          value={layout.id}
          onChange={(event) => {
            if (event.target.value === layout.id) return;
            const candidate: LayoutTemplate = {
              ...DEFAULT_TEMPLATE,
              id: event.target.value,
              name: event.target.value,
            };
            if (validateTemplate(candidate) === null) {
              setLayout(candidate);
            }
          }}
        >
          <option value={DEFAULT_TEMPLATE.id}>{DEFAULT_TEMPLATE.name}</option>
          <option value="layout:focus">Focus</option>
        </select>
        <p style={{ fontSize: 12 }}>{notice}</p>
      </nav>
      <section style={{ flex: 1, padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
        <header>
          <h1>Agent OS</h1>
          <p>
            Session: {snapshot?.session.session_id ?? "—"} · Status:{" "}
            {snapshot?.status ?? "—"} · Sequence: {snapshot?.event_sequence ?? 0}
          </p>
        </header>
        <section style={{ display: "grid", gap: 12, flex: 1, minHeight: 0, gridTemplateColumns: "1fr 1fr 1fr" }}>
          <div style={{ border: "1px solid #ddd", padding: 12, overflow: "auto", width: "32%" }}>
            <h3>Agent Thread</h3>
            {thread === null ? (
              <p>No session yet.</p>
            ) : thread.messages.length === 0 ? (
              <p>No messages yet.</p>
            ) : (
              <ul>
                {thread.messages.map((message) => (
                  <li key={message.sequence}>
                    #{message.sequence} {message.kind}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div style={{ border: "1px solid #ddd", padding: 12, overflow: "auto", width: "32%" }}>
            <h3>Evidence and Approval</h3>
            {snapshot?.pending_approval ? (
              <div>
                <p>{snapshot.pending_approval.capability_id}</p>
                <pre style={{ fontSize: 12 }}>{snapshot.pending_approval.preview}</pre>
                <button onClick={() => void decideApproval("APPROVE")}>Approve</button>
                <button onClick={() => void decideApproval("REJECT")}>Reject</button>
              </div>
            ) : (
              <p>No pending approval.</p>
            )}
          </div>
          <div style={{ border: "1px solid #ddd", padding: 12, overflow: "auto", width: "32%" }}>
            <h3>Files</h3>
            {files === null ? (
              <p>No session yet.</p>
            ) : (
              <ul>
                {files.map((entry) => (
                  <li key={entry.path}>
                    {entry.path} ({entry.size}B)
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div style={{ border: "1px solid #ddd", padding: 12, overflow: "auto", width: "48%" }}>
            <h3>Plan and Tasks</h3>
            {overview === null ? (
              <p>No session yet.</p>
            ) : (
              <ul>
                <li>task: {overview.task_id}</li>
                <li>task status: {overview.task_status}</li>
                <li>run status: {overview.run_status}</li>
                <li>receipts: {overview.receipt_count}</li>
              </ul>
            )}
          </div>
          <div style={{ border: "1px solid #ddd", padding: 12, overflow: "auto", width: "48%" }}>
            <h3>Diff</h3>
            {(() => {
          const ordered = [...layout.panels].sort(
            (a, b) => a.y - b.y || a.x - b.x,
          );
          return ordered.map((placement) => (
            <span key={placement.panel_id} style={{ display: "none" }}>
              {placement.panel_id}
            </span>
          ));
        })()}
        {diffs === null || diffs.length === 0 ? (
              <p>No diffs yet.</p>
            ) : (
              <ul>
                {diffs.map((diff) => (
                  <li key={diff.sequence}>
                    #{diff.sequence} {diff.path ?? "(no path)"}{" "}
                    {diff.truncated ? "(truncated)" : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div style={{ border: "1px solid #ddd", padding: 12, overflow: "auto", width: "48%" }}>
            <h3>Terminal</h3>
            {terminal === null || terminal.length === 0 ? (
              <p>No shell actions yet.</p>
            ) : (
              <ul>
                {terminal.map((line) => (
                  <li key={line.sequence}>
                    #{line.sequence} {line.summary}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {(Object.keys(closedShellMap()) as ClosedIntegrationId[]).map((panelId) => {
            const state = closedShellState(panelId, snapshot?.status ?? null);
            return (
              <div key={panelId} style={{ border: "1px solid #ddd", padding: 12, width: "23%" }}>
                <h3>{state.title}</h3>
                <p>{state.message}</p>
              </div>
            );
          })}
        </section>
        <footer style={{ display: "flex", gap: 8 }}>
          <input
            style={{ flex: 1 }}
            value={draft}
            placeholder="Type a request…"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void sendTurn();
            }}
          />
          <button onClick={() => void sendTurn()} disabled={snapshot === null}>
            Send
          </button>
        </footer>
      </section>
    </main>
  );
}
