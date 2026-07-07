import { ApprovalDetail } from '@/components/ApprovalDetail';

export default async function ApprovalsDetailPage({
  params,
}: {
  params: Promise<{ approvalId: string }>;
}) {
  const { approvalId } = await params;
  return <ApprovalDetail approvalId={approvalId} backHref="/approvals" />;
}
