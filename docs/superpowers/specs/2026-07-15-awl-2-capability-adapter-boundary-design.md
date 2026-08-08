# AWL-2 Capability Adapter Boundary Design

> Status: FOUNDER-DIRECTION-APPROVED / DESIGN_ONLY / NO_RUNTIME_AUTHORIZATION
> Date: 2026-07-15
> Track: Product architecture
> Parent design: docs/superpowers/specs/2026-07-15-adaptive-work-loop-architecture-recast-design.md
> Exact design base: e1343e3da66414c5bb944420432bf03f66ff4cfb
> Base review: ADM-P4 Kimi TECHNICAL_APPROVE

The parent design was inspected in its isolated AWL-0 worktree. It is not copied into this independently based AWL-2 branch; integration must preserve its exact reviewed commit identity.

## 1. Decision

AWL-2 separates generic capability authority from Developer repository behavior through two narrow ports:

1. Agent Core owns the capability contract, permit validation, C7 check, dispatch boundary and canonical ActionReceipt creation.
2. The Developer adapter owns repository paths, artifacts, patch snapshots, allowlisted test execution, repository prompt construction and provider-proposal normalization.
3. RunCoordinator consumes generic CapabilityPort and ExecutionProfilePort interfaces. It no longer requires a WorkspaceSandbox type and contains no repository patch prompt.
4. The existing patch-compensation event model and coordinator orchestration remain behaviorally unchanged in AWL-2. Their later generic decomposition belongs to AWL-3.

This is a strangler refactor inside the modular monolith. It is not a rewrite, a new capability, a product claim or an authorization to edit Runtime from this docs branch.

## 2. Why this boundary is needed

The exact base currently mixes four different responsibilities in packages/os_core/src/agent_os_core/capability.py:

- generic permit/action matching and dispatch;
- C7 halt and correction-epoch validation;
- ActionReceipt construction;
- Developer-specific filesystem, patch, artifact, test and compensation mechanics.

The exact base also puts Developer semantics inside packages/os_core/src/agent_os_core/execution.py:

- RunCoordinator is typed directly to WorkspaceSandbox;
- the candidate envelope is hard-coded as developer-golden-path;
- the provider prompt contains repository content and requires workspace.apply_patch;
- provider response parsing and patch binding are Developer-specific;
- tool argument derivation knows target_path and test_command;
- outcome extraction knows workspace.run_tests.

The composition root in apps/api_server/app.py then constructs WorkspaceSandbox directly, derives grants from its specs, exposes workspace status and re-creates it during workspace attachment.

This coupling blocks clean SQL, browser, personal-work or Data Agent adapters. Adding another if/elif path would turn Core into a collection of vertical rules. Moving only the class without moving prompt/proposal semantics would preserve the same architectural problem under a different import path.

## 3. Considered approaches

### Approach A — file move only

Move WorkspaceSandbox into domain_packs/developer_agent and leave RunCoordinator unchanged.

Advantages:

- smallest diff;
- most existing tests need only import changes.

Rejected because:

- generic Runtime still requires a repository concrete type;
- patch prompt and tool rules remain in Core;
- future adapters still require Core edits;
- the boundary would be nominal rather than executable.

### Approach B — ports plus Developer execution profile, selected

Move repository effects behind CapabilityPort, keep permit/C7/receipt in CapabilityBroker, and move repository prompt/proposal/tool-argument rules behind ExecutionProfilePort.

Advantages:

- removes the concrete repository type from generic constructors;
- keeps authority checks and receipts in Core;
- preserves event, digest, grant and HTTP behavior;
- gives future adapters a typed seam without implementing them;
- supports incremental TDD and exact equivalence review.

Cost:

- touches capability.py, execution.py, composition wiring and affected tests;
- leaves explicit compensation debt for AWL-3.

### Approach C — generic handler registry and compensation rewrite now

Replace provider, tool, outcome and compensation branches with a full handler registry in one package.

Rejected because:

- overlaps AWL-3 RunCoordinator strangler decomposition;
- would change too many event and recovery assumptions at once;
- creates a broad regression surface before the first seam is proven;
- violates NO_BIG_BANG_REWRITE.

## 4. Target module boundary

