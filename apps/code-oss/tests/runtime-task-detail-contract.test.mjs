import assert from 'node:assert/strict';
import { stripTypeScriptTypes } from 'node:module';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { test } from 'node:test';
import { repositoryRoot, upstreamRoot } from '../scripts/paths.mjs';

const generatedCatalog = path.join(upstreamRoot, 'src/vs/agentos/common/runtimeTaskCatalog.ts');

async function loadDecoder() {
	const text = await readFile(generatedCatalog, 'utf8');
	return import(`data:text/javascript;base64,${Buffer.from(stripTypeScriptTypes(text)).toString('base64')}`);
}

// --- task detail (whitelist projection over the over-rich task_json) ---

const detailPayload = () => ({
	task_id: 'task:1',
	sequence: 7,
	status: 'RUNNING',
	goal: { goal_id: 'goal:1', statement: 'Build the workbench', created_at: '2026-09-10T00:00:00Z' },
	commitment: null,
	workflow: null,
	run: { run_id: 'run:9', status: 'RUNNING', created_at: '2026-09-10T00:01:00Z' },
	expected_outcome: null,
	configuration_snapshot: null,
	observed_outcome: null,
	historical_observed_outcome: null,
	outcome_evidence_valid: null,
	approval: null,
	proposed_action: null,
	provider: { provider: 'x', usage: { tokens: 1 } },
	workspace: { root: '/tmp' },
	artifacts: [],
	events: [{ event_type: 'TASK_CREATED', payload: { secret: 'raw' } }],
	domain_pack: { id: 'generic' },
});

test('detail decoder projects only the whitelist from task_json', async () => {
	const { decodeTaskDetail } = await loadDecoder();
	const detail = decodeTaskDetail(detailPayload());
	assert.deepEqual(detail, {
		taskId: 'task:1',
		status: 'RUNNING',
		statement: 'Build the workbench',
		runId: 'run:9',
		runStatus: 'RUNNING',
		runCreatedAt: '2026-09-10T00:01:00Z',
		sequence: 7,
		configurationSnapshotId: null,
		approvalCard: null,
		approvalDecision: null,
	});
	// Output-closed: rich fields present in the input never cross the decoder.
	const keys = Object.keys(detail).sort();
	assert.deepEqual(keys, ['approvalCard', 'approvalDecision', 'configurationSnapshotId', 'runCreatedAt', 'runId', 'runStatus', 'sequence', 'statement', 'status', 'taskId']);
	const wire = JSON.stringify(detail);
	for (const forbidden of ['proposed_action', 'provider', 'events', 'artifacts', 'workspace', 'domain_pack', 'payload', 'tenant_id', 'lease_fence']) {
		assert.equal(wire.includes(forbidden), false, `forbidden key leaked: ${forbidden}`);
	}
});

test('detail decoder tolerates null goal and null run', async () => {
	const { decodeTaskDetail } = await loadDecoder();
	const payload = { ...detailPayload(), goal: null, run: null, status: null };
	assert.deepEqual(decodeTaskDetail(payload), {
		taskId: 'task:1',
		status: null,
		statement: '',
		runId: null,
		runStatus: null,
		runCreatedAt: null,
		sequence: 7,
		configurationSnapshotId: null,
		approvalCard: null,
		approvalDecision: null,
	});
});

test('detail decoder rejects malformed identity fields', async () => {
	const { decodeTaskDetail } = await loadDecoder();
	assert.throws(() => decodeTaskDetail(null));
	assert.throws(() => decodeTaskDetail({}));
	assert.throws(() => decodeTaskDetail({ ...detailPayload(), task_id: '' }));
	assert.throws(() => decodeTaskDetail({ ...detailPayload(), task_id: 42 }));
	assert.throws(() => decodeTaskDetail({ ...detailPayload(), sequence: -1 }));
	assert.throws(() => decodeTaskDetail({ ...detailPayload(), goal: { statement: 5 } }));
	assert.throws(() => decodeTaskDetail({ ...detailPayload(), run: { run_id: '', status: null, created_at: null } }));
});

test('detail decoder rejects unknown top-level keys (contract drift alarm)', async () => {
	const { decodeTaskDetail } = await loadDecoder();
	assert.throws(() => decodeTaskDetail({ ...detailPayload(), brand_new_server_field: {} }), /unknown/i);
	assert.throws(() => decodeTaskDetail({ ...detailPayload(), admin: { escalate: true } }), /unknown/i);
	// Every key the real runtime serves today stays accepted.
	const real = JSON.parse(await readFile(new URL('./fixtures/task-detail-run.real.json', import.meta.url), 'utf8'));
	assert.ok(decodeTaskDetail(real).runId);
});

