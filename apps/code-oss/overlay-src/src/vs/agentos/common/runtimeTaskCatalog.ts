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
	return { taskId: task_id, status: status as string | null, statement, runId, runStatus, runCreatedAt, sequence };
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
