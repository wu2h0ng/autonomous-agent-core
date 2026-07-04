# PR-27 Real-Execution RC Branch Record (2026-07-05)

- Status: independent RC branch pushed under founder authorization / no origin/main push / no release
- Layer: deployment / RR-0048 Option 2 real-world-execution release-candidate handoff
- Verified local head: `26a31bf26a976d6cc2eff554f167cc544b6f070e`
- RC branch: `rc/phase-1b-real-execution-20260705`
- RC branch head: `26a31bf26a976d6cc2eff554f167cc544b6f070e`
- Remote main head: `dba87bc35ae2c7be3dfbcc022c64c0a04cbf9171`

## Decision Boundary

Founder authorization (2026-07-05, RR-0048 phase-gate Option 2) allowed pushing the current verified
real-execution candidate to an **independent** remote RC branch, **parallel to** the frozen Phase-1
controlled-pilot candidate. This resolves the conflict between the RR-0048 Option 2 real-execution slices
(S1–S4) and the controlled-pilot readiness boundary, which forbids adding more feature slices to the frozen
pilot candidate `b8834a644018e070e372be149fb758a928c7a242`.

This did **not** authorize:

- pushing `origin/main` (it remains `dba87bc35ae2c7be3dfbcc022c64c0a04cbf9171`, `DEPLOYMENT_PUSH: HOLD`);
- creating a formal release tag;
- publishing external release or product claims;
- enabling automatic R4/R5 business-action execution;
- expanding autonomous-core, G10, AGI, or RSI claims;
- disturbing the frozen Phase-1 controlled-pilot RC branch `rc/phase-1-controlled-pilot-20260704`
  (`b8834a6`) or its controlled-pilot readiness boundary ("do not add more P1 feature slices").

The executable `DEPLOYMENT_PUSH: HOLD` gate still blocks `origin/main` push and formal release promotion.

## Scope — what this RC carries

The independent real-execution candidate `26a31bf` is deployment local `main`, which is 220 commits ahead of
`origin/main` and includes the RR-0048 Option 2 real-execution slices merged locally (ff-only) with
per-slice feature branches also on origin:

- **S1** (ADR-0005) execution-time governance recheck — corrigibility C7 + seam re-consult before any
  connector side-effect. Branch `codex/s1-execution-time-governance-recheck-20260705`.
- **S2** (ADR-0006) local-disposer-governed first real reversible R0-R3 action — real `MetricCohortABVerifier`
  landed on main; real `action_record` execute + rollback + C7 pause.
  Branch `codex/s2-local-disposer-real-governed-action-20260705`.
- **S3** (ADR-0007) integrated real execution across a real process boundary — OS-side reference seam server,
  full runtime over the wire, fail-safe when the brain is down.
  Branch `codex/s3-cross-process-seam-real-execution-20260705`.
- **S4** (ADR-0008) outcome→learning moat closed to a real governed action, with the anti-wirehead guarantee.
  Branch `codex/s4-outcome-learning-moat-20260705`.

R4/R5 remain proposal-only; the governed-decision seam can only tighten; no cross-repo import (#19).

## Candidate Verification Evidence

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
PYTHONPATH=packages/contracts/src:packages/os_core/src:action_connectors \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest \
  tests.unit.test_execution_time_governance_recheck tests.unit.test_cohort_ab_verifier \
  tests.integration.test_s2_governed_real_action_local_disposer \
  tests.integration.test_s3_cross_process_seam_real_action \
  tests.integration.test_s4_outcome_learning_moat
```

Observed result: `make ci` passed (ruff clean, format clean, primary unittest suite OK, eval OK, threshold
report OK, OpenAPI up to date); the four-slice suite passed with 24 tests OK.

## Verification command for this record

```bash
make rc-branch-verification-check PYTHON=<venv-python> \
  PUSH_EXPECTED_HEAD= \
  # points the verifier at this record:
python scripts/release_gate/rc_branch_verification_check.py \
  --record-file docs/decisions/PR-27-real-execution-rc-branch-20260705.md
```

Observed result: RC branch verification passed against the remote real-execution RC head, unchanged
origin/main head, and absence of release/rc tags.

## Non-Claims

This RC branch record is not a release note and not a customer-facing claim. It records the independent
real-execution controlled-candidate branch handoff boundary so later agents do not confuse it with
`origin/main` promotion, formal release, or the separate frozen Phase-1 controlled-pilot candidate.
Separate future `origin/main` push authorization and release review remain required.
