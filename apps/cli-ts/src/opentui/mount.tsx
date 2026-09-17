/** @jsxImportSource @opentui/react */
/**
 * Mount the full-screen view. Split out of `main.tsx` so the real CLI entry can
 * lazily import it: only the interactive TUI needs `@opentui/core`, so the
 * view-agnostic paths (`--version`, `--help`, `doctor`, `daemon`, `provider`,
 * `session`, headless `-p`) keep working on a runtime without native FFI.
 */
import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";
import type { SurfaceClient } from "../client.js";
import type { TuiController } from "../controller.js";
import { agentVersion } from "../version.js";
import { parseViewFlags } from "./panels.js";
import { App } from "./app.js";

export interface MountFullscreenOptions {
  controller: TuiController;
  client: SurfaceClient;
  workspace: string;
  branch: string | null;
  provider: string | null;
  model: string | null;
  /**
   * Persisted input history and its write-back (Ink parity: Ctrl-R / ↑ must
   * survive a restart). Explicitly `| undefined` because the props are passed
   * straight through under `exactOptionalPropertyTypes`.
   */
  initialHistory?: readonly string[] | undefined;
  onHistoryChange?: ((entries: string[]) => void) | undefined;
  /** Raw argv, used for the view flags (`--no-animation`, `--no-panels`, …). */
  args?: readonly string[];
}

/** Resolves once the view is mounted; the process then lives on the renderer. */
export async function mountFullscreen(options: MountFullscreenOptions): Promise<void> {
  const flags = parseViewFlags([...(options.args ?? [])]);
  const renderer = await createCliRenderer(
    flags.noAnimation ? { useThread: false, targetFps: 1, maxFps: 1 } : {},
  );
  createRoot(renderer).render(
    <App
      controller={options.controller}
      workspace={options.workspace}
      branch={options.branch}
      version={agentVersion()}
      provider={options.provider}
      model={options.model}
      client={options.client}
      initialHistory={options.initialHistory}
      onHistoryChange={options.onHistoryChange}
      withPanels={flags.withPanels}
      withAgents={flags.withAgents}
    />,
  );
}
