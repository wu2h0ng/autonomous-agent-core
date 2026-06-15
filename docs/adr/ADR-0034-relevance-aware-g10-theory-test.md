# ADR-0034: Relevance-Aware G10 Theory Test

- Status: Accepted (pre-registration; implementation pending)
- Date: 2026-06-15
- Deciders: founder approval, Codex CTO execution under ADR-0003 discipline

## Context

G10 established the first decisive positive result in this prototype line:

```text
P0 = confidence-gated policy + no organ
A1 = baseline policy + O1 cheap reset
P0 beats A1 by 40.1% on fresh seeds 800..829
```

ADR-0030 then passed multiple trap checks, including B-temp, a fixed-low-temperature
baseline. However, RR-0019 section 12 found a deeper problem in the theoretical
explanation: the two-channel model `B/K` omitted `RelevanceField.explore_drive`, even
though the real G9/G10 harness drives the full `Agent`, where `explore_drive` is adaptive.

RR-0019 section 13 therefore amended the theory to:

```text
B = (mu, u)                         belief channel
R = rho = RelevanceField.explore_drive
K = k(conf(B))                      confidence commitment channel

P0 effect = K x R, not K alone
```

This ADR freezes the faithful core-harness test of that amended theory. It does not
change C6/C7, does not import LLMs, does not revive G11/C1, and does not change the G10
result. Its purpose is narrower: determine how much of the G10 win remains after the
best relevance-aware non-gated exploration control is allowed to compete.

## Options Considered

### Option A: Do nothing; keep P6 synthesis as final

Pros:

- Avoids spending core effort after P6 consolidation.
- Avoids the temptation to explain every positive result post hoc.

Cons:

- Leaves RR-0019 section 13 untested.
- Leaves ADR-0030's "not merely lower exploration" interpretation under-specified,
  because B-temp did not test a relevance-aware exploration control.

### Option B: Run another offline reconstruction

Pros:

- Cheap and isolated.

Cons:

- Already failed as an apparatus in RR-0019 section 12 because fixing `explore_drive`
  does not match the real `Agent`.
- Would risk a second unfaithful falsification.

### Option C: Pre-register a full-Agent relevance-aware core harness

Pros:

- Tests the real mechanism path: `Agent -> RelevanceField -> PolicySelector`.
- Directly answers the remaining theory question: after `R` is treated fairly, how much
  independent margin remains for `K`?
- Keeps the result interpretable even if it weakens the current story.

Cons:

- Requires code changes in `StructuredRegimeEnv` or a faithful sibling environment.
- Requires an additional strong control arm and more bookkeeping.
- May downgrade part of ADR-0030's interpretation.

## Decision

Choose **Option C**.

Implement a docs-first, then code, full-Agent experiment with no mechanism tuning on
r-final seeds. The experiment is explanatory, not a new route to G11/C1.

### D1. Environment knobs

Add a faithful severity/noise environment path while keeping current `StructuredRegimeEnv`
default behavior bit-identical.

Implementation may either:

- extend `StructuredRegimeEnv` with optional severity-controlled library generation, or
- add a sibling environment if that is cleaner.

The accepted semantics are:

```text
severity in [0, 1]
reward_high = 4.0
reward_low = -1.0
best action reward = reward_high
non-best action reward = reward_high - severity * (reward_high - reward_low)
```

So stale commitment cost is controlled:

```text
severity = 0.10  -> mild stale-action regret ~= 0.5
severity = 0.50  -> medium stale-action regret ~= 2.5
severity = 1.00  -> severe stale-action regret ~= 5.0
```

Required guard:

- Existing `StructuredRegimeEnv()` defaults and all existing G6-G10 tests must remain
  behavior-compatible.

### D2. Arms

All arms must drive the real `Agent.step(env)` path. No fixed-`rho` reconstruction is
allowed.

Required arms:

| Arm | Gate | Organ | RelevanceField | Purpose |
|---|---|---|---|---|
| `A0` | off | none | default | historical no-organ baseline |
| `A1` | off | O1 reset | default | cheap baseline guard |
| `BT` | off, `base_temperature=0.03` | none | default | ADR-0030 fixed-low-temp guard |
| `P0` | frozen G10 gate `{gate_kappa=0.5, gate_temp_floor=0.1}` | none | default | confirmed candidate |
| `RSTAR` | off | none | tuned relevance-aware control | strong non-gated exploration control |

`RSTAR` is selected on calibration seeds only from this pre-specified grid:

```text
base_temperature: [0.03, 0.10, 0.30]
RelevanceField.inertia: [0.25, 0.50, 0.75]
RelevanceField.surprise_gain: [1.0, 2.0, 4.0]
```

Selection rule:

```text
Choose the single RSTAR parameter triple with lowest mean post-shift regret area
aggregated across all calibration conditions in D3.
Freeze it before r-final.
```

No per-condition RSTAR selection is allowed on r-final seeds.

### D3. Seeds and condition grid

Calibration seeds:

```text
1400..1419
```

R-final seeds:

