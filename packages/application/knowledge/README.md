# Knowledge Application Layer

## Overview

The `packages/application/knowledge/` package provides the application-layer boundary between the AI/orchestration workflow and the knowledge retrieval subsystem.

Its primary responsibility is to translate:

```text
AI semantic understanding
        +
trusted application retrieval scope
        +
optional conversation context
        ↓
application retrieval request
        ↓
knowledge retrieval query context
        ↓
knowledge retrieval subsystem
        ↓
grounding context
        ↓
provider-neutral AI evidence
```

The package deliberately keeps **AI-derived semantic hints** separate from **trusted application-controlled retrieval constraints**.

This distinction is the central design principle of these modules.

The package contains five files:

```text
AI-customer-support-agent/
└── packages/
    └── application/
        └── knowledge/
            ├── ai_request_factory.py
            ├── evidence_mapper.py
            ├── models.py
            ├── retrieval_context_factory.py
            ├── retrieval_context_service.py
            └── README.md
```

---

# Responsibilities

| File                           | Responsibility                                                                          |
| ------------------------------ | --------------------------------------------------------------------------------------- |
| `models.py`                    | Defines the application-level `KnowledgeRetrievalRequest` DTO                           |
| `ai_request_factory.py`        | Converts AI intent understanding into a validated application retrieval request         |
| `retrieval_context_factory.py` | Converts the application request into the knowledge subsystem's `RetrievalQueryContext` |
| `retrieval_context_service.py` | Facade coordinating the two request/context translation boundaries                      |
| `evidence_mapper.py`           | Converts knowledge grounding results into provider-neutral AI orchestration evidence    |

Together, they implement two related flows:

### Retrieval request flow

```text
IntentResult
     │
     ▼
AIKnowledgeRetrievalRequestFactory
     │
     ▼
KnowledgeRetrievalRequest
     │
     ▼
KnowledgeRetrievalContextFactory
     │
     ▼
RetrievalQueryContext
     │
     ▼
Knowledge Retrieval
```

### Evidence flow

```text
GroundingContext
     │
     ▼
KnowledgeEvidenceMapper
     │
     ▼
RetrievedEvidence
     │
     ▼
AI orchestration
```

---

# Architectural Position

The package sits between the AI/application workflow and the knowledge subsystem.

The intended dependency direction is:

```text
packages.ai
     │
     │ semantic understanding
     ▼
packages.application.knowledge
     │
     │ retrieval contracts
     ▼
packages.knowledge
```

The evidence mapper additionally connects knowledge retrieval output back toward the AI orchestration contract:

```text
packages.knowledge
       │
       │ GroundingContext
       ▼
packages.application.knowledge
       │
       │ RetrievedEvidence
       ▼
packages.ai.orchestration
```

`evidence_mapper.py` explicitly documents this dependency direction as:

```text
packages.knowledge
        ↓
packages.application
        ↓
packages.ai orchestration contracts
```

The application layer therefore acts as an adapter rather than allowing either subsystem to become tightly coupled to the other's internal models.

---

# Core Trust Boundary

The most important concept in this package is the distinction between **semantic hints** and **trusted retrieval constraints**.

## Semantic hints

AI-derived entities come from customer language and AI inference.

Examples include:

```text
order_id
transaction_id
subscription_id
account_id
issue_type
```

These values help the retrieval subsystem understand what the customer is talking about.

They are **not authorization information**.

`KnowledgeRetrievalRequest` explicitly documents that entities are untrusted retrieval hints and must not be interpreted as database-scope or authorization filters.

---

## Trusted filters

`RetrievalFilters` represents application-controlled retrieval constraints.

These can represent constraints such as:

```text
tenant
product
region
visibility
content type
```

They are kept separate from AI-derived entities and remain hard retrieval constraints.

The architecture therefore intentionally prevents this unsafe conceptual transformation:

```text
AI says:
    account_id = 123

        ↓

Do NOT interpret as:

    database scope = account 123
```

Instead:

```text
AI-derived entity
        ↓
semantic retrieval hint

Trusted application filter
        ↓
hard retrieval constraint
```

This separation is preserved by both factories and by the higher-level service.

---

# 1. `models.py`

## `KnowledgeRetrievalRequest`

`models.py` defines the central application-level DTO:

