# P-SRL-RUNTIME-1 M0 Verification

## Environment
- Worktree: `/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/p-srl-runtime-1-m0-20260716`
- Branch: `codex/p-srl-runtime-1-m0-20260716`
- Base: `e50eaac` (`docs(state): record P-SRL-RUNTIME-1 design candidate`)
- Python: 3.12.13

## M0 invariant tests
```
$ python -m pytest tests/product/test_srl_runtime_invariants.py -v
============================== 14 passed in 0.22s ===============================
```

Passed:
- `test_i4_standing_mission_parent_digest_mismatch`
- `test_i8_assessor_policy_digest_mismatch`
- `test_i11_help_burden_exceeded`
- `test_i12_duplicate_event_deduped`
- `test_i13_binding_budget_exhausted`
- `test_i14_no_capability_grant_from_srl_organ`
- `test_i15_untrusted_outcome_rejected`
- `test_i16_mandate_not_active_rejected`
- `test_i18_read_only_binding_rejects_write_effect`
- `test_i20_after_help_expiry_only_continuable_work`
- `test_i21_help_burden_computed_by_separate_ledger`
- `test_i22_w1_w2_cannot_mutate_mandate`
- `test_i23_same_instance_cannot_propose_and_accept`
- `test_i25_cross_restart_replay_idempotent`

## Static checks (M0 files)
```
$ ruff check packages/os_core/src/agent_os_core/srl_*.py tests/product/test_srl_runtime_invariants.py packages/contracts/src/agent_os_contracts/srl_help.py
All checks passed!

$ ruff format --check packages/os_core/src/agent_os_core/srl_*.py tests/product/test_srl_runtime_invariants.py packages/contracts/src/agent_os_contracts/srl_help.py
14 files already formatted

$ .venv/bin/python -m pyright packages/os_core/src/agent_os_core/srl_*.py packages/contracts/src/agent_os_contracts/srl_help.py
0 errors, 0 warnings, 0 informations
```

## Product regression
```
$ python -m pytest tests/product -q
756 passed, 1 skipped in 37.82s
```

## Project-wide type check
```
$ .venv/bin/python -m pyright
0 errors, 0 warnings, 0 informations
```

## Notes
- Project-wide `ruff check .` reports pre-existing lint issues in `experiments/`, `adapters/`, and `docs/research/` that are unrelated to M0; M0-specific files are clean.
- No provider calls, database writes, TaskService integration, or capability-grant creation occurred.
