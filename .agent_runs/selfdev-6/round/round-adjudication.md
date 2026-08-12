# SELFDEV-6 Prompt-Alignment Round — Adjudication (FINAL, independent-review amended)

> Prereg: `docs/product/AGENT-OS-SELFDEV-6-prompt-alignment-prereg-2026-08-08.md`
> (frozen at 787d6261, manifest `.agent_runs/selfdev-6/manifest.json`)
> Round artifacts: `.agent_runs/selfdev-6/round/`. Date: 2026-08-08.
> Operator: kimi-cli. Independent adjudicator: kimi subagent (blind-anchored,
> no builder history) — pre-draft rulings Q1/Q2/Q3 of record. Envelope E6:
> aligned governed diff prompt (a496442) + 600s + ABAB + health gate.
> Subset byte-identical to SELFDEV-4/5.

## Verdict: NEGATIVE — with the mandatory caveat that the measurement question is UNANSWERED

Literal frozen rubric: chain pass@2 **1/12** < baseline pass@2 **2/12** →
NEGATIVE, recorded without rescue. No kill criterion fired (adjudicator
ruling: the 403 account-quota event is the frozen §3 provider-infra
consumed-attempt class, deliberately excluded from kill-1 since E3;
re-reading kill-1 post-hoc would be gate movement).

**Mandatory caveat (adjudicator-required)**: 40/48 attempts (83%) were
consumed by the provider account-quota event (HTTP 403, both arms, 10/12
tasks affected). The weather-free sample is 8 attempts on 2 tasks. The
round's measurement question — does the prompt alignment close the E5
residual — is UNANSWERED, not answered negatively. The frozen rules contain
no minimum-weather-free-sample adequacy floor; that gap is recorded in the
negative map and fixed ex-ante in E7's prereg.

File-verified accounting:

- **Baseline (24)**: 3 solved (2 tasks: django-10880 a2; django-11066
  a1+a2), 1 DIFF_INVALID, 20 INVALID_PROVIDER (403 quota).
- **Chain (24)**: 2 solved (1 task: django-11066 a1+a2, both
  independent-verifier), 2 APPLY_FAILED (django-10880 ×2 — denial reasons
  now logged: "unified diff context mismatch"), 20 INVALID_PROVIDER (403
  quota). 48 invoked markers == 48 attempt records.

## Mechanism observations (the only clean data points)

- On django-11066, the only task both arms fully sampled: chain solved BOTH
  attempts (aligned prompt produced apply-clean diffs); baseline solved
  both. n=2, thin — but the aligned-prompt chain path works end-to-end.
- django-10880 chain a1+a2: diffs PASSED format validation and failed
  `git apply --check` with logged "unified diff context mismatch" — the
  model emitted context lines that don't exist at this base commit
  (generation-side error, hypothesis-tagged as version-drift hallucination;
  the governed path processed both exactly as designed — fail-closed apply
  guard did its job). Denial-reason logging (a496442) worked end-to-end.
- The whitelist-abort driver correctly declined to abort on 403s
  (unrecognized-vs-whitelist semantics held); the round ran to completion.

## Disclosures of record

1. **Provider account-quota event**: 40 attempts consumed INVALID_PROVIDER
   (403 class; all stderrs preserved). No pause-on-403 existed in the
   frozen driver — the round ran through the wave by design.
2. **No relabel corrections needed beyond the 403 class** (37 files
   reclassified FAILED_UNCLASSIFIED → INVALID_PROVIDER with stderr
   evidence; no solve outcome touched).

## Negative map

1. **No adequacy floor in the round rubric (the structural gap)**: attempt
   accounting prices account-provisioning failures as model failures, and
   nothing forces a minimum weather-free sample — E6's NEGATIVE is 83%
   weather. Fixed ex-ante in E7 (declared adequacy floor ⇒
   INSUFFICIENT_DATA instead of NEGATIVE).
2. **Pause-on-403 accounting absent**: 403 account-quota death is
   window-wide, not attempt-local; treating it per-attempt poisons budgets.
   E7 freezes the crisp line: pause only on account-quota signatures
   (403/AUTHENTICATION_FAILED) with probe-gated resume; timeouts/
   UNAVAILABLE remain consumed (service-side weather the budget prices).
3. **Generation-side context mismatch (django-10880 ×2)**: logged and
   reproducible — the follow-up check (diff the rejected patch's context
   lines against base bytes for version drift) is recorded for the series.

## Paradigm learning (feeds E7; no gate movement)

- E7 (new prereg, adjudicator's five declarations): (1) honest motivation
  declared upfront (E6 destroyed by quota event; the re-run exists because
  the window was inadequate); (2) subset reuse with byte-identical pin;
  (3) pause-on-403 accounting change frozen explicitly + probe-gated resume
  protocol; (4) ex-ante adequacy floor (weather-free attempts below
  threshold ⇒ INSUFFICIENT_DATA, not NEGATIVE); (5) driver7.py +
  strengthened health gate (quota probe) bound in the freeze manifest.
  Disclosure of record: the re-run decision postdates E6's result; the
  mitigations are the ex-ante freeze and independent review.

## Claim boundary

NEGATIVE is restricted to: on this frozen 12-task subset under E6, the chain
solved fewer tasks than the bare baseline — with the mandatory caveat that
83% of attempts were destroyed by an account-quota event and the round's
measurement question is unanswered. NOT: a capability finding about the
aligned prompt, leaderboard comparability, HCW, product superiority,
release, or Autonomy(S,E,O,V,T) evidence.
