# Contract Inferencer — Minimal Specification

**Status**: DRAFT v0.3 — v0.2 review fixes: single authorization point (Stage 4.5), propose/apply split, blocking gates, append-only adjust
**Date**: 2026-08-21
**Author**: MainAgent (with Z. review); v0.2 merge
**References**: §7.4 (typed contract + failure paths), §7.9 (specified/implemented/tested separation),
RR-0024 (Autonomy claim form), RR-0029 (architecture-theory gate), ADR-0037 (SD0–SD4 bounded subgoals), C7 (non-writable final authority),
ADM-P1..P4 (promotion skeleton), holdtrue (JAIGP 2026), TiCoder (FSE 2024),
Intent Formalization (Lahiri, MSR 2026), τ-bench pass^k (Sierra 2024),
Verification Design Principles (community, 2026), SmartSnap (arXiv:2512.22322),
Auto-Eval Judge (arXiv:2508.05508)

---

## 1. Purpose

The Contract Inferencer converts a ratified `Mandate` plus available tool/capability
schemas into a **typed, machine-checkable task contract** — success predicates,
evidence bindings, and failure paths — without hand-written domain templates.

It is the missing mechanism between mandate intake (implemented) and outcome
verification (partially implemented). Today, `Commitment.acceptance_criteria` is
`tuple[NonEmptyStr, ...]` — free-text strings with no checkable semantics. The
inferencer replaces that with typed predicates that the existing
`DeterministicOutcomeEvaluator` can execute against collected evidence.

All LLM-proposed semantic predicates require operator confirmation before they
can become blocking (Stage 4.5); no model-proposed success condition gates a
verdict without it (§9.5, §10).

**This is not**: a sub-contract decomposer, a milestone planner, a clause-library
retrieval system, or an auto-promotion engine. Those are deferred (§14).

---

## 2. Definitions

| Term | Meaning |
|---|---|
| **Mandate** | Existing type. Persistent user intent with `mission_statement`, `desired_outcomes`, `permanent_constraints`. |
| **Tool schema** | JSON Schema describing a callable tool: name, description, parameters (typed), response fields, error responses. Derived from `CapabilitySpec.input_contract`/`output_contract` refs or registered directly. |
| **Success predicate** | A single typed, falsifiable condition that must hold for the task to be considered complete. Conjunctive: ALL blocking predicates must pass. |
| **Evidence binding** | A concrete pointer to an observable artifact or state that proves (or disproves) a predicate: a tool response field, a produced artifact, or an environment query. |
| **Mechanical extraction** | Deterministic derivation of structural predicates from schemas. No LLM. |
| **Semantic proposal** | LLM-generated candidate predicates from mandate text + structural context. |
| **Quality gate** | Deterministic validation of proposed predicates: non-vacuity, evidence binding, soundness, coverage. |
| **Clarification** | One bounded round of Yes/No/choice questions to the user for low-confidence predicates. |
| **Confirmation** | Operator batch approval of semantic predicates before they can block (Stage 4.5). C7-aligned: no model-proposed condition gates a verdict without it. |
| **Pre-endorsed** | A clarified predicate whose question the operator answered "yes" (§9.2); shown first in the confirmation batch with default approve. |
| **Blocking predicate** | A predicate whose failure fails the task verdict. Semantic predicates become blocking only after confirmation. |
| **Advisory predicate** | A predicate whose result is recorded as evidence but does not fail the verdict. LLM_JUDGE predicates are always advisory. |

---

## 3. Architecture Overview

```
Mandate + Tool Schemas
        │
        ▼
┌─────────────────────┐
│ Stage 0: Normalize  │  parse mandate, collect tool schemas, derive deliverable schema
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Stage 1: Mechanical │  structural predicates (types, ranges, enums, cardinality,
│      Extraction     │   field presence, tool success codes, evidence anchors)
└─────────┬───────────┘  no LLM, deterministic
          │
          ▼
┌─────────────────────┐
│ Stage 2: Semantic   │  LLM proposes semantic predicates + evidence bindings
│      Proposal       │  one model call, strict JSON output
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Stage 3: Quality    │  non-vacuity, evidence binding, soundness, coverage,
│      Gate           │  confidence threshold → rejects vacuous, flags low-conf
└─────────┬───────────┘  deterministic
          │
          ▼
┌─────────────────────┐
│ Stage 4: Clarify    │  bounded Yes/No questions for low-confidence predicates
│      (optional)     │  skippable: unanswered → predicate downgraded to advisory
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Stage 4.5: Confirm  │  human reviews ALL semantic predicates (batch, C7 gate)
│      (C7 gate)      │  approve/reject/adjust; unconfirmed → advisory
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Stage 5: Freeze     │  content-addressed InferredTaskContract (SHA256)
│                     │  immutable, maps to ExpectedOutcome + EvaluationContract
└─────────┬───────────┘
          │
          ▼
  governed run (execution still literal false;
  verdict chain tested against fixtures for MVP)
          │
          ▼
┌─────────────────────┐
│ Verdict             │  DeterministicOutcomeEvaluator runs blocking predicates
│                     │  against ObservedOutcome evidence
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Correction Hook     │  failed predicate → typed correction record →
│                     │  CorrectionAuthority.halt() (promotion stays DEFER)
└─────────────────────┘
```

---

## 4. Data Model

All types extend `ContractModel` (frozen, extra=forbid, schema_version="1.0",
content-addressed via `content_digest()`).

### 4.1 Enumerations

```python
class PredicateKind(str, Enum):
    STRUCTURAL = "STRUCTURAL"    # mechanically derived from schemas
    SEMANTIC = "SEMANTIC"        # LLM-proposed, not yet confirmed
    CONFIRMED = "CONFIRMED"      # granted only by Stage 4.5 confirmation; only CONFIRMED semantic predicates may block
    PROMOTED = "PROMOTED"        # from correction clause library (future, not MVP)

class CheckType(str, Enum):
    # --- deterministic, blocking-capable ---
    TYPE = "TYPE"                       # value is of expected JSON type
    RANGE = "RANGE"                     # numeric/string-length/date within bounds
    ENUM = "ENUM"                       # value in allowed set
    REGEX = "REGEX"                     # string matches pattern
    CARDINALITY = "CARDINALITY"         # count of items within [min, max]
    FIELD_PRESENCE = "FIELD_PRESENCE"   # required field exists and is non-null
    STATE_DELTA = "STATE_DELTA"         # environment state changed by expected amount
    TOOL_RESPONSE = "TOOL_RESPONSE"     # specific tool call response satisfies condition
    ARTIFACT_EXISTS = "ARTIFACT_EXISTS" # artifact exists at path with expected hash
    ARTIFACT_CONTENT = "ARTIFACT_CONTENT" # artifact content satisfies condition
    CROSS_CONSISTENCY = "CROSS_CONSISTENCY" # values across artifacts/fields agree
    # --- soft, advisory only ---
    LLM_JUDGE = "LLM_JUDGE"             # LLM evaluates rubric; never blocks

class EvidenceSourceType(str, Enum):
    TOOL_RESPONSE = "TOOL_RESPONSE"
    ARTIFACT = "ARTIFACT"
    ENVIRONMENT_QUERY = "ENVIRONMENT_QUERY"
    ACTION_RECEIPT = "ACTION_RECEIPT"
```

