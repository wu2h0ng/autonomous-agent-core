import { RunDetailClient } from './RunDetailClient';

export default async function RunPage({
  params,
}: {
  params: Promise<{ traceId: string }>;
}) {
  const { traceId } = await params;
  return <RunDetailClient traceId={traceId} />;
}
