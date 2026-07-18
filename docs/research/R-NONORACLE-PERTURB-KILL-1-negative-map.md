# R-NONORACLE-PERTURB-KILL-1 Custody Negative Map

> Disposition: `PARK_HMAC_ASSIGNMENT_COMMITMENT / CUSTODY_TRANSCRIPT_VIOLATION / NOT_FROZEN / NOT_RUN`
> Scope: custody failure only; no mechanism or result run occurred

## What failed

The one-shot HMAC assignment passed its predeclared technical count and block
coverage gates. It still cannot close the split gate. During independent review,
an agent-mediated private check emitted the hidden target-identity key set into
its tool transcript. No key, NTC identity or NTC-side assignment was emitted,
but the scorer custody boundary required that no hidden identity enter chat or
tool transcripts. That stronger condition failed.

The original assignment and public commitment bytes remain preserved as bound
negative evidence. Their mathematical gate success does not repair the custody
failure, and the incident disposition supersedes their earlier public status.

## Rejected rescue moves

- Do not re-key, re-partition or retry this one-shot assignment.
- Do not delete, redact or rewrite the original assignment or commitment bytes.
- Do not treat later transcript deletion as restoration of secrecy.
- Do not use prompt-only instructions as a secret-output boundary.
- Do not freeze or run because the technical count gate passed.

## New path

Any successor package needs a new preregistration and an external non-LLM,
transcript-safe scorer process or service. The minimum boundary is:

1. the secret key and identity mapping stay inside an OS-isolated process or
   service that is not attached to an agent conversation or tool transcript;
2. its output channel is schema-allowlisted before execution and can emit only
   commitments, aggregate counts and predeclared booleans;
3. the private calculation and output projection execute atomically, and raw
   stdout/stderr cannot carry arbitrary identity-bearing objects;
4. an independent verifier receives only the public receipt and booleans, then
   validates exact bindings without loading private assignment objects; and
5. any channel-policy breach fails closed and creates an immutable incident
   receipt rather than triggering a new key or retry.

This is not a retry path for the current package. It is a design requirement
for a separately authorized successor route.
