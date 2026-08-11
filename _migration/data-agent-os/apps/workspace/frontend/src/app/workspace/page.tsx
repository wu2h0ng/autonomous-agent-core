'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import Link from 'next/link';
import { postNlBuild, postRun, postDashboard } from '@/lib/api';
import { AnswerPanel } from '@/components/AnswerPanel';
import { EvidenceCardList } from '@/components/EvidenceCards';
import type { components } from '@/lib/api/schema';

type NLBuildResponse = components['schemas']['NLBuildResponse'];
type DashboardCreateCard = components['schemas']['DashboardCreateCard'];
type RunResponse = components['schemas']['RunResponse'];

type DashboardCard = DashboardCreateCard & {
  localId: string;
  buildResult: NLBuildResponse;
  runResult?: RunResponse;
  runError?: string;
  runPending?: boolean;
};

const PRESETS = [
  { label: 'GMV last week', question: 'What was the GMV last week?' },
  { label: 'ROI by channel', question: 'Show ROI breakdown by marketing channel this quarter.' },
  { label: 'Daily active users', question: 'How many daily active users did we have this month?' },
];

function ConfidenceBadge({ confidence }: { confidence: number }) {
  let colorClasses: string;
  if (confidence > 0.8) {
    colorClasses = 'bg-green-100 text-green-800';
  } else if (confidence > 0.5) {
    colorClasses = 'bg-yellow-100 text-yellow-800';
  } else {
    colorClasses = 'bg-red-100 text-red-800';
  }

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${colorClasses}`}
    >
      {(confidence * 100).toFixed(0)}% confidence
    </span>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 bg-white py-20 px-6">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="currentColor"
        className="h-12 w-12 text-gray-300 mb-4"
      >
        <path d="M4.913 2.658c2.075-.27 4.19-.408 6.337-.408 2.147 0 4.262.139 6.337.408 1.922.25 3.291 1.861 3.405 3.727a4.403 4.403 0 00-1.032-.211 50.89 50.89 0 00-8.42 0c-2.358.196-4.04 2.19-4.04 4.434v4.286a4.403 4.403 0 002.433 3.984L7.28 21.53A1 1 0 016 20.957V15.17c0-2.855 2.14-5.272 4.967-5.545a50.48 50.48 0 016.066 0A5.144 5.144 0 0122 14.883V18a1 1 0 01-1 1h-1a1 1 0 110-2h1V14.883a3.144 3.144 0 00-2.673-3.107 48.48 48.48 0 00-6.654 0A3.144 3.144 0 0010 14.883V18a1 1 0 01-1 1H5.913a4.403 4.403 0 01-1-.118v-.755a2.402 2.402 0 01.634-1.62l1.698-1.856a2.402 2.402 0 01.633-1.62A2.402 2.402 0 018.512 11H10v-.883a5.144 5.144 0 014.967-5.545 50.89 50.89 0 018.42 0" />
      </svg>
      <p className="text-lg font-medium text-gray-500 mb-1">Build a data product</p>
      <p className="text-sm text-gray-400 text-center max-w-sm">
        Type a business question in the left panel. The Agent will match metrics and suggest a
        chart so you can compose a dashboard.
      </p>
    </div>
  );
}

function RunResultPanel({ runResult, runError, runPending }: {
  runResult?: RunResponse;
  runError?: string;
  runPending?: boolean;
}) {
  if (runPending) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Running metric...
        </div>
      </div>
    );
  }

  if (runError) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        {runError}
      </div>
    );
  }

  if (!runResult) {
    return null;
  }

  return (
    <div className="space-y-4">
      <AnswerPanel
        analysis={runResult.user_result.analysis}
        decision={runResult.user_result.decision}
      />
      {runResult.user_result.report?.evidence_cards &&
        runResult.user_result.report.evidence_cards.length > 0 && (
          <EvidenceCardList cards={runResult.user_result.report.evidence_cards} />
        )}
      {runResult.trace_id && (
        <Link
          href={`/trace/${runResult.trace_id}`}
          className="inline-block text-xs text-blue-600 hover:text-blue-800"
        >
          View full trace &rarr;
        </Link>
      )}
    </div>
  );
}

export default function NaturalLanguageWorkspacePage() {
  const [question, setQuestion] = useState('');
  const [dashboardTitle, setDashboardTitle] = useState('New Dashboard');
  const [cards, setCards] = useState<DashboardCard[]>([]);
  const [savedDashboardId, setSavedDashboardId] = useState<string | null>(null);

  const nlBuildMutation = useMutation({
    mutationFn: (q: string) => postNlBuild(q),
  });

  const dashboardMutation = useMutation({
    mutationFn: (body: { title: string; cards: DashboardCreateCard[] }) =>
      postDashboard(body.title, body.cards),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSavedDashboardId(null);
    if (question.trim()) {
      nlBuildMutation.mutate(question);
    }
  };

  const handlePreset = (presetQuestion: string) => {
    setQuestion(presetQuestion);
    setSavedDashboardId(null);
    nlBuildMutation.mutate(presetQuestion);
  };

  const addCard = (buildResult: NLBuildResponse) => {
    const title = buildResult.display_name || buildResult.matched_metric || buildResult.metric_keyword;
    const newCard: DashboardCard = {
      localId: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      title,
      question: buildResult.raw_question,
      metric_name: buildResult.matched_metric || buildResult.metric_keyword,
      chart_type: buildResult.suggested_chart_type,
      buildResult,
    };
    setCards((prev) => [...prev, newCard]);
  };

  const removeCard = (localId: string) => {
    setCards((prev) => prev.filter((c) => c.localId !== localId));
  };

  const runCard = async (localId: string) => {
    const card = cards.find((c) => c.localId === localId);
    if (!card) return;

    setCards((prev) =>
      prev.map((c) =>
        c.localId === localId ? { ...c, runPending: true, runError: undefined, runResult: undefined } : c,
      ),
    );

    try {
      const result = await postRun(card.question);
      setCards((prev) =>
        prev.map((c) =>
          c.localId === localId ? { ...c, runPending: false, runResult: result } : c,
        ),
      );
    } catch (err) {
      setCards((prev) =>
        prev.map((c) =>
          c.localId === localId
            ? {
                ...c,
                runPending: false,
                runError: err instanceof Error ? err.message : 'Run failed',
              }
            : c,
        ),
      );
    }
  };

  const saveDashboard = () => {
    if (cards.length === 0) return;
    const payloadCards: DashboardCreateCard[] = cards.map(({ title, question, metric_name, chart_type }) => ({
      title,
      question,
      metric_name,
      chart_type,
    }));
    dashboardMutation.mutate(
      { title: dashboardTitle || 'New Dashboard', cards: payloadCards },
      {
        onSuccess: (data) => {
          setSavedDashboardId(data.dashboard_id);
        },
      },
    );
  };

  const buildResult = nlBuildMutation.data;

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr_380px]">
        {/* Left Column: Input Panel */}
        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
              Natural Language Builder
            </h2>
            <form onSubmit={handleSubmit} className="space-y-3">
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask a business question, e.g. What was last week's GMV?"
                rows={4}
                className="w-full resize-none rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <button
                type="submit"
                disabled={nlBuildMutation.isPending || !question.trim()}
                className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
              >
                {nlBuildMutation.isPending ? 'Building...' : 'Build Metric'}
              </button>
            </form>
          </div>

          {/* Scenario Presets */}
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
              Scenario Presets
            </h3>
            <div className="space-y-2">
              {PRESETS.map((preset) => (
                <button
                  key={preset.label}
                  onClick={() => handlePreset(preset.question)}
                  disabled={nlBuildMutation.isPending}
                  className="w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-gray-100 hover:border-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>
        </aside>

        {/* Center Column: Metric Builder Results */}
        <section className="min-w-0">
          {nlBuildMutation.isPending && (
            <div className="space-y-4 animate-pulse">
              <div className="rounded-lg border border-gray-200 bg-white p-6">
                <div className="h-5 bg-gray-200 rounded w-3/4 mb-3" />
                <div className="h-4 bg-gray-200 rounded w-1/2 mb-6" />
                <div className="space-y-2">
                  <div className="h-4 bg-gray-200 rounded w-full" />
                  <div className="h-4 bg-gray-200 rounded w-5/6" />
                </div>
              </div>
            </div>
          )}

          {nlBuildMutation.isError && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-6">
              <div className="flex items-start gap-3">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  className="h-5 w-5 flex-shrink-0 text-red-500 mt-0.5"
                >
                  <path
                    fillRule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z"
                    clipRule="evenodd"
                  />
                </svg>
                <div>
                  <h3 className="text-sm font-semibold text-red-800">Build Failed</h3>
                  <p className="mt-1 text-sm text-red-700">
                    {nlBuildMutation.error instanceof Error
                      ? nlBuildMutation.error.message
                      : 'An unexpected error occurred.'}
                  </p>
                  <p className="mt-2 text-xs text-red-600">
                    Check that the API server is running and the Run Key is valid.
                  </p>
                </div>
              </div>
            </div>
          )}

          {!nlBuildMutation.isPending && !nlBuildMutation.isError && !buildResult && <EmptyState />}

          {nlBuildMutation.isSuccess && buildResult && (
            <div className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-base font-semibold text-gray-900">
                    {buildResult.display_name || buildResult.matched_metric || buildResult.metric_keyword}
                  </h3>
                  <p className="text-sm text-gray-500 mt-0.5">{buildResult.raw_question}</p>
                </div>
                <ConfidenceBadge confidence={buildResult.confidence} />
              </div>

              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <dt className="font-medium text-gray-500">Metric</dt>
                <dd className="text-gray-900">{buildResult.matched_metric || buildResult.metric_keyword}</dd>

                <dt className="font-medium text-gray-500">Suggested Chart</dt>
                <dd className="text-gray-900">{buildResult.suggested_chart_type}</dd>

                <dt className="font-medium text-gray-500">Dimensions</dt>
                <dd className="text-gray-900">
                  {buildResult.dimensions && buildResult.dimensions.length > 0
                    ? buildResult.dimensions.join(', ')
                    : '—'}
                </dd>

                {buildResult.parameters && Object.keys(buildResult.parameters).length > 0 && (
                  <>
                    <dt className="font-medium text-gray-500">Parameters</dt>
                    <dd className="text-gray-900">
                      {Object.entries(buildResult.parameters)
                        .map(([k, v]) => `${k}=${v}`)
                        .join(', ')}
                    </dd>
                  </>
                )}
              </dl>

              <button
                onClick={() => addCard(buildResult)}
                className="w-full rounded-md border border-blue-600 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 transition-colors hover:bg-blue-100"
              >
                Add to dashboard
              </button>
            </div>
          )}
        </section>

        {/* Right Column: Dashboard Preview */}
        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
                Dashboard Preview
              </h2>
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                {cards.length} card{cards.length === 1 ? '' : 's'}
              </span>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Dashboard Title</label>
                <input
                  type="text"
                  value={dashboardTitle}
                  onChange={(e) => setDashboardTitle(e.target.value)}
                  placeholder="Dashboard title"
                  className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              {cards.length === 0 && (
                <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-center text-sm text-gray-400">
                  Cards you add will appear here.
                </div>
              )}

              {cards.length > 0 && (
                <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
                  {cards.map((card) => (
                    <div
                      key={card.localId}
                      className="rounded-lg border border-gray-200 bg-white p-3 space-y-3"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <h4 className="text-sm font-medium text-gray-900">{card.title}</h4>
                          <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{card.question}</p>
                        </div>
                        <button
                          onClick={() => removeCard(card.localId)}
                          className="text-gray-400 hover:text-red-600"
                          aria-label="Remove card"
                        >
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            viewBox="0 0 20 20"
                            fill="currentColor"
                            className="h-4 w-4"
                          >
                            <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                          </svg>
                        </button>
                      </div>

                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="rounded bg-gray-100 px-2 py-0.5 text-gray-700">
                          {card.chart_type}
                        </span>
                        <span className="rounded bg-gray-100 px-2 py-0.5 text-gray-700">
                          {card.metric_name}
                        </span>
                      </div>

                      <button
                        onClick={() => runCard(card.localId)}
                        disabled={card.runPending}
                        className="w-full rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
                      >
                        {card.runPending ? 'Running...' : 'Run'}
                      </button>

                      <RunResultPanel
                        runResult={card.runResult}
                        runError={card.runError}
                        runPending={card.runPending}
                      />
                    </div>
                  ))}
                </div>
              )}

              <button
                onClick={saveDashboard}
                disabled={cards.length === 0 || dashboardMutation.isPending}
                className="w-full rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
              >
                {dashboardMutation.isPending ? 'Saving...' : 'Save Dashboard'}
              </button>

              {dashboardMutation.isError && (
                <p className="text-xs text-red-600">
                  {dashboardMutation.error instanceof Error
                    ? dashboardMutation.error.message
                    : 'Failed to save dashboard'}
                </p>
              )}

              {savedDashboardId && (
                <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm">
                  <p className="font-medium text-green-800">Dashboard saved</p>
                  <p className="mt-1 break-all font-mono text-xs text-green-700">
                    ID: {savedDashboardId}
                  </p>
                </div>
              )}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
