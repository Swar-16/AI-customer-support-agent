# Answer Service

## Overview

`answer_service.py` implements the **application-layer answer orchestration service** responsible for producing grounded customer-support answers from enterprise knowledge.

It acts as the integration boundary between:

* the AI decision and intent layers;
* the application-level knowledge retrieval services;
* the knowledge retrieval pipeline;
* evidence mapping;
* grounded response generation.

The service intentionally keeps the generic AI layer independent from the concrete knowledge-retrieval implementation.

```text
Customer Request
       │
       ▼
AnswerServiceRequest
       │
       ▼
Validate Decision
       │
       ▼
Knowledge Retrieval Context
       │
       ▼
Prepare Retrieval Query
       │
       ▼
Build Grounding Context
       │
       ▼
Map Knowledge Evidence
       │
       ▼
Generate Grounded Response
       │
       ▼
AnswerServiceResult
```

The source identifies this class explicitly as an **application-layer integration service for grounded customer answers**.

---

# File Location

```text
AI-customer-support-agent/
└── packages/
    └── application/
        └── ai/
            └── answer_service.py
```

The file belongs to the application layer rather than directly to either the generic AI package or the knowledge package.

---

# Responsibility

The primary responsibility of `AnswerService` is to execute a **knowledge-backed answer workflow** after the request has already been:

1. understood by the intent layer; and
2. routed by the decision layer.

The service does **not** perform intent classification or make the original workflow decision.

The request contract explicitly describes the input as already-understood and already-routed customer input.

Therefore:

```text
Intent Classification
        │
        ▼
Decision Engine
        │
        ▼
AnswerService
        │
        ├── Retrieval
        └── Generation
```

---

# Architectural Position

`AnswerService` sits between the AI domain and knowledge domain.

```text
┌───────────────────────────────┐
│          AI Package           │
│                               │
│ IntentResult                  │
│ DecisionResult                │
│ RetrievedEvidence             │
│ GroundedGenerationResult      │
└───────────────┬───────────────┘
                │
                ▼
       ┌─────────────────┐
       │  AnswerService  │
       └────────┬────────┘
                │
        ┌───────┴──────────┐
        ▼                  ▼
┌────────────────┐  ┌───────────────────┐
│ Knowledge      │  │ Generation        │
│ Retrieval      │  │                  │
│ Pipeline       │  │ GroundedResponse │
└────────────────┘  │ Generator         │
                    └───────────────────┘
```

This separation is deliberate.

The AI package does not need to understand:

* retrieval-query preparation;
* grounding-context construction;
* chunks;
* vector retrieval;
* lexical retrieval;
* reciprocal-rank fusion;
* embedding providers;
* knowledge-document versions.

Likewise, the knowledge package does not depend on AI workflow state, decision objects, or LLM providers.

---

# Imports and Dependencies

The service integrates several domain contracts.

## Decision layer

```python
from packages.ai.decision.policies import RetrievalKind
from packages.ai.decision.schemas import DecisionResult, DecisionType
```

These determine whether the request is eligible for this service and what retrieval source should be used.

---

## Generation layer

```python
from packages.ai.generation.generator import GroundedResponseGenerator
from packages.ai.generation.models import (
    GroundedGenerationRequest,
    GroundedGenerationResult,
)
```

These provide the final grounded response-generation interface.

---

## Intent layer

```python
from packages.ai.intent.schemas import IntentResult
```

The intent result is passed into the retrieval context and subsequently into generation.

---

## Orchestration state

```python
from packages.ai.orchestration.state import RetrievedEvidence
```

The service returns evidence using the neutral `RetrievedEvidence` contract rather than exposing knowledge-retrieval-specific objects.

---

## Application knowledge services

```python
from packages.application.knowledge.evidence_mapper import KnowledgeEvidenceMapper
from packages.application.knowledge.retrieval_context_service import (
    KnowledgeRetrievalContextService,
)
```

These services adapt application-level customer-support information to the underlying knowledge retrieval system.

---

## Knowledge retrieval

