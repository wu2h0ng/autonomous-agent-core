/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

/**
 * Closed read-only projection of the Agent OS Runtime task catalog.
 *
 * The wire shape is the exact `GET /v1/tasks` response of the Python Product
 * Runtime: `{ tasks: [{ task_id, status, statement, run_status, sequence }] }`.
 * The decoder is fail-closed: root keys must be exactly `tasks`, task keys must
 * be exactly the five server fields, and no credential or authority field is
 * ever accepted. Slice 1 is read-only; mutations are rejected upstream of this
 * decoder and never reach it.
 */
export interface AgentOSTaskSummary {
	readonly taskId: string;
	readonly status: string | null;
	readonly statement: string;
	readonly runStatus: string | null;
	readonly sequence: number;
}

export interface AgentOSTaskCatalogSnapshot {
	readonly tasks: readonly AgentOSTaskSummary[];
	readonly fetchedAt: number;
}

function fail(reason: string): never {
	throw new Error(`Invalid Agent OS task catalog: ${reason}`);
}

function decodeTask(value: unknown, index: number): AgentOSTaskSummary {
	if (typeof value !== 'object' || value === null || Array.isArray(value)) {
		fail(`tasks[${index}] must be an object`);
	}
	const record = value as Record<string, unknown>;
	const keys = Object.keys(record).sort();
	const expected = ['run_status', 'sequence', 'statement', 'status', 'task_id'];
	if (keys.length !== expected.length || !keys.every((key, i) => key === expected[i])) {
		fail(`tasks[${index}] must carry exactly ${expected.join(', ')}; got ${keys.join(', ')}`);
	}
	const { task_id, status, statement, run_status, sequence } = record;
	if (typeof task_id !== 'string' || task_id.length === 0) {
		fail(`tasks[${index}].task_id must be a non-empty string`);
	}
	if (status !== null && typeof status !== 'string') {
		fail(`tasks[${index}].status must be a string or null`);
	}
	if (typeof statement !== 'string') {
		fail(`tasks[${index}].statement must be a string`);
	}
	if (run_status !== null && typeof run_status !== 'string') {
		fail(`tasks[${index}].run_status must be a string or null`);
	}
	if (typeof sequence !== 'number' || !Number.isInteger(sequence) || sequence < 0) {
		fail(`tasks[${index}].sequence must be an integer >= 0`);
	}
	return {
		taskId: task_id,
		status: status as string | null,
		statement: statement as string,
		runStatus: run_status as string | null,
		sequence: sequence as number,
	};
}

export function decodeTaskCatalog(payload: unknown, fetchedAt: number = Date.now()): AgentOSTaskCatalogSnapshot {
	if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
		fail('payload must be an object');
	}
	const record = payload as Record<string, unknown>;
	const keys = Object.keys(record);
	if (keys.length !== 1 || keys[0] !== 'tasks') {
		fail(`root keys must be exactly {tasks}; got ${keys.join(', ') || '(none)'}`);
	}
	const tasks = record['tasks'];
	if (!Array.isArray(tasks)) {
		fail('tasks must be an array');
	}
	return {
		tasks: tasks.map((task, index) => decodeTask(task, index)),
		fetchedAt,
	};
}

// --- Slice 2: task detail (whitelist projection over the over-rich task_json) ---

/**
 * Minimal read-only projection of the runtime task detail (`GET /v1/tasks/{id}`).
 *
 * The server payload is intentionally rich (approval, proposed_action,
 * provider usage, raw decoded events, artifacts, workspace, domain pack).
 * None of that may cross the bridge: this decoder projects a fixed whitelist
 * and the output is closed by construction — the forbidden keys can never
 * appear in the result regardless of the input.
 */
export interface AgentOSTaskDetail {
	readonly taskId: string;
	readonly status: string | null;
	readonly statement: string;
	readonly runId: string | null;
	readonly runStatus: string | null;
	readonly runCreatedAt: string | null;
	readonly sequence: number;
	readonly configurationSnapshotId: string | null;
	readonly approvalCard: AgentOSApprovalCard | null;
	readonly approvalDecision: AgentOSApprovalDecision | null;
}

// --- Slice 3: approval card (whitelist projection over proposed_action/approval) ---

