# AGENT-OS-SELFDEV-1 — Multi-Target Non-Synthetic Comparison Prereg (Freeze Draft)

> Status: `DESIGN_ONLY` — no result-bearing run is authorized by this document until
> the freeze mechanics in §9 complete (independent reviewer, exact-content manifest,
> freeze commit). `builder_id != reviewed_by` is mandatory.
> Date: 2026-07-23
> Builder: kimi-cli session (wd_ai-agent-projects, 2026-07-22/23)
> Reviewer: kimi subagent (fresh context, blind-anchored per RR-0031, no builder run
> history). Round 1: CHANGES_REQUESTED (F-1 attempt-consumption/rejection-sampling
> hole; F-2 imprecise freeze-head reference). Round 2 (post §5/§6/§8 amendments):
> TECHNICAL_APPROVE. Round 3 (post §8 T1 carve-out amendment): TECHNICAL_APPROVE.

## 1. Purpose and claim boundary

Question: across a small declared set of non-synthetic Agent OS repository targets,
does the SELFDEV provider arm (real Kimi/OpenAI-compatible provider behind the
first-class `selfdev-run-provider` seal/approve/resume CLI path) reach VERIFIED
within a fixed attempt budget with lower human cognitive work (HCW) than matched
founder/model+tools baselines, when both arms see the same acceptance contract?

This is Translational/Product evidence about mechanical execution under a
pre-digested exact contract. It is NOT task-understanding evidence, NOT a benchmark,
NOT product superiority, NOT release, and NOT `Autonomy(S,E,O,V,T)` evidence.
A supportive round licenses only one claim: "for these four frozen targets, the
provider arm executed mechanical fixes with less recorded human work."

## 2. Prior negative/result map (feeds this design; not re-litigated)

- Synthetic envelope smoke: VERIFIED, verdict SELFDEV_HCW_LOWER
  (`.agent_runs/selfdev-real-provider-20260722`) — dataflow evidence only.
- T1 blind attempt: NOT_MET (provider never saw the acceptance contract)
  (`.agent_runs/selfdev-real-target-evidence-overlap-20260722-rerun`).
- T1 fair attempts (contract in provider-visible statement): attempt-1 rejected
  fail-closed for a malformed tool-proposal envelope; attempt-2 VERIFIED, receipt
  `d5af61e2a358c7a40879ebd0f3ccfe2546f5299d4e16c883585f77c96cccd143`
  (`.agent_runs/selfdev-real-target-evidence-overlap-20260722-fair`).
- Observed provider envelope compliance so far: 1 malformed in 2 fair samples.
  This motivates the attempt-budget accounting in §5 (malformed envelopes are
  recorded consumed attempts, never hidden).

## 3. Arms and fairness

- Baseline arm: founder (+ model/tools) performs the fix manually in the isolated
  workspace against the red fixture, records `operator_intervention_count` and
  `hcw_minutes` (start: reading the fixture; stop: verifier green), then runs
  `selfdev-baseline-capture`. The baseline operator MUST NOT read provider-arm
  outputs before recording. T1 baseline is already frozen
  (`34614e2df74b5284ef87a054793e60271eb171185a9983dde4fd730787d2c235`).
- Provider arm: `agent-os selfdev-run-provider <spec> --baseline-record <record>
  --approve --duration-seconds 3600 --statement <target contract>` on a fresh
  sqlite per attempt. The provider sees only the target file bytes plus the
  statement (execution.py:320 injects the statement as the goal).
- Both arms are evaluated by the identical frozen fixture and verifier command.
- Information parity rule: anything the baseline operator can read in the fixture
  (exact error codes, exact substrings, behavioral contract) MUST appear in the
  provider-visible statement. Statements are frozen in §7/§10.

## 4. Target set (4 targets, fixed; no substitution)

Difficulty tiers are declared upfront so a round cannot be won on easy targets
silently. T1 is a carry-over with full prior history disclosed (§2); its provider
samples under this prereg are NEW attempts on fresh tasks.

