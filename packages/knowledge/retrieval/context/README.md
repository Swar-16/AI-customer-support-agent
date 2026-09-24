# Retrieval Context

## Overview

The `packages/knowledge/retrieval/context/` package defines the **trusted grounding-context layer** of the knowledge retrieval pipeline.

Its responsibility is to transform ranked retrieval candidates into a **bounded, deduplicated, provenance-preserving context** that can be consumed by downstream grounded-generation components.

The package contains two files:

```text
AI-customer-support-agent/
└── packages/
    └── knowledge/
        └── retrieval/
            └── context/
                ├── models.py
                ├── builder.py
                └── README.md
```

The two files have complementary responsibilities:

| File         | Responsibility                                                                                                                        |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| `models.py`  | Defines the immutable models representing grounding blocks, final grounding context, and context budgets                              |
| `builder.py` | Converts ranked retrieval results into bounded grounding context using deduplication, redundancy suppression, and token/block budgets |

The overall flow is:

```text
RetrievalResult
      │
      ▼
GroundingContextBuilder
      │
      ├── preserve ranking order
      ├── remove duplicate chunks
      ├── suppress redundant chunks
      ├── enforce document limits
      ├── enforce block limits
      └── enforce token budget
      │
      ▼
GroundingContext
```

---

# Architectural Role

The context package sits between **retrieval** and **grounded generation**.

```text
Knowledge Retrieval
        │
        ▼
RetrievalResult
        │
        ▼
┌──────────────────────────────┐
│      Retrieval Context       │
│                              │
│  GroundingContextBuilder     │
│  GroundingContext models     │
│  Token estimation            │
│  Budget enforcement          │
│  Deduplication               │
│  Provenance preservation     │
└──────────────┬───────────────┘
               │
               ▼
       GroundingContext
               │
               ▼
     Evidence / Prompt Layer
               │
               ▼
      Grounded Generation
```

This package does **not** perform retrieval itself and does not format the final LLM prompt.

Its responsibility ends at producing a structured, bounded grounding representation.

---

# `models.py`

`models.py` defines the immutable data contracts used by the context-building layer.

It contains three primary models:

```text
GroundingContextBlock
GroundingContext
GroundingContextBudget
```

The models are implemented as frozen, slotted dataclasses, making them immutable and lightweight.

---

# `GroundingContextBlock`

`GroundingContextBlock` represents one trusted knowledge chunk selected for grounding.

It preserves both the actual knowledge content and enough provenance to trace the eventual answer back to its source.

```text
GroundingContextBlock
├── chunk_id
├── version_id
├── document_id
├── chunk_index
├── content
├── document_title
├── section_title
├── metadata
└── retrieval_score
```

The provenance fields allow downstream systems to:

* trace generated answers back to source knowledge;
* render citations;
* debug retrieval/context decisions;
* support auditing;
* reproduce grounding decisions.

The model is explicitly a **context-layer model**, not a database model or an LLM-provider payload.

---

## Validation

`GroundingContextBlock` performs strict validation.

### Identity

The following identifiers must be UUIDs:

```text
chunk_id
version_id
document_id
```

### Chunk Index

`chunk_index` must be:

* an integer;
* non-negative;
* not a boolean masquerading as an integer.

### Text

`content` and `document_title` must be non-empty strings after trimming.

`section_title` may be absent, but if present it is normalized and blank values become `None`.

### Metadata

`metadata` must be a mapping.

The mapping is copied into a `MappingProxyType`, preventing later mutation of the block's metadata.

### Retrieval Score

`retrieval_score` may be `None` or numeric.

If provided, it is normalized to `float` and must be finite.

These validations ensure that a grounding block is structurally trustworthy before it enters the final context.

---

# Creating Blocks from Retrieval Candidates

`GroundingContextBlock.from_candidate()` converts a `RetrievalCandidate` into a context block.

```text
RetrievalCandidate
        │
        ▼
GroundingContextBlock.from_candidate()
        │
        ▼
GroundingContextBlock
```

The method carries forward:

* chunk identity;
* document/version identity;
* chunk position;
* content;
* document title;
* section;
* metadata.

It also derives a single effective retrieval score through `_select_retrieval_score()`.

---

# Retrieval Score Selection

A retrieval candidate can have several scores produced by different pipeline stages.

The context layer chooses the most meaningful available score using this precedence:

```text
reranker_score
      ↓
fusion_score
      ↓
vector_similarity
      ↓
lexical_score
      ↓
None
```

The preference represents the latest available relevance signal.

For example, when reranking is not actually producing a score, the fusion score remains the effective pipeline-level relevance score.

This provides downstream consumers with one consistent `retrieval_score` without discarding the original candidate's richer score information.

---

# `GroundingContext`

`GroundingContext` represents the **final trusted context** produced after retrieval candidates have passed through:

