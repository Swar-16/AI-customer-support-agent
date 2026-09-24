# AI Package

## Overview

The `packages/ai` package contains the **core AI application layer** of the customer-support system.

It is responsible for coordinating and implementing the intelligence required to transform an incoming customer-support request into a controlled, observable outcome.

At a high level, the AI package brings together:

```text
Customer Request
       │
       ▼
┌──────────────────────┐
│     Orchestration    │
└──────────┬───────────┘
           │
           ├──────────────► Intent
           │
           ├──────────────► Decision
           │
           ├──────────────► Retrieval / Knowledge
           │
           ├──────────────► Generation
           │
           └──────────────► Guardrails
                          │
                          ▼
                    Final Outcome
                          │
                          ▼
                    AI Telemetry
```

The package is deliberately organized around **separation of responsibilities**.

The orchestration layer coordinates the workflow, while specialized subsystems own intent classification, decision-making, retrieval, generation, and other AI-specific behavior. Orchestration itself does not implement those underlying algorithms or business policies.

---

# Package Structure

The `ai` package is organized into domain-focused subsystems.

```text
AI-customer-support-agent/
└── packages/
    └── ai/
        ├── orchestration/
        ├── intent/
        ├── decision/
        ├── retrieval/
        ├── generation/
        ├── telemetry/
        └── ...
```

The exact set of directories may evolve as the system grows, but the architectural principle remains the same:

> Each AI capability owns its own implementation and contracts, while orchestration composes those capabilities into a complete support workflow.

---

# Architectural Role

The AI package sits between the application's support-facing layer and the lower-level infrastructure/provider layers.

Conceptually:

```text
                         Customer Support System
                                  │
                                  ▼
                         ┌─────────────────┐
                         │   Application   │
                         │   / Use Cases   │
                         └────────┬────────┘
                                  │
                                  ▼
                    ┌──────────────────────────┐
                    │       packages/ai        │
                    │                          │
                    │  Orchestration           │
                    │  Intent                  │
                    │  Decision                │
                    │  Retrieval               │
                    │  Generation              │
                    │  Telemetry               │
                    └────────────┬─────────────┘
                                 │
               ┌─────────────────┼─────────────────┐
               ▼                 ▼                 ▼
          AI Providers       Database          Guardrails
```

The package therefore acts as the system's **AI domain boundary**.

---

# Core Responsibilities

The AI package is responsible for:

* understanding customer intent;
* determining the appropriate workflow;
* retrieving supporting knowledge where required;
* generating grounded responses;
* handling deterministic support responses;
* requesting clarification when required information is missing;
* representing workflow state;
* converting AI failures into structured errors;
* coordinating guardrail evaluation;
* tracking AI execution;
* recording retrieval and reranker telemetry;
* exposing stable contracts between AI subsystems.

It is **not** intended to become a dumping ground for unrelated business logic, persistence logic, or infrastructure code.

---

# Major AI Subsystems

## 1. Orchestration

The `orchestration` package is the workflow coordination layer.

It coordinates the lifecycle:

```text
Customer Message
      │
      ▼
Intent Routing / Classification
      │
      ▼
Decision
      │
      ├── ANSWER
      ├── RETRIEVE_INFORMATION
      ├── ASK_CLARIFICATION
      └── ESCALATE
      │
      ▼
Response Path
      │
      ▼
Guardrails
      │
      ├── PASS
      ├── REFUSE
      └── ESCALATE
      │
      ▼
Terminal Outcome
```

The orchestration layer deliberately does not implement intent-classification algorithms, decision rules, retrieval algorithms, persistence, retry mechanisms, generation prompts, or business policy.

### Main responsibilities

```text
orchestration/
├── state.py
├── direct_response.py
├── orchestrator.py
└── README.md
```

`state.py` provides the canonical workflow state and lifecycle vocabulary.

`direct_response.py` provides deterministic, application-controlled responses without requiring an LLM.

`orchestrator.py` coordinates the complete workflow.

---

# 2. Intent

The intent subsystem determines **what the customer is trying to accomplish**.

Conceptually:

```text
Customer Message
      │
      ▼
Deterministic Routing
      │
      ├── matched ──────────────┐
      │                         │
      └── no match              │
             │                  │
             ▼                  │
      Intent Classifier          │
             │                  │
             └──────────┬───────┘
                        ▼
                  Intent Result
```

