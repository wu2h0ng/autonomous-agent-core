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
import { SyntaxStyle, type ScrollBoxRenderable, type TextareaRenderable } from "@opentui/core";
import type { ChatMessage, TuiController } from "../controller.js";
import { toolState } from "../controller.js";
import type { ComposerState } from "../composer.js";
import { handleGlobalKey } from "../keys.js";
import { layoutFor, composerRows } from "../layout.js";
import { filterCommands } from "../commands.js";
import {
  filterSelectorItems,
  moveSelector,
  numberedChoice,
} from "../selector.js";
import { overlayRows, sliceWindow } from "./overlays.js";
import { resolveViewKey } from "./viewkeys.js";
import { viewTheme } from "./theme-colors.js";
import { codeBlockRenderNode, highlightStyleTable } from "./code-highlight.js";
import { HomePanel } from "./home-panel.js";
import { shouldShowHome } from "../home.js";
import type { ThemeColors } from "../theme.js";
import { applyVimAction, offsetFromCursor, resolveVimKey } from "./vim.js";
import { activeMention, applyMention, filterMentions } from "../mentions.js";
import { InputHistory } from "../history.js";
import { openExternalEditor } from "../editor.js";
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
  /** Real provider id, or null when unconfigured (matches Ink's status line). */
  provider?: string | null;
  model: string | null;
  client: SurfaceClient;
  /** Persisted input history, so Ctrl-R survives a restart (Ink parity). */
  initialHistory?: readonly string[] | undefined;
  onHistoryChange?: ((entries: string[]) => void) | undefined;
  withPanels?: boolean;
  withAgents?: boolean;
}

const EMPTY_TREE: AgentTreeResult = { rows: [], truncated: false, note: null };
const TREE_INTERVAL_MS = 5000;

const PANEL_SCROLL_LINES = 5;
const SAMPLE_INTERVAL_MS = 3000;

/**
 * #16: fenced-code highlighting hook for every `<markdown>` in the transcript.
 * The bundled tree-sitter grammars cover only js/ts/markdown/zig, so a
 * ```python fence rendered with no highlights at all; `codeBlockRenderNode`
 * attaches our own ranges through CodeRenderable's supported `onHighlight`.
 * Module-scope stable, so a re-render never rebuilds the blocks.
 */
const CODE_BLOCK_RENDER_NODE = codeBlockRenderNode();

/**
 * One row of an overlay list (commands / selector / files / reverse search).
 *
 * `height: 1` is load-bearing: a sibling `<text>` inside a flex COLUMN measures
 * zero height in opentui, so without it every row of an overlay collapsed onto a
 * single line — and onto the border row — which is why overlay contents could
 * only ever be asserted by behaviour rather than by reading the frame.
 */
function OverlayRow({ text, fg }: { text: string; fg?: string | undefined }) {
  // `fg` is spread conditionally: with exactOptionalPropertyTypes an explicit
  // `fg={undefined}` is not assignable to the renderable's `fg`.
  return (
    <text style={{ height: 1 }} {...(fg === undefined ? {} : { fg })}>
      {text}
    </text>
  );
}

function line(message: ChatMessage): string {
  if (message.panel) {
    return [message.panel.title, ...message.panel.lines].join("  ");
  }
  if (message.tool) {
    const result = message.tool.resultSummary ? ` · ${message.tool.resultSummary}` : "";
    return `${TOOL_MARKER[toolState(message.tool)]} ${message.tool.capabilityId} · ${message.tool.argsSummary}${result}`;
  }
  const prefix =
    message.role === "user" ? "› " : message.role === "system" ? "⏵ " : "";
  return prefix + message.content;
}

/**
 * Tool-card marker. `☑` is a confirmed success; `⚠` is a confirmed dispatch
 * whose OWN result reported failure (non-zero exit code / tool-reported error)
 * — rendering a failing `workspace.run_tests` with the same `☑` as a passing
 * one was the S1 audit defect; `✗` is a dispatch that did not succeed; `⏵` is
 * not yet confirmed.
 */
const TOOL_MARKER: Record<ReturnType<typeof toolState>, string> = {
  pending: "⏵",
  done: "☑",
  error: "⚠",
  failed: "✗",
};

function roleColour(theme: ThemeColors, message: ChatMessage): string {
  if (message.role === "user") return theme.user;
  if (message.role === "system") return theme.system;
  if (message.tool) {
    const state = toolState(message.tool);
    if (state === "failed" || state === "error") return theme.toolFailed;
    if (state === "done") return theme.toolDone;
    return theme.toolPending;
  }
  if (message.panel) return theme.notice;
  return theme.assistant;
}