| ID | File | Change (real product gap) | Tier |
|----|------|---------------------------|------|
| T1 | `packages/os_core/src/agent_os_core/self_development.py` | Reject shared baseline/SELFDEV evidence_refs in comparison receipts (carry-over, DONE at ce9cb54) | medium |
| T2 | `packages/os_core/src/agent_os_core/self_development.py` | Reject duplicate evidence_refs within a single record (`_validate_evidence_refs` currently passes `("a","a")`) | low |
| T3 | `apps/cli/__main__.py` | `selfdev-run-provider` prints structured `REAL_PROVIDER_RUN_FAILED` JSON instead of a traceback when `run_task` raises `RunExecutionError` (gap hit by fair attempt-1) | low-medium |
| T4 | `packages/os_core/src/agent_os_core/recovery.py` | `build_recovery_snapshot` rejects event streams whose payloads carry conflicting non-empty `run_id` values (currently keeps the first silently) | low-medium |

Each target gets its own isolated worktree branched from the freeze head (§8),
its own spec JSON, and its own pytest.ini scoping the verifier to the fixture's
test file (T1/T2: `tests/product/test_agent_os_self_development.py`; T3:
`tests/product/test_cli_surface.py`; T4: `tests/product/test_recovery_projection.py`).

## 5. Sampling, attempt budget, and HCW accounting

- Attempt budget: at most 3 provider attempts per target, each on a fresh task
  and fresh sqlite. An attempt is consumed the moment a sealed task invokes the
  provider node (any `run_task` call that reaches the provider node), regardless
  of terminal state. Terminal classes: VERIFIED; verifier non-zero exit
  (NOT_MET); malformed proposal envelope (fail-closed at execution.py:1141);
  provider infra failure (UNAVAILABLE/disconnect); and ANY other termination —
  including operator interrupt, local crash, or abandonment at WAITING_APPROVAL —
  which is classified as a consumed `INVALID` attempt and must be logged in the
  run summary. Previewing a provider proposal and discarding it (omitting
  `--approve`, or abandoning a WAITING_APPROVAL run) is therefore NOT free: it
  consumes an attempt and counts as one operator intervention.
- Target selfdev outcome: VERIFIED if any attempt within budget completes with
  observed outcome VERIFIED; the run-record binds that attempt's evidence and
  MUST list every consumed attempt in the run summary. If the budget is exhausted
  without VERIFIED, the target outcome is the final attempt's outcome
  (`NOT_MET`/`INVALID`), recorded without rescue.
- Selfdev HCW minutes: total operator (human) minutes across ALL attempts of the
  target (launching, reading failures, deciding to retry). Provider/machine
  latency is wall clock, not HCW. Operator interventions: 1 per attempt that
  reaches approval (`--approve` pre-authorization), plus 1 per abandon/preview
  decision (any consumed attempt that reached WAITING_APPROVAL without
  completing the approval continuation), plus 1 per manual retry decision.
  Baseline HCW: existing convention (§3). HCW minutes on both arms are
  operator-declared; receipts bind content digests, not time truth — the claim
  in §1 is therefore scoped to less RECORDED human work.
- No fourth attempt, ever. No target substitution. No fixture edits after freeze.

## 6. Verdict and adjudication rules

- Per target: `selfdev-run-record` + `selfdev-compare` receipt. Receipt verdicts
  follow the frozen comparison semantics (SELFDEV_HCW_LOWER requires both arms
  VERIFIED, hcw_delta < 0, intervention_delta <= 0).
- Round verdict SUPPORTS the narrow claim only if: all 4 targets reach VERIFIED
  within budget AND all 4 receipts return SELFDEV_HCW_LOWER. Anything else is
  recorded as MIXED or NEGATIVE with the full attempt log. Labels: NEGATIVE iff
  a kill criterion fired or no receipt returns SELFDEV_HCW_LOWER; MIXED
  otherwise.
- Kill criteria (stop the round early, record negative map):
  1. Two targets exhaust their attempt budget without VERIFIED.
  2. Any arm tampers with a frozen fixture, verifier, spec, baseline, or the
     frozen provider-arm argv (the exact command envelope in §3, including
     `--approve`). Deviation from the frozen argv is a run-integrity failure;
     the round is INVALID, not failed.
- Post-hoc winners are forbidden: any target added later is a new prereg.

## 7. Frozen provider-visible statements (verbatim)

- T1: "Make SELFDEV comparison fail closed when baseline and SELFDEV run records
  share any evidence_ref. Acceptance contract: build_self_development_comparison_receipt
  must raise SelfDevelopmentValidationError with code RUN_DENIED and detail
  containing EVIDENCE_REF_OVERLAP whenever baseline_record.evidence_refs and
  selfdev_run_record.evidence_refs share at least one ref; non-overlapping records
  must still produce a valid comparison receipt."
