#!/usr/bin/env node
/**
 * Frame-check entry point for the cli-ts TUI: one bounded process per check,
 * inside a bounded suite.
 *
 * WHY THIS EXISTS. The TUI's terminal-level claims -- key handling, modal
 * layers, the theme actually repainting, the composer invariants, the home
 * panel, search, syntax highlighting -- can only be established by looking at a
 * real frame. Those checks live in `scripts/pty_*.py`, and until this entry
 * point existed none of them ran in CI: the cli-ts job ran the node:test suite
 * (which never touches a pty), a typecheck and the install smoke. A rendering or
 * key-handling regression was therefore caught only if someone remembered to run
 * the scripts by hand. This is the same class of gap the product suite and the
 * eval suite each had once, and it is closed the same way: a real CI step, with
 * a runner that makes a failure attributable.
 *
 * SHAPE. The same shape as scripts/test-ci.mjs, which already solved "a suite
 * that hangs on the runner with no attribution": one child process per check,
 * each with its own deadline, all inside a SUITE budget. The check's name is
 * printed before it runs, so a hang is reported as "this check timed out"
 * instead of as an anonymous cancelled job. A check the budget never reached is
 * reported as a FAILURE, never as a pass or a skip: a truncated suite must not
 * look like a complete one.
 *
 * WHAT IS NOT RUN IN CI, AND WHY. `EVIDENCE_ONLY` below lists checks that print
 * frames and booleans and have no failing exit path. Running them in CI would
 * add a step that cannot go red -- the "green but toothless" pattern this repo
 * rejects (AGENTS.md §7.1, §14) -- so they stay in the local `check:frames` set
 * instead. Making them CI gates means giving them a verdict first. Every file on
 * disk must appear in exactly one of the two tables: a new `scripts/pty_*.py`
 * that nobody classifies fails this runner with a message saying so, which is
 * how the coverage cannot silently stay partial.
 *
 * NO OPERATOR STORE, NO `uv`. Two properties the checks themselves do not
 * provide:
 *   * the client persists history/theme/vim state under `$HOME/.agent-os/`, and
 *     the daemon reads its persisted provider config from there too, so this
 *     runner points `AGENT_OS_CLI_STATE` / `AGENT_OS_PROVIDER_CONFIG` /
 *     `AGENT_OS_PRICING_FILE` at a temp directory of its own and drops any
 *     ambient `AGENT_OS_RUNTIME_*` (a stale descriptor exported in the caller's
 *     shell must not decide which daemon a check talks to);
 *   * the checks shelled out to `uv run python` to start the hermetic daemon,
 *     which the cli-ts CI job does not have (it installs the same pins with pip;
 *     see the `no uv, which CI need not have` note in scripts/install_smoke.sh).
 *     They now start it with `sys.executable` -- the interpreter running the
 *     check -- so this runner only has to pick ONE interpreter, and the check
 *     and its daemon can never disagree about the environment.
 *
 * `--list` prints the resolved plan as JSON without running anything;
 * tests/product/test_ci_gate_wiring.py drives it to assert the workflow, the
 * scripts this package declares and the files on disk agree.
 */
