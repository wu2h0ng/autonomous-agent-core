/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { lstat, readFile } from 'node:fs/promises';
import { decodeTaskCatalog } from '../common/runtimeTaskCatalog.js';
import type { AgentOSTaskCatalogSnapshot } from '../common/runtimeTaskCatalog.js';

/**
 * Runtime task catalog bridge, Electron main side.
 *
 * The private runtime descriptor (0600, owner-only) is the only route to the
 * daemon bearer token. This service is the sole process that may read it;
 * renderers receive the decoded projection and never descriptor bytes.
 */
export interface RuntimeDescriptor {
	readonly protocol_version: string;
	readonly pid: number;
	readonly boot_id: string;
	readonly host: string;
	readonly port: number;
	readonly bearer_token: string;
	readonly database_path: string;
	readonly workspace_path: string;
	readonly created_at: string;
}

export type RuntimeTaskCatalogErrorCode =
	| 'RUNTIME_DESCRIPTOR_UNSAFE'
	| 'RUNTIME_DESCRIPTOR_INVALID'
	| 'RUNTIME_DESCRIPTOR_STALE'
	| 'RUNTIME_DESCRIPTOR_CHANGED'
	| 'RUNTIME_READ_ONLY'
	| 'RUNTIME_NOT_LOOPBACK'
	| 'RUNTIME_PATH_NOT_ALLOWED'
	| 'RUNTIME_RESPONSE_TOO_LARGE'
	| 'RUNTIME_UNREACHABLE';

export class RuntimeTaskCatalogError extends Error {
	readonly code: RuntimeTaskCatalogErrorCode;

	constructor(code: RuntimeTaskCatalogErrorCode, message: string) {
		super(message);
		this.name = 'RuntimeTaskCatalogError';
		this.code = code;
	}
}

const REQUEST_TIMEOUT_MS = 5_000;
const RESPONSE_CAP_BYTES = 1_048_576; // 1 MiB
const ALLOWED_GET_PATHS: readonly string[] = ['/v1/tasks'];

function isProcessAlive(pid: number): boolean {
	try {
		process.kill(pid, 0);
		return true;
	} catch {
		return false;
	}
}

export class RuntimeTaskCatalogMainService {
	private readonly descriptorPath: string;
	private readonly now: () => number;

	constructor(descriptorPath: string, now: () => number = () => Date.now()) {
		this.descriptorPath = descriptorPath;
		this.now = now;
	}

	async listTasks(): Promise<AgentOSTaskCatalogSnapshot> {
		const payload = await this.request('GET', '/v1/tasks');
		return decodeTaskCatalog(payload, this.now());
	}

	/** Read-only request guard: the bridge serves data, never commands. */
	async request(method: string, path: string): Promise<unknown> {
		if (method !== 'GET') {
			throw new RuntimeTaskCatalogError('RUNTIME_READ_ONLY', `bridge is read-only; refused ${method} ${path}`);
		}
		if (!ALLOWED_GET_PATHS.includes(path)) {
			throw new RuntimeTaskCatalogError('RUNTIME_PATH_NOT_ALLOWED', `path not allowed on the task catalog bridge: ${path}`);
		}
		const descriptor = await this.loadDescriptor();
		const url = `http://${descriptor.host}:${descriptor.port}${path}`;
		const body = await this.fetchJson(url, descriptor.bearer_token);
		// The daemon may have restarted mid-request; the response is only
		// trustworthy if the descriptor still names the same process/boot.
		const after = await this.loadDescriptor();
		if (after.pid !== descriptor.pid || after.boot_id !== descriptor.boot_id
			|| after.port !== descriptor.port || after.bearer_token !== descriptor.bearer_token) {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_CHANGED', 'runtime descriptor changed during the request');
		}
		return body;
	}

	/** Absolute-URL escape hatch for diagnostics; still loopback-pinned. */
	async fetchFrom(url: string): Promise<unknown> {
		const descriptor = await this.loadDescriptor();
		const origin = `http://${descriptor.host}:${descriptor.port}`;
		if (!url.startsWith(origin + '/')) {
			throw new RuntimeTaskCatalogError('RUNTIME_NOT_LOOPBACK', `refused non-loopback URL: ${url}`);
		}
		return this.fetchJson(url, descriptor.bearer_token);
	}

	private async fetchJson(url: string, bearerToken: string): Promise<unknown> {
		let response;
		try {
			response = await fetch(url, {
				method: 'GET',
				headers: { 'Authorization': `Bearer ${bearerToken}`, 'Accept': 'application/json' },
				signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
			});
		} catch (error) {
			throw new RuntimeTaskCatalogError('RUNTIME_UNREACHABLE', `runtime request failed: ${(error as Error).message}`);
		}
		if (response.status === 401) {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_STALE', 'runtime rejected the descriptor bearer token');
		}
		if (!response.ok) {
			throw new RuntimeTaskCatalogError('RUNTIME_UNREACHABLE', `runtime answered HTTP ${response.status}`);
		}
		const text = await response.text();
		if (Buffer.byteLength(text, 'utf8') > RESPONSE_CAP_BYTES) {
			throw new RuntimeTaskCatalogError('RUNTIME_RESPONSE_TOO_LARGE', 'runtime response exceeds the 1 MiB cap');
		}
		return JSON.parse(text);
	}

	private async loadDescriptor(): Promise<RuntimeDescriptor> {
		let info;
		try {
			info = await lstat(this.descriptorPath);
		} catch {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_UNSAFE', 'runtime descriptor is missing');
		}
		if (info.isSymbolicLink() || !info.isFile()) {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_UNSAFE', 'runtime descriptor must be a regular non-symlink file');
		}
		if (process.platform !== 'win32') {
			if ((info.mode & 0o077) !== 0) {
				throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_UNSAFE', 'runtime descriptor must not be group/world readable');
			}
			const uid = process.getuid?.();
			if (uid !== undefined && info.uid !== uid) {
				throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_UNSAFE', 'runtime descriptor must be owned by the current user');
			}
		}
		let value: Record<string, unknown>;
		try {
			value = JSON.parse(await readFile(this.descriptorPath, 'utf8'));
		} catch {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_INVALID', 'runtime descriptor is not valid JSON');
		}
		if (typeof value !== 'object' || value === null || Array.isArray(value)) {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_INVALID', 'runtime descriptor must be a JSON object');
		}
		const descriptor = value as unknown as RuntimeDescriptor;
		if (descriptor.protocol_version !== '1.0') {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_INVALID', `unsupported descriptor protocol version: ${descriptor.protocol_version}`);
		}
		if (descriptor.host !== '127.0.0.1') {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_UNSAFE', `runtime descriptor host must be loopback, got ${descriptor.host}`);
		}
		if (!Number.isInteger(descriptor.port) || descriptor.port < 1 || descriptor.port > 65535) {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_INVALID', 'runtime descriptor port is out of range');
		}
		if (!Number.isInteger(descriptor.pid) || descriptor.pid <= 0 || !isProcessAlive(descriptor.pid)) {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_STALE', 'runtime descriptor names a dead process');
		}
		if (typeof descriptor.bearer_token !== 'string' || descriptor.bearer_token.length === 0) {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_INVALID', 'runtime descriptor bearer token is missing');
		}
		if (typeof descriptor.boot_id !== 'string' || descriptor.boot_id.length === 0) {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_INVALID', 'runtime descriptor boot_id is missing');
		}
		return descriptor;
	}
}
