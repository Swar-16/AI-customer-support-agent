# Orchestration

## Overview

The `orchestration` package is the **workflow coordination layer of the AI customer-support system**.

It is responsible for coordinating the lifecycle of a customer-support request across:

```text
Customer Message
       │
       ▼
Deterministic Intent Routing
       │
       ├── matched → IntentResult
       │
       └── no match
              │
              ▼
       Intent Classifier
              │
              ▼
        IntentResult
              │
              ▼
        DecisionEngine
              │
              ├── ANSWER
              ├── RETRIEVE_INFORMATION
              ├── ASK_CLARIFICATION
              └── ESCALATE
                       │
                       ▼
             Response-producing path
                       │
                       ▼
              GuardrailEvaluator
                       │
             ┌─────────┼─────────┐
             ▼         ▼         ▼
            PASS     REFUSE    ESCALATE
             │         │         │
             ▼         ▼         ▼
          Approved   Safe      Human
          response  refusal    review
```

The package deliberately separates **workflow coordination** from the implementation of individual AI capabilities.

The orchestrator does not implement:

* intent classification logic;
* decision rules;
* database persistence;
* retries;
* retrieval algorithms;
* embedding/search implementation;
* generation prompts;
* business policy.

Instead, it coordinates the components that own those responsibilities and converts their results into a consistent `AIState`.

---

# Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── ai/
        └── orchestration/
            ├── state.py
            ├── direct_response.py
            ├── orchestrator.py
            └── README.md
```

## Files

| File                 | Responsibility                                                                                                                   |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `state.py`           | Canonical workflow state, lifecycle stages, evidence, errors, guardrail state, escalation state, and validated state transitions |
| `direct_response.py` | Deterministic, application-controlled responses for conversational and out-of-scope requests                                     |
| `orchestrator.py`    | Coordinates the complete AI-support workflow and translates component outcomes into state transitions                            |

---

# Architectural Responsibility

The package sits above individual AI subsystems.

```text
                    AI Orchestration
                           │
          ┌────────────────┼─────────────────┐
          │                │                 │
          ▼                ▼                 ▼
     Intent System    Decision System   Answer Service
          │                │                 │
          └────────────────┼─────────────────┘
                           │
                           ▼
                    Guardrail System
                           │
                           ▼
                      AIState
```

The orchestration layer therefore acts as the **composition boundary**.

It knows:

* which component runs next;
* what result is expected;
* which workflow branches are supported;
* how failures become `PipelineError`;
* how responses become workflow state;
* when human review is required;
* how guardrail outcomes affect the lifecycle.

It does not know the internal implementation details of those components.

---

# Core Components

The package contains three major components.

## `state.py`

Defines the canonical state model:

```text
PipelineStage
PipelineError
EvidenceSourceType
EscalationSource
GuardrailDisposition
RetrievedEvidence
AIState
```

The `AIState` object represents one complete AI-support execution and enforces cross-field lifecycle invariants.

---

## `direct_response.py`

Provides deterministic response handling for:

```text
CONVERSATIONAL
OUT_OF_SCOPE
```

It never calls an LLM.

Instead, it selects one of a finite set of application-owned response templates.

---

## `orchestrator.py`

Contains:

```text
OrchestrationObserver
NullOrchestrationObserver
AIOrchestratorConfig
AIOrchestrator
```

`AIOrchestrator` coordinates:

```text
intent
→ decision
→ direct response / retrieval / clarification / escalation
→ response generation
→ guardrails
→ terminal disposition
```

---

# High-Level Pipeline

The current V1 orchestration flow is:

```text
                     Customer Message
                            │
                            ▼
              DeterministicIntentRouter
                            │
                  ┌─────────┴─────────┐
                  │                   │
                match              no match
                  │                   │
                  │                   ▼
                  │             IntentClassifier
                  │                   │
                  └─────────┬─────────┘
                            ▼
                      IntentResult
                            │
                            ▼
                     DecisionEngine
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
          ▼                 ▼                 ▼
       ANSWER       RETRIEVE_INFORMATION  ASK_CLARIFICATION
          │                 │                 │
          ▼                 ▼                 ▼
  DirectResponseResolver  AnswerService  Allowlisted Response
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │
                            ▼
                  RESPONSE_GENERATED
                            │
                            ▼
                   GuardrailEvaluator
                            │
               ┌────────────┼────────────┐
               ▼            ▼            ▼
              PASS        REFUSE       ESCALATE
               │            │            │
               ▼            ▼            ▼
          Guardrails      Safe          Human
          Completed      Refusal       Review