/**
 * Minimal projection of the pending ActionContract for the approval card
 * (spec §7.3). Projected ONLY while the run is parked at WAITING_APPROVAL.
 * The card is the source of truth for the digest the user approves: the UI
 * echoes `actionDigest` back verbatim and never computes a digest itself.
 */
export interface AgentOSApprovalCard {
	readonly capabilityId: string;
	readonly capabilityVersion: string;
	readonly riskTier: number;
	readonly actionDigest: string;
	readonly policyVersion: string;
	readonly principalId: string;
	readonly runId: string;
	readonly nodeId: string;
	/** Bounded pretty-printed arguments (the resource scope under review). */
	readonly argumentsPreview: string;
	readonly argumentsTruncated: boolean;
}

/** Minimal projection of the recorded ApprovalDecision for card convergence. */
export interface AgentOSApprovalDecision {
	readonly disposition: string;
	readonly reason: string;
	readonly actionDigest: string;
	readonly actorId: string;
	readonly decidedAt: string;
	readonly expiresAt: string;
}

/** ActionContract dump keys the runtime may serve (frozen by real fixture). */
const KNOWN_PROPOSED_ACTION_KEYS: ReadonlySet<string> = new Set([
	'action_digest', 'action_id', 'arguments', 'arguments_json',
	'approval_requirement', 'candidate_envelope_id', 'capability_id',
	'capability_version', 'created_at', 'estimated_budget', 'expected_outcome_id',
	'idempotency_key', 'node_id', 'observed_correction_epochs', 'policy_version',
	'principal_id', 'risk_tier', 'run_id', 'schema_version', 'task_id',
	'tenant_id', 'workspace_id',
]);

/** ApprovalDecision dump keys the runtime may serve (frozen by real fixture). */
const KNOWN_APPROVAL_KEYS: ReadonlySet<string> = new Set([
	'action_digest', 'actor_id', 'actor_role', 'approval_id', 'decided_at',
	'disposition', 'expires_at', 'reason', 'schema_version', 'tenant_id',
	'workspace_id',
]);

const ARGUMENTS_PREVIEW_LIMIT = 4096;

function requireSha256(value: unknown, where: string): string {
	if (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value)) {
		fail(`${where} must be a 64-char lowercase hex digest`);
	}
	return value;
}

function decodeApprovalCard(value: unknown): AgentOSApprovalCard {
	if (typeof value !== 'object' || value === null || Array.isArray(value)) {
		fail('proposed_action must be an object');
	}
	const record = value as Record<string, unknown>;
	for (const key of Object.keys(record)) {
		if (!KNOWN_PROPOSED_ACTION_KEYS.has(key)) {
			fail(`proposed_action carries unknown key: ${key}`);
		}
	}
	const capabilityId = requireNonEmptyString(record['capability_id'], 'proposed_action.capability_id');
	const capabilityVersion = requireNonEmptyString(record['capability_version'], 'proposed_action.capability_version');
	const riskTier = record['risk_tier'];
	if (typeof riskTier !== 'number' || !Number.isInteger(riskTier) || riskTier < 0) {
		fail('proposed_action.risk_tier must be an integer >= 0');
	}
	const actionDigest = requireSha256(record['action_digest'], 'proposed_action.action_digest');
	const policyVersion = requireNonEmptyString(record['policy_version'], 'proposed_action.policy_version');
	const principalId = requireNonEmptyString(record['principal_id'], 'proposed_action.principal_id');
	const runId = requireNonEmptyString(record['run_id'], 'proposed_action.run_id');
	const nodeId = requireNonEmptyString(record['node_id'], 'proposed_action.node_id');
	const args = record['arguments'];
	if (typeof args !== 'object' || args === null || Array.isArray(args)) {
		fail('proposed_action.arguments must be an object');
	}
	const fullPreview = JSON.stringify(args, null, 2);
	const truncated = fullPreview.length > ARGUMENTS_PREVIEW_LIMIT;
	return {
		capabilityId,
		capabilityVersion,
		riskTier,
		actionDigest,
		policyVersion,
		principalId,
		runId,
		nodeId,
		argumentsPreview: truncated ? `${fullPreview.slice(0, ARGUMENTS_PREVIEW_LIMIT)}\n… [truncated]` : fullPreview,
		argumentsTruncated: truncated,
	};
}