```python
from packages.knowledge.retrieval.application.build_grounding_context import (
    BuildGroundingContext,
)
from packages.knowledge.retrieval.models import RetrievalFilters
from packages.knowledge.retrieval.query.service import (
    RetrievalQueryPreparationService,
)
```

These components execute the retrieval-specific portion of the pipeline.

---

# Error Model

The file defines a dedicated application-layer exception hierarchy.

```text
AnswerServiceError
├── InvalidAnswerRequestError
├── UnsupportedAnswerDecisionError
├── UnsupportedRetrievalKindError
└── InvalidRetrievalDecisionError
```

The base exception is:

```python
class AnswerServiceError(RuntimeError):
    ...
```

It represents failures belonging specifically to the answer-service application boundary.

Importantly, retrieval-domain and generation-domain exceptions are **not collapsed** into `AnswerServiceError`.

This allows higher-level orchestration to distinguish between:

```text
retrieval failure
generation failure
unsupported routing
malformed application input
```

---

# `InvalidAnswerRequestError`

```python
class InvalidAnswerRequestError(AnswerServiceError):
    ...
```

This error is raised when the caller supplies something that is not a valid `AnswerServiceRequest`.

The public `answer()` method checks this explicitly before processing the request.

---

# `UnsupportedAnswerDecisionError`

```python
class UnsupportedAnswerDecisionError(AnswerServiceError):
    ...
```

This indicates that the service was asked to execute a decision outside its responsibility.

For V1, the service requires:

```text
DecisionType.RETRIEVE_INFORMATION
```

Anything else is rejected.

This prevents unrelated workflow decisions from being silently converted into knowledge retrieval.

---

# `UnsupportedRetrievalKindError`

```python
class UnsupportedRetrievalKindError(AnswerServiceError):
    ...
```

V1 supports only:

```text
RetrievalKind.KNOWLEDGE
```

Operational retrieval is explicitly not implemented by this service.

```text
RETRIEVE_INFORMATION
        │
        ▼
retrieval_kind
        │
        ├── KNOWLEDGE ───────► supported
        │
        └── OPERATIONAL ─────► rejected
```

Operational retrieval is expected to be handled later by operational tools/services producing the same neutral `RetrievedEvidence` contract.

---

# `InvalidRetrievalDecisionError`

```python
class InvalidRetrievalDecisionError(AnswerServiceError):
    ...
```

This represents a malformed retrieval decision.

The current `DecisionResult` stores `retrieval_kind` inside metadata rather than as a dedicated typed field.

`AnswerService` therefore validates that metadata explicitly rather than blindly trusting it.

---

# `AnswerServiceRequest`

## Purpose

`AnswerServiceRequest` is the immutable application-level input contract for one grounded-answer operation.

```python
@dataclass(frozen=True, slots=True)
class AnswerServiceRequest:
    customer_message: str
    intent_result: IntentResult
    decision_result: DecisionResult
    trusted_filters: RetrievalFilters | None = None
    conversation_context: str | None = None
```

The use of:

```python
frozen=True
slots=True
```

makes the request immutable and memory-efficient.

---

# Request Fields

## `customer_message`

The original customer-authored message.

It is considered **untrusted input**.

The service validates that it is a string and rejects empty messages.

Whitespace is removed before the value is stored:

```python
normalized_message = self.customer_message.strip()
```

An empty normalized message raises:

```text
ValueError("customer_message cannot be empty")
```

---

## `intent_result`

```python
intent_result: IntentResult
```

This contains the already-computed semantic intent.

The service does not calculate the intent itself.

It validates the object type:

```python
if not isinstance(self.intent_result, IntentResult):
    raise TypeError(...)
```

---

## `decision_result`

```python
decision_result: DecisionResult
```

This contains the routing decision produced by the decision engine.

It is also type-validated.

```python
if not isinstance(self.decision_result, DecisionResult):
    raise TypeError(...)
```

---

## `trusted_filters`

```python
trusted_filters: RetrievalFilters | None = None
```

These are application-controlled retrieval constraints.

Unlike `customer_message`, these are explicitly treated as trusted application input.

If supplied, the value must be a `RetrievalFilters` instance.

---

## `conversation_context`

```python
conversation_context: str | None = None
```