```

The decision layer can also directly select:

```text
ESCALATE
```

in which case response generation is bypassed and the workflow enters human-review disposition.

---

# `state.py`

## Purpose

`state.py` defines the **canonical execution state for one AI-support workflow**.

The state records outputs from completed stages but does not execute business logic itself.

---

# `PipelineStage`

`PipelineStage` provides the canonical workflow-stage vocabulary.

```text
RECEIVED
CONTEXT_BUILT
INTENT_CLASSIFIED
DECISION_MADE
RETRIEVAL_COMPLETED
RESPONSE_GENERATED
GUARDRAILS_COMPLETED
ACTION_PROPOSED
ACTION_COMPLETED
ESCALATED
COMPLETED
FAILED
```

The values are:

```text
received
context_built
intent_classified
decision_made
retrieval_completed
response_generated
guardrails_completed
action_proposed
action_completed
escalated
completed
failed
```

These identifiers support:

* orchestration;
* tracing;
* structured logging;
* failure analysis;
* dashboards.

---

# `PipelineError`

`PipelineError` converts workflow failures into structured data instead of propagating raw exceptions through the pipeline.

Fields:

```text
code
message
stage
retryable
metadata
```

`code` is normalized to uppercase.

For example:

```text
generation_provider_timeout
```

becomes:

```text
GENERATION_PROVIDER_TIMEOUT
```

The model is immutable and rejects unexpected fields.

---

# Evidence Model

## `EvidenceSourceType`

The orchestration layer categorizes evidence into:

```text
KNOWLEDGE
OPERATIONAL
SYSTEM
```

### Knowledge

Versioned support material:

* policies;
* FAQs;
* procedures;
* guides;
* published reference information.

### Operational

Runtime business facts:

* order state;
* payment state;
* subscription state;
* account information.

### System

Trusted system-generated information that is neither customer-facing knowledge nor an operational business-system record.

---

# `RetrievedEvidence`

`RetrievedEvidence` is the provider-neutral evidence contract.

It intentionally hides retrieval implementation details such as:

```text
vector distance
lexical rank
RRF score
embedding model
pgvector
reranker implementation
```

Those details remain inside the retrieval/knowledge subsystem.

Fields:

```text
source_type
content
source_id
title
section
relevance_score
metadata
```

`source_id` is a string because different sources can have different identifier formats, including UUIDs, order IDs, transaction IDs, and external-system identifiers.

---

# `EscalationSource`

Records what caused human review to be required:

```text
DECISION
GUARDRAIL
SYSTEM
```

This identifies the origin of escalation without coupling orchestration state to the persistence implementation of an escalation system.

---

# `GuardrailDisposition`

Represents the sanitized orchestration-level guardrail result:

```text
PASS
REFUSE
ESCALATE
```

Values:

```text
pass
refuse
escalate
```

The orchestration layer mirrors this stable vocabulary rather than depending directly on guardrail implementation details.

---

# `AIState`

`AIState` is the central state object.

It contains:

```text
Workflow identity
Customer input
Pipeline stage
Intent result
Decision result
Retrieved evidence
Generated response
Customer notice
Guardrail state
Action references
Escalation state
Errors
Timestamps
Metadata
```

---

# Workflow Identity

Every state contains:

```text
ai_run_id
trace_id
conversation_id
trigger_message_id
```

These provide separate correlation identities for the AI execution, tracing, conversation, and triggering message.

---

# Customer Input

## `customer_message`

Required.

Constraints:

```text
1–20,000 characters
```

Whitespace is stripped and blank messages are rejected.

## `conversation_context`

Optional.

Maximum:

```text
50,000 characters
```

Whitespace-only context becomes `None`.

---

# Pipeline Outputs

`AIState` stores:

```text
intent_result
decision_result
retrieved_evidence
generated_response
```

The state therefore accumulates the outputs of earlier stages as the workflow progresses.

---

# Customer Notice vs Generated Response

This distinction is important.

```text
generated_response
    = candidate produced by the response-generation path

customer_notice
    = application-controlled message for a non-answer terminal outcome
```

An unapproved generated candidate must not become the customer-facing escalation message. The `customer_notice` field exists specifically to preserve this separation.

---

# Guardrail State

The state records:

```text
guardrail_disposition
guardrail_reason_code
guardrail_policy_id
```

Reason codes and policy IDs are normalized to lowercase.

The model prevents:

```text
reason code without disposition
policy ID without disposition
disposition without reason code
```

---

# Escalation State

The state records:

```text
escalation_source
escalation_reason_code
customer_notice
```

An `ESCALATED` state requires all three.

Guardrail-originated escalation additionally requires:

```text
guardrail_disposition = ESCALATE
guardrail_reason_code
```

---

# State Invariants

The model prevents impossible states.

Examples:

```text
INTENT_CLASSIFIED
    requires intent_result
```

```text
DECISION_MADE
    requires intent_result
    requires decision_result