### 4.2 EvidenceBinding

```python
class EvidenceBinding(ContractModel):
    binding_id: NonEmptyStr
    source_type: EvidenceSourceType
    # TOOL_RESPONSE: tool call selector (e.g. "send_email:last")
    # ARTIFACT: artifact path or pattern (e.g. "deliverables/report.json")
    # ENVIRONMENT_QUERY: query descriptor (e.g. "db:SELECT count(*) FROM orders WHERE ...")
    # ACTION_RECEIPT: action_id pattern
    source_selector: NonEmptyStr
    # JSONPath/jq into the source to extract the value under test.
    # None means "the entire source" (e.g. artifact existence).
    extract_path: NonEmptyStr | None = None
    # Human-readable: what this evidence proves. One sentence.
    relation: NonEmptyStr
```

### 4.3 SuccessPredicate

```python
class SuccessPredicate(ContractModel):
    predicate_id: NonEmptyStr          # stable, content-derived ("pred:<sha256[:12]>")
    kind: PredicateKind
    description: NonEmptyStr           # one sentence, human-readable, states the condition positively
    check_type: CheckType
    # Type-specific parameters. Validated by Quality Gate against check_type.
    # See §4.4 for required params per check_type.
    check_params: dict[str, Any]
    evidence_bindings: tuple[EvidenceBinding, ...] = Field(min_length=1)
    blocking: bool = True
    confidence: float = Field(ge=0.0, le=1.0)  # 1.0 for STRUCTURAL; model-reported for SEMANTIC
    # Provenance (proposal origin; authorization is tracked separately in
    # PredicateConfirmation records and is never mutated here):
    #   "mechanical:<extractor_name>"     e.g. "mechanical:tool_response_schema"
    #   "llm:<model_id>"                  e.g. "llm:gpt-5-2026-08-21"
    #   "operator:<principal_id>"         operator-submitted replacement via adjust
    #   "promoted:<clause_id>"            (future)
    source: NonEmptyStr
    # Set by Quality Gate. A predicate with falsifiable=False is rejected.
    falsifiable: bool = False
    # Which of the 7 domain-agnostic meta-templates this instantiates, if any:
    # schema | cardinality | consistency | evidence_anchor | version_conflict | coverage | scope
    meta_template: NonEmptyStr | None = None
    # Reserved for clause-library reuse and cross-domain pollution control when
    # retrieval/promotion opens (§14). Empty in MVP; the field exists now to
    # avoid a schema migration later.
    scope_tags: tuple[NonEmptyStr, ...] = ()
```

### 4.4 check_params by check_type

| check_type | required params | example |
|---|---|---|
| TYPE | `field`, `expected_type` (`"string"`/`"number"`/`"integer"`/`"boolean"`/`"array"`/`"object"`) | `{"field":"$.status","expected_type":"string"}` |
| RANGE | `field`, `min`?, `max`? | `{"field":"$.total","min":0,"max":10000}` |
| ENUM | `field`, `allowed_values` (list) | `{"field":"$.cabin","allowed_values":["economy","business"]}` |
| REGEX | `field`, `pattern` | `{"field":"$.email","pattern":"^[^@]+@[^@]+$"}` |
| CARDINALITY | `target`, `min_count`?, `max_count`? | `{"target":"$.items","min_count":1,"max_count":20}` |
| FIELD_PRESENCE | `field` | `{"field":"$.message_id"}` |
| STATE_DELTA | `query`, `expected_delta` (dict), `baseline_ref` | `{"query":"db:SELECT count(*) FROM emails WHERE folder='sent'","expected_delta":{"$gte":1},"baseline_ref":"pre-run"}` |
| TOOL_RESPONSE | `tool_name`, `condition` (dict of field→expected value or operator) | `{"tool_name":"send_email","condition":{"$.status_code":200,"$.body.message_id":{"$exists":true}}}` |
| ARTIFACT_EXISTS | `path`, `expected_media_type`? | `{"path":"deliverables/report.json","expected_media_type":"application/json"}` |
| ARTIFACT_CONTENT | `path`, `content_assertions` (list of TYPE/RANGE/ENUM/REGEX on extracted fields) | `{"path":"deliverables/report.json","content_assertions":[{"field":"$.suppliers","kind":"CARDINALITY","min_count":1}]}` |
| CROSS_CONSISTENCY | `refs` (list of field selectors), `relation` (`"equal"`/`"sum_equals"`/`"subset"`/`"superset"`) | `{"refs":["$.report.selected_count","$.emails.sent_count"],"relation":"equal"}` |
| LLM_JUDGE | `rubric` (string), `evidence_refs` (list of binding_ids) | `{"rubric":"The email is polite and addresses the recipient by name.","evidence_refs":["bind:1"]}` |

### 4.5 FailurePath

```python
class FailurePath(ContractModel):
    failure_path_id: NonEmptyStr
    # Trigger condition, e.g. "tool response status 429" or "predicate pred:abc fails"
    trigger: NonEmptyStr
    action: Literal["abort", "retry", "escalate", "compensate"]
    max_retries: int = Field(ge=0, default=0)
    escalation_target: NonEmptyStr = "human"
```

### 4.6 Clarification

```python
class ClarificationQuestion(ContractModel):
    question_id: NonEmptyStr
    predicate_id: NonEmptyStr
    question: NonEmptyStr             # specific, bounded, answerable without expertise
    question_type: Literal["yes_no", "choice", "value"]
    options: tuple[NonEmptyStr, ...] = ()  # required for choice
    # What happens to the predicate if the user does not answer:
    #   "drop" — remove predicate
    #   "downgrade" — keep as advisory (blocking=False)
    on_unanswered: Literal["drop", "downgrade"] = "downgrade"

class ClarificationAnswer(ContractModel):
    question_id: NonEmptyStr
    answer: NonEmptyStr
    answered_at: UtcDateTime

class PredicateConfirmation(ContractModel):
    predicate_id: NonEmptyStr
    decision: Literal["approve", "reject", "adjust"]
    adjusted_predicate: SuccessPredicate | None = None  # required when decision="adjust"; full replacement, new content-derived id
    pre_endorsed: bool = False  # clarified "yes" prior to batch confirm; default approve
    confirmed_by: NonEmptyStr
    confirmed_at: UtcDateTime
```

### 4.7 InferredTaskContract

