/** P1 full-screen entry (Bun): SurfaceClient + TuiController + @opentui view. */
/** @jsxImportSource @opentui/react */
import { execFileSync } from "node:child_process";
import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";
import { SurfaceClient } from "../client.js";
import { TuiController } from "../controller.js";
import { defaultDaemonPaths, ensureDaemon } from "../daemon.js";
import { agentVersion } from "../version.js";
import { App } from "./app.js";

function flag(args: string[], ...names: string[]): string | undefined {
  for (const name of names) {
    const index = args.indexOf(name);
    if (index >= 0) return args[index + 1];
  }
  return undefined;
}

function gitBranch(workspace: string): string | null {
  try {
    const out = execFileSync(
      "git",
      ["-C", workspace, "rev-parse", "--abbrev-ref", "HEAD"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
    );
    const branch = out.trim();
    return branch && branch !== "HEAD" ? branch : null;
  } catch {
    return null;
  }
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
let model: string | null = null;
try {
  const status = await client.providerStatus();
  model = status.model_id ?? null;
} catch {
  // status bar falls back
}

const workspace = process.cwd();
const controller = new TuiController(client, {});
const renderer = await createCliRenderer();
createRoot(renderer).render(
  <App
    controller={controller}
    workspace={workspace}
    branch={gitBranch(workspace)}
    version={agentVersion()}
    model={model}
  />,
);
