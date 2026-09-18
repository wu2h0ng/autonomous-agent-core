/**
 * `noem self-update` — the explicit, integrity-verified program-file upgrade
 * path for an installed single-file binary.
 *
 * WHAT IT IS
 *   `noem self-update --source <url>` fetches `<source>/manifest.json`, selects
 *   the artifact published for this platform, downloads it, verifies its
 *   SHA-256 against the checksum the manifest publishes, refuses anything that
 *   is not strictly newer than the running version, stages the bytes next to the
 *   installed program, atomically renames them over it, then runs the INSTALLED
 *   PATH in a fresh process as `<program> --version` and requires the expected
 *   version back. If that last check fails, the previous bytes are restored.
 *
 * WHAT IT IS NOT — no authority change
 *   This module replaces one program file on disk. It does not read, write,
 *   weaken or route around C7 (the non-writable external correction authority),
 *   permission modes, approvals, policy, evidence, `ActionReceipt` /
 *   `ReceiptStatus`, or the admission/promotion spine, and it exposes no API
 *   that can approve, admit, seal, promote, correct or self-modify anything.
 *   New bytes grant no capability those bytes do not already contain. A model
 *   cannot reach this path: it is an operator shell command, not a session or
 *   slash command, it reads no turn input and it changes no session state.
 *
 * INERT BY DEFAULT
 *   There is no default channel, no background check and no telemetry: the
 *   module fetches exactly once, from the source the operator names on the
 *   command line (`--source`) or in `AGENT_OS_SELF_UPDATE_SOURCE`, and only when
 *   the command is invoked. With no source it refuses (`no_source_configured`)
 *   and touches neither the network nor the disk. Publishing is founder-
 *   reserved, so nothing here bakes in a host, a URL or a channel name.
 *
 * VERIFICATION CHAIN (each step can only pass on what the step before it
 * established)
 *   1. source scheme is `file://` or `http(s)://`           -> source_invalid
 *   2. manifest fetched                                     -> source_unreachable
 *   3. manifest shape + our platform entry + a 64-hex
 *      `sha256` present                                     -> manifest_invalid / checksum_missing
 *   4. candidate version parses and is STRICTLY newer        -> manifest_invalid / up_to_date / downgrade_refused
 *   5. artifact bytes downloaded within the size bound      -> source_unreachable
 *   6. bytes are a program image (shebang/Mach-O/ELF/PE)    -> artifact_not_executable
 *   7. staged file written, fsynced, then READ BACK and its
 *      SHA-256 compared to step 3                           -> checksum_mismatch
 *   8. previous bytes copied aside (target never absent)    -> replace_failed
 *   9. staged renamed over the target (atomic, same fs)
 *  10. the installed path answers `--version` with the
 *      version from step 3, in a fresh process              -> rolled_back / rollback_failed
 *
 * INTEGRITY, NOT AUTHENTICITY — the open limit
 *   The checksum proves the bytes are the bytes the manifest described; it does
 *   NOT prove who published the manifest. A source that can serve the manifest
 *   can serve any artifact together with a matching checksum, so nothing here
 *   defends against a hostile source — only against a corrupt, truncated or
 *   mismatched one. A detached signature over the manifest is the fix and is
 *   deliberately NOT faked: this repository has no signing utility and no
 *   trust anchor, so no signature is verified and this module must not claim
 *   one. The manifest schema is versioned (`.../1`) so a signature can be added
 *   without reinterpreting existing manifests.
 *
 *   Downgrade attacks: a source that serves an OLDER artifact under its true
 *   (older) version is detected and refused (`downgrade_refused`), and an equal
 *   version is refused as `up_to_date`. A source that serves older BYTES under a
 *   FORGED newer version string is NOT detectable without a signature — that is
 *   the same authenticity gap as above, stated plainly rather than papered over.
 *
 * WHY THE REPLACE LOOKS LIKE THIS
 *   - Staged in the TARGET's own directory: `rename(2)` is atomic only within a
 *     filesystem, and a temp dir (e.g. /tmp) is very often a different one.
 *   - The previous bytes are COPIED aside, never moved: a move-then-rename would
 *     leave the install path missing entirely if the process died between the
 *     two renames. A copy cannot.
 *   - Rename, never write-in-place: writing in place corrupts the image for any
 *     process already running it and fails with ETXTBSY on Linux.
 *   - The sanity check spawns a FRESH process at the installed path. On macOS a
 *     replaced file is not the running executable — the kernel keeps the old
 *     vnode mapped, so this process would keep reporting the OLD version from
 *     memory no matter what landed on disk. Only a new exec proves the disk
 *     image works.
 *   - A journal file written before the rename makes an interruption
 *     recoverable: the next run decides from what is actually installed whether
 *     the update committed, never happened, or must be rolled back.
 *   - The sanity probe runs the candidate with `AGENT_OS_NO_AUTOSTART=1` so a
 *     probe can never auto-start a runtime daemon (this repository has been hit
 *     once by a stray autostart running a real provider turn against the
 *     operator's default store).
 */
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import {
  chmodSync,
  closeSync,
  existsSync,
  fsyncSync,
  openSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
  writeSync,
} from "node:fs";
import { basename } from "node:path";
import { fileURLToPath } from "node:url";
import { agentVersion } from "./version.js";

// ---------------------------------------------------------------------------
// Typed contract
// ---------------------------------------------------------------------------

/**
 * Terminal outcome of one invocation. Every path in `runSelfUpdate` returns
 * one of these; none of them is a silent no-op.
 */
