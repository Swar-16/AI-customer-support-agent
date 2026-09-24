# Retrieval Query Preparation

## Overview

The `packages/knowledge/retrieval/query/` package is responsible for transforming a validated customer-retrieval context into a **deterministic, retrieval-specific query representation**.

It sits between the application/AI layer and the actual retrieval engines.

```text
Customer / AI Understanding
          │
          ▼
RetrievalQueryContext
          │
          ▼
RetrievalQueryPreparationService
          │
          ▼
RetrievalQueryBuilder
          │
          ▼
PreparedRetrievalQuery
       │          │
       │          ├── semantic_query
       │          │        │
       │          │        ▼
       │          │   Vector Retrieval
       │          │
       │          └── lexical_queries
       │                   │
       │                   ▼
       │              Lexical Retrieval
       │
       └── trusted filters
```

The package contains four files:

```text
AI-customer-support-agent/
└── packages/
    └── knowledge/
        └── retrieval/
            └── query/
                ├── builder.py
                ├── errors.py
                ├── models.py
                ├── service.py
                └── README.md
```

The four modules have distinct responsibilities:

| File         | Responsibility                                                                   |
| ------------ | -------------------------------------------------------------------------------- |
| `models.py`  | Defines the input and output contracts for query preparation                     |
| `builder.py` | Deterministically transforms retrieval context into semantic and lexical queries |
| `errors.py`  | Defines the domain-specific error hierarchy for query preparation                |
| `service.py` | Provides the stable application-facing boundary around the query builder         |

---

# Architectural Role

The query package is deliberately positioned **before retrieval execution**.

It does not search the knowledge base itself.

```text
                         Query Preparation
                               │
       ┌───────────────────────┴───────────────────────┐
       │                                               │
       ▼                                               ▼
RetrievalQueryContext                           Trusted Filters
       │
       ▼
RetrievalQueryBuilder
       │
       ▼
PreparedRetrievalQuery
       │
       ├───────────────┬─────────────────┐
       ▼               ▼                 ▼
original_query   semantic_query   lexical_queries
                       │                 │
                       ▼                 ▼
                 Vector Search      Lexical Search
```

This separation keeps query interpretation and normalization independent from retrieval infrastructure.

---

# Core Design Principle: Semantic Hints vs Trusted Filters

One of the most important boundaries in this package is the distinction between **semantic information** and **trusted retrieval constraints**.

`RetrievalQueryContext` explicitly treats:

* customer message;
* intent hints;
* entity hints;
* conversation context

as semantic input.

Entities are **not automatically converted into hard database/retrieval filters**.

Hard filters must come from trusted application context.

Conceptually:

```text
AI / Customer-derived information
            │
            ▼
      Semantic hints
            │
            ├── intent
            ├── entities
            ├── message
            └── conversation context
            │
            ▼
       Query generation


Trusted application information
            │
            ▼
       Hard filters
            │
            ▼
       Retrieval scope
```

This prevents customer-controlled or model-generated identifiers from accidentally becoming authorization or database-scope constraints.

---

# `models.py`

`models.py` defines the two central immutable data contracts:

```text
RetrievalQueryContext
PreparedRetrievalQuery
```

Both are frozen, slotted dataclasses.

---

# `RetrievalQueryContext`

`RetrievalQueryContext` represents the **semantic input to query preparation**.

Its fields are:

```text
RetrievalQueryContext
├── customer_message
├── intent_key
├── entities
├── filters
└── conversation_context
```

The intent is represented as a stable string such as:

```text
refund_request
payment_issue
general_question
```

This deliberately avoids making the retrieval subsystem depend on AI intent-domain classes.

---

## `customer_message`

The customer message is required.

It must:

* be a string;
* contain usable non-whitespace content.

Whitespace is normalized before the value is stored.

For example:

```text
"   Where   is   my order?   "
```

becomes:

```text
"Where is my order?"
```