* deduplication;
* redundancy filtering;
* budget enforcement.

It is produced before final prompt formatting.

Its structure is:

```text
GroundingContext
├── query
├── blocks
├── estimated_token_count
└── truncated
```

---

## Query

The context retains the original `RetrievalQuery`.

This allows the resulting context to remain explicitly associated with the query that produced it.

The builder/application layer can therefore verify that context has not accidentally been generated for a different retrieval request.

---

## Blocks

`blocks` is an immutable tuple of `GroundingContextBlock` objects.

The model validates that:

* the value is a tuple;
* every item is a `GroundingContextBlock`;
* no chunk ID appears more than once.

This provides a second defensive duplicate check at the final model boundary.

---

## Estimated Token Count

`estimated_token_count` records the estimated textual footprint of the selected context.

It must be:

* an integer;
* non-negative.

The estimate is intentionally provider-independent. Exact model tokenization can be introduced later without changing the context model itself.

---

## Truncation

`truncated` indicates that relevant candidates were excluded while constructing the context because of configured limits.

This allows downstream systems to distinguish:

```text
No relevant knowledge
```

from:

```text
Relevant knowledge existed,
but the context budget prevented all of it
from being included.
```

---

## Convenience Properties

`GroundingContext` exposes:

```text
block_count
is_empty
chunk_ids
```

These provide common context information without requiring callers to inspect the internal tuple directly.

---

# `GroundingContextBudget`

`GroundingContextBudget` controls how much retrieved knowledge may enter the final grounding context.

It contains:

```text
max_tokens
max_blocks
max_blocks_per_document
```

The default maximum blocks per document is `2`.

All limits must be greater than zero.

```text
max_tokens > 0
max_blocks > 0
max_blocks_per_document > 0
```

The budget is deliberately **independent of any specific LLM provider**.

A higher composition layer can later derive the budget from the selected model's context window without changing the context-building implementation.

---

# `builder.py`

`builder.py` contains the actual context-construction algorithm.

Its central class is:

```text
GroundingContextBuilder
```

The file also defines the token-estimation abstraction:

```text
TokenEstimator
```

and its default implementation:

```text
CharacterTokenEstimator
```

---

# `TokenEstimator`

`TokenEstimator` is an abstraction for estimating how much token budget a piece of text consumes.

```text
TokenEstimator
├── estimator_id
└── estimate(text)
```

The abstraction intentionally prevents the context builder from becoming coupled to a particular:

* LLM provider;
* tokenizer;
* model family.

This makes it possible to introduce exact provider-specific tokenization later without changing `GroundingContextBuilder`.

---

# `CharacterTokenEstimator`

`CharacterTokenEstimator` provides a lightweight deterministic implementation.

The default configuration is:

```text
characters_per_token = 4.0
```

Its estimate is approximately:

```text
ceil(character_count / characters_per_token)
```

with a minimum of one token for non-empty text.

It is explicitly an approximation rather than a guarantee and is intended for:

* provider-independent context budgeting;
* deterministic tests;
* lightweight deployments.

Exact model tokenization can later be introduced as another `TokenEstimator` implementation.

---

# `GroundingContextBuilder`

`GroundingContextBuilder` converts a ranked `RetrievalResult` into a bounded `GroundingContext`.

Its responsibilities are:

* preserve retrieval ordering;
* suppress duplicate chunk identities;
* suppress redundant overlapping chunks when safe;
* enforce block limits;
* enforce per-document limits;
* enforce token limits;
* preserve canonical chunk content and provenance;
* indicate when candidates were excluded by budget.

The candidate order supplied by retrieval is treated as the authoritative relevance order.

---

# Context Construction Algorithm

The builder processes candidates sequentially.

```text
RetrievalResult.candidates
          │
          ▼
     First candidate
          │
          ├── duplicate chunk? ─────► skip
          │
          ├── redundant? ───────────► skip
          │
          ├── document limit? ───────► exclude
          │
          ├── block limit? ──────────► exclude
          │
          ├── block too large? ──────► exclude
          │
          ├── total budget exceeded? ► exclude
          │
          ▼
       select block
          │
          ▼
       next candidate
```

The resulting blocks retain the original retrieval order.

This means higher-ranked candidates are considered first and receive priority when budgets become restrictive.

---

# Empty Retrieval

An empty `RetrievalResult` is not treated as an error.

The builder produces:

```text
GroundingContext
├── same query
├── blocks = ()
├── estimated_token_count = 0
└── truncated = false
```

This provides a valid representation of "retrieval produced no candidates" without throwing an exception.

---

# Duplicate Chunk Suppression

The builder maintains a set of seen chunk IDs.

If the same chunk appears more than once in the retrieval result, subsequent occurrences are ignored.

