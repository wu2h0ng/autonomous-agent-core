'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import Link from 'next/link';
import { postRun } from '@/lib/api';
import { AnswerPanel } from '@/components/AnswerPanel';
import { EvidenceCardList } from '@/components/EvidenceCards';
import { DashboardPanel } from '@/components/DashboardChart';
import { ActionProposal } from '@/components/ActionProposal';
import { GovernancePanel } from '@/components/GovernancePanel';
import { FeedbackBar } from '@/components/FeedbackBar';
import { addRecentRun } from '@/lib/recentRuns';

const PRESETS = [
  { label: 'GMV last week', question: 'What was the GMV last week?' },
  { label: 'ROI by channel', question: 'Show ROI breakdown by marketing channel this quarter.' },
  { label: 'Daily active users', question: 'How many daily active users did we have this month?' },
];

function LoadingSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <div className="h-5 bg-gray-200 rounded w-3/4 mb-3" />
        <div className="h-4 bg-gray-200 rounded w-1/2 mb-6" />
        <div className="space-y-2">
          <div className="h-4 bg-gray-200 rounded w-full" />
          <div className="h-4 bg-gray-200 rounded w-5/6" />
          <div className="h-4 bg-gray-200 rounded w-2/3" />
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="h-4 bg-gray-200 rounded w-1/3 mb-3" />
          <div className="h-10 bg-gray-200 rounded w-2/3" />
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="h-4 bg-gray-200 rounded w-1/3 mb-3" />
          <div className="h-10 bg-gray-200 rounded w-2/3" />
        </div>
      </div>
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <div className="h-4 bg-gray-200 rounded w-1/4 mb-4" />
        <div className="space-y-3">
          <div className="h-12 bg-gray-200 rounded" />
          <div className="h-12 bg-gray-200 rounded" />
        </div>
      </div>
    </div>
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
      <p className="text-lg font-medium text-gray-500 mb-1">Ask a business question</p>
      <p className="text-sm text-gray-400 text-center max-w-sm">
        Type a question in the left panel or select a preset to get started.
        The Data Agent will analyze your data and provide governed, evidence-backed answers.
      </p>
    </div>
  );
}

