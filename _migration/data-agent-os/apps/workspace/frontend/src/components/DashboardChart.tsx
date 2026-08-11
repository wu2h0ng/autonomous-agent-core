'use client';

import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import type { components } from '@/lib/api/schema';

type UserResultDashboardWidget = components['schemas']['UserResultDashboardWidget'];

/* ------------------------------------------------------------------ */
/*  Table Fallback                                                     */
/* ------------------------------------------------------------------ */

function TableFallback({
  widget,
}: {
  widget: UserResultDashboardWidget;
}) {
  const columns = widget.columns ?? [];
  const rows = widget.preview_rows ?? [];

  if (columns.length === 0 || rows.length === 0) {
    return (
      <p className="text-sm text-gray-500">No tabular data available.</p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            {columns.map((col) => (
              <th
                key={col}
                className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 bg-white">
          {rows.map((row, rowIdx) => (
            <tr key={rowIdx}>
              {columns.map((col) => (
                <td key={col} className="whitespace-nowrap px-3 py-2 text-gray-700">
                  {row[col] != null ? String(row[col]) : '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {widget.row_count != null && widget.row_count > rows.length && (
        <p className="mt-1 text-xs text-gray-400">
          Showing {rows.length} of {widget.row_count} rows
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Chart Rendering                                                    */
/* ------------------------------------------------------------------ */

function ChartWidget({ widget }: { widget: UserResultDashboardWidget }) {
  const rows = widget.preview_rows ?? [];
  const xField = widget.x_field;
  const yField = widget.y_field;

  if (!xField || !yField || rows.length === 0) {
    return (
      <div className="rounded border border-dashed border-gray-300 p-4 text-center text-sm text-gray-500">
        Chart requires x_field ({xField ?? 'none'}) and y_field ({yField ?? 'none'}) with
        data rows.
      </div>
    );
  }

  // Ensure y values are numeric for charting
  const chartData = rows.map((row) => ({
    ...row,
    [yField]: typeof row[yField] === 'number' ? row[yField] : Number(row[yField]) || 0,
  }));

  const chartType = widget.type;

  if (chartType === 'line_chart') {
    return (
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={xField} tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip />
          <Line
            type="monotone"
            dataKey={yField}
            stroke="#3b82f6"
            strokeWidth={2}
            dot={{ r: 3 }}
          />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === 'bar_chart') {
    return (
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={xField} tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip />
          <Bar dataKey={yField} fill="#8b5cf6" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  // Unknown chart type — fall back to table
  return <TableFallback widget={widget} />;
}

/* ------------------------------------------------------------------ */
/*  DashboardChart — single widget                                     */
/* ------------------------------------------------------------------ */

export function DashboardChart({
  widget,
}: {
  widget: UserResultDashboardWidget;
}) {
  const isChart = widget.type === 'line_chart' || widget.type === 'bar_chart';

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">{widget.title}</h3>
        <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
          {widget.type}
          {widget.unit ? ` (${widget.unit})` : ''}
        </span>
      </div>

      {isChart ? <ChartWidget widget={widget} /> : <TableFallback widget={widget} />}

      {widget.redacted_fields && widget.redacted_fields.length > 0 && (
        <p className="mt-2 text-xs text-amber-600">
          Redacted: {widget.redacted_fields.join(', ')}
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  DashboardPanel — renders all widgets                               */
/* ------------------------------------------------------------------ */

export function DashboardPanel({
  widgets,
  loading,
  error,
}: {
  widgets?: UserResultDashboardWidget[] | null;
  loading?: boolean;
  error?: string | null;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-gray-200 bg-white p-8">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        <span className="ml-2 text-sm text-gray-500">Loading dashboard...</span>
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

  if (!widgets || widgets.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
        No dashboard widgets available.
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-1 lg:grid-cols-2">
      {widgets.map((widget) => (
        <DashboardChart key={widget.widget_id} widget={widget} />
      ))}
    </div>
  );
}
