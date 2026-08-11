# PR-26 Controlled Pilot Internal Handoff Checklist (2026-07-04)

- Status: internal handoff checklist prepared / origin/main push remains HOLD / no release
- Layer: deployment / Phase-1 controlled-pilot closure preparation
- Verified local head: `7197d8ee7514b6e29ad41715099cdcf6d821e33a`

This checklist is for internal Phase-1 controlled-pilot closure preparation
only. It turns the current candidate-maintenance state into an operator-facing
handoff without changing runtime behavior, moving the RC branch, pushing
`origin/main`, creating a release tag, or publishing external product claims.

## Source Anchors

- Live state: `docs/CURRENT_STATE.yaml`
- RC branch record: `docs/decisions/PR-15-controlled-pilot-rc-branch-20260704.md`
- Latest full local CI evidence:
  `docs/decisions/PR-25-controlled-pilot-current-head-full-ci-refresh-20260704.md`
- Push hold decision:
  `docs/decisions/PR-10-deployment-push-hold-decision-20260704.md`

## Allowed Internal Pilot Activities

- Run bounded internal `POST /runs` scenarios through the public API contract.
- Inspect internal-only traces, evidence cards, report/dashboard/decision
  artifacts, and KnowledgeAsset review surfaces using configured internal
  credentials.
- Exercise approval-required R0-R3 paths only through the existing approval
  gate and operator-key flow.
- Record feedback/outcome/adoption observations through existing governed
  correction/adoption surfaces when the pilot scenario has an internal trace
  and evidence chain to bind.
- Record pilot observations as internal evidence for product readiness,
  usability, and trusted-loop gaps.

## Forbidden Activities

- Do not push `origin/main`.
- Do not repoint or overwrite `rc/phase-1-controlled-pilot-20260704` without a
  new explicit founder/CTO authorization.
- Do not create release, rc, or version tags.
- Do not publish customer-facing release notes, benchmark claims, product
  guarantees, autonomous-core/G10/AGI/RSI claims, or external deployment claims.
- Do not enable automatic R4/R5 execution.
- Do not bypass SQL Safety, EvidenceChain, Approval, Trace, ProviderContract,
  or the Agent Runtime policy gate.
- Do not put Customer-0 domain-specific logic into OS Core.
- Do not store secrets, credentials, cookies, customer raw data, or sensitive
  traces in project memory or handoff docs.

## Pilot Closure Evidence To Capture

For each internal pilot scenario, capture enough evidence to prove the Trusted
Loop was exercised rather than narrated:

1. Intent: the business intent and audience (`internal` or `external`) used.
2. Contract: the MetricContract/SemanticObject/DataProduct or ProviderContract
   path exercised.
3. Safety: SQL Safety decision, evidence-chain completeness, and any block code
   or approval requirement.
4. Artifact: report/dashboard/decision/business-action proposal returned to the
   caller, including redaction behavior when external projection is tested.
5. Governance: approval state, operator-key execution result, or explicit reason
   the proposal stayed unexecuted.
6. Trace: trace id, safe trace events, runtime-envelope events when applicable,
   and any sanitized failure path.
7. Feedback: outcome/adoption/KnowledgeAsset observation, if actually produced
   by the scenario.
8. Non-claim boundary: confirmation that the run did not imply release,
   external shipment, automatic R4/R5 execution, or autonomous-core validation.

## Preflight Commands Before Any Pilot Handoff Claim

```bash
make current-state-verification-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make controlled-pilot-readiness-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make push-authorization-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
git ls-remote --heads origin main rc/phase-1-controlled-pilot-20260704
git tag --list '*phase-1*' '*rc*' '*release*'
```

Expected boundary:

- current-state verification passes;
- controlled-pilot readiness passes;
- push authorization exits 2 under `DEPLOYMENT_PUSH: HOLD`;
- `origin/main` remains `dba87bc35ae2c7be3dfbcc022c64c0a04cbf9171` unless a
  later explicit authorization changes it;
- the RC branch remains a bounded handoff branch unless a later explicit
  authorization changes it;
- release/rc tag search has no output.

## Exit Criteria For "Controlled Pilot Closed"

The pilot is not closed by local CI alone. It can only be called closed when a
future record binds all of the following:

- at least one internal scenario with full Trusted Loop evidence from intent to
  trace and feedback/outcome where applicable;
- explicit notation of any blocked, approval-required, or unsupported path;
- no raw secret/customer data embedded in records;
- no R4/R5 automatic execution;
- no `origin/main` push or release tag unless separately authorized and
  recorded;
- a final founder/CTO decision saying whether the pilot result is accepted,
  needs another internal iteration, or is parked.

## Non-Claims

This checklist does not:

- verify a new runtime capability;
- add a product feature slice;
- replace PR-25 full-CI evidence;
- authorize push, release, deployment, or customer-facing publication;
- claim pilot closure;
- claim autonomous-core, G10, AGI, RSI, or general Agent OS validation.
