# PR-09 Deployment Local-Main Aggregate Release Packet (2026-07-03)

- Status: AUTHORIZATION PACKET / DO NOT PUSH AUTOMATICALLY / DO NOT RELEASE
- Layer: deployment / Enterprise OS product body
- Current local `main` head: `f27fd99`
- Latest code-bearing product head: `55da9a7`
- Current `origin/main`: `dba87bc`
- Current divergence: `origin/main..main = 173 commits`
- Decision authority: founder/CTO push gate first, release gate second

This packet is the aggregate push/release decision surface for the current
local-only deployment mainline. It does not itself push, release, deploy, or
convert deployment progress into autonomous-core research evidence.

## 1. Decision Summary

```text
push_gate_status: AWAIT_FOUNDER_CTO_AUTHORIZATION
release_gate_status: HOLD_PENDING_PUSH_AND_RELEASE_REVIEW
candidate_head: f27fd99
runtime_evidence_head: 55da9a7
max_claim_scope: local_main_release_candidate_packeted
```

The deployment repository now has an aggregate packet for the current local
mainline. The missing action is no longer "understand what is in local main."
The missing action is explicit authorization.

## 2. Candidate Boundary

- Remote baseline: `origin/main@dba87bc`
- Current local head: `main@f27fd99`
- Current code-bearing runtime head: `55da9a7`

`f27fd99` is a docs-only truth commit on top of `55da9a7`. The files changed
between `55da9a7` and `f27fd99` are:

- `docs/CURRENT_STATE.yaml`
- `docs/decisions/README.md`
- `docs/decisions/P1-61-knowledge-usage-rationale-events.POST-MERGE-VERIFY-20260703.md`
- `docs/decisions/PR-08-deployment-local-main-release-gap-audit-20260703.md`

Therefore the latest runtime/product verification evidence still binds to
`55da9a7`, while the aggregate truth/release packet binds to `f27fd99`.

## 3. Included Local-Only Stack

The local-only mainline between `dba87bc` and `f27fd99` includes, at minimum:

1. ADR-0003 local-only runtime slices
   - correction-channel runtime envelope
   - internal-only public resume API
2. ADR-0004 governed-decision seam
3. P1-04 eval threshold report
4. P1-05 through P1-61 KnowledgeAsset review/catalog/rationale/usage/audit
   surfaces
5. docs-only truth/state commits that reconcile local-main status and release
   boundaries

This packet treats the stack as one accumulated deployment candidate, not as
isolated slice-local wins.

## 4. Verification Evidence Bound To The Candidate

For the latest code-bearing product head `55da9a7`:

- focused P1-61 regressions: 4 tests OK
- related regressions: 14 tests OK
- `make ci`: 609 primary unittest tests OK / 4 skipped
- eval suite: 12 tests OK
- threshold report passed
- OpenAPI contract up to date
- PostgreSQL `ci-local-full`: full parity passed

Primary evidence records:

- `docs/decisions/P1-61-knowledge-usage-rationale-events.POST-MERGE-VERIFY-20260703.md`
- `docs/decisions/ADR-0004-governed-decision-seam.POST-MERGE-VERIFY-20260703.md`
- `docs/decisions/P1-04-eval-threshold-report.POST-MERGE-VERIFY-20260703.md`
- `docs/decisions/P1-05-knowledge-review-queue.POST-MERGE-VERIFY-20260703.md`
- `docs/decisions/P1-06-knowledge-review-actions.POST-MERGE-VERIFY-20260703.md`
- `docs/decisions/P1-07-knowledge-review-audit.POST-MERGE-VERIFY-20260703.md`
- `docs/decisions/P1-08-reviewed-knowledge-consumption.POST-MERGE-VERIFY-20260703.md`
- `docs/decisions/P1-09-knowledge-context-proposal.POST-MERGE-VERIFY-20260703.md`
- `docs/decisions/P1-10-internal-knowledge-context-projection.POST-MERGE-VERIFY-20260703.md`
- `docs/decisions/P1-11-knowledge-publish-lifecycle.POST-MERGE-VERIFY-20260703.md`
- `docs/decisions/P1-12-knowledge-asset-catalog.POST-MERGE-VERIFY-20260703.md`
- later P1 post-merge verification records through P1-61 as indexed in
  `docs/decisions/README.md`

## 5. What This Packet Does And Does Not Prove

This packet proves:

- the deployment local mainline is no longer ambiguous;
- the current local-only stack has an aggregate decision surface;
- the latest code-bearing head has fresh local CI/eval evidence;
- the runtime/product head and docs/truth head are explicitly separated.

This packet does not prove:

- push approval;
- release approval;
- environment readiness;
- production deployment readiness;
- external shipment;
- autonomous-core / G10 / AGI / RSI / autonomy proof.

## 6. Requested Decision

Requested founder/CTO decision:

```text
Authorize or reject pushing deployment local main f27fd99 to origin/main.
```

If authorized, the push should happen from the current frozen local mainline
without inserting unreviewed code changes between packet issuance and push.

## 7. Follow-On Gate After Push

Even with push authorization, release remains blocked until a separate release
review verifies at least:

- target environment and secret handling
- auth matrix behavior
- external/public vs external/non-public redaction behavior
- rollback/support posture
- any public-facing shipment or customer-commitment claim

## 8. Final Recommendation

```text
Do not do more feature slicing before the push decision is made.
Use f27fd99 as the explicit decision packet head.
Keep release as a second gate after push, not bundled into the push decision.
```
