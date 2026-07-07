import { useAppStore } from './store';
import type { components } from './api/schema';

type RunResponse = components['schemas']['RunResponse'];
type RunReportResponse = components['schemas']['RunReportResponse'];
type TraceResponse = components['schemas']['TraceResponse'];
type KnowledgeAssetCatalogResponse = components['schemas']['KnowledgeAssetCatalogResponse'];
type KnowledgeAssetDetailResponse = components['schemas']['KnowledgeAssetDetailResponse'];
type OutcomeResponse = components['schemas']['OutcomeResponse'];
type AdoptionResponse = components['schemas']['AdoptionResponse'];
type ApprovalListResponse = components['schemas']['ApprovalListResponse'];
type ApprovalListItem = components['schemas']['ApprovalListItem'];
type ApprovalExecuteResponse = components['schemas']['ApprovalExecuteResponse'];
type NLBuildResponse = components['schemas']['NLBuildResponse'];
type DashboardCreateCard = components['schemas']['DashboardCreateCard'];
type DashboardResponse = components['schemas']['DashboardResponse'];
type DashboardListResponse = components['schemas']['DashboardListResponse'];
type SearchResponse = components['schemas']['SearchResponse'];

// The /metrics endpoint does not declare a response_model in the OpenAPI spec,
// so its generated type is `unknown`. We define the concrete contract here.
export type MetricCatalogItem = {
  metric_name: string;
  display_name: string;
  definition: string;
  unit: string;
  dimensions: string[];
  aliases: string[];
};

export type MetricCatalogResponse = {
  items: MetricCatalogItem[];
  total: number;
};

function getHeaders(
  json = false,
  operator = false,
  operatorKeyOverride?: string,
): Record<string, string> {
  const { apiKey, operatorKey, tenantId } = useAppStore.getState();
  const headers: Record<string, string> = {
    'X-API-Key': apiKey,
  };
  const effectiveOperatorKey = operatorKeyOverride ?? operatorKey;
  if (operator && effectiveOperatorKey) headers['X-Operator-Key'] = effectiveOperatorKey;
  if (tenantId) headers['X-Tenant-Id'] = tenantId;
  if (json) headers['Content-Type'] = 'application/json';
  return headers;
}

function getApiUrl(): string {
  return (
    process.env.NEXT_PUBLIC_API_URL ||
    useAppStore.getState().apiUrl ||
    'http://localhost:8000'
  );
}

