/**
 * Ink view layer — renders TuiController state, forwards input.
 *
 * Wrap safety (M2 lesson): messages below `controller.finalizedIndex` render
 * through <Static> (appended to scrollback exactly once, never re-measured);
 * only the still-mutable tail renders in the dynamic area. Finalized
 * assistant messages render as markdown; the in-flight one renders raw.
 *
 * Composer (2026-09-13): App owns all key routing and delegates editing to
 * the pure composer.ts model — multi-line (Ctrl-J), $EDITOR (Ctrl-G), cursor
 * movement, slash palette, ↑/↓ history, Ctrl-R reverse search and `@file`
 * completion. Ink's single-line TextInput is no longer used.
 */
import React, { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Box, Static, Text, useApp, useInput, useStdout } from "ink";
import type { Key } from "ink";
import type { ChatMessage, ToolCall, TuiController } from "./controller.js";
import { formatDuration, formatToolDetail } from "./controller.js";
import { filterCommands } from "./commands.js";
import type { CommandSpec } from "./commands.js";
import {
  backspace,
  deleteForward,
  deleteLine,
  deleteToLineEnd,
  deleteWordForward,
  insertNewline,
  insertText,
  isMultiline,
  move,
  moveWord,
} from "./composer.js";
import type { ComposerState } from "./composer.js";
import { Composer } from "./ComposerView.js";
import { segmentPreview } from "./diff.js";
import {
  collectDiffEntries,
  editArgsToDiff,
  editDiffTooLarge,
  editPathFromArgs,
  hunkStarts,
  previewToDiff,
} from "./diffview.js";
import { openExternalEditor } from "./editor.js";
import { InputHistory } from "./history.js";
import { handleGlobalKey } from "./keys.js";
import { layoutFor } from "./layout.js";
import { renderMarkdown } from "./markdown.js";
import { activeMention, applyMention, filterMentions } from "./mentions.js";
import { filterSelectorItems } from "./selector.js";
import { attentionFor, attentionSequence } from "./attention.js";
import { highlightCode, languageForPath } from "./highlight.js";
import { paint, resolveTheme } from "./theme.js";
import type { ThemeColors } from "./theme.js";

const EMPTY: ComposerState = { value: "", cursor: 0 };
const PLACEHOLDER = "Tell the agent what to do… (Ctrl-J newline · Ctrl-G editor)";
const COMMENT_PLACEHOLDER = "approval comment — Enter approves with it · Esc cancels";

const TOOL_ICON: Record<ToolCall["status"], string> = {
  pending: "⏵",
  done: "✓",
  failed: "✗",
};

/** Overlay bounds: the dynamic area never becomes unbounded scrollback. */
const TOOL_LIST_WINDOW = 10;
const TOOL_ARG_MAX_LINES = 20;
const TOOL_DIFF_PREVIEW_LINES = 40;
const DIFF_MAX_ENTRIES = 20;
const DIFF_MAX_LINES = 400;

/** Modal overlay state (tool-call viewer / diff viewer). */
type Overlay =
  | { kind: "tools"; index: number }
  | { kind: "diff"; entry: number; offset: number };

function isPrintable(input: string, key: Key): boolean {
  if (!input) return false;
  if (key.ctrl || key.meta || key.escape) return false;
  if (key.upArrow || key.downArrow || key.leftArrow || key.rightArrow) return false;
  if (key.return || key.tab || key.backspace || key.delete) return false;
  if (key.pageUp || key.pageDown || key.home || key.end) return false;
  return !/[\u0000-\u001f]/.test(input);
}

function useTerminalWidth(): number {
  const { stdout } = useStdout();
  const fallback = (): number => stdout?.columns ?? process.stdout.columns ?? 80;
  const [width, setWidth] = useState<number>(fallback);
  useEffect(() => {
    const onResize = (): void => setWidth(fallback());
    stdout?.on("resize", onResize);
    onResize();
    return () => {
      stdout?.off("resize", onResize);
    };
  }, [stdout]);
  return width;
}

function MessageView({
  message,
  finalized,
  theme,
}: {
  message: ChatMessage;
  finalized: boolean;
  theme: ThemeColors;
}) {
  if (message.panel) {
    return (
      <Box flexDirection="column" borderStyle="round" borderColor={theme.accent}>
        <Text bold {...paint(theme.accent)}>
          {message.panel.title}
        </Text>
        {message.panel.lines.map((line, index) => (
          <Text key={index} {...paint(theme.notice)}>
            {line}
          </Text>
        ))}
      </Box>
    );
  }
  if (message.tool) {
    const tool = message.tool;
    const color =
      tool.status === "pending"
        ? theme.toolPending
        : tool.status === "done"
          ? theme.toolDone
          : theme.toolFailed;
    const duration = tool.durationMs === undefined ? "" : ` · ${formatDuration(tool.durationMs)}`;
    return (
      <Text {...paint(color)}>
        {TOOL_ICON[tool.status]} {tool.capabilityId}({tool.argsSummary}){duration}
      </Text>
    );
  }
  const prefix = message.role === "user" ? "> " : message.role === "system" ? "⏵ " : "";
  const color =
    message.role === "user" ? theme.user : message.role === "system" ? theme.system : theme.assistant;
  const body =
    message.role === "assistant" && finalized ? renderMarkdown(message.content) : message.content;
  return (
    <Text wrap="wrap" {...paint(color)}>
      {prefix}
      {body}
      {message.interrupted ? " [interrupted]" : ""}
    </Text>
  );
}