~~~text
packages/os_core/src/agent_os_core/
  capability.py
    CapabilityPort
    CapabilityEffect
    CapabilityResult
    CapabilityBroker
  execution_profile.py
    ExecutionProfilePort
  execution.py
    RunCoordinator(CapabilityPort, ExecutionProfilePort, remaining generic dependencies)

domain_packs/developer_agent/
  workspace_capability.py
    DeveloperWorkspaceAdapter
  repository_patch_profile.py
    DeveloperRepositoryPatchProfile
  __init__.py
    manifest
    DeveloperWorkspaceAdapter
    DeveloperRepositoryPatchProfile

apps/api_server/app.py
  composition only:
    construct DeveloperWorkspaceAdapter
    construct DeveloperRepositoryPatchProfile
    inject both into RunCoordinator
~~~

Dependency direction is one-way:

~~~text
contracts <- Agent Core ports <- Developer adapter <- application composition
~~~

Agent Core must not import domain_packs, apps or Developer types. The Developer adapter may import contracts and generic Core port/result types.

## 5. Generic capability contract

### 5.1 CapabilityEffect

CapabilityEffect is an internal, immutable Core value. It describes the connector effect before the authoritative receipt is created.

~~~python
@dataclass(frozen=True)
class CapabilityEffect:
    status: ReceiptStatus
    output: dict[str, object]
    error_code: str = "error:none"
    detail_ref: str = "detail:none"
~~~

It is not a new public Product contract and does not change stored event payloads.

### 5.2 CapabilityPort

~~~python
class CapabilityPort(Protocol):
    def specs(
        self,
        now: datetime | None = None,
        *,
        include_internal: bool = False,
    ) -> Mapping[str, CapabilitySpec]:
        raise NotImplementedError

    def execute(self, action: ActionContract) -> CapabilityEffect:
        raise NotImplementedError
~~~

The port receives no correction authority and creates no permit or ActionReceipt.

### 5.3 CapabilityBroker

CapabilityBroker remains the sole production dispatch boundary. In this order it must:

1. reject permit/action digest mismatch;
2. reject an expired permit before adapter execution;
3. reject a C7 halt;
4. reject stale permit or observed correction epochs;
5. call CapabilityPort.execute exactly once;
6. create ActionReceipt from the exact ActionContract, ActionPermit and CapabilityEffect;
7. return CapabilityResult containing the receipt and output.

The existing ActionPermit and ActionReceipt schemas remain canonical. AWL-2 does not rename ActionReceipt to CapabilityReceipt because that would create a schema/event migration without product value.

The migration preserves the existing failure boundary rather than treating all
`CapabilityDenied` exceptions alike:

- permit/action mismatch, permit expiry, C7 halt and stale correction epochs are
  Broker pre-dispatch rejections; the port is not called and no `ActionReceipt`
  is created;
- argument decoding/type checks, idempotency lookup and cached-effect integrity
  checks remain before the current effect-capture block and therefore keep their
  existing fail-closed exception/no-receipt behavior;
- exceptions raised inside the existing dispatch plus idempotency-write block,
  including `CapabilityDenied`, are converted by the Developer adapter into a
  `FAILED` `CapabilityEffect`; the Broker then creates the same `FAILED`
  `ActionReceipt` with the same error code and detail reference;
- successful and compensated effects create exactly one receipt after exactly
  one port call.

This phase boundary is part of behavioral equivalence. An implementation may
not broadly catch or broadly propagate `CapabilityDenied` while moving the
code.

After AWL-1 integration, CapabilityBroker receives CorrectionSnapshotPort. If AWL-2 is implemented before AWL-1 is integrated, the temporary annotation may remain CorrectionAuthority, but no mutation method may be called.

### 5.4 Bypass boundary

DeveloperWorkspaceAdapter.execute is an internal port method, not a public application action. Production code may call it only through CapabilityBroker. The composition root may retain the concrete adapter for workspace status and artifact reads, but no HTTP, CLI, workflow or provider path may dispatch through it directly.

A static boundary test must fail if:

- Agent Core imports domain_packs.developer_agent;
- a production module other than CapabilityBroker calls the port execute method;
- the app passes a concrete WorkspaceSandbox requirement into RunCoordinator;
- receipt creation moves into the Developer adapter.

