'use client';

import type { components } from '@/lib/api/schema';
import { EvidenceCardList } from './EvidenceCards';

type UserResultReport = components['schemas']['UserResultReport'];

export function EvidenceChainViewer({
  report,
  evidenceChainId,
  traceId,
}: {
  report: UserResultReport;
  evidenceChainId: string;
  traceId: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Evidence Chain</h3>
        <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-800">
          {report.evidence_cards.length > 0 ? 'complete' : 'pending'}
        </span>
      </div>

      <dl className="mb-4 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="font-medium text-gray-500">Trace</dt>
        <dd className="truncate font-mono text-xs text-gray-700">{traceId}</dd>

        <dt className="font-medium text-gray-500">Evidence Chain</dt>
        <dd className="truncate font-mono text-xs text-gray-700">{evidenceChainId}</dd>

        <dt className="font-medium text-gray-500">Cards</dt>
        <dd className="text-gray-900">{report.evidence_cards.length}</dd>
      </dl>

      <EvidenceCardList cards={report.evidence_cards} />
    </div>
  );
}
