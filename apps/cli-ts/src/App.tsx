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
import { formatToolDetail } from "./controller.js";
import { filterCommands } from "./commands.js";
import type { CommandSpec } from "./commands.js";
import { backspace, deleteForward, insertNewline, insertText, isMultiline, move } from "./composer.js";
import type { ComposerState } from "./composer.js";
import { Composer } from "./ComposerView.js";
import { segmentPreview } from "./diff.js";
import { previewToDiff } from "./diffview.js";
import { openExternalEditor } from "./editor.js";
import { InputHistory } from "./history.js";
import { handleGlobalKey } from "./keys.js";
import { layoutFor } from "./layout.js";
import { renderMarkdown } from "./markdown.js";
import { activeMention, applyMention, filterMentions } from "./mentions.js";
import { resolveTheme } from "./theme.js";
import type { ThemeColors } from "./theme.js";

const EMPTY: ComposerState = { value: "", cursor: 0 };
const PLACEHOLDER = "Tell the agent what to do… (Ctrl-J newline · Ctrl-G editor)";

const TOOL_ICON: Record<ToolCall["status"], string> = {
  pending: "⏵",
  done: "✓",
  failed: "✗",
};

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
  if (message.tool) {
    const tool = message.tool;
    const color =
      tool.status === "pending"
        ? theme.toolPending
        : tool.status === "done"
          ? theme.toolDone
          : theme.toolFailed;
    return (
      <Text color={color}>
        {TOOL_ICON[tool.status]} {tool.capabilityId}({tool.argsSummary})
      </Text>
    );
  }
  const prefix = message.role === "user" ? "> " : message.role === "system" ? "⏵ " : "";
  const color =
    message.role === "user" ? theme.user : message.role === "system" ? theme.system : theme.assistant;
  const body =
    message.role === "assistant" && finalized ? renderMarkdown(message.content) : message.content;
  return (
    <Text wrap="wrap" color={color}>
      {prefix}
      {body}
      {message.interrupted ? " [interrupted]" : ""}
    </Text>
  );
}

