import { KnowledgeDetailClient } from './KnowledgeDetailClient';

export default async function KnowledgeAssetPage({
  params,
}: {
  params: Promise<{ assetId: string }>;
}) {
  const { assetId } = await params;
  return <KnowledgeDetailClient assetId={assetId} />;
}