```

```text
RESPONSE_GENERATED
    requires generated_response
```

```text
GUARDRAILS_COMPLETED
    requires PASS or REFUSE
```

```text
ESCALATED
    requires escalation_source
    requires escalation_reason_code
    requires customer_notice
```

```text
FAILED
    requires at least one error
```

```text
COMPLETED
    requires completed_at
```

---

# Immutable-Style State Transitions

`AIState` transitions use:

```python
model_copy(update={...})
```

rather than mutating the existing state.

Important transition methods include:

```text
with_intent()
with_decision()
with_retrieved_evidence()
with_generated_response()
with_guardrails_completed()
with_guardrail_escalation()
with_escalation()
with_error()
complete()
```

This makes state evolution explicit and allows every transition to enforce prerequisites.

---

# `direct_response.py`

## Purpose

`direct_response.py` handles requests that can be answered **without an LLM, retrieval, operational lookup, or business action**.

Supported intent categories:

```text
CONVERSATIONAL
OUT_OF_SCOPE
```

Supported conversational subtypes include:

```text
GREETING
CAPABILITIES
SUPPORT_PROMPT
THANKS
GOODBYE
OUT_OF_SCOPE
```

---

# Why Direct Responses Are Deterministic

Direct-response messages do not require generated content.

Examples:

```text
"Hello"
"Thanks"
"Goodbye"
"What can you help me with?"
```

Instead of invoking an LLM, the resolver chooses from application-owned templates.

This provides:

* predictable output;
* lower latency;
* lower provider usage;
* no generation variability;
* no customer-controlled text reflection;
* safe low-cardinality telemetry.

---

# `DirectResponseKind`

The stable response identifiers are:

```text
GREETING
CAPABILITIES
SUPPORT_PROMPT
THANKS
GOODBYE
OUT_OF_SCOPE
```

These values may be recorded in sanitized telemetry and therefore should remain stable.

---

# `DirectResponse`

`DirectResponse` is an immutable dataclass:

```python
@dataclass(frozen=True, slots=True)
class DirectResponse:
    kind: DirectResponseKind
    text: str
```

The response text:

* must be a string;
* cannot be blank;
* is normalized by collapsing whitespace.

---

# Application-Owned Templates

Templates are stored in an immutable mapping:

```text
_REPONSE_TEXT
```

and include:

```text
GREETING
CAPABILITIES
SUPPORT_PROMPT
THANKS
GOODBYE
OUT_OF_SCOPE
```

The returned response therefore never directly echoes arbitrary customer input.

---

# Conversational Pattern Detection

The resolver uses regex patterns for:

```text
capability questions
support requests
thanks
goodbyes
greetings
```

The message is first normalized using:

```text
casefold
→ punctuation removal
→ underscore normalization
→ whitespace normalization
```

Unicode letters and numbers are preserved.

---

# Response Precedence

When a message is classified as conversational, matching follows this order:

```text
1. capability question
2. goodbye
3. thanks
4. support request
5. greeting
6. generic support prompt
```

This ordering is intentional.

For example, a message containing both a greeting and a capability question should be treated as a capability request rather than merely a greeting.

---

# Security Property

The resolver never inserts customer-controlled content into its response templates.

The customer's message is used only as **untrusted classification input** for selecting an allowlisted response.

Therefore:

```text
customer input
      │
      ▼
pattern matching
      │
      ▼
allowlisted kind
      │
      ▼
application-owned text
```

rather than:

```text
customer input
      │
      ▼
string interpolation
      │
      ▼
response
```

---

# Direct Response Validation

`DirectResponseResolver` validates:

```text
customer_message
intent_result
decision_result
```

The decision must be:

```text
DecisionType.ANSWER
```

The intent must be one of:

```text
CONVERSATIONAL
OUT_OF_SCOPE
```

and the intent must not require clarification.

This prevents unsupported intents from accidentally entering the deterministic response path.

---

# Supported Policy Questions

A policy question should **not** be handled by `DirectResponseResolver`.

Even if it is simple, supported policy information belongs to the knowledge-retrieval workflow.

This keeps:

```text
conversational response
```

separate from:

```text
grounded support answer
```

---

# `orchestrator.py`

## Purpose

`AIOrchestrator` is the main coordinator.

Its job is to execute the currently supported pipeline and turn every expected outcome into an explicit terminal disposition:

```text
approved response
OR
human-review escalation
OR
typed FAILED state
```

Known operational failures are converted into `PipelineError`.

Unexpected programming/invariant defects are allowed to propagate instead of being disguised as recoverable AI failures.

---

# Dependencies

The orchestrator coordinates several subsystem boundaries:

```text
IntentClassifier
DecisionEngine
AnswerService
DeterministicIntentRouter
DirectResponseResolver
GuardrailEvaluator
OrchestrationObserver
```

It also consumes:

```text
IntentResult
DecisionResult
AIState
PipelineError
GuardrailOutcome
GroundingStatus
```

---

# Constructor Dependencies

`AIOrchestrator` requires:

```python
intent_classifier
decision_engine
```

Optional components include:

```python
answer_service
deterministic_intent_router
direct_response_resolver
guardrail_evaluator
observer
config
```

The orchestrator validates dependency types during initialization.

---

# Default Components

When omitted:

```text
deterministic_intent_router
    → DeterministicIntentRouter()

