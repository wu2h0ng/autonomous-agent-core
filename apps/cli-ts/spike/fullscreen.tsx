/** P0 spike: full-screen layout via @opentui/react (Bun runtime). */
/** @jsxImportSource @opentui/react */
import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";

function App() {
  return (
    <box style={{ flexDirection: "column", width: "100%", height: "100%" }}>
      <box
        border
        title=" NOEM "
        style={{ flexGrow: 1, padding: 1, flexDirection: "column" }}
      >
        <text>NOEM · governed terminal agent</text>
        <text> </text>
        <text>workspace  os-sandbox</text>
        <text>path       ~/Documents/…/.worktrees/os-sandbox</text>
        <text>provider   openai-compatible · deepseek-chat</text>
        <text>version    0.1.0</text>
        <text> </text>
        <text>Quick start</text>
        <text>· Describe a task and press Enter (shift+tab switches mode)</text>
      </box>
      <box border title=" message " style={{ height: 3, paddingLeft: 1 }}>
        <text>› Tell the agent what to do…</text>
      </box>
      <text>❯ ASK · deepseek-chat · /help</text>
    </box>
  );
}

const renderer = await createCliRenderer();
createRoot(renderer).render(<App />);
setTimeout(() => process.exit(0), 3000);
