#!/usr/bin/env node
/** agent-os-ts entry: Ink TUI over the local runtime daemon, or headless
 * one-shot with -p/--print (frozen exit codes in headless.ts). */
import React from "react";
import { render } from "ink";
import { SurfaceClient } from "./client.js";
import { loadRuntimeDescriptor } from "./descriptor.js";
import { TuiController } from "./controller.js";
import { runHeadless, type HeadlessOutputFormat } from "./headless.js";
import { renderDoctorText, runDoctor } from "./doctor.js";
import { loadState, saveState, stateFilePath } from "./state.js";
import { App } from "./App.js";

// Writing to a closed pipe (e.g. `agent-os-ts -p ... | head -3`) raises
// EPIPE; mainstream CLI behavior is a quiet exit, not an unhandled throw.
for (const stream of [process.stdout, process.stderr]) {
  stream.on("error", (error: NodeJS.ErrnoException) => {
    if (error.code === "EPIPE") process.exit(0);
    throw error;
  });
}

function flagValue(args: string[], ...names: string[]): string | undefined {
  for (const name of names) {
    const index = args.indexOf(name);
    if (index >= 0) return args[index + 1];
  }
  return undefined;
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const descriptorPath = flagValue(args, "--descriptor");
  const resumeSessionId = flagValue(args, "--resume");
  const printPrompt = flagValue(args, "-p", "--print");
  const outputFormat = flagValue(args, "--output-format") as HeadlessOutputFormat | undefined;

  if (args[0] === "doctor") {
    const report = await runDoctor(descriptorPath);
    process.stdout.write(renderDoctorText(report));
    process.exitCode = report.ok ? 0 : 1;
    return;
  }

  if (args[0] === "provider") {
    const { runProviderCommand } = await import("./provider-command.js");
    process.exitCode = await runProviderCommand({
      descriptorPath,
      args: args.slice(1),
    });
    return;
  }

  const descriptor = await loadRuntimeDescriptor(descriptorPath);
  const client = new SurfaceClient(descriptor);

  if (printPrompt !== undefined) {
    if (outputFormat && outputFormat !== "text" && outputFormat !== "json" && outputFormat !== "stream-json") {
      console.error(`agent-os-ts: unknown --output-format ${outputFormat} (text | json | stream-json)`);
      process.exitCode = 1;
      return;
    }
    process.exitCode = await runHeadless(client, {
      prompt: printPrompt,
      sessionId: resumeSessionId,
      outputFormat,
    });
    return;
  }

  const statePath = stateFilePath();
  const state = loadState(statePath);
  const controller = new TuiController(client, {
    doctor: async () => renderDoctorText(await runDoctor(descriptorPath)),
  });
  controller.themeName = state.theme;
  controller.goal = state.goal;
  controller.vimMode = state.vim;
  if (resumeSessionId) {
    await controller.submit(`/resume ${resumeSessionId}`);
  }

  // Persist history/theme/goal locally (0600, debounced). Never secrets.
  let historyEntries: string[] = state.history;
  let saveTimer: ReturnType<typeof setTimeout> | null = null;
  const persist = (): void => {
    saveState(statePath, {
      history: historyEntries,
      theme: controller.themeName,
      goal: controller.goal,
      vim: controller.vimMode,
    });
  };
  const scheduleSave = (): void => {
    if (saveTimer) clearTimeout(saveTimer);
    const timer = setTimeout(persist, 500);
    saveTimer = timer;
    const maybe = timer as unknown as { unref?: () => void };
    if (typeof maybe.unref === "function") maybe.unref();
  };
  controller.subscribe(() => {
    // Flush immediately on close so a theme/goal change within the debounce
    // window is never lost; otherwise debounce.
    if (controller.status === "closed") persist();
    else scheduleSave();
  });
  process.on("exit", persist); // last-resort synchronous flush

  render(
    React.createElement(App, {
      controller,
      initialHistory: state.history,
      onHistoryChange: (entries: string[]) => {
        historyEntries = entries;
        scheduleSave();
      },
    }),
  );
}

main().catch((cause: unknown) => {
  console.error(`agent-os-ts: ${(cause as Error).message}`);
  process.exitCode = 1;
});
