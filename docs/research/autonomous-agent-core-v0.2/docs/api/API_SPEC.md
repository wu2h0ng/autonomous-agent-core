# API Specification

Agent:

POST /agents
POST /agents/{id}/goals
POST /agents/{id}/plans
POST /agents/{id}/actions

Ontology:

GET /ontology/entities
POST /ontology/update

Correction:

POST /corrections/pause
POST /corrections/veto
POST /corrections/rollback

Audit:

GET /events
