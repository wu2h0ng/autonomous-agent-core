'use client';

import type { components } from '@/lib/api/schema';

type UserResultAnalysis = components['schemas']['UserResultAnalysis'];
type UserResultDecision = components['schemas']['UserResultDecision'];

/* ------------------------------------------------------------------ */
/*  Confidence Badge                                                   */
/* ------------------------------------------------------------------ */

function ConfidenceBadge({ confidence }: { confidence: number }) {
  let colorClasses: string;
  if (confidence > 0.8) {
    colorClasses = 'bg-green-100 text-green-800';
  } else if (confidence > 0.5) {
    colorClasses = 'bg-yellow-100 text-yellow-800';
  } else {
    colorClasses = 'bg-red-100 text-red-800';
  }

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${colorClasses}`}
    >
      {(confidence * 100).toFixed(0)}% confidence
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  UserResultAnalysis                                                 */
/* ------------------------------------------------------------------ */

export function UserResultAnalysisPanel({
  analysis,
}: {
  analysis: UserResultAnalysis | null | undefined;
}) {
  if (!analysis) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
        No analysis data available.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Analysis</h3>
        <ConfidenceBadge confidence={analysis.confidence} />
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="font-medium text-gray-500">Evidence Chain</dt>
        <dd className="truncate font-mono text-xs text-gray-700">
          {analysis.evidence_chain_id}
        </dd>

        <dt className="font-medium text-gray-500">Row Count</dt>
        <dd className="text-gray-900">{analysis.row_count}</dd>
      </dl>

      {analysis.summary && (
        <p className="mt-3 text-sm text-gray-700">{analysis.summary}</p>
      )}

      {analysis.limitations && analysis.limitations.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-gray-500">Limitations</p>
          <ul className="mt-1 list-inside list-disc space-y-0.5 text-xs text-amber-700">
            {analysis.limitations.map((lim, i) => (
              <li key={i}>{lim}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  UserResultDecision                                                 */
/* ------------------------------------------------------------------ */

export function UserResultDecisionPanel({
  decision,
}: {
  decision: UserResultDecision | null | undefined;
}) {
  if (!decision) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
        No decision data available.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Decision</h3>
        <ConfidenceBadge confidence={decision.confidence} />
      </div>

      <div className="space-y-3 text-sm">
        <div>
          <p className="font-medium text-gray-500">Recommendation</p>
          <p className="mt-0.5 text-gray-900">{decision.recommendation}</p>
        </div>

        <div>
          <p className="font-medium text-gray-500">Reason</p>
          <p className="mt-0.5 text-gray-900">{decision.reason}</p>
        </div>

        <div>
          <p className="font-medium text-gray-500">Expected Impact</p>
          <p className="mt-0.5 text-gray-900">{decision.expected_impact}</p>
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
          <dt className="font-medium text-gray-500">Risk Level</dt>
          <dd className="text-gray-900">{decision.risk_level}</dd>

          <dt className="font-medium text-gray-500">Approval Required</dt>
          <dd className="text-gray-900">{decision.approval_required ? 'Yes' : 'No'}</dd>

          {decision.approver_role && (
            <>
              <dt className="font-medium text-gray-500">Approver Role</dt>
              <dd className="text-gray-900">{decision.approver_role}</dd>
            </>
          )}
        </dl>

        {decision.knowledge_context_refs &&
          decision.knowledge_context_refs.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500">
                Knowledge Context References
              </p>
              <ul className="mt-1 flex flex-wrap gap-1">
                {decision.knowledge_context_refs.map((ref, i) => (
                  <li
                    key={i}
                    className="rounded bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-700"
                  >
                    {ref}
                  </li>
                ))}
              </ul>
            </div>
          )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  AnswerPanel — combined view                                        */
/* ------------------------------------------------------------------ */

export function AnswerPanel({
  analysis,
  decision,
  loading,
  error,
}: {
  analysis?: UserResultAnalysis | null;
  decision?: UserResultDecision | null;
  loading?: boolean;
  error?: string | null;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-gray-200 bg-white p-8">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        <span className="ml-2 text-sm text-gray-500">Loading answer...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <UserResultAnalysisPanel analysis={analysis} />
      <UserResultDecisionPanel decision={decision} />
    </div>
  );
}
