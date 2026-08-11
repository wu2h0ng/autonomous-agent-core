'use client';

import Link from 'next/link';
import type { components } from '@/lib/api/schema';

type UserResultArtifact = components['schemas']['UserResultArtifact'];

export function DataProductCard({ artifact }: { artifact: UserResultArtifact }) {
  const widgetCount = artifact.dashboard?.widgets?.length ?? 0;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">DataProduct Candidate</h3>
        <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-800">
          draft
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="font-medium text-gray-500">Candidate ID</dt>
        <dd className="truncate font-mono text-xs text-gray-700">
          dp-{artifact.metric_name}-{artifact.trace_id.slice(-8)}
        </dd>

        <dt className="font-medium text-gray-500">Contract Spine</dt>
        <dd className="text-gray-900">MetricContract + ProviderContract</dd>

        <dt className="font-medium text-gray-500">Metric</dt>
        <dd className="text-gray-900">{artifact.metric_name}</dd>

        <dt className="font-medium text-gray-500">Dashboard</dt>
        <dd className="text-gray-900">{artifact.dashboard?.title || '—'}</dd>

        <dt className="font-medium text-gray-500">Widgets</dt>
        <dd className="text-gray-900">{widgetCount}</dd>

        <dt className="font-medium text-gray-500">Rows</dt>
        <dd className="text-gray-900">{artifact.analysis.row_count}</dd>

        <dt className="font-medium text-gray-500">Audience</dt>
        <dd className="text-gray-900">{artifact.audience}</dd>

        <dt className="font-medium text-gray-500">Evidence Chain</dt>
        <dd className="truncate font-mono text-xs text-gray-700">{artifact.evidence_chain_id}</dd>
      </dl>

      <div className="mt-3 rounded bg-gray-50 p-3 text-xs text-gray-600">
        Built from {artifact.metric_name}, report snapshot, SQL Safety result, and evidence trace.
      </div>

      <div className="mt-3">
        <Link
          href={`/trace/${artifact.trace_id}`}
          className="text-xs text-blue-600 hover:text-blue-800 font-medium"
        >
          View source trace &rarr;
        </Link>
      </div>
    </div>
  );
}
