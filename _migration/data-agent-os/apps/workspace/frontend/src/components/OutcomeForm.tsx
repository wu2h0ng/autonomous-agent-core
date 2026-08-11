'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { postOutcome, postAdoption } from '@/lib/api';
import type { components } from '@/lib/api/schema';

type OutcomeResponse = components['schemas']['OutcomeResponse'];
type AdoptionResponse = components['schemas']['AdoptionResponse'];

type SubmissionResult =
  | { kind: 'outcome'; status: 'success' | 'error'; message: string; payload?: OutcomeResponse }
  | { kind: 'adoption'; status: 'success' | 'error'; message: string; payload?: AdoptionResponse };

export function OutcomeForm({ initialTraceId = '' }: { initialTraceId?: string }) {
  const [traceId, setTraceId] = useState(initialTraceId);
  const [outcome, setOutcome] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [metricDeltasJson, setMetricDeltasJson] = useState('');
  const [result, setResult] = useState<SubmissionResult | null>(null);

  const parseMetricDeltas = (): Record<string, number> | undefined => {
    const trimmed = metricDeltasJson.trim();
    if (!trimmed) return undefined;
    const parsed = JSON.parse(trimmed);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('Metric deltas must be a JSON object');
    }
    return parsed as Record<string, number>;
  };

  const outcomeMutation = useMutation({
    mutationFn: () => postOutcome(traceId, outcome, reviewer || undefined, parseMetricDeltas()),
    onSuccess: (payload) => {
      setResult({
        kind: 'outcome',
        status: 'success',
        message: `Outcome recorded: ${payload.feedback_id} (knowledge version ${payload.knowledge_version})`,
        payload,
      });
    },
    onError: (err: Error) => {
      setResult({ kind: 'outcome', status: 'error', message: err.message });
    },
  });

  const adoptionMutation = useMutation({
    mutationFn: () => postAdoption(traceId, outcome, reviewer || undefined, parseMetricDeltas()),
    onSuccess: (payload) => {
      setResult({
        kind: 'adoption',
        status: 'success',
        message: `Adoption attested: ${payload.adoption_id} (knowledge version ${payload.knowledge_version})`,
        payload,
      });
    },
    onError: (err: Error) => {
      setResult({ kind: 'adoption', status: 'error', message: err.message });
    },
  });

  const canSubmit = traceId.trim() && outcome.trim();
  const isPending = outcomeMutation.isPending || adoptionMutation.isPending;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6">
      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700">Trace ID</label>
          <input
            type="text"
            value={traceId}
            onChange={(e) => setTraceId(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="trace-..."
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Outcome</label>
          <textarea
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
            rows={3}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="Describe the observed result"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Reviewer (optional)</label>
          <input
            type="text"
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="ops@example.com"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">
            Metric Deltas JSON (optional)
          </label>
          <textarea
            value={metricDeltasJson}
            onChange={(e) => setMetricDeltasJson(e.target.value)}
            rows={2}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder='{"gmv": 1200.5}'
          />
          <p className="mt-1 text-xs text-gray-400">
            Optional JSON object of metric name to numeric delta.
          </p>
        </div>

        <div className="flex gap-3 pt-2">
          <button
            onClick={() => outcomeMutation.mutate()}
            disabled={!canSubmit || isPending}
            className={`rounded-md px-4 py-2 text-sm font-medium text-white ${
              canSubmit && !isPending
                ? 'bg-blue-600 hover:bg-blue-700'
                : 'bg-gray-400 cursor-not-allowed'
            }`}
          >
            {outcomeMutation.isPending ? 'Recording...' : 'Record Outcome'}
          </button>
          <button
            onClick={() => adoptionMutation.mutate()}
            disabled={!canSubmit || isPending}
            className={`rounded-md px-4 py-2 text-sm font-medium text-white ${
              canSubmit && !isPending
                ? 'bg-green-600 hover:bg-green-700'
                : 'bg-gray-400 cursor-not-allowed'
            }`}
          >
            {adoptionMutation.isPending ? 'Attesting...' : 'Attest Adoption'}
          </button>
        </div>
      </div>

      {result && (
        <div
          className={`mt-6 rounded-lg border p-4 ${
            result.status === 'success'
              ? 'border-green-200 bg-green-50'
              : 'border-red-200 bg-red-50'
          }`}
        >
          <h3
            className={`text-sm font-semibold ${
              result.status === 'success' ? 'text-green-800' : 'text-red-800'
            }`}
          >
            {result.kind === 'outcome' ? 'Outcome' : 'Adoption'}{' '}
            {result.status === 'success' ? 'recorded' : 'failed'}
          </h3>
          <p
            className={`mt-1 text-sm ${
              result.status === 'success' ? 'text-green-700' : 'text-red-700'
            }`}
          >
            {result.message}
          </p>
        </div>
      )}
    </div>
  );
}
