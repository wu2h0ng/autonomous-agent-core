# API Server

Application boundary for API and local CLI entry points.

Current implemented entry points:

- `agent_os_api.runtime_factory.ContentCommerceRuntimeFactory`
- `agent_os_api.cli.run_cli`

These entry points load `domain_packs/content_commerce/` contracts and build a runnable
Trusted Loop without importing domain logic into OS Core.

FastAPI endpoints remain staged until request/response contracts and auth boundaries are
approved.
