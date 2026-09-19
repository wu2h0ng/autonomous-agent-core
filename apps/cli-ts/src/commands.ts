/**
 * Slash-command registry — the single source of truth shared by the /help
 * transcript, the controller dispatch and the interactive palette.
 *
 * Shipping one registry (not a switch + a help array + a palette array)
 * prevents the three from drifting, which is the exact failure mode the
 * gap analysis flags across the three terminal paths.
 */

export interface CommandSpec {
  /** Canonical command token including the leading slash, e.g. "/status". */
  name: string;
  /** Argument hint shown in help/palette, e.g. "[MODE]" ("" when none). */
  argsHint: string;
  /** One-line description (also a filter fallback). */
  description: string;
}

export const COMMANDS: readonly CommandSpec[] = [
  { name: "/exit", argsHint: "", description: "quit (Esc during a turn issues a correction first; Ctrl-C exits)" },
  { name: "/status", argsHint: "", description: "session id, status, permission mode, event sequence" },
  { name: "/cost", argsHint: "", description: "exact token totals; cost is UNKNOWN (no pricing source)" },
  {
    name: "/metrics",
    argsHint: "[process|log]",
    description: "provider call counts, latency, tokens and failure categories (no prompt text)",
  },
  {
    name: "/provider",
    argsHint: "[set <base-url> <model> [endpoint-class]]",
    description: "show or configure the live provider (key read from AGENT_OS_PROVIDER_KEY; never stored)",
  },
  {
    name: "/mode",
    argsHint: "[MODE]",
    description: "show or set permission mode (ASK | ACCEPT_READ_ONLY | ACCEPT_IN_WORKSPACE)",
  },
  { name: "/resume", argsHint: "<session-id>|<n>", description: "attach to a session (id or recent-list index)" },
  {
    name: "/files",
    argsHint: "[PREFIX]",
    description: "workspace files (bounded read-only listing; optional path filter)",
  },
  { name: "/task", argsHint: "", description: "task overview: run status, receipts, outcome binding" },
  {
    name: "/goal",
    argsHint: "[<objective>|clear]",
    description: "set the persistent session objective included in every turn",
  },
  {
    name: "/theme",
    argsHint: "[name|next]",
    description: "show or switch the render theme",
  },
  {
    name: "/export",
    argsHint: "[path]",
    description: "write the transcript to a file (0600; may contain sensitive content)",
  },
  {
    name: "/keys",
    argsHint: "",
    description: "show the keymap",
  },
  {
    name: "/find",
    argsHint: "<query>",
    description: "search the in-session transcript (view only)",
  },
  {
    name: "/vim",
    argsHint: "",
    description: "toggle vim keymap (Esc normal; i/a insert; dd/dw/cw operators)",
  },
  {
    name: "/doctor",
    argsHint: "",
    description: "run a read-only self-check (descriptor/auth/protocol)",
  },
  {
    name: "/retry",
    argsHint: "",
    description: "re-submit the last message as a fresh turn",
  },
  {
    name: "/edit",
    argsHint: "",
    description: "load the last message into the composer for editing",
  },
  { name: "/clear", argsHint: "", description: "clear the LOCAL view (session context unchanged; Ctrl-L)" },
  {
    name: "/queue",
    argsHint: "[clear]",
    description: "list or clear messages queued while a turn is in flight",
  },
  { name: "/help", argsHint: "", description: "this list" },
] as const;

/**
 * Filter commands for the palette. A bare "" or "/" lists all; a query
 * containing whitespace is "command + args", not a palette query, so the
 * palette closes and Enter submits the raw line.
 */
export function filterCommands(query: string): CommandSpec[] {
  if (query.includes(" ")) return [];
  const needle = query.startsWith("/") ? query.slice(1) : query;
  if (!needle) return [...COMMANDS];
  const lower = needle.toLowerCase();
  const byName = COMMANDS.filter((command) => command.name.slice(1).startsWith(lower));
  if (byName.length > 0) return byName;
  return COMMANDS.filter((command) => command.description.toLowerCase().includes(lower));
}

/** Help transcript lines, derived from the registry (no drift). */
export function helpLines(): string[] {
  return COMMANDS.map((command) => {
    const usage = `${command.name}${command.argsHint ? ` ${command.argsHint}` : ""}`;
    return `${usage.padEnd(22)} ${command.description}`;
  });
}
