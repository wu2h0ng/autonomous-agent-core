/** P1 full-screen view: renders TuiController state via @opentui/react. */
/** @jsxImportSource @opentui/react */
import { useEffect, useReducer, useState } from "react";
import { useKeyboard } from "@opentui/react";
import type { ChatMessage, TuiController } from "../controller.js";
import { handleGlobalKey } from "../keys.js";

export interface FullscreenAppProps {
  controller: TuiController;
  workspace: string;
  branch: string | null;
  version: string;
  model: string | null;
}

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

export function App({
  controller,
  workspace,
  branch,
  version,
  model,
}: FullscreenAppProps) {
  const [, bump] = useReducer((tick: number) => tick + 1, 0);
  const [input, setInput] = useState("");
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

  const snapshot = controller.currentSnapshot;
  const pending = snapshot?.pending_approval;
  const awaiting = controller.status === "awaiting_approval";

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
    if (name === "return") submit(input);
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

  return (
    <box style={{ flexDirection: "column", width: "100%", height: "100%" }}>
      <text>{`◆ noem v${version}   ${name}${branch ? ` · ${branch}` : ""} · ${controller.mode}`}</text>
      <scrollbox style={{ flexGrow: 1, border: true }} focused>
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
      <box border title="message" style={{ height: 3, paddingLeft: 1 }}>
        <input
          placeholder="Tell Noem what to do… (Enter to send)"
          focused={!awaiting}
          value={input}
          onInput={setInput}
        />
      </box>
      <text>{`❯ ${controller.mode}${model ? ` · ${model}` : ""}${
        snapshot
          ? ` · ${controller.tokensTotal} tok · cost UNKNOWN · ev ${snapshot.event_sequence}`
          : ""
      } · /help`}</text>
    </box>
  );
}
