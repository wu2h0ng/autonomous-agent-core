# P-SECURITY-BOUNDARY-0A report

## Scope and result

Implemented the scoped-ledger and credential-metadata boundary on exact base
`30902cc65c92ff73a589c6c5b37894386dd5355c`.

- Added closed `LedgerAccessScope` and resolver-free
  `CredentialAuthorizationSnapshot` contracts.
- Replaced Task 4 credential access with `CredentialAuthorizationReader`; the
  admission path cannot read or return `resolver_key`.
- Replaced the global event-ledger reader with `ScopedEventAdmissionReader` and
  a scope-bound private writer capability.
- Added `ScopedSituatedAssessmentReader`; Task 4 and Task 5 reject mismatched
  assessment/event scopes and principals at construction.
- Scoped receipt uniqueness by principal/tenant/workspace/event. Receipt and
  trace reads validate database scope columns against canonical bytes and the
  receipt join. Legacy Task 3 schemas fail closed under exact schema validation.
- Foreign receipt/event/trace/input-digest guesses return no scoped object and
  cannot delegate, increment, transition, or poison another principal's
  PENDING trace.
- Unexpected adapter/provider exceptions are translated to fixed safe errors;
  raw exception strings are not persisted or logged by this slice.

The old local Task 3 databases are disposable pre-integration artifacts. This
package intentionally provides no production migration.

## TDD attack evidence

RED runs reproduced these concrete failures before their fixes:

1. Missing closed security contracts and safe credential reader.
2. Global `environment_event_id` uniqueness causing cross-scope denial of
   service and a reader returning the wrong tenant's first matching row.
3. Task 4/5 accepting mismatched unscoped authority and ledger ports.
4. A scope-A writer accepting a scope-A-looking trace bound to a scope-B
   receipt.
5. Raw adapter and provider exception sentinels escaping through raised errors.

The independent Task 5 attack finding—foreign principal reads and changes an
owner's PENDING trace to `DENIED/AUTHORITY_CHANGED`—is covered by
`test_foreign_principal_cannot_read_or_poison_pending_trace`. The foreign
facade sees neither receipt nor trace; the owner trace remains byte-equivalent
PENDING and assessment/provider delegation remains zero.

## Verification

```text
Task 1-5 plus security boundary: 242 passed
Credential drift matrix:         20 passed
Full Product:                    1028 passed, 1 skipped
Ruff:                            all checks passed
Pyright:                         0 errors, 0 warnings, 0 informations
git diff --check:                passed
```

## Non-claims and deferred work

- No KMS, DLP, PII classifier, production IAM, production HTTP mapping,
  provider invocation, external effect, merge, push, migration, or release.
- Existing assessment free text is not redacted here; it is confined by the
  scoped assessment facade.
- Task 6 composition/error-to-HTTP mapping remains outside this package. The
  sentinel tests establish zero raw-string persistence/logging for Task 4/5,
  not a production observability or HTTP privacy claim.
- No global situated-runtime rewrite was performed.
