'use client';

import { useParams } from 'next/navigation';
import { ApprovalDetail } from '@/components/ApprovalDetail';

export default function ApprovalPage() {
  const params = useParams();
  const approvalId = String(params.approvalId);
  return <ApprovalDetail approvalId={approvalId} backHref="/approval" />;
}
