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
	approval: { approval_id: 'appr:1', status: 'PENDING' },
	proposed_action: { action_digest: 'abc' },
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
	});
	// Output-closed: rich fields present in the input never cross the decoder.
	const keys = Object.keys(detail).sort();
	assert.deepEqual(keys, ['runCreatedAt', 'runId', 'runStatus', 'sequence', 'statement', 'status', 'taskId']);
	const wire = JSON.stringify(detail);
	for (const forbidden of ['approval', 'proposed_action', 'provider', 'events', 'artifacts', 'workspace', 'domain_pack', 'payload']) {
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
	assert.equal(JSON.stringify(runDetail).includes('approval'), false);

	const trajectoryRaw = JSON.parse(await readFile(path.join(fixturesDir, 'task-trajectory.real.json'), 'utf8'));
	const trajectory = decodeTaskTrajectory(trajectoryRaw);
	assert.equal(trajectory.steps.length, 20);
	assert.equal(trajectory.sourceStreamLastSequence, 20);
	assert.equal(trajectory.steps[0].eventType, 'TASK_CREATED');
	assert.ok(trajectory.steps.every(s => s.gapBefore === 0), 'this run consumed the whole stream');
});