export function App({
  controller,
  initialHistory = [],
  onHistoryChange,
}: {
  controller: TuiController;
  initialHistory?: readonly string[];
  onHistoryChange?: (entries: string[]) => void;
}) {
  const { exit } = useApp();
  const { stdout } = useStdout();
  const [, bump] = useReducer((tick: number) => tick + 1, 0);
  const [composer, setComposer] = useState<ComposerState>(EMPTY);
  const [paletteDismissed, setPaletteDismissed] = useState(false);
  const [selected, setSelected] = useState(0);
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [searchMode, setSearchMode] = useState(false);
  const [searchDraft, setSearchDraft] = useState("");
  const [selectorIndex, setSelectorIndex] = useState(0);
  const [selectorQuery, setSelectorQuery] = useState("");
  const [vimInsert, setVimInsert] = useState(true);
  const [pendingOp, setPendingOp] = useState<"d" | "c" | null>(null);
  const [showReasoning, setShowReasoning] = useState(false);
  const [approvalComment, setApprovalComment] = useState(false);
  const [files, setFiles] = useState<string[]>([]);
  const historyRef = useRef<InputHistory | null>(null);
  if (historyRef.current === null) historyRef.current = new InputHistory(initialHistory);
  const history = historyRef.current;
  const prevStatus = useRef<string>(controller.status);
  const width = useTerminalWidth();
  const layout = layoutFor(width);

  useEffect(() => controller.subscribe(bump), [controller]);

  useEffect(() => {
    if (controller.status === "closed") exit();
  }, [controller.status, exit]);

  useEffect(() => {
    const timer = setInterval(() => controller.tick(), 500);
    return () => clearInterval(timer);
  }, [controller]);

  // Attention signal on status transitions (approval needed / turn done|failed).
  useEffect(() => {
    const previous = prevStatus.current;
    prevStatus.current = controller.status;
    const kind = attentionFor(previous, controller.status, controller.lastStopReason, controller.lastError);
    const sequence = attentionSequence(kind, {
      bell: process.env.AGENT_OS_BELL !== "0",
      notify: process.env.AGENT_OS_NOTIFY === "osc",
    });
    if (sequence) stdout?.write(sequence);
  }, [controller.status, controller.lastStopReason, controller.lastError, stdout]);

  const input = composer.value;
  const mention = activeMention(input, composer.cursor);
  const palette: CommandSpec[] = useMemo(() => {
    if (searchMode || paletteDismissed || !input.startsWith("/")) return [];
    return filterCommands(input);
  }, [input, searchMode, paletteDismissed]);
  const searchMatches = searchMode ? history.search(input) : [];
  const mentionMatches = mention ? filterMentions(files, mention.query) : [];

  useEffect(() => {
    setSelected(0);
  }, [input, searchMode]);

  useEffect(() => {
    setSelectorIndex(0);
    setSelectorQuery("");
  }, [controller.pendingSelector]);

  // Narrowing the list must not leave the cursor past the end (silent no-op).
  useEffect(() => {
    setSelectorIndex(0);
  }, [selectorQuery]);

  // Vim keymap always starts in insert mode when toggled.
  useEffect(() => {
    setVimInsert(true);
  }, [controller.vimMode]);

  useEffect(() => {
    setPendingOp(null);
  }, [vimInsert, controller.vimMode]);

  // `/edit`: pull the last message out of the controller into the composer.
  useEffect(() => {
    const text = controller.consumePendingComposer();
    if (text !== null) setComposer({ value: text, cursor: text.length });
  }, [controller.hasPendingComposer, controller]);

  // `/tools` and `/diff` ask the view to open an overlay (one-shot request).
  useEffect(() => {
    const request = controller.consumePendingOverlay();
    if (request === "tools") {
      const count = controller.messages.filter((message) => message.tool).length;
      setOverlay({ kind: "tools", index: Math.max(0, count - 1) });
    } else if (request === "diff") {
      setOverlay({ kind: "diff", entry: 0, offset: 0 });
    }
  }, [controller.hasPendingOverlay, controller]);

  // A resolved approval closes comment mode (the card is gone).
  useEffect(() => {
    if (controller.status !== "awaiting_approval") setApprovalComment(false);
  }, [controller.status]);

  useEffect(() => {
    if (!mention) return;
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

  const submit = () => {
    // Approval comment mode: Enter approves with the typed comment as the
    // durable reason (the protocol's `reason` field), never a plain message.
    if (approvalComment) {
      const comment = composer.value.trim();
      // An empty comment must not approve: the banner says "Enter approves
      // with it", and a bare Enter is exactly the accidental approval this
      // mode exists to avoid. Esc cancels; y approves without a comment.
      if (!comment) return;
      setApprovalComment(false);
      setComposer(EMPTY);
      void controller.approve(comment).catch(() => undefined);
      return;
    }
    let value = composer.value;
    if (palette.length > 0) {
      const chosen = palette[selected] ?? palette[0];
      if (chosen) value = chosen.name;
    }
    if (!value.trim()) return;
    history.add(value);
    onHistoryChange?.(history.all());
    setComposer(EMPTY);
    setPaletteDismissed(false);
    void controller.submit(value).catch(() => undefined);
  };

  const launchEditor = () => {
    const result = openExternalEditor(composer.value);
    if (result?.changed) setComposer({ value: result.text, cursor: result.text.length });
  };

  const toolCalls = controller.messages.filter((message) => message.tool);
  const pendingPreview = controller.currentSnapshot?.pending_approval?.preview ?? null;
  // The diff viewer's model is only built while it is open (an LCS diff per
  // edit tool is not free), and it is bounded in entries and lines. The
  // counts below are what the viewer is not showing.
  const diffEntrySet =
    overlay?.kind === "diff"
      ? collectDiffEntries(
          controller.messages,
          pendingPreview
            ? {
                title: `approval · ${controller.pendingApproval?.capabilityId ?? "preview"}`,
                preview: pendingPreview,
              }
            : null,
          { maxEntries: DIFF_MAX_ENTRIES, maxLines: DIFF_MAX_LINES },
        )
      : { entries: [], dropped: 0, tooLarge: 0 };
  const diffEntries = diffEntrySet.entries;

  useInput((keyInput, key) => {
    const selector = controller.pendingSelector;
    if (selector) {
      const visible = filterSelectorItems(selector.items, selectorQuery);
      const count = visible.length;
      if (key.escape) {
        controller.cancelSelector();
      } else if (key.return) {
        const pick = visible[Math.min(selectorIndex, Math.max(0, count - 1))];
        if (pick !== undefined) controller.chooseSelector(pick);
      } else if (key.upArrow) {
        setSelectorIndex((index) => (count === 0 ? 0 : (index - 1 + count) % count));
      } else if (key.downArrow) {
        setSelectorIndex((index) => (count === 0 ? 0 : (index + 1) % count));
      } else if (key.backspace || key.delete) {
        setSelectorQuery((query) => query.slice(0, -1));
      } else if (/^[1-9]$/.test(keyInput) && selectorQuery === "") {
        const pick = visible[Number(keyInput) - 1];
        if (pick !== undefined) controller.chooseSelector(pick);
      } else if (isPrintable(keyInput, key)) {
        setSelectorQuery((query) => query + keyInput);
      }
      return;
    }

    // Overlays are modal: while one is open it owns the keys (Esc closes),
    // so a stray y/n can never decide an approval behind the viewer.
    if (overlay) {
      if (key.escape) {
        setOverlay(null);
        return;
      }
      if (overlay.kind === "tools") {
        if (key.ctrl && keyInput === "o") {
          setOverlay(null);
          return;
        }
        if (key.upArrow || keyInput === "k") {
          setOverlay((current) =>
            current?.kind === "tools"
              ? { ...current, index: Math.max(0, current.index - 1) }
              : current,
          );
          return;
        }
        if (key.downArrow || keyInput === "j") {
          setOverlay((current) =>
            current?.kind === "tools"
              ? {
                  ...current,
                  index: Math.min(Math.max(0, toolCalls.length - 1), current.index + 1),
                }
              : current,
          );
          return;
        }
        return;
      }
      const entryIndex = Math.min(overlay.entry, Math.max(0, diffEntries.length - 1));
      const entry = diffEntries[entryIndex];
      const total = entry ? entry.lines.length : 0;
      const hunks = entry ? hunkStarts(entry.lines) : [];
      const page = Math.max(4, Math.min(20, (stdout?.rows ?? 24) - 8));
      const scrollTo = (offset: number): void =>
        setOverlay((current) =>
          current?.kind === "diff"
            ? { ...current, offset: Math.max(0, Math.min(Math.max(0, total - 1), offset)) }
            : current,
        );
      if (key.upArrow || keyInput === "k") {
        scrollTo(overlay.offset - 1);
        return;
      }
      if (key.downArrow || keyInput === "j") {
        scrollTo(overlay.offset + 1);
        return;
      }
      if (key.ctrl && keyInput === "d") {
        scrollTo(overlay.offset + page);
        return;
      }
      if (key.ctrl && keyInput === "u") {
        scrollTo(overlay.offset - page);
        return;
      }
      if (keyInput === "g") {
        scrollTo(0);
        return;
      }
      if (keyInput === "G") {
        scrollTo(total - page);
        return;
      }
      if (keyInput === "n") {
        const next = hunks.find((start) => start > overlay.offset);
        if (next !== undefined) scrollTo(next);
        return;
      }
      if (keyInput === "p") {
        const previous = [...hunks].reverse().find((start) => start < overlay.offset);
        if (previous !== undefined) scrollTo(previous);
        return;
      }
      if (keyInput === "]" || key.tab) {
        if (diffEntries.length > 0) {
          setOverlay({ kind: "diff", entry: (entryIndex + 1) % diffEntries.length, offset: 0 });
        }
        return;
      }
      if (keyInput === "[") {
        if (diffEntries.length > 0) {
          setOverlay({
            kind: "diff",
            entry: (entryIndex - 1 + diffEntries.length) % diffEntries.length,
            offset: 0,
          });
        }
        return;
      }
      return;
    }
    const restoreDraft = (): void => {
      setComposer({ value: searchDraft, cursor: searchDraft.length });
    };
    if (searchMode) {
      if (key.escape) {
        setSearchMode(false);
        restoreDraft();
      } else if (key.return) {
        const pick = searchMatches[selected] ?? searchMatches[0];
        if (pick !== undefined) setComposer({ value: pick, cursor: pick.length });
        else restoreDraft();
        setSearchMode(false);
      } else if (key.upArrow) {
        setSelected((current) => Math.max(0, current - 1));
      } else if (key.downArrow) {
        setSelected((current) => Math.max(0, Math.min(searchMatches.length - 1, current + 1)));
      } else if (key.backspace || key.delete) {
        setComposer((current) => backspace(current));
      } else if (isPrintable(keyInput, key)) {
        setComposer((current) => insertText(current, keyInput));
      }
      return;
    }

    // Vim keymap: normal mode owns navigation/edits; insert mode is the
    // standard composer and Esc returns to normal. Approvals keep priority:
    // y/n must work even in normal mode, and Esc during an active turn is
    // still a correction.
    if (
      controller.vimMode &&
      !searchMode &&
      palette.length === 0 &&
      controller.status !== "awaiting_approval"
    ) {
      if (key.escape && (controller.status === "streaming" || controller.status === "stalled")) {
        handleGlobalKey(controller, keyInput, key);
        return;
      }
      if (!vimInsert) {
        // A pending operator (d/c) consumes the next motion key.
        if (pendingOp) {
          const op = pendingOp;
          setPendingOp(null);
          const remove =
            keyInput === "d"
              ? deleteLine
              : keyInput === "w"
                ? deleteWordForward
                : keyInput === "$"
                  ? deleteToLineEnd
                  : null;
          if (remove) {
            setComposer((current) => remove(current));
            if (op === "c") setVimInsert(true);
          }
          return;
        }
        if (key.escape) return;
        if (keyInput === "d") {
          setPendingOp("d");
          return;
        }
        if (keyInput === "c") {
          setPendingOp("c");
          return;
        }
        if (keyInput === "i") {
          setVimInsert(true);
          return;
        }
        if (keyInput === "a") {
          setComposer((current) => move(current, "right"));
          setVimInsert(true);
          return;
        }
        if (keyInput === "A") {
          setComposer((current) => move(current, "end"));
          setVimInsert(true);
          return;
        }
        if (keyInput === "I") {
          setComposer((current) => move(current, "home"));
          setVimInsert(true);
          return;
        }
        if (keyInput === "h" || key.leftArrow) {
          setComposer((current) => move(current, "left"));
          return;
        }
        if (keyInput === "l" || key.rightArrow) {
          setComposer((current) => move(current, "right"));
          return;
        }
        if (keyInput === "j" || key.downArrow) {
          setComposer((current) => move(current, "down"));
          return;
        }
        if (keyInput === "k" || key.upArrow) {
          setComposer((current) => move(current, "up"));
          return;
        }
        if (keyInput === "0") {
          setComposer((current) => move(current, "home"));
          return;
        }
        if (keyInput === "w") {
          setComposer((current) => moveWord(current, "forward"));
          return;
        }
        if (keyInput === "b") {
          setComposer((current) => moveWord(current, "backward"));
          return;
        }
        if (keyInput === "e") {
          setComposer((current) => moveWord(current, "end"));
          return;
        }
        if (keyInput === "$") {
          setComposer((current) => move(current, "end"));
          return;
        }
        if (keyInput === "x") {
          setComposer((current) => deleteForward(current));
          return;
        }
        if (key.return) {
          submit();
          return;
        }
        return; // normal mode swallows other keys
      }
      if (key.escape) {
        setVimInsert(false);
        return;
      }
    }

    // Newline before Enter so the same physical key can never both split
    // and submit (Ctrl-J is the portable multi-line key; Aider-confirmed).
    if (keyInput === "\n" || (key.ctrl && keyInput === "j")) {
      setComposer((current) => insertNewline(current));
      return;
    }
    if (key.ctrl && keyInput === "r") {
      setSearchDraft(composer.value);
      setSearchMode(true);
      setComposer(EMPTY);
      return;
    }
    // Comment mode owns Esc (cancel) while it is on — the key never falls
    // through to the global handler (which would treat it as a correction).
    if (approvalComment && key.escape) {
      setApprovalComment(false);
      setComposer(EMPTY);
      return;
    }
    if (key.ctrl && keyInput === "o") {
      setOverlay((current) =>
        current?.kind === "tools"
          ? null
          : { kind: "tools", index: Math.max(0, toolCalls.length - 1) },
      );
      return;
    }
    if (key.ctrl && keyInput === "t") {
      setShowReasoning((visible) => !visible);
      return;
    }
    if (key.ctrl && keyInput === "g") {
      launchEditor();
      return;
    }
    if (key.ctrl && keyInput === "a") {
      // Codex-style: while an approval is pending Ctrl-A opens the full diff
      // view; otherwise it stays the readline line-start key.
      if (controller.status === "awaiting_approval" && !approvalComment) {
        setOverlay({ kind: "diff", entry: 0, offset: 0 });
        return;
      }
      setComposer((current) => move(current, "home"));
      return;
    }
    if (key.ctrl && keyInput === "e") {
      setComposer((current) => move(current, "end"));
      return;
    }
    // Readline-style history (also works where Up/Down are intercepted).
    if (key.ctrl && keyInput === "p") {
      setComposer((current) => {
        if (isMultiline(current)) return current;
        const value = history.prev(current.value);
        return { value, cursor: value.length };
      });
      return;
    }
    if (key.ctrl && keyInput === "n") {
      setComposer((current) => {
        if (isMultiline(current)) return current;
        const value = history.next();
        return { value, cursor: value.length };
      });
      return;
    }

    // Multi-character input is a paste (terminal keypresses are single
    // chars). Insert it verbatim, normalizing CR/CRLF to LF — otherwise a
    // pasted newline would be swallowed by the control-char filter.
    if (keyInput.length > 1 && !key.ctrl && !key.meta && !key.escape) {
      const pasted = keyInput
        .replace(/\r\n?/g, "\n")
        .replace(/[\u0000-\u0009\u000b-\u001f\u007f]/g, "");
      if (pasted) setComposer((current) => insertText(current, pasted));
      return;
    }

    if (palette.length > 0) {
      if (key.escape) {
        setPaletteDismissed(true);
        return;
      }
      if (key.upArrow) {
        setSelected((current) => (current - 1 + palette.length) % palette.length);
        return;
      }
      if (key.downArrow) {
        setSelected((current) => (current + 1) % palette.length);
        return;
      }
      if (key.tab) {
        const chosen = palette[selected] ?? palette[0];
        if (chosen) {
          const value = `${chosen.name} `;
          setComposer({ value, cursor: value.length });
        }
        return;
      }
      if (key.return) {
        submit();
        return;
      }
    }

    if (key.tab && mentionMatches.length > 0) {
      const pick = mentionMatches[0] as string;
      setComposer((current) => applyMention(current.value, current.cursor, pick));
      return;
    }

    if (key.leftArrow) {
      setComposer((current) => move(current, "left"));
      return;
    }
    if (key.rightArrow) {
      setComposer((current) => move(current, "right"));
      return;
    }
    if (key.home) {
      setComposer((current) => move(current, "home"));
      return;
    }
    if (key.end) {
      setComposer((current) => move(current, "end"));
      return;
    }
    if (key.upArrow) {
      setComposer((current) => {
        if (isMultiline(current)) return move(current, "up");
        const value = history.prev(current.value);
        return { value, cursor: value.length };
      });
      return;
    }
    if (key.downArrow) {
      setComposer((current) => {
        if (isMultiline(current)) return move(current, "down");
        const value = history.next();
        return { value, cursor: value.length };
      });
      return;
    }

    if (handleGlobalKey(controller, keyInput, key)) return;

    if (controller.status === "awaiting_approval" && !approvalComment) {
      // Approve/reject/comment consume the key: the character must not also
      // leak into the composer (it would be submitted on the next Enter).
      // While comment mode is ON this whole block is skipped, so a comment
      // containing "y"/"n"/"c" can never decide anything by itself.
      if (keyInput === "y") {
        void controller.approve().catch(() => undefined);
        return;
      }
      if (keyInput === "n") {
        void controller.reject().catch(() => undefined);
        return;
      }
      // [c] opens comment mode: Enter approves WITH the typed comment as the
      // durable reason, Esc cancels (never a silent always-allow).
      if (keyInput === "c") {
        setApprovalComment(true);
        setComposer(EMPTY);
        return;
      }
    }

    if (key.return) {
      submit();
      return;
    }
    if (key.backspace) {
      setComposer((current) => backspace(current));
      return;
    }
    if (key.delete) {
      setComposer((current) => deleteForward(current));
      return;
    }
    if (isPrintable(keyInput, key)) {
      setComposer((current) => insertText(current, keyInput));
    }
  });

  const theme = resolveTheme(controller.themeName);
  const snapshot = controller.currentSnapshot;
  const pending = snapshot?.pending_approval;
  const selectorVisible = controller.pendingSelector
    ? filterSelectorItems(controller.pendingSelector.items, selectorQuery)
    : [];
  const approvalDiff = pending?.preview ? previewToDiff(pending.preview) : null;
  const approvalLang =
    approvalDiff && approvalDiff[0]
      ? languageForPath(approvalDiff[0].text.replace(/^edit\s+/, "").trim())
      : undefined;
  const finalized = controller.messages.slice(0, controller.finalizedIndex);
  const active = controller.messages.slice(controller.finalizedIndex);
  const todoPanel = controller.todoPanel;

  // Tool viewer window (bounded rows around the selected call).
  const selectedToolIndex =
    overlay?.kind === "tools" ? Math.min(overlay.index, Math.max(0, toolCalls.length - 1)) : 0;
  const toolWindowStart = Math.max(
    0,
    Math.min(
      selectedToolIndex - Math.floor(TOOL_LIST_WINDOW / 2),
      Math.max(0, toolCalls.length - TOOL_LIST_WINDOW),
    ),
  );
  const toolWindow = toolCalls.slice(toolWindowStart, toolWindowStart + TOOL_LIST_WINDOW);
  const selectedTool = overlay?.kind === "tools" ? toolCalls[selectedToolIndex]?.tool : undefined;
  const selectedToolDiff = selectedTool ? editArgsToDiff(selectedTool.argsJson) : null;
  const selectedToolDiffTooLarge = selectedTool ? editDiffTooLarge(selectedTool.argsJson) : false;
  const selectedToolPath = selectedTool ? editPathFromArgs(selectedTool.argsJson) : null;
  const selectedToolLang = selectedToolPath ? languageForPath(selectedToolPath) : undefined;

  // Diff viewer window.
  const diffEntryIndex =
    overlay?.kind === "diff" ? Math.min(overlay.entry, Math.max(0, diffEntries.length - 1)) : 0;
  const diffEntry = diffEntries[diffEntryIndex];
  const diffOffset = overlay?.kind === "diff" ? overlay.offset : 0;
  const diffPage = Math.max(4, Math.min(20, (stdout?.rows ?? 24) - 8));
  const diffWindow = diffEntry ? diffEntry.lines.slice(diffOffset, diffOffset + diffPage) : [];
  const diffHunks = diffEntry ? hunkStarts(diffEntry.lines) : [];

  return (
    <Box flexDirection="column">
      <Static items={finalized}>
        {(message, index) => <MessageView key={index} message={message} finalized theme={theme} />}
      </Static>
      {active.map((message, index) => (
        <MessageView key={`active-${index}`} message={message} finalized={false} theme={theme} />
      ))}
      {todoPanel && (
        <Box flexDirection="column" borderStyle="round" borderColor={theme.accent}>
          {todoPanel.map((item) => (
            <Text key={item.id} dimColor={item.status === "done"}>
              {item.status === "done" ? "☑" : item.status === "in_progress" ? "◐" : "☐"} {item.content}
            </Text>
          ))}
        </Box>
      )}
      {overlay?.kind === "tools" && (
        <Box flexDirection="column" borderStyle="round" borderColor={theme.border}>
          <Text bold {...paint(theme.accent)}>
            tool calls {toolCalls.length} · selected {toolCalls.length === 0 ? 0 : selectedToolIndex + 1}
            {toolCalls.length > TOOL_LIST_WINDOW
              ? ` (showing ${toolWindowStart + 1}–${toolWindowStart + toolWindow.length})`
              : ""}
          </Text>
          {toolCalls.length === 0 && <Text dimColor>no tool calls yet</Text>}
          {toolWindow.map((message, index) => {
            const tool = message.tool as ToolCall;
            const absolute = toolWindowStart + index;
            const statusColor =
              tool.status === "pending"
                ? theme.toolPending
                : tool.status === "done"
                  ? theme.toolDone
                  : theme.toolFailed;
            const duration = tool.durationMs === undefined ? "" : ` · ${formatDuration(tool.durationMs)}`;
            return (
              <Text
                key={tool.actionId}
                {...paint(absolute === selectedToolIndex ? theme.paletteSelected : statusColor)}
              >
                {absolute === selectedToolIndex ? "› " : "  "}
                {TOOL_ICON[tool.status]} {tool.capabilityId}({tool.argsSummary}){duration}
              </Text>
            );
          })}
          {selectedTool && (
            <Box flexDirection="column" marginTop={1}>
              {formatToolDetail(selectedTool, { maxArgLines: TOOL_ARG_MAX_LINES }).map((line, index) => (
                <Text key={index} {...paint(theme.notice)}>
                  {line}
                </Text>
              ))}
              {selectedToolDiff?.slice(0, TOOL_DIFF_PREVIEW_LINES).map((line, index) => (
                <Text
                  key={`diff-${index}`}
                  wrap="wrap"
                  {...paint(
                    line.kind === "del"
                      ? theme.diffDel
                      : line.kind === "add"
                        ? theme.diffAdd
                        : theme.diffContext,
                  )}
                >
                  {line.kind === "del" ? "- " : line.kind === "add" ? "+ " : "  "}
                  {selectedToolLang && line.kind !== "context"
                    ? highlightCode(line.text, selectedToolLang)
                    : line.text}
                </Text>
              ))}
              {selectedToolDiffTooLarge ? (
                <Text dimColor>
                  (diff not rendered: this edit is too large to diff safely — the arguments above are
                  complete)
                </Text>
              ) : null}
              {selectedToolDiff && selectedToolDiff.length > TOOL_DIFF_PREVIEW_LINES ? (
                <Text dimColor>
                  … ({selectedToolDiff.length - TOOL_DIFF_PREVIEW_LINES} more diff lines; /diff opens the full
                  view)
                </Text>
              ) : null}
            </Box>
          )}
          <Text dimColor>↑↓ select · ctrl-o/esc close · /diff opens the full diff view</Text>
        </Box>
      )}
      {overlay?.kind === "diff" && (
        <Box flexDirection="column" borderStyle="round" borderColor={theme.border}>
          {diffEntry ? (
            <>
              <Text bold {...paint(theme.accent)} wrap="truncate-end">
                diff {diffEntryIndex + 1}/{diffEntries.length} · {diffEntry.title}
                {diffEntry.truncated ? " · truncated" : ""}
                {diffEntrySet.dropped > 0 ? ` · ${diffEntrySet.dropped} older diff(s) not shown` : ""}
                {diffEntrySet.tooLarge > 0 ? ` · ${diffEntrySet.tooLarge} too large to diff` : ""}
                {diffHunks.length > 0
                  ? ` · hunk ${Math.max(1, diffHunks.filter((start) => start <= diffOffset).length)}/${diffHunks.length}`
                  : ""}
              </Text>
              {diffWindow.map((line, index) => {
                const absolute = diffOffset + index;
                return (
                  <Text
                    key={absolute}
                    wrap="wrap"
                    {...paint(
                      line.kind === "del"
                        ? theme.diffDel
                        : line.kind === "add"
                          ? theme.diffAdd
                          : theme.diffContext,
                    )}
                  >
                    {line.kind === "del" ? "- " : line.kind === "add" ? "+ " : "  "}
                    {diffEntry.lang && line.kind !== "context"
                      ? highlightCode(line.text, diffEntry.lang)
                      : line.text}
                  </Text>
                );
              })}
              <Text dimColor>
                line {diffOffset + 1}–{Math.min(diffOffset + diffWindow.length, diffEntry.lines.length)}/
                {diffEntry.lines.length} · ↑↓ scroll · ctrl-d/u page · n/p hunk · [/] prev/next diff · esc
                close
              </Text>
            </>
          ) : (
            <Text dimColor>
              {diffEntrySet.tooLarge > 0
                ? `${diffEntrySet.tooLarge} edit diff(s) are too large to render — the tool viewer has the arguments (esc closes)`
                : diffEntrySet.dropped > 0
                  ? `${diffEntrySet.dropped} older diff(s) not shown (esc closes)`
                  : "no diffs yet — approval previews and edit tool calls appear here (esc closes)"}
            </Text>
          )}
        </Box>
      )}
      {controller.pendingSelector && (
        <Box flexDirection="column" borderStyle="round" borderColor={theme.accent}>
          <Text bold {...paint(theme.accent)}>
            {controller.pendingSelector.title}
          </Text>
          {selectorQuery ? <Text {...paint(theme.notice)}>filter: {selectorQuery}</Text> : null}
          {selectorVisible.map((item, index) => (
            <Text
              key={item}
              {...paint(index === selectorIndex ? theme.paletteSelected : theme.notice)}
            >
              {index === selectorIndex ? "› " : "  "}
              {index + 1}. {item}
            </Text>
          ))}
          {selectorVisible.length === 0 && <Text dimColor>(no match)</Text>}
          <Text dimColor>↑↓ move · type to filter · enter select · esc cancel</Text>
        </Box>
      )}
      {showReasoning && controller.reasoningText ? (
        <Text {...paint(theme.thinking)} wrap="wrap">
          🧠 {controller.reasoningText}
        </Text>
      ) : null}
      {!showReasoning && controller.reasoningText ? (
        <Text dimColor>
          🧠 thinking ({controller.reasoningText.length} chars) · ctrl-t to show
        </Text>
      ) : null}
      {controller.status === "streaming" && <Text dimColor>streaming…</Text>}
      {controller.status === "stalled" && (
        <Text {...paint(theme.toolPending)}>
          STALLED_PENDING_DURABLE_STATE — waiting for the durable record…
        </Text>
      )}
      {controller.status === "awaiting_approval" &&
        (pending ? (
          <Box
            flexDirection="column"
            borderStyle={layout.narrow ? "single" : "round"}
            borderColor={theme.approvalBorder}
          >
            <Text bold {...paint(theme.approvalTitle)}>
              🛡 human approval required — {pending.capability_id}
            </Text>
            {controller.pendingApproval?.riskTier !== undefined && (
              <Text {...paint(theme.notice)}>
                risk tier {controller.pendingApproval.riskTier}
                {controller.pendingApproval.nodeId
                  ? ` · node ${controller.pendingApproval.nodeId}`
                  : ""}
              </Text>
            )}
            {approvalDiff
              ? approvalDiff.map((line, index) => (
                  <Text
                    key={index}
                    wrap="wrap"
                    {...paint(
                      line.kind === "del"
                        ? theme.diffDel
                        : line.kind === "add"
                          ? theme.diffAdd
                          : theme.diffContext,
                    )}
                  >
                    {line.kind === "del" ? "- " : line.kind === "add" ? "+ " : "  "}
                    {approvalLang && line.kind !== "context"
                      ? highlightCode(line.text, approvalLang)
                      : line.text}
                  </Text>
                ))
              : pending.preview
                ? segmentPreview(pending.preview).map((segment, index) => {
                    const color =
                      segment.tone === "old"
                        ? theme.diffDel
                        : segment.tone === "new"
                          ? theme.diffAdd
                          : undefined;
                    return (
                      <Text key={index} wrap="wrap" {...paint(color)}>
                        {segment.text}
                      </Text>
                    );
                  })
                : null}
            <Text dimColor>
              digest {pending.action_digest.slice(0, 16)}… · this approval binds to that digest only
            </Text>
            <Text {...paint(theme.approvalTitle)}>
              [y] approve · [n] reject · [c] comment · ctrl-a full diff · esc is ignored here
            </Text>
          </Box>
        ) : (
          // Snapshot refresh is in flight after the durable pending event;
          // never flash an empty "unknown capability" card (iteration-18).
          <Text dimColor>approval pending — loading preview…</Text>
        ))}
      {controller.lastError && (
        <Text {...paint(theme.danger)}>error: {controller.lastError}</Text>
      )}
      {searchMode && (
        <Box flexDirection="column">
          <Text {...paint(theme.accent)}>reverse search (Ctrl-R): {input || "…"}</Text>
          {searchMatches.slice(0, 5).map((match, index) => (
            <Text
              key={`${match}-${index}`}
              {...paint(index === selected ? theme.paletteSelected : theme.notice)}
            >
              {index === selected ? "› " : "  "}
              {match}
            </Text>
          ))}
          {searchMatches.length === 0 && <Text dimColor>no matching history</Text>}
        </Box>
      )}
      {!searchMode && palette.length > 0 && (
        <Box flexDirection="column">
          {palette.map((command, index) => {
            const usage = `${command.name}${command.argsHint ? ` ${command.argsHint}` : ""}`;
            const suffix = layout.showDescriptions ? ` ${command.description}` : "";
            return (
              <Text
                key={command.name}
                {...paint(index === selected ? theme.paletteSelected : theme.notice)}
              >
                {index === selected ? "› " : "  "}
                {usage}
                {suffix}
              </Text>
            );
          })}
        </Box>
      )}
      {!searchMode && palette.length === 0 && mention && mentionMatches.length > 0 && (
        <Box flexDirection="column">
          <Text {...paint(theme.notice)}>file mention (Tab to insert):</Text>
          {mentionMatches.map((path, index) => (
            <Text key={path} {...paint(index === 0 ? theme.paletteSelected : theme.notice)}>
              {index === 0 ? "› " : "  "}
              {path}
            </Text>
          ))}
        </Box>
      )}
      {approvalComment && (
        <Text {...paint(theme.approvalTitle)}>
          approval comment — type it, then Enter approves with it (recorded in the durable approval) · Esc
          cancels
        </Text>
      )}
      {controller.goal && (
        <Text {...paint(theme.accent)} wrap="truncate-end">
          {`🎯 goal · ${controller.goal} · (/goal clear to unset)`}
        </Text>
      )}
      <Composer
        state={composer}
        placeholder={approvalComment ? COMMENT_PLACEHOLDER : PLACEHOLDER}
        theme={theme}
        modeLabel={controller.vimMode ? (vimInsert ? "[I]" : "[N]") : undefined}
      />
      <Text {...paint(theme.footer)} wrap="truncate-end">
        {`[${controller.mode}]`}
        {controller.queuedCount > 0 ? ` · ${controller.queuedCount} queued` : ""}
        {layout.footerFields && snapshot
          ? ` tokens ${controller.tokensTotal} · cost UNKNOWN · events ${snapshot.event_sequence}`
          : ""}
        {controller.lastStopReason && controller.lastStopReason !== "completed"
          ? ` · last turn: ${controller.lastStopReason}`
          : ""}
        {layout.showHints
          ? " · /help · ctrl-o tools · ctrl-a diff · ctrl-g editor · esc correct · ctrl-c exit"
          : " · /help"}
      </Text>
    </Box>
  );
}
