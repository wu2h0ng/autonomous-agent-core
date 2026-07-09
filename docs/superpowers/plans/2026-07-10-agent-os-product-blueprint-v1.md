# Agent OS Product Blueprint v1 Finalization Plan

> Date: 2026-07-10
> Track: Product definition / docs-only
> Branch: `codex/agent-os-product-blueprint-v1`

## Goal

Finalize one authoritative product blueprint that makes this repository the complete Agent OS monorepo, preserves the evidence boundaries of the existing research program, audits each research line against real product needs, and removes the obsolete statement that this repository is only a non-product research object.

## Deliverables

1. Create `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md` as the product authority.
2. Define the dual-track layered monorepo, canonical product objects, user surfaces, market-parity layer, research moat, promotion gate, and real-comparison gates.
3. Record an evidence-limited research portfolio audit and explicit continue/revalidate/park decisions.
4. Align repository entry documents without altering experiment results or claiming runtime delivery.
5. Verify links, stale identity statements, YAML syntax, tests relevant to documentation integrity, and Git scope.

## Files

- Create: `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md`
- Update: `README.md`
- Update: `AGENTS.md`
- Update: `CLAUDE.md`
- Update: `docs/PRD.md`
- Update: `docs/CURRENT_STATE.yaml`
- Update: `docs/PROJECT_PLAN.md`
- Update: `ROADMAP.md`
- Update: `ENGINEERING.md`
- Update: `.github/pull_request_template.md`
- Update: `codebase_index.md`

## Verification

```bash
ruby -e 'require "yaml"; YAML.load_file("docs/CURRENT_STATE.yaml"); puts "CURRENT_STATE YAML OK"'
test -f docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md

rg -n "不是业务产品|deployment projection, not the main|企业 OS.*降级投影" \
  README.md AGENTS.md CLAUDE.md docs/PRD.md docs/PROJECT_PLAN.md ROADMAP.md codebase_index.md

PYTHONPATH=src python -m unittest discover -s tests -v
git diff --check
git status --short
```

The full test run verifies that docs-only identity changes did not disturb the reconciled research tree. A passing suite remains research/runtime evidence only; it does not establish product completion.

## Execution Record

- Blueprint requirements/authority scan: passed.
- Stale authoritative identity scan: passed.
- `docs/CURRENT_STATE.yaml` parse: passed.
- Full research regression: `Ran 1237 tests in 175.560s`, `OK (skipped=16)`.
- Skip explanation: 13 existing sentinels plus 3 optional `TestReplogle2022Preprocessing` methods because `anndata/numpy` are not installed in this worktree environment.
- Product capability status: blueprint finalized; Product Track runtime remains unimplemented.
