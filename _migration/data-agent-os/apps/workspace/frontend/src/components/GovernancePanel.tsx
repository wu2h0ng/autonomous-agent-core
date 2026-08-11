'use client';

import type { components } from '@/lib/api/schema';

type UserResultArtifact = components['schemas']['UserResultArtifact'];
type UserResultRedaction = components['schemas']['UserResultRedaction'];

/* ------------------------------------------------------------------ */
/*  SQL Safety Status                                                  */
/* ------------------------------------------------------------------ */

function SQLSafetyStatus({ artifact }: { artifact: UserResultArtifact }) {
  const sqlCard = artifact.report.evidence_cards.find(
    (c) => c.card_id === 'sql_safety'
  );

  if (!sqlCard || sqlCard.card_id !== 'sql_safety') {
    return (
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 rounded-full bg-gray-300" />
        <span className="text-sm text-gray-500">SQL Safety: not evaluated</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span
        className={`h-2 w-2 rounded-full ${
          sqlCard.sql_safety_allowed ? 'bg-green-500' : 'bg-red-500'
        }`}
      />
      <span className="text-sm text-gray-900">
        SQL Safety:{' '}
        {sqlCard.sql_safety_allowed ? 'Passed' : 'Blocked'}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Redaction Info                                                      */
/* ------------------------------------------------------------------ */

function RedactionInfo({ redaction }: { redaction: UserResultRedaction }) {
  return (
    <div className="rounded bg-gray-50 p-3 text-sm">
      <div className="flex items-center gap-2">
        <span className="font-medium text-gray-500">Audience:</span>
        <span
          className={`rounded px-1.5 py-0.5 text-xs font-semibold ${
            redaction.audience === 'internal'
              ? 'bg-blue-100 text-blue-800'
              : 'bg-purple-100 text-purple-800'
          }`}
        >
          {redaction.audience}
        </span>
      </div>

      <div className="mt-1 flex items-center gap-2">
        <span className="font-medium text-gray-500">Applied:</span>
        <span className="text-gray-900">{redaction.applied ? 'Yes' : 'No'}</span>
      </div>

      <div className="mt-1 flex items-center gap-2">
        <span className="font-medium text-gray-500">Classification:</span>
        <span className="text-gray-900">{redaction.data_classification}</span>
      </div>

      {redaction.redacted_fields.length > 0 && (
        <div className="mt-1 flex items-start gap-2">
          <span className="shrink-0 font-medium text-gray-500">Redacted Fields:</span>
          <span className="text-amber-700">
            {redaction.redacted_fields.join(', ')}
          </span>
        </div>
      )}

      {redaction.reason && (
        <div className="mt-1 flex items-start gap-2">
          <span className="shrink-0 font-medium text-gray-500">Reason:</span>
          <span className="text-gray-700">{redaction.reason}</span>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  GovernancePanel                                                    */
/* ------------------------------------------------------------------ */

export function GovernancePanel({
  artifact,
  knowledgeAssetId,
  knowledgeVersion,
  loading,
  error,
}: {
  artifact: UserResultArtifact | null | undefined;
  knowledgeAssetId?: string | null;
  knowledgeVersion?: number;
  loading?: boolean;
  error?: string | null;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-gray-200 bg-white p-8">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        <span className="ml-2 text-sm text-gray-500">Loading governance info...</span>
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

  if (!artifact) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
        No governance data available.
      </div>
    );
  }

  const hasKnowledgeCandidate = knowledgeAssetId != null;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h3 className="mb-3 text-sm font-semibold text-gray-900">Governance</h3>

      <div className="space-y-3">
        {/* Evidence chain & approval */}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <dt className="font-medium text-gray-500">Evidence Chain</dt>
          <dd className="truncate font-mono text-xs text-gray-700">
            {artifact.evidence_chain_id}
          </dd>

          <dt className="font-medium text-gray-500">Action Proposal</dt>
          <dd className="truncate font-mono text-xs text-gray-700">
            {artifact.action_proposal_id}
          </dd>

          <dt className="font-medium text-gray-500">Trace</dt>
          <dd className="truncate font-mono text-xs text-gray-700">
            {artifact.trace_id}
          </dd>
        </dl>

        {/* SQL Safety */}
        <SQLSafetyStatus artifact={artifact} />

        {/* Redaction */}
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-gray-400">
            Redaction
          </p>
          <RedactionInfo redaction={artifact.redaction} />
        </div>

        {/* Knowledge Asset Candidate */}
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-gray-400">
            Knowledge Asset
          </p>
          {hasKnowledgeCandidate ? (
            <div className="rounded bg-green-50 p-3 text-sm">
              <div className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-green-500" />
                <span className="font-medium text-green-800">
                  Candidate created
                </span>
              </div>
              <p className="mt-1 font-mono text-xs text-green-700">
                {knowledgeAssetId}
              </p>
              {knowledgeVersion != null && (
                <p className="text-xs text-green-600">
                  Version {knowledgeVersion}
                </p>
              )}
            </div>
          ) : (
            <div className="rounded bg-gray-50 p-3 text-sm text-gray-500">
              No knowledge asset candidate for this run.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