This represents optional, bounded prior conversation context selected by the caller.

If present, it must be a string.

Whitespace is stripped, and an empty resulting value becomes `None`.

---

# Request Trust Model

The request explicitly distinguishes trusted and untrusted information.

```text
┌──────────────────────────────┐
│ AnswerServiceRequest         │
├──────────────────────────────┤
│ customer_message             │
│ → untrusted customer text    │
│                              │
│ intent_result                │
│ → validated semantic output  │
│                              │
│ decision_result              │
│ → deterministic routing      │
│                              │
│ trusted_filters              │
│ → application-controlled     │
│                              │
│ conversation_context         │
│ → bounded caller-selected    │
└──────────────────────────────┘
```

This distinction is particularly important for retrieval because customer-authored text must not automatically be treated as trusted retrieval constraints.

---

# `AnswerServiceResult`

The successful result is:

```python
@dataclass(frozen=True, slots=True)
class AnswerServiceResult:
    evidence: tuple[RetrievedEvidence, ...]
    generation: GroundedGenerationResult
```

Evidence and generation are deliberately returned separately.

---

# Why Evidence and Generation Are Separate

The service does not mutate the global AI workflow state.

Instead, it returns:

```text
evidence
generation
```

and allows the orchestrator to apply the appropriate lifecycle transitions.

For example:

```python
state.with_retrieved_evidence(result.evidence)
state.with_generated_response(result.generation.answer)
```

This keeps `AnswerService` unaware of `AIState` lifecycle rules.

---

# Result Validation

`AnswerServiceResult` validates that:

```text
evidence
    → tuple

every evidence item
    → RetrievedEvidence

generation
    → GroundedGenerationResult
```

This prevents lower-level retrieval objects or arbitrary response objects from leaking through the application boundary.

---

# `AnswerService`

## Constructor

The service receives five dependencies:

```python
AnswerService(
    retrieval_context_service=...,
    query_preparation_service=...,
    build_grounding_context=...,
    evidence_mapper=...,
    response_generator=...,
)
```

These dependencies represent the complete V1 knowledge-answer pipeline.

---

# Constructor Dependencies

## `KnowledgeRetrievalContextService`

Creates the retrieval context from:

* customer message;
* intent result;
* trusted retrieval filters;
* conversation context.

---

## `RetrievalQueryPreparationService`

Transforms the retrieval context into a prepared retrieval query.

---

## `BuildGroundingContext`

Executes/builds the retrieval-backed grounding context.

---

## `KnowledgeEvidenceMapper`

Converts knowledge-specific grounding output into neutral:

```python
RetrievedEvidence
```

objects.

---

## `GroundedResponseGenerator`

Consumes the customer message, intent, evidence, and conversation context to generate the grounded response.

---

# Dependency Validation

The constructor validates every dependency with `isinstance`.

For example:

```python
if not isinstance(
    retrieval_context_service,
    KnowledgeRetrievalContextService,
):
    raise TypeError(...)
```

The same pattern is used for all five dependencies.

This ensures the service is initialized with the expected application contracts.

---

# `answer()` — Public API

The primary public method is:

```python
def answer(
    *,
    request: AnswerServiceRequest,
) -> AnswerServiceResult:
```

Its job is to:

1. validate the request;
2. resolve the retrieval kind;
3. reject unsupported retrieval kinds;
4. execute the appropriate retrieval path;
5. return evidence plus generated output.

---

# V1 Routing Contract

The current implementation supports exactly:

```text
DecisionType.RETRIEVE_INFORMATION
+
RetrievalKind.KNOWLEDGE
```

Therefore:

```text
┌───────────────────────────────┐
│ DecisionResult                │
└───────────────┬───────────────┘
                │
                ▼
       _resolve_retrieval_kind()
                │
                ▼
        RetrievalKind.KNOWLEDGE
                │
                ▼
       _answer_from_knowledge()
```

Operational retrieval is explicitly rejected.

Other retrieval kinds are also rejected defensively.

---

# Why Unsupported Decisions Are Rejected

The service intentionally does **not** silently transform an unsupported decision into knowledge retrieval.

For example:

```text
Decision = ANSWER
```