The static dispatch gate is exact: production Core contains exactly one
`self.connector.execute(action)` call, inside `CapabilityBroker.invoke`.
`apps/api_server/app.py` and `execution.py` must contain neither
`self.sandbox.execute` nor `self.capabilities.execute`; they call
`CapabilityBroker.invoke` only.

## 6. Developer workspace adapter

DeveloperWorkspaceAdapter receives the existing repository behavior without semantic change:

- path confinement and symlink rejection;
- reserved artifact-state rejection;
- workspace.read;
- workspace.apply_patch;
- workspace.compensate_patch as internal-only;
- workspace.run_tests with the same command allowlist and timeout cap;
- artifact.write with content-addressed storage;
- persistent idempotency records;
- durable patch before-image, manifest and PREPARED/APPLIED/COMPENSATED state;
- replay and later-user-edit protection.

The migration is mechanical:

- the current WorkspaceSandbox filesystem and idempotency helpers move to domain_packs/developer_agent/workspace_capability.py;
- invoke becomes execute and returns CapabilityEffect;
- permit, expiry, C7 and receipt logic moves to CapabilityBroker;
- the adapter keeps the same capability IDs, versions, SideEffectGuarantee values, artifact layout, compensation refs and error classes.

For repository-local compatibility, domain_packs.developer_agent may expose WorkspaceSandbox as a temporary alias of DeveloperWorkspaceAdapter. Agent Core must not re-export that alias. Existing real Product entry points are HTTP/UI/CLI; no released Python SDK contract for agent_os_core.WorkspaceSandbox is claimed. If a downstream consumer outside this repository is discovered, implementation stops for a versioned compatibility decision.

There is, however, one known in-repository historical consumer:
`tests/product_eval/test_lh1a_design.py` imports and instantiates the Core
`WorkspaceSandbox`, names `WorkspaceSandbox.specs` in its frozen runtime-shape
assertion and source-inspects `capability.py` for the concrete class. A Core
re-export, reverse Core-to-domain import or lazy alias is forbidden. Before the
Core export is removed, a separate independently reviewed compatibility
successor must therefore be accepted:

1. preserve the original
   `docs/research/LH-RECOVERY-1A-DESIGN-PRECOMMIT.yaml` bytes and its SHA-256
   `21db5ab15ffa84a7db07ded2f4a9fee1b8683a8212084993b695101845acfa21`;
2. preserve the original LH-RECOVERY-1A generator, environments, evaluator,
   preregistration, baselines, assignments, results and verdicts without edit;
3. add a versioned maintenance-only runtime-shape successor that points to
   `DeveloperWorkspaceAdapter.specs` and the Developer adapter source;
4. update only the live test's import, instantiation and live source-shape
   assertions to consume that successor while retaining an assertion that the
   frozen original manifest still records its historical shape;
5. label the successor exactly
   `TEST_MAINTENANCE_ONLY / NO_RESULT_CHANGE / NO_CLAIM_UPGRADE`; freeze and
   accept its exact patch contract before AWL-2 Runtime work, then materialize
   and independently review the live-test commit after the Developer adapter
   exists but before the Core class/export is removed.

Failure to accept that successor keeps AWL-2 at `DESIGN_ONLY`; it is not a
reason to weaken the Core/domain import boundary or rewrite the historical
research record.

## 7. Developer repository execution profile

ExecutionProfilePort removes prompt and proposal semantics from generic Runtime.

~~~python
class ExecutionProfileError(ValueError):
    """A fail-closed profile validation error with no authority semantics."""


