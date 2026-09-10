/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter } from '../../base/common/event.js';
import { MarkdownString } from '../../base/common/htmlContent.js';
import { Disposable } from '../../base/common/lifecycle.js';
import { constObservable } from '../../base/common/observable.js';
import type { CancellationToken } from '../../base/common/cancellation.js';
import type { URI } from '../../base/common/uri.js';
import { localize } from '../../nls.js';
import type { IChatSession, IChatSessionContentProvider, IChatSessionHistoryItem } from '../../workbench/contrib/chat/common/chatSessionsService.js';
import type { AgentOSTaskDetail, AgentOSTaskTrajectory } from '../common/runtimeTaskCatalog.js';
import type { IRuntimeTaskCatalogService } from '../common/runtimeTaskCatalogService.js';
import { AGENT_OS_TASK_SCHEME } from './agentOSSessionsProvider.js';

export const AGENT_OS_TRANSCRIPT_PARTICIPANT = 'agent-os-runtime';

/**
 * Human label per frozen TaskEventType value
 * (agent_os_contracts.runtime, schema 1.0). The whitelist must total the
 * contract: every decodable event type renders, and anything outside the
 * contract was already rejected by the closed trajectory decoder.
 */
export const AGENT_OS_TRANSCRIPT_EVENT_LABELS: Readonly<Record<string, string>> = {
	TASK_CREATED: 'Task created',
	TASK_COMMITTED: 'Task committed',
	TASK_CONFIGURATION_SNAPSHOT_SEALED: 'Configuration snapshot sealed',
	RUN_STARTED: 'Run started',
	RUN_QUEUED: 'Run queued',
	NODE_STARTED: 'Node started',
	NODE_COMPLETED: 'Node completed',
	NODE_FAILED: 'Node failed',
	ACTION_PROPOSED: 'Action proposed',
	CANDIDATES_GENERATED: 'Candidates generated',
	PROVIDER_RESPONDED: 'Provider responded',
	POLICY_DECIDED: 'Policy decided',
	ACTION_RECEIPT_RECORDED: 'Action receipt recorded',
	APPROVAL_REQUESTED: 'Approval requested',
	APPROVAL_RECORDED: 'Approval recorded',
	CORRECTION_WRITTEN: 'Correction written',
	OUTCOME_OBSERVED: 'Outcome observed',
	ARTIFACT_RECORDED: 'Artifact recorded',
	RUN_PAUSED: 'Run paused',
	RUN_RESUMED: 'Run resumed',
	RUN_CANCELLED: 'Run cancelled',
	RUN_SUCCEEDED: 'Run succeeded',
	RUN_FAILED: 'Run failed',
	WAIT_REGISTERED: 'Wait registered',
	EXTERNAL_SIGNAL_RECORDED: 'External signal recorded',
	WAIT_SATISFIED: 'Wait satisfied',
	WAIT_TIMED_OUT: 'Wait timed out',
	COMMITMENT_EXPIRED: 'Commitment expired',
	RUN_PLAN_REBOUND: 'Run plan rebound',
	COMPENSATION_STARTED: 'Compensation started',
	ACTION_COMPENSATED: 'Action compensated',
	COMPENSATION_FAILED: 'Compensation failed',
	COMPENSATION_BLOCKED: 'Compensation blocked',
	SESSION_TURN_STARTED: 'Session turn started',
	SESSION_TURN_COMPLETED: 'Session turn completed',
	SESSION_OPENED: 'Session opened',
	SESSION_MESSAGE_RECORDED: 'Session message recorded',
	SESSION_APPROVAL_PENDING: 'Session approval pending',
	SESSION_APPROVAL_EXECUTION_CLAIMED: 'Session approval execution claimed',
	SESSION_APPROVAL_RESOLVED: 'Session approval resolved',
	SESSION_TURN_CONTINUATION_CHECKPOINT: 'Session turn continuation checkpoint',
	SESSION_CLOSED: 'Session closed',
};

/**
 * Extracts the task id from an `agentos-task:/<id>` resource, fail-closed:
 * foreign schemes, empty ids and anything that still contains a path
 * separator after decoding are rejected before they can reach the bridge.
 */