function decodeApprovalDecision(value: unknown): AgentOSApprovalDecision {
	if (typeof value !== 'object' || value === null || Array.isArray(value)) {
		fail('approval must be an object');
	}
	const record = value as Record<string, unknown>;
	for (const key of Object.keys(record)) {
		if (!KNOWN_APPROVAL_KEYS.has(key)) {
			fail(`approval carries unknown key: ${key}`);
		}
	}
	const disposition = requireNonEmptyString(record['disposition'], 'approval.disposition');
	if (disposition !== 'APPROVE' && disposition !== 'REJECT' && disposition !== 'REVISE') {
		fail(`approval.disposition must be APPROVE/REJECT/REVISE; got ${disposition}`);
	}
	return {
		disposition,
		reason: requireNonEmptyString(record['reason'], 'approval.reason'),
		actionDigest: requireSha256(record['action_digest'], 'approval.action_digest'),
		actorId: requireNonEmptyString(record['actor_id'], 'approval.actor_id'),
		decidedAt: requireNonEmptyString(record['decided_at'], 'approval.decided_at'),
		expiresAt: requireNonEmptyString(record['expires_at'], 'approval.expires_at'),
	};
}

/**
 * Top-level keys the runtime's task_json serves today (frozen by the real
 * captured fixture). The projection whitelists its OUTPUT, and this set
 * closes the INPUT surface: any new server field fails closed here, so a
 * silent contract drift cannot slip richer data past review.
 */
const KNOWN_TASK_DETAIL_KEYS: ReadonlySet<string> = new Set([
	'approval', 'artifacts', 'commitment', 'configuration_snapshot', 'domain_pack',
	'events', 'expected_outcome', 'goal', 'historical_observed_outcome',
	'observed_outcome', 'outcome_evidence_valid', 'proposed_action', 'provider',
	'run', 'sequence', 'status', 'task_id', 'workflow', 'workspace',
]);

export function decodeTaskDetail(payload: unknown): AgentOSTaskDetail {
	if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
		fail('detail payload must be an object');
	}
	const record = payload as Record<string, unknown>;
	for (const key of Object.keys(record)) {
		if (!KNOWN_TASK_DETAIL_KEYS.has(key)) {
			fail(`detail payload carries unknown top-level key: ${key}`);
		}
	}
	const { task_id, status, goal, run, sequence } = record;
	if (typeof task_id !== 'string' || task_id.length === 0) {
		fail('task_id must be a non-empty string');
	}
	if (status !== null && typeof status !== 'string') {
		fail('status must be a string or null');
	}
	if (typeof sequence !== 'number' || !Number.isInteger(sequence) || sequence < 0) {
		fail('sequence must be an integer >= 0');
	}
	let statement = '';
	if (goal !== null && goal !== undefined) {
		if (typeof goal !== 'object' || Array.isArray(goal)) {
			fail('goal must be an object or null');
		}
		const text = (goal as Record<string, unknown>)['statement'];
		if (typeof text !== 'string') {
			fail('goal.statement must be a string');
		}
		statement = text;
	}
	let runId: string | null = null;
	let runStatus: string | null = null;
	let runCreatedAt: string | null = null;
	if (run !== null && run !== undefined) {
		if (typeof run !== 'object' || Array.isArray(run)) {
			fail('run must be an object or null');
		}
		const runRecord = run as Record<string, unknown>;
		const run_id = runRecord['run_id'];
		const run_status = runRecord['status'];
		const created_at = runRecord['created_at'];
		if (typeof run_id !== 'string' || run_id.length === 0) {
			fail('run.run_id must be a non-empty string');
		}
		if (run_status !== null && typeof run_status !== 'string') {
			fail('run.status must be a string or null');
		}
		if (created_at !== null && typeof created_at !== 'string') {
			fail('run.created_at must be a string or null');
		}
		runId = run_id;
		runStatus = run_status as string | null;
		runCreatedAt = created_at as string | null;
	}
	let configurationSnapshotId: string | null = null;
	const configurationSnapshot = record['configuration_snapshot'];
	if (configurationSnapshot !== null && configurationSnapshot !== undefined) {
		if (typeof configurationSnapshot !== 'object' || Array.isArray(configurationSnapshot)) {
			fail('configuration_snapshot must be an object or null');
		}
		const snapshotId = (configurationSnapshot as Record<string, unknown>)['snapshot_id'];
		if (typeof snapshotId !== 'string' || snapshotId.length === 0) {
			fail('configuration_snapshot.snapshot_id must be a non-empty string');
		}
		configurationSnapshotId = snapshotId;
	}
	const proposedAction = record['proposed_action'];
	const approvalCard = runStatus === 'WAITING_APPROVAL' && proposedAction !== null && proposedAction !== undefined
		? decodeApprovalCard(proposedAction)
		: null;
	const approval = record['approval'];
	const approvalDecision = approval !== null && approval !== undefined
		? decodeApprovalDecision(approval)
		: null;
	return { taskId: task_id, status: status as string | null, statement, runId, runStatus, runCreatedAt, sequence, configurationSnapshotId, approvalCard, approvalDecision };
}

