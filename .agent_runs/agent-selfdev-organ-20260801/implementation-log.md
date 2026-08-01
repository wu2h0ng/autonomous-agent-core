# Implementation log

## 2026-08-01

- Characterized historical SELFDEV donor `5fa6f69e466cbd1a7dd97732d339b387f97ffe56`; rejected branch/file transplantation and retained only narrow admission/rollback lessons.
- Added `SelfDevelopmentWorkSpec` to the canonical persisted `MandateTaskLink` contract without changing ordinary-link digests.
- Added `SelfDevelopmentOrgan` as a narrow controller port. It verifies a real linked Git worktree, exact branch and exact base HEAD before and after execution.
- Bound the organ to the existing Responsibility Surface and linked Task; no second Task or public SELFDEV CLI is created.
- Made canonical Commitment acceptance criteria and the persisted execution envelope provider-visible.
- Bound pending action approval Help to the exact Task action and an external tenant-admin principal; conflicting durable approval decisions fail closed.
- Added success, identity-drift, approval, negative-outcome and compensation attack tests. Provider-proposed failing edits restore the exact file preimage.

Claim ceiling: first isolated single-target Product organ only. AgentLoop effect custody, broader terminal capability, resident wake, promotion, release, HCW reduction, general intelligence and `Autonomy(S,E,O,V,T)` remain unestablished.
