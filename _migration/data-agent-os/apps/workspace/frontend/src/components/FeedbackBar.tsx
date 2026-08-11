'use client';

import { useState, useCallback } from 'react';
import type { components } from '@/lib/api/schema';

type OutcomeRequest = components['schemas']['OutcomeRequest'];
type OutcomeResponse = components['schemas']['OutcomeResponse'];

type FeedbackOutcome = 'useful' | 'inaccurate' | 'needs_review';

interface FeedbackBarProps {
  traceId: string;
  /** Base API URL (e.g. "http://localhost:8000"). Falls back to store apiUrl. */
  apiUrl?: string;
  /** Optional API key header value. */
  apiKey?: string;
  /** Called after successful submission. */
  onSuccess?: (response: OutcomeResponse) => void;
  /** Called when submission fails. */
  onError?: (error: string) => void;
}

const FEEDBACK_OPTIONS: { value: FeedbackOutcome; label: string; color: string }[] = [
  { value: 'useful', label: 'Useful', color: 'bg-green-600 hover:bg-green-700 focus:ring-green-500' },
  { value: 'inaccurate', label: 'Inaccurate', color: 'bg-red-600 hover:bg-red-700 focus:ring-red-500' },
  { value: 'needs_review', label: 'Needs review', color: 'bg-amber-600 hover:bg-amber-700 focus:ring-amber-500' },
];

export function FeedbackBar({
  traceId,
  apiUrl,
  apiKey,
  onSuccess,
  onError,
}: FeedbackBarProps) {
  const [selected, setSelected] = useState<FeedbackOutcome | null>(null);
  const [gapNote, setGapNote] = useState('');
  const [showGapNote, setShowGapNote] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const handleSelect = useCallback(
    (outcome: FeedbackOutcome) => {
      if (submitted) return;
      setSelected(outcome);
      setShowGapNote(true);
      setSubmitError(null);
    },
    [submitted]
  );

  const handleSubmit = useCallback(async () => {
    if (!selected) return;

    setSubmitting(true);
    setSubmitError(null);

    const body: OutcomeRequest = {
      trace_id: traceId,
      outcome: selected,
      reviewer: 'workspace-user',
      metric_deltas: gapNote ? { gap_note: gapNote } : undefined,
    };

    // Resolve base URL: prop > dynamic import of store > relative
    let base = apiUrl ?? '';
    if (!base) {
      try {
        const { useAppStore } = await import('@/lib/store');
        base = useAppStore.getState().apiUrl;
      } catch {
        base = '';
      }
    }

    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      };
      if (apiKey) {
        headers['X-API-Key'] = apiKey;
      }

      const response = await fetch(`${base}/outcomes`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        throw new Error(`Failed to submit feedback: ${response.status} ${response.statusText}`);
      }

      const data: OutcomeResponse = await response.json();
      setSubmitted(true);
      onSuccess?.(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setSubmitError(message);
      onError?.(message);
    } finally {
      setSubmitting(false);
    }
  }, [selected, traceId, apiUrl, apiKey, gapNote, onSuccess, onError]);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h3 className="mb-3 text-sm font-semibold text-gray-900">Feedback</h3>

      {/* Feedback buttons */}
      <div className="flex flex-wrap gap-2">
        {FEEDBACK_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => handleSelect(option.value)}
            disabled={submitted || submitting}
            className={`rounded-md px-4 py-2 text-sm font-medium text-white shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${
              selected === option.value
                ? `${option.color} ring-2 ring-offset-2`
                : option.color
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      {/* Gap note textarea */}
      {showGapNote && selected && !submitted && (
        <div className="mt-3">
          <label
            htmlFor="gap-note"
            className="mb-1 block text-xs font-medium text-gray-500"
          >
            Additional notes (optional)
          </label>
          <textarea
            id="gap-note"
            value={gapNote}
            onChange={(e) => setGapNote(e.target.value)}
            placeholder="Describe any gaps, inaccuracies, or suggestions..."
            rows={3}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              onClick={handleSubmit}
              disabled={submitting}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? 'Submitting...' : 'Submit Feedback'}
            </button>
          </div>
        </div>
      )}

      {/* Error */}
      {submitError && (
        <p className="mt-2 text-sm text-red-600">{submitError}</p>
      )}

      {/* Success */}
      {submitted && (
        <div className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">
          Feedback submitted. Thank you.
        </div>
      )}
    </div>
  );
}
