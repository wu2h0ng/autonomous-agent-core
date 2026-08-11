'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getApproval, executeApproval } from '@/lib/api';
import { useAppStore } from '@/lib/store';

interface ApprovalDetailProps {
  approvalId: string;
  backHref?: string;
}

export function ApprovalDetail({ approvalId, backHref = '/approvals' }: ApprovalDetailProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { operatorKey: storedOperatorKey } = useAppStore();
  const [operatorKey, setOperatorKey] = useState(storedOperatorKey || '');
  const [reason, setReason] = useState('');
  const [result, setResult] = useState<{ status: 'success' | 'error'; message: string } | null>(
    null,
  );

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['approval', approvalId],
    queryFn: () => getApproval(approvalId),
  });

  const executeMutation = useMutation({
    mutationFn: () => executeApproval(approvalId, operatorKey, reason || 'approved via workspace'),
    onSuccess: (payload) => {
      setResult({
        status: 'success',
        message: `Approval executed. Operation trace: ${payload.operation_trace_id}`,
      });
      queryClient.invalidateQueries({ queryKey: ['approval', approvalId] });
      queryClient.invalidateQueries({ queryKey: ['approvals'] });
    },
    onError: (err: Error) => {
      setResult({ status: 'error', message: err.message });
    },
  });

  const isPending = data?.status === 'pending';
  const canExecute = isPending && operatorKey.trim() && !executeMutation.isPending;

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <button
        onClick={() => router.push(backHref)}
        className="mb-4 text-sm text-blue-600 hover:text-blue-800"
      >
        ← Back to approvals
      </button>
      <h1 className="text-2xl font-bold text-gray-900">Approval Detail</h1>

      {isLoading && (
        <div className="mt-6 animate-pulse space-y-3">
          <div className="h-4 bg-gray-200 rounded w-1/2" />
          <div className="h-4 bg-gray-200 rounded w-1/3" />
          <div className="h-4 bg-gray-200 rounded w-2/3" />
        </div>
      )}

      {isError && (
        <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-6">
          <h3 className="text-sm font-semibold text-red-800">Failed to load approval</h3>
          <p className="mt-1 text-sm text-red-700">
            {error instanceof Error ? error.message : 'Unknown error'}
          </p>
        </div>
      )}

      {data && (
        <div className="mt-6 space-y-6">
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <div className="mb-4 flex items-center justify-between">
              <span className="font-mono text-sm text-gray-600">{data.approval_id}</span>
              <StatusBadge status={data.status} />
            </div>
            <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <dt className="text-xs font-semibold uppercase text-gray-500">Proposal ID</dt>
                <dd className="mt-1 text-sm text-gray-900">{data.proposal_id}</dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase text-gray-500">Approver Role</dt>
                <dd className="mt-1 text-sm text-gray-900">{data.approver_role || '-'}</dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase text-gray-500">Approved By</dt>
                <dd className="mt-1 text-sm text-gray-900">{data.approved_by || '-'}</dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase text-gray-500">Reason</dt>
                <dd className="mt-1 text-sm text-gray-900">{data.reason || '-'}</dd>
              </div>
            </dl>
          </div>

          {isPending && (
            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h2 className="mb-4 text-lg font-semibold text-gray-900">Execute Approval</h2>
              <div className="space-y-4">
                {!storedOperatorKey && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700">
                      Operator Key
                    </label>
                    <input
                      type="password"
                      value={operatorKey}
                      onChange={(e) => setOperatorKey(e.target.value)}
                      className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      placeholder="operator key"
                    />
                  </div>
                )}
                <div>
                  <label className="block text-sm font-medium text-gray-700">Reason</label>
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    rows={3}
                    className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    placeholder="Reason for approval"
                  />
                </div>
                <button
                  onClick={() => executeMutation.mutate()}
                  disabled={!canExecute}
                  className={`rounded-md px-4 py-2 text-sm font-medium text-white ${
                    canExecute ? 'bg-blue-600 hover:bg-blue-700' : 'bg-gray-400 cursor-not-allowed'
                  }`}
                >
                  {executeMutation.isPending ? 'Executing...' : 'Execute'}
                </button>
              </div>
            </div>
          )}

          {result && (
            <div
              className={`rounded-lg border p-6 ${
                result.status === 'success'
                  ? 'border-green-200 bg-green-50'
                  : 'border-red-200 bg-red-50'
              }`}
            >
              <h3
                className={`text-sm font-semibold ${
                  result.status === 'success' ? 'text-green-800' : 'text-red-800'
                }`}
              >
                {result.status === 'success' ? 'Executed' : 'Execution failed'}
              </h3>
              <p
                className={`mt-1 text-sm ${
                  result.status === 'success' ? 'text-green-700' : 'text-red-700'
                }`}
              >
                {result.message}
              </p>
            </div>
          )}
        </div>
      )}
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
