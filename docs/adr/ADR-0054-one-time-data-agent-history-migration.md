# ADR-0054: One-Time Data Agent History Migration into Agent OS

- Status: Accepted for design and migration planning; execution remains gated
- Date: 2026-07-10
- Deciders: founder (explicit Option B and review-remediation approval), delegated CTO
- Claim class: `product-architecture` / `repository-migration`
- Target track: Product Track
- Product authority: `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md`
- Spine authority: `docs/architecture/T-P-OS-SPINE-0-ARCHITECTURE-PACKET.md`
- Migration authority: `docs/architecture/T-P-OS-SPINE-1-DATA-AGENT-MIGRATION-MAP.yaml`
- Satisfies: parent Hard Boundary #19 requirement for a founder/CTO-approved cross-repository ADR

## Context

The founder decided that the historical `autonomous-agent-core` repository evolves into
the complete Agent OS monorepo. The existing `ai-native-business-data-agent-os` repository
contains product/runtime implementation and history that should become the first
enterprise domain pack rather than remain a permanent second product runtime.

Parent Hard Boundary #19 forbids importing or copying code between the independent
repositories without a new founder/CTO-approved ADR. It also forbids runtime coupling by
default. This ADR records the narrow exception needed for Option B while preserving the
reason for that boundary: one authority spine, auditable provenance and no hidden
cross-repository dependency.

Claude's independent review of `ca4610b..e78b72a` identified two blocking omissions in the
first design:

1. the migration map did not contain an explicit Hard Boundary #19 authorization gate;
2. direct no-squash import could pull historical secret blobs into the target before a
   full-history safety scan.

The review also found that tying the complete Data Agent migration to SPINE-0 made the
first executable vertical too broad. This ADR therefore authorizes migration only as the
successor `T-P-OS-SPINE-1`, after the developer spine is accepted.

## Decision

### 1. Narrow cross-repository exception

One history-preserving migration from the pinned Data Agent donor into the Agent OS
monorepo is authorized for planning and later execution under the migration map.

This exception permits only:

- read-only inspection and characterization of the donor repository;
- creation of a reviewed migration mirror when history filtering is required;
- one subtree/history import into `_migration/data-agent-os` on an isolated feature branch;
- extraction of generic product code into Product Track packages;
- extraction of data-specific behavior into `domain_packs/data_agent`;
- removal of the staging tree after accepted extraction while retaining approved history.

It does not permit:

- runtime imports from the donor repository or `_migration` staging;
- bidirectional synchronization, dual writes or a permanent repository federation;
- copying Research Track code into Product Track without a `ResearchCandidateManifest`;
- importing `ai-agent-engineering-workflow` into product runtime;
- executing migration before every gate below is accepted;
- pushing or merging the migration branch without explicit founder authorization.

Any broader cross-repository integration requires a new ADR.

### 2. Product sequence split

```text
T-P-OS-SPINE-0
  = generic durable developer golden path
  = no donor import and no Data Agent seam completion requirement

T-P-OS-SPINE-1
  = history-safe Data Agent migration
  = generic extraction + domain_packs/data_agent
  = shared-spine Data Agent seam acceptance
```

SPINE-1 may use contracts delivered by SPINE-0 but may not retroactively redefine
SPINE-0 acceptance.

### 3. History safety before import

The pinned donor's complete reachable history must be scanned before any donor commit or
blob becomes reachable from the target repository.

The pre-import report must bind:

- full donor commit SHA and all scanned refs;
- scanner name/version/configuration and invocation;
- secret/high-entropy credential findings;
- customer data, PII and sensitive raw-data findings;
- oversized/binary/LFS object inventory;
- licensing/provenance exceptions relevant to redistribution;
- false-positive adjudications with reviewer identity;
- report digest and final verdict: `PASS`, `REMEDIATE`, or `ABORT`.

Disposition:

- `PASS`: direct no-squash subtree import from the reviewed donor ref is allowed.
- `REMEDIATE`: construct a filtered migration mirror, rotate/revoke any exposed credential,
  record old-to-new commit mapping and rerun the same scan. Only the filtered mirror may be
  imported.
- `ABORT`: no donor history import; return to founder/CTO for a new migration decision.

No-squash means history-preserving only after the safety gate passes. It never means that
known secret or customer-data blobs must be preserved.

### 4. Execution gates

Execution of SPINE-1 is blocked until all of the following hold:

1. parent/root Agent OS identity and Hard Boundary #19 text are reconciled with this ADR;
2. SPINE-0 is accepted through its real developer golden path;
3. the migration implementation plan and provenance manifest are reviewed;
4. donor full SHA is pinned and donor worktree status is recorded;
5. the full-history safety report returns `PASS`;
6. donor characterization tests cover generic runtime and Data Agent safety behavior;
7. the isolated migration branch has no unrelated changes;
8. no push/merge authorization is inferred from this ADR.

### 5. Security incident rule

If a secret or sensitive historical blob is discovered after local import:

1. stop migration and prohibit all pushes;
2. revoke/rotate the exposed credential where applicable;
3. remove imported refs and create a filtered migration mirror;
4. rewrite the unpublished migration branch from the clean mirror;
5. rerun history scan and provenance verification;
6. record the incident and reviewer decision.

`git revert` is not a secret-removal mechanism because imported objects remain in history.
If the contaminated history has already been pushed, founder/Security incident handling
and coordinated remote history remediation are required before work resumes.

## Alternatives considered

### A. Rebuild Product Track from scratch

Rejected. It discards substantial runtime/product implementation, repeats solved work and
delays real product pressure on the research program.

### B. Permanent dual-repository RPC federation

Rejected for the first product body. It preserves duplicate authority, version skew and
operational overhead before scale justifies it.

### C. Direct no-squash import without history scan

Rejected. A clean current worktree says nothing about deleted historical secrets or
sensitive blobs.

### D. History-safe one-time migration after SPINE-0

Accepted. It preserves useful provenance where safe, keeps the first vertical bounded and
ends with one Product Track authority.

## Consequences

- The parent cross-repository prohibition remains the default; this ADR is a narrow,
  auditable exception.
- Agent OS gains no runtime dependency on the donor repository.
- Data Agent migration is no longer part of SPINE-0 completion.
- The migration has a non-negotiable history-safety cost before import.
- A filtered migration mirror may change commit SHAs; provenance mapping becomes required.
- Existing donor product/runtime success does not validate Research Track autonomy claims.
- Until SPINE-1 passes, the donor remains an independent implementation/history source and
  no migration capability may be claimed.

## Verification and review

Required before execution:

- machine-readable migration map validation;
- full-history safety report and digest;
- independent review of scan exceptions and provenance mapping;
- dependency searches proving no Product Track import from donor/staging/Research Track;
- donor characterization and post-extraction behavior tests;
- Git ancestry/provenance verification;
- founder authorization before push or merge.

## Approval record

The founder selected Option B, requested independent Claude review, and then explicitly
authorized applying that review. This ADR records the resulting bounded authorization.
It authorizes design and migration planning now; the execution gates above remain binding.
