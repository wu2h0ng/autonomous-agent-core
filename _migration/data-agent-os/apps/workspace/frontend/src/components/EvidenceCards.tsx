'use client';

import type { components } from '@/lib/api/schema';

type MetricContractEvidenceCard = components['schemas']['MetricContractEvidenceCard'];
type SQLSafetyEvidenceCard = components['schemas']['SQLSafetyEvidenceCard'];
type QueryResultEvidenceCard = components['schemas']['QueryResultEvidenceCard'];
type EvidenceCard = MetricContractEvidenceCard | SQLSafetyEvidenceCard | QueryResultEvidenceCard;

/* ------------------------------------------------------------------ */
/*  MetricContractEvidenceCard                                         */
/* ------------------------------------------------------------------ */

export function MetricContractEvidenceCard({
  card,
}: {
  card: MetricContractEvidenceCard;
}) {
  return (
    <div className="rounded-lg border border-blue-200 border-l-4 border-l-blue-500 bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center gap-2">
        <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-800">
          Metric Contract
        </span>
        <h3 className="text-sm font-semibold text-gray-900">{card.title}</h3>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="font-medium text-gray-500">Metric</dt>
        <dd className="text-gray-900">{card.metric_name}</dd>

        <dt className="font-medium text-gray-500">Display Name</dt>
        <dd className="text-gray-900">{card.display_name}</dd>

        <dt className="font-medium text-gray-500">Version</dt>
        <dd className="text-gray-900">{card.metric_version}</dd>

        <dt className="font-medium text-gray-500">Unit</dt>
        <dd className="text-gray-900">{card.unit}</dd>

        <dt className="font-medium text-gray-500">Owner</dt>
        <dd className="text-gray-900">{card.owner}</dd>

        <dt className="font-medium text-gray-500">Classification</dt>
        <dd className="text-gray-900">{card.data_classification}</dd>

        <dt className="font-medium text-gray-500">Dimensions</dt>
        <dd className="text-gray-900">
          {card.dimensions.length > 0 ? card.dimensions.join(', ') : '—'}
        </dd>

        <dt className="font-medium text-gray-500">Derived From</dt>
        <dd className="text-gray-900">
          {card.derived_from.length > 0 ? card.derived_from.join(', ') : '—'}
        </dd>
      </dl>

      {card.redacted_fields && card.redacted_fields.length > 0 && (
        <p className="mt-2 text-xs text-amber-600">
          Redacted: {card.redacted_fields.join(', ')}
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  SQLSafetyEvidenceCard                                              */
/* ------------------------------------------------------------------ */

export function SQLSafetyEvidenceCard({
  card,
}: {
  card: SQLSafetyEvidenceCard;
}) {
  const borderColor = card.sql_safety_allowed
    ? 'border-l-green-500'
    : 'border-l-red-500';

  const statusBadge = card.sql_safety_allowed ? (
    <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-800">
      SQL Safety Passed
    </span>
  ) : (
    <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-800">
      SQL Safety Blocked
    </span>
  );

  return (
    <div
      className={`rounded-lg border border-gray-200 border-l-4 ${borderColor} bg-white p-4 shadow-sm`}
    >
      <div className="mb-2 flex items-center gap-2">
        {statusBadge}
        <h3 className="text-sm font-semibold text-gray-900">{card.title}</h3>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="font-medium text-gray-500">Query Metric</dt>
        <dd className="text-gray-900">{card.query_metric_name}</dd>

        <dt className="font-medium text-gray-500">Fingerprint</dt>
        <dd className="truncate font-mono text-xs text-gray-700">
          {card.sql_fingerprint ?? '—'}
        </dd>

        <dt className="font-medium text-gray-500">Limit</dt>
        <dd className="text-gray-900">{card.limit_value ?? '—'}</dd>

        <dt className="font-medium text-gray-500">Checked Tables</dt>
        <dd className="text-gray-900">
          {card.checked_tables.length > 0 ? card.checked_tables.join(', ') : '—'}
        </dd>

        <dt className="font-medium text-gray-500">Checked Schemas</dt>
        <dd className="text-gray-900">
          {card.checked_schemas.length > 0 ? card.checked_schemas.join(', ') : '—'}
        </dd>

        <dt className="font-medium text-gray-500">Bound Params</dt>
        <dd className="text-gray-900">
          {card.bound_parameter_names.length > 0
            ? card.bound_parameter_names.join(', ')
            : '—'}
        </dd>

        <dt className="font-medium text-gray-500">Derived From</dt>
        <dd className="text-gray-900">
          {card.derived_from.length > 0 ? card.derived_from.join(', ') : '—'}
        </dd>
      </dl>

      {card.redacted_fields && card.redacted_fields.length > 0 && (
        <p className="mt-2 text-xs text-amber-600">
          Redacted: {card.redacted_fields.join(', ')}
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  QueryResultEvidenceCard                                            */
/* ------------------------------------------------------------------ */

export function QueryResultEvidenceCard({
  card,
}: {
  card: QueryResultEvidenceCard;
}) {
  return (
    <div className="rounded-lg border border-purple-200 border-l-4 border-l-purple-500 bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center gap-2">
        <span className="rounded bg-purple-100 px-2 py-0.5 text-xs font-semibold text-purple-800">
          Query Result
        </span>
        <h3 className="text-sm font-semibold text-gray-900">{card.title}</h3>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="font-medium text-gray-500">Row Count</dt>
        <dd className="text-gray-900">{card.row_count}</dd>

        <dt className="font-medium text-gray-500">Preview Rows</dt>
        <dd className="text-gray-900">{card.preview_row_count}</dd>

        <dt className="font-medium text-gray-500">Columns</dt>
        <dd className="text-gray-900">
          {card.columns.length > 0 ? card.columns.join(', ') : '—'}
        </dd>

        <dt className="font-medium text-gray-500">Derived From</dt>
        <dd className="text-gray-900">
          {card.derived_from.length > 0 ? card.derived_from.join(', ') : '—'}
        </dd>
      </dl>

      {card.redacted_fields && card.redacted_fields.length > 0 && (
        <p className="mt-2 text-xs text-amber-600">
          Redacted: {card.redacted_fields.join(', ')}
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  EvidenceCardList — renders the discriminated union                  */
/* ------------------------------------------------------------------ */

export function EvidenceCardList({ cards }: { cards: EvidenceCard[] }) {
  if (!cards || cards.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
        No evidence cards available.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {cards.map((card, idx) => {
        switch (card.card_id) {
          case 'metric_contract':
            return <MetricContractEvidenceCard key={`mc-${idx}`} card={card} />;
          case 'sql_safety':
            return <SQLSafetyEvidenceCard key={`ss-${idx}`} card={card} />;
          case 'query_result':
            return <QueryResultEvidenceCard key={`qr-${idx}`} card={card} />;
          default:
            return null;
        }
      })}
    </div>
  );
}
