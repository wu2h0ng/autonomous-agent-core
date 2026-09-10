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
	| 'RUNTIME_COMMAND_REJECTED'
	| 'RUNTIME_COMMAND_FAILED'
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

/**
 * Slice 3: the bridge's entire mutation surface — exactly the two-step
 * approval recipe (spec §7.2/§12③). Method+path are checked together;
 * every other non-GET shape stays refused.
 */
const ALLOWED_POST_PATH_PATTERNS: readonly RegExp[] = [
	/^\/v1\/tasks\/[^/]+\/approval$/,
	/^\/v1\/tasks\/[^/]+\/run$/,
];

function isAllowedPostPath(path: string): boolean {
	return ALLOWED_POST_PATH_PATTERNS.some(pattern => pattern.test(path));
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
		// Validated segments contain no character that needs URL encoding, and
		// the runtime router does not percent-decode — encodeURIComponent would
		// turn a legal `:` into a 404.
		const payload = await this.request('GET', `/v1/tasks/${segment}`);
		const detail = decodeTaskDetail(payload);
		this.servedCatalog = true;
		return detail;
	}

	/** Read the closed trajectory projection of one run (`GET /v1/tasks/{id}/runs/{runId}/trajectory`). */
	async getTaskTrajectory(taskId: string, runId: string): Promise<AgentOSTaskTrajectory> {
		const taskSegment = assertSafeRouteSegment(taskId, 'taskId');
		const runSegment = assertSafeRouteSegment(runId, 'runId');
		const payload = await this.request('GET', `/v1/tasks/${taskSegment}/runs/${runSegment}/trajectory`);
		const trajectory = decodeTaskTrajectory(payload);
		this.servedCatalog = true;
		return trajectory;
	}

	/**
	 * Slice 3 write path (1/2): record the principal's approval decision
	 * (`POST /v1/tasks/{id}/approval`). The digest is echoed verbatim from the
	 * rendered approval card projection — the bridge never computes one.
	 * Returns the freshly decoded detail so the card converges on the
	 * server-recorded decision, never on local optimistic state.
	 */
	async decideTaskApproval(taskId: string, decision: unknown): Promise<AgentOSTaskDetail> {
		const segment = assertSafeRouteSegment(taskId, 'taskId');
		if (typeof decision !== 'object' || decision === null || Array.isArray(decision)) {
			throw new RuntimeTaskCatalogError('RUNTIME_COMMAND_REJECTED', 'decideTaskApproval requires a decision object');
		}
		const record = decision as Record<string, unknown>;
		const keys = Object.keys(record).sort();
		const expected = ['actionDigest', 'disposition', 'reason'];
		if (keys.length !== expected.length || !keys.every((key, i) => key === expected[i])) {
			throw new RuntimeTaskCatalogError('RUNTIME_COMMAND_REJECTED', `decision must carry exactly ${expected.join(', ')}; unknown or missing keys: ${keys.join(', ')}`);
		}
		const { actionDigest, disposition, reason } = record;
		if (typeof actionDigest !== 'string' || !/^[0-9a-f]{64}$/.test(actionDigest)) {
			throw new RuntimeTaskCatalogError('RUNTIME_COMMAND_REJECTED', 'decision actionDigest must be the exact 64-char hex digest shown on the approval card');
		}
		if (disposition !== 'APPROVE' && disposition !== 'REJECT') {
			throw new RuntimeTaskCatalogError('RUNTIME_COMMAND_REJECTED', `decision disposition must be APPROVE or REJECT over this bridge; got ${JSON.stringify(disposition)}`);
		}
		if (typeof reason !== 'string' || reason.trim().length === 0) {
			throw new RuntimeTaskCatalogError('RUNTIME_COMMAND_REJECTED', 'decision reason must be a non-empty string');
		}
		const payload = await this.request('POST', `/v1/tasks/${segment}/approval`, {
			action_digest: actionDigest,
			disposition,
			reason: reason.trim(),
		});
		const detail = decodeTaskDetail(payload);
		this.servedCatalog = true;
		return detail;
	}

	/**
	 * Slice 3 write path (2/2): resume a parked run after approval
	 * (`POST /v1/tasks/{id}/run`). The body is ALWAYS exactly
	 * `{ configuration_snapshot_id }` — the endpoint also accepts `inputs`
	 * and `recover_stale_lease`, and this bridge must never emit them
	 * (gate review P2 N-2).
	 */
	async resumeTaskRun(taskId: string, configurationSnapshotId: unknown): Promise<AgentOSTaskDetail> {
		const segment = assertSafeRouteSegment(taskId, 'taskId');
		if (typeof configurationSnapshotId !== 'string' || configurationSnapshotId.length === 0) {
			throw new RuntimeTaskCatalogError('RUNTIME_COMMAND_REJECTED', 'resumeTaskRun requires a non-empty configuration snapshot id string');
		}
		const snapshotSegment = assertSafeRouteSegment(configurationSnapshotId, 'configurationSnapshotId');
		const payload = await this.request('POST', `/v1/tasks/${segment}/run`, {
			configuration_snapshot_id: snapshotSegment,
		});
		const detail = decodeTaskDetail(payload);
		this.servedCatalog = true;
		return detail;
	}

	/**
	 * Method+path closed request guard: GET serves the read allowlist; POST
	 * serves exactly the two approval-recipe routes; every other shape is
	 * refused before any network traffic.
	 */
	async request(method: string, path: string, body?: unknown): Promise<unknown> {
		if (method === 'GET') {
			if (!isAllowedGetPath(path)) {
				throw new RuntimeTaskCatalogError('RUNTIME_PATH_NOT_ALLOWED', `path not allowed on the task catalog bridge: ${path}`);
			}
		} else if (method === 'POST') {
			if (!isAllowedPostPath(path)) {
				throw new RuntimeTaskCatalogError('RUNTIME_READ_ONLY', `bridge is read-only except the typed approval commands; refused ${method} ${path}`);
			}
		} else {
			throw new RuntimeTaskCatalogError('RUNTIME_READ_ONLY', `bridge is read-only except the typed approval commands; refused ${method} ${path}`);
		}
		const descriptor = await this.loadDescriptor();
		const url = `http://${descriptor.host}:${descriptor.port}${path}`;
		const responseBody = await this.fetchJson(url, descriptor.bearer_token, method, body);
		// The daemon may have restarted mid-request; the response is only
		// trustworthy if the descriptor still names the same process/boot.
		const after = await this.loadDescriptor();
		if (after.pid !== descriptor.pid || after.boot_id !== descriptor.boot_id
			|| after.port !== descriptor.port || after.bearer_token !== descriptor.bearer_token) {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_CHANGED', 'runtime descriptor changed during the request');
		}
		return responseBody;
	}

	private async fetchJson(url: string, bearerToken: string, method: string, body?: unknown): Promise<unknown> {
		let response;
		try {
			response = await fetch(url, {
				method,
				headers: {
					'Authorization': `Bearer ${bearerToken}`,
					'Accept': 'application/json',
					...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
				},
				...(body !== undefined ? { body: JSON.stringify(body) } : {}),
				signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
			});
		} catch (error) {
			throw new RuntimeTaskCatalogError('RUNTIME_UNREACHABLE', `runtime request failed: ${(error as Error).message}`);
		}
		if (response.status === 401) {
			throw new RuntimeTaskCatalogError('RUNTIME_DESCRIPTOR_STALE', 'runtime rejected the descriptor bearer token');
		}
		if (!response.ok) {
			// The daemon answers {error, message}; surface both verbatim so the
			// UI can show the server's own words instead of guessing semantics.
			const detail = await this.readErrorDetail(response);
			if (response.status >= 400 && response.status < 500) {
				throw new RuntimeTaskCatalogError('RUNTIME_COMMAND_REJECTED', `runtime refused the command (HTTP ${response.status})${detail}`);
			}
			throw new RuntimeTaskCatalogError('RUNTIME_COMMAND_FAILED', `runtime command failed (HTTP ${response.status})${detail}`);
		}
		const text = await response.text();
		if (Buffer.byteLength(text, 'utf8') > RESPONSE_CAP_BYTES) {
			throw new RuntimeTaskCatalogError('RUNTIME_RESPONSE_TOO_LARGE', 'runtime response exceeds the 1 MiB cap');
		}
		return JSON.parse(text);
	}

	private async readErrorDetail(response: Response): Promise<string> {
		try {
			const text = await response.text();
			if (Buffer.byteLength(text, 'utf8') > RESPONSE_CAP_BYTES) {
				return '';
			}
			const parsed = JSON.parse(text);
			if (parsed && typeof parsed.message === 'string') {
				return `: ${parsed.message}`;
			}
			if (parsed && typeof parsed.error === 'string') {
				return `: ${parsed.error}`;
			}
		} catch {
			// Fall through: an unreadable error body must not mask the status.
		}
		return '';
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