Invalid customer messages raise `InvalidCustomerMessageError`.

---

## `intent_key`

The intent is optional.

When supplied, it is normalized using the same text normalization rules.

The package does not require the intent to belong to a predefined enumeration.

The distinction is:

```text
Malformed intent value
        │
        ▼
InvalidIntentHintError

Unknown but structurally valid intent
        │
        ▼
Allowed as a semantic hint
```

This keeps the retrieval layer decoupled from the AI intent taxonomy.

---

## `entities`

Entities are represented as:

```text
Mapping[str, str]
```

Each key and value must contain usable text.

The normalized mapping is wrapped in `MappingProxyType`, preventing callers from mutating the context after construction.

Example:

```text
{
    "issue_type": "refund",
    "product": "wireless headphones"
}
```

Entities are semantic hints only.

They do **not** automatically become:

```text
WHERE order_id = ...
```

or another hard retrieval constraint.

---

## `filters`

`filters` represents the trusted retrieval scope.

It must be a valid:

```text
RetrievalFilters
```

instance.

Invalid filter objects raise `InvalidTrustedFiltersError`.

This creates the trust boundary:

```text
entities
   │
   └── semantic / untrusted

filters
   │
   └── trusted application scope
```

---

## `conversation_context`

Conversation context is optional.

When present, it is normalized as text.

Blank optional context becomes invalid/absent according to the normalization rules rather than being allowed to propagate as meaningless whitespace.

---

# `PreparedRetrievalQuery`

`PreparedRetrievalQuery` is the output of the query-preparation stage.

It contains:

```text
PreparedRetrievalQuery
├── original_query
├── semantic_query
├── lexical_queries
└── filters
```

These fields correspond directly to the downstream retrieval branches.

```text
PreparedRetrievalQuery
       │
       ├── semantic_query
       │       └──► vector retrieval
       │
       ├── lexical_queries
       │       └──► lexical retrieval
       │
       └── filters
               └──► trusted retrieval scope
```

The original normalized query is retained independently for traceability and downstream lifecycle use.

---

# Semantic Query

`semantic_query` is the natural-language representation intended for semantic/vector retrieval.

It is normalized and must be non-empty.

The query builder can construct this representation from the original customer request and relevant semantic context.

The semantic query is not required to have the same wording as the original message.

---

# Lexical Queries

`lexical_queries` is a tuple of compact query variants intended for full-text retrieval.

It has several important invariants:

* must be a tuple;
* each query must be valid text;
* queries are normalized;
* duplicate queries are removed case-insensitively;
* at least one usable lexical query must remain.

For example:

```text
(
    "refund payment",
    "refund payment",
    "payment refund"
)
```

becomes conceptually:

```text
(
    "refund payment",
    "payment refund"
)
```

The first occurrence is retained.

If no usable lexical query remains, `MissingLexicalQueriesError` is raised.

---

# Query Immutability

Both query models are immutable.

```text
@dataclass(frozen=True, slots=True)
```

This is important because prepared retrieval queries can be passed through multiple pipeline stages without allowing one component to silently modify the request another component is using.

---

# `builder.py`

`builder.py` contains the deterministic query-preparation implementation.

Its central responsibility is to transform:

```text
RetrievalQueryContext
```

into:

```text
PreparedRetrievalQuery
```

The builder is responsible for query normalization, semantic query construction, lexical query generation, entity handling, deduplication, and configured safety limits.

The lexical-query portion explicitly avoids treating identifier-like entities as normal lexical terms. For example, keys such as `order_id`, `account_id`, `transaction_id`, and `subscription_id` are excluded from generic lexical-term extraction.

---

# Identifier Handling

Identifier-like entity keys are deliberately excluded from generic lexical expansion.

The structural rule is:

```text
"id"
or
key.endswith("_id")
```

Therefore:

```text
order_id
account_id
transaction_id
subscription_id
```