import { spawn } from "node:child_process";
import { accessSync, constants, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import { fileURLToPath } from "node:url";

const PACKAGE_ROOT = fileURLToPath(new URL("..", import.meta.url));
const SCRIPTS_DIR = join(PACKAGE_ROOT, "scripts");

// The enforced defaults: a per-check deadline (how long one hung check may block,
// and what it is killed and reported as) and a suite budget (the wall clock the
// whole loop shares).
//
// Measured on this tree (2026-09-19, macOS): the 15 CI gates below run a full
// sequential pass in ~507 s end to end. The time is dominated by fixed `sleep`s
// inside the checks -- the TUI has to be given time to paint -- so a slower
// runner scales it far less than it scales CPU-bound work; pty_fullscreen_vim.py
// is the longest single check. 240 s per check stays ~1.7x the slowest, and the
// 720 s budget is ~1.4x the measured pass. 19 pty_*.py files exist on disk: the
// 15 gates here plus 4 evidence-only captures (see EVIDENCE_ONLY) that print
// frames/booleans with no non-zero exit path; `check:frames --all` runs all 19.
//
// The budget is what has to fit the cli-ts job's own `timeout-minutes` alongside
// everything else in that job (install, the node:test suite's own 720 s budget,
// typecheck, install smoke), so its ceiling is not a free parameter. The job is
// bounded at 1800 s, tests/product/test_ci_gate_wiring.py requires a 300 s
// reserve for the steps that are not suites, and test:ci already claims 720 s of
// it, so 1800 - 720 - 300 = 780 s is the most this suite could ever be allowed.
// The default is 720 s (the same as test:ci's, and ~1.8x the measured pass),
// which leaves 60 s of slack, and the CEILING is the same number so that no
// environment override can push the job past the bound the wiring test checks.
// A budget override above the ceiling is REJECTED rather than clamped -- clamping
// is how a documented bound stops being one.
const DEFAULTS = { perCheckTimeoutMs: 240_000, suiteBudgetMs: 720_000 };
// The budget's floor is 1 ms ON PURPOSE: it is a probe value, not a CI setting.
// The wiring test runs this entry point with `PTY_SUITE_BUDGET_MS=1` to prove the
// budget is enforced (nothing runs, every check is reported as never-run, the
// exit is non-zero). Clamping the floor up to a "sensible" minute would make
// that proof impossible.
const BOUNDS = {
  perCheckTimeoutMs: { min: 5_000, max: 300_000 },
  suiteBudgetMs: { min: 1, max: 720_000 },
};

// The checks that GATE: each exits non-zero when the behaviour it asserts is not
// observed, so a CI step running it can go red. This is the set the cli-ts job
// runs (`check:frames:ci`).
const GATES = [
  // The shipped entry in a real pty, driven one byte at a time: home panel first
  // frame, typing echo, Enter submit + stream, Ctrl-C exit, narrow-terminal
  // relayout, mid-session resize, and the approval card's human approve path.
  "scripts/pty_smoke.py",
  // The REAL entry (src/cli.tsx) on both runtimes: the view-free paths on node
  // (no native FFI), actionable advice instead of a stack on the interactive
  // path, and the rendered home panel on bun.
  "scripts/pty_entry_check.py",
  // The welcome panel owns the FIRST frame, and is gone once a turn has painted.
  "scripts/pty_home_frame_check.py",
  // Ctrl-R reverse search overlay + composer growth for a multi-line draft.
  "scripts/pty_search_check.py",
  // Fenced code tokens carry their syntax colours: >= 3 distinct non-default
  // SGR foregrounds, read from the reconstructed frame.
  "scripts/pty_highlight_check.py",
  // `/theme` changes the RENDERED colours of the located header row.
  "scripts/pty_theme_check.py",
  // Vim normal-mode editing (0/x) and submit, asserted on the submitted message.
  "scripts/pty_fullscreen_vim.py",
  // A real cross-session switch from the agents panel (a listed session that is
  // not the client's own session).
  "scripts/pty_fullscreen_p3a_multisession.py",
  // The composer invariants: "/stat" opens the palette, Enter RUNS /status, the
  // process survives the submit, and the command runs exactly once.
  "scripts/pty_fullscreen_composer_invariant.py",
  // Backspace (0x7f), ctrl-d forward delete and a CR/CRLF paste read back
  // row-by-row from the reconstructed screen.
  "scripts/pty_fullscreen_editor_keys.py",
  // Slice B: @mention completion, input history and the markdown render path.
  "scripts/pty_fullscreen_parity_b.py",
  // The operator control surface, landed from the stop/resume/deny-visibility
  // branches (the workflow's frame-check step pre-listed these as GATES to add
  // in the same PR that lands the files). Each drives the shipped Bun TUI in a
  // real pty against a hermetic sys.executable daemon and exits non-zero on the
  // first unobserved assertion.
  // Ctrl-X mid-turn durably PAUSES the held turn: no dispatch, no second
  // provider call, composer untouched, session left PAUSED.
  "scripts/pty_stop_key_check.py",
  // `/resume <id>` after Ctrl-X reactivates the session (RUN_RESUMED) and a new
  // turn runs; nothing held-open is dispatched while stopped.
  "scripts/pty_resume_check.py",
  // A rule DENY renders as its own failed card distinct from an ordinary tool
  // failure and the model's false "done" claim; durable DENY, no receipt, file
  // untouched.
  "scripts/pty_deny_frame_check.py",
  // Killing the runtime mid-session is reported on the transcript, never fatal:
  // no unhandled-rejection stack smeared over the frame, the surface keeps
  // answering (a second failed command is reported the same way).
  "scripts/pty_runtime_lost_check.py",
];

// Checks that print frames and booleans with NO failing exit path. They run in
// the local `check:frames` set (`--all`) and deliberately not in CI: a step that
// cannot fail is not a gate, and the honest move is to say so rather than to let
// a green step imply that these claims are enforced.
const EVIDENCE_ONLY = new Map([
  [
    "scripts/pty_fullscreen_p2.py",
    "evidence capture: prints the boot/Tab-cycle/flag frames plus TYPABLE_AFTER_TAB; " +
      "has no verdict and no non-zero exit path",
  ],
  [
    "scripts/pty_fullscreen_p3a.py",
    "evidence capture: prints the agents/task-tree frames and the --no-agents frame; " +
      "has no aggregate verdict and no non-zero exit path",
  ],
  [
    "scripts/pty_fullscreen_parity_a.py",
    "evidence capture: prints the palette/selector frames and a SUMMARY dict; " +
      "has no verdict and no non-zero exit path",
  ],
  [
    "scripts/pty_fullscreen_parity_c.py",
    "evidence capture: the key-delivery matrix needs the env-gated NOEM_KEY_DEBUG " +
      "instrumentation and is skipped without it; the editor round trip prints a " +
      "boolean but the script has no non-zero exit path",
  ],
]);

// Commands that cannot fail and cannot run anything: a `check:frames:ci` built
// out of these would report a green cli-ts job that ran no check at all, which is
// the hole tests/product/test_ci_gate_wiring.py exists to keep closed. The value
// is enforced there, not here.

function readBoundedMs(name, fallback, bounds) {
  const raw = process.env[name];
  if (raw === undefined || raw.trim() === "") return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < bounds.min || value > bounds.max) {
    console.error(
      `${name}=${JSON.stringify(raw)} is outside the enforced range ` +
        `${bounds.min}..${bounds.max} ms. An unbounded deadline is how a hang turns ` +
        `into an anonymously cancelled job, so this value is rejected rather than ` +
        `clamped to the nearest bound.`,
    );
    process.exit(1);
  }
  return value;
}