// --- slice 3: approval card projection (whitelist over proposed_action/approval) ---

const proposedActionPayload = () => ({
	schema_version: '1.0',
	action_id: 'action:1',
	task_id: 'task:1',
	run_id: 'run:9',
	node_id: 'apply',
	principal_id: 'user:local',
	tenant_id: 'tenant:local',
	workspace_id: 'workspace:local',
	capability_id: 'workspace.apply_patch',
	capability_version: '1',
	arguments_json: '{"content":"after\\n","path":"fixture.txt"}',
	arguments: { content: 'after\n', path: 'fixture.txt' },
	risk_tier: 2,
	idempotency_key: 'idem:1',
	estimated_budget: { max_cost_usd: '1' },
	policy_version: 'policy-1',
	observed_correction_epochs: { task_epoch: 0 },
	expected_outcome_id: 'expected:1',
	candidate_envelope_id: 'env:1',
	created_at: '2026-09-11T00:00:00Z',
	action_digest: 'a'.repeat(64),
});

const waitingDetailPayload = () => ({
	...detailPayload(),
	run: { run_id: 'run:9', status: 'WAITING_APPROVAL', created_at: '2026-09-10T00:01:00Z', policy_version: 'policy-1' },
	configuration_snapshot: { snapshot_id: 'snap:1', state: 'SEALED' },
	proposed_action: proposedActionPayload(),
});

test('approval card projects only while WAITING_APPROVAL, from the whitelist', async () => {
	const { decodeTaskDetail } = await loadDecoder();
	const detail = decodeTaskDetail(waitingDetailPayload());
	assert.equal(detail.runStatus, 'WAITING_APPROVAL');
	assert.equal(detail.configurationSnapshotId, 'snap:1');
	assert.equal(detail.approvalDecision, null);
	assert.deepEqual(detail.approvalCard, {
		capabilityId: 'workspace.apply_patch',
		capabilityVersion: '1',
		riskTier: 2,
		actionDigest: 'a'.repeat(64),
		policyVersion: 'policy-1',
		principalId: 'user:local',
		runId: 'run:9',
		nodeId: 'apply',
		argumentsPreview: JSON.stringify({ content: 'after\n', path: 'fixture.txt' }, null, 2),
		argumentsTruncated: false,
	});
	// Forbidden authority/budget fields never cross into the card.
	const wire = JSON.stringify(detail.approvalCard);
	for (const forbidden of ['tenant_id', 'workspace_id', 'idempotency_key', 'estimated_budget', 'observed_correction_epochs', 'expected_outcome_id', 'candidate_envelope_id', 'arguments_json', 'schema_version', 'approval_requirement', 'lease_fence']) {
		assert.equal(wire.includes(forbidden), false, `forbidden card key leaked: ${forbidden}`);
	}
	// Not waiting → no card, even if the server still serves proposed_action.
	const running = decodeTaskDetail({ ...waitingDetailPayload(), run: { run_id: 'run:9', status: 'RUNNING', created_at: '2026-09-10T00:01:00Z' } });
	assert.equal(running.approvalCard, null);
	assert.equal(running.configurationSnapshotId, 'snap:1');
});

test('approval card decoding fails closed on malformed proposed_action', async () => {
	const { decodeTaskDetail } = await loadDecoder();
	const bad = (mutate) => {
		const payload = waitingDetailPayload();
		payload.proposed_action = mutate(proposedActionPayload());
		return payload;
	};
	// Contract drift: unknown key inside proposed_action.
	assert.throws(() => decodeTaskDetail(bad(p => ({ ...p, brand_new: true }))), /unknown/i);
	// Missing required card fields.
	assert.throws(() => decodeTaskDetail(bad(({ action_digest, ...rest }) => rest)), /action_digest/);
	assert.throws(() => decodeTaskDetail(bad(({ arguments: _, ...rest }) => rest)), /arguments/);
	// Malformed digest / risk tier / arguments.
	assert.throws(() => decodeTaskDetail(bad(p => ({ ...p, action_digest: 'abc' }))), /digest/);
	assert.throws(() => decodeTaskDetail(bad(p => ({ ...p, risk_tier: 'high' }))), /risk_tier/);
	assert.throws(() => decodeTaskDetail(bad(p => ({ ...p, arguments: 'not-an-object' }))), /arguments/);
	// Waiting run without any proposed action: no card, not a crash.
	const noAction = waitingDetailPayload();
	noAction.proposed_action = null;
	assert.equal(decodeTaskDetail(noAction).approvalCard, null);
});

