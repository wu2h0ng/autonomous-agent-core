/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { lstat, readFile } from 'node:fs/promises';
import { decodeTaskCatalog, decodeTaskDetail, decodeTaskTrajectory } from '../common/runtimeTaskCatalog.js';
import type { AgentOSTaskCatalogSnapshot, AgentOSTaskDetail, AgentOSTaskTrajectory } from '../common/runtimeTaskCatalog.js';

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

/**
 * Route templates the read-only bridge may call. Every dynamic segment is
 * validated by {@link assertSafeRouteSegment} before the path is built, and
 * validated segments can never contain `/`, so `[^/]+` here cannot match a
 * smuggled path separator even after percent-encoding.
 */
const ALLOWED_GET_PATH_PATTERNS: readonly RegExp[] = [
	/^\/v1\/tasks$/,
	/^\/v1\/tasks\/[^/]+$/,
	/^\/v1\/tasks\/[^/]+\/runs\/[^/]+\/trajectory$/,
];

function isAllowedGetPath(path: string): boolean {
	return ALLOWED_GET_PATH_PATTERNS.some(pattern => pattern.test(path));
}

const SAFE_ROUTE_SEGMENT = /^[A-Za-z0-9:._-]{1,256}$/;

/**
 * Fail-closed validation of a task/run id before it is placed in a URL path.
 * Anything that could alter the route shape (slashes, whitespace, dots alone,
 * control characters, overlong values, non-strings) is rejected.
 */
function assertSafeRouteSegment(value: unknown, label: string): string {
	if (typeof value !== 'string' || !SAFE_ROUTE_SEGMENT.test(value) || value === '.' || value === '..') {
		throw new RuntimeTaskCatalogError('RUNTIME_PATH_NOT_ALLOWED', `path not allowed: ${label} is not a safe route segment: ${JSON.stringify(value)}`);
	}
	return value;
}

function isProcessAlive(pid: number): boolean {
	try {
		process.kill(pid, 0);
		return true;
	} catch {
		return false;
	}
}

export interface RuntimeDescriptorStatLike {
	isSymbolicLink(): boolean;
	isFile(): boolean;
	readonly mode: number;
	readonly uid: number;
}

/** Ownership/permission checks shared by the async catalog path and the sync quit path. */
export function assertRuntimeDescriptorStatSafe(info: RuntimeDescriptorStatLike): void {
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
}

/** Pure validation of parsed descriptor JSON, shared by both read paths. */
export function parseRuntimeDescriptor(value: unknown): RuntimeDescriptor {
	if (typeof value !== 'object' || value === null || Array.isArray(value)) {
		throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_INVALID', 'runtime descriptor must be a JSON object');
	}
	const descriptor = value as RuntimeDescriptor;
	if (descriptor.protocol_version !== '1.0') {
		throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_INVALID', `unsupported descriptor protocol version: ${descriptor.protocol_version}`);
	}
	if (descriptor.host !== '127.0.0.1') {
		throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_UNSAFE', `runtime descriptor host must be loopback, got ${descriptor.host}`);
	}
	if (!Number.isInteger(descriptor.port) || descriptor.port < 1 || descriptor.port > 65535) {
		throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_INVALID', 'runtime descriptor port is out of range');
	}
	if (typeof descriptor.bearer_token !== 'string' || descriptor.bearer_token.length === 0) {
		throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_INVALID', 'runtime descriptor bearer token is missing');
	}
	if (typeof descriptor.boot_id !== 'string' || descriptor.boot_id.length === 0) {
		throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_INVALID', 'runtime descriptor boot_id is missing');
	}
	if (!Number.isInteger(descriptor.pid) || descriptor.pid <= 0) {
		throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_INVALID', 'runtime descriptor pid is invalid');
	}
	return descriptor;
}

export class RuntimeTaskCatalogMainService {
	private readonly descriptorPath: string;
	private readonly now: () => number;

	constructor(descriptorPath: string, now: () => number = () => Date.now()) {
		this.descriptorPath = descriptorPath;
		this.now = now;
	}

	private servedCatalog = false;

	/**
	 * Whether this app instance actually served any runtime read (catalog,
	 * task detail or trajectory) to a renderer. The application-quit
	 * lifecycle uses it to terminate only the runtime this session
	 * interacted with — never a daemon the app merely could see.
	 */
	get hasServedCatalog(): boolean {
		return this.servedCatalog;
	}

	async listTasks(): Promise<AgentOSTaskCatalogSnapshot> {
		const payload = await this.request('GET', '/v1/tasks');
		const snapshot = decodeTaskCatalog(payload, this.now());
		this.servedCatalog = true;
		return snapshot;
	}

	/** Read the whitelist-projected detail of a single task (`GET /v1/tasks/{id}`). */
	async getTaskDetail(taskId: string): Promise<AgentOSTaskDetail> {
		const segment = assertSafeRouteSegment(taskId, 'taskId');
		const payload = await this.request('GET', `/v1/tasks/${encodeURIComponent(segment)}`);
		const detail = decodeTaskDetail(payload);
		this.servedCatalog = true;
		return detail;
	}

	/** Read the closed trajectory projection of one run (`GET /v1/tasks/{id}/runs/{runId}/trajectory`). */
	async getTaskTrajectory(taskId: string, runId: string): Promise<AgentOSTaskTrajectory> {
		const taskSegment = assertSafeRouteSegment(taskId, 'taskId');
		const runSegment = assertSafeRouteSegment(runId, 'runId');
		const payload = await this.request('GET', `/v1/tasks/${encodeURIComponent(taskSegment)}/runs/${encodeURIComponent(runSegment)}/trajectory`);
		const trajectory = decodeTaskTrajectory(payload);
		this.servedCatalog = true;
		return trajectory;
	}

	/** Read-only request guard: the bridge serves data, never commands. */
	async request(method: string, path: string): Promise<unknown> {
		if (method !== 'GET') {
			throw new RuntimeTaskCatalogError('RUNTIME_READ_ONLY', `bridge is read-only; refused ${method} ${path}`);
		}
		if (!isAllowedGetPath(path)) {
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
		assertRuntimeDescriptorStatSafe(info);
		let value: unknown;
		try {
			value = JSON.parse(await readFile(this.descriptorPath, 'utf8'));
		} catch {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_INVALID', 'runtime descriptor is not valid JSON');
		}
		const descriptor = parseRuntimeDescriptor(value);
		if (!isProcessAlive(descriptor.pid)) {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_STALE', 'runtime descriptor names a dead process');
		}
		return descriptor;
	}
}