```text
1500..1529
```

PRED-A' grid:

```text
severity = [0.10, 1.00]
noise = 0.30
period = 40
n_actions = 8
n_regimes = 5
steps = 2000
window = 15
```

PRED-B' grid:

```text
severity = 1.00
noise = [0.10, 0.30, 0.50, 1.00]
period = 40
n_actions = 8
n_regimes = 5
steps = 2000
window = 15
```

PRED-C' uses the severe/default condition:

```text
severity = 1.00
noise = 0.30
```

### D4. Metrics

Primary metric:

```text
post_shift_regret_area = sum(env.last_regret for WINDOW steps after each shift)
```

Lower is better.

For each condition and arm, report:

```text
mean area
paired per-seed differences vs P0
Wilcoxon one-sided p where applicable
bootstrap 95% CI for paired mean reduction
```

Theory diagnostics must also report per-window traces or aggregates for:

```text
rho = RelevanceField.explore_drive
conf = PolicySelector confidence
tau = effective policy temperature
w_e = effective epistemic weight
```

If current `PolicySelector` does not expose these, add instrumentation without changing
selection behavior.

### D5. Pre-registered predictions

Let:

```text
adv(P0, X) = 1 - mean_area(P0) / mean_area(X)
```

Positive advantage means P0 is better.

#### PRED-A' severity threshold

Compare P0 to `RSTAR`.

Expected pattern:

```text
mild severity:   adv(P0, RSTAR) <= 0.05
severe severity: adv(P0, RSTAR) >= 0.15
severe - mild paired advantage gap bootstrap CI lower > 0
```

Interpretation:

- PASS supports the amended trajectory account: KxR matters when stale commitment is
  costly.
- FAIL means the severity-threshold theory is not supported in the real harness.

#### PRED-B' difficulty band

At `severity=1.00`, compare P0 to `RSTAR` across the noise grid.

Expected pattern:

```text
best interior advantage at noise in {0.30, 0.50}
best interior advantage >= low-noise advantage + 0.05
best interior advantage >= high-noise advantage + 0.05
bootstrap CI lower > 0 for both interior-edge gaps
```

Interpretation:

- PASS supports the "windowed convergence" account.
- FAIL means the inverted-U account is not supported in the real harness.

#### PRED-C' relevance-aware control share

At `severity=1.00, noise=0.30`, compute:

```text
margin_total = mean_area(A1) - mean_area(P0)
margin_R = mean_area(A1) - mean_area(RSTAR)
share_R = margin_R / margin_total
```

Expected pattern:

```text
0.25 <= share_R <= 0.75
P0 still beats RSTAR by adv(P0, RSTAR) >= 0.15
```

Interpretation:

- PASS means relevance-aware exploration explains a substantial part of the old G10
  margin, but confidence-gated commitment still has a decisive residue.
- If `share_R > 0.75` or `adv(P0, RSTAR) < 0.15`, downgrade ADR-0030's broad reading to:
  "relevance-aware exploration explains most of the old P0-vs-A1 margin."
- If `share_R < 0.25`, the original G10 result remains mostly a K-channel result, but the
  amended B/R/K model still remains the faithful description.

### D6. Validity and safety guards

Required implementation tests:

- Default `StructuredRegimeEnv()` behavior remains compatible with existing tests.
- Severity-controlled env has deterministic reward gaps and deterministic replay.
- `RSTAR` calibration uses only seeds 1400..1419 and freezes one global parameter triple.
- R-final refuses to run if calibration has not produced a frozen `RSTAR`.
- Every arm uses `Agent.step`, not a hand-rolled policy loop.
- C6: no organ/action/policy/shell write is introduced.
- C7: pause/forbidden dominance remains unchanged.

### D7. Result disposition

This experiment can only update the theory and interpretation ledger.

It must not:

- reopen G11/C1,
- retune P0,
- retune O1/O4/O5/O2,
- introduce LLM or self-recursive runtime machinery,
- claim a new autonomy axis.

Possible outcomes:

| Outcome | Disposition |
|---|---|
| PRED-A'/B'/C' all pass | RR-0019 B/R/K trajectory account gains real-harness support |
| A'/B' fail but C' shows P0 residue | G10 remains empirically true; trajectory explanation weakens |
| C' shows RSTAR captures most margin | Downgrade ADR-0030 interpretation; P0 win may be mostly relevance-aware exploration plus minor K |
| P0 fails broadly under the new env | G10 remains true only for its original env; do not generalize |

## Consequences

- This ADR creates a new task family: T-P6.5 relevance-aware G10 theory test.
- Implementation must be serial and docs-first:
  1. Environment severity/noise path + tests.
  2. Policy diagnostic instrumentation + tests.
  3. RSTAR calibration harness + freeze artifact.
  4. R-final experiment + ADR result update.
- The current P6 synthesis remains valid, but its publication wording should treat the
  G10 mechanism as `K x R` until ADR-0034 resolves the split.
- No core mechanism code should be changed before these gates are implemented in tests.
