import * as vscode from 'vscode';
import { AgentSurface } from './agentSurface.js';
import { loadDescriptor, RuntimeClient } from './runtimeClient.js';

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const surface = new AgentSurface(async () => {
    const configured = vscode.workspace.getConfiguration('agentOS').get<string>('runtimeDescriptor', '~/.agent-os/runtime.json');
    return new RuntimeClient(await loadDescriptor(configured));
  });
  context.subscriptions.push(
    vscode.commands.registerCommand('agentOS.retryRuntime', () => surface.retry())
  );
}

export function deactivate(): void {}
