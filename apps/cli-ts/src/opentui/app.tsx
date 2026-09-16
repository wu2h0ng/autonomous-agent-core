/**
 * P2 full-screen view: transcript + files/diff sidebar.
 *
 * View-only layer: SurfaceClient / TuiController / surface protocol are
 * unchanged.
 *
 * Focus policy (regression fix): the composer input owns keyboard focus at all
 * times — opentui focus is exclusive, so giving a panel `focused` would blur
 * the input and steal typing. `Tab` therefore only changes the *selected*
 * panel (shown in the title/header); `pgup`/`pgdn` scroll the selected panel via
 * an explicit `scrollBy`, and the mouse wheel scrolls whichever panel it is over.
 * Approvals stay global (y/n) and force the transcript to be selected so they
 * remain in front. Key ownership/precedence is resolved by the pure
 * `resolveViewKey` (src/opentui/viewkeys.ts) so the order is testable.
 */
/** @jsxImportSource @opentui/react */
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useKeyboard } from "@opentui/react";
import { SyntaxStyle, type ScrollBoxRenderable } from "@opentui/core";
import type { ChatMessage, TuiController } from "../controller.js";
import { handleGlobalKey } from "../keys.js";
import { layoutFor } from "../layout.js";
import { filterCommands } from "../commands.js";
import {
  filterSelectorItems,
  moveSelector,
  numberedChoice,
} from "../selector.js";
import { sliceWindow } from "./overlays.js";
import { resolveViewKey } from "./viewkeys.js";
import { activeMention, applyMention, filterMentions } from "../mentions.js";
import { InputHistory } from "../history.js";
import { openExternalEditor } from "../editor.js";
import {
  backspace,
  cursorLineCol,
  deleteForward,
  deleteLine,
  deleteToLineEnd,
  deleteWordForward,
  insertNewline,
  insertText,
  lineCount,
  isMultiline,
  move,
  moveWord,
  type ComposerState,
} from "../composer.js";
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
  planEnter,
  repositionCursor,
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
  // Self-owned composer: value + caret. The native <input> was single-line and
  // consumed most keys, which blocked multiline editing and vim; owning it lets
  // composer.ts drive every edit and gives mentions a real caret.
  const [composer, setComposer] = useState<ComposerState>({ value: "", cursor: 0 });
  const input = composer.value;
  const setComposerValue = (value: string, caret = value.length): void => {
    setComposer({ value, cursor: caret });
  };
  const [selected, setSelected] = useState<PanelId>("transcript");
  const [width, setWidth] = useState(terminalWidth);
  const [sample, setSample] = useState<WorkspaceSample>(EMPTY_SAMPLE);
  const [tree, setTree] = useState<AgentTreeResult>(EMPTY_TREE);
  const [cursor, setCursor] = useState(0);
  const [selectorQuery, setSelectorQuery] = useState("");
  const [selectorIndex, setSelectorIndex] = useState(0);
  const [paletteIndex, setPaletteIndex] = useState(0);
  const [files, setFiles] = useState<string[]>([]);
  const syntaxStyle = useMemo(() => SyntaxStyle.create(), []);
  const historyRef = useRef<InputHistory | null>(null);
  if (historyRef.current === null) historyRef.current = new InputHistory();
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
  // The full-screen composer is a single-line input, so the caret is taken to be
  // at the end of the text (adequate for `@path` completion while typing).
  const mention = activeMention(input, composer.cursor);
  const mentionMatches = mention ? filterMentions(files, mention.query) : [];

  const selector = controller.pendingSelector;
  const selectorItems = selector
    ? filterSelectorItems(selector.items, selectorQuery)
    : [];
  const selectorState = { items: selectorItems, index: selectorIndex };
  const palette = input.startsWith("/") && !input.includes(" ")
    ? filterCommands(input)
    : [];

  useEffect(() => {
    setPaletteIndex(0);
  }, [input]);

  useEffect(() => {
    if (mention === null) return;
    let cancelled = false;
    void controller
      .workspaceFiles()
      .then((entries) => {
        if (!cancelled) setFiles(entries.map((entry) => entry.path));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [mention?.query, controller]);

  // Render the draft with a visible caret block; a caret at the end of a line
  // is shown after the last character.
  const caret = cursorLineCol(composer);
  const composerLines = composer.value.split("\n").map((row, index) => {
    if (index !== caret.line) return row;
    const before = row.slice(0, caret.column);
    const after = row.slice(caret.column);
    return `${before}▌${after}`;
  });
  const composerHeight = Math.min(2 + composerLines.length, 8);

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


  useKeyboard((key: { name?: string; ctrl?: boolean; sequence?: string }) => {
    const name = key.name ?? "";
    const ctrl = key.ctrl === true;
    const sequence = key.sequence ?? "";
    if (process.env.NOEM_KEY_DEBUG === "1") {
      process.stderr.write(`DBGKEY name=${name} seq=${JSON.stringify(sequence)} ctrl=${ctrl}\n`);
    }
    const owner = resolveViewKey({
      selectorOpen: selector,
      awaitingApproval: awaiting,
      paletteOpen: palette.length > 0,
      mentionOpen: mentionMatches.length > 0,
      activePanel,
      name,
      ctrl,
      sequence,
    });

    if (process.env.NOEM_KEY_DEBUG === "1") {
      process.stderr.write(`DBGLAYER ${owner.layer} ${JSON.stringify(owner)}\n`);
    }
    switch (owner.layer) {
      case "selector": {
        if (name === "escape") {
          controller.cancelSelector();
          setSelectorQuery("");
          setSelectorIndex(0);
          return;
        }
        if (name === "return") {
          const pick = selectorItems[
            Math.min(selectorIndex, Math.max(0, selectorItems.length - 1))
          ];
          if (pick !== undefined) controller.chooseSelector(pick);
          setSelectorQuery("");
          return;
        }
        if (name === "up" || name === "down") {
          const next = moveSelector(selectorState, name === "down" ? 1 : -1);
          setSelectorIndex(next.index);
          return;
        }
        if (name === "backspace") {
          setSelectorQuery((q) => q.slice(0, -1));
          setSelectorIndex(0);
          return;
        }
        if (/^[1-9]$/.test(sequence) && selectorQuery === "") {
          const pick = numberedChoice(selectorState, Number(sequence));
          if (pick !== undefined) controller.chooseSelector(pick);
          return;
        }
        if (/^[\x20-\x7e]$/.test(sequence)) {
          setSelectorQuery((q) => q + sequence);
          setSelectorIndex(0);
          return;
        }
        return;
      }
      case "approval": {
        if (owner.action === "approve") void controller.approve();
        else if (owner.action === "reject") void controller.reject();
        return;
      }
      case "global": {
        handleGlobalKey(controller, name, { ctrl, escape: name === "escape" });
        return;
      }
      case "palette": {
        if (owner.action === "up" || owner.action === "down") {
          const step = owner.action === "down" ? 1 : -1;
          setPaletteIndex((i) => (i + step + palette.length) % palette.length);
          return;
        }
        if (owner.action === "complete" || owner.action === "submit") {
          const pick = palette[Math.min(paletteIndex, palette.length - 1)];
          if (pick === undefined) return;
          process.stderr.write(`DBGPALETTE input=${JSON.stringify(input)} pick=${pick.name} n=${palette.length}\n`);
          if (owner.action === "complete") {
            setComposerValue(`${pick.name} `);
            setPaletteIndex(0);
          } else {
            submit(pick.name);
          }
          return;
        }
        return;
      }
      case "mention": {
        if (owner.action === "complete" && mention !== null) {
          const pick = mentionMatches[0];
          if (pick !== undefined) {
            const applied = applyMention(input, composer.cursor, pick);
            setComposer({ value: applied.value, cursor: applied.cursor });
          }
        }
        return;
      }
      case "history": {
        if (historyRef.current === null) return;
        // A multiline draft keeps the arrows for caret movement (Ink parity).
        if (isMultiline(composer)) {
          setComposer((c) => move(c, owner.action === "prev" ? "up" : "down"));
          return;
        }
        setComposerValue(owner.action === "prev" ? historyRef.current.prev(input) : historyRef.current.next());
        return;
      }
      case "editor": {
        const result = openExternalEditor(input);
        if (result !== null && result.changed) setComposerValue(result.text);
        return;
      }
      case "panel": {
        if (owner.action === "switch") {
          setSelected(nextPanel(activePanel, panels));
          return;
        }
        if (owner.action === "scroll") {
          const target = scrollRefs[activePanel]?.current;
          target?.scrollBy(
            (owner.delta ?? 1) * PANEL_SCROLL_LINES,
            "absolute",
          );
          return;
        }
        return;
      }
      case "agents": {
        setCursor((current) => moveCursor(current, owner.delta, tree.rows.length));
        return;
      }
      case "composer": {
        if (owner.action === "insert") {
          const pasted = sequence
            .replace(/\r\n?/g, "\n")
            .replace(/[\u0000-\u0009\u000b-\u001f\u007f]/g, "");
          if (pasted !== "") setComposer((c) => insertText(c, pasted));
          return;
        }
        if (owner.action === "newline") {
          setComposer((c) => insertNewline(c));
          return;
        }
        if (owner.action === "backspace") {
          setComposer((c) => backspace(c));
          return;
        }
        if (owner.action === "delete") {
          setComposer((c) => deleteForward(c));
          return;
        }
        if (owner.action === "delete-word") {
          setComposer((c) => deleteWordForward(c));
          return;
        }
        if (owner.action === "delete-to-line-end") {
          setComposer((c) => deleteToLineEnd(c));
          return;
        }
        if (owner.action === "delete-line") {
          setComposer((c) => deleteLine(c));
          return;
        }
        if (owner.action === "move") {
          if (owner.dir !== undefined) setComposer((c) => move(c, owner.dir!));
          return;
        }
        if (owner.action === "move-word") {
          if (owner.motion !== undefined) setComposer((c) => moveWord(c, owner.motion!));
          return;
        }
        return;
      }
      case "enter": {
        const plan = planEnter(activePanel, tree.rows, cursor, input);
        if (plan.kind === "resume") void controller.submit(`/resume ${plan.sessionId}`);
        else if (plan.kind === "submit") submit(plan.text);
        return;
      }
      default:
        return;
    }
  });

  const submit = (value: string): void => {
    const text = value.trim();
    if (!text) return;
    historyRef.current?.add(text);
    setComposer({ value: "", cursor: 0 });
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
        {finalized.map((message, index) =>
          message.role === "assistant" && !message.panel && !message.tool ? (
            <markdown key={`f${index}`} content={message.content} syntaxStyle={syntaxStyle} />
          ) : (
            <text key={`f${index}`}>{line(message)}</text>
          ),
        )}
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
      {mentionMatches.length > 0 ? (
        <box border title="files" style={{ flexDirection: "column", paddingLeft: 1 }}>
          {mentionMatches.slice(0, 8).map((path, index) => (
            <text key={`m${index}`}>{`${index === 0 ? "▌ " : "  "}@${path}`}</text>
          ))}
          <text>{"[tab] complete"}</text>
        </box>
      ) : null}
      {selector ? (
        <box border title={selector.title} style={{ flexDirection: "column", paddingLeft: 1 }}>
          {(() => {
            const window = sliceWindow(selectorItems, selectorIndex, 8);
            return window.items.map((item, index) => (
              <text key={`s${index}`}>
                {`${index === window.index ? "▌ " : "  "}${item}`}
              </text>
            ));
          })()}
          <text>{`${selectorQuery ? `filter: ${selectorQuery}` : "↑/↓ move · 1-9 pick · enter select · esc cancel"}`}</text>
        </box>
      ) : null}
      {palette.length > 0 ? (
        <box border title="commands" style={{ flexDirection: "column", paddingLeft: 1 }}>
          {(() => {
            const window = sliceWindow(palette, paletteIndex, 6);
            return window.items.map((command, index) => (
              <text key={`c${index}`}>
                {`${index === window.index ? "▌ " : "  "}${command.name}${layout.showDescriptions && command.description ? `  ${command.description}` : ""}`}
              </text>
            ));
          })()}
        </box>
      ) : null}
      <box
        border
        title={`message${isMultiline(composer) ? ` (${lineCount(composer.value)} lines)` : ""}`}
        style={{ height: composerHeight, paddingLeft: 1, flexDirection: "column" }}
      >
        {composerLines.map((line, index) => (
          <text key={`c${index}`}>{`${index === caret.line ? "› " : "  "}${line}`}</text>
        ))}
      </box>
      <text>{`${input === "" ? "[ctrl+j] newline · [ctrl+g] $EDITOR · " : ""}❯ ${controller.mode}${model ? ` · ${model}` : ""}${
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