```python
KnowledgeRetrievalRequest
```

It is a frozen, slotted dataclass:

```text
@dataclass(frozen=True, slots=True)
```

Its fields are:

```text
customer_message
intent_key
entities
filters
conversation_context
```

Conceptually:

```text
KnowledgeRetrievalRequest
├── customer_message
├── intent_key
├── entities
├── filters
└── conversation_context
```

---

## `customer_message`

The original customer message is required.

It must:

* be a string;
* be stripped of surrounding whitespace;
* not be empty.

Invalid values raise `TypeError` or `ValueError` as appropriate.

---

## `intent_key`

The normalized semantic intent is also required.

It follows the same validation rules as `customer_message`:

```text
must be string
      ↓
strip whitespace
      ↓
must not be empty
```

---

## `entities`

Entities are represented as:

```python
Mapping[str, str]
```

They default to an empty mapping.

Validation requires:

* the overall object to be a mapping;
* every key to be a string;
* every value to be a string;
* keys to be non-empty after trimming;
* empty values to be discarded.

After normalization, entities are wrapped using:

```python
MappingProxyType
```

making the resulting mapping immutable from the caller's perspective.

---

## `filters`

The request requires:

```python
RetrievalFilters
```

If a different type is provided, construction fails with `TypeError`.

The default is an empty `RetrievalFilters` instance.

The important architectural point is that `filters` is structurally separate from `entities`.

---

## `conversation_context`

Conversation context is optional:

```text
str | None
```

If provided, it must:

1. be a string;
2. be stripped;
3. become `None` if empty.

This allows the retrieval layer to receive relevant bounded conversational context without requiring it to know how that context was obtained.

---

# 2. `ai_request_factory.py`

## `AIKnowledgeRetrievalRequestFactory`

This factory translates AI semantic understanding into the application retrieval contract.

Its documented purpose is:

```text
IntentResult
      ↓
KnowledgeRetrievalRequest
```

The factory's public operation is:

```python
create(
    *,
    customer_message,
    intent_result,
    trusted_filters=None,
    conversation_context=None
)
```

It produces:

```python
KnowledgeRetrievalRequest
```

---

# Factory Processing

The factory performs two main transformations:

```text
IntentResult
     │
     └── _extract_entity_hints()
              │
              ▼
        entity hints

trusted_filters
     │
     └── _resolve_trusted_filters()
              │
              ▼
        RetrievalFilters

Both
  │
  ▼
KnowledgeRetrievalRequest
```

---

## Intent validation

The supplied intent result must be:

```python
IntentResult
```

Otherwise:

```text
TypeError
```

is raised.

---

# Trusted Filter Resolution

If:

```text
trusted_filters is None
```

the factory creates:

```python
RetrievalFilters()
```

Otherwise the supplied value must already be a `RetrievalFilters` instance.

The factory does not derive trusted filters from the AI intent.

That is deliberate.

---

# Entity Extraction

The factory converts `IntentEntities` into:

```text
Mapping[str, str]
```

using `_extract_entity_hints()`.

The method requires an actual:

```python
IntentEntities
```

instance.

---

## Canonical entities

The canonical fields are:

```text
order_id
transaction_id
subscription_id
account_id
issue_type
```

These fields retain their canonical names.

Values are stripped and empty values are omitted.

---

## Additional attributes

`IntentEntities.attributes` is treated as an extensibility mechanism.

Additional attributes are accepted only when:

```text
key   is str
value is str
```

Malformed auxiliary entries are ignored rather than causing the complete retrieval request to fail.

---

## Canonical field precedence

Additional attributes cannot override canonical fields.

For example, if:

```text
canonical:
    order_id = ORD-123
```

and attributes contain:

```text
order_id = ORD-999
```

the attribute is ignored.

This ensures schema-defined semantic information has precedence over extensibility data.

---

# Resulting Request

The factory produces:

```text
KnowledgeRetrievalRequest(
    customer_message=...,
    intent_key=...,
    entities=...,
    filters=...,
    conversation_context=...
)
```

This creates the first stable application-level boundary.

---

# 3. `retrieval_context_factory.py`

## `KnowledgeRetrievalContextFactory`

This factory translates:

```text
KnowledgeRetrievalRequest
        ↓
RetrievalQueryContext
```