export type SelfUpdateStatus =
  /** The installed program was replaced and the new bytes answer `--version`. */
  | "updated"
  /** `--check` only: the source publishes something strictly newer. */
  | "update_available"
  /** The source publishes the version that is already installed. */
  | "up_to_date"
  /** No source was named (no `--source`, no `AGENT_OS_SELF_UPDATE_SOURCE`). */
  | "no_source_configured"
  /** The source is not a `file://` or `http(s)://` URL. */
  | "source_invalid"
  /** The manifest or the artifact could not be read from the source. */
  | "source_unreachable"
  /** The manifest is not JSON, not our schema, or has no entry for this platform. */
  | "manifest_invalid"
  /** The manifest names an artifact but publishes no checksum for it. */
  | "checksum_missing"
  /** The downloaded bytes do not hash to the published checksum. */
  | "checksum_mismatch"
  /** The bytes are not a program image (or are empty). */
  | "artifact_not_executable"
  /** The source publishes an OLDER version than the one installed. */
  | "downgrade_refused"
  /** The install path could not be derived or is not an existing file. */
  | "target_unresolved"
  /** The staged/backup/rename step failed; the install path was not replaced. */
  | "replace_failed"
  /** The new bytes were installed, failed their own `--version`, and the previous bytes were put back. */
  | "rolled_back"
  /** The new bytes failed AND the previous bytes could not be put back. */
  | "rollback_failed"
  /** A previous run was interrupted and another process still holds this install path. */
  | "interrupted_update_pending"
  /** A previous interrupted run was found and resolved from what is installed. */
  | "interrupted_resolved";

/** Why an installed candidate was rejected after the replace. */
export type SanityRejection =
  /** The candidate could not be executed at all (ENOEXEC, EACCES, bad arch, signal). */
  | "spawn_error"
  /** The candidate ran and exited non-zero. */
  | "exit_nonzero"
  /** The candidate ran, exited zero, and reported a version other than the published one. */
  | "version_mismatch"
  /** The candidate did not answer within the probe deadline. */
  | "timeout";

/** How a previously interrupted run ended. */
export type InterruptedResolution =
  | "pending"
  | "committed"
  | "cleaned"
  | "restored"
  | "unrecoverable";

export interface InterruptedOutcome {
  resolution: InterruptedResolution;
  detail: string;
  journalPath: string;
  backupPath: string;
}

export interface SelfUpdateReport {
  status: SelfUpdateStatus;
  /** The installed program is in the state the command promised. */
  ok: boolean;
  /** 0 success, 1 refused/failed, 2 usage error (no source, no target, bad flags). */
  exitCode: number;
  /** One line, always present and always specific. */
  detail: string;
  source: string | null;
  target: string | null;
  fromVersion: string;
  toVersion: string | null;
  expectedSha256: string | null;
  /** SHA-256 measured over the bytes ON DISK in the staged file, not over memory. */
  measuredSha256: string | null;
  bytes: number | null;
  /** Previous bytes, kept after a successful update as the manual restore point. */
  backupPath: string | null;
  journalPath: string | null;
  rejection: SanityRejection | null;
  interrupted: InterruptedOutcome | null;
}

export interface SelfUpdateOptions {
  /** The source the operator named. Omitting it is a refusal, not a default. */
  source?: string | undefined;
  /** Install path; omitted means "the running program, when it is a compiled binary". */
  target?: string | undefined;
  /** Verify availability and version only: download the artifact? no. install? no. */
  check?: boolean;
  /** Env for the source fallback and for locating the running program. */
  env?: NodeJS.ProcessEnv;
  deps?: SelfUpdateDeps;
}

/** Test seams, mirroring `doctor.ts`'s injectable resolution. */
export interface SelfUpdateDeps {
  /** Current installed version; defaults to the embedded `package.json` version. */
  currentVersion?: () => string;
  /** Byte fetcher for `file://` and `http(s)://`. */
  fetchBytes?: (url: string, timeoutMs: number) => Promise<Uint8Array>;
  /** Platform key used to pick the manifest's artifact entry. */
  platform?: string;
  /** Execute a program image and return what it printed for `--version`. */
  probe?: (path: string, timeoutMs: number) => ProbeOutcome;
  /** Is this pid alive? (The journal's "another run still holds this path" test.) */
  pidAlive?: (pid: number) => boolean;
  fetchTimeoutMs?: number;
  probeTimeoutMs?: number;
}

export type ProbeOutcome =
  | { ok: true; version: string }
  | { ok: false; rejection: SanityRejection; detail: string };

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const SELF_UPDATE_MANIFEST_SCHEMA = "noem-self-update-manifest/1";
export const SELF_UPDATE_JOURNAL_SCHEMA = "noem-self-update-journal/1";
export const SELF_UPDATE_SOURCE_ENV = "AGENT_OS_SELF_UPDATE_SOURCE";
export const MANIFEST_FILE = "manifest.json";
export const STAGED_SUFFIX = ".noem-staged";
export const BACKUP_SUFFIX = ".noem-backup";
export const JOURNAL_SUFFIX = ".noem-update.json";

const DEFAULT_FETCH_TIMEOUT_MS = 60_000;
const DEFAULT_PROBE_TIMEOUT_MS = 20_000;
/** Bounded so a hostile or broken source cannot fill the disk. */
const MAX_ARTIFACT_BYTES = 512 * 1024 * 1024;
const VERSION_ARG = "--version";
const INTERPRETER_NAMES = new Set(["node", "node.exe", "bun", "bun.exe", "deno", "tsx", "ts-node"]);

interface ManifestArtifact {
  file: string;
  sha256: string | null;
  bytes: number | null;
}