must not become:

```text
ANSWER
  ↓
retrieve knowledge anyway
```

Similarly:

```text
Decision = RETRIEVE_INFORMATION
RetrievalKind = OPERATIONAL
```

must not become:

```text
OPERATIONAL
  ↓
KNOWLEDGE
```

This prevents routing errors from querying the wrong source of truth.

---

# Knowledge Answer Flow

The complete V1 knowledge path is:

```text
AnswerServiceRequest
        │
        ▼
Validate Routing
        │
        ▼
KnowledgeRetrievalContextService
        │
        ▼
RetrievalQueryContext
        │
        ▼
RetrievalQueryPreparationService
        │
        ▼
PreparedRetrievalQuery
        │
        ▼
BuildGroundingContext
        │
        ▼
GroundingContext
        │
        ▼
KnowledgeEvidenceMapper
        │
        ▼
tuple[RetrievedEvidence, ...]
        │
        ▼
GroundedGenerationRequest
        │
        ▼
GroundedResponseGenerator
        │
        ▼
GroundedGenerationResult
        │
        ▼
AnswerServiceResult
```

This sequence is explicitly documented in the service itself.

---

# `_answer_from_knowledge()`

The private knowledge-path method performs the actual integration.

```python
def _answer_from_knowledge(
    *,
    request: AnswerServiceRequest,
) -> AnswerServiceResult:
```

The first step creates retrieval context:

```python
retrieval_context = self._retrieval_context_service.create(
    customer_message=request.customer_message,
    intent_result=request.intent_result,
    trusted_filters=request.trusted_filters,
    conversation_context=request.conversation_context,
)
```

---

# Query Preparation

The retrieval context is then converted into a prepared query:

```python
prepared_query = self._query_preparation_service.prepare(
    context=retrieval_context
)
```

This keeps retrieval-query construction outside `AnswerService`.

The answer service only coordinates the operation.

---

# Grounding Context Construction

The prepared query is passed to:

```python
self._build_grounding_context.build(
    prepared_query=prepared_query
)
```

The resulting `GroundingContext` represents the knowledge evidence selected for response generation.

---

# Evidence Mapping

The grounding context is converted into neutral AI evidence:

```python
evidence = self._evidence_mapper.map(
    context=grounding_context
)
```

This is an important architectural boundary.

Knowledge-specific retrieval structures remain inside the knowledge/application layers.

The AI-facing result is:

```python
tuple[RetrievedEvidence, ...]
```

---

# Grounded Generation Request

The service constructs:

```python
GroundedGenerationRequest(
    customer_message=request.customer_message,
    intent=request.intent_result,
    evidence=evidence,
    conversation_context=request.conversation_context,
)
```

Therefore the generator receives:

```text
Customer Message
+
Intent
+
Retrieved Evidence
+
Conversation Context
```

---

# Response Generation

The generator is called through its domain interface:

```python
generation = self._response_generator.generate(
    request=generation_request
)
```

The service does not directly interact with an LLM provider.

Instead:

```text
AnswerService
      │
      ▼
GroundedResponseGenerator
      │
      ▼
Generation Provider
```

This keeps provider-specific concerns outside the application integration service.

---

# Empty Retrieval Behavior

An important behavior is that **empty retrieval is not treated as an exception**.

The source explicitly states that `BuildGroundingContext` considers empty retrieval a valid semantic outcome.

Therefore:

```text
No evidence found
      │
      ▼
evidence = ()
      │
      ▼
Generator
      │
      ▼
Potential INSUFFICIENT_EVIDENCE response
```

This is designed to prevent hallucination rather than treating lack of evidence as an infrastructure failure.

---

# Retrieval Failure vs Empty Retrieval

These two conditions have different meanings.

## Empty retrieval

```text
No matching knowledge
```

This is a valid semantic outcome.

## Retrieval failure

```text
Retrieval infrastructure/domain failure
```

This remains a retrieval-domain exception and is intentionally allowed to propagate.

The service does not collapse retrieval failures into `AnswerServiceError`.

---

# `_resolve_retrieval_kind()`

This static method validates routing metadata.

