'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { listApprovals } from '@/lib/api';
import { ApprovalList } from '@/components/ApprovalList';

const STATUS_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
];

export default function ApprovalsPage() {
  const [statusFilter, setStatusFilter] = useState('');

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['approvals', statusFilter],
    queryFn: () => listApprovals({ status: statusFilter || undefined, limit: 100 }),
  });

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Approvals</h1>
          <p className="text-sm text-gray-500 mt-1">
            Review and execute pending business-action proposals.
          </p>
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {isLoading && (
        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="animate-pulse space-y-0">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 border-b border-gray-100 p-4">
                <div className="h-4 bg-gray-200 rounded w-32" />
                <div className="h-4 bg-gray-200 rounded flex-1" />
                <div className="h-4 bg-gray-200 rounded w-20" />
              </div>
            ))}
          </div>
        </div>
      )}

      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6">
          <h3 className="text-sm font-semibold text-red-800">Failed to load approvals</h3>
          <p className="mt-1 text-sm text-red-700">
            {error instanceof Error ? error.message : 'Unknown error'}
          </p>
        </div>
      )}

      {data && <ApprovalList approvals={data.items} />}
    </div>
  );
}
