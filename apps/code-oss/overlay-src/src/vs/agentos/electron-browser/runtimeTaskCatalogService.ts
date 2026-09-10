/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { ProxyChannel } from '../../base/parts/ipc/common/ipc.js';
import { IMainProcessService } from '../../platform/ipc/common/mainProcessService.js';
import type { AgentOSTaskCatalogSnapshot, AgentOSTaskDetail, AgentOSTaskTrajectory } from '../common/runtimeTaskCatalog.js';
import { IRuntimeTaskCatalogService } from '../common/runtimeTaskCatalogService.js';
import { RUNTIME_TASK_CATALOG_CHANNEL } from '../electron-main/runtimeTaskCatalogChannel.js';

/**
 * Renderer-side proxy for the read-only Runtime task catalog. Registered lazy
 * and inert; it holds no credentials and only talks to the main-process
 * channel, which returns the decoded projection.
 */
export class RuntimeTaskCatalogService implements IRuntimeTaskCatalogService {
	declare readonly _serviceBrand: undefined;

	private readonly service: IRuntimeTaskCatalogService;

	constructor(@IMainProcessService mainProcessService: IMainProcessService) {
		this.service = ProxyChannel.toService<IRuntimeTaskCatalogService>(
			mainProcessService.getChannel(RUNTIME_TASK_CATALOG_CHANNEL),
		);
	}

	listTasks(): Promise<AgentOSTaskCatalogSnapshot> {
		return this.service.listTasks();
	}

	getTaskDetail(taskId: string): Promise<AgentOSTaskDetail> {
		return this.service.getTaskDetail(taskId);
	}

	getTaskTrajectory(taskId: string, runId: string): Promise<AgentOSTaskTrajectory> {
		return this.service.getTaskTrajectory(taskId, runId);
	}
}