```python
@staticmethod
def _resolve_retrieval_kind(
    decision: DecisionResult,
) -> RetrievalKind:
```

Its purpose is to isolate the current representation of retrieval routing.

At present:

```text
DecisionResult
     │
     ▼
metadata["retrieval_kind"]
```

is used instead of a first-class typed field.

---

# Retrieval Kind Validation

The method performs several checks.

### 1. Decision type

The decision must be:

```text
RETRIEVE_INFORMATION
```

Otherwise:

```python
UnsupportedAnswerDecisionError
```

is raised.

---

### 2. Metadata existence and type

The service retrieves:

```python
raw_kind = decision.metadata.get("retrieval_kind")
```

It must be a string.

Otherwise:

```text
InvalidRetrievalDecisionError
```

is raised.

---

### 3. Non-empty value

The string is stripped.

An empty value is rejected:

```text
InvalidRetrievalDecisionError
```

---

### 4. Enum conversion

Finally:

```python
RetrievalKind(normalized_kind)
```

converts the metadata string into the typed enum.

Unknown values become:

```text
InvalidRetrievalDecisionError
```

with the original `ValueError` preserved as the cause.

---

# Migration Boundary

`_resolve_retrieval_kind()` deliberately acts as a migration boundary.

The current decision schema stores:

```text
metadata["retrieval_kind"]
```

A future schema may instead define:

```text
decision.retrieval_kind
```

When that happens, the conversion logic can be changed in one place.

The rest of `AnswerService` can remain unchanged.

---

# Separation of Responsibilities

The service intentionally avoids implementing the internals of retrieval and generation.

```text
AnswerService
    │
    ├── coordinates
    │
    ├── validates routing
    │
    ├── passes data between services
    │
    └── assembles final result
```

It does **not**:

```text
perform vector search
perform lexical search
calculate RRF
generate embeddings
construct retrieval algorithms
parse knowledge documents
call LLM SDKs directly
manage AIState lifecycle
```

This keeps it an integration/orchestration service rather than a domain implementation.

---

# Layer Boundaries

The architecture can be summarized as:

```text
                    Application Layer
                          │
                   AnswerService
                          │
          ┌───────────────┼────────────────┐
          │               │                │
          ▼               ▼                ▼
      AI Contracts   Knowledge Services   Generator
          │               │                │
          ▼               ▼                ▼
      Intent/Decision  Retrieval        LLM Provider
```

The service therefore serves as an **anti-corruption/integration boundary** between the generic AI domain and concrete knowledge implementation.

---

# Data Flow

A complete data transformation looks like:

```text
customer_message
       │
       ├───────────────┐
       │               │
       ▼               ▼
 intent_result    conversation_context
       │               │
       └───────┬───────┘
               │
               ▼
     KnowledgeRetrievalContext
               │
               ▼
     PreparedRetrievalQuery
               │
               ▼
        GroundingContext
               │
               ▼
      RetrievedEvidence[]
               │
       ┌───────┴─────────┐
       │                 │
       ▼                 ▼
customer_message      intent_result
       │                 │
       └────────┬────────┘
                ▼
     GroundedGenerationRequest
                │
                ▼
     GroundedGenerationResult
                │
                ▼
       AnswerServiceResult
```

---

# Error Propagation Strategy

The service distinguishes between errors it owns and errors it does not own.

## Owned by AnswerService

```text
InvalidAnswerRequestError
UnsupportedAnswerDecisionError
UnsupportedRetrievalKindError
InvalidRetrievalDecisionError
```

## Owned by lower-level domains

```text
retrieval-domain errors
generation-domain errors
provider-specific failures
```

Lower-level domain errors remain typed and propagate upward.

This allows the orchestrator to classify failures accurately.

---

# Testing Considerations

The design makes the service straightforward to test because its dependencies are injected explicitly.

A test can construct:

```text
AnswerService
    │
    ├── mock retrieval context service
    ├── mock query preparation service
    ├── mock grounding builder
    ├── mock evidence mapper
    └── mock response generator
```

Important behavior to test includes:

### Request validation

* non-string customer message;
* empty customer message;
* invalid intent result;
* invalid decision result;
* invalid retrieval filters;
* invalid conversation context.

