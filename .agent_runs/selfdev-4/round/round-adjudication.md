# SELFDEV-4 Format-Symmetric Round — Adjudication (FINAL, independent-review amended)

> Prereg: `docs/product/AGENT-OS-SELFDEV-4-format-symmetric-prereg-2026-07-26.md`
> (frozen at 5fa6f69, manifest `.agent_runs/selfdev-4/manifest.json`)
> Round artifacts: `.agent_runs/selfdev-4/round/`. Date: 2026-08-07.
> Operator: kimi-cli. Independent adjudicator: kimi subagent (blind-anchored,
> no builder history) — ADJUDICATION_AMENDED. Envelope E4: 600s + ABAB +
> BOTH arms unified-diff (chain via ADR-0058). Fresh 12-task subset.

## Verdict: NEGATIVE

On this frozen 12-task subset under E4, chain pass@2 **1/12** < baseline
pass@2 **4/12**; recorded without rescue. No kill criterion fired (ruling:
the mirror-wipe infra event damaged 1 task = 8.3% < 25%; the operator
over-budget violation is outcome-neutral by construction — self-inflicted
harm to the chain, incapable of manufacturing SUPPORTS).

File-verified accounting (independent adjudicator):

- **Baseline (24)**: 5 solved (django-11066 ×2, pytest-5631 a1, pytest-5809
  a2, sympy-12419 a1 → 4 tasks), 13 INVALID_PROVIDER, 4 DIFF_INVALID,
  1 APPLY_FAILED, 1 INVALID_INFRA (mirror wipe).
- **Chain (25 consumed = 22 driver + 3 disclosed over-budget operator smokes
  on astropy-14182, which pre-empted that task's driver slots via
  skip-on-existing — no ABAB for this task)**: 1 solved (django-10880 a2,
  independent verifier), 16 INVALID_PROVIDER, 5 DIFF_INVALID,
  2 INVALID_ENVELOPE, 1 APPLY_FAILED.

## Decomposition (what this NEGATIVE actually measured)

Weather-free attempts: baseline usable 11 (5 solved / 4 DIFF_INVALID /
1 APPLY_FAILED / 1 INVALID_INFRA); chain usable 9 (1 solved / 5 DIFF_INVALID
/ 2 INVALID_ENVELOPE / 1 APPLY_FAILED). Weather exposure: baseline 54%
(13/24); chain 59% driver-only (13/22), 64% total consumed (16/25) — ABAB
near-symmetric except astropy-14182 (no interleave due to the smoke files
occupying its driver slots).

8/9 weather-free chain attempts failed on the tool-call JSON diff transport
(malformed envelopes, invalid hunks, apply-time context mismatch) — versus
the chain's complete-file contract at E3 (19/20 completed attempts solved)
and the baseline's free-text diff channel (5/11 usable solved) under the
same weather. This NEGATIVE measures a HARNESS-TRANSPORT REGRESSION, not
governance value, not the diff concept.

## Disclosures of record

1. **Operator over-budget violation (astropy-14182)**: 3 chain smokes vs a
   2-attempt budget (504/504/MALFORMED — all consumed INVALID_PROVIDER,
   `operator_error` flags on file), task INVALID, founder-ruled continuation
   2026-07-28 (`round/astropy__astropy-14182/operator-note.md`).
2. **/tmp mirror-wipe infra event**: mirrors wiped twice mid-round; 1
   consumed baseline attempt INVALID_INFRA; django-10880 chain a2 was
   env-damaged BEFORE provider invocation — deleted and lawfully rerun under
   the E1/E3 pre-invocation precedent (the rerun produced the round's only
   chain solve with genuine independent-verifier evidence; marker/record
   ledger consistent). Mirrors rebuilt durable (~/.cache); all 17 workspaces
   made object-self-contained. **New rule** (adjudicator): non-attempt
   artifacts are RETAINED from now on — the E1 retention recommendation was
   ignored twice and is now binding for future rounds.
3. **10 relabeled attempt files** (driver's coarse infra_error bucket →
   evidence classes, `reclassified` markers + original stderrs preserved):
   APPLY_FAILED ×2, INVALID_INFRA ×1, DIFF_INVALID ×5, INVALID_ENVELOPE ×2.
4. **solve4.py mid-round replacement (disclosed, adjudicated
   outcome-neutral)**: the frozen solve4.py was non-functional for this
   round (it pointed at `.agent_runs/selfdev-2/round` and extracted
   content-only candidates — a freeze defect). The replacement (round path +
   diff-candidate routing) is in the evidence-production path; the verdict
   is unaffected because solve determination flows through the unchanged
   `run_benchmark_verifier`. Both hashes are bound: frozen-at-5fa6f69
   (`.agent_runs/selfdev-4/manifest.json`) and current. Freeze §5 gains a
   solver smoke-check for future rounds.

## Negative map

1. **Chain diff-mode tool-call contract fragility (8/9 weather-free
   failures)**: the governed tool-call JSON channel (arguments_json with
   `{path, diff}`) is materially harder for long diffs than free text —
   extra envelope keys, malformed hunk bodies, apply-time context mismatch.
   Primary new finding.
2. **Provider weather wave (chain 16/25, baseline 13/24 consumed)**:
   RemoteDisconnected/504/timeout/malformed clustered in the window; ABAB
   kept exposure near-symmetric but a >50% loss rate destroys statistical
   resolution at N=12.
3. **Baseline free-text diff robustness (5/11 usable solved)**: supports
   text-channel diff + server-side extraction as the robust transport.
4. **Freeze-defect escape (solve4.py)**: §5 re-verification covered
   workspaces/images/daemon but not mechanism-file sanity; a solver
   smoke-check is now required at freeze.

## Paradigm learning (feeds the next envelope; no gate movement)

- Next envelope candidates (new prereg): chain diff via FREE-TEXT output +
  server-side extraction inside the governed provider node (keep ADR-0058's
  diff semantics, change the transport), or revert the chain to
  complete-file with the declared asymmetry kept. The S4 evidence says the
  tool-call JSON transport is the regression source.
- Pre-round provider health gate: with >50% weather loss N=12 cannot resolve;
  screen the window before starting (probe suite), or grow N.
- The E1/E3 adjudicator retention recommendation is now a binding rule:
  non-attempt artifacts are retained.

## Claim boundary

NEGATIVE is restricted to: on this frozen 12-task subset under E4, the chain
with the ADR-0058 tool-call diff transport solved fewer tasks than the bare
baseline, with the decomposition above. NOT: a finding about governance
value or complete-file mode, leaderboard comparability, HCW, product
superiority, release, or Autonomy(S,E,O,V,T) evidence.
