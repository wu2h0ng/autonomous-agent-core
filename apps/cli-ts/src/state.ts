/**
 * Local CLI state persistence — input history, theme and `/goal` across
 * restarts (mainstream: persisted history/config). Strictly non-sensitive:
 * only these three fields are stored, never prompts' secrets or credentials.
 * Every failure is non-fatal (missing/corrupt file -> defaults; write
 * failure -> false) so a bad state file can never block the TUI.
 */
import { chmodSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export interface CliState {
  history: string[];
  theme: string;
  goal: string | null;
  vim: boolean;
}

export const DEFAULT_STATE: CliState = { history: [], theme: "default", goal: null, vim: false };

const MAX_HISTORY = 200;

export function stateFilePath(env: NodeJS.ProcessEnv = process.env): string {
  if (env.AGENT_OS_CLI_STATE) return env.AGENT_OS_CLI_STATE;
  return join(env.HOME ?? homedir(), ".agent-os", "cli-ts-state.json");
}

export function loadState(path: string): CliState {
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8")) as Partial<CliState>;
    return {
      history: Array.isArray(parsed.history)
        ? parsed.history.filter((entry): entry is string => typeof entry === "string").slice(-MAX_HISTORY)
        : [],
      theme: typeof parsed.theme === "string" && parsed.theme ? parsed.theme : DEFAULT_STATE.theme,
      goal: typeof parsed.goal === "string" && parsed.goal ? parsed.goal : null,
      vim: typeof parsed.vim === "boolean" ? parsed.vim : false,
    };
  } catch {
    return { ...DEFAULT_STATE };
  }
}

export function saveState(path: string, state: CliState): boolean {
  try {
    mkdirSync(dirname(path), { recursive: true });
    const payload: CliState = {
      history: state.history.slice(-MAX_HISTORY),
      theme: state.theme,
      goal: state.goal,
      vim: state.vim,
    };
    writeFileSync(path, JSON.stringify(payload), { encoding: "utf8", mode: 0o600 });
    chmodSync(path, 0o600); // tighten pre-existing files too
    return true;
  } catch {
    return false;
  }
}
