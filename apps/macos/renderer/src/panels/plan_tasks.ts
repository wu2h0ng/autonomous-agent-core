// Plan and Tasks panel logic (Wave 2b): closed read-only task projection.

export interface TaskOverview {
  task_id: string;
  task_status: string;
  run_status: string;
  expected_outcome_id: string;
  receipt_count: number;
  session_id: string;
}

export interface OverviewFetchLike {
  (path: string, init?: { method?: string; headers?: Record<string, string> }): Promise<{
    ok: boolean;
    status: number;
    text(): Promise<string>;
  }>;
}

const OVERVIEW_FIELDS = [
  "task_id",
  "task_status",
  "run_status",
  "run_id",
  "expected_outcome_id",
  "receipt_count",
  "session_id",
] as const;

export async function fetchOverview(
  baseUrl: string,
  token: string,
  taskId: string,
  fetchImpl: OverviewFetchLike,
): Promise<TaskOverview> {
  const response = await fetchImpl(
    `${baseUrl}/v1/surface/tasks/${encodeURIComponent(taskId)}/overview`,
    {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Agent-OS-Protocol": "1.0",
      },
    },
  );
  if (!response.ok) {
    throw new Error(`task overview failed: HTTP ${response.status}`);
  }
  const body = JSON.parse(await response.text()) as {
    overview: unknown;
  };
  if (typeof body.overview !== "object" || body.overview === null) {
    throw new Error("task overview returned no overview object");
  }
  const overview = body.overview as Record<string, unknown>;
  for (const field of OVERVIEW_FIELDS) {
    if (typeof overview[field] !== "string" && field !== "receipt_count") {
      throw new Error("task overview returned an invalid field");
    }
  }
  if (typeof overview.receipt_count !== "number") {
    throw new Error("task overview returned an invalid receipt_count");
  }
  for (const key of Object.keys(overview)) {
    if (!OVERVIEW_FIELDS.includes(key as (typeof OVERVIEW_FIELDS)[number])) {
      throw new Error("task overview returned an unexpected field");
    }
  }
  return overview as unknown as TaskOverview;
}
