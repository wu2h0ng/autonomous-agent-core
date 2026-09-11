/**
 * Ink view layer — renders TuiController state, forwards input.
 *
 * Wrap safety (M2 lesson): messages below `controller.finalizedIndex` render
 * through <Static> (appended to scrollback exactly once, never re-measured);
 * only the still-mutable tail renders in the dynamic area. Finalized
 * assistant messages render as markdown; the in-flight one renders raw.
 */
import React, { useEffect, useReducer, useState } from "react";
import { Box, Static, Text, useApp, useInput } from "ink";
import TextInput from "ink-text-input";
import type { ChatMessage, TuiController } from "./controller.js";
import { segmentPreview } from "./diff.js";
import { handleGlobalKey } from "./keys.js";
import { renderMarkdown } from "./markdown.js";

function MessageView({ message, finalized }: { message: ChatMessage; finalized: boolean }) {
  if (message.tool) {
    const tool = message.tool;
    const icon = tool.status === "pending" ? "⏵" : tool.status === "done" ? "✓" : "✗";
    const color = tool.status === "pending" ? "yellow" : tool.status === "done" ? "green" : "red";
    return (
      <Text color={color}>
        {icon} {tool.capabilityId}({tool.argsSummary})
      </Text>
    );
  }
  const prefix = message.role === "user" ? "> " : message.role === "system" ? "⏵ " : "";
  const color = message.role === "user" ? "cyan" : message.role === "system" ? "yellow" : "white";
  const body =
    message.role === "assistant" && finalized ? renderMarkdown(message.content) : message.content;
  return (
    <Text color={color} wrap="wrap">
      {prefix}
      {body}
      {message.interrupted ? " [interrupted]" : ""}
    </Text>
  );
}

export function App({ controller }: { controller: TuiController }) {
  const { exit } = useApp();
  const [, bump] = useReducer((tick: number) => tick + 1, 0);
  const [input, setInput] = useState("");

  useEffect(() => controller.subscribe(bump), [controller]);

  useEffect(() => {
    if (controller.status === "closed") exit();
  }, [controller.status, exit]);

  useEffect(() => {
    const timer = setInterval(() => controller.tick(), 500);
    return () => clearInterval(timer);
  }, [controller]);

  useInput((keyInput, key) => {
    if (handleGlobalKey(controller, keyInput, key)) return;
    if (controller.status === "awaiting_approval") {
      if (keyInput === "y") void controller.approve().catch(() => undefined);
      if (keyInput === "n") void controller.reject().catch(() => undefined);
    }
  });

  const snapshot = controller.currentSnapshot;
  const pending = snapshot?.pending_approval;
  const finalized = controller.messages.slice(0, controller.finalizedIndex);
  const active = controller.messages.slice(controller.finalizedIndex);
  const todoPanel = controller.todoPanel;

  return (
    <Box flexDirection="column">
      <Static items={finalized}>
        {(message, index) => <MessageView key={index} message={message} finalized />}
      </Static>
      {active.map((message, index) => (
        <MessageView key={`active-${index}`} message={message} finalized={false} />
      ))}
      {todoPanel && (
        <Box flexDirection="column" borderStyle="round" borderColor="cyan">
          {todoPanel.map((item) => (
            <Text key={item.id} dimColor={item.status === "done"}>
              {item.status === "done" ? "☑" : item.status === "in_progress" ? "◐" : "☐"} {item.content}
            </Text>
          ))}
        </Box>
      )}
      {controller.status === "streaming" && <Text dimColor>streaming…</Text>}
      {controller.status === "stalled" && (
        <Text color="yellow">STALLED_PENDING_DURABLE_STATE — waiting for the durable record…</Text>
      )}
      {controller.status === "awaiting_approval" && (
        <Box flexDirection="column" borderStyle="round" borderColor="yellow">
          <Text bold>approval required — {pending?.capability_id ?? "unknown capability"}</Text>
          {pending?.preview
            ? segmentPreview(pending.preview).map((segment, index) => (
                <Text
                  key={index}
                  wrap="wrap"
                  color={segment.tone === "old" ? "red" : segment.tone === "new" ? "green" : undefined}
                >
                  {segment.text}
                </Text>
              ))
            : null}
          <Text dimColor>
            digest {pending?.action_digest.slice(0, 16) ?? ""}… [y] approve [n] reject
          </Text>
        </Box>
      )}
      {controller.lastError && <Text color="red">error: {controller.lastError}</Text>}
      <Box>
        <Text color="green">{controller.status === "idle" ? "> " : "… "}</Text>
        <TextInput
          value={input}
          onChange={setInput}
          onSubmit={(value) => {
            setInput("");
            void controller.submit(value).catch(() => undefined);
          }}
        />
      </Box>
      <Text dimColor>
        {snapshot
          ? `mode ${controller.mode} · tokens ${controller.tokensTotal} · cost UNKNOWN · events ${snapshot.event_sequence}`
          : "no session"}
        {controller.lastStopReason && controller.lastStopReason !== "completed"
          ? ` · last turn: ${controller.lastStopReason}`
          : ""}
        {" · /help · esc/ctrl-c correct · ctrl-l clear"}
      </Text>
    </Box>
  );
}
