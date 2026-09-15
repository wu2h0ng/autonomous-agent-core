/**
 * Headless provider administration (`noem provider ...`).
 *
 * Mirrors the TUI `/provider`: status / set / clear. The API key is read from
 * AGENT_OS_PROVIDER_KEY (never typed, never written to local state); the daemon
 * persists only the non-secret config and stores the key in the OS keychain.
 */
import { SurfaceClient } from "./client.js";
import { loadRuntimeDescriptor } from "./descriptor.js";

export interface ProviderCommandOptions {
  descriptorPath?: string | undefined;
  args: string[];
}

const SUBCOMMANDS = new Set(["status", "set", "clear"]);

function flagValue(args: string[], ...names: string[]): string | undefined {
  for (const name of names) {
    const index = args.indexOf(name);
    if (index >= 0) return args[index + 1];
  }
  return undefined;
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
  let apiKey: string | undefined;
  if (sub === "set") {
    baseUrl = flagValue(options.args, "--base-url", "--base");
    model = flagValue(options.args, "--model");
    endpointClass = flagValue(options.args, "--endpoint-class");
    if (!baseUrl || !model) {
      process.stderr.write(
        "usage: noem provider set --base-url <url> --model <id> [--endpoint-class <class>]\n",
      );
      return 1;
    }
    apiKey = process.env.AGENT_OS_PROVIDER_KEY;
    if (!apiKey) {
      process.stderr.write(
        "AGENT_OS_PROVIDER_KEY is not set; export it, then retry (the key is never stored in local state).\n",
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
    const status = await client.configureProvider({
      baseUrl: baseUrl as string,
      model: model as string,
      apiKey: apiKey as string,
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
