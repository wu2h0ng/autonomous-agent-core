# RR-0031 Qualification Scaffold Cast Review

- Reviewer: `aba_blind_calibrator`
- Blind phase: `PASS_TO_CONTROLLED_EXPOSURE`
- Controlled-exposure manifest: approved ABA design five files plus current run goal/context/plan/prereg/verification/team-plan only
- First delta verdict: `REVISE`
- Exact correction re-review: `APPROVE_QUALIFICATION_SCAFFOLD_CAST`
- Findings: `P0=0 / P1=0`

## First-delta findings

1. Public qualification-scaffold authority and experiment-implementation authority used overlapping state names. They are now separate: scaffold approval can open only five named public files, while experiment implementation remains denied.
2. Multiple reviewers shared `review.md`. Review artifacts are now split into `advisory_cast_review.md`, `qualification_cast_review.md` and future `implementation_review.md` with distinct identities.
3. The imported design contains stale internal workflow labels; the final exact-byte `messages.jsonl` approval receipt now has explicit precedence without upgrading preregistration/readiness/freeze/run state.
4. Verification now separates completed, pending and out-of-scope evidence instead of using a roll-up green claim.

## Exact correction closure

- B1-B4 and the context pack now distinguish qualification-scaffold admission from experiment implementation admission.
- Canonical reviewer ids exactly bind advisory, qualification and future implementation review artifacts without shared-file writers.
- Verification evidence is separated into completed, pending and out-of-scope sections.
- Stale internal design labels remain superseded only by the exact design receipt and cannot upgrade preregistration, readiness, freeze or run state.

Approved state: `QUALIFICATION_SCAFFOLD_CAST_APPROVED / EXPERIMENT_IMPLEMENTATION_DENIED / PREREG_REVISE / NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`.
