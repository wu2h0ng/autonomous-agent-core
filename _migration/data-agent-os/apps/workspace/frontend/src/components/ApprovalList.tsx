'use client';

import Link from 'next/link';
import type { components } from '@/lib/api/schema';

type ApprovalListItem = components['schemas']['ApprovalListItem'];

export function ApprovalList({ approvals }: { approvals?: ApprovalListItem[] }) {
  if (!approvals || approvals.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 bg-white p-12 text-center">
        <p className="text-lg font-medium text-gray-500 mb-1">No approvals found</p>
        <p className="text-sm text-gray-400">
          Approvals are created when a query proposes a business action that requires operator
          review.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Approval ID
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Proposal ID
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Status
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Approver Role
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Approved By
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {approvals.map((item) => (
            <tr key={item.approval_id} className="hover:bg-gray-50 transition-colors">
              <td className="px-4 py-3">
                <Link
                  href={`/approvals/${item.approval_id}`}
                  className="text-sm font-mono text-blue-600 hover:text-blue-800"
                >
                  {item.approval_id.slice(0, 12)}...
                </Link>
              </td>
              <td className="px-4 py-3">
                <span className="text-sm text-gray-700">{item.proposal_id}</span>
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={item.status} />
              </td>
              <td className="px-4 py-3">
                <span className="text-sm text-gray-700">{item.approver_role || '-'}</span>
              </td>
              <td className="px-4 py-3">
                <span className="text-sm text-gray-700">{item.approved_by || '-'}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-yellow-50 text-yellow-700 ring-yellow-600/20',
    approved: 'bg-green-50 text-green-700 ring-green-600/20',
    rejected: 'bg-red-50 text-red-700 ring-red-600/20',
  };
  const cls = colors[status] ?? 'bg-gray-50 text-gray-700 ring-gray-600/20';
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${cls}`}
    >
      {status}
    </span>
  );
}
