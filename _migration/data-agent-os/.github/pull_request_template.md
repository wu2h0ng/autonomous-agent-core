## Summary

Describe what changed and why.

## Scope

- [ ] Contracts / schema
- [ ] OS Core
- [ ] SQL Safety
- [ ] EvidenceChain
- [ ] Eval / tests
- [ ] Domain pack
- [ ] Provider / connector
- [ ] API / UI
- [ ] Docs / governance

## Required Checks

- [ ] `python -m unittest discover -s tests -p "test_*.py"`
- [ ] Contract changes include compatibility tests or migration notes.
- [ ] SQL Safety behavior changes include allow/block regression cases.
- [ ] EvidenceChain changes preserve required evidence fields.
- [ ] Domain-specific logic does not enter `packages/os_core/`.
- [ ] R4/R5 actions remain proposal-only unless explicitly approved.

## Risk Notes

List data access, permissions, model, connector, or operational risks.

## Reviewer Notes

Call out anything that needs specific attention.
