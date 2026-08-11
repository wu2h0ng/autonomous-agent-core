# Action Connectors

Action connectors live outside OS Core and must be governed by OperationContract, risk level, approval, and trace.

`action_record` is the current reversible write connector. Its in-memory and SQL stores append real records, enforce connector-local idempotency, audit replay/conflict/ACK-uncertain counts, summarize conflict and uncertain-execution audit facts with payload fingerprints rather than raw audit parameters, and support snapshot/rollback of the local ledger only.

ACK-uncertain recovery is deliberately scoped to the connector-local ledger: a retry with the same idempotency key can recover a committed local write as `idempotent_replay` without appending again. This is not an external-system exactly-once or arbitrary external connector acknowledgement guarantee.

MVP R4/R5 actions are proposal-only.
