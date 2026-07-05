'use client';

import { useState } from 'react';
import type { components } from '@/lib/api/schema';

type UserResultBusinessAction = components['schemas']['UserResultBusinessAction'];

/* ------------------------------------------------------------------ */
/*  Risk Level Badge                                                   */
/* ------------------------------------------------------------------ */

function RiskBadge({ riskLevel }: { riskLevel: string }) {
  const normalized = riskLevel.toUpperCase();

  let colorClasses: string;
  switch (normalized) {
    case 'R1':
      colorClasses = 'bg-green-100 text-green-800';
      break;
    case 'R2':
      colorClasses = 'bg-yellow-100 text-yellow-800';
      break;
    case 'R3':
      colorClasses = 'bg-orange-100 text-orange-800';
      break;
    case 'R4':
    case 'R5':
      colorClasses = 'bg-red-100 text-red-800';
      break;
    default:
      colorClasses = 'bg-gray-100 text-gray-800';
  }

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${colorClasses}`}
    >
      {riskLevel}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  ActionProposal                                                     */
/* ------------------------------------------------------------------ */

export function ActionProposal({
  action,
  onApprove,
  onReject,
  loading,
  error,
}: {
  action: UserResultBusinessAction | null | undefined;
  onApprove?: (approvalId: string) => void;
  onReject?: (approvalId: string) => void;
  loading?: boolean;
  error?: string | null;
}) {
  const [decision, setDecision] = useState<'approved' | 'rejected' | null>(null);

  if (loading) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-gray-200 bg-white p-8">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        <span className="ml-2 text-sm text-gray-500">Loading action proposal...</span>
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

  if (!action) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
        No action proposal available.
      </div>
    );
  }

  const isHighRisk = ['R4', 'R5'].includes(action.risk_level.toUpperCase());

  const handleApprove = () => {
    setDecision('approved');
    if (action.approval_id && onApprove) {
      onApprove(action.approval_id);
    }
  };

  const handleReject = () => {
    setDecision('rejected');
    if (action.approval_id && onReject) {
      onReject(action.approval_id);
    }
  };

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Action Proposal</h3>
        <RiskBadge riskLevel={action.risk_level} />
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="font-medium text-gray-500">Action Type</dt>
        <dd className="text-gray-900">{action.action_type}</dd>

        <dt className="font-medium text-gray-500">Connector</dt>
        <dd className="text-gray-900">{action.connector_name}</dd>

        <dt className="font-medium text-gray-500">Status</dt>
        <dd>
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
              action.status === 'pending'
                ? 'bg-amber-100 text-amber-800'
                : action.status === 'approved'
                  ? 'bg-green-100 text-green-800'
                  : action.status === 'rejected'
                    ? 'bg-red-100 text-red-800'
                    : 'bg-gray-100 text-gray-800'
            }`}
          >
            {action.status}
          </span>
        </dd>

        <dt className="font-medium text-gray-500">Approval Required</dt>
        <dd className="text-gray-900">{action.approval_required ? 'Yes' : 'No'}</dd>

        {action.approver_role && (
          <>
            <dt className="font-medium text-gray-500">Approver Role</dt>
            <dd className="text-gray-900">{action.approver_role}</dd>
          </>
        )}

        <dt className="font-medium text-gray-500">Row Count</dt>
        <dd className="text-gray-900">{action.row_count}</dd>

        <dt className="font-medium text-gray-500">Evidence Chain</dt>
        <dd className="truncate font-mono text-xs text-gray-700">
          {action.evidence_chain_id}
        </dd>
      </dl>

      {isHighRisk && (
        <div className="mt-3 rounded bg-red-50 px-3 py-2 text-xs text-red-700">
          R4/R5 actions are proposal-only in MVP. Execution requires separate CTO/founder
          authorization.
        </div>
      )}

      {/* Approve / Reject buttons */}
      {action.approval_required && action.approval_id && !decision && (
        <div className="mt-4 flex gap-3">
          <button
            type="button"
            onClick={handleApprove}
            disabled={isHighRisk}
            className="rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Approve
          </button>
          <button
            type="button"
            onClick={handleReject}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
          >
            Reject
          </button>
        </div>
      )}

      {decision && (
        <div
          className={`mt-4 rounded px-3 py-2 text-sm font-medium ${
            decision === 'approved'
              ? 'bg-green-50 text-green-700'
              : 'bg-red-50 text-red-700'
          }`}
        >
          Action {decision === 'approved' ? 'approved' : 'rejected'}.
        </div>
      )}
    </div>
  );
}
