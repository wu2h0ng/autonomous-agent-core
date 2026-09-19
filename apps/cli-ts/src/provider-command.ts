/**
 * Headless provider administration (`noem provider ...`).
 *
 * Mirrors the TUI `/provider`: status / set / clear. The API key is NEVER taken
 * from the argv (it would leak to shell history / process listings): it comes
 * from `AGENT_OS_PROVIDER_KEY`, from `--key-stdin` (piped), or from a hidden TTY
 * prompt. The daemon persists only the non-secret config and stores the key in
 * the OS keychain.
 */
import { SurfaceClient } from "./client.js";
import { loadRuntimeDescriptor } from "./descriptor.js";

export interface ProviderCommandOptions {
  descriptorPath?: string | undefined;
  args: string[];
  /** Test seam: supply the key without touching process.env / TTY / stdin. */
  keyProvider?: (() => Promise<string | null>) | undefined;
}

const SUBCOMMANDS = new Set(["status", "set", "clear"]);

function flagValue(args: string[], ...names: string[]): string | undefined {
  for (const name of names) {
    const index = args.indexOf(name);
    if (index >= 0) return args[index + 1];
  }
  return undefined;
}

/** Read the key from stdin until EOF (the `--key-stdin` path). */
async function readKeyFromStdin(): Promise<string> {
  const chunks: string[] = [];
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) chunks.push(chunk as string);
  // Strip a single trailing newline (pipes usually add one); keep the rest.
  return chunks.join("").replace(/[\r\n]+$/, "");
}

/** Hidden TTY prompt: read chars without echoing them (Ctrl-C cancels). */
async function promptHiddenKey(): Promise<string | null> {
  return new Promise((resolve) => {
    const stdin = process.stdin;
    if (typeof stdin.setRawMode !== "function") {
      resolve(null);
      return;
    }
    process.stderr.write("api key (hidden): ");
    stdin.setRawMode(true);
    stdin.resume();
    stdin.setEncoding("utf8");
    let key = "";
    const cleanup = (value: string | null): void => {
      stdin.setRawMode?.(false);
      stdin.pause();
      stdin.removeListener("data", onData);
      process.stderr.write("\n");
      resolve(value);
    };
    const onData = (chunk: string): void => {
      for (const ch of chunk) {
        if (ch === "\r" || ch === "\n" || ch === "\u0004") {
          cleanup(key);
          return;
        }
        if (ch === "\u0003") {
          cleanup(null); // Ctrl-C: cancelled, no key
          return;
        }
        if (ch === "\u007f" || ch === "\b") {
          key = key.slice(0, -1);
        } else {
          key += ch;
        }
      }
    };
    stdin.on("data", onData);
  });
}

/**
 * Resolve the API key for `provider set`. Order:
 *   1. injected key provider (tests)
 *   2. `--key-stdin` (piped, hermetic)
 *   3. `AGENT_OS_PROVIDER_KEY` in the environment
 *   4. a hidden TTY prompt when stdin is a terminal
 * Returns null when no non-leaking key source is available.
 */
async function resolveApiKey(
  args: string[],
  injected?: (() => Promise<string | null>) | undefined,
): Promise<string | null> {
  if (injected) return injected();
  if (args.includes("--key-stdin")) return await readKeyFromStdin();
  const envKey = process.env.AGENT_OS_PROVIDER_KEY;
  if (envKey) return envKey;
  if (process.stdin.isTTY === true) return await promptHiddenKey();
  return null;
}

export async function runProviderCommand(
  options: ProviderCommandOptions,
): Promise<number> {
  const sub = (options.args[0] ?? "status").toLowerCase();
  if (!SUBCOMMANDS.has(sub)) {
    process.stderr.write(
      `noem: unknown provider subcommand ${sub} (status | set | clear)\n`,
    );
    return 1;
  }

  let baseUrl: string | undefined;
  let model: string | undefined;
  let endpointClass: string | undefined;
  if (sub === "set") {
    baseUrl = flagValue(options.args, "--base-url", "--base");
    model = flagValue(options.args, "--model");
    endpointClass = flagValue(options.args, "--endpoint-class");
    // A key on the argv is the one leak we must refuse (history / ps / argv).
    if (
      options.args.includes("--api-key") ||
      options.args.some((arg) => arg.startsWith("--api-key="))
    ) {
      process.stderr.write(
        "noem: do not pass --api-key on the command line (it leaks to shell history " +
          "and process listings). Use --key-stdin, export AGENT_OS_PROVIDER_KEY, or run " +
          "`noem provider set` interactively on a TTY.\n",
      );
      return 1;
    }
    if (!baseUrl || !model) {
      process.stderr.write(
        "usage: noem provider set --base-url <url> --model <id> [--endpoint-class <class>] [--key-stdin]\n",
      );
      return 1;
    }
  }

  try {
    const descriptor = await loadRuntimeDescriptor(options.descriptorPath);
    const client = new SurfaceClient(descriptor);
    if (sub === "status") {
      const status = await client.providerStatus();
      process.stdout.write(`${JSON.stringify(status, null, 2)}\n`);
      return 0;
    }
    if (sub === "clear") {
      const status = await client.clearProvider();
      process.stdout.write(
        `provider cleared (persisted=${status.persisted}; the running daemon keeps its provider until restart)\n`,
      );
      return 0;
    }
    const apiKey = await resolveApiKey(options.args, options.keyProvider);
    if (!apiKey) {
      process.stderr.write(
        "no provider key available. Pipe it with --key-stdin, export AGENT_OS_PROVIDER_KEY, " +
          "or run interactively on a TTY (the key is never stored in local state).\n",
      );
      return 1;
    }
    const status = await client.configureProvider({
      baseUrl: baseUrl as string,
      model: model as string,
      apiKey,
      ...(endpointClass ? { endpointClass } : {}),
    });
    process.stdout.write(
      `provider configured: model ${status.model_id ?? "?"} · ` +
        `endpoint ${status.endpoint_class ?? "?"} · base_url ${status.base_url ?? "?"} · ` +
        `persisted=${status.persisted}\n`,
    );
    return 0;
  } catch (cause) {
    process.stderr.write(`noem provider: ${(cause as Error).message}\n`);
    return 1;
  }
}
