/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import { test } from 'node:test';
import type { decodeTaskCatalog as decodeTaskCatalogType, decodeTaskDetail as decodeTaskDetailType, decodeTaskTrajectory as decodeTaskTrajectoryType } from './runtimeTaskCatalog.js';

// The sibling module is TypeScript; load its real bytes with types stripped so
// the test exercises the exact shipped decoder rather than a copy.
const source = await readFile(new URL('./runtimeTaskCatalog.ts', import.meta.url), 'utf8');
const { decodeTaskCatalog, decodeTaskDetail, decodeTaskTrajectory } = await import(`data:text/javascript;base64,${Buffer.from(stripTypeScriptTypes(source)).toString('base64')}`) as {
	decodeTaskCatalog: typeof decodeTaskCatalogType;
	decodeTaskDetail: typeof decodeTaskDetailType;
	decodeTaskTrajectory: typeof decodeTaskTrajectoryType;
};

test('decodes the exact GET /v1/tasks projection', () => {
	const snapshot = decodeTaskCatalog({
		tasks: [{ task_id: 'task:1', status: 'RUNNING', statement: 'Build the workbench', run_status: 'RUNNING', sequence: 7 }],
	}, 42);
	assert.equal(snapshot.fetchedAt, 42);
	assert.equal(snapshot.tasks[0]?.taskId, 'task:1');
	assert.equal(snapshot.tasks[0]?.runStatus, 'RUNNING');
});

test('fails closed on authority material and malformed shapes', () => {
	assert.throws(() => decodeTaskCatalog({ tasks: [], bearer_token: 'forbidden' } as unknown));
	assert.throws(() => decodeTaskCatalog({ tasks: [{ task_id: '', status: null, statement: 'x', run_status: null, sequence: 0 }] }));
	assert.throws(() => decodeTaskCatalog({ tasks: [{ task_id: 't', status: null, statement: 'x', run_status: null, sequence: -1 }] }));
});

test('detail decoder never projects rich task_json fields', () => {
	const detail = decodeTaskDetail({
		task_id: 'task:1', sequence: 3, status: 'RUNNING',
		goal: { statement: 'detail' },
		run: { run_id: 'run:1', status: 'RUNNING', created_at: '2026-09-10T00:00:00Z' },
		approval: { status: 'PENDING' }, proposed_action: {}, provider: {}, events: [],
	});
	assert.deepEqual(Object.keys(detail).sort(), ['runCreatedAt', 'runId', 'runStatus', 'sequence', 'statement', 'status', 'taskId']);
	assert.equal(detail.runId, 'run:1');
});

test('trajectory decoder enforces monotonic steps within the stream head', () => {
	const step = (sequence: number) => ({
		schema_version: '1.0', step_id: `s${sequence}`, sequence, source_event_id: `e${sequence}`,
		event_type: 'NODE_COMPLETED', event_digest: 'd'.repeat(64), occurred_at: '2026-09-10T00:00:00Z',
		model_invocation: null, capability_invocation: null,
	});
	const manifest = {
		schema_version: '1.0', episode_id: 'ep:1', tenant_id: 't', workspace_id: 'w', task_id: 'task:1', run_id: 'run:1',
		source_stream_last_sequence: 10, workflow_digest: null, workflow_status: 'MISSING', policy_version: null,
		policy_digest: null, policy_status: 'MISSING', working_set_ref: {}, correction_epoch: null,
		correction_epoch_status: 'MISSING', missing_bindings: [],
	};
	const base = { schema_version: '1.0', manifest, outcome_links: [], correction_links: [], trajectory_digest: 'x'.repeat(64) };
	const ok = decodeTaskTrajectory({ ...base, steps: [step(2), step(7)] });
	assert.deepEqual(ok.steps.map(s => s.gapBefore), [1, 4]);
	assert.throws(() => decodeTaskTrajectory({ ...base, steps: [step(7), step(2)] }));
	assert.throws(() => decodeTaskTrajectory({ ...base, steps: [step(11)] }));
});