// --- Slice 2: trajectory (exact-keys closed contract) ---

/**
 * Read-only projection of `GET /v1/tasks/{id}/runs/{run_id}/trajectory`.
 *
 * Exact-keys fail-closed decoding of the TrajectoryProjection contract.
 * Steps inherit their sequence from the per-task event stream after per-run
 * filtering, so gaps are normal: they are preserved as `gapBefore`
 * annotations, never silently dropped. Steps must be strictly increasing and
 * stay within `source_stream_last_sequence`, otherwise the projection is
 * rejected. Unknown event types are rejected.
 */
export interface AgentOSTrajectoryStep {
	readonly stepId: string;
	readonly sequence: number;
	readonly eventType: string;
	readonly occurredAt: string;
	/** Stream events skipped before this step by per-run filtering (0 = continuous). */
	readonly gapBefore: number;
}

export interface AgentOSTaskTrajectory {
	readonly taskId: string;
	readonly runId: string;
	readonly sourceStreamLastSequence: number;
	readonly trajectoryDigest: string;
	readonly steps: readonly AgentOSTrajectoryStep[];
}

/** TaskEventType values from agent_os_contracts.runtime (frozen contract). */
const ALLOWED_EVENT_TYPES: ReadonlySet<string> = new Set([
	'TASK_CREATED', 'TASK_COMMITTED', 'TASK_CONFIGURATION_SNAPSHOT_SEALED',
	'RUN_STARTED', 'RUN_QUEUED', 'NODE_STARTED', 'NODE_COMPLETED', 'NODE_FAILED',
	'ACTION_PROPOSED', 'CANDIDATES_GENERATED', 'PROVIDER_RESPONDED', 'POLICY_DECIDED',
	'ACTION_RECEIPT_RECORDED', 'APPROVAL_REQUESTED', 'APPROVAL_RECORDED',
	'CORRECTION_WRITTEN', 'OUTCOME_OBSERVED', 'ARTIFACT_RECORDED',
	'RUN_PAUSED', 'RUN_RESUMED', 'RUN_CANCELLED', 'RUN_SUCCEEDED', 'RUN_FAILED',
	'WAIT_REGISTERED', 'EXTERNAL_SIGNAL_RECORDED', 'WAIT_SATISFIED', 'WAIT_TIMED_OUT',
	'COMMITMENT_EXPIRED', 'RUN_PLAN_REBOUND',
	'COMPENSATION_STARTED', 'ACTION_COMPENSATED', 'COMPENSATION_FAILED', 'COMPENSATION_BLOCKED',
	'SESSION_TURN_STARTED', 'SESSION_TURN_COMPLETED', 'SESSION_OPENED',
	'SESSION_MESSAGE_RECORDED', 'SESSION_APPROVAL_PENDING',
	'SESSION_APPROVAL_EXECUTION_CLAIMED', 'SESSION_APPROVAL_RESOLVED',
	'SESSION_TURN_CONTINUATION_CHECKPOINT', 'SESSION_CLOSED',
]);

function requireExactKeys(record: Record<string, unknown>, expected: readonly string[], where: string): void {
	const keys = Object.keys(record).sort();
	const wanted = [...expected].sort();
	if (keys.length !== wanted.length || !keys.every((key, i) => key === wanted[i])) {
		fail(`${where} must carry exactly ${wanted.join(', ')}; got ${keys.join(', ')}`);
	}
}

/** ContractModel dumps always carry schema_version; it must stay pinned. */
function requireSchemaVersion(record: Record<string, unknown>, where: string): void {
	if (record['schema_version'] !== '1.0') {
		fail(`${where}.schema_version must be "1.0"; got ${JSON.stringify(record['schema_version'])}`);
	}
}

