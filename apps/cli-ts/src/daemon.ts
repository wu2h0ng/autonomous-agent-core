/**
 * Daemon lifecycle for the terminal client.
 *
 * Mainstream agent CLIs are self-contained: the user types the product name and
 * the agent starts whatever sidecar it needs. Agent OS is a client to a Python
 * governance daemon, so the client resolves the daemon on demand — attaching to
 * a healthy one, or starting one in the background (inheriting the caller's
 * environment so a provider key exported in the shell flows through) — so that
 * `agentos` alone works. Launcher resolution (`resolveDaemonLaunch`) prefers the
 * checkout the caller stands in over any separately installed runtime, so a
 * source checkout never silently talks to a different build or database — but a
 * directory that only LOOKS like our checkout (a `pyproject.toml` naming
 * `agent-os-runtime` next to a broken `uv.lock`) must not shadow a runtime that
 * works: when a launcher is gone before any daemon became ready, the next
 * candidate is tried and the fallback is reported instead of waiting out the
 * whole deadline. Launcher stderr is captured (bounded, secret-redacted), so the
 * real cause survives the `stdio: "ignore"` that used to swallow it.
 */
import {
  execFileSync,
  spawn as nodeSpawn,
  type ChildProcess,
} from "node:child_process";
import {
  closeSync,
  existsSync,
  lstatSync,
  mkdtempSync,
  openSync,
  readFileSync,
  readlinkSync,
  readSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { rm } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import {
  DEFAULT_RUNTIME_DESCRIPTOR,
  SurfaceProtocolSkewError,
  loadRuntimeDescriptor,
  type RuntimeDescriptor,
} from "./descriptor.js";

export interface DaemonPaths {
  descriptorPath: string;
  workspace: string;
  database: string;
}

export interface DaemonDeps {
  spawn: (command: string, args: string[], options: Record<string, unknown>) => ChildProcess;
  fetch: typeof fetch;
  sleep: (ms: number) => Promise<void>;
  now: () => number;
  /**
   * Ordered launch candidates: the first is preferred, the rest are the
   * fallbacks tried when a launcher dies before a daemon is ready. Injecting a
   * single plan (the common test case) pins the chain to that one launcher;
   * `null`/`[]` means "no launcher at all".
   */
  resolveLaunch: (
    env: NodeJS.ProcessEnv,
  ) => DaemonLaunchPlan | DaemonLaunchPlan[] | null;
  matchProcess: (pid: number, descriptorPath: string) => boolean;
  /**
   * Reports a fallback to the user. Stderr, never stdout: a headless
   * `--output-format json` turn must keep printing exactly one result object.
   */
  warn: (message: string) => void;
}

/** Where a resolved launcher came from; `doctor` reports it to the user. */
export type DaemonLaunchSource =
  | "override"
  | "checkout"
  | "path"
  | "uv";

export interface DaemonLaunchPlan {
  command: string[];
  source: DaemonLaunchSource;
  /**
   * Checkout the command must run in (only for `source: "checkout"`), else null.
   * Distinct from `--workspace`: `uv run` resolves the checkout's workspace
   * packages from this directory, while `--workspace` stays the user's own.
   */
  checkoutRoot: string | null;
}

export interface DaemonResolveDeps {
  hasOnPath: (name: string) => boolean;
  /** Nearest enclosing agent-os checkout of a directory, or null. */
  findCheckout: (startDir: string) => string | null;
  /** Directory the checkout search starts from. */
  cwd: () => string;
}

export function defaultDaemonPaths(workspace: string = process.cwd()): DaemonPaths {
  const home = homedir();
  return {
    descriptorPath:
      process.env.AGENT_OS_RUNTIME_DESCRIPTOR || DEFAULT_RUNTIME_DESCRIPTOR,
    workspace,
    database:
      process.env.AGENT_OS_RUNTIME_DATABASE ||
      join(home, ".agent-os", "agent-os.sqlite3"),
  };
}

const RUNTIME_SCRIPT = "agent-os-runtime";

/** Steady-state readiness poll interval (the long-standing cadence). */
const READY_POLL_MS = 300;
/** Fast interval for the first moments of a cold start. */
const READY_POLL_FAST_MS = 50;
/** How long the fast interval is used before backing off. */
const READY_POLL_FAST_WINDOW_MS = 2000;
/**
 * Grace served to a launcher that exited: a double-forking launcher could still
 * hand a daemon off, so the candidate is not called failed the instant the
 * process is gone (measured: a broken `uv.lock` makes `uv run` exit 2 in 16ms,
 * while the daemon it would have started answers in ~400ms).
 */
const EXIT_SETTLE_MS = 500;
/** Tail kept of a failed launcher's stderr: bounded lines, bounded bytes. */
const STDERR_TAIL_LINES = 12;
const STDERR_TAIL_MAX_BYTES = 8192;
/** Env variables whose values are masked out of captured launcher output. */
const SECRET_ENV_PATTERN = /(TOKEN|SECRET|PASSWORD|_KEY|APIKEY)$/i;
/** Mask written in place of a secret; never the secret itself. */
const REDACTED = "<redacted>";

/**
 * Operator-typed secrets (the P5 interactive `/provider` key) registered at
 * runtime. They are never written to state/history/transcript; this registry
 * exists only so that, if one ever surfaces in a captured launcher stderr, the
 * redactor masks it there too. Entries are kept in-memory for process lifetime.
 */
const runtimeSecrets: string[] = [];

/** Add an operator-typed secret to the redaction mask set (P5 security line). */
export function registerRuntimeSecret(secret: string): void {
  if (secret.length > 0 && !runtimeSecrets.includes(secret)) {
    runtimeSecrets.push(secret);
  }
}

/**
 * Every launcher to try, in order. The first element is the launcher the client
 * prefers (`resolveDaemonLaunch` returns exactly that, and `doctor` reports it);
 * the rest are fallbacks used only when an earlier candidate is gone before a
 * daemon became ready.
 *
 * Order, and why: an explicit `AGENT_OS_RUNTIME_CMD` beats everything and is the
 * ONLY candidate — the user named that command, so silently starting a different
 * runtime instead would betray the choice. Next the checkout the caller is
 * standing in, because a separate install of `agent-os-runtime` (e.g. the uv tool
 * install under `~/.local/share/uv/tools/`) is a *different build* that may serve
 * a different kernel against a different database — the client used to prefer it
 * whenever it was on PATH, even inside a source checkout. Then PATH, then a bare
 * `uv run`.
 */
export function resolveDaemonCandidates(
  env: NodeJS.ProcessEnv = process.env,
  deps: Partial<DaemonResolveDeps> = {},
): DaemonLaunchPlan[] {
  const hasOnPath = deps.hasOnPath ?? defaultHasOnPath;
  const findCheckout = deps.findCheckout ?? findCheckoutRoot;
  const cwd = deps.cwd ?? ((): string => process.cwd());
  const override = env.AGENT_OS_RUNTIME_CMD;
  if (override && override.trim()) {
    return [
      {
        command: override.trim().split(/\s+/),
        source: "override",
        checkoutRoot: null,
      },
    ];
  }
  const uvOnPath = hasOnPath("uv");
  const plans: DaemonLaunchPlan[] = [];
  // `uv run` only resolves the checkout's workspace packages when it runs *in*
  // that checkout, so the checkout is also the plan's spawn cwd.
  const checkout = findCheckout(cwd());
  if (checkout !== null && uvOnPath) {
    plans.push({
      command: ["uv", "run", RUNTIME_SCRIPT],
      source: "checkout",
      checkoutRoot: checkout,
    });
  }
  if (hasOnPath(RUNTIME_SCRIPT)) {
    plans.push({ command: [RUNTIME_SCRIPT], source: "path", checkoutRoot: null });
  }
  if (uvOnPath) {
    plans.push({
      command: ["uv", "run", RUNTIME_SCRIPT],
      source: "uv",
      checkoutRoot: null,
    });
  }
  return plans;
}

/** The preferred launcher (first candidate), or null when there is none. */
export function resolveDaemonLaunch(
  env: NodeJS.ProcessEnv = process.env,
  deps: Partial<DaemonResolveDeps> = {},
): DaemonLaunchPlan | null {
  return resolveDaemonCandidates(env, deps)[0] ?? null;
}

/** argv-only view of `resolveDaemonLaunch`, for callers that need just that. */
export function resolveDaemonCommand(
  env: NodeJS.ProcessEnv = process.env,
  deps: Partial<DaemonResolveDeps> = {},
): string[] | null {
  return resolveDaemonLaunch(env, deps)?.command ?? null;
}

function defaultHasOnPath(name: string): boolean {
  const path = process.env.PATH || "";
  for (const dir of path.split(":")) {
    if (dir && existsSync(join(dir, name))) return true;
  }
  return false;
}

export interface DanglingPathShim {
  /** The PATH entry that is a broken symlink, e.g. ~/.local/bin/agent-os-runtime. */
  shim: string;
  /** What the shim points at (best effort; null if unreadable). */
  target: string | null;
}

/**
 * Find a `name` on PATH that is a SYMLINK whose target does not resolve. This is
 * the failure mode of `uv tool install` writing shims into ~/.local/bin while
 * UV_TOOL_DIR (and, before 2026-09-19, UV_TOOL_BIN_DIR) pointed at a temp dir:
 * the shim survives the temp cleanup but points at a deleted path.
 *
 * `existsSync` (used by defaultHasOnPath) already follows the link and reports
 * false for a dangling shim, so the launcher chain skips it -- which is correct,
 * but then silently falls through to `uv run` outside a checkout and dies with a
 * confusing ENOENT. Returning the shim here lets us tell the operator the real
 * repair instead.
 */
export function detectDanglingPathShim(
  name: string,
  pathEnv: string | undefined = process.env.PATH,
): DanglingPathShim | null {
  for (const dir of (pathEnv ?? "").split(":")) {
    if (!dir) continue;
    const candidate = join(dir, name);
    let link: string;
    try {
      const stat = lstatSync(candidate);
      if (!stat.isSymbolicLink()) continue;
      link = readlinkSync(candidate);
    } catch {
      continue;
    }
    if (!existsSync(candidate)) {
      return { shim: candidate, target: link };
    }
  }
  return null;
}

/** Actionable repair text for a dangling shim, or null when there is none. */
export function danglingShimRepairHint(
  name: string = RUNTIME_SCRIPT,
  pathEnv: string | undefined = process.env.PATH,
): string | null {
  const broken = detectDanglingPathShim(name, pathEnv);
  if (broken === null) return null;
  return (
    `noem: the \`${name}\` shim on PATH (${broken.shim}) is a broken symlink ` +
    `-> ${broken.target ?? "(unreadable target)"}. This usually means a previous ` +
    "install pointed the shims at a temporary uv tools dir that was deleted. " +
    "Reinstall from this tree to repair it: `uv tool install . --force --reinstall`."
  );
}

/**
 * Nearest ancestor of `startDir` that is this repo's checkout: a `pyproject.toml`
 * declaring the `agent-os-runtime` console script, plus the workspace markers
 * (`packages/os_core` or `uv.lock`) that let `uv run` build the local packages
 * instead of falling back to an installed tool. Returns null outside a checkout.
 */
export function findCheckoutRoot(
  startDir: string,
  exists: (path: string) => boolean = existsSync,
  readFile: (path: string) => string | null = readFileOrNull,
): string | null {
  let dir = startDir;
  for (;;) {
    const manifest = readFile(join(dir, "pyproject.toml"));
    if (
      manifest !== null &&
      declaresConsoleScript(manifest, RUNTIME_SCRIPT) &&
      (exists(join(dir, "packages", "os_core")) || exists(join(dir, "uv.lock")))
    ) {
      return dir;
    }
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

function readFileOrNull(path: string): string | null {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

/** True when the TOML text assigns `name` inside a `[project.scripts]` table. */
function declaresConsoleScript(toml: string, name: string): boolean {
  let section = "";
  for (const rawLine of toml.split("\n")) {
    const line = rawLine.trim();
    if (line.startsWith("[")) {
      section = line.replace(/\s+/g, "");
      continue;
    }
    if (section !== "[project.scripts]") continue;
    if (line.split("=")[0]?.trim() === name) return true;
  }
  return false;
}

/**
 * The descriptor, or `null` when there is no daemon to attach to.
 *
 * A protocol skew is NOT "no daemon" and is rethrown: the descriptor was written
 * by another build that is probably still running, and its file is that daemon's
 * only handle. Treating the skew as absence is what made an older client delete a
 * live daemon's descriptor and then try to start a competing daemon over the same
 * database, reporting "daemon did not become ready in time" instead of naming the
 * version mismatch it actually hit.
 */
async function tryLoad(descriptorPath: string): Promise<RuntimeDescriptor | null> {
  try {
    return await loadRuntimeDescriptor(descriptorPath);
  } catch (error) {
    if (error instanceof SurfaceProtocolSkewError) throw error;
    return null;
  }
}

/** A daemon is healthy when its surface API answers an authenticated request. */
export async function daemonHealthy(
  descriptor: RuntimeDescriptor,
  fetchImpl: typeof fetch = fetch,
): Promise<boolean> {
  try {
    const response = await fetchImpl(
      `${descriptor.baseUrl}/v1/surface/sessions?limit=1`,
      { headers: { Authorization: `Bearer ${descriptor.bearer_token}` } },
    );
    return response.status === 200;
  } catch {
    return false;
  }
}

export interface EnsureDaemonOptions {
  descriptorPath: string;
  workspace: string;
  database: string;
  autoStart?: boolean;
  timeoutSeconds?: number;
}

/** How one launcher candidate ended, when it did not produce a daemon. */
interface AttemptNote {
  plan: DaemonLaunchPlan;
  kind: "spawn-error" | "exited" | "not-ready";
  /** What happened, without the stderr tail. */
  detail: string;
  /** Redacted tail of the launcher's stderr, or null when it wrote nothing. */
  stderrTail: string | null;
  /** Retained (redacted, bounded) capture on disk, or null when none was kept. */
  capturePath: string | null;
}

type LaunchOutcome = { descriptor: RuntimeDescriptor } | { note: AttemptNote };

const SOURCE_NOUN: Record<DaemonLaunchSource, string> = {
  override: "AGENT_OS_RUNTIME_CMD launcher",
  checkout: "checkout launcher",
  path: "PATH launcher",
  uv: "uv launcher",
};

function toCandidates(
  launch: DaemonLaunchPlan | DaemonLaunchPlan[] | null,
): DaemonLaunchPlan[] {
  if (launch === null) return [];
  return Array.isArray(launch) ? launch : [launch];
}

/** Where a candidate comes from, in the words the user sees. */
function originLabel(plan: DaemonLaunchPlan): string {
  switch (plan.source) {
    case "override":
      return "AGENT_OS_RUNTIME_CMD";
    case "checkout":
      return `checkout ${plan.checkoutRoot ?? "?"}`;
    case "path":
      return "PATH";
    default:
      return "uv run fallback";
  }
}

function planLabel(plan: DaemonLaunchPlan): string {
  return `"${plan.command.join(" ")}" (${originLabel(plan)})`;
}

/** One line naming a failed candidate, for warnings and the final error. */
function attemptSummary(note: AttemptNote): string {
  return `${SOURCE_NOUN[note.plan.source]} ${planLabel(note.plan)}: ${note.detail}`;
}

function formatSeconds(ms: number): string {
  return `${(Math.max(0, ms) / 1000).toFixed(2)}s`;
}

/**
 * Where a launcher's stderr is captured: next to the descriptor, one file per
 * source, so a fallback never overwrites the failed launcher's output. Created
 * 0600 for the same reason the descriptor is private.
 */
function captureFilePath(
  descriptorPath: string,
  source: DaemonLaunchSource,
): string {
  return join(dirname(descriptorPath), `daemon-launch-${source}.log`);
}

function tryOpenCapture(path: string): number | null {
  try {
    return openSync(path, "w", 0o600);
  } catch {
    return null;
  }
}

/**
 * Open a launcher's stderr sink, preferring the descriptor's directory (where a
 * user looks first) and falling back to a private temp directory: on a machine
 * that has never run the daemon that directory may not exist yet, and a missing
 * directory is not a reason to lose the only evidence of why a launch failed.
 */
function createCapture(preferredPath: string): { fd: number; path: string } | null {
  const direct = tryOpenCapture(preferredPath);
  if (direct !== null) return { fd: direct, path: preferredPath };
  try {
    const dir = mkdtempSync(join(tmpdir(), "agent-os-launch-"));
    const path = join(dir, "stderr.log");
    const fd = tryOpenCapture(path);
    return fd === null ? null : { fd, path };
  } catch {
    return null;
  }
}

async function discardCapture(path: string): Promise<void> {
  try {
    await rm(path, { force: true });
  } catch {
    // Diagnostics only; failing to remove it is not a reason to fail the start.
  }
}

/** Last bytes of a capture, or null when empty/unreadable; always bounded. */
function readTailBytes(path: string): string | null {
  try {
    const { size } = statSync(path);
    if (size === 0) return null;
    const length = Math.min(size, STDERR_TAIL_MAX_BYTES);
    const buffer = Buffer.alloc(length);
    const fd = openSync(path, "r");
    try {
      readSync(fd, buffer, 0, length, size - length);
    } finally {
      closeSync(fd);
    }
    return buffer.toString("utf8");
  } catch {
    return null;
  }
}

/**
 * Values that must never reach a log line we print or keep: the token the
 * descriptor currently carries (a launcher may echo its own configuration) plus
 * anything in the environment that is named like a credential.
 */
function secretsToMask(descriptorPath: string): string[] {
  const secrets: string[] = [];
  const raw = readFileOrNull(descriptorPath);
  if (raw !== null) {
    try {
      const token = (JSON.parse(raw) as { bearer_token?: unknown }).bearer_token;
      if (typeof token === "string" && token.length > 0) secrets.push(token);
    } catch {
      // An unreadable descriptor has no token to learn here.
    }
  }
  for (const [name, value] of Object.entries(process.env)) {
    if (typeof value === "string" && value.length >= 8 && SECRET_ENV_PATTERN.test(name)) {
      secrets.push(value);
    }
  }
  for (const secret of runtimeSecrets) {
    if (secret.length > 0) secrets.push(secret);
  }
  return secrets;
}

function redactSecrets(text: string, secrets: string[]): string {
  let out = text;
  for (const secret of secrets) {
    if (secret.length > 0) out = out.split(secret).join(REDACTED);
  }
  return out;
}

/** Last non-empty lines of captured output, each already bounded by the read. */
function tailLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trimEnd())
    .filter((line) => line.length > 0)
    .slice(-STDERR_TAIL_LINES);
}

/**
 * Read a failed launcher's capture back, mask secrets, and keep on disk exactly
 * what we are willing to show — so the retained file cannot hold what the
 * message hides. An empty capture is not kept at all.
 */
async function collectCapture(
  capturePath: string,
  descriptorPath: string,
): Promise<{ tail: string | null; capturePath: string | null }> {
  const raw = readTailBytes(capturePath);
  if (raw === null) {
    await discardCapture(capturePath);
    return { tail: null, capturePath: null };
  }
  const redacted = redactSecrets(raw, secretsToMask(descriptorPath));
  try {
    writeFileSync(capturePath, redacted, { mode: 0o600 });
  } catch {
    // The message is redacted either way; leave the file as it is.
  }
  const lines = tailLines(redacted);
  if (lines.length === 0) {
    await discardCapture(capturePath);
    return { tail: null, capturePath: null };
  }
  return { tail: lines.join("\n"), capturePath };
}

async function failedNote(
  plan: DaemonLaunchPlan,
  kind: AttemptNote["kind"],
  detail: string,
  capturePath: string,
  descriptorPath: string,
): Promise<AttemptNote> {
  const capture = await collectCapture(capturePath, descriptorPath);
  return {
    plan,
    kind,
    detail,
    stderrTail: capture.tail,
    capturePath: capture.capturePath,
  };
}

/**
 * Run one candidate and wait for its daemon. Returns the moment an
 * authenticated answer comes back; otherwise a note saying why not — a launcher
 * that is gone is never waited out to the deadline, because the thing that
 * proves it failed (its exit, its stderr) is already in hand.
 */
async function runLauncher(
  plan: DaemonLaunchPlan,
  options: EnsureDaemonOptions,
  resolved: DaemonDeps,
  deadline: number,
): Promise<LaunchOutcome> {
  const capture = createCapture(
    captureFilePath(options.descriptorPath, plan.source),
  );
  const fd = capture?.fd ?? null;
  const capturePath = capture?.path ?? captureFilePath(options.descriptorPath, plan.source);
  const exit: { at: number | null; how: string | null; spawnError: string | null } = {
    at: null,
    how: null,
    spawnError: null,
  };
  let child: ChildProcess;
  try {
    child = resolved.spawn(
      plan.command[0] as string,
      [
        ...plan.command.slice(1),
        "--workspace",
        options.workspace,
        "--database",
        options.database,
        "--descriptor",
        options.descriptorPath,
      ],
      {
        detached: true,
        // The launcher's stderr goes to a file the daemon can keep writing to
        // for its whole life: a pipe would break the moment this client exits,
        // and the old `stdio: "ignore"` threw away the one piece of evidence
        // that explains a failed launch.
        stdio: fd === null ? "ignore" : ["ignore", "ignore", fd],
        env: process.env,
        // Spawn cwd, NOT the workspace: `uv run` must stand in the checkout to
        // resolve that checkout's workspace packages. `--workspace` above stays
        // the user's own directory, which is a different thing.
        cwd: plan.checkoutRoot ?? options.workspace,
      },
    );
  } catch (cause) {
    if (fd !== null) closeSync(fd);
    return {
      note: await failedNote(
        plan,
        "spawn-error",
        (cause as Error).message,
        capturePath,
        options.descriptorPath,
      ),
    };
  }
  // The child holds its own copy of the capture file; ours would keep that file
  // alive after a successful launch and is not needed to read it back.
  if (fd !== null) closeSync(fd);
  child.once?.("exit", ((code: number | null, signal: NodeJS.Signals | null) => {
    if (exit.at !== null) return;
    exit.at = resolved.now();
    exit.how = code === null ? `killed by ${signal ?? "a signal"}` : `exited ${code}`;
  }) as (code?: unknown) => void);
  try {
    await new Promise<void>((resolve, reject) => {
      child.once?.("spawn", () => resolve());
      child.once?.("error", (error: Error) => {
        exit.spawnError = error.message;
        reject(error);
      });
    });
  } catch {
    return {
      note: await failedNote(
        plan,
        "spawn-error",
        exit.spawnError ?? "could not be started",
        capturePath,
        options.descriptorPath,
      ),
    };
  }
  // Poll quickly while a cold start is plausible: the daemon is ready in well
  // under a second here (measured ~400ms for both launchers), and a flat 300ms
  // sleep made the client hand back ~200ms *after* readiness (measured 610ms
  // total). Past the window it backs off to the old cadence, so a slow or
  // half-dead daemon is not hammered for the whole timeout.
  const attemptStart = resolved.now();
  const fastUntil = attemptStart + READY_POLL_FAST_WINDOW_MS;
  for (;;) {
    const now = resolved.now();
    if (now >= deadline) break;
    // A launcher that exited gets EXIT_SETTLE_MS of grace (a hand-off launcher
    // could still have a daemon coming up), then the candidate is called failed
    // and the next one gets the remaining time instead of waiting it all out.
    const limit =
      exit.at === null ? deadline : Math.min(deadline, exit.at + EXIT_SETTLE_MS);
    if (now >= limit) break;
    await resolved.sleep(now < fastUntil ? READY_POLL_FAST_MS : READY_POLL_MS);
    const descriptor = await tryLoad(options.descriptorPath);
    if (descriptor && (await daemonHealthy(descriptor, resolved.fetch))) {
      child.unref?.();
      await discardCapture(capturePath);
      return { descriptor };
    }
  }
  if (exit.at !== null) {
    return {
      note: await failedNote(
        plan,
        "exited",
        `${exit.how ?? "exited"} after ${formatSeconds(exit.at - attemptStart)}`,
        capturePath,
        options.descriptorPath,
      ),
    };
  }
  return {
    note: await failedNote(
      plan,
      "not-ready",
      `no daemon answered within ${formatSeconds(resolved.now() - attemptStart)}`,
      capturePath,
      options.descriptorPath,
    ),
  };
}

/**
 * The error a run of candidates ends with: the long-standing wording, plus what
 * each candidate actually did and the tail of what it said. Kept separate from
 * the warning so an all-candidates-failed run is still one throw.
 */
function launcherFailureMessage(notes: AttemptNote[]): string {
  if (notes.length > 0 && notes.every((note) => note.kind === "spawn-error")) {
    return (
      `failed to start daemon (${notes.map(attemptSummary).join("; ")}); set ` +
      "AGENT_OS_RUNTIME_CMD or start it manually"
    );
  }
  const lines = notes.map((note) => {
    const parts = [`  - ${attemptSummary(note)}`];
    if (note.stderrTail !== null) {
      parts.push(...note.stderrTail.split("\n").map((line) => `      ${line}`));
    }
    if (note.capturePath !== null) parts.push(`    full output: ${note.capturePath}`);
    return parts.join("\n");
  });
  return [
    "daemon did not become ready in time; verify the provider configuration " +
      "or start it manually with `agentos daemon start`",
    ...lines,
  ].join("\n");
}

/** Told to the user when a launcher was abandoned and another one took over. */
function fallbackWarning(notes: AttemptNote[], next: DaemonLaunchPlan): string {
  const kept = notes
    .map((note) => note.capturePath)
    .filter((path): path is string => path !== null);
  const output =
    kept.length > 0 ? `; launcher output kept at ${kept.join(", ")}` : "";
  return (
    `noem: ${notes.map(attemptSummary).join("; ")}${output}; falling back to ` +
    planLabel(next)
  );
}

/**
 * Attach to a healthy daemon, or start one in the background and wait until it
 * is ready. Throws when auto-start is disabled/unavailable or no launcher
 * produced a ready daemon.
 */
export async function ensureDaemon(
  options: EnsureDaemonOptions,
  deps?: Partial<DaemonDeps>,
): Promise<{ descriptor: RuntimeDescriptor; started: boolean }> {
  const resolved: DaemonDeps = {
    spawn: nodeSpawn as DaemonDeps["spawn"],
    fetch,
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now: Date.now,
    resolveLaunch: resolveDaemonCandidates,
    matchProcess: processMatchesDescriptor,
    warn: (message) => process.stderr.write(`${message}\n`),
    ...deps,
  };
  const existing = await tryLoad(options.descriptorPath);
  if (existing && (await daemonHealthy(existing, resolved.fetch))) {
    return { descriptor: existing, started: false };
  }
  if (options.autoStart === false) {
    throw new Error(
      `no running daemon at ${options.descriptorPath}; start one or enable auto-start`,
    );
  }
  const candidates = toCandidates(resolved.resolveLaunch(process.env));
  // If we are about to fall through to the bare `uv run` launcher with no
  // checkout and no working PATH shim, but there IS a dangling shim on PATH,
  // say so before the confusing ENOENT (bug 2026-09-19: a broken shim silently
  // fell through to `uv run` outside a project and died).
  const onlyUvFallback =
    candidates.length > 0 &&
    candidates.every((c) => c.source === "uv");
  if (onlyUvFallback) {
    const hint = danglingShimRepairHint();
    if (hint !== null) resolved.warn(hint);
  }
  if (candidates.length === 0) {
    throw new Error(
      "no daemon launcher found; install agent-os-runtime, run from the repo with uv, " +
        "or set AGENT_OS_RUNTIME_CMD",
    );
  }
  // Stop a still-alive stale daemon before respawning, but only when the pid
  // is verified to be this runtime (never blind-kill a recycled pid).
  if (
    existing &&
    resolved.matchProcess(existing.pid, options.descriptorPath)
  ) {
    killPid(existing.pid);
  }
  await rm(options.descriptorPath, { force: true });
  // One deadline for the whole chain: the fallback must not extend how long the
  // client waits, only how many launchers it tries inside that time.
  const deadline = resolved.now() + (options.timeoutSeconds ?? 20) * 1000;
  const notes: AttemptNote[] = [];
  for (const plan of candidates) {
    if (resolved.now() >= deadline) break;
    const outcome = await runLauncher(plan, options, resolved, deadline);
    if ("descriptor" in outcome) {
      if (notes.length > 0) resolved.warn(fallbackWarning(notes, plan));
      return { descriptor: outcome.descriptor, started: true };
    }
    notes.push(outcome.note);
  }
  throw new Error(launcherFailureMessage(notes));
}

/** True when the pid runs this runtime with our registry descriptor argument. */
function processMatchesDescriptor(pid: number, descriptorPath: string): boolean {
  try {
    const out = execFileSync("ps", ["-p", String(pid), "-o", "command="], {
      encoding: "utf8",
    });
    return out.includes(descriptorPath);
  } catch {
    return false;
  }
}

function killPid(pid: number): void {
  try {
    process.kill(pid, "SIGTERM");
  } catch {
    // already gone
  }
}

/** Stop the daemon referenced by a descriptor and remove the descriptor. */
export async function stopDaemon(descriptorPath: string): Promise<boolean> {
  const descriptor = await tryLoad(descriptorPath);
  if (descriptor === null) return false;
  if (!processMatchesDescriptor(descriptor.pid, descriptorPath)) {
    // Do not blind-kill a recycled pid; drop the stale descriptor only.
    await rm(descriptorPath, { force: true });
    return false;
  }
  killPid(descriptor.pid);
  await rm(descriptorPath, { force: true });
  return true;
}