are treated as identifiers rather than ordinary lexical search terms.

This helps prevent operational identifiers from polluting general policy/FAQ-style knowledge retrieval.

---

# Entity Term Extraction

Non-identifier entity values can contribute lexical terms.

The builder:

1. iterates over entity hints;
2. skips identifier-like keys;
3. treats `issue_type` separately;
4. tokenizes usable values;
5. optionally removes stop words;
6. deduplicates terms.

The resulting terms can contribute to lexical-query construction.

---

# Tokenization

The builder extracts lexical terms using a token pattern and normalizes them with `casefold()`.

Conceptually:

```text
Entity value
    │
    ▼
Tokenization
    │
    ▼
Normalization
    │
    ▼
Stop-word filtering
    │
    ▼
Term deduplication
```

This produces compact lexical terms suitable for full-text search rather than blindly passing the entire conversation context into a lexical backend.

---

# Term Deduplication

Lexical terms are deduplicated case-insensitively.

For example:

```text
Refund
refund
REFUND
```

collapse to one logical term.

The first occurrence is preserved.

This reduces unnecessary query length and avoids repeatedly contributing the same search term.

---

# Lexical Query Budget

The builder enforces a configured maximum lexical-query character count.

It builds the query incrementally without splitting a token in the middle.

Conceptually:

```text
terms
 │
 ├── term 1 ✓
 ├── term 2 ✓
 ├── term 3 ✓
 ├── term 4 ✗ exceeds budget
 │
 ▼
bounded lexical query
```

This prevents uncontrolled entity expansion from creating excessively large lexical-search requests.

---

# Oversized Individual Token

A single token may itself exceed the lexical character budget.

The builder avoids splitting that token as part of normal term construction.

Instead, it falls back to a bounded portion of the original query as a defensive mechanism. If no usable bounded query can be constructed, `QueryPreparationLimitError` is raised.

This preserves a strict safety boundary around generated lexical queries.

---

# Deterministic Preparation

The builder is intended to be deterministic.

Given equivalent:

```text
RetrievalQueryContext
+
configuration
```

it should produce the same:

```text
PreparedRetrievalQuery
```

This is important for:

* testing;
* reproducibility;
* retrieval evaluation;
* debugging;
* caching;
* observability.

The service layer specifically describes the builder operation as deterministic preparation.

---

# Query Expansion

The error model includes a dedicated:

```text
QueryExpansionError
```

for optional deterministic expansion.

This allows future support for things such as:

* synonyms;
* subtype expansion;
* deterministic entity expansion.

Expansion failures remain distinct from malformed input and basic query construction failures.

---

# Query Preparation Limits

The builder can enforce safety/resource limits.

Examples include:

* too many entity hints;
* excessive lexical variants;
* excessive prepared-query length;
* excessive conversation-context contribution.

These failures are represented by:

```text
QueryPreparationLimitError
```

which belongs to the builder-error branch of the hierarchy.

---

# `service.py`

`service.py` contains:

```text
RetrievalQueryPreparationService
```

This is the stable application-facing boundary around the builder.

Its responsibilities are:

* accept a validated `RetrievalQueryContext`;
* invoke the configured `RetrievalQueryBuilder`;
* preserve expected domain errors;
* translate unexpected implementation failures;
* validate the builder's return type.

---

# Dependency Injection

The service receives its builder explicitly:

```text
RetrievalQueryPreparationService(
    builder=...
)
```

The builder must be a valid `RetrievalQueryBuilder`.

Otherwise:

```text
RetrievalQueryPreparationUnavailableError
```

is raised.

This keeps strategy/configuration composition outside the service itself.

---

# `prepare()`

The main operation is:

```text
prepare(
    context: RetrievalQueryContext
) -> PreparedRetrievalQuery
```

The service first validates the input type.

```text
invalid context
      │
      ▼
TypeError
```

A valid context is passed directly to the configured builder.