test('approval decision projection converges the card after a decision', async () => {
	const { decodeTaskDetail } = await loadDecoder();
	const approval = {
		schema_version: '1.0',
		approval_id: 'approval:1',
		tenant_id: 'tenant:local',
		workspace_id: 'workspace:local',
		action_digest: 'a'.repeat(64),
		actor_id: 'user:local',
		actor_role: 'PRINCIPAL',
		disposition: 'APPROVE',
		reason: 'reviewed',
		decided_at: '2026-09-11T00:05:00Z',
		expires_at: '2026-09-11T00:15:00Z',
	};
	const detail = decodeTaskDetail({ ...waitingDetailPayload(), approval });
	assert.deepEqual(detail.approvalDecision, {
		disposition: 'APPROVE',
		reason: 'reviewed',
		actionDigest: 'a'.repeat(64),
		actorId: 'user:local',
		decidedAt: '2026-09-11T00:05:00Z',
		expiresAt: '2026-09-11T00:15:00Z',
	});
	// Decision wire never carries authority internals.
	const wire = JSON.stringify(detail.approvalDecision);
	for (const forbidden of ['tenant_id', 'workspace_id', 'actor_role', 'approval_id', 'schema_version']) {
		assert.equal(wire.includes(forbidden), false, `forbidden decision key leaked: ${forbidden}`);
	}
	// Malformed decisions fail closed.
	assert.throws(() => decodeTaskDetail({ ...waitingDetailPayload(), approval: { ...approval, disposition: 'MAYBE' } }), /disposition/);
	assert.throws(() => decodeTaskDetail({ ...waitingDetailPayload(), approval: { ...approval, extra: 1 } }), /unknown/i);
});

test('approval card arguments preview is bounded', async () => {
	const { decodeTaskDetail } = await loadDecoder();
	const huge = waitingDetailPayload();
	huge.proposed_action = {
		...proposedActionPayload(),
		arguments: { content: 'x'.repeat(8192), path: 'fixture.txt' },
	};
	const detail = decodeTaskDetail(huge);
	assert.equal(detail.approvalCard.argumentsTruncated, true);
	assert.ok(detail.approvalCard.argumentsPreview.length <= 4200, 'preview must be bounded');
});

// --- trajectory (exact-keys closed contract) ---

const trajectoryPayload = (steps) => ({
	schema_version: '1.0',
	manifest: {
		schema_version: '1.0',
		episode_id: 'ep:1',
		tenant_id: 'tenant:e2e',
		workspace_id: 'workspace:e2e',
		task_id: 'task:1',
		run_id: 'run:9',
		source_stream_last_sequence: 10,
		workflow_digest: null,
		workflow_status: 'MISSING',
		policy_version: null,
		policy_digest: null,
		policy_status: 'MISSING',
		working_set_ref: { head_digest: 'a'.repeat(64), entry_digests: [] },
		correction_epoch: null,
		correction_epoch_status: 'MISSING',
		missing_bindings: [],
	},
	steps,
	outcome_links: [],
	correction_links: [],
	trajectory_digest: 'b'.repeat(64),
});

const step = (sequence, eventType = 'NODE_COMPLETED') => ({
	schema_version: '1.0',
	step_id: `step:${sequence}:evt`,
	sequence,
	source_event_id: `evt:${sequence}`,
	event_type: eventType,
	event_digest: 'c'.repeat(64),
	occurred_at: '2026-09-10T00:02:00Z',
	model_invocation: null,
	capability_invocation: null,
});

test('trajectory decoder maps steps and annotates run-filter gaps', async () => {
	const { decodeTaskTrajectory } = await loadDecoder();
	// Sequences 2, 5, 10: gaps are the norm after per-run filtering.
	const trajectory = decodeTaskTrajectory(trajectoryPayload([step(2, 'TASK_CREATED'), step(5), step(10, 'RUN_SUCCEEDED')]));
	assert.equal(trajectory.taskId, 'task:1');
	assert.equal(trajectory.runId, 'run:9');
	assert.equal(trajectory.sourceStreamLastSequence, 10);
	assert.equal(trajectory.trajectoryDigest, 'b'.repeat(64));
	assert.deepEqual(
		trajectory.steps.map(s => [s.sequence, s.eventType, s.gapBefore]),
		[[2, 'TASK_CREATED', 1], [5, 'NODE_COMPLETED', 2], [10, 'RUN_SUCCEEDED', 4]],
	);
});

