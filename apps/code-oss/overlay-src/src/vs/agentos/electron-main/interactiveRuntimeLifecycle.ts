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
 * Pid-reuse defence: a start-time fingerprint is captured before SIGTERM and
 * re-checked on every poll and again before SIGKILL. A reused pid never shares
 * the original fingerprint, so escalation can never hit a foreign process; if
 * identity can no longer be proven, the routine fails closed and does not
 * signal at all.
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
}

export const INTERACTIVE_RUNTIME_TERMINATION_DEADLINE_MS = 5_000;

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

/**
 * Start-time fingerprint of the process at `pid`. Two different processes
 * never share a start time, so a changed fingerprint proves the pid was
 * reused. Returns null when the pid is dead or cannot be inspected.
 */
export function processStartFingerprint(pid: number): string | null {
	try {
		const out = execFileSync('ps', ['-o', 'lstart=', '-p', String(pid)], { encoding: 'utf8' }).trim();
		return out.length > 0 ? out : null;
	} catch {
		return null;
	}
}

export function beginInteractiveRuntimeTermination(
	descriptorPath: string,
	deadlineMs: number = INTERACTIVE_RUNTIME_TERMINATION_DEADLINE_MS,
	deps: InteractiveRuntimeTerminationDeps = {},
): InteractiveRuntimeTermination {
	const fingerprintOf = deps.fingerprintOf ?? processStartFingerprint;
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
		// Escalation is destructive; re-prove both identities before SIGKILL.
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
		try {
			process.kill(pid, 'SIGKILL');
		} catch { /* already gone */ }
		return 'terminated';
	})();
	return { pending: true, done };
}
