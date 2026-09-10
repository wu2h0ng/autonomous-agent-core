/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { IServerChannel } from '../../base/parts/ipc/common/ipc.js';
import type { RuntimeTaskCatalogMainService } from './runtimeTaskCatalogMainService.js';

export const RUNTIME_TASK_CATALOG_CHANNEL = 'agentOSRuntimeTaskCatalog';

/**
 * IPC channel for the read-only Runtime task catalog. Exactly three read
 * commands are exposed (list, detail, trajectory); everything else —
 * including any mutation-shaped command — throws. The channel only ever
 * returns the decoded projection, so descriptor bytes and the bearer token
 * cannot cross into a renderer.
 */
export class RuntimeTaskCatalogChannel implements IServerChannel<string> {
	private readonly service: RuntimeTaskCatalogMainService;

	constructor(service: RuntimeTaskCatalogMainService) {
		this.service = service;
	}

	listen(_: string, event: string): never {
		throw new Error(`Unknown runtime task catalog event: ${event}`);
	}

	async call<T>(_: string, command: string, args?: unknown): Promise<T> {
		const argv = Array.isArray(args) ? args : [];
		switch (command) {
			case 'listTasks':
				return this.service.listTasks() as Promise<T>;
			case 'getTaskDetail': {
				const [taskId] = argv;
				if (typeof taskId !== 'string') {
					throw new Error(`getTaskDetail requires a string taskId argument`);
				}
				return this.service.getTaskDetail(taskId) as Promise<T>;
			}
			case 'getTaskTrajectory': {
				const [taskId, runId] = argv;
				if (typeof taskId !== 'string' || typeof runId !== 'string') {
					throw new Error(`getTaskTrajectory requires string taskId and runId arguments`);
				}
				return this.service.getTaskTrajectory(taskId, runId) as Promise<T>;
			}
			default:
				throw new Error(`Unknown runtime task catalog command: ${command}`);
		}
	}
}
