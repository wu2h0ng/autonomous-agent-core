'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { getKnowledgeAssets } from '@/lib/api';

const STATE_OPTIONS = [
  { value: '', label: 'All States' },
  { value: 'draft', label: 'Draft' },
  { value: 'active', label: 'Active' },
  { value: 'published', label: 'Published' },
  { value: 'deprecated', label: 'Deprecated' },
];

const QUALITY_STATUS_OPTIONS = [
  { value: '', label: 'All Quality' },
  { value: 'unused', label: 'Unused' },
  { value: 'proposal_only', label: 'Proposal Only' },
  { value: 'outcome_observed', label: 'Outcome Observed' },
  { value: 'adoption_observed', label: 'Adoption Observed' },
];

const REVIEW_PRIORITY_OPTIONS = [
  { value: '', label: 'All Priorities' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
];

export default function KnowledgePage() {
  const [stateFilter, setStateFilter] = useState('');
  const [qualityFilter, setQualityFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['knowledge', stateFilter, qualityFilter, priorityFilter],
    queryFn: () =>
      getKnowledgeAssets({
        state: stateFilter || undefined,
        quality_status: qualityFilter || undefined,
        review_priority: priorityFilter || undefined,
        limit: 50,
      }),
  });

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Knowledge Assets</h1>
        <p className="text-sm text-gray-500 mt-1">
          Browse and manage organizational knowledge assets generated from query runs.
        </p>
      </div>

      {/* Filters */}
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <select
          value={stateFilter}
          onChange={(e) => setStateFilter(e.target.value)}
          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          {STATE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <select
          value={qualityFilter}
          onChange={(e) => setQualityFilter(e.target.value)}
          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          {QUALITY_STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <select
          value={priorityFilter}
          onChange={(e) => setPriorityFilter(e.target.value)}
          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          {REVIEW_PRIORITY_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        {data && (
          <span className="text-xs text-gray-400 ml-auto">
            {data.count} of {data.total_count} assets
          </span>
        )}
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="animate-pulse space-y-0">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 border-b border-gray-100 p-4">
                <div className="h-4 bg-gray-200 rounded w-24" />
                <div className="h-4 bg-gray-200 rounded flex-1" />
                <div className="h-4 bg-gray-200 rounded w-16" />
                <div className="h-4 bg-gray-200 rounded w-20" />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6">
          <h3 className="text-sm font-semibold text-red-800">Failed to load knowledge assets</h3>
          <p className="mt-1 text-sm text-red-700">
            {error instanceof Error ? error.message : 'Unknown error'}
          </p>
        </div>
      )}

      {/* Table */}
      {data && data.items && data.items.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Asset ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Title
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    State
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Quality
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Priority
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Weight
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Owner
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.items.map((asset) => (
                  <tr key={asset.asset_id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <Link
                        href={`/knowledge/${asset.asset_id}`}
                        className="text-sm font-mono text-blue-600 hover:text-blue-800"
                      >
                        {asset.asset_id.slice(0, 12)}...
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-sm text-gray-900">{asset.title}</span>
                    </td>
                    <td className="px-4 py-3">
                      <StateBadge state={asset.state} />
                    </td>
                    <td className="px-4 py-3">
                      <QualityBadge status={asset.quality_status} />
                    </td>
                    <td className="px-4 py-3">
                      <PriorityBadge priority={asset.review_priority} />
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-sm text-gray-700">
                        {asset.result_weight.toFixed(2)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-sm text-gray-600">{asset.owner}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {data && (!data.items || data.items.length === 0) && (
        <div className="rounded-lg border border-dashed border-gray-300 bg-white p-12 text-center">
          <p className="text-lg font-medium text-gray-500 mb-1">No knowledge assets found</p>
          <p className="text-sm text-gray-400">
            Knowledge assets are created when query results are adopted.
            Try adjusting the filters or running more queries.
          </p>
        </div>
      )}
    </div>
  );
}

function StateBadge({ state }: { state: string }) {
  const colors: Record<string, string> = {
    draft: 'bg-gray-50 text-gray-700 ring-gray-600/20',
    active: 'bg-green-50 text-green-700 ring-green-600/20',
    published: 'bg-blue-50 text-blue-700 ring-blue-600/20',
    deprecated: 'bg-red-50 text-red-700 ring-red-600/20',
  };
  const cls = colors[state] ?? 'bg-gray-50 text-gray-700 ring-gray-600/20';
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${cls}`}>
      {state}
    </span>
  );
}

function QualityBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    unused: 'bg-gray-50 text-gray-600 ring-gray-500/20',
    proposal_only: 'bg-yellow-50 text-yellow-700 ring-yellow-600/20',
    outcome_observed: 'bg-blue-50 text-blue-700 ring-blue-600/20',
    adoption_observed: 'bg-green-50 text-green-700 ring-green-600/20',
  };
  const cls = colors[status] ?? 'bg-gray-50 text-gray-600 ring-gray-500/20';
  const label = status.replace(/_/g, ' ');
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${cls}`}>
      {label}
    </span>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const colors: Record<string, string> = {
    high: 'bg-red-50 text-red-700 ring-red-600/20',
    medium: 'bg-yellow-50 text-yellow-700 ring-yellow-600/20',
    low: 'bg-green-50 text-green-700 ring-green-600/20',
  };
  const cls = colors[priority] ?? 'bg-gray-50 text-gray-700 ring-gray-600/20';
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${cls}`}>
      {priority}
    </span>
  );
}
