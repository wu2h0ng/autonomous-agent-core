export type ProductSurface = "agent" | "ide";
export type IdeView = "landing" | "editor";

export interface IdeShellState {
  surface: ProductSurface;
  workspace: string | null;
  ideView: IdeView;
}

export function createIdeShellState(): IdeShellState {
  return { surface: "agent", workspace: null, ideView: "landing" };
}

export function destinationLabel(surface: ProductSurface): "IDE ↗" | "Agent ↗" {
  return surface === "agent" ? "IDE ↗" : "Agent ↗";
}

export function switchSurface(state: IdeShellState): IdeShellState {
  if (state.surface === "agent") {
    return { ...state, surface: "ide", ideView: state.workspace === null ? "landing" : "editor" };
  }
  return { ...state, surface: "agent" };
}

export function openWorkspace(state: IdeShellState, workspace: string): IdeShellState {
  const normalized = workspace.trim();
  if (normalized === "") return state;
  return { ...state, surface: "ide", workspace: normalized, ideView: "editor" };
}

/** Window-level navigation for the two-window product shell. */
export async function focusSurfaceWindow(surface: ProductSurface): Promise<void> {
  const { WebviewWindow } = await import("@tauri-apps/api/webviewWindow");
  const current = WebviewWindow.getCurrent();
  const target = await WebviewWindow.getByLabel(surface);
  if (!target) throw new Error(`${surface} window is not available`);
  if (target.label === current.label) return;
  await target.show();
  await target.setFocus();
  await current.hide();
}

export async function currentSurface(): Promise<ProductSurface> {
  const { WebviewWindow } = await import("@tauri-apps/api/webviewWindow");
  return WebviewWindow.getCurrent().label === "ide" ? "ide" : "agent";
}
