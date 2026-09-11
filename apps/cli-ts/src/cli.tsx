#!/usr/bin/env node
/** agent-os-ts entry: Ink TUI over the local runtime daemon. */
import React from "react";
import { render } from "ink";
import { SurfaceClient } from "./client.js";
import { loadRuntimeDescriptor } from "./descriptor.js";
import { TuiController } from "./controller.js";
import { App } from "./App.js";

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const descriptorFlag = args.indexOf("--descriptor");
  const resumeFlag = args.indexOf("--resume");
  const descriptorPath = descriptorFlag >= 0 ? args[descriptorFlag + 1] : undefined;
  const resumeSessionId = resumeFlag >= 0 ? args[resumeFlag + 1] : undefined;

  const descriptor = await loadRuntimeDescriptor(descriptorPath);
  const client = new SurfaceClient(descriptor);
  const controller = new TuiController(client);
  if (resumeSessionId) {
    await controller.submit(`/resume ${resumeSessionId}`);
  }
  render(React.createElement(App, { controller }));
}

main().catch((cause: unknown) => {
  console.error(`agent-os-ts: ${(cause as Error).message}`);
  process.exitCode = 1;
});