The orchestration layer consumes the resulting intent rather than knowing how the classifier internally works.

This keeps classification implementation independent from workflow composition.

---

# 3. Decision

The decision subsystem determines **what the system should do next** based on the interpreted customer intent and available context.

The supported workflow decisions include:

```text
ANSWER
RETRIEVE_INFORMATION
ASK_CLARIFICATION
ESCALATE
```

The orchestrator consumes the decision and dispatches the appropriate workflow.

This separation means:

```text
Intent
   ↓
Decision
   ↓
Workflow
```

rather than embedding decision logic directly into orchestration.

---

# 4. Retrieval and Knowledge

The retrieval subsystem provides the knowledge required for grounded responses.

A typical retrieval pipeline is conceptually:

```text
Query
  │
  ├───────────────► Vector Retrieval
  │
  └───────────────► Lexical Retrieval
                          │
                          ▼
                       Fusion
                          │
                          ▼
                      Reranking
                          │
                          ▼
                  Grounding Context
```

The orchestration layer consumes provider-neutral evidence/context rather than retrieval implementation details.

For example, the orchestration evidence model intentionally hides details such as:

```text
vector distance
lexical rank
RRF score
embedding model
pgvector
reranker implementation
```

Those details belong inside the retrieval/knowledge subsystem rather than the orchestration contract.

---

# 5. Generation

The generation subsystem is responsible for producing responses when the workflow requires model-generated or grounded output.

Conceptually:

```text
Intent
   +
Decision
   +
Customer Context
   +
Retrieved Evidence
   │
   ▼
Grounded Generation
   │
   ▼
Generated Response
```

The orchestration layer is responsible for deciding **when** generation happens and how generation outcomes affect workflow state.

The generation subsystem owns the details of the provider interaction.

---

# 6. Deterministic Responses

Not every customer request needs an LLM.

The orchestration layer supports application-controlled responses for workflows such as:

```text
CONVERSATIONAL
OUT_OF_SCOPE
ASK_CLARIFICATION
```

These paths use deterministic response resolution.

For example:

```text
Decision = ASK_CLARIFICATION
        │
        ▼
Allowlisted clarification response
        │
        ▼
Normal response lifecycle
        │
        ▼
Guardrails
```

The direct-answer workflow likewise uses `DirectResponseResolver` and does not perform knowledge retrieval, provider generation, operational lookup, or business actions.

This provides predictable behavior for workflows that do not require generative AI.

---

# 7. Guardrails

Generated or selected responses pass through guardrail evaluation before becoming eligible for final persistence/output.

Conceptually:

```text
Response
   │
   ▼
Guardrail Evaluator
   │
   ├── PASS
   │
   ├── REFUSE
   │
   └── ESCALATE
```

This gives the system a final control point between response generation and customer-facing completion.

The orchestrator treats guardrail outcomes as workflow state rather than embedding guardrail implementation details itself.

---

# 8. Telemetry

The `telemetry` package is the observability and persistence boundary for AI execution.

It captures:

```text
orchestration stages
retrieval runs
retrieval candidates
reranker calls
timing
latency
provider/model identity
lifecycle status
errors
retryability
candidate ranks
candidate scores
context selection
bounded fingerprints
stable identifiers
```

Telemetry therefore surrounds the AI pipeline rather than implementing the AI capabilities themselves.

---

# Telemetry Architecture

The telemetry layer has three major scopes.

```text
                 AI Execution
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
     Stages      Retrieval      Reranker
        │            │            │
        ▼            ▼            ▼
   Stage Events  Retrieval Run  Reranker Calls
```

### Stage telemetry

Captures:

```text
orchestration lifecycle
duration
errors
retryability
```

### Retrieval telemetry

Captures:

```text
retrieval configuration
retrieval stages
candidate rankings
candidate scores
context selection
context size
latency
```

### Reranker telemetry

Captures:

```text
reranker identity
provider/model
candidate-set identity
input/output counts
latency
provider request ID
status
errors
timeouts
```

---

# End-to-End AI Flow

The complete AI package can be viewed as:

