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
