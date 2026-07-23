# AGENT-OS-SELFDEV-2 — Public-Benchmark Baseline Round: Design Packet (for CTO gate)

> Status: `DESIGN_ONLY` — requires founder/CTO gate before any implementation.
> Date: 2026-07-23. Author: kimi-cli session.
> Supersedes the evaluation method (not the receipts) of round
> SELFDEV-MT-20260723 (adjudicated NEGATIVE, `.agent_runs/selfdev-mt-20260723/round-adjudication.md`).

## 1. Why this change, stated honestly

Founder direction (2026-07-23): use a public benchmark as the baseline instead of
matched founder/model+tools HCW baselines.

What a public benchmark CAN measure (claim class A — capability/comparability):
whether the SELFDEV chain (Agent OS governance + real provider) solves real
GitHub-issue tasks at a rate comparable to published same-model scaffolds. This
is the irreducibility/weak-baseline-theater check the MT round could not answer.

What it CANNOT measure (claim class B — the project's constitutional metric,
AGENTS.md §9B): whether the chain reduces the operator's hidden cognitive work
on the operator's own tasks. Published numbers contain no HCW for our operator.
Per constitution §6, A cannot backfill B. Resolution: this round's PRIMARY
metric is solve-rate comparability (A); HCW accounting (B) is retained as a
secondary ledger (operator minutes/interventions per task) at zero founder cost
— the founder does no manual fixes in this design.

## 2. Verified facts (checked 2026-07-23)

- Our provider model is `kimi-k2-0711-preview`. Kimi K2's published SWE-bench
  Verified score is ~71.2% (vendor scaffold; moonshotai.github.io/Kimi-K2 and
  press coverage). This is the external comparator for the SAME model — the
  strongest cheap baseline available.
- SWE-bench Verified (500 tasks) is widely regarded as contamination-inflated;
  SWE-bench Pro (Scale AI, 1,865 tasks incl. private repos) and SWE-rebench
  (fresh, decontaminated pipeline) exist. The Verified↔Pro delta is ~30 points
  for frontier models. Any Verified-based number we produce must carry a
  contamination limitation note.
- SELFDEV-S1 admission today accepts ONLY the Agent OS repo
  (`_AGENT_OS_REPOSITORIES`, allowlisted prefixes, `python -m pytest`
  allowlist). Public-benchmark tasks are external repos with foreign test
  environments: admission is a CONTRACT change requiring an ADR (§5 below).

## 3. Round design (summary)

- Task source: SWE-bench Verified, filtered to tasks whose gold patch touches
  exactly ONE file (fits the current single-file replacement chain) and whose
  repo is pip-installable in a plain venv (django/sympy/requests/pytest-style;
  no conda-only or compiled-toolchain repos). Candidate count after filtering
  is expected to be ample; selection is FROZEN before any run.
- Subset: N=12 tasks, selected by a frozen deterministic rule (e.g. sort by
  instance_id, take first 12 passing the filters). Selection rule + full task
  list + per-task environment manifest pinned in the prereg manifest.
- Information parity (same rule as previous rounds, now matching SWE-bench's
  own setup): the provider arm sees the issue text plus the bytes of the gold
  patched file(s) at base commit, and the FAIL_TO_PASS test node ids. It does
  NOT see the test patch contents or the gold patch. (SWE-bench agents see the
  issue; FAIL_TO_PASS ids are disclosed in our statement because our verifier
  runs them and the MT-round fairness rule requires contract visibility.)
- Provider chain: unchanged frozen argv (`selfdev-run-provider --approve
  --duration-seconds 3600 --statement <issue+contract>`), 2 attempts per task
  (budget tightened from 3: benchmark tasks are heavier; attempt accounting and
  INVALID/NOT_MET classes unchanged from the MT prereg).
