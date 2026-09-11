/**
 * Ink view layer — renders TuiController state, forwards input. All logic
 * lives in controller.ts (Ink-free, unit-tested); this file only renders.
 */
import React, { useEffect, useReducer, useState } from "react";
import { Box, Text, useApp, useInput } from "ink";
import TextInput from "ink-text-input";
import type { TuiController } from "./controller.js";

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
    if (key.ctrl && keyInput === "c") {
      void controller.interrupt();
      return;
    }
    if (controller.status === "awaiting_approval") {
      if (keyInput === "y") void controller.approve().catch(() => undefined);
      if (keyInput === "n") void controller.reject().catch(() => undefined);
    }
  });

  const snapshot = controller.currentSnapshot;
  const pending = snapshot?.pending_approval;

  return (
    <Box flexDirection="column">
      {controller.messages.map((message, index) => (
        <Text
          key={index}
          color={message.role === "user" ? "cyan" : message.role === "system" ? "yellow" : "white"}
          wrap="wrap"
        >
          {message.role === "user" ? "> " : message.role === "system" ? "⏵ " : ""}
          {message.content}
          {message.interrupted ? " [interrupted]" : ""}
        </Text>
      ))}
      {controller.status === "streaming" && <Text dimColor>streaming…</Text>}
      {controller.status === "stalled" && (
        <Text color="yellow">STALLED_PENDING_DURABLE_STATE — waiting for the durable record…</Text>
      )}
      {controller.status === "awaiting_approval" && (
        <Box flexDirection="column" borderStyle="round" borderColor="yellow">
          <Text bold>approval required — {pending?.capability_id ?? "unknown capability"}</Text>
          {pending?.preview ? <Text wrap="wrap">{pending.preview}</Text> : null}
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
        {" · /help · ctrl-c correct/exit"}
      </Text>
    </Box>
  );
}
