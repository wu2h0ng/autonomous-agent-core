'use client';

import type { components } from '@/lib/api/schema';

type TraceResponse = components['schemas']['TraceResponse'];
type TraceEventItem = components['schemas']['TraceEventItem'];
type TelemetryItem = components['schemas']['TelemetryItem'];

/* ------------------------------------------------------------------ */
/*  Payload Summary (max 5 key-value pairs)                            */
/* ------------------------------------------------------------------ */

function PayloadSummary({ payload }: { payload: Record<string, unknown> }) {
  const entries = Object.entries(payload).slice(0, 5);

  if (entries.length === 0) {
    return <span className="text-xs text-gray-400">empty payload</span>;
  }

  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="font-medium text-gray-500">{key}</dt>
          <dd className="truncate text-gray-700">
            {typeof value === 'object' ? JSON.stringify(value) : String(value)}
          </dd>
        </div>
      ))}
      {Object.keys(payload).length > 5 && (
        <p className="col-span-2 text-[10px] text-gray-400">
          +{Object.keys(payload).length - 5} more fields
        </p>
      )}
    </dl>
  );
}

/* ------------------------------------------------------------------ */
/*  Telemetry Badges                                                   */
/* ------------------------------------------------------------------ */

function TelemetryBadges({ items }: { items: TelemetryItem[] }) {
  if (items.length === 0) return null;

  return (
    <div className="mt-4 flex flex-wrap gap-2">
      {items.map((item, idx) => (
        <span
          key={idx}
          className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-700"
          title={
            item.attributes
              ? JSON.stringify(item.attributes)
              : `${item.dimension}: ${item.name}`
          }
        >
          <span className="font-semibold">{item.name}</span>
          <span className="text-slate-500">
            {item.value}
            {item.unit}
          </span>
        </span>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  TraceEvent (vertical timeline node)                                */
/* ------------------------------------------------------------------ */

function TraceEvent({
  event,
  index,
  isLast,
}: {
  event: TraceEventItem;
  index: number;
  isLast: boolean;
}) {
  return (
    <li className="relative flex gap-4 pb-6">
      {/* Timeline connector */}
      <div className="flex flex-col items-center">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-bold text-blue-700 ring-4 ring-white">
          {index + 1}
        </div>
        {!isLast && (
          <div className="mt-1 w-px grow bg-gray-200" />
        )}
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1 pt-0.5">
        <p className="text-sm font-semibold text-gray-900">{event.step}</p>
        <div className="mt-1 rounded bg-gray-50 p-2">
          <PayloadSummary payload={event.payload} />
        </div>
      </div>
    </li>
  );
}

/* ------------------------------------------------------------------ */
/*  TraceTimeline                                                      */
/* ------------------------------------------------------------------ */

export function TraceTimeline({
  trace,
  loading,
  error,
}: {
  trace: TraceResponse | null | undefined;
  loading?: boolean;
  error?: string | null;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-gray-200 bg-white p-8">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        <span className="ml-2 text-sm text-gray-500">Loading trace...</span>
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

  if (!trace) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
        No trace data available.
      </div>
    );
  }

  const events = trace.events ?? [];
  const telemetry = trace.telemetry ?? [];

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Execution Trace</h3>
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
              trace.status === 'completed'
                ? 'bg-green-100 text-green-800'
                : trace.status === 'blocked'
                  ? 'bg-red-100 text-red-800'
                  : 'bg-amber-100 text-amber-800'
            }`}
          >
            {trace.status}
          </span>
          <span className="font-mono text-xs text-gray-400">{trace.trace_id}</span>
        </div>
      </div>

      {events.length === 0 ? (
        <p className="text-sm text-gray-500">No trace events recorded.</p>
      ) : (
        <ol className="relative">
          {events.map((event, idx) => (
            <TraceEvent
              key={idx}
              event={event}
              index={idx}
              isLast={idx === events.length - 1}
            />
          ))}
        </ol>
      )}

      <TelemetryBadges items={telemetry} />
    </div>
  );
}
