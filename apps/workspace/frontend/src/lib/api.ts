import { useAppStore } from './store';
import type { components } from './api/schema';

type RunResponse = components['schemas']['RunResponse'];
type RunReportResponse = components['schemas']['RunReportResponse'];
type TraceResponse = components['schemas']['TraceResponse'];
type KnowledgeAssetCatalogResponse = components['schemas']['KnowledgeAssetCatalogResponse'];
type KnowledgeAssetDetailResponse = components['schemas']['KnowledgeAssetDetailResponse'];
type OutcomeResponse = components['schemas']['OutcomeResponse'];

function getHeaders(json = false): Record<string, string> {
  const { runKey } = useAppStore.getState();
  const headers: Record<string, string> = {
    'X-Run-Key': runKey,
  };
  if (json) headers['Content-Type'] = 'application/json';
  return headers;
}

async function apiGet<T>(path: string): Promise<T> {
  const { apiUrl } = useAppStore.getState();
  const response = await fetch(`${apiUrl}${path}`, {
    headers: getHeaders(),
  });
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const { apiUrl } = useAppStore.getState();
  const response = await fetch(`${apiUrl}${path}`, {
    method: 'POST',
    headers: getHeaders(true),
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

export async function getReport(traceId: string): Promise<RunReportResponse> {
  return apiGet<RunReportResponse>(`/runs/${traceId}/report`);
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
): Promise<OutcomeResponse> {
  return apiPost<OutcomeResponse>('/outcomes', {
    trace_id: traceId,
    outcome,
    reviewer: reviewer ?? 'workspace-user',
  });
}

export async function postFeedback(
  traceId: string,
  outcome: string,
): Promise<OutcomeResponse> {
  return postOutcome(traceId, outcome);
}
