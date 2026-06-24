# ADR-0002 Enterprise Integration Readiness: Merge-Readiness Note (2026-06-24)

- Status: review note / merge-order decision required.
- Branch under review: `codex/enterprise-integration-readiness` at `3d5bde4`.
- Remote base checked: `origin/main` at `ad87efa`.
- Local main checked: `main` at `f35f4e8`.
- Scope: connector-declared execution semantics generalization + side-effect-free report-read projection + postgres-backed `report_snapshots` durability + CI dependency preflight.
- Boundary: this note does not merge, push, release, or approve external deployment.

## 1. Required Conclusion

```text
ready_against_origin_main:
  yes
ready_to_direct_merge_into_local_main:
  no
reason:
  local main already contains ADR-0003 runtime-substrate status/docs commits after origin/main;
  a direct merge has content conflicts in README.md and docs/CURRENT_STATE.yaml.
recommended_next:
  create an explicit reconcile branch if local ADR-0003 main remains the intended base,
  resolve the two status-doc conflicts there, then rerun make ci before any merge/push.
```

## 2. Evidence

Commands run from the isolated enterprise integration worktree:

```bash
git merge-tree --write-tree origin/main HEAD
```

Result: exit 0, wrote merge tree `dedccfa7db66fad6ef12c513d59df7cc79cfe43c`. No conflict was reported against `origin/main`.

```bash
git merge-tree --write-tree main HEAD
```

Result: exit 1, with content conflicts in:

- `README.md`
- `docs/CURRENT_STATE.yaml`

Both branches have merge-base `ad87efa`, which means the local-main conflict is real parallel work, not a dirty worktree artifact.

## 3. Verified Branch State

The branch itself remains locally verified:

- `make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python`
- 419 primary unittest tests OK, 4 skipped.
- 12 eval tests OK.
- ruff check clean.
- ruff format check clean.
- OpenAPI contract up to date.
- YAML load and `git diff --check` clean after the report snapshot durability update.

Targeted coverage added on this branch:

- report snapshot survives a fresh app/runtime instance on the postgres backend;
- external report key is still forced to the external projection;
- internal and external projections keep separate `artifact_id` values;
- migration coverage includes the new `report_snapshots` table.

## 4. Merge-Order Options

### Option A: Merge This Branch Before Local ADR-0003 Main

Use only if `origin/main` remains the target base for this slice. This avoids the current conflict, but then the ADR-0003 runtime-substrate branch must be reconciled after this branch lands.

### Option B: Reconcile With Local ADR-0003 Main First

Use if local `main` at `f35f4e8` is the intended next base. Create a dedicated reconcile branch from local `main`, merge `codex/enterprise-integration-readiness`, resolve only the status-doc conflicts, rerun `make ci`, and record the reconcile result before any push or release decision.

Recommended: Option B, unless the founder explicitly wants to ship the ADR-0002 integration branch before ADR-0003. The reason is practical: local `main` has already moved with ADR-0003 status, so preserving the current local truth-source stack is less error-prone than pretending the integration branch is the only pending line.

## 5. Non-Claims

This branch and this review note still do not claim:

- external release;
- external-system exactly-once;
- external ACK confirmation;
- full RBAC/DLP/tenant isolation;
- field-level or row-level authorization;
- durable arbitrary external connector recovery;
- automatic R4/R5 business action execution;
- any autonomous-core verdict or autonomy claim.

