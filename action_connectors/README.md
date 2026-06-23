# Action Connectors

Action connectors live outside OS Core and must be governed by OperationContract, risk level, approval, and trace.

`action_record` is the current reversible write connector. Its in-memory and SQL stores append real records, enforce connector-local idempotency, audit replay/conflict counts, summarize conflicts with payload fingerprints rather than raw conflicting parameters, and support snapshot/rollback of the local ledger only.

MVP R4/R5 actions are proposal-only.