class ExecutionProfilePort(Protocol):
    @property
    def generator_id(self) -> str:
        raise NotImplementedError

    @property
    def generator_version(self) -> str:
        raise NotImplementedError

    def build_provider_request(
        self,
        *,
        task_id: str,
        run_id: str,
        provider_profile: ProviderProfile,
        provider_capability: str,
        context: Mapping[str, Any],
        now: datetime,
    ) -> ProviderRequest:
        raise NotImplementedError

    def bind_provider_response(
        self,
        response: ProviderResponse,
        *,
        context: Mapping[str, Any],
    ) -> tuple[ProviderToolProposal, ...]:
        raise NotImplementedError

    def tool_arguments(
        self,
        capability_id: str,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def requires_provider_bound_action(self, capability_id: str) -> bool:
        raise NotImplementedError

    def verification_exit_code(
        self,
        context: Mapping[str, Any],
    ) -> int | None:
        raise NotImplementedError
~~~

DeveloperRepositoryPatchProfile implements the current behavior exactly:

- generator_id is developer-golden-path;
- generator_version is 1;
- workspace.read requires target_path or path;
- the provider prompt binds goal, path, current SHA-256 and at most 20,000 characters of current content;
- only workspace.apply_patch may be proposed;
- zero or multiple proposals, extra argument fields, a mismatched path or non-string content fail closed;
- text JSON fallback keeps the current parsing behavior;
- expected_sha256 is injected from the reviewed read output;
- workspace.run_tests derives test_command or command, with python -m pytest as the same default;
- workspace.apply_patch requires a provider-bound ActionContract;
- verification_exit_code reads only the workspace.run_tests result.

The Developer profile raises `ExecutionProfileError` with the exact existing
failure message for missing, ambiguous or malformed proposals and invalid
arguments. `RunCoordinator` catches only `ExecutionProfileError` at each
profile call boundary and raises `RunExecutionError(str(exc)) from exc`. The
domain profile does not import `RunExecutionError`, and provider failures remain
separate. This preserves the public coordinator failure type without coupling a
domain adapter back to the execution implementation.

RunCoordinator continues to own provider invocation, ProviderFailure handling, ActionContract construction, policy, approval, broker dispatch, event append and outcome recording. The profile cannot grant authority or execute effects.

## 8. Composition and lifecycle

AgentOSApplication remains the Developer composition root for the current bounded slice.

At construction:

1. create DeveloperWorkspaceAdapter;
2. create DeveloperRepositoryPatchProfile;
3. derive ordinary grants and configuration capability versions from the adapter specs;
4. inject both ports into every RunCoordinator;
5. keep the same developer-agent DomainPackManifest.

During attach_workspace:

1. validate the absolute path and allowlisted root exactly as today;
2. under the existing configuration lock, create a new DeveloperWorkspaceAdapter;
3. rebuild grants from its specs;
4. make later RunCoordinator instances receive the new adapter;
5. do not alter a sealed TaskConfigurationSnapshot or a running Run.

Workspace status and artifact retrieval are application-level Developer functions and may use the concrete adapter. Generic Core does not.

## 9. Compatibility and equivalence contract

AWL-2 preserves:

- capability IDs and versions;
- CapabilitySpec contents;
- CapabilityGrant construction and scope;
- ActionContract and ActionReceipt schemas;
- Task event types and payload shapes;
- provider request allowed capability IDs;
- provider patch validation and expected_sha256 binding;
- idempotency keys and stored record shape;
- artifact and compensation directory layout;
- correction halt/epoch behavior;
- policy, approval and lease-fence checks;
- recovery, reverse compensation and duplicate-effect behavior;
- HTTP/UI/CLI behavior and developer-agent manifest.

The only intended internal API changes are:

- RunCoordinator takes CapabilityPort plus ExecutionProfilePort instead of WorkspaceSandbox;
- workspace behavior is imported from domain_packs.developer_agent rather than agent_os_core;
- CapabilityBroker owns receipt construction and adapter dispatch guards.

All direct authority/idempotency tests that currently call
`sandbox.invoke(action, permit, correction)` migrate to
`CapabilityBroker(adapter, correction).invoke(action, permit)`. All direct
`RunCoordinator` constructions in long-horizon execution, compensation and
rebind regression tests receive the same explicit execution profile as the
application. No temporary adapter `invoke` method may survive the completed
AWL-2 change.

No existing event or canonical contract digest may drift. Any required event/schema migration invalidates AWL-2 and requires a separate reviewed packet.

## 10. Transitional debt deliberately left for AWL-3

The exact base has patch-specific compensation orchestration and PatchCompensationRecord in RunCoordinator. AWL-2 does not rewrite this path.

The temporary state is acceptable only if:

- the concrete WorkspaceSandbox type and repository prompt are absent from generic constructors;
- compensation still dispatches through the generic broker and capability port;
- all existing compensation equivalence tests pass;
- the remaining workspace capability-ID references are listed in the review receipt;
- no new workspace-specific branch is added to RunCoordinator.

AWL-3 must later extract generic ActionPipeline and RecoveryCoordinator behavior behind the stable AWL-2 ports. AWL-2 may not pre-implement that decomposition.

## 11. Test strategy

### Boundary tests

- a fake non-workspace CapabilityPort constructs CapabilityBroker and RunCoordinator;
- Agent Core contains no import of domain_packs or DeveloperWorkspaceAdapter;
- Agent Core capability.py contains no filesystem, subprocess, patch or artifact implementation;
- execution.py contains no repository patch prompt or parser;
- only CapabilityBroker creates ActionReceipt in the capability dispatch path;
- application composition, not Core, imports the Developer adapter.
- exactly one production `self.connector.execute(action)` call exists, in the
  Broker, and neither the app nor execution Core calls a port's `execute`
  method directly;
- `_as_sequence` remains a generic Core helper because Broker receipt creation
  consumes it.

### Authority tests

Use a spy port whose execute count starts at zero. Assert no execution for:

- permit/action mismatch;
- expired permit;
- C7 halt;
- stale correction epoch.

Assert one execution and one receipt for an accepted action. The receipt must bind the exact action digest, permit ID, idempotency key, connector ID, status, output artifacts and detail ref.

### Developer adapter tests

Retain all current path escape, symlink, reserved state, allowlisted test, artifact, idempotency, patch snapshot, replay, tamper and later-user-edit tests. Update imports only where behavior is unchanged.

### Provider-profile tests

Retain the golden path and add direct profile tests for:

- exact allowed capability set;
- reviewed path and SHA binding;
- extra fields;
- path mismatch;
- ambiguous proposal;
- malformed text fallback;
- provider-bound action requirement;
- test-command argument projection.

### End-to-end equivalence

Run existing Product golden path, security, long-horizon recovery, compensation, API surface and task-configuration suites. No provider network call is required.

The initial restored-context `test_exit_code` calculation and every later
post-tool recalculation must both delegate to
`ExecutionProfilePort.verification_exit_code`; replacing only the later call is
not sufficient. The compatibility successor must also run the affected
`tests/product_eval/test_lh1a_design.py` checks without modifying any frozen
research artifact.

## 12. Known base drift

The exact design base was verified before edits with:

~~~text
473 passed, 1 skipped, 2 failed
~~~

Both failures are pre-existing fixed-NOW evaluation-grant expiry baseline drift in tests/product/test_materialization_evaluation_api.py:

- test_http_records_lists_and_restarts_without_mutating_product_state
- test_record_endpoint_bypasses_generic_http_idempotency_cache

Each expected HTTP 201 and received HTTP 403. AWL-2 must not fix or hide these failures. Implementation verification must report either:

- full green if an independently reviewed upstream base has fixed the drift; or
- exactly the same two failures and no new failures if implementation remains on e1343e3.

## 13. Stop rules

Stop and return REVISE if:

1. Core must import a Developer adapter to preserve compatibility;
2. an adapter can create a permit, correction epoch, policy decision or ActionReceipt;
3. a direct production path bypasses CapabilityBroker;
4. capability IDs, versions, grants, events, digests or artifact layout must change;
5. moving the prompt requires new model behavior or provider calls;
6. compensation equivalence cannot be preserved without rewriting recovery;
7. the implementation grows into SQL, browser, Data Agent, plugin registry or AWL-3;
8. the exact-head review cannot distinguish the two known baseline failures from new regressions.
9. the LH-RECOVERY-1A compatibility successor is absent, changes a frozen
   research byte or attempts to preserve compatibility through a Core re-export;
10. the adapter exposes a production `invoke` bypass or app/execution code calls
    `execute` outside the Broker.

## 14. Acceptance

AWL-2 is implementation-ready only when:

- this design and its implementation plan receive an exact-head technical review;
- the implementation starts from an explicitly selected reviewed base;
- TDD freezes authority, receipt, import and prompt boundaries before code moves;
- targeted tests and static boundary checks pass;
- the full Product suite has no regression beyond the documented base drift;
- Ruff, format check, Pyright, compileall and git diff --check pass;
- the implementation branch is independently reviewed;
- the independently reviewed LH-RECOVERY-1A runtime-shape successor is accepted
  and integrated before any Core `WorkspaceSandbox` removal;
- direct invoke and direct constructor call sites are exhaustively inventoried
  and migrated, and broker-only static gates pass;
- no push, merge or release occurs without separate authorization.

This document does not authorize Runtime edits, implementation, integration, push, merge or release.
