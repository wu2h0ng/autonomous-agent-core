/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { lstatSync, readFileSync } from 'node:fs';
import { assertRuntimeDescriptorStatSafe, parseRuntimeDescriptor } from './runtimeTaskCatalogMainService.js';

/**
 * Bounded termination of the interactive runtime on application quit.
 *
 * Window and renderer reloads never reach this path; only application quit
 * does. The descriptor is re-read immediately before signalling so a stale
 * file (or a recycled pid) cannot redirect the signal to an unrelated process.
 */

export type InteractiveRuntimeTerminationResult = 'terminated' | 'not-running' | 'descriptor-unavailable' | 'descriptor-changed';

export interface InteractiveRuntimeTermination {
	/** Whether a signal was sent and the caller should delay quit until `done`. */
	readonly pending: boolean;
	readonly done: Promise<InteractiveRuntimeTerminationResult>;
}

export const INTERACTIVE_RUNTIME_TERMINATION_DEADLINE_MS = 5_000;

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

function isProcessAlive(pid: number): boolean {
	try {
		process.kill(pid, 0);
		return true;
	} catch {
		return false;
	}
}

export function beginInteractiveRuntimeTermination(
	descriptorPath: string,
	deadlineMs: number = INTERACTIVE_RUNTIME_TERMINATION_DEADLINE_MS,
): InteractiveRuntimeTermination {
	let descriptor;
	try {
		assertRuntimeDescriptorStatSafe(lstatSync(descriptorPath));
		descriptor = parseRuntimeDescriptor(JSON.parse(readFileSync(descriptorPath, 'utf8')));
	} catch {
		return { pending: false, done: Promise.resolve('descriptor-unavailable') };
	}
	if (!isProcessAlive(descriptor.pid)) {
		return { pending: false, done: Promise.resolve('not-running') };
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
	try {
		process.kill(descriptor.pid, 'SIGTERM');
	} catch {
		return { pending: false, done: Promise.resolve('not-running') };
	}
	const pid = descriptor.pid;
	const done = (async (): Promise<InteractiveRuntimeTerminationResult> => {
		const deadline = Date.now() + deadlineMs;
		while (Date.now() < deadline) {
			if (!isProcessAlive(pid)) {
				return 'terminated';
			}
			await sleep(50);
		}
		if (isProcessAlive(pid)) {
			try {
				process.kill(pid, 'SIGKILL');
			} catch { /* already gone */ }
		}
		return 'terminated';
	})();
	return { pending: true, done };
}
