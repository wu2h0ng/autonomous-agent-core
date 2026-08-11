'use client';

import { useState, useSyncExternalStore, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
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
  const router = useRouter();
  const { runs, clear } = useRecentRuns();
  const [traceLookup, setTraceLookup] = useState('');

  const handleLookup = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = traceLookup.trim();
    if (trimmed) {
      router.push(`/runs/${encodeURIComponent(trimmed)}`);
    }
  };

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Recent Runs</h1>
          <p className="text-sm text-gray-500 mt-1">
            Session history from this browser plus live lookup by trace ID against the API.
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

      <form
        onSubmit={handleLookup}
        className="mb-8 flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-white p-4"
      >
        <div className="flex-1 min-w-[240px]">
          <label htmlFor="trace-lookup" className="block text-sm font-medium text-gray-700 mb-1">
            Look up run by trace ID
          </label>
          <input
            id="trace-lookup"
            type="text"
            value={traceLookup}
            onChange={(e) => setTraceLookup(e.target.value)}
            placeholder="Paste trace_id from API or smoke test"
            className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-mono text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <button
          type="submit"
          disabled={!traceLookup.trim()}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
        >
          Open report
        </button>
      </form>

      {runs.length === 0 && (
        <div className="rounded-lg border border-dashed border-gray-300 bg-white p-12 text-center">
          <p className="text-lg font-medium text-gray-500 mb-1">No recent runs in this session</p>
          <p className="text-sm text-gray-400 mb-4">
            Run a query on the Workspace page, or paste a trace ID above to load a report from the
            API.
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
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Actions
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
                  <td className="px-4 py-3">
                    <Link
                      href={`/trace/${run.traceId}`}
                      className="text-sm text-blue-600 hover:text-blue-800"
                    >
                      Trace
                    </Link>
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