export function parseAgentOSTaskResource(resource: URI): string {
	if (resource.scheme !== AGENT_OS_TASK_SCHEME) {
		throw new Error(`Not an agentos-task resource: ${resource.scheme}`);
	}
	const encoded = resource.path.startsWith('/') ? resource.path.slice(1) : resource.path;
	const taskId = decodeURIComponent(encoded);
	if (taskId.length === 0 || taskId.includes('/') || taskId === '.' || taskId === '..') {
		throw new Error(`Invalid Agent OS task id in resource path: ${JSON.stringify(resource.path)}`);
	}
	return taskId;
}

function timestampOf(iso: string | null): number | undefined {
	if (iso === null) {
		return undefined;
	}
	const parsed = Date.parse(iso);
	return Number.isNaN(parsed) ? undefined : parsed;
}

function transcriptEntry(markdown: MarkdownString, occurredAt: string): IChatSessionHistoryItem {
	return {
		type: 'response',
		parts: [{ kind: 'markdownContent', content: markdown }],
		participant: AGENT_OS_TRANSCRIPT_PARTICIPANT,
		completedAt: timestampOf(occurredAt),
	};
}

/**
 * Maps the whitelist task detail and the closed trajectory projection onto
 * read-only chat history. Per-run filtering leaves sequence gaps in the
 * stream; they surface as explicit annotation entries, never silent skips.
 */
export function agentOSTaskTranscript(detail: AgentOSTaskDetail, trajectory: AgentOSTaskTrajectory | null): readonly IChatSessionHistoryItem[] {
	const history: IChatSessionHistoryItem[] = [{
		type: 'request',
		prompt: detail.statement.length > 0 ? detail.statement : detail.taskId,
		participant: AGENT_OS_TRANSCRIPT_PARTICIPANT,
		timestamp: timestampOf(detail.runCreatedAt),
	}];
	if (trajectory === null) {
		history.push(transcriptEntry(
			new MarkdownString(localize('agentOS.transcript.noRun', "No run has been recorded for this task yet.")),
			detail.runCreatedAt ?? '',
		));
		return history;
	}
	for (const step of trajectory.steps) {
		if (step.gapBefore > 0) {
			history.push(transcriptEntry(
				new MarkdownString(localize(
					'agentOS.transcript.gap',
					"> {0} stream event(s) not part of this run (sequence gap before seq #{1}).",
					step.gapBefore,
					step.sequence,
				)),
				step.occurredAt,
			));
		}
		const label = AGENT_OS_TRANSCRIPT_EVENT_LABELS[step.eventType];
		if (label === undefined) {
			// Defence in depth: the closed decoder already rejected unknown
			// types, so reaching this point means the whitelist drifted.
			throw new Error(`No transcript label for Agent OS event type: ${step.eventType}`);
		}
		history.push(transcriptEntry(
			new MarkdownString(`**${label}** — \`${step.eventType}\` · seq #${step.sequence} · ${step.occurredAt}`),
			step.occurredAt,
		));
	}
	return history;
}

/**
 * Read-only chat session content provider for `agentos-task:` resources. The
 * transcript is a projection of runtime truth; the provider carries no write
 * handler, so the rendered chat has no path back into the runtime.
 */
export class AgentOSTaskContentProvider extends Disposable implements IChatSessionContentProvider {
	private readonly catalog: IRuntimeTaskCatalogService;
	private readonly reportError: (error: Error) => void;

	constructor(catalog: IRuntimeTaskCatalogService, reportError: (error: Error) => void) {
		super();
		this.catalog = catalog;
		this.reportError = reportError;
	}

	async provideChatSessionContent(sessionResource: URI, _token: CancellationToken): Promise<IChatSession> {
		try {
			const taskId = parseAgentOSTaskResource(sessionResource);
			const detail = await this.catalog.getTaskDetail(taskId);
			const trajectory = detail.runId === null ? null : await this.catalog.getTaskTrajectory(detail.taskId, detail.runId);
			const history = agentOSTaskTranscript(detail, trajectory);
			const onWillDisposeEmitter = this._register(new Emitter<void>());
			return {
				sessionResource,
				title: detail.statement.length > 0 ? detail.statement : detail.taskId,
				history,
				isReadOnly: constObservable(true),
				isCompleteObs: constObservable(true),
				onWillDispose: onWillDisposeEmitter.event,
				dispose: () => onWillDisposeEmitter.fire(),
			};
		} catch (error) {
			this.reportError(error instanceof Error ? error : new Error(String(error)));
			throw error;
		}
	}
}
