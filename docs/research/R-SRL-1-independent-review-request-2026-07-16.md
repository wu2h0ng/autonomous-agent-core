# R-SRL-1 Independent Methodology Review Request

> Date: 2026-07-16
> Branch: `codex/canonical-convergence-20260715`
> Harness implementation head: `f79ee6cdf21face976dd25ad52493cc7cd7a2dd0`
> Status: `P0_P1_IMPLEMENTED / NOT_FROZEN / AWAITING_INDEPENDENT_REVIEW`
> Track: `R` (research evidence)
> Authority: `docs/research/R-SRL-1-preregistration-2026-07-16.md`

## 1. Request

Request an independent methodology review of the R-SRL-1 evaluation harness before environment/scorer freeze and any result-bearing run.

The internal self-attack review (2026-07-16) listed five P0 and six P1 findings. All have been implemented. The reviewer should assess whether the current implementation closes each finding and whether the harness is ready for freeze.

## 2. Scope

### In scope

- Frozen unit loader, manifest verification, event gateway (`tests/research/r_srl_1/harness.py`).
- Hidden scorer plugin architecture (`tests/research/r_srl_1/scorer.py`).
- Fail-closed outcome evaluator integration (`tests/research/r_srl_1/outcome_evaluator.py`).
- Test/build gateway and matched-arm budget ledger.
- Baseline arm capability envelopes.
- Realistic repository fixture for sample unit `u00`.
- Help burden ledger and `HelpBurdenReceipt` computation.
- HCW recorder, category taxonomy and prototype rater CLI.
- Standardized operator protocols and prohibited-coaching validation.
- Restart state comparator and real-time wall-clock budget enforcement.
- Contract/preregistration alignment.

### Out of scope

- SRL Runtime implementation.
- Provider/model binding.
- Actual result-bearing run.
- Product-track activation or release.

## 3. Artifact manifest

| Path | SHA-256 |
|------|---------|
| `tests/research/r_srl_1/harness.py` | `sha256:87622156bbb1128d6420465ab720f1fd5f6c954b01ccb2a407a2164f62e6a5d0` |
| `tests/research/r_srl_1/scorer.py` | `sha256:fb0aee819a0f6cbdbc35ea67864c645046876dece8577ef979629be243b11583` |
| `tests/research/r_srl_1/outcome_evaluator.py` | `sha256:2bad6f91a1ebe984066a2dc879b58f54ab86c6b91ba4797654dee6ecaa44d74a` |
| `tests/research/r_srl_1/test_harness.py` | `sha256:075bfa68b304c535d724cd865e2d17e5972e3324ee17ee4bcdd06d8dfe620225` |
| `tests/research/r_srl_1/test_scorer.py` | `sha256:244963449b64a0338adecc3d4c92f79f634236af10f174f08558c23e8305840c` |
| `tests/research/r_srl_1/hcw_recorder.py` | `sha256:60049d04da36a3e37e65a4f32c5438f8f9ec75dd5a7bce5629f34c9c9639d7ed` |
| `tests/research/r_srl_1/test_hcw_recorder.py` | `sha256:00a6ce3a7d22664bf1458a2b92645e692708fe56ea83110d3b655a588781164f` |
| `tests/research/r_srl_1/operator_protocols.py` | `sha256:ba47f5ad07facbcc821776a91153bc699440d2ce6ccdb63bc461911da2b3d6f0` |
| `tests/research/r_srl_1/operator_protocols.yaml` | `sha256:96b351b60dabfa1b82a542c07731d8581789dc61a4e20b11c7532051fdc5c51f` |
| `tests/research/r_srl_1/test_operator_protocols.py` | `sha256:c89c1f5b90277e3184accfdd92a60945d8a5e5c207a540eca23718a86dbcc9d4` |
| `tests/research/r_srl_1/conftest.py` | `sha256:f72be7e2f548b82fe2d35322adc208a63cc4aaad71563a8e3a2e6056edb06b6f` |
| `tests/research/r_srl_1/pilot_hcw_on_u00.py` | `sha256:a8894a4d29f19fefa7a896b09038b7638e8e11afd97fe8ad4112b80204bcd814` |
| `tests/research/r_srl_1/fixtures/u00/unit.yaml` | `sha256:79f5318b6270b9b9469b9a10d5c1fa09429ce22299b36c7aa5fefa58492cec62` |
| `tests/research/r_srl_1/fixtures/u00/snapshot.yaml` | `sha256:0eff0eb2665ca2bc92f8b0103a1eace24b2e44fb8eef0c7cba6cd88f3857de10` |
| `tests/research/r_srl_1/fixtures/u00/mission.yaml` | `sha256:871bdf49d280fba52269ed69945519767e964e91c475a09c4436e2440eeaeadc` |
| `tests/research/r_srl_1/fixtures/u00/events.yaml` | `sha256:2ee46ad8a46d409de983eba9d452038a6da31c329915befc536da8978fc6c8d9` |
| `tests/research/r_srl_1/fixtures/u00/expected_outcomes.yaml` | `sha256:9980195281338b0f941b5c12e5b1548cd480934d3c3643cc4ff4811b3ecabc41` |
| `docs/research/R-SRL-1-preregistration-2026-07-16.md` | `sha256:69b3d13aff1f1adb6260db243622b5ae79b774a638e410f2dceb9048a8a016bc` |
| `docs/research/R-SRL-1-evaluation-harness-design-2026-07-16.md` | `sha256:8f781a49723c7a25ff53a69cc407b074dce76c4cdcd17d71785fcde733fc1d0c` |
| `docs/research/R-SRL-1-evaluation-harness-self-attack-review-2026-07-16.md` | `sha256:dacc029c0535249ed6adc2447842dd858ad84c6c05aa55b8316080035e676742` |