### Routing validation

* `ANSWER` decision;
* `RETRIEVE_INFORMATION` without retrieval kind;
* empty retrieval kind;
* unknown retrieval kind;
* `KNOWLEDGE`;
* `OPERATIONAL`.

### Knowledge path

* retrieval context creation;
* query preparation;
* grounding context construction;
* evidence mapping;
* generation request construction;
* generation result propagation.

### Empty retrieval

Verify that:

```text
empty evidence
```

is passed to the generator rather than treated as an exception.

### Failure propagation

Verify that retrieval and generation domain exceptions remain distinguishable.

---

# Example Successful Flow

Conceptually:

```python
request = AnswerServiceRequest(
    customer_message="How can I return my order?",
    intent_result=intent_result,
    decision_result=decision_result,
    trusted_filters=filters,
    conversation_context=context,
)

result = answer_service.answer(request=request)
```

The resulting object contains:

```text
result.evidence
result.generation
```

The orchestrator can then use those values to update its own AI workflow state.

---

# Example Unsupported Flow

If the decision is:

```text
DecisionType.ANSWER
```

the service does not attempt retrieval.

Instead:

```text
answer()
  │
  ▼
_resolve_retrieval_kind()
  │
  ▼
UnsupportedAnswerDecisionError
```

---

# Example Operational Retrieval

If the decision contains:

```text
RETRIEVE_INFORMATION
retrieval_kind = OPERATIONAL
```

the service rejects it:

```text
UnsupportedRetrievalKindError
```

because V1 implements only knowledge retrieval.

---

# Future Extension: Operational Retrieval

The current architecture intentionally leaves room for operational retrieval.

Today:

```text
RETRIEVE_INFORMATION
       │
       ▼
KNOWLEDGE
       │
       ▼
AnswerService
```

Future architecture may allow:

```text
RETRIEVE_INFORMATION
       │
       ├── KNOWLEDGE
       │      └── AnswerService
       │
       └── OPERATIONAL
              └── Operational Tool/Service
```

Both paths can ultimately produce:

```text
RetrievedEvidence
```

which keeps the higher-level orchestration contract neutral.

The current source explicitly identifies this as a future direction.

---

# Design Principles

## 1. Validate routing before retrieval

The service must know what source it is supposed to query before executing retrieval.

---

## 2. Do not silently reinterpret decisions

Unsupported decisions are rejected rather than converted into another workflow.

---

## 3. Keep retrieval implementation details isolated

Knowledge-specific internals remain behind application/knowledge services.

---

## 4. Keep generation provider-independent

The service depends on `GroundedResponseGenerator`, not a concrete LLM SDK.

---

## 5. Preserve typed failures

Retrieval and generation failures remain distinguishable.

---

## 6. Treat no evidence as a semantic result

Lack of evidence should allow the generator to produce an appropriate insufficient-evidence response instead of encouraging hallucination.

---

## 7. Return evidence and generation separately

The orchestrator owns lifecycle state transitions.

---

## 8. Centralize routing metadata migration

`_resolve_retrieval_kind()` provides one boundary for evolving the `DecisionResult` schema.

---

# Summary

`answer_service.py` is the **application integration boundary for grounded customer-support answers**.

Its core responsibility can be summarized as:

```text
Validate
   │
   ▼
Route
   │
   ▼
Retrieve Knowledge
   │
   ▼
Map Evidence
   │
   ▼
Generate Grounded Answer
   │
   ▼
Return Evidence + Generation
```

The V1 implementation supports only:

```text
RETRIEVE_INFORMATION
        +
    KNOWLEDGE
```

and explicitly rejects unsupported decisions and retrieval kinds.

The most important architectural property is its boundary between the generic AI layer and the knowledge subsystem:

```text
AI Domain
   │
   │ neutral contracts
   ▼
AnswerService
   │
   │ application integration
   ▼
Knowledge Retrieval
   │
   ▼
Grounded Evidence
   │
   ▼
Grounded Generation
```

This allows the AI package to remain unaware of retrieval implementation details while the knowledge package remains independent of AI orchestration and LLM-specific concerns.