It is intentionally a very thin adapter.

Its public method is:

```python
create(*, request)
```

The request must be a:

```python
KnowledgeRetrievalRequest
```

instance.

---

# Field Mapping

The factory maps the application request directly:

```text
KnowledgeRetrievalRequest
        │
        ├── customer_message ──────► customer_message
        ├── intent_key ────────────► intent_key
        ├── entities ──────────────► entities
        ├── filters ───────────────► filters
        └── conversation_context ──► conversation_context
```

No semantic transformation is performed here.

That is important because semantic interpretation belongs upstream, while this factory's responsibility is boundary translation.

---

# Knowledge Package Isolation

The factory deliberately keeps the knowledge package independent from `packages.ai`.

The application request has already absorbed the AI-facing details, allowing the knowledge retrieval subsystem to receive its own:

```python
RetrievalQueryContext
```

rather than depending directly on `IntentResult`.

---

# 4. `retrieval_context_service.py`

## `KnowledgeRetrievalContextService`

This class is the application facade over the two factories.

Its purpose is to hide the intermediate:

```python
KnowledgeRetrievalRequest
```

from higher-level orchestration code.

The service coordinates:

```text
AIKnowledgeRetrievalRequestFactory
              │
              ▼
KnowledgeRetrievalRequest
              │
              ▼
KnowledgeRetrievalContextFactory
              │
              ▼
RetrievalQueryContext
```

---

# Dependencies

The constructor requires:

```python
AIKnowledgeRetrievalRequestFactory
KnowledgeRetrievalContextFactory
```

Both dependencies are type-checked during initialization.

This makes the service's collaborators explicit.

---

# Public Service API

The service exposes:

```python
create(
    *,
    customer_message,
    intent_result,
    trusted_filters=None,
    conversation_context=None
)
```

and returns:

```python
RetrievalQueryContext
```

Higher-level orchestration therefore does not need to manually perform the intermediate conversions.

---

# Service Execution Flow

The complete service operation is:

```text
create(...)
   │
   ├── customer_message
   ├── intent_result
   ├── trusted_filters
   └── conversation_context
             │
             ▼
AIKnowledgeRetrievalRequestFactory.create()
             │
             ▼
KnowledgeRetrievalRequest
             │
             ▼
KnowledgeRetrievalContextFactory.create()
             │
             ▼
RetrievalQueryContext
```

---

# Why the Service Exists

Without the service, higher-level code would need to know about:

```text
KnowledgeRetrievalRequest
AIKnowledgeRetrievalRequestFactory
KnowledgeRetrievalContextFactory
```

With the service, orchestration only needs:

```text
customer message
+
intent result
+
trusted filters
+
conversation context
```

and receives:

```text
RetrievalQueryContext
```

This is the facade's primary purpose.

---

# 5. `evidence_mapper.py`

## `KnowledgeEvidenceMapper`

The previous four files deal with the **request side** of knowledge retrieval.

`evidence_mapper.py` handles the **response side**.

It translates:

```text
GroundingContext
        ↓
RetrievedEvidence
```

The class is explicitly an application-layer adapter.

---

# Mapping Flow

```text
Knowledge Retrieval
        │
        ▼
GroundingContext
        │
        ├── GroundingContextBlock
        ├── GroundingContextBlock
        └── GroundingContextBlock
                 │
                 ▼
        KnowledgeEvidenceMapper
                 │
                 ▼
        RetrievedEvidence
```

The mapper returns:

```python
tuple[RetrievedEvidence, ...]
```

rather than exposing the knowledge subsystem's block objects to orchestration.

---

# Input Validation

The mapper requires:

```python
GroundingContext
```

and raises `TypeError` for another input type.

Every block is then mapped independently.

---

# Evidence Mapping

A `GroundingContextBlock` becomes:

```python
RetrievedEvidence
```

with:

```text
source_type
source_id
title
section
content
relevance_score
metadata
```

The source type is explicitly:

```text
EvidenceSourceType.KNOWLEDGE
```

---

# Source Identity

The evidence uses:

```text
source_id = chunk_id
```

while the human-readable information comes from:

```text
title   = document_title
section = section_title
content = content
```

and retrieval ranking is preserved through:

```text
relevance_score = retrieval_score
```

---

# Provenance Preservation

