import { RuntimeClient, RuntimeConnectionError } from './runtimeClient.js';

/** Runtime bridge. Native window creation and layout live in Code-OSS. */
export class AgentSurface {
  private client: RuntimeClient | undefined;

  constructor(private readonly connect: () => Promise<RuntimeClient>) {}

  async retry(): Promise<boolean> {
    try {
      this.client = await this.connect();
      await this.client.health();
      return true;
    } catch {
      this.client = undefined;
      return false;
    }
  }
}

export function safeMessage(error: unknown): string {
  return error instanceof RuntimeConnectionError ? error.message : 'Agent OS Runtime 操作失败';
}
