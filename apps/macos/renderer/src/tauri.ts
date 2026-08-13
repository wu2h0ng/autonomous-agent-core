// Narrow Tauri IPC wrapper for the renderer.
//
// Only allowlisted commands exist on the Rust side; this module exposes the
// subset the renderer needs and degrades gracefully outside a Tauri runtime
// (tests / plain browser preview) so panels remain testable.

export interface RuntimeConnection {
  base_url: string;
  bearer_token: string;
}

interface TauriWindow {
  __TAURI__?: {
    core?: {
      invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown>;
    };
  };
}

function tauriInvoke(): ((command: string) => Promise<unknown>) | null {
  const win = window as TauriWindow;
  return win.__TAURI__?.core?.invoke ?? null;
}

export async function runtimeConnection(): Promise<RuntimeConnection> {
  const invoke = tauriInvoke();
  if (invoke === null) {
    // Outside the Tauri runtime: no connection is available. Panels surface
    // this as an explicit error instead of fabricating a connection.
    throw new Error("runtime connection unavailable (not running inside the Agent OS shell)");
  }
  const value = await invoke("runtime:connection");
  if (typeof value !== "string") {
    throw new Error("runtime connection returned an invalid payload");
  }
  const parsed = JSON.parse(value) as {
    base_url?: unknown;
    bearer_token?: unknown;
  };
  if (
    typeof parsed.base_url !== "string" ||
    typeof parsed.bearer_token !== "string"
  ) {
    throw new Error("runtime connection payload is incomplete");
  }
  return {
    base_url: parsed.base_url,
    bearer_token: parsed.bearer_token,
  };
}
