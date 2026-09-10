/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { execFileSync } from 'node:child_process';
import { lstatSync, readFileSync } from 'node:fs';
import { assertRuntimeDescriptorStatSafe, parseRuntimeDescriptor } from './runtimeTaskCatalogMainService.js';

/**
 * Bounded termination of the interactive runtime on application quit.
 *
 * Window and renderer reloads never reach this path; only application quit
 * does. The descriptor is re-read immediately before signalling so a stale
 * file (or a recycled pid) cannot redirect the signal to an unrelated process.
 *
 * Pid-reuse defence is layered, weakest signal first: a start-time
 * fingerprint (second resolution, cheap early exit) is captured before
 * SIGTERM and re-checked on every poll; before destructive SIGKILL the
 * descriptor pid+boot_id is re-read AND a bearer-authenticated HTTP probe
 * must answer on the descriptor socket. A foreign process at a reused pid
 * cannot satisfy the probe without the bearer secret, so escalation cannot
 * hit it; if identity cannot be proven on every channel, the routine fails
 * closed and does not signal at all.
 */

export type InteractiveRuntimeTerminationResult = 'terminated' | 'not-running' | 'descriptor-unavailable' | 'descriptor-changed';

export interface InteractiveRuntimeTermination {
	/** Whether a signal was sent and the caller should delay quit until `done`. */
	readonly pending: boolean;
	readonly done: Promise<InteractiveRuntimeTerminationResult>;
}

export interface InteractiveRuntimeTerminationDeps {
	/** Process start-time fingerprint; injected by tests to simulate pid reuse. */
	readonly fingerprintOf?: (pid: number) => string | null;
	/** Bearer-authenticated runtime probe; injected by tests to simulate identity loss. */
	readonly probeIdentity?: (descriptor: { readonly host: string; readonly port: number; readonly bearer_token: string }) => Promise<boolean>;
}

export const INTERACTIVE_RUNTIME_TERMINATION_DEADLINE_MS = 5_000;

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

/**
 * Start-time fingerprint of the process at `pid`. Resolution is one second,
 * so this is a cheap early signal only — destructive escalation must also
 * pass the bearer-authenticated runtime probe below. Returns null when the
 * pid is dead or cannot be inspected.
 */
export function processStartFingerprint(pid: number): string | null {
	try {
		const out = execFileSync('ps', ['-o', 'lstart=', '-p', String(pid)], { encoding: 'utf8' }).trim();
		return out.length > 0 ? out : null;
	} catch {
		return null;
	}
}

/**
 * Strong runtime identity proof: something listening on the descriptor's exact
 * host:port must answer bearer-authenticated HTTP. A foreign process at a
 * reused pid cannot satisfy this without also holding the bearer secret.
 * Any failure (refused, timeout, 401, non-OK) means identity is NOT proven.
 */
export async function probeRuntimeIdentity(descriptor: { readonly host: string; readonly port: number; readonly bearer_token: string }): Promise<boolean> {
	try {
		const response = await fetch(`http://${descriptor.host}:${descriptor.port}/v1/tasks`, {
			method: 'GET',
			headers: { 'Authorization': `Bearer ${descriptor.bearer_token}`, 'Accept': 'application/json' },
			signal: AbortSignal.timeout(1_000),
		});
		return response.ok;
	} catch {
		return false;
	}
}

export function beginInteractiveRuntimeTermination(
	descriptorPath: string,
	deadlineMs: number = INTERACTIVE_RUNTIME_TERMINATION_DEADLINE_MS,
	deps: InteractiveRuntimeTerminationDeps = {},
): InteractiveRuntimeTermination {
	const fingerprintOf = deps.fingerprintOf ?? processStartFingerprint;
	const probeIdentity = deps.probeIdentity ?? probeRuntimeIdentity;
	let descriptor;
	try {
		assertRuntimeDescriptorStatSafe(lstatSync(descriptorPath));
		descriptor = parseRuntimeDescriptor(JSON.parse(readFileSync(descriptorPath, 'utf8')));
	} catch {
		return { pending: false, done: Promise.resolve('descriptor-unavailable') };
	}
	// Narrow the pid-reuse window: re-read and require the same runtime
	// identity immediately before signalling.
	try {
		const fresh = parseRuntimeDescriptor(JSON.parse(readFileSync(descriptorPath, 'utf8')));
		if (fresh.pid !== descriptor.pid || fresh.boot_id !== descriptor.boot_id) {
			return { pending: false, done: Promise.resolve('descriptor-changed') };
		}
	} catch {
		return { pending: false, done: Promise.resolve('descriptor-unavailable') };
	}
	// Capture the process identity before signalling; every later escalation
	// must prove the pid still hosts this exact process.
	const fingerprint = fingerprintOf(descriptor.pid);
	if (fingerprint === null) {
		return { pending: false, done: Promise.resolve('not-running') };
	}
	try {
		process.kill(descriptor.pid, 'SIGTERM');
	} catch {
		return { pending: false, done: Promise.resolve('not-running') };
	}
	const pid = descriptor.pid;
	const bootId = descriptor.boot_id;
	const done = (async (): Promise<InteractiveRuntimeTerminationResult> => {
		const deadline = Date.now() + deadlineMs;
		while (Date.now() < deadline) {
			const current = fingerprintOf(pid);
			if (current === null || current !== fingerprint) {
				// Dead, or the pid was reused by a foreign process: either way
				// our runtime is gone and nothing more may be signalled.
				return 'terminated';
			}
			await sleep(50);
		}
		// Escalation is destructive; re-prove identity on three independent
		// channels before SIGKILL, and fail closed when any cannot be proven:
		// start-time fingerprint (cheap, second-resolution), descriptor
		// pid+boot_id (catches a replacement runtime), and the bearer-
		// authenticated HTTP probe (strong: a foreign process at a reused pid
		// cannot answer with the bearer on the descriptor socket).
		const current = fingerprintOf(pid);
		if (current === null || current !== fingerprint) {
			return 'terminated';
		}
		try {
			const fresh = parseRuntimeDescriptor(JSON.parse(readFileSync(descriptorPath, 'utf8')));
			if (fresh.pid !== pid || fresh.boot_id !== bootId) {
				return 'descriptor-changed';
			}
		} catch {
			return 'descriptor-unavailable';
		}
		if (!await probeIdentity(descriptor)) {
			return 'terminated';
		}
		try {
			process.kill(pid, 'SIGKILL');
		} catch { /* already gone */ }
		return 'terminated';
	})();
	return { pending: true, done };
}
