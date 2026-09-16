/**
 * P2 full-screen view: transcript + files/diff sidebar.
 *
 * View-only layer: SurfaceClient / TuiController / surface protocol are
 * unchanged.
 *
 * Focus policy (regression fix): the composer input owns keyboard focus at all
 * times — opentui focus is exclusive, so giving a panel `focused` would blur
 * the input and steal typing. `Tab` therefore only changes the *selected*
 * panel (shown in the title/header); keyboard scrolling of a panel is done
 * explicitly via `scrollBy` on the selected panel, and the mouse wheel scrolls
 * whichever panel it is over. Approvals stay global (y/n) and force the
 * transcript to be selected so they remain in front.
 */
/** @jsxImportSource @opentui/react */
import { useEffect, useReducer, useRef, useState } from "react";
import { useKeyboard } from "@opentui/react";
import type { ScrollBoxRenderable } from "@opentui/core";
import type { ChatMessage, TuiController } from "../controller.js";
import { handleGlobalKey } from "../keys.js";
import { layoutFor } from "../layout.js";
import {
  filePanelLines,
  nextPanel,
  visiblePanels,
  type PanelId,
} from "./panels.js";
import { EMPTY_SAMPLE, sampleWorkspace, type WorkspaceSample } from "./workspace-panels.js";
import {
  agentRowLine,
  clampCursor,
  cursorKey,
  moveCursor,
  repositionCursor,
  resumableSessionId,
} from "./agents.js";
import { fetchAgentTree, type AgentTreeResult } from "./agent-tree-source.js";
import type { SurfaceClient } from "../client.js";

export interface FullscreenAppProps {
  controller: TuiController;
  workspace: string;
  branch: string | null;
  version: string;
  model: string | null;
  client: SurfaceClient;
  withPanels?: boolean;
  withAgents?: boolean;
}

const EMPTY_TREE: AgentTreeResult = { rows: [], truncated: false, note: null };
const TREE_INTERVAL_MS = 5000;

const PANEL_SCROLL_LINES = 5;
const SAMPLE_INTERVAL_MS = 3000;

function line(message: ChatMessage): string {
  if (message.panel) {
    return [message.panel.title, ...message.panel.lines].join("  ");
  }
  if (message.tool) {
    const icon =
      message.tool.status === "done"
        ? "☑"
        : message.tool.status === "failed"
          ? "✗"
          : "⏵";
    return `${icon} ${message.tool.capabilityId} · ${message.tool.argsSummary}`;
  }
  const prefix =
    message.role === "user" ? "› " : message.role === "system" ? "⏵ " : "";
  return prefix + message.content;
}

function terminalWidth(): number {
  return process.stdout.columns ?? 80;
}