test('trajectory decoder rejects non-monotonic or out-of-stream sequences', async () => {
	const { decodeTaskTrajectory } = await loadDecoder();
	assert.throws(() => decodeTaskTrajectory(trajectoryPayload([step(5), step(2)])), /increasing/);
	assert.throws(() => decodeTaskTrajectory(trajectoryPayload([step(2), step(2)])), /increasing/);
	// Beyond the stream head the projection cannot be trusted.
	assert.throws(() => decodeTaskTrajectory(trajectoryPayload([step(11)])), /source_stream_last_sequence|stream/);
	assert.throws(() => decodeTaskTrajectory(trajectoryPayload([step(0)])), /sequence/);
});

test('trajectory decoder rejects unknown event types and closed-shape violations', async () => {
	const { decodeTaskTrajectory } = await loadDecoder();
	assert.throws(() => decodeTaskTrajectory(trajectoryPayload([step(1, 'TOTALLY_UNKNOWN')])), /event_type|unknown/i);
	// Root must be exactly the TrajectoryProjection shape.
	const extra = { ...trajectoryPayload([step(1)]), bearer_token: 'forbidden' };
	assert.throws(() => decodeTaskTrajectory(extra));
	assert.throws(() => decodeTaskTrajectory({}));
	assert.throws(() => decodeTaskTrajectory(trajectoryPayload([])), /steps/);
	const badStep = { ...step(1), extra_key: true };
	assert.throws(() => decodeTaskTrajectory(trajectoryPayload([badStep])));
	const badManifest = trajectoryPayload([step(1)]);
	badManifest.manifest = { ...badManifest.manifest, admin: true };
	assert.throws(() => decodeTaskTrajectory(badManifest));
});

// --- real runtime fixtures (captured 2026-09-10, sanitized, no secrets) ---

test('decoders accept real runtime responses', async () => {
	const { decodeTaskDetail, decodeTaskTrajectory } = await loadDecoder();
	const fixturesDir = path.join(repositoryRoot, 'apps', 'code-oss', 'tests', 'fixtures');
	const detailRaw = JSON.parse(await readFile(path.join(fixturesDir, 'task-detail.real.json'), 'utf8'));
	const draftDetail = decodeTaskDetail(detailRaw);
	assert.equal(draftDetail.runId, null); // freshly POSTed task, never run

	const runDetailRaw = JSON.parse(await readFile(path.join(fixturesDir, 'task-detail-run.real.json'), 'utf8'));
	const runDetail = decodeTaskDetail(runDetailRaw);
	assert.ok(runDetail.runId, 'run-bearing detail must expose run_id');
	assert.equal(runDetail.statement, 'inspect fixture');
	assert.equal(JSON.stringify(runDetail).includes('proposed_action'), false);

	// Slice 3 real fixtures: parked approval and recorded decision.
	const waitingRaw = JSON.parse(await readFile(path.join(fixturesDir, 'task-detail-waiting-approval.real.json'), 'utf8'));
	const waiting = decodeTaskDetail(waitingRaw);
	assert.equal(waiting.runStatus, 'WAITING_APPROVAL');
	assert.ok(waiting.approvalCard, 'parked run must project an approval card');
	assert.equal(waiting.approvalCard.capabilityId, 'workspace.apply_patch');
	assert.match(waiting.approvalCard.actionDigest, /^[0-9a-f]{64}$/);
	assert.ok(waiting.configurationSnapshotId, 'parked run must expose the sealed snapshot id');

	const approvedRaw = JSON.parse(await readFile(path.join(fixturesDir, 'task-detail-approved.real.json'), 'utf8'));
	const approved = decodeTaskDetail(approvedRaw);
	assert.equal(approved.approvalDecision?.disposition, 'APPROVE');
	assert.equal(approved.approvalDecision?.actionDigest, approved.approvalCard?.actionDigest, 'decision digest must equal the card digest');

	const trajectoryRaw = JSON.parse(await readFile(path.join(fixturesDir, 'task-trajectory.real.json'), 'utf8'));
	const trajectory = decodeTaskTrajectory(trajectoryRaw);
	assert.equal(trajectory.steps.length, 20);
	assert.equal(trajectory.sourceStreamLastSequence, 20);
	assert.equal(trajectory.steps[0].eventType, 'TASK_CREATED');
	assert.ok(trajectory.steps.every(s => s.gapBefore === 0), 'this run consumed the whole stream');
});