function terminalWidth(): number {
  return process.stdout.columns ?? 80;
}

/** Terminal height for the composer's growth cap (#12 multiline). */
function terminalRows(): number {
  return process.stdout.rows ?? 24;
}

export function App({
  controller,
  workspace,
  branch,
  version,
  provider = null,
  model,
  client,
  initialHistory = [],
  onHistoryChange,
  withPanels = true,
  withAgents = true,
}: FullscreenAppProps) {
  const [, bump] = useReducer((tick: number) => tick + 1, 0);
  const [input, setInput] = useState("");
  const composerRef = useRef<TextareaRenderable | null>(null);
  /** Single text source of truth: the textarea owns the draft; this mirrors it
   * for the overlays (palette/mentions) and writes go through the buffer. */
  const setComposerText = (value: string): void => {
    const buffer = composerRef.current?.editBuffer;
    // Skip a no-op setText: the write is applied asynchronously and RESETS the
    // caret to the start, so calling it with an unchanged value (vim's A/I
    // motions) silently moved the caret before the following keystroke.
    if (buffer !== undefined && buffer.getText() !== value) buffer.setText(value);
    // setText leaves the caret at the start; put it at the end so the next
    // keystroke appends (otherwise typing prepends and backspace does nothing).
    buffer?.setCursorByOffset(value.length);
    setInput(value);
  };
  const syncComposer = (): void => {
    setInput(composerRef.current?.plainText ?? "");
  };
  // Read by the textarea's onSubmit: whenever the VIEW owns Enter (agents panel
  // session switch, or an overlay such as the palette/selector), the textarea
  // must not also submit - otherwise one Enter runs the action twice.
  const agentsPanelRef = useRef(false);
  const overlayOwnsEnterRef = useRef(false);
  /**
   * #14: synchronous mirrors of the search state. The router must see the new
   * value for the VERY NEXT key (the same trap the vim insert flag documents),
   * so the flag is written in the handler, not only via React state.
   */
  const searchOpenRef = useRef(false);
  const searchDraftRef = useRef("");
  const [selected, setSelected] = useState<PanelId>("transcript");
  const [width, setWidth] = useState(terminalWidth);
  const [sample, setSample] = useState<WorkspaceSample>(EMPTY_SAMPLE);
  const [tree, setTree] = useState<AgentTreeResult>(EMPTY_TREE);
  const [cursor, setCursor] = useState(0);
  const [selectorQuery, setSelectorQuery] = useState("");
  const [selectorIndex, setSelectorIndex] = useState(0);
  const [paletteIndex, setPaletteIndex] = useState(0);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchIndex, setSearchIndex] = useState(0);
  const [vimInsert, setVimInsert] = useState(true);
  // Synchronous mirror of vimInsert: the router must see the new mode for the
  // VERY NEXT key, which a React state update cannot guarantee.
  const vimInsertRef = useRef(true);
  const [pendingOp, setPendingOp] = useState<"d" | "c" | null>(null);
  const [files, setFiles] = useState<string[]>([]);
  const theme = viewTheme(controller.themeName);
  const syntaxStyle = useMemo(() => {
    const style = SyntaxStyle.create();
    // #16: register the scope vocabulary the code highlighter actually emits
    // (highlight.js token classes + tree-sitter capture names + `default`).
    for (const [scope, definition] of Object.entries(highlightStyleTable(theme))) {
      style.registerStyle(scope, definition);
    }
    return style;
  }, [controller.themeName]);
  const historyRef = useRef<InputHistory | null>(null);
  if (historyRef.current === null) historyRef.current = new InputHistory(initialHistory);
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
  // The composer is a textarea (multiline), but the overlay caret is still taken
  // to be at the end of the text: palette/mention completion therefore triggers at
  // the END of the draft only (a mid-text `@` does not complete).
  const mention = activeMention(input, input.length);
  const mentionMatches = mention ? filterMentions(files, mention.query) : [];

  const selector = controller.pendingSelector;
  const selectorItems = selector
    ? filterSelectorItems(selector.items, selectorQuery)
    : [];
  const selectorState = { items: selectorItems, index: selectorIndex };
  // #14: while the reverse search is open the composer holds the QUERY, so the
  // slash palette must stay out of the way (Ink gates its palette the same way).
  const palette = !searchOpen && input.startsWith("/") && !input.includes(" ")
    ? filterCommands(input)
    : [];
  const searchMatches = searchOpen ? (historyRef.current?.search(input) ?? []) : [];

  useEffect(() => {
    setPaletteIndex(0);
  }, [input]);

  useEffect(() => {
    setSearchIndex(0);
  }, [input, searchOpen]);

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
    // Fetch ONCE per open mention session. Depending on the query made every
    // keystroke cancel the previous fetch, so the last one could resolve into a
    // cleaned-up closure and `files` stayed empty (the completion then had
    // nothing to complete with).
  }, [mention !== null, controller]);

  const snapshot = controller.currentSnapshot;
  const pending = snapshot?.pending_approval;
  const awaiting = controller.status === "awaiting_approval";

  // `!searchOpen` (Ink gates vim on `!searchMode` too) is not cosmetic: without
  // it, Esc on the Ctrl-R overlay switched the composer to vim normal mode
  // instead of cancelling the search, and normal mode then swallowed every
  // following key — the overlay stayed up with no key left that could close it.
  const vimNormal =
    controller.vimMode &&
    !vimInsert &&
    !awaiting &&
    selector === null &&
    palette.length === 0 &&
    !searchOpen;

  /** Current draft + caret as a composer state (for the vim edits). */
  const composerState = (): ComposerState => {
    const buffer = composerRef.current;
    const value = buffer?.plainText ?? input;
    const cursor = buffer
      ? offsetFromCursor(value, buffer.editBuffer.getCursorPosition().row, buffer.editBuffer.getCursorPosition().col)
      : value.length;
    return { value, cursor };
  };


  const panels = visiblePanels(width, withPanels, withAgents);
  // Approvals are global and must stay in front: force the transcript selected.
  agentsPanelRef.current = !awaiting && panels.includes(selected) && selected === "agents";
  // `selector` is `null` (not `undefined`) when closed (controller.pendingSelector);
  // test `!== null`, otherwise this is always true and the composer can never submit.
  overlayOwnsEnterRef.current = awaiting || selector !== null || palette.length > 0 || searchOpen;
  searchOpenRef.current = searchOpen;
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


  useKeyboard((key: { name?: string; ctrl?: boolean; shift?: boolean; sequence?: string }) => {
    const name = key.name ?? "";
    const ctrl = key.ctrl === true;
    const sequence = key.sequence ?? "";
    const owner = resolveViewKey({
      selectorOpen: selector,
      searchOpen: searchOpenRef.current,
      awaitingApproval: awaiting,
      paletteOpen: palette.length > 0,
      mentionOpen: mentionMatches.length > 0,
      activePanel,
      vimNormal,
      vimInsertMode: controller.vimMode && vimInsertRef.current,
      streaming: controller.status === "streaming" || controller.status === "stalled",
      name,
      ctrl,
      sequence,
    });

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
      case "search": {
        if (owner.action === "open") {
          // Save the live draft, then turn the composer into the query box.
          // Update the ref FIRST so the very next key already routes as search.
          searchDraftRef.current = input;
          searchOpenRef.current = true;
          setSearchOpen(true);
          setSearchIndex(0);
          setComposerText("");
          return;
        }
        if (owner.action === "cancel") {
          searchOpenRef.current = false;
          setSearchOpen(false);
          setComposerText(searchDraftRef.current);
          return;
        }
        if (owner.action === "pick") {
          const pick = searchMatches[Math.min(searchIndex, Math.max(0, searchMatches.length - 1))];
          searchOpenRef.current = false;
          setSearchOpen(false);
          // No match: fall back to the saved draft (Ink does the same).
          setComposerText(pick ?? searchDraftRef.current);
          return;
        }
        if (owner.action === "up" || owner.action === "down") {
          if (searchMatches.length === 0) return;
          const step = owner.action === "down" ? 1 : -1;
          setSearchIndex((current) => {
            const next = current + step;
            return next < 0 ? 0 : next >= searchMatches.length ? searchMatches.length - 1 : next;
          });
          return;
        }
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
          if (owner.action === "complete") {
            setComposerText(`${pick.name} `);
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
            const applied = applyMention(input, input.length, pick);
            setComposerText(applied.value);
          }
        }
        return;
      }
      case "history": {
        if (historyRef.current === null) return;
        setComposerText(owner.action === "prev" ? historyRef.current.prev(input) : historyRef.current.next());
        return;
      }
      case "editor": {
        // Read the TEXTAREA, not the React mirror: bracketed paste never goes
        // through `useKeyboard`, so the mirror was stale (measured: 200 pasted
        // characters reached the editor as 0 bytes) and the write-back then
        // replaced the paste with the editor's output.
        const draft = composerRef.current?.plainText ?? input;
        const result = openExternalEditor(draft);
        if (result !== null && result.changed) setComposerText(result.text);
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
      case "vim": {
        const before = composerState();
        if (owner.action === "normal") {
          // Leave editing for vim normal mode. Update the ref FIRST so the next
          // key is already routed as normal mode, and blur the textarea.
          vimInsertRef.current = false;
          setVimInsert(false);
          composerRef.current?.blur();
          setPendingOp(null);
          return;
        }
        const action = resolveVimKey(name, pendingOp, key.shift === true);
        if (action.kind === "submit") {
          submit(composerRef.current?.plainText ?? input);
          return;
        }
        let target = before;
        let insert = false;
        if (action.kind === "clearPending") {
          setPendingOp(null);
        } else if (action.kind === "pending") {
          setPendingOp(action.op);
        } else if (action.kind !== "ignore") {
          const result = applyVimAction(before, action);
          target = result.state;
          insert = result.insert;
          setComposerText(result.state.value);
          composerRef.current?.editBuffer.setCursorByOffset(result.state.cursor);
          setPendingOp(null);
        }
        // The textarea has no readOnly and a blur is asynchronous, so it can
        // still insert the very key this layer just handled (observed: "A"
        // inserted as text while the A motion also ran). Restore the intended
        // text/caret on the next tick, after the renderable applied it.
        queueMicrotask(() => {
          const buffer = composerRef.current?.editBuffer;
          if (buffer === undefined) return;
          if (buffer.getText() !== target.value) buffer.setText(target.value);
          buffer.setCursorByOffset(target.cursor);
        });
        if (insert) {
          vimInsertRef.current = true;
          setVimInsert(true);
          composerRef.current?.focus();
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
        break;
    }
    // Mirror the textarea for the overlays AFTER the renderable has applied the
    // key (a synchronous read can lag by one keystroke, which desynced the
    // palette/mention layers).
    queueMicrotask(syncComposer);
  });

  const completeMention = (value: string): string => {
    const token = activeMention(value, value.length);
    if (token === null) return value;
    const first = filterMentions(files, token.query)[0];
    return first === undefined ? value : applyMention(value, value.length, first).value;
  };

  const submit = (value: string): void => {
    const text = completeMention(value).trim();
    if (!text) return;
    historyRef.current?.add(text);
    onHistoryChange?.(historyRef.current?.all() ?? []);
    // Single clearing point: every submit path (textarea onSubmit, palette
    // command, agents-panel fall-through) must empty the textarea buffer too,
    // otherwise the stale draft is mirrored back on the next keystroke.
    setComposerText("");
    void controller.submit(text);
  };

  const name = workspace.split("/").filter(Boolean).pop() ?? workspace;
  const finalized = controller.messages.slice(0, controller.finalizedIndex);
  const active = controller.messages.slice(controller.finalizedIndex);
  const layout = layoutFor(width);
  // #18: same rule as Ink's App (`finalized.length === 0 && active.length === 0`)
  // — the welcome panel owns an otherwise-empty transcript. The controller opens
  // its session lazily (ensureSession is only called by runTurn), so the panel
  // stays up until the first turn.
  const showHome = shouldShowHome(finalized.length, active.length);

  const transcript = (
    <scrollbox
      ref={transcriptRef}
      style={{ flexGrow: 1, border: true }}
      title={`transcript · ${activePanel === "transcript" ? "selected" : "sticky-follow"}`}
      stickyScroll
      stickyStart="bottom"
    >
      <box style={{ flexDirection: "column", paddingLeft: 1 }}>
        {showHome ? (
          <HomePanel
            input={{
              workspace,
              branch,
              version,
              provider,
              model,
              columns: width,
            }}
            theme={theme}
            narrow={layout.narrow}
          />
        ) : null}
        {finalized.map((message, index) =>
          message.role === "assistant" && !message.panel && !message.tool ? (
            <markdown
              key={`f${index}`}
              content={message.content}
              syntaxStyle={syntaxStyle}
              renderNode={CODE_BLOCK_RENDER_NODE}
              fg={theme.assistant}
            />
          ) : (
            <text key={`f${index}`} fg={roleColour(theme, message)}>
              {line(message)}
            </text>
          ),
        )}
        {active.map((message, index) => (
          <text key={`a${index}`} fg={roleColour(theme, message)}>
            {line(message)}
          </text>
        ))}
        {controller.reasoningText ? (
          <text>{`🧠 ${controller.reasoningText}`}</text>
        ) : null}
        {controller.stopRequested ? (
          <text>{`stopping… (stop requested; ends at the next safe point)`}</text>
        ) : controller.status === "streaming" ? (
          <text>streaming…</text>
        ) : null}
        {controller.lastError ? (
          <text>{`error: ${controller.lastError}`}</text>
        ) : null}
        {pending ? (
          <box
            border
            borderColor={theme.approvalBorder}
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
      <text style={{ height: 1 }} fg={theme.accent}>{`◆ noem v${version}   ${name}${branch ? ` · ${branch}` : ""} · ${controller.mode} · ${activePanel}`}</text>
      <box style={{ flexDirection: "row", flexGrow: 1, flexShrink: 1 }}>
        {transcript}
        {panels.length > 1 ? sidebar : null}
      </box>
      {searchOpen ? (
        (() => {
          // Windowed (not Ink's fixed first 5) because the full-screen's own
          // palette/selector overlays window the same way, so the highlighted
          // row can never scroll out of the list.
          const window = sliceWindow(searchMatches, searchIndex, 5);
          const content = 1 + Math.max(window.items.length, 1);
          return (
            <box
              border
              style={{
                flexDirection: "column",
                paddingLeft: 1,
                height: overlayRows(content),
              }}
            >
              <OverlayRow
                text={`reverse search (Ctrl-R): ${input || "…"}`}
                fg={theme.accent}
              />
              {window.items.map((match, index) => (
                <OverlayRow
                  key={`r${index}`}
                  text={`${index === window.index ? "› " : "  "}${match}`}
                  fg={index === window.index ? theme.paletteSelected : theme.notice}
                />
              ))}
              {searchMatches.length === 0 ? <OverlayRow text="no matching history" /> : null}
            </box>
          );
        })()
      ) : null}
      {!searchOpen && mentionMatches.length > 0 ? (
        <box
          border
          title="files"
          style={{
            flexDirection: "column",
            paddingLeft: 1,
            height: overlayRows(Math.min(mentionMatches.length, 8) + 1),
          }}
        >
          {mentionMatches.slice(0, 8).map((path, index) => (
            <OverlayRow key={`m${index}`} text={`${index === 0 ? "▌ " : "  "}@${path}`} />
          ))}
          <OverlayRow text="[tab] complete" />
        </box>
      ) : null}
      {selector ? (
        (() => {
          const window = sliceWindow(selectorItems, selectorIndex, 8);
          return (
            <box
              border
              title={selector.title}
              style={{
                flexDirection: "column",
                paddingLeft: 1,
                height: overlayRows(window.items.length + 1),
              }}
            >
              {window.items.map((item, index) => (
                <OverlayRow
                  key={`s${index}`}
                  text={`${index === window.index ? "▌ " : "  "}${item}`}
                />
              ))}
              <OverlayRow
                text={`${selectorQuery ? `filter: ${selectorQuery}` : "↑/↓ move · 1-9 pick · enter select · esc cancel"}`}
              />
            </box>
          );
        })()
      ) : null}
      {palette.length > 0 ? (
        (() => {
          const window = sliceWindow(palette, paletteIndex, 6);
          return (
            <box
              border
              title="commands"
              style={{
                flexDirection: "column",
                paddingLeft: 1,
                height: overlayRows(window.items.length),
              }}
            >
              {window.items.map((command, index) => (
                <OverlayRow
                  key={`c${index}`}
                  text={`${index === window.index ? "▌ " : "  "}${command.name}${layout.showDescriptions && command.description ? `  ${command.description}` : ""}`}
                />
              ))}
            </box>
          );
        })()
      ) : null}
      <box
        border
        title="message"
        style={{ height: composerRows(input, terminalRows()), paddingLeft: 1 }}
      >
        <textarea
          ref={composerRef}
          placeholder="Tell Noem what to do… (Enter to send · ctrl+j newline)"
          focused={!awaiting && !vimNormal}
          keyBindings={[
            { name: "return", action: "submit" },
            { name: "kpenter", action: "submit" },
            { name: "linefeed", action: "newline" },
          ]}
          onSubmit={() => {
            if (agentsPanelRef.current || overlayOwnsEnterRef.current) return;
            submit(composerRef.current?.plainText ?? "");
          }}
        />
      </box>
      <text style={{ height: 1 }}>{`❯ ${controller.mode}${model ? ` · ${model}` : ""}${
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
