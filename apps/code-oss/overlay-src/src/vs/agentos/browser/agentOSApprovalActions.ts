/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../nls.js';
import { Action2, registerAction2 } from '../../platform/actions/common/actions.js';
import type { ServicesAccessor } from '../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../platform/notification/common/notification.js';
import { IQuickInputService } from '../../platform/quickinput/common/quickInput.js';
import type { IDisposable } from '../../base/common/lifecycle.js';
import { IRuntimeTaskCatalogService } from '../common/runtimeTaskCatalogService.js';
import { AGENT_OS_APPROVAL_DECIDE_COMMAND } from './agentOSTaskContentProvider.js';

/** Args carried by the approval card command links (projection-sourced). */
export interface AgentOSApprovalCommandArgs {
	readonly taskId: string;
	readonly actionDigest: string;
	readonly disposition: 'APPROVE' | 'REJECT';
	readonly configurationSnapshotId: string;
}

function parseArgs(value: unknown): AgentOSApprovalCommandArgs {
	if (typeof value !== 'object' || value === null || Array.isArray(value)) {
		throw new Error('approval decision requires the card command arguments');
	}
	const args = value as Record<string, unknown>;
	if (typeof args.taskId !== 'string' || typeof args.actionDigest !== 'string'
		|| typeof args.configurationSnapshotId !== 'string'
		|| (args.disposition !== 'APPROVE' && args.disposition !== 'REJECT')) {
		throw new Error('approval decision arguments are malformed');
	}
	return args as unknown as AgentOSApprovalCommandArgs;
}

/**
 * Registers the approval decision command behind the card links. The command
 * is the ONLY renderer-side write path: it echoes the card's digest, asks for
 * a mandatory reason, submits through the typed bridge commands and — on
 * APPROVE — resumes the parked run with exactly the sealed snapshot id.
 * Convergence is server-truth: after the round trip the cached session is
 * invalidated so the next render re-pulls the recorded decision.
 */
export function registerAgentOSApprovalActions(hooks: { onAfterDecision(taskId: string): void }): IDisposable {
	return registerAction2(class extends Action2 {
		constructor() {
			super({
				id: AGENT_OS_APPROVAL_DECIDE_COMMAND,
				title: localize('agentOS.approval.decideTitle', "Agent OS: Decide Pending Approval"),
				f1: false,
			});
		}

		async run(accessor: ServicesAccessor, value: unknown): Promise<void> {
			const catalog = accessor.get(IRuntimeTaskCatalogService);
			const quickInput = accessor.get(IQuickInputService);
			const notifications = accessor.get(INotificationService);

			let args: AgentOSApprovalCommandArgs;
			try {
				args = parseArgs(value);
			} catch (error) {
				notifications.notify({ severity: Severity.Error, message: localize('agentOS.approval.badArgs', "The approval card is malformed; close and reopen the task. ({0})", (error as Error).message) });
				return;
			}

			const reason = await quickInput.input({
				title: args.disposition === 'APPROVE'
					? localize('agentOS.approval.approveTitle', "Approve {0}", args.actionDigest.slice(0, 12))
					: localize('agentOS.approval.rejectTitle', "Reject {0}", args.actionDigest.slice(0, 12)),
				prompt: localize('agentOS.approval.reasonPrompt', "A reason is required and is recorded with the decision."),
				validateInput: input => Promise.resolve(input.trim().length === 0
					? localize('agentOS.approval.reasonRequired', "Reason is required")
					: undefined),
			});
			if (reason === undefined) {
				return; // Cancelled: nothing was submitted.
			}

			try {
				const decided = await catalog.decideTaskApproval(args.taskId, {
					actionDigest: args.actionDigest,
					disposition: args.disposition,
					reason: reason.trim(),
				});
				let resumed = false;
				if (args.disposition === 'APPROVE') {
					await catalog.resumeTaskRun(args.taskId, args.configurationSnapshotId);
					resumed = true;
				}
				hooks.onAfterDecision(args.taskId);
				notifications.notify({
					severity: Severity.Info,
					message: decided.approvalDecision?.disposition === 'REJECT'
						? localize('agentOS.approval.rejectedInfo', "Decision recorded: rejected. The action will not run.")
						: resumed
							? localize('agentOS.approval.approvedResumed', "Decision recorded: approved. The run has resumed.")
							: localize('agentOS.approval.decisionRecorded', "Decision recorded."),
				});
			} catch (error) {
				// The bridge's typed errors carry the daemon's own message; surface
				// it verbatim, never a guessed meaning.
				notifications.notify({
					severity: Severity.Error,
					message: localize('agentOS.approval.failed', "Approval decision failed: {0}", (error as Error).message),
				});
			}
		}
	});
}
