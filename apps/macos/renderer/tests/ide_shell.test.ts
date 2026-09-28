import { describe, expect, it } from "vitest";

import {
  createIdeShellState,
  destinationLabel,
  openWorkspace,
  switchSurface,
} from "../src/ide_shell";

describe("IDE shell navigation", () => {
  it("uses one destination action instead of an Agent/IDE segmented switch", () => {
    const initial = createIdeShellState();

    expect(destinationLabel(initial.surface)).toBe("IDE ↗");

    const inIde = switchSurface(initial);
    expect(inIde.surface).toBe("ide");
    expect(destinationLabel(inIde.surface)).toBe("Agent ↗");

    const backInAgent = switchSurface(inIde);
    expect(backInAgent.surface).toBe("agent");
    expect(backInAgent.workspace).toBeNull();
  });

  it("allows entering IDE before selecting a coding workspace", () => {
    const inIde = switchSurface(createIdeShellState());

    expect(inIde.surface).toBe("ide");
    expect(inIde.workspace).toBeNull();
    expect(inIde.ideView).toBe("landing");

    const opened = openWorkspace(inIde, "/repo/agent-os");
    expect(opened.workspace).toBe("/repo/agent-os");
    expect(opened.ideView).toBe("editor");
  });
});