```python
class InferredTaskContract(ContractModel):
    contract_id: NonEmptyStr          # "itc:" + content_digest(self excluding contract_id)
    mandate_id: NonEmptyStr
    mandate_digest: Sha256Digest
    task_id: NonEmptyStr
    inferred_at: UtcDateTime
    inferrer_version: NonEmptyStr     # e.g. "contract-inferencer/0.1.0"
    model_id: NonEmptyStr             # LLM used for semantic proposal; "none" if mechanical-only
    # JSON Schema of the expected final deliverable. Mechanically derived where possible,
    # LLM-proposed for semantic fields.
    deliverable_schema: dict[str, Any]
    preconditions: tuple[SuccessPredicate, ...] = ()
    success_predicates: tuple[SuccessPredicate, ...] = Field(min_length=1)
    failure_paths: tuple[FailurePath, ...] = ()
    clarification_questions: tuple[ClarificationQuestion, ...] = ()
    clarification_answers: tuple[ClarificationAnswer, ...] = ()
    confirmation_records: tuple[PredicateConfirmation, ...] = ()
    confirmation_status: Literal["PENDING", "CONFIRMED", "NOT_REQUIRED"] = "PENDING"
    unresolved_items: tuple[NonEmptyStr, ...] = ()
    warnings: tuple[NonEmptyStr, ...] = ()
    meta_templates_instantiated: tuple[NonEmptyStr, ...] = ()
```

### 4.8 InferenceReport

```python
class InferenceReport(ContractModel):
    report_id: NonEmptyStr
    contract_id: NonEmptyStr
    mandate_id: NonEmptyStr
    pipeline_state: Literal["QUESTIONS_PENDING", "CONFIRMATION_PENDING", "FROZEN", "REJECTED"]
    mechanical_count: int = Field(ge=0)
    semantic_proposed_count: int = Field(ge=0)
    semantic_rejected_count: int = Field(ge=0)   # rejected by quality gate
    confirmed_count: int = Field(ge=0)
    blocking_count: int = Field(ge=0)
    advisory_count: int = Field(ge=0)
    clarification_raised: int = Field(ge=0)
    clarification_answered: int = Field(ge=0)
    coverage_gaps: tuple[NonEmptyStr, ...] = ()
    inference_latency_ms: int = Field(ge=0)
    model_id: NonEmptyStr
    created_at: UtcDateTime
```

---

## 5. Stage 0 — Input Normalization

**Input**:
- `Mandate` (ratified)
- `list[ToolSchema]` — each tool's JSON Schema for parameters and response
- `task_id` — caller-provided task identifier

**Processing** (deterministic):
1. Validate mandate is RATIFIED or ACTIVE.
2. Collect tool schemas. If a `CapabilitySpec` references `input_contract`/`output_contract`
   as artifact refs, resolve them to JSON Schema. If unresolved, record a warning and
   proceed without that tool's schema (mechanical extraction will be weaker).
3. Parse `mandate.mission_statement` + `mandate.desired_outcomes` for explicit
   deliverable format hints:
   - Keywords: "JSON", "CSV", "email", "spreadsheet", "report", "file named X"
   - If explicit JSON fields are named, seed `deliverable_schema.properties`.
   - If no format hint, default `deliverable_schema` to `{"type":"object"}` and let
     Stage 2 propose fields.
4. Record `mandate_digest = content_digest(mandate)`.

**Output**: normalized context object passed to Stage 1 and Stage 2.

---

## 6. Stage 1 — Mechanical Extraction

**No LLM. Fully deterministic. Pure functions over schemas.**

For each tool schema, derive:

| Extraction | Predicate | check_type |
|---|---|---|
| Required parameter with type | Parameter must be present and typed when tool is called | TYPE + FIELD_PRESENCE |
| Parameter with enum constraint | Argument value in enum | ENUM |
| Parameter with min/max | Argument within range | RANGE |
| Parameter with pattern | Argument matches regex | REGEX |
| Success response (e.g. 2xx) with body schema | Tool call must succeed; response fields present | TOOL_RESPONSE |
| Response contains ID/confirmation field | That field is an evidence anchor (binding, not predicate by itself) | evidence binding on the relevant success predicate |
| Error responses (4xx/5xx) | Each documented error → FailurePath | failure_paths |
| Side-effect guarantee = NON_IDEMPOTENT_NON_QUERYABLE | FailurePath with action=escalate (mirrors PolicyKernel) | failure_paths |

Cross-tool derivations:
- If the mandate names a deliverable format matching a tool's response schema,
  derive ARTIFACT_EXISTS or CROSS_CONSISTENCY predicates.
- If multiple tools write to the same entity, derive a CROSS_CONSISTENCY predicate
  (e.g. number of emails sent equals number of suppliers selected).

All mechanically extracted predicates have:
- `kind=STRUCTURAL`, `confidence=1.0`, `falsifiable=True` (set by construction),
  `blocking=True`, `source="mechanical:<extractor>"`.

**Design rule**: Mechanical extraction never invents semantic conditions. It only
encodes what the schema already guarantees or requires. If a schema says a field
is required, the predicate checks that the field is present — not that its value
is semantically correct.

---

## 7. Stage 2 — Semantic Proposal

**One LLM call.** The model receives a structured prompt and returns strict JSON
matching `list[SuccessPredicate]`.

### 7.1 Prompt contract

The prompt MUST include the following sections, in order:

1. **System instruction**: role is "contract drafter," not "task executor."
   Output only the JSON array. No prose. No markdown fences.

2. **Mandate text**: `mission_statement`, `desired_outcomes`, `permanent_constraints`,
   verbatim.

3. **Available tools**: name, description, parameter schema (names, types, constraints,
   required), response schema (field names, types, success indicators), documented
   errors. Full JSON Schema, not summaries.

4. **Already-extracted structural predicates**: the Stage 1 output as JSON.
   Instruction: "Do not duplicate these. Propose ADDITIONAL semantic predicates
   that structural checks cannot capture."

5. **Deliverable schema seed**: the Stage 0 output.

6. **Meta-template primitives** (the 7 domain-agnostic types, each with one-line
   definition and one example):
   - `schema` — type/format constraints on deliverable fields
   - `cardinality` — how many of something (exact count, min, max)
   - `consistency` — values across artifacts/fields agree
   - `evidence_anchor` — a specific artifact/state that proves completion
   - `version_conflict` — concurrent modification / stale state detection
   - `coverage` — all items in scope were processed (no silent skips)
   - `scope` — no unauthorized actions or out-of-scope effects

7. **Hard rules** (numbered, explicit):
   - R1: Every predicate MUST bind to at least one `EvidenceBinding` with a concrete
     `source_selector` referencing an available tool response, a named artifact, or
     an environment query. A predicate without observable evidence is invalid.
   - R2: Every predicate MUST be falsifiable: there must exist a concrete outcome
     state that would fail it. Do not propose tautologies ("result is not null"
     when the tool always returns non-null).
   - R3: Do NOT propose predicates about the agent's reasoning, effort, or process.
     Only predicates about observable outcomes, artifacts, and environment state.
   - R4: Prefer deterministic check types (TYPE, RANGE, ENUM, REGEX, CARDINALITY,
     FIELD_PRESENCE, STATE_DELTA, TOOL_RESPONSE, ARTIFACT_EXISTS, ARTIFACT_CONTENT,
     CROSS_CONSISTENCY). Use LLM_JUDGE only when no deterministic check can
     capture the condition, and mark it `blocking=false`.
   - R5: Each predicate's `description` must state the condition in positive,
     specific language. A stranger reading only the description must know what
     "done" looks like.
   - R6: Assign `confidence` honestly: 0.9+ if the mandate explicitly states the
     condition; 0.7–0.9 if strongly implied; below 0.7 if inferred from domain
     knowledge not stated in the mandate.
   - R7: Do not propose predicates that duplicate structural predicates from
     section 4.
   - R8: For each predicate, set `meta_template` to one of the 7 primitives if
     applicable, else null.
   - R9: `scope_tags` MUST be `[]` in this version. Do not propose domain tags.

