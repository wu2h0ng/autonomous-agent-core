# AGENT-OS-SELFDEV-7 — Adequacy-Floored Prompt-Alignment Round Prereg (DRAFT)

> Status: `DRAFT` — no result-bearing run until independent review accepts and
> the freeze commit records the exact-content manifest.
> Date: 2026-08-08. Builder: kimi-cli session.
> Governing documents: ADR-0056/0058/0059, SELFDEV-2/3/4/5/6 prergs and
> adjudications. Harness under test: unchanged from E6 (aligned governed
> diff prompt, a496442). This round exists because E6's window was
> inadequate — declared upfront per the adjudicator's five declarations.

## 0. The five declarations (adjudicator-required, ex-ante)

1. **Honest motivation**: E6's measurement was destroyed by a provider
   account-quota event (83% of attempts consumed by 403s; weather-free
   sample 8 attempts on 2 tasks; the prompt-alignment question went
   unanswered). E7 is a re-run of the SAME envelope because E6's window was
   inadequate. This declaration postdates E6's result; the mitigations are
   this ex-ante freeze and independent review. E6's NEGATIVE stands as its
   own record and is not replaced or "corrected" by anything in E7.
2. **Subset reuse**: the SELFDEV-4 frozen subset is reused VERBATIM for the
   fourth round (byte-identity proven in this round's manifest). Provider
   arms carry no cross-run memory; fresh 2-attempt budgets per task (series
   norm). Reserve tasks are not consumed.
3. **Pause-on-403 accounting change (frozen explicitly)**: ONLY
   account-quota signatures (HTTP 403 / AUTHENTICATION_FAILED) trigger a
   driver PAUSE with probe-gated resume (health probe every 5 minutes;
   resume after 2 consecutive healthy probes; max cumulative pause 6 hours,
   after which remaining attempts are consumed INVALID_PROVIDER). Timeouts,
   UNAVAILABLE, RemoteDisconnected, malformed responses and every other
   provider failure remain consumed attempts exactly as before. All pause/
   resume events are logged with timestamps; invoked markers and partial
   records are preserved, never deleted (retention rule binding).
4. **Ex-ante adequacy floor**: after the round completes, count each arm's
   weather-free attempts (terminal classes other than INVALID_PROVIDER /
   INVALID_INFRA / pause-related). If EITHER arm has fewer than 12
   weather-free attempts (half the 24-attempt budget), the round verdict is
   INSUFFICIENT_DATA — not SUPPORTS, not NEGATIVE. This is frozen before
   any attempt and binds the adjudicator.
5. **Driver + gate binding**: driver7.py (whitelist abort + pause-on-403 +
   probe-gated resume) and the health gate (3 small probes + 1 medium
   extractable-diff probe + 1 explicit 403-discriminating quota probe) are
   bound in the freeze manifest.

## 1. Purpose and claim boundary

Question (carried, unanswered by E6): on the frozen 12-task subset, with the
aligned governed diff prompt (a496442), at pass@2 with ABAB and the health
gate, does the chain's weather-free solve rate match the baseline's — is
the E5 residual (~6.5× gap localized to the governed prompt/response
contract) closed by prompt alignment?

NON-CLAIMS (carried verbatim): no comparability to published agentic
scaffolds; no leaderboard claim; no HCW-reduction claim; contamination
upper bound; not release; not `Autonomy(S,E,O,V,T)` evidence.

Secondary declared analysis (descriptive only, NO gate): E5/E6/E7 per-arm
comparison; the django-10880 context-mismatch follow-up (diff the rejected
patch's context lines against base bytes for version drift).

## 2. Prior negative/result map

- E6 (NEGATIVE with unanswered-question caveat): chain 1/12 vs baseline
  2/12, 83% quota-destroyed; clean data points: chain django-11066 2/2
  solved (aligned prompt works end-to-end); django-10880 chain ×2
  APPLY_FAILED with logged "unified diff context mismatch"
  (generation-side, hypothesis-tagged).
- E5 (NEGATIVE): residual localized to the governed prompt/response
  contract (~6.5× weather-free gap) plus the apply-gate class.
- Carried fixes live in the harness: denial-reason logging, whitelist
  abort, denial observability (all in a496442).

## 3. Arms, inputs, budgets (carried; only the pause rule is new)

- Inputs: identical both arms (issue + base-commit bytes + F2P + P2P ids;
  neither sees test_patch or gold patch).
- Chain arm: frozen argv `agent-os benchmark-run-provider
  .agent_runs/selfdev-4/selection.json <instance_id> --approve
  --duration-seconds 3600` (aligned prompt, a496442). 2 attempts per task.
- Cheap baseline: frozen argv `agent-os benchmark-run-baseline
  .agent_runs/selfdev-4/selection.json <instance_id>`. 2 calls per task.
- Attempt accounting: carried verbatim (watchdogs 1800/2400, invoked
  markers, terminal classes, preview=consumed, frozen argv = run integrity,
  retention binding) PLUS the §0.3 pause-on-403 change (frozen there).
- Solve determination: ONLY the independent round-level verifier (§6).
- Execution: strictly sequential; ABAB per-attempt; workspace restored
  before EVERY attempt; no early stopping (whitelist abort = kill-4 event).
- Health gate (strengthened): 3 small probes + 1 medium extractable-diff
  probe + 1 explicit quota probe (a 403 response fails the gate), within 30
  minutes before the first attempt; failure ⇒ no start.

## 4. Frozen subset (REUSED, hash-pinned)

`.agent_runs/selfdev-4/selection.json` at 5fa6f69 (sha256 in the SELFDEV-4
manifest; byte-identity proven in this round's manifest). 12 MAIN tasks
only. astropy-14182 enters with a fresh 2-attempt budget (new round;
declared, carried).

## 5. Environment freeze (carried)

Provider `openai-compatible` / `kimi-k2-0711-preview`, revision unpinned
(LIMITATION), timeout 600s, commitment 3600s, provider-default sampling
(LIMITATION). Containers per ADR-0056 D5. Pre-round re-verification:
docker up, 12 workspaces clean at pinned heads, images present, solver
sanity, workspace object self-containment intact. Repo head: this prereg's
freeze commit.

## 6. Verifier flow (carried)

checkout base → apply candidate → apply hidden test patch → F2P → curated
P2P → solve iff both green → restore (always). Solve ONLY via the
independent round-level verifier re-run.

## 7. Verdict and kill criteria

- SUPPORTS the narrow claim iff chain pass@2 solve count > baseline pass@2
  solve count on the frozen subset, no task-level integrity failure, AND
  the §0.4 adequacy floor is met (both arms ≥12 weather-free attempts).
  Strict inequality; ties do not support. SUPPORTS reads exactly as:
  "observed difference on this frozen 12-task subset under the
  aligned-prompt envelope with an adequate window" — nothing more.
- **INSUFFICIENT_DATA iff either arm falls below the §0.4 floor** (and no
  kill criterion fired). NEGATIVE iff a kill criterion fired or (floor met
  and) chain < baseline. MIXED otherwise.
- Kill criteria (carried verbatim): 1. env/infra failure on >25% of frozen
  tasks (task-environment, NOT provider-infra attempt classes — the E6
  ruling stands: 403 quota events are provider-infra attempts, now with the
  §0.3 pause semantics) ⇒ INVALID; 2. manifest/fixture/argv drift ⇒
  INVALID; 3. cheap-baseline data loss ⇒ INVALID; 4. parallel provider
  calls or early stop ⇒ INVALID (whitelist abort or a pause-protocol
  violation = kill-4 event); 5. two or more tasks with restore/compensation
  failure ⇒ INVALID; 6. pre-round re-verification or health gate fails and
  is waived ⇒ INVALID (no waiver path).

## 8. Freeze mechanics

1. Independent reviewer (reviewed_by != builder_id, RR-0031 blind
   anchoring); literal verdict; changes re-open review.
2. Freeze commit: this prereg, driver7.py, solve7.py, exact-content
   manifest binding those plus the reused selection cross-pin.
3. Round order: health gate → ABAB with §0.3 pause semantics; run to
   completion.
4. Adjudication: receipts, verdict per §7 (incl. adequacy floor), E5/E6/E7
   descriptive (no gate), negative map, paradigm learning, state sync,
   independent adjudication.

## 9. Boundaries (carried)

C7/approval/verifier semantics unchanged; untrusted code stays containerized
with no network/credentials; no untyped model output becomes a consequential
command; no mid-round envelope changes; any further change is a NEW prereg.
