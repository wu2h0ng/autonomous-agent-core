# ADR-0056: SELFDEV external benchmark task admission and containerized execution boundary

- Status: Accepted
- Date: 2026-07-23
- Deciders: founder (CTO gate 2026-07-23: design packet D1–D5 all approved, D5 = containerized runner; ADR-0003 founder-reserved tier — external execution/side effects) / agent drafts per founder direction
- Review: independent reviewer (kimi subagent, blind-anchored, no builder run history) — TECHNICAL_APPROVE 2026-07-23

## Context

Round SELFDEV-MT-20260723 (self-made targets, founder HCW baselines) was
adjudicated NEGATIVE (kill criterion 1; negative map: provider full-file
replacement syntax failures on large files 2/2, neighbor breakage 2/2,
parallel-load timeouts 2/7). On 2026-07-23 the founder rejected the
evaluation method and directed public-benchmark baselines. The
review-hardened design packet
`docs/product/AGENT-OS-SELFDEV-2-benchmark-baseline-design-2026-07-23.md`
(independent review: TECHNICAL_APPROVE after 3 rounds) requires five product
changes that touch admission contracts and the execution boundary:

1. SELFDEV admission today accepts only the Agent OS repository
   (`_AGENT_OS_REPOSITORIES`, allowlisted path prefixes, pytest allowlist).
   SWE-bench tasks are third-party repos at historic base commits.
2. Executing third-party historic code is arbitrary code execution on the
   founder's host. The current sandbox is cwd-confined only: pytest-allowlist
   subprocess with the FULL host environment (provider credentials included),
   no network isolation, 120s hard cap (`capability.py` `_run_tests`).
3. The round needs a SWE-bench-style verifier (FAIL_TO_PASS + curated
   PASS_TO_PASS node ids) instead of whole-file scoped pytest.
4. The round needs a bare one-shot cheap baseline (pass@2, unified diff,
   `git apply` fail-closed) as the strong cheap comparator.
5. Frozen subsets require pre-freeze gold environment validation: base+test-patch
   must FAIL F2P; base+gold+test-patch must PASS both sets.

## Options Considered

- **Option A (chosen): new external benchmark admission path + containerized
  per-task runner.** Costs: docker daemon dependency (colima on the run host),
  image build time at freeze, new contract + runner + verifier code with
  tests. Benefits: untrusted code runs without host credentials, network, or
  host filesystem access; the Agent OS self-development admission boundary
  stays clean (constitution §2 identity). C6/C7: untouched — admission adds a
  task source; approval authority, evaluation gates, correction/promotion and
  C7 roots are not modified; untrusted code never holds execution authority
  beyond producing bytes that the same typed verifier evaluates.
- **Option B: host execution with env scrubbing + founder risk acceptance.**
  Cheaper to build, but arbitrary historic `setup.py`/test code runs with
  network on the founder's host; scrubbing is best-effort against a motivated
  or compromised fixture. Rejected at the CTO gate (D5) as below the §8 bar.
- **Option C: widen `_AGENT_OS_REPOSITORIES` / prefixes to admit external
  repos.** Smallest diff, but blurs the "Agent OS develops Agent OS" identity
  and weakens target validators that protect the product repository.
  Rejected: identity and validator strength are load-bearing.

Strongest counterargument to A: containerization adds operational fragility
(daemon availability, image builds for historic deps on arm64) that can
invalidate a round for infrastructure reasons. Accepted and priced: kill
criterion 1 in the design treats >25% env failure as round INVALID
(infrastructure, not capability), and gold env validation runs pre-freeze so
bad tasks never enter the subset.

## Decision

1. **Benchmark admission contract.** New `SelfDevelopmentBenchmarkTask`
   contract (packages/contracts): task_id, repo_url, base_commit,
   issue_text_hash, gold_file_path, gold_file_bytes (must be ≤ 19,000),
   f2p_node_ids, p2p_node_ids (curated per-instance lists), env_manifest
   (interpreter, pinned deps with hashes, per-task verifier timeout seconds,
   min provider output-token budget), plus a content digest. Separate
   validator/builder from Agent OS selfdev admission; existing Agent OS
   admission is not modified.
2. **Containerized per-task runner.** Docker image per repo built at freeze
   time with deps pre-fetched and hash-locked. Run properties: no network,
   no host environment (credentials never enter the container), resource
   limits (cpu/memory/pids), read-only root fs except a per-task workspace
   mount, per-task configurable timeout (fail-closed default). The sandbox
   gains a container-backed execution mode used ONLY for benchmark tasks;
   Agent OS targets keep today's semantics unchanged.
3. **Verifier flow (identical for both arms).** checkout base → apply
   candidate → apply hidden test patch → run F2P node ids → run curated P2P
   node ids → solve iff both sets green → restore base bytes. A task solves
   ONLY via an independent round-level re-run of this flow on the final
   workspace state; the chain's internal VERIFIED is telemetry, not evidence.
4. **Cheap-baseline runner.** Same provider profile/timeout/sampling and the
   same inputs as the chain arm; one-shot unified-diff output; `git apply`
   fail-closed (malformed diff = attempt failure, no human repair); pass@2
   per task; same verifier flow.
5. **Gold env validation harness.** Pre-freeze, per candidate task:
   base+test-patch FAILS the F2P set AND base+gold+test-patch PASSES both
   sets; evidence recorded in the env manifest. Only validation-passing tasks
   enter the selection pool.
6. **Verifier argv discipline.** Enumerated node-id pytest argv patterns with
   node-id argument validation; no general shell is opened.
7. **Env scrubbing.** Verifier subprocesses (in-container and host-side
   tooling) never receive host credentials.

## Consequences

- Build scope: benchmark task contract + validator, container runner,
  node-id verifier, cheap-baseline runner, gold-validation harness, CLI
  surfaces for each, and product tests (tests first, targeted
  pytest/ruff/pyright, no CI bypass).
- Operational: docker daemon required on the run host at freeze and round
  time (colima); absence = infra INVALID, not capability.
- Deferred (not in this ADR): multi-file/exploration harness, SWE-rebench
  collection pipeline, any HCW-reduction claim work.
- Review requirement: this ADR requires independent review before moving to
  Accepted; implementation follows acceptance.
- On acceptance: PROJECT_PLAN / CURRENT_STATE task cards updated; the
  SELFDEV-2 prereg (subset, statements, budgets, verdict, manifest) is
  drafted against this ADR and gets its own independent review before any
  result-bearing run.