8. **Two examples**:
   - Good predicate: semantic, evidence-bound, falsifiable (e.g. "selected supplier
     has the lowest landed cost among qualified suppliers" with evidence binding
     to the comparison artifact).
   - Bad predicate: vague, no evidence, non-falsifiable (e.g. "the report looks
     good" with no binding), with explanation of why it is rejected.

9. **Output instruction**: return a JSON array of SuccessPredicate objects.
   Maximum 15 semantic predicates (structural predicates are derived in
   Stage 1 and do not count). Prioritize the most important conditions.

### 7.2 Model call parameters

- Temperature: 0 (deterministic output preferred)
- Response format: JSON mode / structured output enforced
- Timeout: 30s
- On invalid JSON: one retry with the validation error appended; if still invalid,
  the pipeline is REJECTED with fatal warning
  (`"semantic_proposal_failed: <error>"`) — no contract proceeds on silent
  semantic-proposal failure, because a structural-only contract would verify
  schema shape while missing the task's intent. Distinct from §8.2's fatal
  (zero predicates after Q1–Q3); here Stage 2 itself failed.

### 7.3 Output

`list[SuccessPredicate]` with `kind=SEMANTIC`, `source="llm:<model_id>"`,
`falsifiable=False` (to be set by Quality Gate).

---

## 8. Stage 3 — Quality Gate

**Deterministic. No LLM.** Runs after Stage 2 (and again after Stage 4 clarification).

### 8.1 Checks

**Q1 — Evidence binding validity** (blocking rejection):
- Every predicate has ≥1 EvidenceBinding.
- Every binding's `source_selector` references an available tool name, a plausible
  artifact path (string non-empty), or an environment query descriptor.
- Bindings referencing unknown tools are rejected with reason.

**Q2 — Non-vacuity** (blocking rejection):
- `check_type` is not LLM_JUDGE (those are advisory by definition).
- `check_params` contains the required keys for its `check_type` (per §4.4 table).
- The predicate constrains a value: at least one of `expected_type`, `min`/`max`,
  `allowed_values`, `pattern`, `min_count`/`max_count`, `condition`,
  `content_assertions`, or `relation` is present and non-trivial.
- A FIELD_PRESENCE predicate is non-vacuous only if the field is not already
  guaranteed by a structural predicate (no duplicate trivial checks).

**Q3 — LLM_JUDGE isolation** (blocking rejection):
- Any predicate with `check_type=LLM_JUDGE` MUST have `blocking=False`.

**Q4 — Soundness (contradiction detection)** (warning, not rejection, for MVP):
- If two predicates constrain the same `extract_path` with incompatible conditions
  (e.g. RANGE max=100 and RANGE min=200), emit a warning and drop the lower-confidence
  predicate. Record both in `warnings`.

**Q5 — Coverage** (warning):
- Every field in `deliverable_schema.properties` should be referenced by at least
  one predicate's evidence binding or check_params. Uncovered fields → `coverage_gaps`.

**Q6 — Confidence routing** (v0.2: confidence never auto-grants blocking status):
- SEMANTIC predicates with `confidence < CLARIFICATION_THRESHOLD` (default 0.7)
  generate ClarificationQuestions (Stage 4).
- SEMANTIC predicates with `confidence >= CLARIFICATION_THRESHOLD` are routed
  to Contract Confirmation (Stage 4.5). They stay `kind=SEMANTIC`; `blocking`
  is not finalized until confirmed. No model-proposed semantic predicate
  becomes blocking without operator confirmation (holdtrue; Lahiri).

**Q7 — Meta-template tagging**:
- If `meta_template` is set, validate it is one of the 7 allowed values.

### 8.2 Output

- `accepted: list[SuccessPredicate]` — with `falsifiable=True` set
- `rejected: list[tuple[SuccessPredicate, reason]]`
- `clarification_needed: list[SuccessPredicate]` — low-confidence, generate questions
- `confirmation_needed: list[SuccessPredicate]` — high-confidence SEMANTIC, route to Stage 4.5
- `warnings: list[str]`
- `coverage_gaps: list[str]`

If zero predicates survive Q1–Q3 (regardless of blocking status), the
inferencer MUST NOT produce a contract. It returns an `InferenceReport` with
`pipeline_state=REJECTED` and a fatal warning:
`"no_predicates_survived: contract would be vacuous"`. The caller must decide:
provide more tool schemas or escalate to human. A contract consisting only of
SEMANTIC predicates awaiting confirmation is a valid PENDING state and does
NOT trigger this condition; the blocking-count gate applies at freeze (§10).

---

## 9. Stage 4 — Clarification & Confirmation Protocol

**One bounded round. Skippable. TiCoder-style (Fakhoury et al., FSE 2024).**

### 9.1 Question generation

For each predicate in `clarification_needed`, generate one `ClarificationQuestion`:
- `question_type="yes_no"` for most cases: "Should <condition described in predicate.description>?"
- `question_type="choice"` when the predicate has multiple interpretations (options
  derived from `check_params` where possible).
- Questions must be answerable by a non-expert user in one sentence.
- No open-ended "what do you want?" questions.

### 9.2 User answers

The caller presents questions and returns `list[ClarificationAnswer]`. Each answer
is one of:
- **"yes"** → ambiguity resolved: `check_params` updated per answer, `confidence=1.0`. `kind` stays SEMANTIC and `blocking` stays unset; the predicate is marked `pre_endorsed=True` and enters the Stage 4.5 confirmation batch with default approve. Stage 4.5 is the sole point where CONFIRMED and blocking are granted.
- **"no"** → predicate is removed.
- **A choice value** → predicate's `check_params` are updated with the chosen value,
  `confidence=1.0`, `kind` stays SEMANTIC, `pre_endorsed=True` for Stage 4.5.
- **Unanswered** (user skips) → predicate is handled per `on_unanswered`:
  - `"downgrade"` (default): kept with `blocking=False`, kind stays SEMANTIC,
    `confidence` unchanged. Recorded in `unresolved_items`.
  - `"drop"`: removed.

### 9.3 Re-run quality gate

After applying answers, re-run Stage 3 Q1–Q5 on the updated predicate set. This
catches contradictions introduced by user answers.

### 9.4 Bounds

- Maximum 7 questions per inference (cognitive load bound).
- If more than 7 predicates need clarification, only the 7 with lowest confidence
  are surfaced; the rest are downgraded to advisory with a warning.
- No follow-up rounds in MVP.

---

### 9.5 Contract Confirmation (C7 gate)

**v0.2 addition.** holdtrue's central finding: the human approves the
*contract*, not the code. Lahiri's boundary: "there is no oracle for
specification correctness other than the user." Model self-reported
`confidence` never substitutes for operator confirmation. Stage 4.5 is the
sole point where a semantic predicate can become CONFIRMED and blocking.

**Input** — two groups of SEMANTIC predicates in one batch:
- `actionable`: high-confidence predicates routed by Q6, never clarified;
- `pre_endorsed`: predicates whose clarification question the operator
  answered "yes" (§9.2). Shown first with default `approve`; the operator can
  expand, edit, or override any of them.

STRUCTURAL predicates are listed read-only for context and are not part of
the decision set.

**Processing**:
1. Operator decides per semantic predicate:
   - `approve` → kind=CONFIRMED, confidence=1.0, blocking as proposed;
   - `reject` → removed;
   - `adjust` → operator submits a complete replacement predicate
     (`adjusted_predicate`). The replacement runs Stage 3 Q1–Q5; if it fails,
     the adjust is rejected and the original predicate is dropped with a
     warning. If it passes, the replacement is CONFIRMED with its own
     `PredicateConfirmation` record; the original's record documents the
     lineage (old `predicate_id` → replacement predicate).
2. **Adjust never modifies in place.** A replacement is a new predicate with a
   new content-derived id; the original remains in the confirmation history
   (append-only). Silent weakening is impossible; operator-approved changes —
   including narrowing or widening — are allowed, because the operator is the
   spec oracle (Lahiri). What is forbidden is any change without a
   confirmation record.
3. Predicates left unconfirmed are downgraded to `blocking=False` (advisory).
   Unconfirmed predicates never silently become blocking.
4. `PredicateConfirmation` records persist into
   `InferredTaskContract.confirmation_records`; `confirmation_status` moves
   PENDING → CONFIRMED, or NOT_REQUIRED when the contract has zero semantic
   predicates.
5. After applying decisions, count blocking predicates. If `blocking_count == 0`
   (all semantic rejected and no structural predicates exist), freeze is
   refused and the contract is REJECTED with fatal warning
   `"no_blocking_predicates"` (§10, §8.2).

**Bounds**: the decision set contains ≤15 semantic predicates (§7.1 caps the
proposal); structural predicates are read-only context and may exceed 15.

**Rationale against the v0.1 alternative** (confidence-threshold auto-accept):
a high-confidence but semantically wrong predicate — e.g. "supplier must be in
Shenzhen" never stated in the mandate — would become a blocking verdict
condition the operator never saw. Q1–Q3 check form, not meaning.

---

## 10. Stage 5 — Freeze

0. Freeze gates: (a) if semantic predicates exist and `confirmation_status`
   is PENDING, do not freeze — return the contract in PENDING state; (b) if
   `blocking_count == 0`, do not freeze — return REJECTED with fatal warning
   `"no_blocking_predicates"`. Freeze requires `confirmation_status` ∈
   {CONFIRMED, NOT_REQUIRED} and at least one blocking predicate.
1. Assemble `InferredTaskContract` from accepted predicates, failure paths,
   clarification record, confirmation records, warnings.
2. Compute `contract_id = "itc:" + content_digest(contract excluding contract_id)`.
3. Compute `InferenceReport`.
4. Both objects are immutable (`ContractModel.frozen=True`).
5. Persist both to the workspace record alongside the mandate.

The frozen contract is the artifact that maps to the existing evaluation types
(§11). It does not authorize execution (C7: `MandateWorkspaceRecord` cannot
authorize execution; that remains externally gated).

---

## 11. Contract → Verdict Integration

The inferred contract maps to existing types without modifying them:

### 11.1 Mapping to ExpectedOutcome

One `ExpectedOutcome` per blocking predicate (or one aggregate with conjunctive
semantics — decision below). ExpectedOutcome records are materialized at freeze
time, when the blocking set is final — never during inference.

| InferredTaskContract field | ExpectedOutcome field |
|---|---|
| `predicate_id` | `expected_outcome_id` |
| `task_id` | `task_id` |
| `"predicate:" + check_type` | `evaluator_type` |
| inferrer version | `evaluator_version` |
| evidence binding selectors | `evidence_requirements` |
| failure semantics from failure_paths | `failure_semantics` |
| `1.0` (conjunctive: all must pass) | `threshold` |
| run timeout from mandate | `observation_window_seconds` |
| freeze time | `frozen_at` |

**Decision (MVP)**: one ExpectedOutcome per predicate. This gives per-predicate
failure granularity in the verdict, which is required for typed corrections (§12).
Aggregation (all must pass) is the caller's conjunctive AND.

### 11.2 Predicate execution by DeterministicOutcomeEvaluator

The evaluator needs a new dispatch layer: given an `ExpectedOutcome` with
`evaluator_type="predicate:<check_type>"`, execute the corresponding check
against the `ObservedOutcome.evidence_refs`:

| check_type | execution |
|---|---|
| TYPE/RANGE/ENUM/REGEX | Resolve evidence binding → extract value via `extract_path` → evaluate condition |
| CARDINALITY | Count items at target → compare to min/max |
| FIELD_PRESENCE | Extract value → check non-null |
| STATE_DELTA | Compare pre-run baseline vs post-run query result → evaluate delta |
| TOOL_RESPONSE | Find tool call receipt matching `tool_name` → evaluate condition on response |
| ARTIFACT_EXISTS | Resolve artifact ref → check existence + media type |
| ARTIFACT_CONTENT | Load artifact → run content_assertions |
| CROSS_CONSISTENCY | Extract all referenced values → evaluate relation |
| LLM_JUDGE | Call judge model with rubric + evidence → record score; NEVER fail the verdict |

All deterministic check types return binary pass/fail with the observed value
recorded. LLM_JUDGE returns a score in [0,1] recorded as advisory evidence.

### 11.3 Verdict aggregation

- If ANY blocking predicate fails → overall verdict `NOT_MET`.
- If all blocking predicates pass → `VERIFIED`.
- If evidence is missing for a blocking predicate → `UNRESOLVED` with
  `unresolved_gaps` listing the missing evidence refs.
- Advisory predicate results are recorded in evidence but do not affect status.

This maps directly to the existing `OutcomeStatus` enum (VERIFIED / NOT_MET /
UNRESOLVED / INVALID) and `EvaluationResultReceipt.result`
(MET / NOT_MET / INCONCLUSIVE / INVALID).

---

## 12. Correction Hook

When a blocking predicate fails:

1. Produce a `TypedPredicateCorrection`:
   ```python
   class TypedPredicateCorrection(ContractModel):
       correction_id: NonEmptyStr
       contract_id: NonEmptyStr
       predicate_id: NonEmptyStr
       predicate_description: NonEmptyStr
       observed_value: dict[str, Any]   # what the evidence actually showed
       expected_condition: dict[str, Any]  # the check_params that failed
       failure_code: Literal[
           "CRITERIA_NOT_MET",        # evidence present, condition failed
           "INSUFFICIENT_EVIDENCE",   # evidence missing
           "UNSUPPORTED",             # check type not executable
       ]
       evidence_refs: tuple[NonEmptyStr, ...]
       created_at: UtcDateTime
   ```

2. Call `CorrectionAuthority.correct(scope="task", scope_id=task_id,
   reason=correction_id)` — this halts the task run (existing mechanism).

3. The `TypedPredicateCorrection` is persisted. It is the structured input for:
   - **Human review**: the operator sees exactly which predicate failed, what was
     observed, and what was expected.
   - **Future clause proposal** (post-MVP): the correction + failure evidence
     feeds a new semantic proposal round, producing a candidate clause that goes
     through the quality gate and C7-gated promotion (ADM-P1..P4).

4. **MVP explicitly does NOT auto-promote.** The correction is recorded and halts;
   promotion remains DEFER per current ADM production policy. The hook is the
   seam where promotion connects later.

---

## 13. Component Interfaces

```python
from typing import Protocol

class ToolSchemaProvider(Protocol):
    """Resolves capability refs to JSON Schemas."""
    def get_tool_schemas(self, mandate: Mandate) -> list[dict]: ...

class MechanicalExtractor(Protocol):
    """Pure deterministic extraction. No LLM, no I/O beyond schema parsing."""
    def extract(
        self,
        mandate: Mandate,
        tool_schemas: list[dict],
        deliverable_schema_seed: dict,
    ) -> tuple[list[SuccessPredicate], list[FailurePath], dict]:
        """Returns (structural predicates, failure paths, updated deliverable schema)."""
        ...

class SemanticProposer(Protocol):
    """One LLM call. Returns candidate semantic predicates."""
    def propose(
        self,
        mandate: Mandate,
        tool_schemas: list[dict],
        structural_predicates: list[SuccessPredicate],
        deliverable_schema: dict,
    ) -> list[SuccessPredicate]:
        ...

class QualityGate(Protocol):
    """Deterministic validation."""
    def check(
        self,
        predicates: list[SuccessPredicate],
        tool_schemas: list[dict],
        deliverable_schema: dict,
    ) -> "QualityGateResult": ...

class ClarificationProtocol(Protocol):
    """Generates questions; applies answers."""
    def generate_questions(
        self,
        predicates: list[SuccessPredicate],
        max_questions: int = 7,
    ) -> list[ClarificationQuestion]: ...

    def apply_answers(
        self,
        contract: InferredTaskContract,
        answers: list[ClarificationAnswer],
    ) -> InferredTaskContract: ...

class ContractInferencer(Protocol):
    """Top-level orchestrator. One-shot propose + deterministic apply steps.

    Stage 2 (the only LLM call) runs exactly once per mandate, inside infer().
    apply_clarification and apply_confirmation are pure transformations on the
    contract object — no LLM, no re-proposal — so repeated calls are
    deterministic even if the model backend changes between calls.
    """
    def infer(
        self,
        mandate: Mandate,
        task_id: str,
        tool_schemas: list[dict] | None = None,
    ) -> tuple[InferredTaskContract, InferenceReport]:
        """
        Runs stages 0–3. Returns a contract whose `InferenceReport.pipeline_state` is:
        - QUESTIONS_PENDING: clarification questions raised, awaiting answers;
        - CONFIRMATION_PENDING: no questions (or answers already applied),
          awaiting confirmation decisions;
        - FROZEN: zero semantic predicates, confirmation NOT_REQUIRED;
        - REJECTED: zero predicates survived Q1–Q3 (§8.2).
        """
        ...

    def apply_clarification(
        self,
        contract: InferredTaskContract,
        answers: list[ClarificationAnswer],
    ) -> tuple[InferredTaskContract, InferenceReport]:
        """Stage 4. Deterministic; re-runs Q1–Q5. Returns CONFIRMATION_PENDING,
        or FROZEN when zero semantic predicates remain and blocking ≥ 1."""
        ...

    def apply_confirmation(
        self,
        contract: InferredTaskContract,
        decisions: list[PredicateConfirmation],
    ) -> tuple[InferredTaskContract, InferenceReport]:
        """Stage 4.5 + Stage 5. Deterministic; re-runs Q1–Q5 on adjusted
        predicates. Returns FROZEN, or REJECTED with fatal warning
        "no_blocking_predicates" when blocking_count == 0."""
        ...
```

### Invocation flow (two-call design for clarification)

```python
contract, report = inferencer.infer(mandate, task_id, tool_schemas)

if report.pipeline_state == "QUESTIONS_PENDING":
    answers = ui.prompt(contract.clarification_questions)
    contract, report = inferencer.apply_clarification(contract, answers)

if report.pipeline_state == "CONFIRMATION_PENDING":
    # Stage 4.5: operator reviews ALL semantic predicates (batch, C7 gate)
    decisions = ui.confirm(contract.success_predicates)
    contract, report = inferencer.apply_confirmation(contract, decisions)

# report.pipeline_state is FROZEN (ready for verdict mapping) or REJECTED

# State transition table:
# | Call                 | Inputs                     | Resulting pipeline_state                       |
# |----------------------|----------------------------|------------------------------------------------|
# | infer                | mandate + schemas          | QUESTIONS_PENDING / CONFIRMATION_PENDING /     |
# |                      |                            | FROZEN (pure structural, blocking ≥ 1) /       |
# |                      |                            | REJECTED (zero predicates)                     |
# | apply_clarification  | contract + answers         | CONFIRMATION_PENDING / FROZEN / REJECTED       |
# | apply_confirmation   | contract + decisions       | FROZEN / REJECTED (blocking = 0)               |
```

---

## 14. MVP Boundaries — Explicit Deferrals

| Deferred | Why | Future trigger |
|---|---|---|
| Sub-contract / milestone decomposition | Single flat contract is the minimal unit; decomposition needs task-level verdict chain which is missing | When task-level verdict chain exists |
| Case retrieval from prior runs (layer 3) | No clause library exists yet; promotion is DEFER | After ADM promotion runs once |
| Auto-promotion of corrections to clauses | C7 requires external approval; ADM production is all-DEFER | After first real PROMOTE |
| k/k stability gate | Needs multiple independent runs; execution is literal false | After execution opens |
| Symbolic proof / mutation analysis | holdtrue L2/L6 require code backends; agent tasks have no SMT model | When a domain has formalizable predicates |
| Multi-round clarification | One round is the TiCoder-validated minimum; multi-round adds latency without proven ROI | Measured clarification insufficiency |
| Cross-domain meta-template transfer study | Meta-templates are domain-agnostic by construction; transfer is an empirical question | After ≥3 domain contracts exist |
| LLM_JUDGE predicates as anything but advisory | Research shows LLM judges ~70-90% agreement, not reliable enough to gate | When judge reliability per-task is calibrated (IRT thresholds) |
| Automatic tool schema resolution from CapabilitySpec refs | `input_contract`/`output_contract` are string refs; resolution needs artifact store integration | After artifact store read path exists |
| Predicate suggestion for STATE_DELTA baselines | Requires pre-run environment snapshot capability | After observation binding can snapshot state |

---

## 15. Test Plan

### 15.1 Mechanical extractor tests

- **M-1**: Tool schema with required typed parameter → FIELD_PRESENCE + TYPE predicate
- **M-2**: Enum parameter → ENUM predicate with correct allowed_values
- **M-3**: Min/max parameter → RANGE predicate
- **M-4**: Success response with ID field → TOOL_RESPONSE predicate + evidence binding
- **M-5**: Documented 4xx error → FailurePath
- **M-6**: NON_IDEMPOTENT_NON_QUERYABLE capability → FailurePath action=escalate
- **M-7**: Empty tool schema list → zero structural predicates (semantic must carry)
- **M-8**: Mechanical extractor is pure: same input → byte-identical output

### 15.2 Quality gate tests

- **Q-1**: Predicate without evidence binding → rejected
- **Q-2**: Tautological predicate ("result exists" when always exists) → rejected
- **Q-3**: LLM_JUDGE with blocking=True → rejected
- **Q-4**: Two contradictory RANGE predicates → lower-confidence dropped, warning
- **Q-5**: Deliverable field with no predicate → coverage_gap warning
- **Q-6**: Low-confidence semantic predicate → clarification_needed
- **Q-7**: Zero predicates survive Q1–Q3 (regardless of blocking status) →
  REJECTED with `"no_predicates_survived"`. A contract with only PENDING
  semantic predicates is a valid PENDING state, not this condition (§8.2);
  the blocking-count gate applies at freeze (§10 step 0b).

### 15.3 Semantic proposal tests (model-dependent, evaluated not asserted)

- **S-1**: Mandate "send email to selected supplier" → predicate binding to send_email
  tool response with evidence on message_id
- **S-2**: Mandate with explicit JSON format → deliverable_schema fields proposed
- **S-3**: Mandate with no tools → no predicates with TOOL_RESPONSE bindings
- **S-4**: Invalid JSON from model → one retry → still invalid → pipeline
  REJECTED with fatal warning `semantic_proposal_failed`, no contract produced
  (§7.2)
- **S-5**: Measure: on 10 held-out mandates, ≥80% of proposed predicates pass Q1–Q3
  (non-vacuity + evidence binding). This is a quality gate on the proposer itself.

### 15.4 Clarification tests

- **C-1**: "yes" answer → check_params resolved, confidence 1.0, kind stays SEMANTIC, pre_endorsed=True for the confirmation batch (never CONFIRMED/blocking at this stage)
- **C-2**: "no" answer → predicate removed
- **C-3**: Unanswered with on_unanswered="downgrade" → advisory
- **C-4**: More than 7 low-confidence predicates → only 7 questions, rest downgraded
- **C-5**: Empty answers list → all clarified predicates downgraded to advisory;
  pipeline then proceeds through the confirmation/freeze gates (§9.2, §10).

### 15.4b Confirmation tests

- **CF-1**: `approve` → predicate CONFIRMED, blocking finalized, record persisted; pre_endorsed predicates default to approve
- **CF-2**: `reject` → predicate removed from contract
- **CF-3**: No decision for a semantic predicate → downgraded to advisory; never blocking
- **CF-4**: `adjust` → replacement predicate re-runs Q1–Q5; original stays in history (append-only); replacement gets its own confirmation record
- **CF-5**: Mechanical-only contract (zero semantic predicates) → confirmation_status NOT_REQUIRED, freezes without a confirmation round
- **CF-6**: Semantic predicates with PENDING confirmation → freeze refused (no contract artifact)
- **CF-7**: Clarified "yes" predicate before confirmation → kind still SEMANTIC, not blocking (§9.2)
- **CF-8**: All semantic rejected and zero structural → REJECTED with `"no_blocking_predicates"` fatal warning

### 15.5 End-to-end tests

- **E-1**: Mandate + tool schema → frozen contract with ≥1 blocking predicate,
  content digest stable across re-runs (temperature=0)
- **E-2**: Contract maps to ExpectedOutcome records, one per blocking predicate
- **E-3**: DeterministicOutcomeEvaluator executes a TYPE predicate against a
  fixture ObservedOutcome → correct pass/fail
- **E-4**: Failed predicate → TypedPredicateCorrection + CorrectionAuthority halts
- **E-5**: Contract with all-advisory predicates and zero blocking → rejected
- **E-6**: Dana procurement task fixture (from prior conversation): mandate +
  email/supplier tool schemas → contract includes predicates for: email sent
  (TOOL_RESPONSE), supplier selected (ARTIFACT_CONTENT), phishing emails not
  acted on (CROSS_CONSISTENCY or scope), deliverable JSON exists
  (ARTIFACT_EXISTS). This is the showcase test.
- **E-7**: Bypass detection — any blocking predicate whose `source` starts with
  `"llm:"` or `"operator:"` MUST have a matching `PredicateConfirmation`
  record (by `predicate_id`) at freeze and at verdict mapping; otherwise
  rejected. STRUCTURAL (`mechanical:`) and PROMOTED predicates are exempt.
- **E-8**: Full three-phase path — mandate with a low-confidence predicate
  (clarification) + a high-confidence predicate (confirmation) → infer →
  apply_clarification → apply_confirmation → FROZEN → verdict against fixture
  → every blocking predicate has a matching PredicateConfirmation record.

### 15.6 Non-vacuity meta-test (inspired by holdtrue L5)

- For every frozen contract, run a **negative control**: inject a deliberately
  broken outcome state (e.g. missing artifact, wrong count, failed tool response)
  and verify that at least one blocking predicate FAILS. A contract where all
  predicates pass even against a broken state is vacuous and must be rejected.
- This is the most important test in the suite. It catches the "green report
  that verified nothing" anti-pattern (Verification Design Principles §9).

---

## 16. Open Questions

1. **Tool schema source**: In MVP, tool schemas are passed as explicit JSON Schema
   dicts. Should the inferencer also accept OpenAPI specs, or is JSON Schema the
   canonical form? (Leaning: JSON Schema only; adapters convert.)

2. **STATE_DELTA baselines**: The pre-run baseline snapshot requires observation
   infrastructure that may not exist yet. For MVP, STATE_DELTA predicates can be
   PROPOSED by the LLM but will return UNRESOLVED at verdict time if no baseline
   exists. Acceptable? (Leaning: yes — proposal is forward-compatible; verdict
   honesty requires UNRESOLVED rather than fake pass.)

3. **Predicate ID stability**: IDs are content-derived. If a user clarification
   changes a predicate's params, the ID changes. Is this desirable for tracking
   across correction epochs? (Leaning: yes — changed predicate is a new predicate;
   the old ID appears in the correction record.)

4. **Multiple tools with same name/version**: Tool response matching needs
   disambiguation when a tool is called multiple times. For MVP, match by
   `tool_name` + most recent call; future: call sequence numbers.

5. **Confidence calibration**: The 0.7 threshold is a guess. It should be tuned
   against held-out data: measure clarification rate vs. predicate failure rate
   at different thresholds. Tracked in §18 metric M-3.

6. **LLM judge model selection for LLM_JUDGE predicates**: Should be a different
   model family than the proposer (cross-family, per Verification Design
   Principles §7). For MVP, record the judge model ID in the predicate source.

---

## 17. Architecture-Theory Gate (RR-0029 §5)

Required before implementation-cast; to be filled by the implementation owner
and reviewed independently (builder_id != reviewed_by).

- **Claim class**: new core mechanism — contract inference (mandate → typed
  success predicates + evidence bindings + failure paths) feeding governed
  verdicts. Not a product wrapper of an existing mechanism.
- **Write channel**: extends `packages/contracts` (new predicate/confirmation
  types) and adds one dispatch layer to `DeterministicOutcomeEvaluator`
  (`os_core/execution.py`). No new authority surfaces; no model-writable path.
- **Consumption/control path**: inferred contract maps to `ExpectedOutcome`;
  verdict consumes evidence artifacts; corrections flow through
  `CorrectionAuthority` and halt (§13). Control path is C7-gated: confirmation
  (§9.5) precedes any blocking semantic predicate; freeze does not authorize
  execution.
- **Prior negative map**: LLM judges reach only 62–74% agreement with humans
  (Auto-Eval Judge) and ~90% with tool access (Agent-as-a-Judge) — insufficient
  to gate alone; naive self-review degrades performance (Verification Design
  Principles); nl2postcond catches only 1/8 real bugs; no cross-domain precedent
  for semantic contract inference outside code; τ-bench gold states are
  human-built. These motivate the deterministic quality gate, advisory-only
  LLM_JUDGE, human confirmation, and non-vacuity controls.
- **Cheap baseline**: the operator hand-writes contracts using the same
  `SuccessPredicate` types, executed by the same `DeterministicOutcomeEvaluator`.
  This isolates the inferencer's value (automated proposal) from the
  evaluator's value (deterministic checking). The inferencer must beat this
  baseline on operator time at equal verdict quality (§18 M-1); otherwise the
  mechanism is NOT_MET.
- **C6/C7/SD4**: confirmation and correction are external authority (C6/C7);
  the inferencer cannot self-confirm, self-promote, or modify its own gates.
  No SD4 surface: no runtime self-modification; library writes open only via
  the future promotion path under external approval.
- **Product/process boundary**: domain-agnostic contract machinery only.
  Domain semantics enter via predicates, not via Agent Core policy changes.

---

## 18. Metrics & Acceptance

All metrics measured on a labeled corpus of N≥10 held-out mandates with
human-drafted contracts as ground truth.

**M-1 — Cheap-baseline comparison (kill criterion)**: operator minutes per
frozen contract, inferencer vs. hand-written contracts + existing evaluator,
at equal verdict quality. If the inferencer does not reduce operator time, the
mechanism is NOT_MET — regardless of other metrics.

**M-2 — Intervention-cost decay (forward prediction, Phase 2)**: per-domain
mean confirmation minutes per contract must decrease monotonically as
same-type contracts accumulate (via clause library + retrieval). MVP has no
library, so no decay mechanism exists yet; this metric activates when §14
retrieval opens. Recorded now so the prediction is frozen before it can be
post-hoc fit.

**M-3 — Semantic precision/recall**: precision = fraction of blocking
predicates an operator retains as-is; recall = fraction of human-drafted
conditions covered by ≥1 predicate. MVP targets precision ≥ 0.6, recall ≥ 0.4
on the corpus; thresholds are calibration targets (tuned per §16, open
question 5), not success claims. Calibration note: also measure inter-annotator
agreement (two operators draft contracts for the same mandates). If
human-human agreement is itself only ~0.5–0.7, recall 0.4 against a single
human draft is near the ceiling; if human-human agreement exceeds 0.9, the
recall target must be raised.

**M-4 — Proposer form validity**: ≥80% of proposed predicates pass Q1–Q3
(§15.3 S-5).

**M-5 — Non-vacuity**: every frozen contract passes the negative control
(§15.6); any contract that fails it is rejected, not shipped.

**Acceptance gate (MVP exit)**: M-1 passed; M-3 at or above targets; M-5 holds
for all frozen contracts; E-7 bypass detection and E-8 full-path test green;
full test plan (§15) green. Verdict-quality and k/k stability comparisons
against un-gated execution are deferred to Phase 2 (execution is still
literal false).

---

## 19. References

| Reference | Contribution to this spec |
|---|---|
| holdtrue (JAIGP 2026, github.com/holdtrue-dev) | Contract-first with human approval at contract; sealed contexts; non-vacuity negative probe; evidence-graded verdicts; contract revision never silent |
| TiCoder (Fakhoury et al., FSE 2024 / IEEE TSE 2024) | Interactive ambiguity resolution: generate tests at ambiguity points, user Yes/No/Undef; correctness doubled, cognitive load dropped |
| Intent Formalization (Lahiri, MSR, arXiv:2603.17150) | Spectrum of spec expressiveness; soundness/completeness metrics; "no oracle for spec correctness other than the user" |
| nl2postcond / NL2Contract (UMass, arXiv:2510.12702) | LLM can generate meaningful postconditions from NL; caught 1/8 real Defects4J bugs; preconditions matter |
| τ-bench (Sierra, arXiv:2406.12045) | Deterministic DB-diff verdict; pass^k stability metric; conjunctive reward |
| Verification Design Principles (github.com/verificationdesign) | External signals > self-review; independence of generation/verification; executable verification is king; cross-family judges; delta-based assertions; CoT is not evidence |
| SmartSnap (arXiv:2512.22322) | Proactive in-situ evidence collection; 3C principles; evidence curated by agent during execution |
| Auto-Eval Judge (arXiv:2508.05508) | Criteria Generator auto-generates checklist from task description; but soft LLM-judge verdict, only 62-74% human agreement — validates the idea, motivates typed predicates |
| Agent-as-a-Judge (Meta, ICML 2025) | Judge with tool/execution agency reaches ~90% agreement vs ~70% for passive LLM-judge |
| agent-completion-gate (github.com/zhjai) | C7 structural gate pattern; explicitly does NOT infer criteria — the gap this spec fills |
| Threshold (github.com/misty-step) | Task spec with output contract + acceptance oracle; master agent derives via clarifying interview; launch contract; no self-promotion |
| Existing codebase | ContractModel (frozen, content-addressed), Mandate, ExpectedOutcome/ObservedOutcome, DeterministicOutcomeEvaluator, EvaluationContract, EvidenceManifest, CorrectionAuthority, PolicyKernel |
| RR-0029 (project constitution, §5) | Architecture-theory gate: claim class, write channel, consumption/control path, prior negative map, cheap baseline, C6/C7/SD4, boundaries (§17) |
