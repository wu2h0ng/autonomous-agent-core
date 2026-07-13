# SPINE-E2E-1 Result

Date: 2026-07-13

Track: Product evaluation

Verdict: **INVALID — instrumentation/protocol misclassification, not Product failure**

## Result boundary

The fresh, frozen `SPINE-E2E-1` run did not produce a valid end-to-end verdict. It must not be reported as `PASS`, Product `NOT_PASS`, or long-horizon evidence. No `evaluation/result.json` was fabricated after the failure.

- Candidate target: `8bd5aec4676df8cb6dad7a4ae31be30f5d17a34e`
- Runner target: `804c8d54bf5b78d9d850edb452db4affe3c1cd22`
- Frozen mechanisms: 49, drift zero at the failure boundary
- Frozen context hash: `1e343fe6565a0c5efb8222fb408b952be4699ab904ca3591a3cc14d5e10aa972`
- Phase chain: `prepare_started` through `resume_failed`, ordinals `0..7` continuous
- Provider chain: 24 accepted, zero rejected; 12 scenario digests each called exactly twice
- External verification with the required result path correctly fails with `result-missing:result path not found`

## Mechanical evidence

The time gates reached before the defect were satisfied:

- interrupt start to probe completion: `2.538661792s <= 60s`
- interrupt completion to resume start: `368.153604041s >= 360s`
- prepare start to resume start: `437.5562s <= 1800s`

Evidence digests:

- prereg lock: `c06fac42415b6bf1e848c95f3abec11760c4a7a12e824a39cbe6a5ccadcdd19a`
- canonical prereg/spec: `8ed7093b86750e3156f2c6f3744fbe751f6ec26949ed94190de42e64207a5849`
- source spec: `2916c0029c902de468bdc9f62fa4b3412f712a40e9558ec30e6071fb3d89262f`
- phase ledger: `ef7ad1f9adc67e3ca645ee1409683e975fb988986f4dfb8d31757ef797363a45`
- provider ledger: `a63725215d335b5568a396a392878718418a7e0fc146bb5dc67a4df7c02a2d1b`
- resume failure: `b05146a1936b95d375eef0f844c5dd2d60adfafb220c312f010d3b34de42f2fe`

## Root cause

The frozen helper counted all `ACTION_RECEIPT_RECORDED` events, while the frozen resume protocol treated an increase in that total as a duplicated apply receipt. In the first resumed scenario, `st_reverse`, resume correctly added a `workspace.run_tests` receipt. The `workspace.apply_patch` receipt remained exactly one; tests exited zero; the outcome was `VERIFIED` with score `1`; and the case reached `RUN_SUCCEEDED`. The protocol nevertheless raised `RuntimeError: resume duplicated the completed apply receipt`, mapped to `INVALID_INTERNAL_ERROR`.

The remaining 11 interrupted scenarios did not resume, so the full claim cannot be adjudicated.

## Operational notes

Two initial invocations failed before evaluation genesis because the Product import path was absent; they produced no evaluation artifacts. During prepare, the embedded runner used the Product virtual environment, which lacked PyYAML; the exact write-once prepare anchor event was completed with the fixed runner worktree and system Python without rerunning the Product phase. These operational defects did not change the frozen Product evidence or the final `INVALID` classification.

## Binding disposition

- Preserve this run unchanged as `INVALID`.
- Do not rerun, rescue, retune, weaken a gate, or post-hoc construct a result.
- `SPINE-E2E-1 PASS` is absent.
- `LH-RECOVERY-1A D2` remains blocked and is not constructed.
- Parent `LH-RECOVERY-1` remains blocked and was not run.
- Any successor requires apply-specific receipt accounting, a new preregistration and freeze, and a fresh run.

Independent result review: `ACCEPT INVALID` under read-only mechanical adjudication.