interface UpdateJournal {
  schema: string;
  pid: number;
  target: string;
  backup: string;
  from_version: string;
  to_version: string;
  expected_sha256: string;
  started_at: string;
}

// ---------------------------------------------------------------------------
// Version comparison
// ---------------------------------------------------------------------------

export interface ParsedVersion {
  major: number;
  minor: number;
  patch: number;
  prerelease: string | null;
}

/** `X.Y.Z`, optional `-prerelease`, optional `+build`. Null when it is not one. */
export function parseVersion(raw: string): ParsedVersion | null {
  const match = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/.exec(raw.trim());
  if (match === null) return null;
  const [, major, minor, patch, prerelease] = match;
  return {
    major: Number(major),
    minor: Number(minor),
    patch: Number(patch),
    prerelease: prerelease ?? null,
  };
}

/** `1 if a > b`, `-1 if a < b`, `0 if equal`, `null when either side is unparseable`. */
export function compareVersions(a: string, b: string): number | null {
  const left = parseVersion(a);
  const right = parseVersion(b);
  if (left === null || right === null) return null;
  for (const key of ["major", "minor", "patch"] as const) {
    if (left[key] !== right[key]) return left[key] < right[key] ? -1 : 1;
  }
  return comparePrerelease(left.prerelease, right.prerelease);
}

/** Absence of a prerelease ranks ABOVE its presence (1.0.0 > 1.0.0-rc.1). */
function comparePrerelease(a: string | null, b: string | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  const left = a.split(".");
  const right = b.split(".");
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    const l = left[index];
    const r = right[index];
    if (l === undefined) return -1;
    if (r === undefined) return 1;
    const ln = /^\d+$/.test(l) ? Number(l) : null;
    const rn = /^\d+$/.test(r) ? Number(r) : null;
    if (ln !== null && rn !== null) {
      if (ln !== rn) return ln < rn ? -1 : 1;
      continue;
    }
    if (ln !== null) return -1;
    if (rn !== null) return 1;
    if (l !== r) return l < r ? -1 : 1;
  }
  return 0;
}

// ---------------------------------------------------------------------------
// Sources, targets, fetchers
// ---------------------------------------------------------------------------

function platformKey(deps: SelfUpdateDeps): string {
  return deps.platform ?? `${process.platform}-${process.arch}`;
}

function sourceScheme(source: string): "file" | "http" | "https" | null {
  try {
    const url = new URL(source);
    if (url.protocol === "file:") return "file";
    if (url.protocol === "http:") return "http";
    if (url.protocol === "https:") return "https";
    return null;
  } catch {
    return null;
  }
}

/** `<source>/<name>` with the source treated as a directory. */
export function sourceUrl(source: string, name: string): string {
  const base = source.endsWith("/") ? source : `${source}/`;
  return new URL(name, base).toString();
}