```text
                         Customer Message
                                │
                                ▼
                    ┌─────────────────────┐
                    │ Deterministic Route │
                    └──────────┬──────────┘
                               │
                       ┌───────┴────────┐
                       │                │
                    matched          no match
                       │                │
                       │                ▼
                       │         Intent Classifier
                       │                │
                       └───────┬────────┘
                               ▼
                         Intent Result
                               │
                               ▼
                         Decision Engine
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
            ▼                  ▼                  ▼
         ANSWER          RETRIEVE_INFO      CLARIFICATION
            │                  │                  │
            ▼                  ▼                  ▼
     Direct Response       Retrieval       Allowlisted
                           Pipeline        Response
            │                  │                  │
            │                  ▼                  │
            │             Grounding Context       │
            │                  │                  │
            └──────────────────┼──────────────────┘
                               ▼
                       Response Generated
                               │
                               ▼
                       Guardrail Evaluator
                               │
                 ┌─────────────┼─────────────┐
                 │             │             │
                 ▼             ▼             ▼
                PASS         REFUSE       ESCALATE
                 │             │             │
                 └─────────────┼─────────────┘
                               ▼
                         Final Outcome
                               │
                               ▼
                           Telemetry
```

The V1 orchestration flow explicitly follows intent → decision → response/retrieval/clarification → guardrails → terminal disposition.

---

# Canonical Workflow State

The orchestration subsystem exposes `AIState` as the canonical representation of one AI-support execution.

The workflow stages include:

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

These stage identifiers support orchestration, tracing, structured logging, failure analysis, and dashboards.

---

# Structured Failure Handling

AI failures are represented as structured `PipelineError` objects rather than allowing arbitrary provider exceptions to define the workflow state.

A pipeline error contains:

```text
code
message
stage
retryable
metadata
```

This allows failures to remain machine-readable throughout the system.

Conceptually:

```text
Provider Exception
       │
       ▼
AI-specific error
       │
       ▼
PipelineError
       │
       ▼
AIState
       │
       ▼
Telemetry / terminal outcome
```

---

# AI Package Boundaries

The package follows a clear ownership model.

| Concern                          | Owner                         |
| -------------------------------- | ----------------------------- |
| Workflow coordination            | `orchestration`               |
| Canonical workflow state         | `orchestration.state`         |
| Intent interpretation            | `intent`                      |
| Workflow decision                | `decision`                    |
| Knowledge retrieval              | retrieval/knowledge subsystem |
| Response generation              | `generation`                  |
| Response safety                  | guardrails                    |
| Execution observability          | `telemetry`                   |
| Database persistence             | database/application layers   |
| Business policy                  | policy/application domain     |
| External provider implementation | provider-specific components  |

This prevents individual AI components from becoming tightly coupled to infrastructure or one another.

---

# Provider Independence

The AI package should interact with providers through domain-level contracts.

For example:

```text
Orchestrator
     │
     ▼
Generation Contract
     │
     ▼
Provider Adapter
     │
     ▼
External LLM
```

rather than:

```text
Orchestrator
     │
     ▼
Specific LLM SDK
```

The same principle applies to:

* embeddings;
* rerankers;
* classifiers;
* retrieval providers;
* generation providers.

This makes providers replaceable without rewriting orchestration logic.

---

# Observability Model

Telemetry allows the different AI subsystems to be correlated through stable identifiers.

A typical trace is:

```text
AI Run
  │
  ├── trace_id
  │
  ├── orchestration stage events
  │
  └── Retrieval Run
          │
          ├── embedding call
          │
          ├── retrieval candidates
          │
          └── Reranker Call
                  │
                  └── provider request ID
```

This makes it possible to reconstruct an operational execution path without storing the underlying customer conversation or knowledge-base content.

---

# Privacy and Data Minimization

The AI package's telemetry architecture is explicitly designed to avoid turning observability data into a copy of customer data.

Telemetry stores operational information such as:

```text
IDs
fingerprints
counts
ranks
scores
latencies
status
provider/model identity
error codes
bounded metadata
timestamps
```

It does not intentionally store:

```text
customer message text
query text
retrieved chunk content
candidate content
prompts
generated answers
conversation context
```

When textual correlation is required, bounded SHA-256 fingerprints are used instead of raw text.

---

# Transaction Boundaries

AI operations can involve slow external services, so telemetry persistence avoids holding database transactions open during provider calls.

The intended pattern is:

```text
AI operation
     │
     ▼
Telemetry event/state
     │
     ▼
Short database transaction
     │
     ▼
Commit
```

rather than:

```text
BEGIN
   │
   ├── embedding call
   ├── retrieval
   ├── reranking
   └── LLM call
   │
COMMIT
```

