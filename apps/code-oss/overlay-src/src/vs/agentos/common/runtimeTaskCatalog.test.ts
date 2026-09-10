/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { decodeTaskCatalog } from './runtimeTaskCatalog.js';

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