direct_response_resolver
    → DirectResponseResolver()

observer
    → NullOrchestrationObserver()

config
    → AIOrchestratorConfig()
```

`AnswerService` and `GuardrailEvaluator` remain optional.

---

# `AIOrchestratorConfig`

Configuration is represented by an immutable dataclass:

```python
@dataclass(frozen=True, slots=True)
class AIOrchestratorConfig:
    pipeline_version: str = "v1"
```

The pipeline version is normalized and cannot be empty.

It is stored in `AIState.metadata` and is intended to be persisted with `ai.runs`, allowing historical runs to be attributed to the orchestration version that produced them.

---

# `process_message()`

This is the public entry point.

```python
process_message(
    ai_run_id,
    trace_id,
    conversation_id,
    trigger_message_id,
    customer_message,
    conversation_context=None,
) -> AIState
```

The caller owns persistence and creates/persists the run identifiers before invoking the orchestrator.

The method performs:

```text
1. initialize AIState
2. classify intent
3. make deterministic decision
4. execute selected workflow
5. return terminal/intermediate state
```

---

# Initial State

The initial state contains:

```text
ai_run_id
trace_id
conversation_id
trigger_message_id
customer_message
conversation_context
metadata.pipeline_version
```

The initial stage is:

```text
RECEIVED
```

---

# Intent Classification

The orchestration layer first attempts deterministic intent routing:

```python
deterministic_route = self._deterministic_intent_router.route(...)
```

If a route is found:

```text
DeterministicIntentRouter
        │
        ▼
IntentResult
        │
        ▼
AIState.with_intent()
```

No probabilistic classifier call is required.

If deterministic routing does not produce a result, the orchestrator invokes:

```text
IntentClassifier
```

with:

```text
customer_message
conversation_context
```

---

# Intent Classification Failure Mapping

Known failures become structured pipeline errors.

| Exception                           | Error code                      | Retryable |
| ----------------------------------- | ------------------------------- | --------: |
| `InvalidIntentInputError`           | `INTENT_INVALID_INPUT`          |        No |
| `IntentClassificationTimeoutError`  | `INTENT_PROVIDER_TIMEOUT`       |       Yes |
| `InvalidIntentResponseError`        | `INTENT_INVALID_RESPONSE`       |       Yes |
| `IntentClassificationProviderError` | `INTENT_PROVIDER_FAILURE`       |       Yes |
| `IntentClassificationError`         | `INTENT_CLASSIFICATION_FAILURE` |        No |

---

# Decision Stage

Once an `IntentResult` exists:

```text
IntentResult
     │
     ▼
DecisionEngine.decide()
     │
     ▼
DecisionResult
```

The result is added to state using:

```python
state.with_decision(result)
```

A decision cannot be reached without an intent result.

---

# Decision Types

The orchestrator currently supports:

```text
ANSWER
RETRIEVE_INFORMATION
ASK_CLARIFICATION
ESCALATE
```

---

# `ANSWER`

An `ANSWER` decision uses:

```text
DirectResponseResolver
```

This is intended for deterministic, application-controlled responses such as:

```text
greeting
capability question
thanks
goodbye
out-of-scope response
```

It does not perform retrieval or provider generation.

The resulting response still goes through:

```text
RESPONSE_GENERATED
        ↓
guardrails
```

before becoming eligible for persistence.

---

# `ASK_CLARIFICATION`

Clarification responses are deterministic.

No additional LLM/provider call is made.

The orchestrator selects a safe response using:

```text
required_information
intent
allowlisted clarification templates
```

---

# Clarification Strategy

Specific requirement keys take precedence.

Examples:

```text
order_id
order_id_or_transaction_id
subscription_id
```

If only generic:

```text
clarification
```

is supplied, the orchestrator uses the classified intent to select an appropriate clarification template.

If the intent is:

```text
UNKNOWN
```

the orchestrator asks the customer to describe the support problem rather than pretending that a particular identifier is sufficient.

---

# `RETRIEVE_INFORMATION`

This path delegates retrieval and grounded generation to:

```text
AnswerService
```

The orchestrator does not know about:

```text
embeddings
vector search
lexical search
RRF
reranking
knowledge chunks
grounding internals
generation prompts
```

---

# AnswerService Boundary

The workflow is:

```text
DecisionResult
     │
     ▼
