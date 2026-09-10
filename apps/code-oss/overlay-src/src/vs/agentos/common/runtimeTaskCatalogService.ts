/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { createDecorator } from '../../platform/instantiation/common/instantiation.js';
import type { AgentOSTaskCatalogSnapshot, AgentOSTaskDetail, AgentOSTaskTrajectory } from './runtimeTaskCatalog.js';

export const IRuntimeTaskCatalogService = createDecorator<IRuntimeTaskCatalogService>('runtimeTaskCatalogService');

/**
 * Runtime task catalog service. Reads: catalog, task detail, run trajectory.
 * Slice 3 write surface: exactly the two-step approval recipe —
 * decideTaskApproval (record the principal's decision) and resumeTaskRun
 * (resume a parked run after approval). Everything else stays read-only.
 */
export interface IRuntimeTaskCatalogService {
	readonly _serviceBrand: undefined;
	listTasks(): Promise<AgentOSTaskCatalogSnapshot>;
	getTaskDetail(taskId: string): Promise<AgentOSTaskDetail>;
	getTaskTrajectory(taskId: string, runId: string): Promise<AgentOSTaskTrajectory>;
	decideTaskApproval(taskId: string, decision: AgentOSTaskApprovalDecisionInput): Promise<AgentOSTaskDetail>;
	resumeTaskRun(taskId: string, configurationSnapshotId: string): Promise<AgentOSTaskDetail>;
}

/** Typed input for the approval decision command; the digest echoes the card. */
export interface AgentOSTaskApprovalDecisionInput {
	readonly actionDigest: string;
	readonly disposition: 'APPROVE' | 'REJECT';
	readonly reason: string;
}
