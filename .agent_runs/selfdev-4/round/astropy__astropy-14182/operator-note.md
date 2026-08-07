# Operator error disclosure (2026-07-28)

The operator (kimi-cli) ran the frozen chain argv three times on this task as a
"smoke test" in flaky provider weather (HTTP 504, HTTP 504, MALFORMED). Per the
prereg's attempt accounting, every provider-node invocation consumes an
attempt — so 3 attempts were consumed against the task's pass@2 budget of 2.
No "free smoke" exists for a frozen argv. The task's budget is exhausted;
its outcome records INVALID (final attempt class: INVALID_PROVIDER), and no
further attempts will be run on it. The remaining 11 main tasks are untouched
by any provider call. Founder ruled 2026-07-28: continue the round for the
remaining 11 with this violation disclosed in adjudication.