AnswerServiceRequest
     │
     ▼
AnswerService
     │
     ├── retrieval
     ├── evidence mapping
     └── grounded generation
     │
     ▼
evidence + generated answer + grounding status
```

From the orchestrator's perspective, AnswerService performs those operations atomically.

The orchestrator still records the lifecycle transitions.

---

# Retrieval State Transition

When the AnswerService succeeds:

```python
state.with_retrieved_evidence(result.evidence)
```

produces:

```text
RETRIEVAL_COMPLETED
```

Then:

```python
_complete_generation(...)
```

produces:

```text
RESPONSE_GENERATED
```

---

# Grounding Status

The orchestrator checks:

```text
GroundingStatus.INSUFFICIENT_EVIDENCE
GroundingStatus.NOT_REQUIRED
GroundingStatus.GROUNDED
```

---

## `GROUNDED`

Normal path:

```text
RESPONSE_GENERATED
        ↓
GUARDRAIL EVALUATION
```

---

## `INSUFFICIENT_EVIDENCE`

The response is not treated as a successful answer.

Instead:

```text
knowledge gap
     ↓
human review
```

The provider-generated candidate remains internal and an application-controlled escalation notice is attached.

This is a **normal workflow disposition**, not an infrastructure failure.

---

## `NOT_REQUIRED`

In a knowledge-retrieval workflow, this is treated as incompatible:

```text
GROUNDING_STATUS_INVALID
```

and results in a failed state.

---

# Retrieval/Generation Failure Mapping

Known failures are converted into typed `PipelineError` instances.

| Failure                                | Error code                    | Retryable |
| -------------------------------------- | ----------------------------- | --------: |
| Unsupported retrieval kind             | `RETRIEVAL_KIND_UNSUPPORTED`  |        No |
| Invalid/unsupported retrieval decision | `RETRIEVAL_DECISION_INVALID`  |        No |
| Generation timeout                     | `GENERATION_PROVIDER_TIMEOUT` |       Yes |
| Generation provider failure            | `GENERATION_PROVIDER_FAILURE` |       Yes |
| Invalid generation response            | `GENERATION_INVALID_RESPONSE` |       Yes |
| Generic generation failure             | `GENERATION_FAILURE`          |        No |
| AnswerService failure                  | `ANSWER_WORKFLOW_FAILURE`     |        No |

---

# Response Generation Lifecycle

`_complete_generation()` does not itself generate text.

Generation has already happened inside `AnswerService` or a deterministic resolver.

Its responsibility is to:

```text
record generated response
+
emit lifecycle events
```

using:

```python
state.with_generated_response(answer)
```

---

# Guardrail Evaluation

Guardrails are evaluated only after a response candidate exists.

The context contains:

```text
customer_message
decision
generated_response
retrieved_evidence
```

The evaluator can return:

```text
PASS
ESCALATE
REFUSE
```

---

# Guardrail `PASS`

A `PASS` result means the generated response is authorized.

The state becomes:

```text
GUARDRAILS_COMPLETED
guardrail_disposition = PASS
```

The generated response remains intact.

---

# Guardrail `REFUSE`

A rejected candidate is **replaced** with an application-controlled refusal.

The original generated candidate must not be returned or persisted.

The state becomes:

```text
generated_response = safe refusal
guardrail_disposition = REFUSE
stage = GUARDRAILS_COMPLETED
```

---

# Guardrail `ESCALATE`

A guardrail escalation means:

```text
generated candidate
       ↓
rejected
       ↓
candidate remains internal
       ↓
human review
```

Only sanitized guardrail identifiers are retained in orchestration state.

The customer receives an application-controlled escalation notice.

---

# Unknown Guardrail Outcomes

Unknown dispositions fail closed:

```text
GUARDRAIL_OUTCOME_UNSUPPORTED
```

The workflow becomes:

```text
FAILED
```

rather than assuming an unrecognized outcome is safe.

---

# Decision-Based Escalation

The decision engine can directly select:

```text
DecisionType.ESCALATE
```

The orchestrator then:

1. resolves an allowlisted customer notice;
2. records `EscalationSource.DECISION`;
3. records the decision reason code;
4. transitions the state to `ESCALATED`.

---

# Escalation Notice Safety

Escalation notices are selected from structured reason codes.

The orchestrator does not interpolate:

```text
customer text
model output
provider errors
internal reason summaries
```

into these messages.

Supported reason-specific notices include cases such as:

```text
customer requested human
severe dissatisfaction
security-sensitive request
operational lookup unavailable
human approval required
policy conflict
knowledge unavailable
```

The exact text is application-controlled.

---

# Knowledge-Gap Escalation

A particularly important path is:

```text
RETRIEVE_INFORMATION
        ↓
