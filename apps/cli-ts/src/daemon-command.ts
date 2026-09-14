/**
 * `agent-os-ts daemon start|stop|status` — manage the local governance daemon.
 */
import {
  daemonHealthy,
  defaultDaemonPaths,
  ensureDaemon,
  stopDaemon,
  type DaemonDeps,
} from "./daemon.js";
import { loadRuntimeDescriptor } from "./descriptor.js";

export interface DaemonCommandOptions {
  descriptorPath?: string | undefined;
  workspace?: string | undefined;
  args: string[];
}

export async function runDaemonCommand(
  options: DaemonCommandOptions,
  deps?: Partial<DaemonDeps>,
): Promise<number> {
  const sub = (options.args[0] ?? "status").toLowerCase();
  const paths = defaultDaemonPaths(options.workspace);
  const descriptorPath = options.descriptorPath ?? paths.descriptorPath;
  try {
    if (sub === "start") {
      const { descriptor, started } = await ensureDaemon(
        {
          descriptorPath,
          workspace: paths.workspace,
          database: paths.database,
          autoStart: true,
          timeoutSeconds: 30,
        },
        deps,
      );
      process.stdout.write(
        `daemon ${started ? "started" : "already running"} at ${descriptor.baseUrl} (pid ${descriptor.pid})\n`,
      );
      return 0;
    }
    if (sub === "stop") {
      const stopped = await stopDaemon(descriptorPath);
      process.stdout.write(`daemon ${stopped ? "stopped" : "not running"}\n`);
      return 0;
    }
    if (sub === "status") {
      const descriptor = await loadRuntimeDescriptor(descriptorPath);
      const healthy = await daemonHealthy(descriptor);
      process.stdout.write(
        healthy
          ? `daemon running at ${descriptor.baseUrl} (pid ${descriptor.pid})\n`
          : "daemon descriptor present but the runtime is not healthy\n",
      );
      return healthy ? 0 : 1;
    }
    process.stderr.write(
      `agent-os-ts: unknown daemon subcommand ${sub} (start | stop | status)\n`,
    );
    return 1;
  } catch (cause) {
    process.stderr.write(`agent-os-ts daemon: ${(cause as Error).message}\n`);
    return 1;
  }
}