---

# Domain Error Preservation

Known query-preparation errors are allowed to propagate unchanged.

```text
RetrievalQueryBuilder
        │
        ├── QueryNormalizationError
        ├── QueryConstructionError
        ├── QueryExpansionError
        ├── QueryPreparationLimitError
        └── other RetrievalQueryPreparationError
                    │
                    ▼
              caller receives
              original domain error
```

This preserves the semantic meaning of expected failures.

---

# Unexpected Error Translation

Unexpected implementation failures are not allowed to leak arbitrary exceptions through the application boundary.

They are translated into:

```text
UnexpectedRetrievalQueryPreparationError
```

with the original exception chained as the cause.

Conceptually:

```text
Unexpected internal exception
          │
          ▼
RetrievalQueryPreparationService
          │
          ▼
UnexpectedRetrievalQueryPreparationError
          │
          └── original exception preserved as cause
```

This provides callers with a stable service-level error contract.

---

# Output Contract Validation

The service also verifies that the builder actually returns:

```text
PreparedRetrievalQuery
```

If the builder returns an unexpected object, the service raises:

```text
UnexpectedRetrievalQueryPreparationError
```

This protects the application boundary from a malformed implementation or incorrectly configured builder.

---

# `errors.py`

`errors.py` defines the complete domain-specific exception hierarchy.

The root is:

```text
RetrievalQueryPreparationError
```

which derives from the broader retrieval error hierarchy.

This allows callers to catch all query-preparation failures without depending on individual implementation classes.

---

# Error Hierarchy

The hierarchy is conceptually:

```text
RetrievalQueryPreparationError
│
├── RetrievalQueryContextError
│   ├── InvalidCustomerMessageError
│   ├── InvalidIntentHintError
│   ├── InvalidEntityHintsError
│   ├── InvalidConversationContextError
│   └── InvalidTrustedFiltersError
│
├── PreparedRetrievalQueryError
│   ├── InvalidOriginalQueryError
│   ├── InvalidSemanticQueryError
│   ├── InvalidLexicalQueryError
│   └── MissingLexicalQueriesError
│
├── RetrievalQueryBuilderError
│   ├── QueryNormalizationError
│   ├── QueryConstructionError
│   ├── QueryExpansionError
│   └── QueryPreparationLimitError
│
├── RetrievalQueryConfigurationError
│   ├── InvalidQueryPreparationConfigError
│   └── QueryPreparationStrategyError
│       └── QueryPreparationStrategyNotFoundError
│
└── RetrievalQueryServiceError
    ├── RetrievalQueryPreparationUnavailableError
    └── UnexpectedRetrievalQueryPreparationError
```

This structure separates failures by responsibility rather than relying on generic `ValueError` or `RuntimeError` handling.

---

# Context Errors

These errors represent malformed input to the query-preparation stage:

```text
InvalidCustomerMessageError
InvalidIntentHintError
InvalidEntityHintsError
InvalidConversationContextError
InvalidTrustedFiltersError
```

They indicate that the input context itself is structurally invalid.

---

# Prepared Query Errors

These errors indicate that the resulting prepared representation is invalid:

```text
InvalidOriginalQueryError
InvalidSemanticQueryError
InvalidLexicalQueryError
MissingLexicalQueriesError
```

For example:

```text
no usable lexical queries
        │
        ▼
MissingLexicalQueriesError
```

The distinction allows callers to differentiate invalid source context from invalid prepared-query output.

---

# Builder Errors

Builder-specific failures include:

```text
QueryNormalizationError
QueryConstructionError
QueryExpansionError
QueryPreparationLimitError
```

These describe failures during deterministic transformation rather than malformed caller input.

---

# Configuration Errors

Configuration failures have their own branch:

```text
RetrievalQueryConfigurationError
├── InvalidQueryPreparationConfigError
└── QueryPreparationStrategyError
    └── QueryPreparationStrategyNotFoundError
```