AnswerService
        ↓
INSUFFICIENT_EVIDENCE
        ↓
ESCALATED
```

This is different from a retrieval infrastructure failure.

The system is saying:

> The workflow completed, but there is not enough verified evidence to answer reliably.

Therefore:

```text
INSUFFICIENT_EVIDENCE
≠
RETRIEVAL_FAILURE
```

The former is a business/workflow disposition; the latter is an operational failure.

---

# Observability

The orchestrator exposes an observer contract:

```python
OrchestrationObserver
```

with:

```text
stage_started()
stage_completed()
stage_failed()
```

Implementations may connect these events to:

* structured logs;
* OpenTelemetry;
* Prometheus;
* persistence events;
* test assertions.

The orchestrator itself does not know how observability is implemented.

---

# `NullOrchestrationObserver`

A no-op implementation is provided:

```text
NullOrchestrationObserver
```

It avoids repeated:

```python
if observer is not None:
```

checks throughout the pipeline.

This is the default when no observer is supplied.

---

# Failure Handling Philosophy

The orchestration layer distinguishes between:

## Expected operational failures

Examples:

```text
provider timeout
provider failure
invalid provider response
unsupported retrieval source
answer-service failure
```

These become:

```text
PipelineError
      ↓
AIState(stage=FAILED)
```

---

## Programming/invariant defects

Examples:

```text
decision without intent
guardrail evaluation before response generation
missing required state
unexpected impossible state
```

These intentionally propagate as exceptions rather than being disguised as normal AI failures.

This distinction prevents genuine application bugs from being silently classified as recoverable provider failures.

---

# Terminal Outcomes

Every supported workflow ultimately produces one of three broad outcomes:

```text
                    Workflow
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
     Approved        Escalated     Failed
      response       human review  error
```

An approved response may be:

```text
direct deterministic response
OR
grounded generated response
OR
application-controlled clarification
OR
safe refusal
```

---

# Direct Response vs Grounded Response

These paths must remain conceptually distinct.

## Direct

```text
Customer
   ↓
Intent
   ↓
Decision = ANSWER
   ↓
DirectResponseResolver
   ↓
Application-owned response
```

No retrieval or LLM generation is required.

---

## Grounded

```text
Customer
   ↓
Intent
   ↓
Decision = RETRIEVE_INFORMATION
   ↓
AnswerService
   ├── Retrieval
   └── Grounded generation
   ↓
Guardrails
   ↓
Customer response
```

This separation prevents simple conversational interactions from unnecessarily invoking retrieval/generation infrastructure.

---

# Security Model

The orchestration package applies several important security boundaries.

## 1. No raw customer text in deterministic templates

Direct responses are selected from allowlisted application-owned templates.

## 2. Rejected generated responses are not persisted

Guardrail refusals replace the generated candidate before the response can be treated as approved.

## 3. Guardrail escalation preserves the rejected candidate internally

Only sanitized identifiers and a safe customer notice are exposed through the escalation state.

## 4. Customer notices are application-controlled

Escalation notices do not directly contain provider/model output.

## 5. Unknown guardrail states fail closed

Unrecognized outcomes do not default to approval.

---

# Dependency Boundaries

The orchestration package intentionally delegates responsibilities.

```text
┌─────────────────────────────────────────────┐
│              ORCHESTRATION                 │
│                                             │
│ workflow coordination + state transitions  │
└─────────────────────────────────────────────┘
          │          │          │
          ▼          ▼          ▼
       Intent     Decision    AnswerService
       System      System       │
                                ├── Retrieval
                                └── Generation

          │
          ▼
      Guardrails
```

The orchestrator should not duplicate the logic owned by these subsystems.

---

# Responsibility Matrix

| Responsibility                  | Owner                                  |
| ------------------------------- | -------------------------------------- |
| Intent taxonomy                 | Intent package                         |
| Intent classification           | `IntentClassifier`                     |
| Deterministic intent shortcuts  | `DeterministicIntentRouter`            |
| Decision rules                  | `DecisionEngine`                       |
| Direct conversational responses | `DirectResponseResolver`               |
| Retrieval                       | `AnswerService` / retrieval subsystem  |
| Grounded generation             | `AnswerService` / generation subsystem |
| Guardrail policy                | `GuardrailEvaluator`                   |
| Workflow sequencing             | `AIOrchestrator`                       |
| Workflow state                  | `AIState`                              |
| Structured workflow failures    | `PipelineError`                        |
| Persistence                     | Application layer                      |
| Escalation record creation      | Application layer                      |
| Observability implementation    | Observer implementation                |

---

# Pipeline State Flow

A typical grounded request follows:

```text
RECEIVED
    │
    ▼
