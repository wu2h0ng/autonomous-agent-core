/**
 * Shell entry point for the upgrade path: `noem self-update ...`.
 *
 * Deliberately NOT a TUI slash command and NOT a session/surface operation: it
 * replaces a program file on the machine, so it is reachable only from a shell,
 * takes no input from a turn and calls no governance route. It also never
 * auto-starts or contacts the runtime daemon — `cli.tsx` dispatches it before
 * daemon resolution, so a self-update cannot depend on, or wake, a kernel.
 *
 *   noem self-update --status
 *   noem self-update --source <url> --check
 *   noem self-update --source <url> [--target <path>]
 *
 * Exit codes (this command's own table; the daemon-facing tables are unchanged):
 *   0  updated | update_available | up_to_date | interrupted_resolved
 *   1  refused or failed (the typed status names which)
 *   2  usage: no source named, source not http(s)/file, no resolvable install path
 */
import {
  renderSelfUpdateStatusText,
  renderSelfUpdateText,
  runSelfUpdate,
  runSelfUpdateStatus,
  SELF_UPDATE_SOURCE_ENV,
  traceEvent,
} from "./self-update.js";

export interface SelfUpdateCommandOptions {
  args: string[];
  env?: NodeJS.ProcessEnv;
}

const USAGE = [
  "usage:",
  "  noem self-update --status",
  "  noem self-update --source <url> --check",
  "  noem self-update --source <url> [--target <path>] [--json]",
  "",
  "  --source <url>   the source the OPERATOR names (file:// or http(s)://); a directory",
  `                   holding manifest.json + the artifact. Or set ${SELF_UPDATE_SOURCE_ENV}.`,
  "                   There is no default channel: publishing is a founder-reserved decision,",
  "                   so nothing is contacted unless a source is named here.",
  "  --target <path>  the program file to replace (default: this binary, when it is a",
  "                   compiled single-file binary; an interpreter cannot guess it).",
  "  --check          fetch the manifest and compare versions; download and install nothing.",
  "  --status         read-only: installed version, install path, pending update journal.",
  "  --json           machine-readable report on stdout.",
  "",
  "  Integrity is not optional: an artifact whose SHA-256 does not match the manifest is",
  "  refused, and the installed program is replaced only through an atomic rename whose",
  "  result must answer `--version` as published — otherwise the previous bytes are restored.",
  "  This command replaces a program file and nothing else: C7, permission modes, approval,",
  "  policy, evidence and ActionReceipt/ReceiptStatus are not read or changed by it.",
].join("\n");

function flagValue(args: string[], ...names: string[]): string | undefined {
  for (const name of names) {
    const index = args.indexOf(name);
    if (index >= 0) return args[index + 1];
  }
  return undefined;
}

export async function runSelfUpdateCommand(
  options: SelfUpdateCommandOptions,
): Promise<number> {
  const env = options.env ?? process.env;
  const args = options.args;
  const json = args.includes("--json");

  if (args.includes("--help") || args.includes("-h")) {
    process.stdout.write(`${USAGE}\n`);
    return 0;
  }

  const target = flagValue(args, "--target");
  const source = flagValue(args, "--source", "-s");
  const VALUE_FLAGS = new Set(["--source", "-s", "--target"]);
  const BOOL_FLAGS = new Set(["--check", "--status", "--json", "--help", "-h"]);
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index] as string;
    if (VALUE_FLAGS.has(arg)) {
      index += 1; // its value is not a flag
      continue;
    }
    if (BOOL_FLAGS.has(arg)) continue;
    process.stderr.write(
      `noem self-update: unexpected argument ${JSON.stringify(arg)}\n${USAGE}\n`,
    );
    return 2;
  }

  if (args.includes("--status")) {
    const status = runSelfUpdateStatus({
      ...(target === undefined ? {} : { target }),
      env,
    });
    process.stdout.write(json ? `${JSON.stringify(status, null, 2)}\n` : renderSelfUpdateStatusText(status));
    return 0;
  }

  const report = await runSelfUpdate({
    ...(source === undefined ? {} : { source }),
    ...(target === undefined ? {} : { target }),
    check: args.includes("--check"),
    env,
  });
  process.stdout.write(
    json ? `${JSON.stringify(report, null, 2)}\n` : renderSelfUpdateText(report),
  );
  // The trace line is emitted on stderr so `--json` stdout stays a single
  // document; it records the effect and grants nothing.
  process.stderr.write(`${JSON.stringify(traceEvent(report))}\n`);
  return report.exitCode;
}