- T2: "In packages/os_core/src/agent_os_core/self_development.py, make SELFDEV
  record builders reject duplicate evidence refs within a single record.
  Acceptance contract: build_self_development_baseline_record and
  build_self_development_run_record must raise SelfDevelopmentValidationError
  with code INVALID_SELFDEV_TARGET and detail containing EVIDENCE_REF_DUPLICATE
  when evidence_refs contains the same ref more than once; distinct refs must
  still build valid records."
- T3: "In apps/cli/__main__.py, make selfdev-run-provider report provider run
  failures structurally. Acceptance contract: when run_task raises
  agent_os_core RunExecutionError, the command must print a JSON object to
  stdout containing mode REAL_PROVIDER_RUN_FAILED and the task payload, and must
  not crash with a traceback; success-path output must remain unchanged."
- T4: "In packages/os_core/src/agent_os_core/recovery.py, make
  build_recovery_snapshot reject event streams whose payloads carry conflicting
  run identifiers. Acceptance contract: when two events carry different non-empty
  run_id values in their payloads, build_recovery_snapshot must raise ValueError
  with message containing 'recovery projection requires one run stream';
  single-run streams must keep projecting unchanged."

## 8. Environment freeze

- Worktree: `autonomous-agent-core/.worktrees/canonical-convergence-20260715`,
  branch `codex/canonical-convergence-20260715`.
- Freeze head: `4c40ff6` (the commit landing this prereg). T2–T4 specs pin
  `repository_head: 4c40ff6` and branch their isolated worktrees from it. T1 is
  the carve-out: its guardrail is already implemented at `ce9cb54` (an ancestor
  of `4c40ff6`), so branching T1 from the freeze head would make its frozen
  fixture green pre-patch; T1 therefore keeps its original spec pinning
  `repository_head: 59112db` (matching its frozen baseline record
  `34614e2d…`) and branches from `59112db`. The freeze commit (§9.3) lands
  after review acceptance and adds only: per-target spec JSONs, fixture patch
  files, pytest.ini files, and the exact-content manifest.
- Provider profile: `openai-compatible`, model `kimi-k2-0711-preview`,
  `model_revision_digest: null` (LIMITATION: the provider revision is not pinned
  by the current profile contract; model-id drift mid-round invalidates the
  round), `AGENT_OS_PROVIDER_TIMEOUT_SECONDS=180`, commitment
  `duration_seconds=3600`.
- LLM sampling parameters are provider defaults and not seedable (LIMITATION:
  recorded, not hidden; attempt-level evidence preserves every envelope).
- Verifier: `python -m pytest` scoped by per-target pytest.ini; allowlisted per
  the SELFDEV-S1 contract.

## 9. Freeze mechanics (required before any result-bearing run)

1. Founder assigns an independent reviewer (`reviewed_by != builder_id`);
   RR-0031 blind anchoring: the reviewer reads the constitution, this prereg and
   the §2 negative map before any run history.
2. Reviewer returns literal acceptance or change requests; builder cannot
   self-approve. Changes after acceptance re-open review.
3. At acceptance, a freeze commit records: this prereg, per-target spec JSONs,
   per-target fixture patch files (materialized verbatim from §10), and an
   exact-content manifest (sha256 of every mechanism file: prereg, specs,
   fixtures, pytest.ini files). Drift against the manifest invalidates run
   integrity (INVALID, not failed).
4. Only then: baseline arms (T2–T4; T1 frozen) → provider arms → receipts →
   adjudication → negative map + paradigm learning update.

## 10. Frozen fixtures (verbatim; materialized into each target workspace at setup)

F1 (T1): already frozen in the T1 workspace
(`+44 lines tests/product/test_agent_os_self_development.py`,
`test_selfdev_comparison_receipt_refuses_shared_evidence_refs`, plus pytest.ini);
bound by baseline record `34614e2d…` and the fair-run summary.

F2 (T2) — appended to `tests/product/test_agent_os_self_development.py`:

