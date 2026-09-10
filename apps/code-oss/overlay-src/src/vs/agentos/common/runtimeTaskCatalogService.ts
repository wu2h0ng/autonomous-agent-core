/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { createDecorator } from '../../platform/instantiation/common/instantiation.js';
import type { AgentOSTaskCatalogSnapshot, AgentOSTaskDetail, AgentOSTaskTrajectory } from './runtimeTaskCatalog.js';

export const IRuntimeTaskCatalogService = createDecorator<IRuntimeTaskCatalogService>('runtimeTaskCatalogService');

/**
 * Read-only Runtime task catalog. Exactly three reads are exposed (catalog,
 * task detail, run trajectory); mutations, approvals and automation arrive
 * through the host protocol in later slices, never through this service.
 */
export interface IRuntimeTaskCatalogService {
	readonly _serviceBrand: undefined;
	listTasks(): Promise<AgentOSTaskCatalogSnapshot>;
	getTaskDetail(taskId: string): Promise<AgentOSTaskDetail>;
	getTaskTrajectory(taskId: string, runId: string): Promise<AgentOSTaskTrajectory>;
}
