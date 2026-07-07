'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { getReport } from '@/lib/api';
import { AnswerPanel } from '@/components/AnswerPanel';
import { EvidenceChainViewer } from '@/components/EvidenceChainViewer';
import { DashboardPanel } from '@/components/DashboardChart';
import { ActionProposalPanel } from '@/components/ActionProposalPanel';
import { DataProductCard } from '@/components/DataProductCard';
import { GovernancePanel } from '@/components/GovernancePanel';

interface RunDetailClientProps {
  traceId: string;
}

export function RunDetailClient({ traceId }: RunDetailClientProps) {
  const [audience, setAudience] = useState<'internal' | 'external'>('internal');

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['run-report', traceId, audience],
    queryFn: () => getReport(traceId, audience),
  });

  const artifact = data?.user_result;

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-6">
      <div className="mb-6">
        <Link
          href="/runs"
          className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 mb-2"
        >
          ← Back to runs
        </Link>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Run Report</h1>
            <p className="text-sm text-gray-500 mt-1 font-mono">{traceId}</p>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-600">Audience</label>
            <select
              value={audience}
              onChange={(e) => setAudience(e.target.value as 'internal' | 'external')}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="internal">Internal</option>
              <option value="external">External</option>
            </select>
          </div>
        </div>
      </div>

      {isLoading && (
        <div className="space-y-6 animate-pulse">
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <div className="h-5 bg-gray-200 rounded w-3/4 mb-3" />
            <div className="h-4 bg-gray-200 rounded w-1/2" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-lg border border-gray-200 bg-white p-4 h-40" />
            <div className="rounded-lg border border-gray-200 bg-white p-4 h-40" />
          </div>
        </div>
      )}

      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6">
          <h3 className="text-sm font-semibold text-red-800">Failed to load report</h3>
          <p className="mt-1 text-sm text-red-700">
            {error instanceof Error ? error.message : 'Unknown error'}
          </p>
        </div>
      )}

      {artifact && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_380px]">
          <section className="min-w-0 space-y-6">
            {/* Business Context */}
            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
                Business Context
              </h2>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                <dt className="font-medium text-gray-500">Title</dt>
                <dd className="text-gray-900">{artifact.title}</dd>

                <dt className="font-medium text-gray-500">Question</dt>
                <dd className="text-gray-900">{artifact.question}</dd>

                <dt className="font-medium text-gray-500">Metric</dt>
                <dd className="text-gray-900">{artifact.metric_name}</dd>

                <dt className="font-medium text-gray-500">Audience</dt>
                <dd className="text-gray-900">{artifact.audience}</dd>
              </dl>
            </div>

            {/* Answer */}
            <AnswerPanel analysis={artifact.analysis} decision={artifact.decision} />

            {/* Dashboard Widgets */}
            <DashboardPanel widgets={artifact.dashboard?.widgets} />

            {/* Evidence Chain */}
            <EvidenceChainViewer
              report={artifact.report}
              evidenceChainId={artifact.evidence_chain_id}
              traceId={traceId}
            />

            {/* DataProduct Candidate */}
            <DataProductCard artifact={artifact} />
          </section>

          <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
            <GovernancePanel artifact={artifact} />
            <ActionProposalPanel action={artifact.business_action} />

            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <Link
                href={`/trace/${traceId}`}
                className="text-sm text-blue-600 hover:text-blue-800 font-medium"
              >
                View execution trace &rarr;
              </Link>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
