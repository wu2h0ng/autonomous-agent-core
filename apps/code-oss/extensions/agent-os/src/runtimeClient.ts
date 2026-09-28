import { lstat, readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';
import { RuntimeDescriptor, SessionSnapshot, SURFACE_PROTOCOL_VERSION, TurnResponse } from './contracts.js';

export class RuntimeConnectionError extends Error {}

export function expandHome(value: string): string {
  return value === '~' ? homedir() : value.startsWith('~/') ? path.join(homedir(), value.slice(2)) : value;
}

export function parseDescriptor(raw: string): RuntimeDescriptor {
  let value: unknown;
  try { value = JSON.parse(raw); } catch { throw new RuntimeConnectionError('Runtime descriptor is not valid JSON'); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new RuntimeConnectionError('Runtime descriptor must be an object');
  const descriptor = value as Record<string, unknown>;
  if (descriptor.protocol_version !== SURFACE_PROTOCOL_VERSION) throw new RuntimeConnectionError('Runtime protocol is not supported');
  if (descriptor.host !== '127.0.0.1' && descriptor.host !== '::1') throw new RuntimeConnectionError('Runtime must use a loopback address');
  if (!Number.isInteger(descriptor.port) || Number(descriptor.port) < 1 || Number(descriptor.port) > 65535) throw new RuntimeConnectionError('Runtime port is invalid');
  if (typeof descriptor.bearer_token !== 'string' || descriptor.bearer_token.length < 1) throw new RuntimeConnectionError('Runtime credential is unavailable');
  if (typeof descriptor.workspace_path !== 'string' || descriptor.workspace_path.length < 1) throw new RuntimeConnectionError('Runtime workspace is unavailable');
  return descriptor as unknown as RuntimeDescriptor;
}

export async function loadDescriptor(descriptorPath: string): Promise<RuntimeDescriptor> {
  const resolved = expandHome(descriptorPath);
  const metadata = await lstat(resolved);
  if (!metadata.isFile() || metadata.isSymbolicLink()) throw new RuntimeConnectionError('Runtime descriptor must be a regular file');
  if ((metadata.mode & 0o077) !== 0) throw new RuntimeConnectionError('Runtime descriptor permissions must be 0600');
  return parseDescriptor(await readFile(resolved, 'utf8'));
}

export class RuntimeClient {
  constructor(private readonly descriptor: RuntimeDescriptor, private readonly fetcher: typeof fetch = fetch) {}

  private async request<T>(route: string, method: 'GET' | 'POST', body?: object): Promise<T> {
    let response: Response;
    try {
      response = await this.fetcher(`http://${this.descriptor.host}:${this.descriptor.port}${route}`, {
        method,
        headers: {
          Authorization: `Bearer ${this.descriptor.bearer_token}`,
          'Content-Type': 'application/json',
          'X-Agent-OS-Protocol': SURFACE_PROTOCOL_VERSION
        },
        body: body ? JSON.stringify(body) : undefined
      });
    } catch { throw new RuntimeConnectionError('Cannot reach the local Agent OS Runtime'); }
    if (!response.ok) {
      if (response.status === 401) throw new RuntimeConnectionError('Runtime credential is stale; restart the Runtime');
      throw new RuntimeConnectionError(`Runtime request failed with HTTP ${response.status}`);
    }
    const value = await response.json() as T & { protocol_version?: string };
    if (value.protocol_version && value.protocol_version !== SURFACE_PROTOCOL_VERSION) throw new RuntimeConnectionError('Runtime protocol changed during the request');
    return value;
  }

  async health(): Promise<void> { await this.request('/v1/health', 'GET'); }

  async openSession(statement: string): Promise<SessionSnapshot> {
    const value = await this.request<{ snapshot: SessionSnapshot }>('/v1/surface/sessions', 'POST', {
      protocol_version: SURFACE_PROTOCOL_VERSION,
      client: {
        client_id: 'code-oss', client_type: 'DESKTOP', principal_id: 'user:local',
        tenant_id: 'tenant:local', workspace_id: 'workspace:local', device_id: 'device:code-oss'
      },
      statement,
      idempotency_key: `code-oss-open-${crypto.randomUUID()}`,
      requested_at: new Date().toISOString()
    });
    return value.snapshot;
  }

  async runTurn(snapshot: SessionSnapshot, message: string): Promise<TurnResponse> {
    const value = await this.request<{ turn: TurnResponse }>(`/v1/surface/sessions/${encodeURIComponent(snapshot.session.session_id)}/turns`, 'POST', {
      protocol_version: SURFACE_PROTOCOL_VERSION,
      client: {
        client_id: 'code-oss', client_type: 'DESKTOP', principal_id: 'user:local',
        tenant_id: 'tenant:local', workspace_id: 'workspace:local', device_id: 'device:code-oss'
      },
      message,
      expected_event_sequence: snapshot.event_sequence,
      idempotency_key: `code-oss-turn-${crypto.randomUUID()}`,
      requested_at: new Date().toISOString()
    });
    return value.turn;
  }
}

