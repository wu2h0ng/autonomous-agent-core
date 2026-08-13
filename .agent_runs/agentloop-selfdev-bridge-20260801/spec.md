# Product and authority specification

## Required behavior

1. Persisted SELFDEV scope binds an exact clean linked worktree, non-main branch, base HEAD, verifier and an explicit finite write set.
2. The existing linked Task and Run are reused. No chat/session helper may create a second Task.
3. AgentLoop may inspect and propose iterative `workspace.edit` operations across admitted files; all provider and tool actions remain typed through `ActionPipeline` and `PolicyKernel`.
4. Every mutating effect is wrapped by the responsibility loop's durable effect custody before invocation and fenced again before receipt commit. The same governed action executor owns policy, permit, broker invocation and Task receipt ordering for AgentLoop and RunCoordinator.
5. V0 uses one external durable exact-action approval per mutating action. No repository write occurs until that approval binds the original persisted ActionContract bytes. Rejection, expiry, conflict or missing approval is fail-closed and resumable on the same Task. Batch approval is explicitly deferred.
6. Verification runs only after the approved edit set completes. VERIFIED may settle only after exact scope/head/fence revalidation.
7. NOT_MET, provider/tool failure, correction, scope drift and interruption compensate all completed writes in reverse order without overwriting later external edits.
8. Main/master, commit, push, merge, release, approval/policy/evaluator code and operational state paths remain prohibited.
9. AgentLoop action identity, progress, provider/tool history and successful effect metadata are reconstructed from the same Task event stream. Randomly regenerated action/node/idempotency identity and `terminal_session.json` are forbidden in this route.
10. Successful mutating-effect records bind ordered sequence, action, path, compensation ref, manifest digest and applied digest. Recovery compensates that ledger strictly in reverse order; static WorkflowGraph enumeration is insufficient.

## Acceptance tests

- Two-file precise edit succeeds on the same Task and both effects have responsibility custody plus Task receipts.
- A provider request can inspect before editing and is not forced to receive complete files above 20k.
- Missing approval leaves all files byte-identical and returns a typed wait/block state.
- Approval digest mismatch and changed action arguments fail closed.
- Failure after the second edit compensates both edits in reverse order.
- Interruption between effect and Task receipt is reconciled as effect-unknown; it is never reported VERIFIED.
- Restart reuses the original pending ActionContract digest/idempotency identity and does not ask the provider to regenerate it.
- No second `TASK_CREATED`/`RUN_STARTED` or terminal session projection is created.
- Out-of-scope edit, symlink/path escape, dirty base/head/branch drift and prohibited capability fail closed.
- Existing single-target organ and ordinary AgentLoop behavior do not regress.

## Non-goals

- Resident daemon or automatic wake.
- Promotion, commit, push, merge, main or release authority.
- General-purpose benchmark work or another internal baseline round.
- Production credential/KMS work unless directly required by this bridge.
- Batch approval contracts and automatic promotion.

## Frozen route decision

- `SelfDevelopmentOrgan` and `ResponsibilityLoopController` remain the only responsibility entry and workspace guard.
- AgentLoop is an existing-Task inspect/propose organ; `open_chat_session`, `ConfirmationGateway`, `AutoApproveGateway` and AgentLoop self-authored approval are inadmissible for SELFDEV.
- Approval waits use the existing Task `ACTION_PROPOSED -> APPROVAL_REQUESTED -> APPROVAL_RECORDED` truth and the existing Outcome/Help projection.
- The existing WorkspaceSandbox exact-edit snapshots and CAS compensation are reused; donor benchmark/diff plumbing is not imported.