This makes configuration problems distinguishable from runtime query failures.

---

# Service Errors

Service-level failures include:

```text
RetrievalQueryPreparationUnavailableError
UnexpectedRetrievalQueryPreparationError
```

The former indicates that the query-preparation capability is unavailable because a required dependency/strategy is missing.

The latter represents an unexpected internal failure translated at the application boundary.

---

# Complete Query Preparation Flow

The four files work together as follows:

```text
                  RetrievalQueryContext
                           │
                           ▼
             RetrievalQueryPreparationService
                           │
                    validate context
                           │
                           ▼
                  RetrievalQueryBuilder
                           │
             ┌─────────────┼─────────────┐
             │             │             │
             ▼             ▼             ▼
        normalize       entities      conversation
          query          / hints        context
             │             │             │
             └─────────────┼─────────────┘
                           ▼
                construct semantic query
                           │
                           ▼
                construct lexical queries
                           │
                           ▼
                  enforce safety limits
                           │
                           ▼
                 PreparedRetrievalQuery
                    │               │
                    ▼               ▼
              Vector Search    Lexical Search
```

---

# Position in the Full RAG Pipeline

The query package is one stage in the larger knowledge retrieval pipeline.

```text
Customer Message
       │
       ▼
AI / Application Understanding
       │
       ▼
RetrievalQueryContext
       │
       ▼
┌─────────────────────────────┐
│     Query Preparation       │
│                             │
│  models.py                  │
│  builder.py                 │
│  service.py                 │
│  errors.py                  │
└──────────────┬──────────────┘
               │
               ▼
      PreparedRetrievalQuery
          │             │
          │             │
          ▼             ▼
       Vector        Lexical
      Retrieval     Retrieval
          │             │
          └──────┬──────┘
                 ▼
               Fusion
                 │
                 ▼
             Reranking
                 │
                 ▼
         Grounding Context
                 │
                 ▼
          Answer Generation
```

---

# Integration With Retrieval

The prepared query is consumed by the retrieval orchestration layer.

The broader retrieval pipeline explicitly branches the prepared representation into:

```text
semantic query → vector retrieval
lexical query  → lexical retrieval
```

and then combines the resulting rankings through fusion before optional reranking.

Therefore, query preparation is not merely a convenience utility—it establishes the exact representations consumed by the retrieval branches.

---

# Security and Trust Boundary

The package's treatment of filters is particularly important.

A customer may say:

```text
"My order 12345 hasn't arrived."
```

or an AI system may extract:

```text
order_id = 12345
```

That identifier can be useful for semantic understanding, but it must not automatically become a trusted retrieval scope.

Instead:

```text
Customer / AI entity
        │
        ▼
semantic hint
        │
        ▼
query generation
```

while:

```text
Trusted application context
        │
        ▼
RetrievalFilters
        │
        ▼
actual retrieval scope
```

This separation is explicitly enforced by the query models.

---

# Why Semantic and Lexical Queries Are Separate

Different retrieval technologies benefit from different query representations.

### Semantic retrieval

Needs natural-language meaning:

```text
"How can I get a refund for an item I purchased?"
```

### Lexical retrieval

Benefits from compact searchable terms:

```text
"refund purchased item"
```

The preparation layer therefore produces both representations once, allowing downstream retrieval services to remain focused on their own search mechanisms.

---

# Query Normalization

Normalization is applied consistently throughout the query models.

The normalization process:

1. requires a string;
2. collapses whitespace;
3. strips redundant spacing;
4. rejects empty results.

Conceptually:

```text
raw text
   │
   ▼
split whitespace
   │
   ▼
join with single spaces
   │
   ▼
validated normalized text
```

This ensures that downstream retrieval receives predictable input.

---

# Immutability and Reproducibility

The package heavily favors immutable contracts:

```text
RetrievalQueryContext
PreparedRetrievalQuery
```