```text
Candidate A
  chunk_id = X
       │
       ▼
    selected

Candidate B
  chunk_id = X
       │
       ▼
     skip
```

This is a defensive measure even if the upstream retrieval/fusion pipeline is expected to produce unique candidates.

The final `GroundingContext` independently enforces the same invariant.

---

# Redundancy Suppression

The builder also suppresses obvious textual redundancy.

However, the check is intentionally conservative.

Two candidates are considered redundant only when they:

1. belong to the same document;
2. belong to the same document version;
3. have duplicate or containment-equivalent normalized content.

Candidates from different documents or versions are **not** removed merely because their text is similar.

This preserves independent provenance, since different sources may legitimately support the same statement.

---

# Document-Level Budget

The context budget can restrict the number of blocks contributed by a single document.

```text
max_blocks_per_document
```

For example:

```text
Document A → block 1 ✓
Document A → block 2 ✓
Document A → block 3 ✗
```

This prevents a single document from dominating the grounding context.

When a candidate is excluded because of this limit, the builder marks the resulting context as truncated.

---

# Global Block Budget

The builder also enforces:

```text
max_blocks
```

Once the number of selected blocks reaches this limit, additional candidates are excluded.

Again, this causes:

```text
truncated = True
```

because relevant retrieval candidates were available but could not all enter the final context.

---

# Token Budget

Each candidate is converted into a `GroundingContextBlock`.

The builder then estimates the complete textual footprint of that block.

Importantly, it does **not** estimate only `content`.

The estimate includes:

```text
document_title
section_title (if present)
content
```

This better represents what downstream generation will eventually need to consume.

---

# Whole-Block Selection

Context blocks are either included completely or excluded completely.

The builder does not truncate the middle of a knowledge chunk to make it fit.

```text
Candidate Chunk
      │
      ├── fits budget → include whole block
      │
      └── exceeds budget → exclude whole block
```

This preserves the direct relationship between the context and the persisted knowledge chunk and avoids creating partial, potentially misleading evidence.

---

# Budget Enforcement

A candidate is excluded when:

```text
block_tokens > max_tokens
```

or:

```text
current_tokens + block_tokens > max_tokens
```

The context is then marked:

```text
truncated = True
```

The builder continues evaluating candidates rather than terminating the entire operation merely because one candidate does not fit.

---

# Token Estimator Validation

The builder validates token-estimator output.

The estimator must return:

* an integer;
* a non-negative value;
* a non-zero value when the estimated text is non-empty.

Invalid estimator behavior produces `GroundingContextBudgetError`.

This prevents malformed token estimates from silently corrupting context-budget enforcement.

---

# Candidate Conversion Errors

When a retrieval candidate cannot be converted into a valid `GroundingContextBlock`, the builder raises:

```text
GroundingContextCandidateError
```

The original validation failure is preserved as the cause.

This gives callers a domain-specific error indicating that a retrieval candidate could not become valid grounding evidence.

---

# Provider-Neutral Context Construction

A key architectural principle is that the context builder does not depend on a particular LLM tokenizer or prompt format.

```text
                    Context Builder
                          │
             ┌────────────┴────────────┐
             │                         │
             ▼                         ▼
      TokenEstimator             Grounding Models
             │                         │
             ▼                         ▼
     provider-neutral            provider-neutral
```

The final prompt representation belongs to a later generation layer.

This allows the same context-selection logic to be reused with different LLM providers and models.

---

# Provenance Preservation

The context layer deliberately carries source information forward.

```text
RetrievalCandidate
      │
      ▼
GroundingContextBlock
      │
      ├── chunk_id
      ├── version_id
      ├── document_id
      ├── chunk_index
      ├── document_title
      ├── section_title
      └── metadata
```

This makes it possible for downstream systems to associate an answer with the knowledge that supported it.

The model explicitly identifies provenance preservation as supporting:

* citations;
* debugging;
* auditing;
* reproducibility.

---

# End-to-End Context Flow

The complete context pipeline is:

```text
                     Retrieval
                         │
                         ▼
                  RetrievalResult
                         │
                         ▼
              GroundingContextBuilder
                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              ▼              ▼
      Deduplicate    Redundancy      Budget
       Chunks         Filtering      Enforcement
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                GroundingContextBlock
                         │
                         ▼
                 GroundingContext
                         │
                         ▼
                Evidence Mapping
                         │
                         ▼
                Grounded Generation
```

---

# Relationship With Retrieval

The context package assumes that retrieval has already ranked candidates.

The builder does **not** re-rank candidates.

Instead:

```text
Retrieval
   │
   └── determines relevance ordering
             │
             ▼
Context Builder
   │
   └── determines which relevant candidates fit
       into the grounding constraints
```

This separation keeps ranking and context budgeting independent.

---

# Relationship With Grounded Generation

The context layer produces the structured knowledge representation consumed by later AI components.