function requireNonEmptyString(value: unknown, where: string): string {
	if (typeof value !== 'string' || value.length === 0) {
		fail(`${where} must be a non-empty string`);
	}
	return value;
}

export function decodeTaskTrajectory(payload: unknown): AgentOSTaskTrajectory {
	if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
		fail('trajectory payload must be an object');
	}
	const record = payload as Record<string, unknown>;
	requireExactKeys(record, ['manifest', 'steps', 'outcome_links', 'correction_links', 'trajectory_digest', 'schema_version'], 'trajectory root');
	requireSchemaVersion(record, 'trajectory root');
	const { manifest, steps, outcome_links, correction_links, trajectory_digest } = record;
	if (typeof manifest !== 'object' || manifest === null || Array.isArray(manifest)) {
		fail('manifest must be an object');
	}
	const manifestRecord = manifest as Record<string, unknown>;
	requireExactKeys(manifestRecord, [
		'correction_epoch', 'correction_epoch_status', 'episode_id', 'missing_bindings',
		'policy_digest', 'policy_status', 'policy_version', 'run_id', 'schema_version',
		'source_stream_last_sequence', 'task_id', 'tenant_id', 'workflow_digest',
		'workflow_status', 'workspace_id', 'working_set_ref',
	], 'manifest');
	requireSchemaVersion(manifestRecord, 'manifest');
	const taskId = requireNonEmptyString(manifestRecord['task_id'], 'manifest.task_id');
	const runId = requireNonEmptyString(manifestRecord['run_id'], 'manifest.run_id');
	const lastSequence = manifestRecord['source_stream_last_sequence'];
	if (typeof lastSequence !== 'number' || !Number.isInteger(lastSequence) || lastSequence < 1) {
		fail('manifest.source_stream_last_sequence must be an integer >= 1');
	}
	if (!Array.isArray(steps) || steps.length === 0) {
		fail('steps must be a non-empty array');
	}
	if (!Array.isArray(outcome_links) || !Array.isArray(correction_links)) {
		fail('outcome_links and correction_links must be arrays');
	}
	const digest = requireNonEmptyString(trajectory_digest, 'trajectory_digest');
	let previous = 0;
	const decodedSteps: AgentOSTrajectoryStep[] = steps.map((value, index) => {
		if (typeof value !== 'object' || value === null || Array.isArray(value)) {
			fail(`steps[${index}] must be an object`);
		}
		const stepRecord = value as Record<string, unknown>;
		requireExactKeys(stepRecord, [
			'capability_invocation', 'event_digest', 'event_type', 'model_invocation',
			'occurred_at', 'schema_version', 'sequence', 'source_event_id', 'step_id',
		], `steps[${index}]`);
		requireSchemaVersion(stepRecord, `steps[${index}]`);
		const stepId = requireNonEmptyString(stepRecord['step_id'], `steps[${index}].step_id`);
		requireNonEmptyString(stepRecord['source_event_id'], `steps[${index}].source_event_id`);
		requireNonEmptyString(stepRecord['event_digest'], `steps[${index}].event_digest`);
		const occurredAt = requireNonEmptyString(stepRecord['occurred_at'], `steps[${index}].occurred_at`);
		const eventType = requireNonEmptyString(stepRecord['event_type'], `steps[${index}].event_type`);
		if (!ALLOWED_EVENT_TYPES.has(eventType)) {
			fail(`steps[${index}].event_type is unknown: ${eventType}`);
		}
		const sequence = stepRecord['sequence'];
		if (typeof sequence !== 'number' || !Number.isInteger(sequence) || sequence < 1) {
			fail(`steps[${index}].sequence must be an integer >= 1`);
		}
		if (sequence <= previous) {
			fail(`steps[${index}].sequence must be strictly increasing`);
		}
		if (sequence > lastSequence) {
			fail(`steps[${index}].sequence ${sequence} exceeds source_stream_last_sequence ${lastSequence}`);
		}
		const gapBefore = sequence - previous - 1;
		previous = sequence;
		return { stepId, sequence, eventType, occurredAt, gapBefore };
	});
	return { taskId, runId, sourceStreamLastSequence: lastSequence, trajectoryDigest: digest, steps: decodedSteps };
}