The mapper deliberately preserves knowledge-specific provenance inside metadata.

The following values are added:

```text
document_id
version_id
chunk_id
chunk_index
```

This provides traceability without forcing the generic `RetrievedEvidence` contract to understand knowledge-specific identifiers.

The design therefore achieves:

```text
Generic AI evidence contract
          +
Knowledge-specific provenance
          ↓
metadata
```

---

# Metadata Handling

Existing block metadata is first copied:

```python
metadata = dict(block.metadata)
```

Then stable provenance fields are added.

This means knowledge metadata is preserved while ensuring the standard provenance fields are available to downstream consumers.

---

# Complete Architecture

The five files together form the following architecture:

```text
                    AI / Application Layer
                           │
                           │
                    IntentResult
                           │
                           ▼
              ┌─────────────────────────┐
              │ AIKnowledgeRetrieval    │
              │ RequestFactory          │
              └────────────┬────────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │ KnowledgeRetrieval      │
              │ Request                 │
              └────────────┬────────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │ KnowledgeRetrieval      │
              │ ContextFactory          │
              └────────────┬────────────┘
                           │
                           ▼
                    RetrievalQueryContext
                           │
                           ▼
                 ┌─────────────────────┐
                 │ Knowledge Retrieval │
                 │ Subsystem           │
                 └──────────┬──────────┘
                            │
                            ▼
                    GroundingContext
                            │
                            ▼
                 ┌─────────────────────┐
                 │ KnowledgeEvidence   │
                 │ Mapper              │
                 └──────────┬──────────┘
                            │
                            ▼
                    RetrievedEvidence
                            │
                            ▼
                    AI Orchestration
```

---

# Request-Side vs Response-Side Adapters

A useful way to understand the package is to divide it into two halves.

## Request side

```text
ai_request_factory.py
        │
        ▼
models.py
        │
        ▼
retrieval_context_factory.py
        │
        ▼
retrieval_context_service.py
```

These files prepare and translate retrieval requests.

---

## Response side

```text
evidence_mapper.py
```

This file translates retrieved grounding information back into an orchestration-neutral evidence representation.

---

# Trust Model

The package maintains the following trust hierarchy:

```text
                    Trusted
                       ▲
                       │
          RetrievalFilters
                       │
                       │ hard constraints
                       │
                       │
                Application Layer
                       │
                       │
                 IntentResult
                       │
                       ▼
                   Untrusted
```

More accurately, `IntentResult` itself is accepted as an already-classified AI result, but the **entities extracted from it remain semantic hints** rather than authorization or scope controls. This distinction is explicitly preserved by the request model and factories.

---

# Important Invariants

## 1. AI entities never become trusted filters

```text
entities ≠ filters
```

Entities provide semantic retrieval hints.

Filters provide application-controlled retrieval constraints.

---

## 2. Canonical entities override auxiliary attributes

The canonical fields:

```text
order_id
transaction_id
subscription_id
account_id
issue_type
```

cannot be overwritten by arbitrary `attributes`.

---

## 3. Retrieval filters must have the correct type

The application boundary requires an actual:

```python
RetrievalFilters
```

instance.

---

## 4. Application requests are immutable

`KnowledgeRetrievalRequest` is:

```text
frozen=True
slots=True
```

and its entities are converted to a `MappingProxyType`.

---

## 5. Empty semantic values are removed

Entity values and optional conversation context are normalized so that empty strings do not propagate through the retrieval pipeline.

---

## 6. Knowledge internals do not leak into orchestration

The evidence mapper converts knowledge-specific `GroundingContextBlock` objects into generic `RetrievedEvidence` objects.

---

## 7. Provenance is retained

Although knowledge-specific models are hidden from orchestration, provenance remains available through evidence metadata:

```text
document_id
version_id
chunk_id
chunk_index
```

---

# Typical End-to-End Usage

A higher-level application component can use the facade approximately as:

```text
customer message
       │
       ▼
IntentResult
       │
       ├── entities
       └── intent
       │
       ▼
KnowledgeRetrievalContextService
       │
       ├── trusted RetrievalFilters
       └── optional conversation context
       │
       ▼
RetrievalQueryContext
       │
       ▼
knowledge retrieval
       │
       ▼
GroundingContext
       │
       ▼
KnowledgeEvidenceMapper
       │
       ▼
RetrievedEvidence[]
       │
       ▼
AI orchestration
```