/** Every `pty_*.py` under scripts/, at any depth, as `scripts/<rel>`. */
function checksOnDisk(dir = SCRIPTS_DIR, prefix = "scripts") {
  const found = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const relativePath = `${prefix}/${entry.name}`;
    if (entry.isDirectory()) found.push(...checksOnDisk(join(dir, entry.name), relativePath));
    else if (/^pty_.*\.py$/.test(entry.name)) found.push(relativePath);
  }
  return found.sort();
}

/** The first interpreter of `names` that exists on PATH, or null. */
function onPath(names) {
  const dirs = (process.env.PATH ?? "").split(delimiter).filter((dir) => dir !== "");
  for (const name of names) {
    for (const dir of dirs) {
      const candidate = join(dir, name);
      try {
        accessSync(candidate, constants.X_OK);
        return { name, path: candidate };
      } catch {
        // Not here; keep looking.
      }
    }
  }
  return null;
}

/** `python3`/`python` first: the CI job installs the pinned deps into python3. */
function resolveInterpreter() {
  const python = onPath(["python3", "python"]);
  if (python) return { label: python.name, argv: [python.path, "-u"] };
  const uv = onPath(["uv"]);
  if (uv) return { label: "uv run python", argv: [uv.path, "run", "python", "-u"] };
  return null;
}

