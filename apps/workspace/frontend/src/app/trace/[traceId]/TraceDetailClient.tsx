'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { getTrace } from '@/lib/api';
import { TraceTimeline } from '@/components/TraceTimeline';

interface TraceDetailClientProps {
  traceId: string;
}

export function TraceDetailClient({ traceId }: TraceDetailClientProps) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['trace', traceId],
    queryFn: () => getTrace(traceId),
  });

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      {/* Header */}
      <div className="mb-6">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 mb-4"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            className="h-4 w-4"
          >
            <path
              fillRule="evenodd"
              d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z"
              clipRule="evenodd"
            />
          </svg>
          Back to Workspace
        </Link>
        <h1 className="text-2xl font-bold text-gray-900">Trace Detail</h1>
        <p className="text-sm text-gray-500 mt-1 font-mono">{traceId}</p>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-4 animate-pulse">
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <div className="h-5 bg-gray-200 rounded w-1/3 mb-4" />
            <div className="space-y-3">
              <div className="h-12 bg-gray-100 rounded" />
              <div className="h-12 bg-gray-100 rounded" />
              <div className="h-12 bg-gray-100 rounded" />
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6">
          <h3 className="text-sm font-semibold text-red-800">Failed to load trace</h3>
          <p className="mt-1 text-sm text-red-700">
            {error instanceof Error ? error.message : 'Unknown error'}
          </p>
        </div>
      )}

      {/* Success */}
      {data && (
        <div className="space-y-6">
          {/* Status badge */}
          <div className="flex items-center gap-3">
            <span
              className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-medium ring-1 ${
                data.status === 'success'
                  ? 'bg-green-50 text-green-700 ring-green-600/20'
                  : data.status === 'blocked'
                    ? 'bg-red-50 text-red-700 ring-red-600/20'
                    : 'bg-gray-50 text-gray-700 ring-gray-600/20'
              }`}
            >
              {data.status}
            </span>
          </div>

          {/* Trace Timeline */}
          {data.events && data.events.length > 0 && (
            <TraceTimeline trace={data} />
          )}

          {/* Telemetry Summary */}
          {data.telemetry && data.telemetry.length > 0 && (
            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-4">
                Telemetry
              </h3>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {data.telemetry.map((item, idx) => (
                  <div
                    key={idx}
                    className="rounded-lg border border-gray-100 bg-gray-50 p-4"
                  >
                    <p className="text-xs text-gray-500 mb-1">{item.dimension}</p>
                    <p className="text-sm font-medium text-gray-900">{item.name}</p>
                    <p className="text-lg font-bold text-gray-900 mt-1">
                      {item.value}
                      <span className="ml-1 text-xs font-normal text-gray-500">
                        {item.unit}
                      </span>
                    </p>
                    {item.attributes && Object.keys(item.attributes).length > 0 && (
                      <details className="mt-2">
                        <summary className="text-xs text-gray-400 cursor-pointer">
                          Attributes
                        </summary>
                        <pre className="mt-1 text-xs text-gray-500 overflow-x-auto">
                          {JSON.stringify(item.attributes, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Empty states */}
          {(!data.events || data.events.length === 0) && (
            <div className="rounded-lg border border-dashed border-gray-300 bg-white p-12 text-center">
              <p className="text-sm text-gray-400">No trace events recorded for this run.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
