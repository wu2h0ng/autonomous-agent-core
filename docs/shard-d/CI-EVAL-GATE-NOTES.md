# Shard D — CI eval-gate findings & proposed CI changes (integration applies)

Owner: `.github/workflows/ci.yml` is the integration single-owner. Nothing in it is
edited here; this file is the change request for the integration phase.

## 1. Container images (`container:` / `image:` / `services:`)

**Finding: there are NO container images in this workflow.** Grep confirms:

```
$ grep -nE "runs-on|container:|image:|services:" .github/workflows/ci.yml
19:    runs-on: ubuntu-latest
316:   runs-on: ubuntu-latest
```

Both jobs run on the GitHub-hosted `ubuntu-latest` VM, not a container. There is no
`container:` job directive, no `image:`, and no `services:` block, so there is nothing to
pin to `@sha256:...`. **No action required for image digest pinning.** (If a future job
adds a service container or `container:` directive, it must be pinned to a digest, not a
tag.)

## 2. Action references (supply-chain pin)

The six `uses:` references are pinned to **major-version tags**, not commit SHAs:

| line | ref | note |
|---|---|---|
| 30 | `actions/checkout@v4` | floating major tag |
| 31 | `actions/setup-python@v5` | floating major tag |
| 331 | `actions/checkout@v4` | floating major tag |
| 337 | `actions/setup-node@v4` | floating major tag (node-version: "22") |
| 345 | `oven-sh/setup-bun@v2` | floating major tag (bun-version: "1.4.2") |
| 412 | `actions/setup-python@v5` | floating major tag |

**Proposed change for integration (NOT applied here):** replace each `@vN` with the
immutable `<full-length-sha>#readme` form once resolved. Resolving the SHA requires
network (`gh api repos/<org>/<action>/git/ref/tags/v4`), which is outside this shard's
offline scope and would be invented if guessed. Recommend integration resolve and apply:

```
actions/checkout@<sha-of-v4>          # replace both line 30 and 331
actions/setup-python@<sha-of-v5>      # replace both line 31 and 412
actions/setup-node@<sha-of-v4>
oven-sh/setup-bun@<sha-of-v2>
```

This is hardening, not a correctness fix: the gates still pass on the major tags.

## 3. Cross-repo runner-contract

The cross-repo dependency is **not** a reusable workflow in `ci.yml` (grep for
`uses: <org>/<repo>/.github/workflows/...@ref`, `workflow_call`, `uses: ./` returns
nothing). It lives in the test suite:

- `tests/product_eval/test_runner_contract_qualification.py` pins the sibling repo
  `ai-agent-engineering-workflow` at **commit SHA `50eb4d27b17688f0943f80207dddb702983afd51`**
  (constant `RUNNER_HEAD`), on branch `codex/team-event-contract-v1-20260713`. It is
  **already SHA-pinned, not tag/branch** — the re-pin requirement is satisfied.
- The sibling worktree is not materialized in this repo's CI or a fresh clone, so every
  dependent test is **quarantined with a reason** (see
  `tests/product_eval/_quarantine.py`, bucket `cross_repo`). No CI change is needed;
  un-quarantine when the sibling worktree is checked out at that exact SHA.

## 4. The terminal-coding eval step itself

The step at `.github/workflows/ci.yml:304-307` already runs the correct three offline
arms:

```
pytest tests/product_eval/test_terminal_coding_eval.py
       tests/product_eval/test_terminal_coding_eval_live.py
       tests/product_eval/test_terminal_coding_horizon.py -q
```

The drift was on the **guard test** side
(`tests/product/test_ci_gate_wiring.py` glob `test_terminal_coding_eval*` omitted the
third `horizon` arm). That guard is fixed in this shard (tests/product), not in ci.yml.
**No ci.yml change required for the eval step.**
