import { TraceDetailClient } from './TraceDetailClient';

export default async function TracePage({
  params,
}: {
  params: Promise<{ traceId: string }>;
}) {
  const { traceId } = await params;
  return <TraceDetailClient traceId={traceId} />;
}