const onDisk = checksOnDisk();
const declared = [...GATES, ...EVIDENCE_ONLY.keys()];

// Both directions, because each one is a different way for the coverage to rot:
// a check on disk that nobody classified is a check CI will never run, and a
// classified name with no file on disk is a check CI will report as missing.
const unclassified = onDisk.filter((file) => !declared.includes(file));
const missingOnDisk = declared.filter((file) => !onDisk.includes(file));
if (unclassified.length > 0 || missingOnDisk.length > 0) {
  console.error(
    `apps/cli-ts/scripts/pty-ci.mjs and the checks on disk disagree ` +
      `(onDisk=${onDisk.length}, declared=${declared.length}). Classify every ` +
      `scripts/pty_*.py in this file -- as a GATE if it exits non-zero on a failed ` +
      `assertion, or in EVIDENCE_ONLY with the reason it cannot:`,
  );
  for (const file of unclassified) {
    console.error(`  on disk but NOT classified (CI would never run it): ${file}`);
  }
  for (const file of missingOnDisk) {
    console.error(`  classified but missing on disk: ${file}`);
  }
  process.exit(1);
}

const mode = process.argv.includes("--all") ? "all" : "ci";
const files = mode === "all" ? onDisk : onDisk.filter((file) => GATES.includes(file));
const perCheckMs = readBoundedMs(
  "PTY_CHECK_TIMEOUT_MS",
  DEFAULTS.perCheckTimeoutMs,
  BOUNDS.perCheckTimeoutMs,
);
const suiteBudgetMs = readBoundedMs(
  "PTY_SUITE_BUDGET_MS",
  DEFAULTS.suiteBudgetMs,
  BOUNDS.suiteBudgetMs,
);
const worstCaseSuiteMs = Math.min(files.length * perCheckMs, suiteBudgetMs);

const plan = {
  packageRoot: PACKAGE_ROOT,
  mode,
  allChecks: onDisk,
  ciChecks: GATES,
  evidenceOnly: [...EVIDENCE_ONLY].map(([file, why]) => ({ file, why })),
  files,
  fileCount: files.length,
  perCheckTimeoutMs: perCheckMs,
  suiteBudgetMs,
  worstCaseSuiteMs,
};

if (process.argv.includes("--list")) {
  const interpreter = resolveInterpreter();
  console.log(JSON.stringify({ ...plan, interpreter: interpreter?.label ?? null }, null, 2));
  process.exit(0);
}

const interpreter = resolveInterpreter();
if (interpreter === null) {
  console.error(
    "no python3, python or uv on PATH: the frame checks drive the shipped entry " +
      "and start the hermetic daemon with the interpreter running the check, so " +
      "there is nothing to run them with.",
  );
  process.exit(1);
}

console.log(
  `=== ${files.length} frame checks (${mode === "all" ? "the whole on-disk set" : "CI gates"}), ` +
    `interpreter ${interpreter.label}, ${perCheckMs} ms deadline each, ` +
    `${suiteBudgetMs} ms for the suite (worst case ${worstCaseSuiteMs} ms)`,
);
if (files.length * perCheckMs > suiteBudgetMs) {
  console.log(
    `=== note: ${files.length} checks x ${perCheckMs} ms would be ${files.length * perCheckMs} ms, ` +
      `so the suite budget is what bounds this step: a run that spends ${suiteBudgetMs} ms is ` +
      `stopped there and its remaining checks are reported as never-run failures.`,
  );
}