The important property is that the caller does not need to understand the intermediate translation contracts.

---

# Error Behavior

The modules use explicit type validation at their boundaries.

Examples include:

```text
AIKnowledgeRetrievalRequestFactory
    ├── intent_result must be IntentResult
    ├── trusted_filters must be RetrievalFilters or None
    └── entities must be IntentEntities

KnowledgeRetrievalRequest
    ├── customer_message must be non-empty string
    ├── intent_key must be non-empty string
    ├── entities must be Mapping[str, str]
    ├── filters must be RetrievalFilters
    └── conversation_context must be string or None

KnowledgeRetrievalContextFactory
    └── request must be KnowledgeRetrievalRequest

KnowledgeRetrievalContextService
    ├── ai_request_factory must be AIKnowledgeRetrievalRequestFactory
    └── context_factory must be KnowledgeRetrievalContextFactory

KnowledgeEvidenceMapper
    └── context must be GroundingContext
```

These checks make invalid cross-layer contracts fail immediately rather than producing downstream retrieval failures.

---

# Testing Considerations

Tests for this package should focus primarily on **translation correctness, trust boundaries, normalization, and contract validation**.

## `models.py`

Test:

* empty `customer_message`;
* non-string `customer_message`;
* empty `intent_key`;
* non-string `intent_key`;
* invalid entity mapping;
* non-string entity keys;
* non-string entity values;
* blank entity keys;
* blank entity values;
* immutable entity mapping;
* invalid `RetrievalFilters`;
* invalid conversation context;
* blank conversation context normalization.

---

## `ai_request_factory.py`

Test:

* invalid `IntentResult`;
* missing trusted filters;
* valid trusted filters;
* invalid trusted filters;
* canonical entity extraction;
* whitespace normalization;
* empty entity omission;
* auxiliary attribute extraction;
* malformed auxiliary attributes;
* canonical field collision;
* preservation of conversation context;
* correct `intent_key` propagation.

---

## `retrieval_context_factory.py`

Test:

* invalid request type;
* complete field preservation;
* entity preservation;
* filter preservation;
* conversation-context preservation.

The factory should not introduce semantic changes to the request.

---

## `retrieval_context_service.py`

Test:

* invalid factory dependencies;
* correct factory invocation;
* trusted-filter propagation;
* conversation-context propagation;
* returned `RetrievalQueryContext`.

The service should coordinate rather than duplicate transformation logic.

---

## `evidence_mapper.py`

Test:

* invalid `GroundingContext`;
* empty grounding context;
* multiple blocks;
* source type mapping;
* chunk ID mapping;
* title/section/content preservation;
* relevance score preservation;
* existing metadata preservation;
* document/version/chunk provenance;
* chunk index preservation.

---

# Design Summary

The package is intentionally small but establishes an important architectural boundary.

```text
             AI understanding
                    │
                    ▼
       ┌────────────────────────┐
       │ AI Request Factory     │
       └────────────┬───────────┘
                    │
                    ▼
       ┌────────────────────────┐
       │ Application Request    │
       │ DTO                    │
       └────────────┬───────────┘
                    │
             trust boundary
                    │
                    ▼
       ┌────────────────────────┐
       │ Retrieval Context      │
       │ Factory                │
       └────────────┬───────────┘
                    │
                    ▼
          Knowledge Retrieval
                    │
                    ▼
       ┌────────────────────────┐
       │ Grounding Context      │
       └────────────┬───────────┘
                    │
                    ▼
       ┌────────────────────────┐
       │ Evidence Mapper        │
       └────────────┬───────────┘
                    │
                    ▼
          AI Retrieved Evidence
```

The five files therefore provide a clean application boundary with three major goals:

1. **Translate AI understanding into knowledge retrieval contracts.**
2. **Keep AI-derived semantic hints separate from trusted retrieval scope.**
3. **Translate knowledge grounding results into provider-neutral AI evidence while retaining provenance.**

This keeps `packages.ai` and `packages.knowledge` from becoming directly coupled to each other's internal models, while giving the application layer a single, explicit place to enforce the boundary between **semantic retrieval intent, trusted retrieval scope, knowledge retrieval, and AI grounding evidence**.