The telemetry package explicitly uses short transactions for retrieval, reranker lifecycle transitions, and orchestration-stage events.

---

# Validation Philosophy

The AI package uses explicit domain validation at subsystem boundaries.

Telemetry, for example, validates:

```text
UUID values
timezone-aware timestamps
non-negative latency
non-empty error fields
expected domain types
expected repository implementations
```

More generally, AI subsystems should reject malformed domain inputs at their boundaries instead of allowing invalid state to propagate through the pipeline.

---

# Orchestration and Telemetry Relationship

The relationship between the two packages is especially important:

```text
                    Orchestrator
                         │
                         │ lifecycle
                         ▼
                 StageTelemetryEvent
                         │
                         ▼
                   Telemetry Sink
                         │
             ┌───────────┴───────────┐
             ▼                       ▼
        Structured Logs       Database Events
```

The telemetry event abstraction is intentionally independent of:

* SQLAlchemy;
* OpenTelemetry;
* Prometheus;
* logging vendors.

Adapters can translate the same structured event into different telemetry systems.

---

# Pluggable Telemetry

The telemetry architecture supports multiple destinations.

The sink abstraction can support implementations such as:

```text
LoggingTelemetrySink
OpenTelemetrySink
MetricsTelemetrySink
CompositeTelemetrySink
```

A composite sink can fan an event out to multiple destinations, while isolating failures between sinks.

This allows observability infrastructure to evolve without changing orchestration code.

---

# Deterministic vs Generative Paths

The AI architecture deliberately supports both deterministic and generative execution.

## Deterministic

Examples:

```text
known direct response
clarification response
out-of-scope response
```

These can use application-owned templates and do not necessarily require an LLM.

## Generative

Examples:

```text
knowledge-grounded support answer
```

These may require:

```text
retrieval
    ↓
grounding context
    ↓
generation provider
    ↓
guardrails
```

The orchestrator selects the appropriate path according to the decision result.

---

# Retrieval-Grounded Generation

For knowledge-backed support requests, the conceptual flow is:

```text
Customer Message
       │
       ▼
Intent
       │
       ▼
Decision = RETRIEVE_INFORMATION
       │
       ▼
Retrieval
       │
       ├── Vector
       ├── Lexical
       ├── Fusion
       └── Reranking
       │
       ▼
Grounding Context
       │
       ▼
Generation
       │
       ▼
Guardrails
       │
       ▼
Response
```

Telemetry records the operational characteristics of the retrieval and reranking stages without persisting the underlying retrieved text.

---

# Escalation

Escalation is a first-class workflow outcome.

A decision may directly produce:

```text
ESCALATE
```

in which case response generation is bypassed and the workflow moves toward human review.

Guardrails can also produce an escalation outcome after evaluating a response.

Thus escalation can originate from different stages while still converging on the same workflow state model.

---

# AI Package Design Principles

## 1. Separation of concerns

Each subsystem owns a focused responsibility.

```text
Intent       → What does the customer want?
Decision     → What should the system do?
Retrieval    → What evidence is available?
Generation   → What response should be produced?
Guardrails   → Is the response acceptable?
Orchestration→ How do these pieces execute together?
Telemetry    → What happened during execution?
```

---

## 2. Explicit contracts

Subsystems communicate through typed/domain-level objects instead of exposing implementation details.

---

## 3. Provider independence

Provider SDKs should remain behind provider-specific adapters.

---

## 4. Deterministic control where possible

Not every support request should invoke generative AI.

Application-controlled responses are preferred for workflows where deterministic behavior is sufficient.

---

## 5. Grounded generation

When a response depends on enterprise knowledge, retrieval and evidence should precede generation.

---

## 6. Safety before completion

Responses pass through guardrail evaluation before reaching the terminal response lifecycle.

---

## 7. Observable execution

Every significant workflow stage should be observable through structured telemetry.

---

## 8. Data minimization

Operational visibility should not require duplicating customer conversations or knowledge-base content into telemetry.

---

## 9. Short database transactions

Database transactions should surround persistence operations rather than external AI/provider calls.

---

## 10. Structured failures

Failures should carry:

```text
code
stage
retryability
metadata
```

instead of relying exclusively on raw exception messages.

---

# Conceptual Dependency Direction

The intended dependency direction is:

