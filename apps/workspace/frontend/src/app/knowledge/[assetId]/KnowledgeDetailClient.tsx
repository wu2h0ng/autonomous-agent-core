'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { getKnowledgeAssetDetail } from '@/lib/api';

interface KnowledgeDetailClientProps {
  assetId: string;
}

export function KnowledgeDetailClient({ assetId }: KnowledgeDetailClientProps) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['knowledge-asset', assetId],
    queryFn: () => getKnowledgeAssetDetail(assetId),
  });

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      {/* Header */}
      <div className="mb-6">
        <Link
          href="/knowledge"
          className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 mb-4"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            className="h-4 w-4"
          >
            <path
              fillRule="evenodd"
              d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z"
              clipRule="evenodd"
            />
          </svg>
          Back to Knowledge
        </Link>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="animate-pulse space-y-4">
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <div className="h-6 bg-gray-200 rounded w-2/3 mb-4" />
            <div className="h-4 bg-gray-200 rounded w-1/3 mb-6" />
            <div className="space-y-3">
              <div className="h-4 bg-gray-200 rounded w-full" />
              <div className="h-4 bg-gray-200 rounded w-3/4" />
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6">
          <h3 className="text-sm font-semibold text-red-800">Failed to load asset</h3>
          <p className="mt-1 text-sm text-red-700">
            {error instanceof Error ? error.message : 'Unknown error'}
          </p>
        </div>
      )}

      {/* Success */}
      {data && (
        <div className="space-y-6">
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <div className="flex items-start justify-between mb-4">
              <div>
                <h1 className="text-xl font-bold text-gray-900">{data.title}</h1>
                <p className="text-sm text-gray-500 mt-1 font-mono">{data.asset_id}</p>
              </div>
              <div className="flex gap-2">
                <span className="inline-flex items-center rounded-full bg-gray-50 px-2.5 py-0.5 text-xs font-medium text-gray-700 ring-1 ring-gray-600/20">
                  {data.state}
                </span>
              </div>
            </div>

            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              <InfoItem label="Asset Type" value={data.asset_type} />
              <InfoItem label="Owner" value={data.owner} />
              <InfoItem label="Knowledge Version" value={String(data.knowledge_version)} />
              <InfoItem label="Result Weight" value={data.result_weight.toFixed(3)} />
              <InfoItem label="Quality Status" value={data.quality_status.replace(/_/g, ' ')} />
              <InfoItem
                label="Review Priority"
                value={data.review_priority}
              />
              <InfoItem label="Lifecycle Events" value={String(data.lifecycle_event_count)} />
              <InfoItem
                label="Distinct Usage Traces"
                value={String(data.distinct_usage_trace_count)}
              />
              <InfoItem
                label="Adoption Corrections"
                value={String(data.adoption_correction_count)}
              />
            </div>
          </div>

          {/* Outcome */}
          {data.outcome && (
            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
                Outcome
              </h3>
              <p className="text-sm text-gray-700">{data.outcome}</p>
            </div>
          )}

          {/* Review Rationale */}
          {data.review_rationale_codes.length > 0 && (
            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
                Review Rationale
              </h3>
              <div className="flex flex-wrap gap-2">
                {data.review_rationale_codes.map((code) => (
                  <span
                    key={code}
                    className="inline-flex items-center rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 ring-1 ring-indigo-600/20"
                  >
                    {code.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Source trace link */}
          {data.source_trace_id && (
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <Link
                href={`/trace/${data.source_trace_id}`}
                className="text-sm text-blue-600 hover:text-blue-800 font-medium"
              >
                View source trace &rarr;
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-gray-500 mb-0.5">{label}</p>
      <p className="text-sm font-medium text-gray-900">{value}</p>
    </div>
  );
}
