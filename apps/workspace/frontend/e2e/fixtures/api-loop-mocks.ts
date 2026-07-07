/** Mock API payloads for Playwright live-API closed-loop E2E (mocked transport). */

export const MOCK_TRACE_ID = 'trace-e2e-mock-001';
export const MOCK_APPROVAL_ID = 'approval-e2e-mock-001';
export const MOCK_EVIDENCE_CHAIN_ID = 'evidence-e2e-mock-001';

export const mockRunResponse = {
  trace_id: MOCK_TRACE_ID,
  evidence_chain_id: MOCK_EVIDENCE_CHAIN_ID,
  action_proposal_id: 'proposal-e2e-mock-001',
  knowledge_asset_id: null,
  knowledge_version: null,
  trace_steps: ['intent_parsed', 'sql_safety_passed', 'evidence_built', 'action_proposed'],
  user_result: {
    kind: 'data_agent_result',
    trace_id: MOCK_TRACE_ID,
    title: 'GMV Analysis',
    question: 'What was the GMV last week?',
    metric_name: 'gmv',
    evidence_chain_id: MOCK_EVIDENCE_CHAIN_ID,
    audience: 'internal',
    analysis: {
      summary: 'GMV totaled 128,800 CNY for the selected period.',
      confidence: 0.92,
      evidence_chain_id: MOCK_EVIDENCE_CHAIN_ID,
      row_count: 1,
      limitations: [],
    },
    decision: {
      recommendation: 'Review campaign spend against GMV lift.',
      reason: 'Spend efficiency improved week over week.',
      expected_impact: 'Maintain current budget allocation.',
      confidence: 0.88,
      risk_level: 'R3',
      approval_required: true,
      approver_role: 'operator',
      action_proposal_id: 'proposal-e2e-mock-001',
      knowledge_context_refs: [],
    },
    report: {
      title: 'Evidence Report',
      sections: [],
      evidence_cards: [],
    },
    dashboard: {
      widgets: [],
    },
    business_action: {
      action_type: 'execute',
      connector_name: 'action_record',
      risk_level: 'R3',
      status: 'awaiting_approval',
      approval_required: true,
      approval_id: MOCK_APPROVAL_ID,
      approver_role: 'operator',
      row_count: 1,
      evidence_chain_id: MOCK_EVIDENCE_CHAIN_ID,
    },
    redaction: {
      audience: 'internal',
      applied: false,
      data_classification: 'internal',
      redacted_fields: [],
    },
  },
};

export const mockApprovalDetail = {
  approval_id: MOCK_APPROVAL_ID,
  proposal_id: 'proposal-e2e-mock-001',
  trace_id: MOCK_TRACE_ID,
  status: 'pending',
  action_type: 'execute',
  connector_name: 'action_record',
  risk_level: 'R3',
  approver_role: 'operator',
  created_at: '2026-07-07T12:00:00Z',
};

export const mockApprovalList = {
  items: [
    {
      approval_id: MOCK_APPROVAL_ID,
      trace_id: MOCK_TRACE_ID,
      status: 'pending',
      action_type: 'execute',
      risk_level: 'R3',
      connector_name: 'action_record',
    },
  ],
  total: 1,
};

export const mockApprovalExecuteResponse = {
  approval_id: MOCK_APPROVAL_ID,
  state: 'executed',
  operation_trace_id: 'op-trace-e2e-mock-001',
  execution_audit: {
    connector_name: 'action_record',
    execution_status: 'executed',
  },
};

export const mockOutcomeResponse = {
  feedback_id: 'feedback-e2e-mock-001',
  trace_id: MOCK_TRACE_ID,
  outcome: 'useful',
};

export const mockTraceResponse = {
  trace_id: MOCK_TRACE_ID,
  status: 'ok',
  events: [{ step: 'intent_parsed', payload: {} }],
};