```text
                    Application
                        │
                        ▼
                 AI Orchestration
                  /    |     \
                 /     |      \
                ▼      ▼       ▼
            Intent   Decision  Generation
                \      |       /
                 \     |      /
                  ▼    ▼     ▼
                    Retrieval
                       │
                       ▼
                    Evidence

                    Telemetry
                       ▲
                       │
              observes execution
```

The important distinction is that telemetry **observes** execution rather than owning the AI workflow.

Likewise, orchestration **coordinates** subsystems rather than implementing their internal algorithms.

---

# What Does Not Belong Here

The `packages/ai` package should not become the home for unrelated infrastructure.

Avoid placing the following directly inside AI domain modules unless they are genuinely AI-specific:

```text
database session management
raw SQL
HTTP routing
authentication
customer account CRUD
generic caching infrastructure
deployment configuration
business-policy definitions
provider SDK initialization
generic logging configuration
```

Those concerns belong in their respective application/infrastructure layers.

The AI package should consume the appropriate abstractions instead.

---

# Typical Execution Trace

A successful grounded request may look like:

```text
1. Request received
        │
        ▼
2. Context built
        │
        ▼
3. Intent determined
        │
        ▼
4. Decision made
        │
        ▼
5. Retrieval started
        │
        ├── vector retrieval
        ├── lexical retrieval
        ├── fusion
        └── reranking
        │
        ▼
6. Grounding context constructed
        │
        ▼
7. Response generated
        │
        ▼
8. Guardrails evaluated
        │
        ▼
9. Response accepted
        │
        ▼
10. Workflow completed
```

Telemetry can independently capture the operational events surrounding these stages.

---

# Failure Trace

A failure follows the same state-oriented architecture:

```text
AI Stage
   │
   ▼
Exception / invalid result
   │
   ▼
Structured AI Error
   │
   ▼
PipelineError
   │
   ▼
AIState(stage=FAILED)
   │
   ├── retryable?
   ├── error code
   └── metadata
   │
   ▼
Telemetry
```

This makes failures consistent across providers and AI subsystems.

---

# Extension Points

The package is designed to grow without requiring the orchestrator to become tightly coupled to new implementations.

Potential future AI components can include:

```text
additional intent classifiers
additional retrieval strategies
additional rerankers
additional generation providers
tool/function execution
agentic workflows
specialized domain agents
additional guardrail evaluators
additional telemetry sinks
```

The preferred pattern is:

```text
New Capability
      │
      ▼
Domain Contract
      │
      ▼
Implementation / Adapter
      │
      ▼
Orchestrator integration
```

rather than placing implementation details directly inside `orchestrator.py`.

---

# Operational Observability

The combined AI telemetry architecture makes it possible to investigate:

### Workflow performance

```text
Which stage consumed the most time?
Where are latency spikes occurring?
Which workflows fail most often?
```

### Retrieval performance

```text
How many candidates enter retrieval?
How many survive fusion?
How many survive reranking?
How many are selected for grounding?
```

### Provider behavior

```text
Which provider/model was used?
How long did it take?
Did it fail?
Did it timeout?
Was the failure retryable?
```

### Workflow correctness

```text
Which decision was made?
Which branch executed?
Did the request reach guardrails?
Did it complete or escalate?
```

These questions can be answered using operational metadata without persisting the underlying customer content.

---

# Summary

`packages/ai` is the **core AI domain boundary** of the customer-support system.

Its architecture separates:

```text
Interpretation
     ↓
Decision
     ↓
Evidence
     ↓
Response
     ↓
Safety
     ↓
Outcome
     ↓
Observability
```

The major responsibilities are distributed across specialized subsystems:

```text
┌───────────────────────────────────────────────┐
│                 packages/ai                   │
├───────────────────────────────────────────────┤
│                                               │
│  Intent        Understand customer intent     │
│  Decision      Select workflow                │
│  Retrieval     Obtain supporting evidence     │
│  Generation    Produce responses              │
│  Orchestration Coordinate execution           │
│  Guardrails    Evaluate response safety       │
│  Telemetry     Observe and persist execution  │
│                                               │
└───────────────────────────────────────────────┘
```

The orchestration layer provides the workflow composition boundary, while telemetry provides an operational observability boundary. The telemetry architecture captures stage, retrieval, and reranker execution while deliberately minimizing sensitive content persistence.

The resulting architecture keeps the AI system:

* modular;
* provider-independent;
* observable;
* testable;
* state-driven;
* safety-aware;
* retrieval-grounded;
* privacy-conscious;
* and extensible.
