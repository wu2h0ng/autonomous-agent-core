/** @jsxImportSource @opentui/react */
/**
 * Dev/spike entry for the full-screen view (`bun run src/opentui/main.tsx`).
 *
 * This is the entry every pty check drives, so it stays behaviourally identical
 * to before; the real CLI goes through `src/cli.tsx`, which lazily imports
 * `mount.js` instead. Keep the two in sync when the view's props change —
 * including the persisted history (the checks keep the run hermetic with
 * AGENT_OS_CLI_STATE, so this never touches the developer's real state file).
 */
import { SurfaceClient } from "../client.js";
import { TuiController } from "../controller.js";
import { defaultDaemonPaths, ensureDaemon } from "../daemon.js";
import { gitBranch } from "../git.js";
import { loadState, saveState, stateFilePath } from "../state.js";
import { mountFullscreen } from "./mount.js";

function flag(args: string[], ...names: string[]): string | undefined {
  for (const name of names) {
    const index = args.indexOf(name);
    if (index >= 0) return args[index + 1];
  }
  return undefined;
}

const args = process.argv.slice(2);
const paths = defaultDaemonPaths();
const { descriptor } = await ensureDaemon({
  descriptorPath: flag(args, "--descriptor") ?? paths.descriptorPath,
  workspace: paths.workspace,
  database: paths.database,
  autoStart: !args.includes("--no-daemon"),
});
const client = new SurfaceClient(descriptor);
let provider: string | null = null;
let model: string | null = null;
try {
  const status = await client.providerStatus();
  provider = status.provider_id ?? null;
  model = status.model_id ?? null;
} catch {
  // status bar falls back
}

const workspace = process.cwd();
const statePath = stateFilePath();
const state = loadState(statePath);
await mountFullscreen({
  controller: new TuiController(client, {}),
  client,
  workspace,
  branch: gitBranch(workspace),
  provider,
  model,
  initialHistory: state.history,
  onHistoryChange: (entries: string[]) => {
    saveState(statePath, { ...state, history: entries });
  },
  args,
});
