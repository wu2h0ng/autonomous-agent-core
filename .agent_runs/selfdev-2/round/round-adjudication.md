# SELFDEV-2 Benchmark Round — Adjudication (FINAL, independent-review amended)

> Prereg: `docs/product/AGENT-OS-SELFDEV-2-prereg-benchmark-round-2026-07-23.md`
> (frozen at 9843d5f, manifest `.agent_runs/selfdev-2/manifest.json`)
> Round artifacts: `.agent_runs/selfdev-2/round/`. Adjudication date: 2026-07-25.
> Operator: kimi-cli. Independent adjudicator: kimi subagent (blind-anchored,
> no builder history) — ADJUDICATION_AMENDED: verdict label upheld, all
> mechanism labels/counts corrected to per-attempt stderr evidence.

## Verdict: SUPPORTS

Observed difference on this frozen 12-task subset: chain pass@2 **9/12** >
baseline pass@2 **2/12**, strict inequality, no task-level integrity failure
(all 17 workspaces verified clean at pinned heads post-round, independently
re-verified; solves determined ONLY by the independent round-level verifier,
never by chain-internal outcomes), inside the declared oracle-localized
single-shot single-file envelope.

Two declared material caveats:

1. **Arm-window asymmetry** — the baseline arm ran 2026-07-24 in a
   degraded-provider window (20/24 attempts consumed by provider infra
   failures: 18 UNAVAILABLE + 2 explicit 180s timeouts; plus 2 diff-invalid
   output-contract failures); the chain arm ran 2026-07-25 in a healthier
   window (7/24 consumed by 180s timeouts + 1 malformed envelope). No
   same-window estimator exists, so the margin's interpretation is downgraded
   to unreliable. The 0.8s health probe is operator-asserted telemetry, not
   receipt-bound.
2. **2/12 solves are f2p-only** (`pydata__xarray-4075`,
   `pylint-dev__pylint-6903`, `p2p_vacuous` per prereg §4/§7; symmetric both
   arms).

Kill-criterion ruling (independent adjudicator): kill criterion 1 does NOT
fire — §3's frozen terminal classes include "provider infra failure" as a
per-attempt consumed class; kill-1 covers task-environment infrastructure
(workspaces/containers/daemon/manifests), of which zero failures occurred.
No downgrade-for-confound provision exists in the frozen rubric; inventing
one post-hoc would itself be gate movement.

NOT: leaderboard comparability, contamination-free measurement, HCW
reduction, product superiority, release, or Autonomy(S,E,O,V,T) evidence.

## Per-task receipts (file-verified mechanism labels)

| Task | Baseline a1 | Baseline a2 | Chain a1 | Chain a2 | Solved (B/C) |
|---|---|---|---|---|---|
| astropy__astropy-13453 (17.7KB) | INVALID (180s timeout) | INVALID (180s timeout) | INVALID (180s timeout) | INVALID (180s timeout) | – / – |
| django__django-13670 | INVALID (diff invalid) | INVALID (UNAVAILABLE) | SOLVED | SOLVED | – / ✓ |
| django__django-14089 | INVALID (UNAVAILABLE) | INVALID (UNAVAILABLE) | SOLVED | SOLVED | – / ✓ |
| matplotlib__matplotlib-22719 | INVALID (UNAVAILABLE) | INVALID (UNAVAILABLE) | SOLVED | SOLVED | – / ✓ |
| psf__requests-1766 | INVALID (UNAVAILABLE) | INVALID (UNAVAILABLE) | SOLVED | SOLVED | – / ✓ |
| pydata__xarray-4075 | INVALID (diff invalid) | SOLVED | SOLVED (f2p-only) | SOLVED (f2p-only) | ✓ / ✓ |
| pylint-dev__pylint-6903 | INVALID (UNAVAILABLE) | INVALID (UNAVAILABLE) | SOLVED (f2p-only) | SOLVED (f2p-only) | – / ✓ |
| pylint-dev__pylint-7080 | INVALID (UNAVAILABLE) | INVALID (UNAVAILABLE) | INVALID (180s timeout) | INVALID (180s timeout) | – / – |
| scikit-learn__scikit-learn-14141 | SOLVED | INVALID (UNAVAILABLE) | SOLVED | NOT_SOLVED (f2p exit=4) | ✓ / ✓ |
| sphinx-doc__sphinx-10449 | INVALID (UNAVAILABLE) | INVALID (UNAVAILABLE) | SOLVED | INVALID (180s timeout) | – / ✓ |
| sphinx-doc__sphinx-10466 | INVALID (UNAVAILABLE) | INVALID (UNAVAILABLE) | INVALID (malformed envelope) | SOLVED | – / ✓ |
| sympy__sympy-13974 (13.6KB) | INVALID (UNAVAILABLE) | INVALID (UNAVAILABLE) | INVALID (180s timeout) | INVALID (180s timeout) | – / – |

Totals: baseline — 2 solved, 18 UNAVAILABLE, 2 explicit 180s timeouts,
2 diff-invalid (24/24). Chain — 15 solved, 7 timeouts, 1 malformed envelope,
1 NOT_SOLVED (24/24; 16 completed governed flows).

## Driver-level corrections (documented; ruled lawful by the adjudicator)

1. Driver subcommand bug (`benchmark-run-chain`) — 2 argparse non-attempts,
   provider node never invoked ⇒ non-consumed, fixed and rerun. Ruling:
   lawful; recommendation recorded: retain non-attempt artifacts in future
   rounds rather than deleting.
2. 7 attempt-2 runs blocked by the fail-closed dirty-workspace check
   (pre-invocation, check did its F-C job) ⇒ non-consumed; workspaces
   restored, rerun as genuine attempts. Restoring between attempts is now
   part of the driver.

## Negative map (corrected to evidence)

1. **Frozen-envelope binding constraint**: chain-arm timeouts were 4/4 on
   the two ≥13.5KB tasks (astropy 17.7KB, sympy 13.6KB) and 3 more on
   ≤7KB tasks (pylint-7080 6.0KB ×2, sphinx-10449 7.0KB ×1) — the large-file
   ceiling is structural (180s × K2 reasoning latency × complete-file
   output); small-file timeouts show residual window variation.
2. **Baseline-window degradation (20/24)**: dominated by provider-health
   window (18 UNAVAILABLE URLError + 2 timeouts), not task difficulty — the
   same tasks later completed on the chain arm in a healthier window.
3. **sklearn chain a2 (f2p exit=4)**: the only completed-attempt solve
   failure; the provider's second patch made the test module uncollectable.
4. **Output-contract failures**: 2/24 baseline diff-invalid, 1/24 chain
   malformed envelope — the prior rounds' failure classes persist at low
   rate.

## Paradigm learning (feeds the NEXT round's envelope; no gate movement)

- Within a healthy window the chain solved 15/16 completed attempts —
  governed-chain correctness is NOT the bottleneck; the envelope's
  time/output contract is. Next-round candidates (new prereg): longer
  provider timeout or a timeout-exempt attempt class; diff-format patch
  channel for the chain; ABAB interleaved arm scheduling to eliminate the
  window confound structurally (baseline-first ordering created it here).
- The diff-vs-full-file asymmetry ran against the chain and the chain still
  won: the conservative-direction design held, strengthening (not weakening)
  the narrow claim within the envelope.

## Claim boundary (verbatim from the amended adjudication)

SUPPORTS is restricted to: observed difference on this frozen 12-task
subset, inside the declared envelope, with the two declared caveats. NOT:
leaderboard comparability, contamination-free measurement, HCW reduction,
product superiority, release, or Autonomy(S,E,O,V,T) evidence.