async function apiGet<T>(path: string, operator = false, operatorKey?: string): Promise<T> {
  const response = await fetch(`${getApiUrl()}${path}`, {
    headers: getHeaders(false, operator, operatorKey),
  });
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function apiPost<T>(
  path: string,
  body: unknown,
  operator = false,
  operatorKey?: string,
): Promise<T> {
  const response = await fetch(`${getApiUrl()}${path}`, {
    method: 'POST',
    headers: getHeaders(true, operator, operatorKey),
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export async function postRun(
  question: string,
  audience: 'internal' | 'external' = 'internal',
): Promise<RunResponse> {
  return apiPost<RunResponse>('/runs', {
    question,
    parameters: {},
    audience,
  });
}

export async function runQuestion(
  question: string,
  audience: 'internal' | 'external' = 'internal',
): Promise<RunResponse> {
  return postRun(question, audience);
}

export async function getReport(
  traceId: string,
  audience?: 'internal' | 'external',
): Promise<RunReportResponse> {
  const qs = audience ? `?audience=${encodeURIComponent(audience)}` : '';
  return apiGet<RunReportResponse>(`/runs/${encodeURIComponent(traceId)}/report${qs}`);
}

export async function getTrace(traceId: string): Promise<TraceResponse> {
  return apiGet<TraceResponse>(`/traces/${traceId}`);
}

export async function getKnowledgeAssets(params?: {
  state?: string;
  quality_status?: string;
  review_priority?: string;
  limit?: number;
  offset?: number;
}): Promise<KnowledgeAssetCatalogResponse> {
  const query = new URLSearchParams();
  if (params?.state) query.set('state', params.state);
  if (params?.quality_status) query.set('quality_status', params.quality_status);
  if (params?.review_priority) query.set('review_priority', params.review_priority);
  if (params?.limit != null) query.set('limit', String(params.limit));
  if (params?.offset != null) query.set('offset', String(params.offset));
  const qs = query.toString();
  return apiGet<KnowledgeAssetCatalogResponse>(
    `/knowledge/assets${qs ? `?${qs}` : ''}`,
  );
}

export async function getKnowledgeAssetDetail(
  assetId: string,
): Promise<KnowledgeAssetDetailResponse> {
  return apiGet<KnowledgeAssetDetailResponse>(`/knowledge/assets/${assetId}`);
}

export async function postOutcome(
  traceId: string,
  outcome: string,
  reviewer?: string,
  metricDeltas?: Record<string, number>,
): Promise<OutcomeResponse> {
  return apiPost<OutcomeResponse>('/outcomes', {
    trace_id: traceId,
    outcome,
    reviewer: reviewer ?? 'workspace-user',
    metric_deltas: metricDeltas ?? null,
  });
}

export async function recordOutcome(
  traceId: string,
  outcome: string,
  metricDeltas?: Record<string, number>,
): Promise<OutcomeResponse> {
  return postOutcome(traceId, outcome, 'workspace-user', metricDeltas);
}

export async function postFeedback(
  traceId: string,
  outcome: string,
): Promise<OutcomeResponse> {
  return postOutcome(traceId, outcome);
}

export async function postAdoption(
  traceId: string,
  outcome: string,
  reviewer?: string,
  metricDeltas?: Record<string, number>,
): Promise<AdoptionResponse> {
  return apiPost<AdoptionResponse>('/adoptions', {
    trace_id: traceId,
    outcome,
    reviewer: reviewer ?? 'workspace-user',
    metric_deltas: metricDeltas ?? null,
  });
}

export async function recordAdoption(
  traceId: string,
  metricDeltas?: Record<string, number>,
): Promise<AdoptionResponse> {
  return postAdoption(traceId, 'adopted via workspace', 'workspace-user', metricDeltas);
}

export async function getApprovals(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<ApprovalListResponse> {
  const query = new URLSearchParams();
  if (params?.status) query.set('status', params.status);
  if (params?.limit != null) query.set('limit', String(params.limit));
  if (params?.offset != null) query.set('offset', String(params.offset));
  const qs = query.toString();
  return apiGet<ApprovalListResponse>(`/approvals${qs ? `?${qs}` : ''}`);
}

export async function listApprovals(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<ApprovalListResponse> {
  return getApprovals(params);
}

export async function getApproval(approvalId: string): Promise<ApprovalListItem> {
  return apiGet<ApprovalListItem>(`/approvals/${encodeURIComponent(approvalId)}`);
}

export async function executeApproval(
  approvalId: string,
  operatorKey: string,
  reason?: string,
): Promise<ApprovalExecuteResponse> {
  return apiPost<ApprovalExecuteResponse>(
    `/approvals/${encodeURIComponent(approvalId)}/execute`,
    { reason: reason || 'Executed via workspace UI', approved_by: operatorKey },
    true,
    operatorKey,
  );
}

export async function searchKnowledge(
  query: string,
  options?: { k?: number; metric?: string; owner?: string },
): Promise<SearchResponse> {
  const params = new URLSearchParams();
  params.set('q', query);
  if (options?.k != null) params.set('k', String(options.k));
  if (options?.metric) params.set('metric', options.metric);
  if (options?.owner) params.set('owner', options.owner);
  return apiGet<SearchResponse>(`/knowledge/search?${params.toString()}`);
}

export async function postNlBuild(question: string): Promise<NLBuildResponse> {
  return apiPost<NLBuildResponse>('/nl-build', {
    question,
    parameters: {},
  });
}

export async function getMetrics(params?: {
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<MetricCatalogResponse> {
  const query = new URLSearchParams();
  if (params?.q) query.set('q', params.q);
  if (params?.limit != null) query.set('limit', String(params.limit));
  if (params?.offset != null) query.set('offset', String(params.offset));
  const qs = query.toString();
  return apiGet<MetricCatalogResponse>(`/metrics${qs ? `?${qs}` : ''}`);
}

export async function postDashboard(
  title: string,
  cards: DashboardCreateCard[],
): Promise<DashboardResponse> {
  return apiPost<DashboardResponse>('/dashboards', {
    title,
    cards,
  });
}

export async function getDashboard(dashboardId: string): Promise<DashboardResponse> {
  return apiGet<DashboardResponse>(`/dashboards/${dashboardId}`);
}

export async function getDashboards(params?: {
  limit?: number;
  offset?: number;
}): Promise<DashboardListResponse> {
  const query = new URLSearchParams();
  if (params?.limit != null) query.set('limit', String(params.limit));
  if (params?.offset != null) query.set('offset', String(params.offset));
  const qs = query.toString();
  return apiGet<DashboardListResponse>(`/dashboards${qs ? `?${qs}` : ''}`);
}
