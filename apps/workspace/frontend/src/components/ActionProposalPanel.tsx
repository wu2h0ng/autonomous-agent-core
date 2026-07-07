'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { executeApproval } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import { ActionProposal } from './ActionProposal';

type UserResultBusinessAction = components['schemas']['UserResultBusinessAction'];

export function ActionProposalPanel({
  action,
}: {
  action: UserResultBusinessAction | null | undefined;
}) {
  const queryClient = useQueryClient();
  const { operatorKey: storedOperatorKey } = useAppStore();
  const [operatorKey, setOperatorKey] = useState(storedOperatorKey || '');
  const [result, setResult] = useState<{ status: 'success' | 'error'; message: string } | null>(
    null,
  );

  const executeMutation = useMutation({
    mutationFn: (approvalId: string) => executeApproval(approvalId, operatorKey),
    onSuccess: (payload) => {
      setResult({
        status: 'success',
        message: `Approval executed. Operation trace: ${payload.operation_trace_id}`,
      });
      queryClient.invalidateQueries({ queryKey: ['approval', payload.approval_id] });
      queryClient.invalidateQueries({ queryKey: ['approvals'] });
    },
    onError: (err: Error) => {
      setResult({ status: 'error', message: err.message });
    },
  });

  const riskLevel = action?.risk_level?.toUpperCase() ?? '';
  const isHighRisk = riskLevel === 'R4' || riskLevel === 'R5';
  const canExecute =
    !isHighRisk &&
    action?.approval_required &&
    action.approval_id &&
    operatorKey.trim() &&
    !executeMutation.isPending;

  return (
    <div className="space-y-4">
      <ActionProposal
        action={action}
        onApprove={(approvalId) => executeMutation.mutate(approvalId)}
      />

      {action?.approval_required && action.approval_id && (
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <h4 className="mb-3 text-sm font-semibold text-gray-900">Execute Approval</h4>

          {!storedOperatorKey && (
            <div className="mb-3">
              <label className="block text-xs font-medium text-gray-500 mb-1">
                Operator Key
              </label>
              <input
                type="password"
                value={operatorKey}
                onChange={(e) => setOperatorKey(e.target.value)}
                placeholder={storedOperatorKey ? 'Using key from settings' : 'Enter operator key'}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          )}

          {isHighRisk && (
            <div className="mb-3 rounded bg-red-50 px-3 py-2 text-xs text-red-700">
              R4/R5 actions are proposal-only in MVP. Execution requires separate CTO/founder
              authorization.
            </div>
          )}

          <button
            type="button"
            onClick={() => action.approval_id && executeMutation.mutate(action.approval_id)}
            disabled={!canExecute}
            className={`rounded-md px-4 py-2 text-sm font-medium text-white ${
              canExecute
                ? 'bg-blue-600 hover:bg-blue-700'
                : 'bg-gray-400 cursor-not-allowed'
            }`}
          >
            {executeMutation.isPending ? 'Executing...' : 'Execute Action'}
          </button>

          {result && (
            <div
              className={`mt-3 rounded px-3 py-2 text-sm ${
                result.status === 'success'
                  ? 'bg-green-50 text-green-700'
                  : 'bg-red-50 text-red-700'
              }`}
            >
              {result.message}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