export default function QueryPage() {
  const [question, setQuestion] = useState('');

  const runMutation = useMutation({
    mutationFn: (q: string) => postRun(q),
    onSuccess: (payload, variables) => {
      addRecentRun(payload.trace_id, variables);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (question.trim()) {
      runMutation.mutate(question);
    }
  };

  const handlePreset = (presetQuestion: string) => {
    setQuestion(presetQuestion);
    runMutation.mutate(presetQuestion);
  };

  const data = runMutation.data;

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr_340px]">
        {/* Left Column: Input Panel */}
        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
              Business Query
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
                disabled={runMutation.isPending || !question.trim()}
                className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
              >
                {runMutation.isPending ? 'Analyzing...' : 'Submit Query'}
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
                  disabled={runMutation.isPending}
                  className="w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-gray-100 hover:border-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>

          {/* Last trace link */}
          {data?.trace_id && (
            <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-2">
              <Link
                href={`/runs/${data.trace_id}`}
                className="block text-sm text-blue-600 hover:text-blue-800 font-medium"
              >
                View run report &rarr;
              </Link>
              <Link
                href={`/trace/${data.trace_id}`}
                className="text-sm text-blue-600 hover:text-blue-800 font-medium"
              >
                View full trace &rarr;
              </Link>
            </div>
          )}
        </aside>

        {/* Center Column: Results */}
        <section className="min-w-0">
          {runMutation.isPending && <LoadingSkeleton />}

          {runMutation.isError && (
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
                  <h3 className="text-sm font-semibold text-red-800">Query Failed</h3>
                  <p className="mt-1 text-sm text-red-700">
                    {runMutation.error instanceof Error
                      ? runMutation.error.message
                      : 'An unexpected error occurred.'}
                  </p>
                  <p className="mt-2 text-xs text-red-600">
                    Check that the API server is running and the Run Key is valid.
                  </p>
                </div>
              </div>
            </div>
          )}

          {!runMutation.isPending && !runMutation.isError && !data && <EmptyState />}

          {runMutation.isSuccess && data && (
            <div className="space-y-6">
              {/* Answer */}
              <AnswerPanel
                analysis={data.user_result.analysis}
                decision={data.user_result.decision}
              />

              {/* Dashboard Widgets */}
              {data.user_result.dashboard?.widgets &&
                data.user_result.dashboard.widgets.length > 0 && (
                  <DashboardPanel widgets={data.user_result.dashboard.widgets} />
                )}

              {/* Evidence Cards from report */}
              {data.user_result.report?.evidence_cards &&
                data.user_result.report.evidence_cards.length > 0 && (
                  <EvidenceCardList cards={data.user_result.report.evidence_cards} />
                )}

              {/* Report sections */}
              {data.user_result.report?.sections &&
                data.user_result.report.sections.length > 0 && (
                  <div className="rounded-lg border border-gray-200 bg-white p-6">
                    <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
                      {data.user_result.report.title}
                    </h3>
                    <div className="space-y-4">
                      {data.user_result.report.sections.map((section, i) => (
                        <div key={i}>
                          <h4 className="text-sm font-medium text-gray-900 mb-1">
                            {section.heading}
                          </h4>
                          {section.body && (
                            <p className="text-sm text-gray-700">{section.body}</p>
                          )}
                          {section.items && section.items.length > 0 && (
                            <ul className="list-disc pl-5 text-sm text-gray-700 space-y-0.5">
                              {section.items.map((item, j) => (
                                <li key={j}>{item}</li>
                              ))}
                            </ul>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

              {/* Related knowledge */}
              {data.related_knowledge && data.related_knowledge.length > 0 && (
                <div className="rounded-lg border border-gray-200 bg-white p-4">
                  <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
                    Related Knowledge
                  </h3>
                  <div className="space-y-2">
                    {data.related_knowledge.map((k) => (
                      <div
                        key={k.asset_id}
                        className="flex items-center justify-between rounded-md bg-gray-50 px-3 py-2"
                      >
                        <span className="text-sm text-gray-700">{k.title}</span>
                        <span className="text-xs text-gray-500">
                          Score: {k.score.toFixed(2)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        {/* Right Column: Governance Rail */}
        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          {!data && !runMutation.isPending && (
            <div className="rounded-lg border border-dashed border-gray-300 bg-white p-6 text-center">
              <p className="text-sm text-gray-400">
                Governance details will appear here after a query.
              </p>
            </div>
          )}

          {runMutation.isSuccess && data && (
            <>
              {/* Action Proposal */}
              {data.user_result.business_action && (
                <ActionProposal action={data.user_result.business_action} />
              )}

              {/* Governance Panel */}
              {data.user_result && (
                <GovernancePanel
                  artifact={data.user_result}
                  knowledgeAssetId={data.knowledge_asset_id}
                  knowledgeVersion={data.knowledge_version}
                />
              )}

              {/* Inline Trace Timeline */}
              {data.trace_steps && data.trace_steps.length > 0 && (
                <div className="rounded-lg border border-gray-200 bg-white p-4">
                  <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
                    Trace Steps
                  </h3>
                  <div className="space-y-1">
                    {data.trace_steps.map((step, i) => (
                      <div key={i} className="flex items-center gap-2 text-sm text-gray-600">
                        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-blue-50 text-xs font-medium text-blue-600">
                          {i + 1}
                        </span>
                        <span>{step}</span>
                      </div>
                    ))}
                  </div>
                  <Link
                    href={`/trace/${data.trace_id}`}
                    className="mt-3 inline-block text-xs text-blue-600 hover:text-blue-800"
                  >
                    View detailed trace &rarr;
                  </Link>
                </div>
              )}

              {/* Feedback Bar */}
              <FeedbackBar traceId={data.trace_id} />
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
