# SELFDEV-5 Transport-Fix Round — Adjudication (FINAL, independent-review amended)

> Prereg: `docs/product/AGENT-OS-SELFDEV-5-transport-fix-prereg-2026-08-07.md`
> (frozen at 553027b, manifest `.agent_runs/selfdev-5/manifest.json`)
> Round artifacts: `.agent_runs/selfdev-5/round/`. Date: 2026-08-08.
> Operator: kimi-cli. Independent adjudicator: kimi subagent (blind-anchored,
> no builder history) — ADJUDICATION_AMENDED. Envelope E5: 600s + ABAB +
> health gate + BOTH arms free-text diff with identical extraction/validation
> (chain via ADR-0059). Subset byte-identical to SELFDEV-4.

## Verdict: NEGATIVE

On this frozen 12-task subset under E5, chain pass@2 **1/12** < baseline
pass@2 **5/12**; recorded without rescue; no kill criterion fired (the
403-quota window is the provider-infra consumed-attempt class; the abort
misfire's precondition was never met; the driver repair was pre-gate with
zero attempts consumed — both driver hashes bound: frozen-at-553027b in
`.agent_runs/selfdev-5/manifest.json` vs current).

File-verified accounting (independent adjudicator):

- **Baseline (24)**: 6 solved (5 tasks: django-10880 ×2, django-11066 a1,
  pytest-5809 a2, sklearn-13328 a1, pytest-5631 a1), 12 INVALID_PROVIDER,
  5 DIFF_INVALID, 1 APPLY_FAILED.
- **Chain (24)**: 1 solved (django-11066 a1, independent verifier),
  11 INVALID_PROVIDER, 8 DIFF_INVALID, 1 INVALID_ENVELOPE, 3 APPLY_FAILED.

Weather exposure symmetric (chain 11/24, baseline 12/24).

## Decomposition (what this NEGATIVE actually measured)

**The transport fix changed nothing** (chain weather-free: 1/9 at E4
tool-call JSON → 1/13 at E5 free-text; baseline ~50% of usable both
rounds). Same model, tasks, transport, extraction, validator. The residual
failure mass localizes:

1. **Predominantly to the governed provider prompt/response contract**
   (9/12 weather-free chain failures: 8 DIFF_INVALID + 1 INVALID_ENVELOPE,
   vs baseline 5/12 under identical transport — a ~6.5× weather-free
   solve-rate gap). The governed node's fixed prompt template and response
   contract — not governance semantics — is the leading residual.
2. **Plus an apply-gate class (3/12, CapabilityDenied, denial reason
   unlogged)** that is governance mechanics and cannot be root-caused from
   current receipts — the apply path must log denial reasons before the
   next envelope can assign this class anywhere.

NOT: a finding about governance semantics, leaderboard comparability, HCW,
product superiority, release, or Autonomy(S,E,O,V,T) evidence.

## Disclosures of record

1. **Driver sys.path repair** (pre-gate crash, zero attempts consumed,
   timestamp-verified): both driver hashes bound (frozen-at-553027b vs
   current); classification logic untouched; outcome-neutral by
   construction, consistent with the S3/S4 drift precedents.
2. **403-quota pause/resume**: provider account quota exhausted mid-round;
   3 attempts consumed INVALID_PROVIDER with 403 markers + stderr preserved
   (baseline astropy-14182 a1, baseline sympy-12419 a2, chain sympy-12419
   a2); no re-runs (48 invoked markers == 48 attempt records); recovery
   probe before resume; ABAB preserved; round completed.
3. **6 relabeled attempt files** (coarse infra_error bucket → evidence
   classes, markers + stderr preserved): 3 × 403-class INVALID_PROVIDER +
   3 × APPLY_FAILED.

## Negative map

1. **Governed prompt/contract output-validity gap (9/12 weather-free chain
   failures)** — the series' sharpest localization. Next-envelope candidate
   (new prereg): align the governed diff-mode prompt with the baseline's
   proven prompt shape, governance gates unchanged.
2. **Apply-gate observability gap (3/12)**: CapabilityDenied reasons are not
   logged in apply-path stderrs — must be logged before the next round or
   this class stays unassignable.
3. **Recurrent defect class — classifier-misfire abort (second
   consecutive)**: the driver abort keys on UNRECOGNIZED stderr — an
   inverted design. Structural fix for future drivers: abort only on a
   whitelist of genuine infra signatures (docker/workspace/manifest), never
   on unrecognized provider output.
4. **Provider weather (chain 11/24, baseline 12/24) + the 403 quota
   window**: health gate defers round start but cannot prevent mid-round
   windows; N=12 resolves only large effects under ~50% weather loss.

## Paradigm learning (feeds the next round; no gate movement)

- Localization chain of the series: mechanics (E1) → output-contract size
  (E3 600s) → format (E4 diff) → transport (E5 text+extraction) → governed
  prompt/response layer (open) + apply-gate observability (open). Next
  round (new prereg): prompt-shape alignment + denial-reason logging +
  whitelist-abort driver + pre-round health gate (carried).
- If the chain then matches the baseline on weather-free attempts, the
  harness-cost question closes positively; if not, the residual sits in the
  response-contract strictness itself.

## Claim boundary

NEGATIVE is restricted to: on this frozen 12-task subset under E5, the chain
solved fewer tasks than the bare baseline, with the decomposition above.
NOT: a finding about governance semantics, leaderboard comparability, HCW,
product superiority, release, or Autonomy(S,E,O,V,T) evidence.