INTENT_CLASSIFIED
    │
    ▼
DECISION_MADE
    │
    ▼
RETRIEVAL_COMPLETED
    │
    ▼
RESPONSE_GENERATED
    │
    ▼
GUARDRAILS_COMPLETED
    │
    ▼
COMPLETED
```

A knowledge-gap path:

```text
RECEIVED
    ↓
INTENT_CLASSIFIED
    ↓
DECISION_MADE
    ↓
RETRIEVAL_COMPLETED
    ↓
RESPONSE_GENERATED
    ↓
INSUFFICIENT_EVIDENCE
    ↓
ESCALATED
```

A guardrail escalation:

```text
RESPONSE_GENERATED
    ↓
GUARDRAIL
    ↓
ESCALATE
    ↓
ESCALATED
```

A provider failure:

```text
ANY STAGE
    ↓
known operational exception
    ↓
PipelineError
    ↓
FAILED
```

---

# Why State and Orchestrator Are Separate

`AIState` answers:

> What has happened?

`AIOrchestrator` answers:

> What should the workflow execute next?

For example:

```text
AIState
    stage = DECISION_MADE
    decision = RETRIEVE_INFORMATION
```

The state records the decision.

The orchestrator interprets that state and invokes `AnswerService`.

This separation keeps the data contract independent from workflow execution.

---

# Why Direct Response Is Separate

`DirectResponseResolver` answers:

> Given an `ANSWER` decision for a supported deterministic intent, which safe application-owned response should be returned?

This logic does not belong inside `AIOrchestrator` because it would otherwise cause the orchestrator to accumulate:

* regex patterns;
* conversational templates;
* intent-specific response rules.

Keeping it separate makes the orchestrator primarily a coordinator rather than a large collection of response rules.

---

# Testing Strategy

Tests for this package should cover three levels.

## State tests

Verify:

* stage invariants;
* required fields;
* normalization;
* invalid transitions;
* escalation requirements;
* guardrail requirements;
* failure requirements;
* completion requirements.

---

## Direct-response tests

Test:

```text
hello
hi
what can you help with
thanks
goodbye
I need help
out-of-scope intent
unsupported intent
clarification-required intent
blank input
punctuation-heavy input
```

Also verify that customer text is never reflected into the returned template.

---

## Orchestrator tests

Test:

```text
deterministic intent route
LLM intent fallback
intent provider timeout
intent provider failure
decision success
decision failure
direct answer
retrieval answer
clarification
decision escalation
knowledge-gap escalation
guardrail pass
guardrail refusal
guardrail escalation
unsupported guardrail outcome
retrieval failure
generation timeout
generation provider failure
invalid generation response
answer-service failure
```

---

# Important Test Invariants

The following should never occur:

```text
DECISION_MADE without intent_result
```

```text
RETRIEVAL_COMPLETED without decision_result
```

```text
RESPONSE_GENERATED without generated_response
```

```text
GUARDRAILS_COMPLETED with ESCALATE disposition
```

```text
ESCALATED without customer_notice
```

```text
FAILED without PipelineError
```

```text
COMPLETED without completed_at
```

---

# Example: Simple Greeting

Input:

```text
"Hello"
```

Possible flow:

```text
DeterministicIntentRouter
        ↓
IntentType.CONVERSATIONAL
        ↓
DecisionEngine
        ↓
DecisionType.ANSWER
        ↓
DirectResponseResolver
        ↓
DirectResponseKind.GREETING
        ↓
"Hello! How can I help you today?"
        ↓
Guardrails
        ↓
COMPLETED
```

No retrieval or LLM generation is necessary.

---

# Example: Policy Question

Input:

```text
"What is your refund policy?"
```

Conceptually:

```text
IntentClassifier
        ↓
REFUND_REQUEST / GENERAL_QUESTION
        ↓
DecisionEngine
        ↓
RETRIEVE_INFORMATION
        ↓
AnswerService
        ├── retrieve support knowledge
        └── grounded generation
        ↓
Guardrails
        ↓
Approved response
```

The direct-response resolver should not answer the policy question because policy answers require the knowledge-retrieval path.

---

# Example: Ambiguous Request

Input:

```text
"I need help."
```

Potential flow:

```text
Intent
    ↓
Decision = ASK_CLARIFICATION
    ↓
allowlisted clarification
    ↓
RESPONSE_GENERATED
    ↓
Guardrails
```

The response does not ask the LLM to invent a clarification question.

Instead, the orchestrator chooses a bounded application-controlled clarification message.

---

# Example: Knowledge Gap

```text
Customer
   ↓
