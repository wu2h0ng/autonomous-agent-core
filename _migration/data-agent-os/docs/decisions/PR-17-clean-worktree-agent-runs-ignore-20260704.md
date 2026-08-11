# PR-17 Clean Worktree Agent Runs Ignore (2026-07-04)

- Status: verified locally / origin/main push remains HOLD / no release
- Layer: deployment / release-candidate maintenance hygiene
- Verified local head: `bfcc0ce22e57a0d21242a35dd3cba15ab4bb51ab`

This record closes the long-running local worktree hygiene issue where generated
`.agent_runs/` artifacts appeared as untracked noise after every local
verification run. The artifacts are local runner/CI outputs and are referenced
through decision records as non-mergeable evidence, not source files.

## Verified Surface

- `.gitignore` now ignores `.agent_runs/`.
- `git ls-files .agent_runs` returns no tracked files, so no tracked source or
  durable decision artifact is hidden by the new ignore rule.
- Plain `git status --short --branch` is clean on tracked files after the
  ignore rule.

## Commands

```bash
git ls-files .agent_runs
git check-ignore -v .agent_runs .agent_runs/eval-threshold-report/golden-threshold-report.json
git status --short --branch
make current-state-verification-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make rc-branch-verification-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make push-authorization-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

## Observed Results

- `.agent_runs/` has no tracked files.
- `.gitignore:17:.agent_runs/` ignores both the directory and generated
  threshold-report JSON.
- Tracked worktree is clean at `bfcc0ce`.
- `make current-state-verification-check`: passed against PR-16.
- `make rc-branch-verification-check`: passed and confirmed remote RC branch
  `rc/phase-1-controlled-pilot-20260704` at
  `b8834a644018e070e372be149fb758a928c7a242`, remote main at
  `dba87bc35ae2c7be3dfbcc022c64c0a04cbf9171`, and no release/rc tag.
- `make push-authorization-check`: exited 2 under `DEPLOYMENT_PUSH: HOLD` for
  current head `bfcc0ce22e57a0d21242a35dd3cba15ab4bb51ab`, preserving the
  origin/main promotion block.

## Non-Claims

This cleanup does not:

- change product runtime behavior;
- push to `origin/main`;
- create a release tag;
- publish an external release or customer-facing claim;
- enable automatic R4/R5 business-action execution.