export function App({
  controller,
  workspace,
  branch,
  version,
  model,
  client,
  withPanels = true,
  withAgents = true,
}: FullscreenAppProps) {
  const [, bump] = useReducer((tick: number) => tick + 1, 0);
  const [input, setInput] = useState("");
  const [selected, setSelected] = useState<PanelId>("transcript");
  const [width, setWidth] = useState(terminalWidth);
  const [sample, setSample] = useState<WorkspaceSample>(EMPTY_SAMPLE);
  const [tree, setTree] = useState<AgentTreeResult>(EMPTY_TREE);
  const [cursor, setCursor] = useState(0);
  const cursorKeyRef = useRef<string | null>(null);
  const transcriptRef = useRef<ScrollBoxRenderable | null>(null);
  const agentsRef = useRef<ScrollBoxRenderable | null>(null);
  const filesRef = useRef<ScrollBoxRenderable | null>(null);
  const diffRef = useRef<ScrollBoxRenderable | null>(null);

  useEffect(
    () =>
      controller.subscribe(() => {
        bump();
        if (controller.status === "closed") process.exit(0);
      }),
    [controller],
  );
  useEffect(() => {
    const timer = setInterval(() => controller.tick(), 500);
    return () => clearInterval(timer);
  }, [controller]);
  useEffect(() => {
    const onResize = (): void => setWidth(terminalWidth());
    process.stdout.on("resize", onResize);
    return () => {
      process.stdout.off("resize", onResize);
    };
  }, []);
  useEffect(() => {
    if (!withPanels) {
      setSample(EMPTY_SAMPLE);
      return;
    }
    let cancelled = false;
    let inFlight = false;
    const run = async (): Promise<void> => {
      if (inFlight) return;
      inFlight = true;
      const next = await sampleWorkspace(workspace);
      inFlight = false;
      if (!cancelled) setSample(next);
    };
    void run();
    const timer = setInterval(() => void run(), SAMPLE_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [workspace, withPanels]);

  cursorKeyRef.current = cursorKey(tree.rows, cursor);
  const snapshot = controller.currentSnapshot;
  const pending = snapshot?.pending_approval;
  const awaiting = controller.status === "awaiting_approval";

  const panels = visiblePanels(width, withPanels, withAgents);
  // Approvals are global and must stay in front: force the transcript selected.
  const activePanel: PanelId = awaiting
    ? "transcript"
    : panels.includes(selected)
      ? selected
      : "transcript";
  const scrollRefs: Record<PanelId, React.RefObject<ScrollBoxRenderable | null>> = {
    transcript: transcriptRef,
    agents: agentsRef,
    files: filesRef,
    diff: diffRef,
  };

  const showAgentsPanel = panels.includes("agents");
  useEffect(() => {
    if (!showAgentsPanel) {
      setTree(EMPTY_TREE);
      return;
    }
    let cancelled = false;
    let inFlight = false;
    const run = async (): Promise<void> => {
      if (inFlight) return;
      inFlight = true;
      const next = await fetchAgentTree(client);
      inFlight = false;
      if (!cancelled) {
        setTree(next);
        // Keep the same ROW highlighted across refreshes (index can shift).
        setCursor((current) =>
          repositionCursor(next.rows, cursorKeyRef.current, current),
        );
      }
    };
    void run();
    const timer = setInterval(() => void run(), TREE_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [client, showAgentsPanel]);


  useKeyboard((key: { name?: string; ctrl?: boolean }) => {
    const name = key.name ?? "";
    // Reuse the tested frozen mapping: Esc (streaming/stalled) and Ctrl-C ->
    // controller.interrupt(); Esc is always consumed and never approves/rejects.
    if (handleGlobalKey(controller, name, { ctrl: key.ctrl === true, escape: name === "escape" })) {
      return;
    }
    if (awaiting) {
      if (name === "y") void controller.approve();
      else if (name === "n") void controller.reject();
      return;
    }
    if (name === "tab") {
      setSelected(nextPanel(activePanel, panels));
      return;
    }
    if (name === "pageup" || name === "pagedown") {
      const target = scrollRefs[activePanel]?.current;
      const delta = name === "pageup" ? -PANEL_SCROLL_LINES : PANEL_SCROLL_LINES;
      target?.scrollBy(delta, "absolute");
      return;
    }
    // The agents panel owns ctrl+up/down (cursor) and Enter (switch session).
    // Plain arrows/letters stay with the composer, which keeps keyboard focus.
    const down = name === "down" || name === "n";
    const up = name === "up" || name === "p";
    if (activePanel === "agents" && key.ctrl === true && (down || up)) {
      setCursor((current) => moveCursor(current, down ? 1 : -1, tree.rows.length));
      return;
    }
    if (name === "return") {
      if (activePanel === "agents") {
        const target = resumableSessionId(tree.rows, cursor);
        // Only a session row switches; on any other row Enter falls through so
        // composer text can still be submitted.
        if (target !== null) {
          // Reuses the /resume path. The controller refuses it whenever a turn
          // or an approval is pending, so a switch can never abandon a turn or
          // move an approval surface out of view.
          void controller.submit(`/resume ${target}`);
          return;
        }
      }
      submit(input);
    }
  });

  const submit = (value: string): void => {
    const text = value.trim();
    if (!text) return;
    setInput("");
    void controller.submit(text);
  };

  const name = workspace.split("/").filter(Boolean).pop() ?? workspace;
  const finalized = controller.messages.slice(0, controller.finalizedIndex);
  const active = controller.messages.slice(controller.finalizedIndex);
  const layout = layoutFor(width);

  const transcript = (
    <scrollbox
      ref={transcriptRef}
      style={{ flexGrow: 1, border: true }}
      title={`transcript · ${activePanel === "transcript" ? "selected" : "sticky-follow"}`}
      stickyScroll
      stickyStart="bottom"
    >
      <box style={{ flexDirection: "column", paddingLeft: 1 }}>
        {finalized.map((message, index) => (
          <text key={`f${index}`}>{line(message)}</text>
        ))}
        {active.map((message, index) => (
          <text key={`a${index}`}>{line(message)}</text>
        ))}
        {controller.reasoningText ? (
          <text>{`🧠 ${controller.reasoningText}`}</text>
        ) : null}
        {controller.status === "streaming" ? <text>streaming…</text> : null}
        {controller.lastError ? (
          <text>{`error: ${controller.lastError}`}</text>
        ) : null}
        {pending ? (
          <box
            border
            title="approval"
            style={{ flexDirection: "column", paddingLeft: 1 }}
          >
            <text>{`🛡 human approval required — ${pending.capability_id}`}</text>
            {String(pending.preview ?? "")
              .split("\n")
              .slice(0, 6)
              .map((row, index) => (
                <text key={`p${index}`}>{row}</text>
              ))}
            <text>{`digest ${pending.action_digest.slice(0, 16)}… · [y] approve · [n] reject`}</text>
          </box>
        ) : null}
      </box>
    </scrollbox>
  );

  const sidebar = (
    <box style={{ flexDirection: "column", width: 40 }}>
      {panels.includes("agents") ? (
      <scrollbox
        ref={agentsRef}
        style={{ flexGrow: 2, border: true }}
        title={`agents${activePanel === "agents" ? " · selected" : ""}`}
      >
        <box style={{ flexDirection: "column", paddingLeft: 1 }}>
          {(tree.rows.length > 0
            ? tree.rows.map((row, index) =>
                index === clampCursor(cursor, tree.rows.length)
                  ? `▌ ${agentRowLine(row)}`
                  : `  ${agentRowLine(row)}`,
              )
            : [tree.note ?? "(no mandates)"]
          )
            .concat(tree.truncated ? ["(truncated)"] : [])
            .concat(tree.note && tree.rows.length > 0 ? [tree.note] : [])
            .map((row, index) => (
              <text key={`g${index}`}>{row}</text>
            ))}
        </box>
      </scrollbox>
      ) : null}
      <scrollbox
        ref={filesRef}
        style={{ flexGrow: 1, border: true }}
        title={`files${activePanel === "files" ? " · selected" : ""}`}
      >
        <box style={{ flexDirection: "column", paddingLeft: 1 }}>
          {filePanelLines(sample.files, sample.note).map((row, index) => (
            <text key={`x${index}`}>{row}</text>
          ))}
        </box>
      </scrollbox>
      <scrollbox
        ref={diffRef}
        style={{ flexGrow: 2, border: true }}
        title={`diff${activePanel === "diff" ? " · selected" : ""}`}
      >
        <box style={{ flexDirection: "column", paddingLeft: 1 }}>
          {(sample.diff.length > 0 ? sample.diff : ["(no unstaged diff)"]).map(
            (row, index) => (
              <text key={`d${index}`}>{row}</text>
            ),
          )}
        </box>
      </scrollbox>
    </box>
  );

  return (
    <box style={{ flexDirection: "column", width: "100%", height: "100%" }}>
      <text>{`◆ noem v${version}   ${name}${branch ? ` · ${branch}` : ""} · ${controller.mode} · ${activePanel}`}</text>
      <box style={{ flexDirection: "row", flexGrow: 1 }}>
        {transcript}
        {panels.length > 1 ? sidebar : null}
      </box>
      <box border title="message" style={{ height: 3, paddingLeft: 1 }}>
        <input
          placeholder="Tell Noem what to do… (Enter to send)"
          focused={!awaiting}
          value={input}
          onInput={setInput}
        />
      </box>
      <text>{`❯ ${controller.mode}${model ? ` · ${model}` : ""}${
        snapshot && layout.footerFields
          ? ` · ${controller.tokensTotal} tok · cost UNKNOWN · ev ${snapshot.event_sequence}`
          : ""
      } · ${
        panels.length > 1
          ? activePanel === "agents"
            ? `[tab] panel: agents · [ctrl+↑/↓] move · [enter] switch session`
            : `[tab] panel: ${activePanel} · [pgup/pgdn] scroll`
          : "/help"
      }`}</text>
    </box>
  );
}