Intent
   ↓
RETRIEVE_INFORMATION
   ↓
AnswerService
   ↓
INSUFFICIENT_EVIDENCE
   ↓
ESCALATED
```

The workflow is not marked as `FAILED`.

The system successfully determined that it lacks sufficient verified evidence and therefore requests human review.

---

# Example: Guardrail Refusal

```text
Generated Candidate
        ↓
GuardrailEvaluator
        ↓
REFUSE
        ↓
Original candidate discarded
        ↓
Application-controlled refusal
        ↓
GUARDRAILS_COMPLETED
```

The original candidate must not be returned or persisted.

---

# Example: Guardrail Escalation

```text
Generated Candidate
        ↓
GuardrailEvaluator
        ↓
ESCALATE
        ↓
Candidate remains internal
        ↓
Safe customer notice
        ↓
ESCALATED
```

Only sanitized reason/policy identifiers are retained as guardrail state.

---

# Design Principles

## 1. Orchestration is coordination, not implementation

The orchestrator connects specialized components rather than reimplementing them.

---

## 2. Deterministic paths are preferred where possible

Conversational responses and clarification messages use application-controlled templates instead of unnecessary model calls.

---

## 3. AI output must cross a validated boundary

Intent and decision outputs become structured models before orchestration uses them.

---

## 4. Retrieval internals remain encapsulated

The orchestrator receives evidence and grounding status rather than vector-search internals.

---

## 5. Guardrails are part of the response lifecycle

A generated response is not automatically an approved response.

The lifecycle is:

```text
generated
    ↓
guardrails
    ↓
approved / refused / escalated
```

---

## 6. Expected failures become typed state

Provider and workflow failures become `PipelineError` rather than arbitrary exceptions crossing the pipeline.

---

## 7. Programming defects should remain visible

Unexpected invariant violations are not silently converted into normal AI failures.

---

## 8. Customer-facing text should be controlled

Where the application already knows the appropriate response, it uses allowlisted templates rather than unnecessary generation.

---

## 9. State transitions are explicit

Workflow progression occurs through named transition methods instead of arbitrary state mutation.

---

# Package Interaction Diagram

```text
                         Customer Message
                                │
                                ▼
                  ┌────────────────────────┐
                  │ Deterministic Router   │
                  └────────────┬───────────┘
                               │
                    no route   │   route
                       │       │
                       ▼       │
              ┌──────────────┐ │
              │IntentClassifier│ │
              └──────┬───────┘ │
                     │          │
                     └────┬─────┘
                          ▼
                    ┌───────────┐
                    │ IntentResult
                    └─────┬─────┘
                          ▼
                    ┌─────────────┐
                    │DecisionEngine│
                    └──────┬──────┘
                           ▼
                   ┌───────────────┐
                   │ DecisionResult│
                   └───────┬───────┘
                           │
       ┌───────────────────┼──────────────────┐
       ▼                   ▼                  ▼
     ANSWER          RETRIEVE_INFO       CLARIFICATION
       │                   │                  │
       ▼                   ▼                  ▼
 DirectResponse       AnswerService      Safe Template
       │                   │                  │
       │              ┌────┴─────┐            │
       │              ▼          ▼            │
       │          Evidence    Generation      │
       │              │          │            │
       └──────────────┴──────────┴────────────┘
                           │
                           ▼
                  RESPONSE_GENERATED
                           │
                           ▼
                  GuardrailEvaluator
                     │     │     │
                    PASS REFUSE ESCALATE
                     │     │     │
                     ▼     ▼     ▼
                  Complete Safe   Human
                  Response Refusal Review
```

---

# Summary

The `packages/ai/orchestration` package is the **control plane for one AI customer-support execution**.

Its responsibilities are divided cleanly:

```text
state.py
    ↓
"What is the current workflow state?"

direct_response.py
    ↓
"What safe deterministic response should be returned?"

orchestrator.py
    ↓
"Which component should run, and how should its result
be represented in the workflow?"
```

The resulting architecture is:

```text
                   AIOrchestrator
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
   Intent System    Decision System   AnswerService
        │                │                │
        └────────────────┼────────────────┘
                         │
                         ▼
                  Response Candidate
                         │
                         ▼
                 GuardrailEvaluator
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
             PASS      REFUSE    ESCALATE
              │          │          │
              └──────────┼──────────┘
                         ▼
                       AIState
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
          COMPLETED              ESCALATED
                                  or
                                FAILED
```

The key architectural property is that **AI capabilities remain modular while orchestration owns lifecycle coordination**.

`AIState` provides the validated state contract, `DirectResponseResolver` provides safe deterministic response selection, and `AIOrchestrator` composes the specialized subsystems into one explicit, observable, failure-aware workflow.
