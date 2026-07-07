'use client';

import { useSyncExternalStore, useCallback } from 'react';
import Link from 'next/link';
import {
  clearRecentRuns,
  getRecentRunsSnapshot,
  subscribeRecentRuns,
  type RecentRun,
} from '@/lib/recentRuns';

const SERVER_RUNS: RecentRun[] = [];

function useRecentRuns(): { runs: RecentRun[]; clear: () => void } {
  const runs = useSyncExternalStore(
    subscribeRecentRuns,
    getRecentRunsSnapshot,
    () => SERVER_RUNS,
  );

  const clear = useCallback(() => {
    clearRecentRuns();
  }, []);

  return { runs, clear };
}

export default function RunsPage() {
  const { runs, clear } = useRecentRuns();

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Recent Runs</h1>
          <p className="text-sm text-gray-500 mt-1">
            Trace IDs from this browser session. No backend list endpoint exists yet.
          </p>
        </div>
        {runs.length > 0 && (
          <button
            onClick={clear}
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Clear history
          </button>
        )}
      </div>

      {runs.length === 0 && (
        <div className="rounded-lg border border-dashed border-gray-300 bg-white p-12 text-center">
          <p className="text-lg font-medium text-gray-500 mb-1">No recent runs</p>
          <p className="text-sm text-gray-400 mb-4">
            Run a query on the Workspace page to add trace IDs here.
          </p>
          <Link
            href="/"
            className="inline-flex rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Go to Workspace
          </Link>
        </div>
      )}

      {runs.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Trace ID
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Question
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Time
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {runs.map((run) => (
                <tr key={run.traceId} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <Link
                      href={`/runs/${run.traceId}`}
                      className="text-sm font-mono text-blue-600 hover:text-blue-800"
                    >
                      {run.traceId}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm text-gray-700">{run.question}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm text-gray-500">
                      {new Date(run.timestamp).toLocaleString()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