- Comparators:
  1. PRIMARY cheap baseline: same model, same provider account, bare one-shot
     scaffold (issue + file bytes in, unified-diff out, no Agent OS chain, no
     approval/eval loop) on the identical frozen subset. This answers "is the
     governance chain better than just asking the model" — the constitution's
     strong-cheap-baseline requirement, fully automatable, zero founder HCW.
  2. CONTEXT ONLY: published K2 Verified 71.2% (vendor scaffold, full 500,
     different harness) — cited for orientation, never used as the gate.
- Metrics: per-task solve (FAIL_TO_PASS green + PASS_TO_PASS green) within
  budget; subset solve rates for chain vs cheap baseline; operator HCW ledger
  (secondary, claim class B); attempt/invalid distribution (negative map).
- Verdict: SUPPORTS the narrow claim ("the Agent OS chain beats a bare
  one-shot same-model scaffold on this frozen subset") iff chain solve rate >
  cheap-baseline solve rate with no task-level integrity failure; otherwise
  MIXED/NEGATIVE as recorded. Kill criteria: env failure on >25% of tasks
  (round INVALID — infrastructure, not capability), any fixture/manifest drift
  (INVALID), or cheap-baseline data loss.
- Cost estimate: 12 tasks × (≤2 chain attempts + 1 cheap-baseline call) ×
  ~10-20K tokens ≈ under 1M tokens; wall ~1-2h sequential. No founder minutes.

## 4. Required product changes (ADR-level, before the prereg freeze)

1. ADR: SELFDEV admission of external benchmark tasks. Scope: a new
   `SelfDevelopmentBenchmarkTask` admission path (separate from
   `_AGENT_OS_REPOSITORIES`), binding: repo url + base commit + environment
   manifest + FAIL_TO_PASS/PASS_TO_PASS sets + issue text hash. The existing
   Agent OS admission is untouched.
2. Environment builder: per-task venv provisioning + verifier runner that
   executes the declared test node ids in the task workspace (our sandbox
   already runs shell in isolated workspaces; needs deps install step).
3. Verifier: SWE-bench style FAIL_TO_PASS + PASS_TO_PASS evaluation instead of
   full-file scoped pytest. (Current `python -m pytest` allowlist stays for
   Agent OS targets.)
4. Cheap-baseline runner: minimal script calling the same provider with the
   same inputs, producing a unified-diff candidate + same verifier. No chain,
   no approval, no receipts.
5. All five land behind the same gates as any product change: tests first,
   targeted pytest/ruff/pyright, no CI bypass.

## 5. Boundaries (unchanged)

- Not a leaderboard claim: a 12-task subset supports no public ranking claim.
- Contamination: Verified is likely inside K2's training distribution; the
  subset result is an upper bound on novelty-free execution. A follow-up may
  use SWE-rebench recent-vintage tasks if this round shows the machinery works.
- No HCW-reduction claim from this round (class A only); the HCW ledger is
  recorded for later rounds on the operator's own task portfolio.
- C7/approval/verifier semantics unchanged; the chain keeps exact-digest
  approval and fail-closed compensation per task.

## 6. Execution sequence after CTO gate

1. ADR draft (external benchmark admission) → independent review → implement
   §4 items 1-4 with tests.
2. Dataset acquisition + frozen subset selection + env manifests.
3. New prereg (subset, statements, comparators, budgets, verdicts, kill rules,
   exact-content manifest) → independent reviewer → freeze commit.
4. Round: cheap baseline first (cheap, fast), then chain attempts per task.
5. Receipts, adjudication, negative map, paradigm learning, state sync.

## 7. Decision points for the CTO gate

- D1: approve the claim-class split (benchmark comparability primary, HCW
  ledger secondary) — yes/no.
- D2: task source — SWE-bench Verified single-file subset (recommended:
  pragmatic, same-model published comparator exists) vs SWE-rebench vintage
  slice (cleaner contamination, needs collection pipeline, +1-2 days).
- D3: subset size N=12 and 2-attempt budget (cost/latency trade-off) — yes/no.
- D4: authorize the §4 ADR scope (external admission + env builder + verifier
  + cheap-baseline runner) as the next Product/Translational package.