## 4. Verification commands

From the worktree root:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. uv run --extra product-test pytest tests/research/r_srl_1 -q
uv run ruff check tests/research/r_srl_1
uv run ruff format --check tests/research/r_srl_1
uv run --extra product-test pyright tests/research/r_srl_1
PYTHONPATH=packages/contracts/src:packages/os_core/src:. uv run --extra product-test pytest tests/product -q
```

Expected results as of 2026-07-16:

- `tests/research/r_srl_1`: 93 passed, 0 failed.
- `tests/product`: 742 passed, 1 skipped.
- `ruff check`: All checks passed.
- `ruff format --check`: already formatted.
- `pyright`: 0 errors, 0 warnings, 0 informations.

## 5. Finding closure checklist

| ID | Finding | Mitigation | Verdict requested |
|----|---------|------------|-------------------|
| P0-1 | Event gateway did not enforce matched call/token/retry budget | `BudgetLedger` with hard-stop `BudgetExceeded` | Closed? |
| P0-2 | No standardized test/build output contract | `RsrlEventGateway.run_tests/run_build` returning `TestResult`/`BuildResult` | Closed? |
| P0-3 | No enforcement that baseline arms avoid SRL-internal structures | `ArmRole`/`ArmEnvelope` with SRL type-name rejection | Closed? |
| P0-4 | Hidden scorer unspecified | `RsrlHiddenEvaluator` plugin architecture with fail-closed plugins for all 9 u00 event types (TEST_FIXED, DECOY, INTERFACE_ADAPTED, CONFLICT_RESOLVED, RESTART_EQUIVALENT, UNCERTAINTY_RESOLVED, BELIEF_UPDATED, COMMITMENT_MET, HELP_ESCALATED) | Closed? |
| P0-5 | DOE integration hand-wavy | `RsrlOutcomeEvaluator` derives `KNOWN_EVENT_TYPES` from the scorer plugin map, dispatches recomputation through it and fails closed for unknown types | Closed? |
| P1-1 | u00 fixture not a real repository lineage | `canonical-lib` fixture with project metadata, src layout, tests, xfail target | Closed? |
| P1-2 | No help burden ledger | `HelpBurdenLedger` + `HelpBurdenReceipt` | Closed? |
| P1-3 | HCW recorder unspecified | `HcwRecorder`, `HcwAnnotation`, rater CLI prototype | Closed? |
| P1-4 | No operator instruction standardization | `operator_protocols.yaml` + validation | Closed? |
| P1-5 | Restart comparator not implemented | `RestartState`, `export_state`, `compare_state` | Closed? |
| P1-6 | Wall-clock budget not real-time | `check_wall_time` at every public gateway method | Closed? |

## 6. Known limitations / negative map

- The harness is in-process and local. There is no OS-level sandbox or process kill for budget enforcement.
- `operator_minutes` in the help burden ledger are explicitly estimated, not measured from real operator time.
- The HCW recorder is a prototype; it does not record actual screen/terminal video and has not been validated with two real raters.
- `RestartState` is derived from gateway action/help logs, not from a real SRL Runtime memory image.
- Baseline arm envelope is output/envelope-level; import-time isolation is not enforced.
- The fixture is synthetic; it is representative but not a real external project lineage.

## 7. Questions for the reviewer

1. Does the current implementation satisfy each P0/P1 finding from the self-attack review?
2. Are there remaining leakage paths for baseline arms to access SRL-internal information?
3. Is the `HelpBurdenReceipt` computation aligned with the preregistration's precision/recall/burden requirements?
4. Are the operator protocols sufficient to control expectancy bias, or do they need additional constraints?
5. Is the restart comparator's expected-delta interface clear enough for the frozen event sequence?
6. Are there any freeze-blocking issues beyond the known limitations listed above?

## 8. How to report

Return a verdict document in `docs/research/` with one of:

- `ACCEPT_FOR_FREEZE` — no P0/P1 blockers; environment/scorer freeze authorized.
- `CONDITIONAL_APPROVE` — minor revisions required; list exact findings and required fixes.
- `REVISE_BEFORE_REVIEW` — material issues remain; re-review required after fixes.

Verdict must reference this manifest, the exact head under review, and the test commands above.

## 9. Non-claims

This review request does not establish autonomy, product capability, experimental validity, or a result. It is a methodology gate before freeze.
