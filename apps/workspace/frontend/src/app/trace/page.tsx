'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function TraceIndexPage() {
  const [traceId, setTraceId] = useState('');
  const router = useRouter();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (traceId.trim()) {
      router.push(`/trace/${traceId.trim()}`);
    }
  };

  return (
    <div className="mx-auto max-w-2xl px-6 py-16">
      <h1 className="text-2xl font-bold text-gray-900 mb-2">Trace Lookup</h1>
      <p className="text-sm text-gray-500 mb-8">
        Enter a trace ID to view the full execution timeline, events, and telemetry
        for a specific run.
      </p>
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={traceId}
          onChange={(e) => setTraceId(e.target.value)}
          placeholder="Enter trace ID (e.g., abc123-def456...)"
          className="flex-1 rounded-md border border-gray-300 bg-white px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
        />
        <button
          type="submit"
          disabled={!traceId.trim()}
          className="rounded-md bg-blue-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
        >
          View Trace
        </button>
      </form>
      <p className="mt-4 text-xs text-gray-400">
        Trace IDs are returned with each query result. You can find them on the Workspace page
        after running a query.
      </p>
    </div>
  );
}
