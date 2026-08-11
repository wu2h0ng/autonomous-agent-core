'use client';

import { OutcomeForm } from '@/components/OutcomeForm';

export default function OutcomesPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <h1 className="text-2xl font-bold text-gray-900">Record Outcome / Adoption</h1>
      <p className="mt-1 text-sm text-gray-500">
        Attach observed results to a trace. Outcome is self-report feedback; Adoption attests
        realized external value and may promote the associated knowledge asset.
      </p>

      <div className="mt-6">
        <OutcomeForm />
      </div>
    </div>
  );
}