export const defaultFetchBytes = async (
  url: string,
  timeoutMs: number,
): Promise<Uint8Array> => {
  const parsed = new URL(url);
  if (parsed.protocol === "file:") {
    return new Uint8Array(readFileSync(fileURLToPath(parsed)));
  }
  const response = await fetch(url, {
    signal: AbortSignal.timeout(timeoutMs),
    redirect: "follow",
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ${response.statusText}`.trim());
  }
  return new Uint8Array(await response.arrayBuffer());
};

/**
 * Absolute path of the program file this process is running as, or null when it
 * cannot be known. A `bun build --compile` binary IS the program; under an
 * interpreter (`bun run src/cli.tsx`, `node dist/cli.js`) `process.execPath` is
 * the interpreter, and replacing it would destroy the user's Bun/Node — so that
 * case resolves to null and the operator must pass `--target`.
 *
 * (Measured: a compiled bun binary reports `process.argv[1]` as the virtual
 * `/$bunfs/root/<name>` and `Bun.main` likewise, so neither identifies the
 * installed file; `process.execPath` does.)
 */
export function defaultInstallTarget(): string | null {
  const execPath = process.execPath;
  if (typeof execPath !== "string" || execPath === "") return null;
  const name = basename(execPath).toLowerCase();
  if (INTERPRETER_NAMES.has(name)) return null;
  return execPath;
}

interface ResolvedTarget {
  path: string;
  ok: boolean;
  detail: string;
}

function resolveTarget(explicit: string | undefined): ResolvedTarget {
  const candidate = explicit ?? defaultInstallTarget() ?? "";
  if (candidate === "") {
    return {
      path: "",
      ok: false,
      detail:
        "no install path: this process is an interpreter running a script, not an installed " +
        "single-file binary — pass --target <path-to-installed-program>",
    };
  }
  let real: string;
  try {
    real = realpathSync(candidate);
  } catch {
    return { path: candidate, ok: false, detail: `${candidate} does not exist (or is a broken symlink)` };
  }
  let stat;
  try {
    stat = statSync(real);
  } catch (cause) {
    return { path: real, ok: false, detail: `${real} is not readable: ${(cause as Error).message}` };
  }
  if (!stat.isFile()) {
    return { path: real, ok: false, detail: `${real} is not a regular file — refusing to replace it` };
  }
  return { path: real, ok: true, detail: real };
}

/** A program image: a shebang script or a Mach-O / ELF / PE binary. */
export function artifactImageKind(bytes: Uint8Array): "shebang" | "macho" | "elf" | "pe" | null {
  if (bytes.length < 4) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (bytes[0] === 0x23 && bytes[1] === 0x21) return "shebang"; // "#!"
  // Both byte orders: a Mach-O magic is stored in the host's order, so a
  // little-endian arm64 build starts cf fa ed fe (which reads big-endian as
  // cffaedfe, not one of the canonical constants).
  const be = view.getUint32(0, false);
  const le = view.getUint32(0, true);
  for (const word of [be, le]) {
    if (word === 0xfeedface || word === 0xfeedfacf || word === 0xcafebabe) return "macho";
  }
  if (bytes[0] === 0x7f && bytes[1] === 0x45 && bytes[2] === 0x4c && bytes[3] === 0x46) return "elf";
  if (bytes[0] === 0x4d && bytes[1] === 0x5a) return "pe";
  return null;
}

/**
 * Run `<path> --version` in a FRESH process.
 *
 * `AGENT_OS_NO_AUTOSTART=1` is forced so a probe can never leave a runtime
 * daemon behind: `--version` returns before daemon resolution today, and this
 * keeps a regression in that ordering from turning a self-update into an
 * autostart against the operator's real store.
 */
export function defaultProbe(path: string, timeoutMs: number): ProbeOutcome {
  const result = spawnSync(path, [VERSION_ARG], {
    encoding: "utf8",
    timeout: timeoutMs,
    env: { ...process.env, AGENT_OS_NO_AUTOSTART: "1" },
  });
  if (result.error) {
    const code = (result.error as NodeJS.ErrnoException).code ?? "unknown";
    const message = result.error.message;
    if (code === "ETIMEDOUT") return { ok: false, rejection: "timeout", detail: `no answer within ${timeoutMs}ms` };
    return {
      ok: false,
      rejection: "spawn_error",
      // Node sometimes prefixes the code itself, e.g. "EBADMACHO: unknown error".
      detail: message.startsWith(`${code}:`) ? message : `${code}: ${message}`,
    };
  }
  if (result.status !== 0) {
    const how = result.status === null ? `killed by ${result.signal ?? "a signal"}` : `exit ${result.status}`;
    const noise = `${result.stderr ?? ""}`.trim().split("\n").slice(-1)[0] ?? "";
    return {
      ok: false,
      rejection: "exit_nonzero",
      detail: `${how}${noise === "" ? "" : ` — ${noise}`}`,
    };
  }
  const version = `${result.stdout ?? ""}`.trim();
  if (version === "") {
    return { ok: false, rejection: "spawn_error", detail: "printed nothing for --version" };
  }
  return { ok: true, version };
}

// ---------------------------------------------------------------------------
// Manifest
// ---------------------------------------------------------------------------

interface ManifestRead {
  version: string | null;
  artifact: ManifestArtifact | null;
  status: SelfUpdateStatus | null;
  detail: string;
}

/**
 * Hand-validated rather than schema-validated on purpose: `checksum_missing`
 * must stay distinguishable from `manifest_invalid`, and an aggregate schema
 * error would collapse exactly that difference — the distinction is part of the
 * contract, so it is checked directly.
 */
export function readManifest(raw: string, platform: string): ManifestRead {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (cause) {
    return { version: null, artifact: null, status: "manifest_invalid", detail: `not JSON: ${(cause as Error).message}` };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { version: null, artifact: null, status: "manifest_invalid", detail: "not a JSON object" };
  }
  const body = parsed as Record<string, unknown>;
  if (body["schema"] !== SELF_UPDATE_MANIFEST_SCHEMA) {
    return {
      version: null,
      artifact: null,
      status: "manifest_invalid",
      detail: `schema ${JSON.stringify(body["schema"])} is not ${SELF_UPDATE_MANIFEST_SCHEMA}`,
    };
  }
  const version = body["version"];
  if (typeof version !== "string" || parseVersion(version) === null) {
    return { version: null, artifact: null, status: "manifest_invalid", detail: `version ${JSON.stringify(version)} is not X.Y.Z` };
  }
  const artifacts = body["artifacts"];
  if (typeof artifacts !== "object" || artifacts === null || Array.isArray(artifacts)) {
    return { version: null, artifact: null, status: "manifest_invalid", detail: "artifacts is not an object" };
  }
  const entry = (artifacts as Record<string, unknown>)[platform];
  if (entry === undefined) {
    return {
      version,
      artifact: null,
      status: "manifest_invalid",
      detail: `no artifact published for ${platform} (published: ${Object.keys(artifacts as object).sort().join(", ") || "none"})`,
    };
  }
  if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
    return { version, artifact: null, status: "manifest_invalid", detail: `artifacts.${platform} is not an object` };
  }
  const fields = entry as Record<string, unknown>;
  const file = fields["file"];
  // A bare basename only: a manifest must not be able to point the download
  // outside the source directory (../ or an absolute path).
  if (typeof file !== "string" || file === "" || file !== basename(file) || file.includes("\\")) {
    return {
      version,
      artifact: null,
      status: "manifest_invalid",
      detail: `artifacts.${platform}.file ${JSON.stringify(file)} is not a bare file name`,
    };
  }
  const sha256 = fields["sha256"];
  if (sha256 === undefined || sha256 === null || sha256 === "") {
    return {
      version,
      artifact: null,
      status: "checksum_missing",
      detail: `artifacts.${platform} publishes ${file} with no sha256 — an unverifiable artifact is refused, never installed`,
    };
  }
  if (typeof sha256 !== "string" || !/^[0-9a-fA-F]{64}$/.test(sha256)) {
    return {
      version,
      artifact: null,
      status: "manifest_invalid",
      detail: `artifacts.${platform}.sha256 ${JSON.stringify(sha256)} is not 64 hex digits`,
    };
  }
  const bytes = fields["bytes"];
  if (bytes !== undefined && bytes !== null && (typeof bytes !== "number" || !Number.isInteger(bytes) || bytes < 0)) {
    return { version, artifact: null, status: "manifest_invalid", detail: `artifacts.${platform}.bytes is not a byte count` };
  }
  return {
    version,
    artifact: { file, sha256: sha256.toLowerCase(), bytes: typeof bytes === "number" ? bytes : null },
    status: null,
    detail: `manifest declares ${version} for ${platform}`,
  };
}

// ---------------------------------------------------------------------------
// Journal (interruption recovery)
// ---------------------------------------------------------------------------

export function journalPathFor(target: string): string {
  return `${target}${JOURNAL_SUFFIX}`;
}

export function backupPathFor(target: string): string {
  return `${target}${BACKUP_SUFFIX}`;
}

function readJournal(target: string): UpdateJournal | null {
  const path = journalPathFor(target);
  if (!existsSync(path)) return null;
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8")) as Partial<UpdateJournal>;
    if (parsed.schema !== SELF_UPDATE_JOURNAL_SCHEMA || typeof parsed.pid !== "number") return null;
    return parsed as UpdateJournal;
  } catch {
    return null;
  }
}

function writeJournal(path: string, journal: UpdateJournal): void {
  writeFileSync(path, `${JSON.stringify(journal, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  const fd = openSync(path, "r+");
  try {
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
}

function defaultPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (cause) {
    return (cause as NodeJS.ErrnoException).code === "EPERM";
  }
}

/**
 * Decide an interrupted run's fate from what is ACTUALLY installed, not from
 * what the journal intended: the journal only says a replace was in flight.
 */
function recoverInterrupted(
  target: string,
  journal: UpdateJournal,
  probe: (path: string, timeoutMs: number) => ProbeOutcome,
  pidAlive: (pid: number) => boolean,
  probeTimeoutMs: number,
): InterruptedOutcome {
  const journalPath = journalPathFor(target);
  const backupPath = journal.backup;
  const base = { journalPath, backupPath };
  if (pidAlive(journal.pid)) {
    return {
      ...base,
      resolution: "pending",
      detail: `pid ${journal.pid} is still running the update started at ${journal.started_at}`,
    };
  }
  const staged = `${target}${STAGED_SUFFIX}`;
  const installed = probe(target, probeTimeoutMs);
  const version = installed.ok ? installed.version : null;

  if (version === journal.to_version) {
    if (existsSync(staged)) rmSync(staged, { force: true });
    rmSync(journalPath, { force: true });
    return { ...base, resolution: "committed", detail: `the replace landed: ${journal.to_version} answers --version` };
  }
  if (version === journal.from_version) {
    // Either the rename never happened or a rollback already finished; either
    // way the installed program is the expected one, so the crash changed nothing.
    if (existsSync(staged)) rmSync(staged, { force: true });
    if (existsSync(backupPath)) rmSync(backupPath, { force: true });
    rmSync(journalPath, { force: true });
    return { ...base, resolution: "cleaned", detail: `the install path still answers ${journal.from_version}; nothing was changed` };
  }
  if (!existsSync(backupPath)) {
    rmSync(journalPath, { force: true });
    return {
      ...base,
      resolution: "unrecoverable",
      detail:
        `the install path answers ${version ?? "nothing"} (expected ${journal.from_version} or ` +
        `${journal.to_version}) and no backup exists at ${backupPath}`,
    };
  }
  const backupProbe = probe(backupPath, probeTimeoutMs);
  if (backupProbe.ok && backupProbe.version === journal.from_version) {
    renameSync(backupPath, target);
    rmSync(journalPath, { force: true });
    return { ...base, resolution: "restored", detail: `restored ${journal.from_version} from ${backupPath}` };
  }
  rmSync(journalPath, { force: true });
  return {
    ...base,
    resolution: "unrecoverable",
    detail:
      `the install path answers ${version ?? "nothing"} and the backup at ${backupPath} does not ` +
      `answer ${journal.from_version}${backupProbe.ok ? ` (it answers ${backupProbe.version})` : ` (${backupProbe.detail})`}`,
  };
}

// ---------------------------------------------------------------------------
// Report construction
// ---------------------------------------------------------------------------

interface ReportInput {
  status: SelfUpdateStatus;
  detail: string;
  source?: string | null;
  target?: string | null;
  fromVersion: string;
  toVersion?: string | null;
  expectedSha256?: string | null;
  measuredSha256?: string | null;
  bytes?: number | null;
  backupPath?: string | null;
  journalPath?: string | null;
  rejection?: SanityRejection | null;
  interrupted?: InterruptedOutcome | null;
}

const USAGE_STATUSES: readonly SelfUpdateStatus[] = ["no_source_configured", "source_invalid", "target_unresolved"];
const SUCCESS_STATUSES: readonly SelfUpdateStatus[] = ["updated", "update_available", "up_to_date", "interrupted_resolved"];

function report(input: ReportInput): SelfUpdateReport {
  const exitCode = USAGE_STATUSES.includes(input.status) ? 2 : SUCCESS_STATUSES.includes(input.status) ? 0 : 1;
  return {
    status: input.status,
    ok: exitCode === 0,
    exitCode,
    detail: input.detail,
    source: input.source ?? null,
    target: input.target ?? null,
    fromVersion: input.fromVersion,
    toVersion: input.toVersion ?? null,
    expectedSha256: input.expectedSha256 ?? null,
    measuredSha256: input.measuredSha256 ?? null,
    bytes: input.bytes ?? null,
    backupPath: input.backupPath ?? null,
    journalPath: input.journalPath ?? null,
    rejection: input.rejection ?? null,
    interrupted: input.interrupted ?? null,
  };
}

/** The one append-only trace this command leaves: it is not a receipt and grants nothing. */
export interface SelfUpdateTraceEvent {
  event: "self_update";
  status: SelfUpdateStatus;
  from_version: string;
  to_version: string | null;
  target: string | null;
  sha256: string | null;
  detail: string;
}

export function traceEvent(reportValue: SelfUpdateReport): SelfUpdateTraceEvent {
  return {
    event: "self_update",
    status: reportValue.status,
    from_version: reportValue.fromVersion,
    to_version: reportValue.toVersion,
    target: reportValue.target,
    sha256: reportValue.measuredSha256,
    detail: reportValue.detail,
  };
}

// ---------------------------------------------------------------------------
// The command
// ---------------------------------------------------------------------------

function sha256Hex(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

/** Write bytes with fsync, so a power loss cannot leave a half-written image. */
function writeSynced(path: string, bytes: Uint8Array, mode: number): void {
  const fd = openSync(path, "w", mode);
  try {
    let written = 0;
    while (written < bytes.length) {
      written += writeSync(fd, bytes, written, bytes.length - written);
    }
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  chmodSync(path, mode);
}

function installModeFor(target: string): number {
  const current = statSync(target).mode & 0o777;
  // Keep the install's own mode, but a program file must be executable.
  return current | 0o111;
}

export async function runSelfUpdate(options: SelfUpdateOptions = {}): Promise<SelfUpdateReport> {
  const deps = options.deps ?? {};
  const env = options.env ?? process.env;
  const current = (deps.currentVersion ?? agentVersion)();
  const fetchBytes = deps.fetchBytes ?? defaultFetchBytes;
  const probe = deps.probe ?? defaultProbe;
  const pidAlive = deps.pidAlive ?? defaultPidAlive;
  const fetchTimeoutMs = deps.fetchTimeoutMs ?? DEFAULT_FETCH_TIMEOUT_MS;
  const probeTimeoutMs = deps.probeTimeoutMs ?? DEFAULT_PROBE_TIMEOUT_MS;

  // The source gate comes FIRST, before anything is resolved or read: with no
  // source named this command must do nothing at all — no probe, no network,
  // no touch of the install. That is what "default off" means here, so it is
  // checked before the install path is even looked up.
  const source = (options.source ?? env[SELF_UPDATE_SOURCE_ENV] ?? "").trim();
  const sourceDetail = source === "" ? null : source;
  if (sourceDetail === null) {
    return report({
      status: "no_source_configured",
      detail:
        `no source named: pass --source <url> or set ${SELF_UPDATE_SOURCE_ENV}. ` +
        "This command has no default release channel on purpose — publishing is a " +
        "founder-reserved decision — so it stays inert until an operator names one.",
      source: null,
      target: options.target ?? defaultInstallTarget(),
      fromVersion: current,
    });
  }
  if (sourceScheme(sourceDetail) === null) {
    return report({
      status: "source_invalid",
      detail: `${sourceDetail} is not a file://, http:// or https:// URL`,
      source: sourceDetail,
      target: options.target ?? defaultInstallTarget(),
      fromVersion: current,
    });
  }

  const resolved = resolveTarget(options.target);
  if (!resolved.ok) {
    return report({ status: "target_unresolved", detail: resolved.detail, source: sourceDetail, fromVersion: current });
  }
  const target = resolved.path;

  // A previous run that was killed mid-replace is decided from what is on disk
  // now, before a new one is allowed to touch the same path.
  let interrupted: InterruptedOutcome | null = null;
  const journal = readJournal(target);
  if (journal !== null) {
    interrupted = recoverInterrupted(target, journal, probe, pidAlive, probeTimeoutMs);
    if (interrupted.resolution === "pending") {
      return report({
        status: "interrupted_update_pending",
        detail: `another self-update holds ${target}: ${interrupted.detail}`,
        source: sourceDetail,
        target,
        fromVersion: current,
        journalPath: interrupted.journalPath,
        backupPath: interrupted.backupPath,
        interrupted,
      });
    }
    if (interrupted.resolution === "unrecoverable") {
      return report({
        status: "rollback_failed",
        detail: `an interrupted update left ${target} unusable and could not be resolved: ${interrupted.detail}`,
        source: sourceDetail,
        target,
        fromVersion: current,
        journalPath: interrupted.journalPath,
        backupPath: interrupted.backupPath,
        interrupted,
      });
    }
  }

  // 2./3. manifest
  let manifestRaw: string;
  try {
    manifestRaw = new TextDecoder().decode(await fetchBytes(sourceUrl(sourceDetail, MANIFEST_FILE), fetchTimeoutMs));
  } catch (cause) {
    return report({
      status: "source_unreachable",
      detail: `cannot read ${sourceUrl(sourceDetail, MANIFEST_FILE)}: ${(cause as Error).message}`,
      source: sourceDetail,
      target,
      fromVersion: current,
      interrupted,
    });
  }
  const platform = platformKey(deps);
  const read = readManifest(manifestRaw, platform);
  if (read.status !== null) {
    return report({
      status: read.status,
      detail: read.detail,
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion: read.version,
      interrupted,
    });
  }
  const artifact = read.artifact as ManifestArtifact;
  const toVersion = read.version as string;
  const expectedSha256 = artifact.sha256 as string;

  // 4. strictly newer, or refuse
  const ordering = compareVersions(toVersion, current);
  if (ordering === null) {
    return report({
      status: "manifest_invalid",
      detail: `the installed version ${JSON.stringify(current)} is not X.Y.Z, so it cannot be ordered against ${toVersion}`,
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion,
      expectedSha256,
      interrupted,
    });
  }
  if (ordering === 0) {
    return report({
      status: "up_to_date",
      detail: `already at ${current}; the source publishes ${toVersion}`,
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion,
      expectedSha256,
      interrupted,
    });
  }
  if (ordering < 0) {
    return report({
      status: "downgrade_refused",
      detail:
        `the source publishes ${toVersion}, which is OLDER than the installed ${current} — refused. ` +
        "A mistaken or malicious source cannot walk this install backwards, but bytes carrying a " +
        "forged newer version string would not be detectable without a signature (none is verified here).",
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion,
      expectedSha256,
      interrupted,
    });
  }
  if (options.check === true) {
    return report({
      status: "update_available",
      detail:
        `the source publishes ${toVersion} (installed ${current}). --check downloaded nothing and ` +
        "verified nothing: run without --check to verify the checksum and install.",
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion,
      expectedSha256,
      interrupted,
    });
  }

  // 5. artifact
  const artifactUrl = sourceUrl(sourceDetail, artifact.file);
  let bytes: Uint8Array;
  try {
    bytes = await fetchBytes(artifactUrl, fetchTimeoutMs);
  } catch (cause) {
    return report({
      status: "source_unreachable",
      detail: `cannot read ${artifactUrl}: ${(cause as Error).message}`,
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion,
      expectedSha256,
      interrupted,
    });
  }
  if (bytes.length === 0) {
    return report({
      status: "artifact_not_executable",
      detail: `${artifactUrl} is empty (0 bytes)`,
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion,
      expectedSha256,
      interrupted,
    });
  }
  if (bytes.length > MAX_ARTIFACT_BYTES) {
    return report({
      status: "artifact_not_executable",
      detail: `${artifactUrl} is ${bytes.length} bytes, over the ${MAX_ARTIFACT_BYTES}-byte bound`,
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion,
      expectedSha256,
      interrupted,
    });
  }
  if (artifactImageKind(bytes) === null) {
    return report({
      status: "artifact_not_executable",
      detail: `${artifactUrl} is not a program image (no shebang, Mach-O, ELF or PE magic)`,
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion,
      expectedSha256,
      interrupted,
    });
  }
  if (artifact.bytes !== null && artifact.bytes !== bytes.length) {
    return report({
      status: "checksum_mismatch",
      detail: `the manifest says ${artifact.file} is ${artifact.bytes} bytes; the source served ${bytes.length}`,
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion,
      expectedSha256,
      interrupted,
    });
  }

  // 7. stage next to the target, then verify the bytes ON DISK: the checksum
  // must cover what will be renamed into place, not what was once in memory.
  const stagedPath = `${target}${STAGED_SUFFIX}`;
  const backupPath = backupPathFor(target);
  const mode = installModeFor(target);
  let measured: string;
  try {
    writeSynced(stagedPath, bytes, mode);
    measured = sha256Hex(new Uint8Array(readFileSync(stagedPath)));
  } catch (cause) {
    rmSync(stagedPath, { force: true });
    return report({
      status: "replace_failed",
      detail: `cannot stage next to ${target}: ${(cause as Error).message}`,
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion,
      expectedSha256,
      backupPath: null,
      interrupted,
    });
  }
  if (measured !== expectedSha256) {
    rmSync(stagedPath, { force: true });
    return report({
      status: "checksum_mismatch",
      detail:
        `the staged bytes hash to ${measured}; the manifest publishes ${expectedSha256} — ` +
        "refused, and the installed program was not touched",
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion,
      expectedSha256,
      measuredSha256: measured,
      bytes: bytes.length,
      interrupted,
    });
  }

  // 8. previous bytes aside (copy, so the target is never absent), 9. journal.
  try {
    const previous = new Uint8Array(readFileSync(target));
    writeSynced(backupPath, previous, mode);
    if (statSync(backupPath).size !== previous.length) {
      throw new Error(`wrote ${statSync(backupPath).size} of ${previous.length} bytes`);
    }
  } catch (cause) {
    rmSync(stagedPath, { force: true });
    return report({
      status: "replace_failed",
      detail: `cannot back up ${target}: ${(cause as Error).message}`,
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion,
      expectedSha256,
      measuredSha256: measured,
      bytes: bytes.length,
      interrupted,
    });
  }

  const journalPath = journalPathFor(target);
  try {
    writeJournal(journalPath, {
      schema: SELF_UPDATE_JOURNAL_SCHEMA,
      pid: process.pid,
      target,
      backup: backupPath,
      from_version: current,
      to_version: toVersion,
      expected_sha256: expectedSha256,
      started_at: new Date().toISOString(),
    });
    renameSync(stagedPath, target);
  } catch (cause) {
    rmSync(stagedPath, { force: true });
    rmSync(journalPath, { force: true });
    return report({
      status: "replace_failed",
      detail: `cannot replace ${target}: ${(cause as Error).message}`,
      source: sourceDetail,
      target,
      fromVersion: current,
      toVersion,
      expectedSha256,
      measuredSha256: measured,
      bytes: bytes.length,
      backupPath,
      journalPath,
      interrupted,
    });
  }

  // 10. the installed path, in a NEW process.
  const installed = probe(target, probeTimeoutMs);
  const base = {
    source: sourceDetail,
    target,
    fromVersion: current,
    toVersion,
    expectedSha256,
    measuredSha256: measured,
    bytes: bytes.length,
    backupPath,
    journalPath,
    interrupted,
  };
  if (installed.ok && installed.version === toVersion) {
    rmSync(journalPath, { force: true });
    return report({
      ...base,
      status: "updated",
      detail:
        `replaced ${target}: ${current} -> ${toVersion} (${bytes.length} bytes, sha256 ${measured.slice(0, 12)}…); ` +
        `the previous bytes stay at ${backupPath}`,
    });
  }

  const rejection: SanityRejection = installed.ok ? "version_mismatch" : installed.rejection;
  const why = installed.ok
    ? `the installed path answers ${installed.version} for --version, not ${toVersion}`
    : `the installed path does not run: ${installed.detail}`;

  // Rollback. Renaming the copy back is itself atomic, so an interruption
  // leaves either the new bytes or the old ones — never nothing.
  try {
    renameSync(backupPath, target);
  } catch (cause) {
    return report({
      ...base,
      status: "rollback_failed",
      rejection,
      detail:
        `${why}. The previous bytes could NOT be restored from ${backupPath} ` +
        `(${(cause as Error).message}) — restore them by hand, e.g. ` +
        `"cp ${backupPath} ${target}". The journal is at ${journalPath}.`,
    });
  }
  const restored = probe(target, probeTimeoutMs);
  if (!restored.ok || restored.version !== current) {
    return report({
      ...base,
      status: "rollback_failed",
      rejection,
      detail:
        `${why}. The previous bytes were copied back but do not verify ` +
        `(${restored.ok ? `they answer ${restored.version}, expected ${current}` : restored.detail}). ` +
        `The journal is at ${journalPath}.`,
    });
  }
  rmSync(journalPath, { force: true });
  return report({
    ...base,
    status: "rolled_back",
    rejection,
    detail: `${why}; restored ${current} from ${backupPath} and verified it again`,
  });
}

// ---------------------------------------------------------------------------
// --status (read-only)
// ---------------------------------------------------------------------------

export interface SelfUpdateStatusReport {
  currentVersion: string;
  installPath: string | null;
  installPathDetail: string;
  source: string | null;
  journalPath: string | null;
  journal: UpdateJournal | null;
  journalOwnerAlive: boolean;
  backupPath: string | null;
  ok: boolean;
}

/** Read-only: names the install, the configured source and any pending journal. */
export function runSelfUpdateStatus(
  options: { target?: string | undefined; env?: NodeJS.ProcessEnv; deps?: SelfUpdateDeps } = {},
): SelfUpdateStatusReport {
  const deps = options.deps ?? {};
  const env = options.env ?? process.env;
  const resolved = resolveTarget(options.target);
  const journal = resolved.ok ? readJournal(resolved.path) : null;
  const source = (env[SELF_UPDATE_SOURCE_ENV] ?? "").trim();
  return {
    currentVersion: (deps.currentVersion ?? agentVersion)(),
    installPath: resolved.ok ? resolved.path : null,
    installPathDetail: resolved.detail,
    source: source === "" ? null : source,
    journalPath: resolved.ok ? journalPathFor(resolved.path) : null,
    journal,
    journalOwnerAlive:
      journal === null ? false : (deps.pidAlive ?? defaultPidAlive)(journal.pid),
    backupPath: resolved.ok ? backupPathFor(resolved.path) : null,
    ok: journal === null,
  };
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

export function renderSelfUpdateText(value: SelfUpdateReport): string {
  const lines = [
    `${value.ok ? "✓" : "✗"} ${value.status}: ${value.detail}`,
    `  from ${value.fromVersion}${value.toVersion === null ? "" : ` -> ${value.toVersion}`}`,
  ];
  if (value.target !== null) lines.push(`  program ${value.target}`);
  if (value.source !== null) lines.push(`  source ${value.source}`);
  if (value.expectedSha256 !== null) {
    lines.push(
      `  sha256 expected ${value.expectedSha256}` +
        (value.measuredSha256 === null ? " (not measured)" : ` / measured ${value.measuredSha256}`),
    );
  }
  if (value.rejection !== null) lines.push(`  rejection ${value.rejection}`);
  if (value.backupPath !== null) lines.push(`  previous bytes ${value.backupPath}`);
  if (value.interrupted !== null) {
    lines.push(`  interrupted run: ${value.interrupted.resolution} — ${value.interrupted.detail}`);
  }
  lines.push(
    "  no governance object was touched: this replaced a program file only " +
      "(C7 / permissions / approval / policy / evidence / ActionReceipt unchanged)",
  );
  return `${lines.join("\n")}\n`;
}

export function renderSelfUpdateStatusText(value: SelfUpdateStatusReport): string {
  const lines = [
    `noem ${value.currentVersion}`,
    `  program ${value.installPath ?? `(not resolvable) ${value.installPathDetail}`}`,
    `  source ${value.source ?? `(none configured; ${SELF_UPDATE_SOURCE_ENV} is unset)`}`,
  ];
  if (value.journal === null) {
    lines.push("  no interrupted run: no update journal next to the program");
  } else {
    lines.push(
      `  INTERRUPTED RUN: ${value.journal.from_version} -> ${value.journal.to_version} by pid ` +
        `${value.journal.pid} (${value.journalOwnerAlive ? "still alive" : "gone"}), started ${value.journal.started_at}`,
      `    journal ${value.journalPath}`,
      `    previous bytes ${value.backupPath}${existsSync(value.backupPath ?? "") ? "" : " (missing)"}`,
      "    the next `noem self-update` resolves this before touching the program",
    );
  }
  return `${lines.join("\n")}\n`;
}