are frozen dataclasses.

Mappings such as entities are protected through immutable mapping wrappers.

This provides:

* safer cross-layer handoff;
* predictable equality;
* reduced accidental mutation;
* easier testing;
* reproducible retrieval behavior.

---

# Testing Strategy

The query package should be tested at four levels.

## Model Tests

Verify:

* whitespace normalization;
* blank-input rejection;
* invalid entity mappings;
* invalid filters;
* immutable entities;
* lexical query tuple requirements;
* lexical query deduplication;
* missing lexical-query rejection.

## Builder Tests

Verify:

* deterministic semantic-query generation;
* lexical term extraction;
* identifier exclusion;
* stop-word handling;
* term deduplication;
* lexical-query limits;
* conversation-context handling;
* query expansion behavior;
* configuration limits.

## Service Tests

Verify:

* dependency validation;
* context validation;
* correct builder invocation;
* preservation of domain errors;
* unexpected exception translation;
* invalid builder output detection.

## Error Tests

Verify that exceptions inherit from the expected domain base classes and preserve their semantic categories.

---

# Important Invariants

The query package maintains several important invariants.

### Valid Customer Input

`customer_message` must always be normalized, non-empty text.

### Trusted Filters

Only `RetrievalFilters` represents hard retrieval scope.

### Semantic Independence

The retrieval package does not depend on AI intent-domain classes.

### Lexical Query Availability

A prepared query must contain at least one usable lexical query.

### Lexical Deduplication

Equivalent lexical queries are retained only once.

### Bounded Queries

Generated lexical queries respect configured size limits.

### Immutable Contracts

Prepared query objects cannot be modified after construction.

### Stable Error Boundary

All expected query-preparation failures derive from `RetrievalQueryPreparationError`.

### Deterministic Preparation

Equivalent inputs and configuration should produce equivalent prepared-query representations.

---

# Design Principles

## 1. Separate Interpretation From Retrieval

The query package prepares retrieval inputs but never executes the search.

## 2. Separate Semantic Hints From Trusted Scope

AI/customer-derived entities are not silently promoted to hard filters.

## 3. Produce Retrieval-Specific Representations

Semantic and lexical retrieval receive representations appropriate to their respective search mechanisms.

## 4. Keep Models Immutable

Query objects are stable once created.

## 5. Keep Preparation Deterministic

The same context should produce predictable query representations.

## 6. Bound Generated Queries

Lexical expansion cannot grow without limits.

## 7. Preserve Error Semantics

Expected domain failures are not collapsed into generic exceptions.

## 8. Translate Unexpected Failures

The service boundary converts unexpected implementation failures into a stable application-level exception.

## 9. Keep Infrastructure Out

The query layer knows nothing about PostgreSQL, vector databases, Elasticsearch, embedding providers, or LLM providers.

---

# Summary

The `packages/knowledge/retrieval/query/` package is the **query transformation boundary** of the retrieval subsystem.

Its core transformation is:

```text
RetrievalQueryContext
        │
        ▼
RetrievalQueryPreparationService
        │
        ▼
RetrievalQueryBuilder
        │
        ▼
PreparedRetrievalQuery
        │
        ├──────────────┐
        ▼              ▼
 semantic_query   lexical_queries
        │              │
        ▼              ▼
 vector retrieval  lexical retrieval
        │              │
        └───────┬──────┘
                ▼
              Fusion
```

The four files provide a clean separation of responsibilities:

```text
models.py
    │
    └── immutable query contracts

builder.py
    │
    └── deterministic query transformation

errors.py
    │
    └── domain-specific failure taxonomy

service.py
    │
    └── stable application-facing boundary
```

The resulting design keeps **query preparation, retrieval infrastructure, ranking, grounding, and answer generation independently composable**, while maintaining an explicit trust boundary around retrieval filters and deterministic, bounded query construction.