```python
def test_selfdev_records_reject_duplicate_evidence_refs() -> None:
    spec = SelfDevelopmentTaskSpec(
        mandate_id="META-SHADOW-MANDATE-0",
        repository_id="autonomous-agent-core",
        repository_head="0123456789abcdef",
        isolated_workspace="/tmp/agent-os-selfdev",
        isolated_branch="codex/selfdev-dup-evidence",
        target_path=AGENT_OS_TARGET,
        verifier_commands=("python -m pytest",),
        expected_outcome_id="expected:selfdev-dup-evidence",
        rollback_strategy="compensate_task",
        operator_intervention_count=1,
        hcw_minutes=2.0,
        baseline_assignment_id="baseline:selfdev-dup-evidence",
    )
    with pytest.raises(SelfDevelopmentValidationError) as run_exc:
        build_self_development_run_record(
            spec,
            operator_intervention_count=1,
            hcw_minutes=1.0,
            outcome_status="VERIFIED",
            evidence_refs=("dup:ref", "distinct:ref", "dup:ref"),
        )
    assert run_exc.value.code == INVALID_SELFDEV_TARGET
    assert "EVIDENCE_REF_DUPLICATE" in run_exc.value.detail

    with pytest.raises(SelfDevelopmentValidationError) as base_exc:
        build_self_development_baseline_record(
            baseline_assignment_id="baseline:selfdev-dup-evidence",
            repository_id="autonomous-agent-core",
            target_path=AGENT_OS_TARGET,
            operator_intervention_count=1,
            hcw_minutes=1.0,
            outcome_status="VERIFIED",
            evidence_refs=("dup:ref", "dup:ref"),
        )
    assert base_exc.value.code == INVALID_SELFDEV_TARGET
    assert "EVIDENCE_REF_DUPLICATE" in base_exc.value.detail
```

F3 (T3) — appended to `tests/product/test_cli_surface.py`; the fixture also
extends that file's `FakeApplication` with run-error injection:

```python
# FakeApplication.__init__ gains: self.run_error: Exception | None = None
# FakeApplication.run_task gains at top:
#     if self.run_error is not None:
#         raise self.run_error

def test_cli_selfdev_run_provider_reports_structured_failure_without_traceback(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("AGENT_OS_PROVIDER_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("AGENT_OS_PROVIDER_MODEL", "frontier-model")
    monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY_ENV", "AGENT_OS_TEST_PROVIDER_KEY")
    monkeypatch.setenv("AGENT_OS_TEST_PROVIDER_KEY", "redacted-test-key")
    fake = FakeApplication()
    fake.run_error = RunExecutionError(
        "provider patch arguments must contain only path and content"
    )
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: fake)
    spec_path = _write_selfdev_spec(tmp_path, branch="codex/selfdev-cli-failure")
    baseline_path = _write_selfdev_baseline_record(
        tmp_path,
        branch="codex/selfdev-cli-failure",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "selfdev-run-provider",
            str(spec_path),
            "--baseline-record",
            str(baseline_path),
        ],
    )

    cli.main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["mode"] == "REAL_PROVIDER_RUN_FAILED"
    assert output["task"]["task_id"] == "task:selfdev-created"
    assert captured.err == ""
```

(`RunExecutionError` added to the file's `agent_os_core` import list.)

F4 (T4) — appended to `tests/product/test_recovery_projection.py`:

```python
def test_recovery_snapshot_rejects_conflicting_run_ids() -> None:
    events = _events(
        (TaskEventType.RUN_STARTED, {"run": {"run_id": "run:one"}}),
        (TaskEventType.RUN_RESUMED, {"run": {"run_id": "run:two"}}),
    )

    with pytest.raises(ValueError) as exc_info:
        build_recovery_snapshot(events)

    assert "recovery projection requires one run stream" in str(exc_info.value)
```

## 11. C6/C7/SD4 and product/process boundary

- Write channel: provider output reaches the repository only through the frozen
  workflow (read → provider → approval → apply → tests → evaluate), exact-digest
  human approval (`--approve`), allowlisted verifier, and compensate_task
  rollback. No untyped model output becomes a consequential command.
- C7, permission ceilings, gates, evaluators and this prereg's acceptance
  criteria are not modifiable by the provider arm; SD4 remains forbidden.
- Baseline and provider evidence stay in separate ledgers; receipts bind
  content digests, and shared evidence refs are fail-closed (S13).

## 12. Round artifacts

Run dir: `.agent_runs/selfdev-mt-20260723/` (per-target subdirs). Each target
archives: spec, baseline record/capture, per-attempt sqlite + redacted provider
output, run summary, run-record, comparison receipt, and a round-level
adjudication note including the negative map.