// A temp dir of this run's own, so no check can write into the operator's
// `~/.agent-os/` store: the client persists history/theme/vim state under it and
// the daemon reads its provider config from there. Clearing the paths makes CI
// and a developer's machine behave the same way -- a clean machine.
const sandbox = mkdtempSync(join(tmpdir(), "cli-ts-frames-"));
const childEnv = {
  ...process.env,
  AGENT_OS_CLI_STATE: join(sandbox, "cli-ts-state.json"),
  AGENT_OS_PROVIDER_CONFIG: join(sandbox, "provider.json"),
  AGENT_OS_PRICING_FILE: join(sandbox, "pricing.json"),
  // Every check emulates a terminal by hand (it opens a pty and sets the window
  // size with TIOCSWINSZ). Some checks hard-pin TERM=xterm-256color for the TUI
  // they start; others (pty_smoke.py and the operator-surface checks) take the
  // inherited value through `os.environ.get("TERM", "xterm-256color")`. Pinning
  // it here covers the latter too, so whether a colour assertion can hold does
  // not depend on the caller's shell -- a runner with TERM=dumb or unset is not a
  // different renderer, it is the same renderer asked to advertise less.
  TERM: "xterm-256color",
};
delete childEnv.AGENT_OS_RUNTIME_DESCRIPTOR;
delete childEnv.AGENT_OS_RUNTIME_DATABASE;

function run(file, timeoutMs) {
  return new Promise((resolve) => {
    const child = spawn(interpreter.argv[0], [...interpreter.argv.slice(1), file], {
      cwd: PACKAGE_ROOT,
      stdio: "inherit",
      env: childEnv,
      // Its own process group, so a check that hangs can be killed WITH its
      // children: each one starts a hermetic daemon and a bun TUI, and killing
      // only the wrapper would leave both behind for the rest of the job.
      detached: true,
    });
    const timer = setTimeout(() => {
      try {
        process.kill(-child.pid, "SIGKILL");
      } catch {
        child.kill("SIGKILL");
      }
      resolve({ file, code: 124, timedOut: true, timeoutMs });
    }, timeoutMs);
    child.on("exit", (code, signal) => {
      clearTimeout(timer);
      // BUG 2026-09-19: the check script exits but the hermetic daemon it
      // started (`uv run agent-os-runtime` + its python child) keeps running in
      // the same process group. Killing only the wrapper left ~40 orphaned
      // daemons (some alive >1 day). Reap the WHOLE group now that the wrapper
      // is gone: negative pid signals the process group created by detached:true.
      try {
        process.kill(-child.pid, "SIGKILL");
      } catch {
        // Group already reaped by the timeout path above, or no members left.
      }
      resolve({ file, code: code ?? 1, timedOut: false, signal: signal ?? null });
    });
  });
}

const startedAt = Date.now();
const deadline = startedAt + suiteBudgetMs;
const failures = [];
try {
  for (const file of files) {
    console.log(`\n=== ${file}`);
    const remaining = deadline - Date.now();
    if (remaining <= 0) {
      console.error(
        `=== ${file}: NOT RUN - the ${suiteBudgetMs} ms suite budget was already spent. This ` +
          `check is reported as a failure rather than skipped: a suite that runs out of budget ` +
          `part way through must not report success.`,
      );
      failures.push(`${file} (budget exhausted, never ran)`);
      continue;
    }
    // A timeout under load is a scheduling/slow-boot flake, not an assertion
    // failure: retry it ONCE before counting it. An exit-nonzero (assertion
    // failure) is never retried, so weakening a gate is out of scope.
    let result = await run(file, Math.min(perCheckMs, remaining));
    if (result.timedOut) {
      console.error(`=== ${file}: TIMED OUT after ${result.timeoutMs} ms (retrying once)`);
      result = await run(file, Math.min(perCheckMs, deadline - Date.now()));
    }
    if (result.timedOut) {
      console.error(`=== ${file}: TIMED OUT after retry (${result.timeoutMs} ms)`);
      failures.push(`${file} (timeout after ${result.timeoutMs} ms)`);
    } else if (result.code !== 0) {
      failures.push(
        `${file} (exit ${result.code}${result.signal ? ` signalled ${result.signal}` : ""})`,
      );
    }
  }
} finally {
  rmSync(sandbox, { recursive: true, force: true });
}

console.log(
  `\n=== ran ${files.length} frame checks in ${Math.round((Date.now() - startedAt) / 1000)} s ` +
    `(budget ${suiteBudgetMs} ms, per check ${perCheckMs} ms)`,
);
if (failures.length > 0) {
  console.error(`=== ${failures.length} failing check(s):`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log("=== all frame checks passed");