export function App({ controller }: { controller: TuiController }) {
  const { exit } = useApp();
  const [, bump] = useReducer((tick: number) => tick + 1, 0);
  const [composer, setComposer] = useState<ComposerState>(EMPTY);
  const [paletteDismissed, setPaletteDismissed] = useState(false);
  const [selected, setSelected] = useState(0);
  const [showToolDetails, setShowToolDetails] = useState(false);
  const [searchMode, setSearchMode] = useState(false);
  const [searchDraft, setSearchDraft] = useState("");
  const [files, setFiles] = useState<string[]>([]);
  const history = useRef(new InputHistory()).current;
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
    let value = composer.value;
    if (palette.length > 0) {
      const chosen = palette[selected] ?? palette[0];
      if (chosen) value = chosen.name;
    }
    if (!value.trim()) return;
    history.add(value);
    setComposer(EMPTY);
    setPaletteDismissed(false);
    void controller.submit(value).catch(() => undefined);
  };

  const launchEditor = () => {
    const result = openExternalEditor(composer.value);
    if (result?.changed) setComposer({ value: result.text, cursor: result.text.length });
  };

  useInput((keyInput, key) => {
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
    if (key.ctrl && keyInput === "o") {
      setShowToolDetails((visible) => !visible);
      return;
    }
    if (key.ctrl && keyInput === "g") {
      launchEditor();
      return;
    }
    if (key.ctrl && keyInput === "a") {
      setComposer((current) => move(current, "home"));
      return;
    }
    if (key.ctrl && keyInput === "e") {
      setComposer((current) => move(current, "end"));
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

    if (controller.status === "awaiting_approval") {
      // Approve/reject consume the key: the character must not also leak
      // into the composer (it would be submitted on the next Enter).
      if (keyInput === "y") {
        void controller.approve().catch(() => undefined);
        return;
      }
      if (keyInput === "n") {
        void controller.reject().catch(() => undefined);
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
  const approvalDiff = pending?.preview ? previewToDiff(pending.preview) : null;
  const finalized = controller.messages.slice(0, controller.finalizedIndex);
  const active = controller.messages.slice(controller.finalizedIndex);
  const todoPanel = controller.todoPanel;
  const toolMessages = controller.messages.filter((message) => message.tool).slice(-5);

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
      {showToolDetails && toolMessages.length > 0 && (
        <Box flexDirection="column" borderStyle="round" borderColor={theme.border}>
          <Text bold color={theme.accent}>
            tool transcript (last {toolMessages.length})
          </Text>
          {toolMessages.map((message) => {
            const tool = message.tool as ToolCall;
            return (
              <Box key={tool.actionId} flexDirection="column" marginBottom={1}>
                <Text color={theme.accent}>
                  {TOOL_ICON[tool.status]} {tool.capabilityId} · {tool.argsSummary}
                </Text>
                {formatToolDetail(tool).map((line, index) => (
                  <Text key={index} color={theme.notice}>
                    {line}
                  </Text>
                ))}
              </Box>
            );
          })}
        </Box>
      )}
      {controller.status === "streaming" && <Text dimColor>streaming…</Text>}
      {controller.status === "stalled" && (
        <Text color={theme.toolPending}>STALLED_PENDING_DURABLE_STATE — waiting for the durable record…</Text>
      )}
      {controller.status === "awaiting_approval" &&
        (pending ? (
          <Box flexDirection="column" borderStyle={layout.narrow ? "single" : "round"} borderColor={theme.approvalBorder}>
            <Text bold color={theme.approvalTitle}>
              🛡 human approval required — {pending.capability_id}
            </Text>
            {approvalDiff
              ? approvalDiff.map((line, index) => (
                  <Text
                    key={index}
                    wrap="wrap"
                    color={
                      line.kind === "del"
                        ? theme.toolFailed
                        : line.kind === "add"
                          ? theme.toolDone
                          : theme.notice
                    }
                  >
                    {line.kind === "del" ? "- " : line.kind === "add" ? "+ " : "  "}
                    {line.text}
                  </Text>
                ))
              : pending.preview
                ? segmentPreview(pending.preview).map((segment, index) => {
                    const color =
                      segment.tone === "old"
                        ? theme.toolFailed
                        : segment.tone === "new"
                          ? theme.toolDone
                          : undefined;
                    return (
                      <Text key={index} wrap="wrap" {...(color ? { color } : {})}>
                        {segment.text}
                      </Text>
                    );
                  })
                : null}
            <Text dimColor>
              digest {pending.action_digest.slice(0, 16)}… · this approval binds to that digest only
            </Text>
            <Text color={theme.approvalTitle}>[y] approve · [n] reject · esc is ignored here</Text>
          </Box>
        ) : (
          // Snapshot refresh is in flight after the durable pending event;
          // never flash an empty "unknown capability" card (iteration-18).
          <Text dimColor>approval pending — loading preview…</Text>
        ))}
      {controller.lastError && <Text color={theme.danger}>error: {controller.lastError}</Text>}
      {searchMode && (
        <Box flexDirection="column">
          <Text color={theme.accent}>reverse search (Ctrl-R): {input || "…"}</Text>
          {searchMatches.slice(0, 5).map((match, index) => (
            <Text key={`${match}-${index}`} color={index === selected ? theme.paletteSelected : theme.notice}>
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
              <Text key={command.name} color={index === selected ? theme.paletteSelected : theme.notice}>
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
          <Text color={theme.notice}>file mention (Tab to insert):</Text>
          {mentionMatches.map((path, index) => (
            <Text key={path} color={index === 0 ? theme.paletteSelected : theme.notice}>
              {index === 0 ? "› " : "  "}
              {path}
            </Text>
          ))}
        </Box>
      )}
      {controller.goal && (
        <Text color={theme.accent} wrap="truncate-end">
          {`🎯 goal · ${controller.goal} · (/goal clear to unset)`}
        </Text>
      )}
      <Composer state={composer} placeholder={PLACEHOLDER} theme={theme} />
      <Text color={theme.footer} wrap="truncate-end">
        {`[${controller.mode}]`}
        {layout.footerFields && snapshot
          ? ` tokens ${controller.tokensTotal} · cost UNKNOWN · events ${snapshot.event_sequence}`
          : ""}
        {controller.lastStopReason && controller.lastStopReason !== "completed"
          ? ` · last turn: ${controller.lastStopReason}`
          : ""}
        {layout.showHints
          ? " · /help · ↑↓ history · ctrl-r search · ctrl-o tools · ctrl-g editor · esc correct · ctrl-c exit"
          : " · /help"}
      </Text>
    </Box>
  );
}