It does not:

* construct the final prompt;
* call an LLM;
* generate an answer;
* decide whether the answer is safe;
* perform business actions.

Its output is simply the trusted knowledge context required by those later stages.

---

# Important Invariants

The package maintains several important invariants.

### Immutable Context Models

`GroundingContextBlock`, `GroundingContext`, and `GroundingContextBudget` are immutable dataclasses.

### Unique Chunks

A final `GroundingContext` cannot contain duplicate chunk IDs.

### Valid Provenance

Every context block retains document and version identity.

### Bounded Context

The context cannot exceed configured block, per-document, or token limits.

### Ordered Selection

Candidate relevance order from retrieval is preserved.

### No Partial Chunks

Candidate content is included as a whole block or excluded.

### Provider Independence

Context construction does not depend on a specific LLM provider or tokenizer.

### Explicit Truncation

When relevant candidates are excluded by budget, the context records this through `truncated`.

---

# Error Boundaries

The context package exposes domain-specific errors from the surrounding retrieval subsystem for invalid context construction.

```text
Invalid candidate
       │
       ▼
GroundingContextCandidateError

Invalid token estimation
       │
       ▼
GroundingContextBudgetError
```

These errors distinguish context-construction failures from ordinary empty retrieval.

An empty result is valid:

```text
RetrievalResult
    │
    └── no candidates
           │
           ▼
      Empty GroundingContext
```

Whereas malformed candidates or invalid budget calculations represent actual pipeline errors.

---

# Extensibility

The most obvious extension point is `TokenEstimator`.

The default:

```text
CharacterTokenEstimator
```

can later be replaced with implementations such as:

```text
ModelSpecificTokenEstimator
ProviderTokenEstimator
ExactTokenizerEstimator
```

without changing the `GroundingContextBuilder` API.

The core context-selection algorithm therefore remains independent of tokenizer implementation.

---

# Testing Considerations

The context layer should be tested around its invariants rather than implementation details.

Important scenarios include:

### Model validation

* invalid UUIDs;
* negative chunk indexes;
* blank content;
* invalid metadata;
* non-finite scores;
* duplicate chunk IDs;
* invalid budgets.

### Context building

* empty retrieval;
* normal ordered selection;
* duplicate chunks;
* duplicate text in the same document/version;
* similar text across different documents;
* per-document limits;
* maximum block limits;
* maximum token limits;
* oversized individual blocks;
* exact budget boundaries;
* truncation reporting.

### Token estimation

* empty text;
* normal text;
* invalid estimator configuration;
* negative estimates;
* non-integer estimates;
* zero estimate for non-empty text.

### Provenance

Verify that:

```text
chunk_id
version_id
document_id
chunk_index
document_title
section_title
metadata
```

are preserved when a retrieval candidate becomes a grounding block.

---

# Design Principles

## 1. Retrieval and Context Selection Are Separate

Retrieval determines relevance; context construction determines what can safely fit into the grounding context.

## 2. Preserve Provenance

Every selected block remains traceable to its source knowledge.

## 3. Budget Explicitly

Context size is controlled through explicit, provider-independent constraints.

## 4. Prefer Whole Evidence

Knowledge chunks are not partially truncated.

## 5. Preserve Ranking

Higher-ranked retrieval candidates are considered first.

## 6. Deduplicate Defensively

The context layer does not assume that upstream retrieval has already eliminated every duplicate.

## 7. Suppress Redundancy Conservatively

Only obvious same-document/version redundancy is removed.

## 8. Stay Provider-Neutral

Token estimation and context representation do not depend on one LLM provider.

## 9. Fail Explicitly

Malformed candidates and invalid token estimates produce domain-specific errors rather than silently generating questionable context.

## 10. Keep Context Structured

The output is a typed `GroundingContext`, not an already-formatted prompt string.

---

# Summary

The `packages/knowledge/retrieval/context/` package is the **bounded evidence-selection layer** between retrieval and grounded generation.

Its architecture is intentionally simple:

```text
models.py
    │
    ├── GroundingContextBlock
    ├── GroundingContext
    └── GroundingContextBudget
             ▲
             │
             │
builder.py   │
    │        │
    ├── TokenEstimator
    ├── CharacterTokenEstimator
    └── GroundingContextBuilder
             │
             ▼
      RetrievalResult
             │
             ▼
      GroundingContext
```

The central transformation is:

```text
Ranked Retrieval Candidates
            │
            ▼
     Deduplication
            │
            ▼
    Redundancy Filtering
            │
            ▼
     Document Limits
            │
            ▼
       Block Limits
            │
            ▼
       Token Budget
            │
            ▼
    Provenance-Preserving
      Grounding Context
```

This layer ensures that downstream AI generation receives **bounded, structured, traceable, and provider-independent knowledge context** rather than raw retrieval output.
