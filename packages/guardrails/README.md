# Guardrails

## Overview

The `packages/guardrails/` package provides the deterministic **response-safety boundary** for the AI customer-support pipeline.

Its purpose is to evaluate a generated customer response against a controlled set of application-defined guardrail policies **before the response is exposed to the customer**.

The package deliberately separates:

* the **data contract** used by guardrails;
* individual **policy implementations**;
* deterministic **policy orchestration**;
* and **guardrail-specific exceptions**.

```text
Generated AI Response
        │
        ▼
┌───────────────────────┐
│   GuardrailContext    │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│   GuardrailEvaluator  │
│                       │
│  Ordered Policies     │
└───────────┬───────────┘
            │
      ┌─────┴─────┐
      │           │
      ▼           ▼
   Violation     No violation
      │           │
      ▼           ▼
GuardrailResult   PASS
      │
 ┌────┴─────┐
 ▼          ▼
REFUSE    ESCALATE
```

The package consists of four files:

```text
packages/guardrails/
├── models.py
├── policies.py
├── evaluator.py
└── errors.py
```

---

# Responsibilities

The guardrails layer is responsible for **deterministic post-generation validation**.

It protects against situations where an AI response:

* is missing when the selected decision requires one;
* is incompatible with the AI decision;
* attempts to override trusted instructions;
* attempts to expose protected prompt content;
* falsely claims that a sensitive business action was completed;
* presents customer-specific operational information without trusted operational evidence.

The guardrail system is intentionally narrow. It is not a general-purpose toxicity classifier, sentiment analyzer, or autonomous business-decision engine.

---

# Architecture

The package follows a simple policy/evaluator architecture:

```text
                    GuardrailContext
                           │
                           ▼
                 ┌───────────────────┐
                 │ GuardrailEvaluator │
                 └─────────┬─────────┘
                           │
             configured policies, in order
                           │
       ┌───────────────────┼──────────────────────────┐
       ▼                   ▼                          ▼
 Response Presence   Decision Compatibility   Prompt Manipulation
       │                   │                          │
       └───────────────────┼──────────────────────────┘
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
 Sensitive Action Claim       Unsupported Operational Claim
             │                           │
             └─────────────┬─────────────┘
                           ▼
                    GuardrailResult
```

The evaluator is intentionally a coordinator rather than a policy engine. Policy-specific detection logic lives inside the individual policy classes.

---

# Package Components

## `models.py`

`models.py` defines the contracts shared by the entire guardrail subsystem.

The primary types are:

* `GuardrailOutcome`
* `GuardrailReasonCode`
* `GuardrailContext`
* `GuardrailResult`

### Guardrail Outcomes

A guardrail evaluation can produce one of three dispositions:

| Outcome    | Meaning                                                                                                       |
| ---------- | ------------------------------------------------------------------------------------------------------------- |
| `PASS`     | The generated response may be exposed to the customer                                                         |
| `REFUSE`   | The generated response must not be exposed and the request should receive a safe refusal                      |
| `ESCALATE` | The generated response must not be treated as authoritative and the workflow should move toward human support |

These outcomes form the external decision contract of the guardrail subsystem.

### Reason Codes

`GuardrailReasonCode` provides stable machine-readable reasons such as:

* `SAFE_RESPONSE`
* `MISSING_GENERATED_RESPONSE`
* `DECISION_RESPONSE_MISMATCH`
* `UNSUPPORTED_KNOWLEDGE_CLAIM`
* `UNSUPPORTED_OPERATIONAL_CLAIM`
* `INVALID_CITATION_REFERENCE`
* `SENSITIVE_ACTION_CLAIM`
* `PROMPT_MANIPULATION_ATTEMPT`
* `SAFETY_RESTRICTION`

These identifiers are intended for telemetry, persistence, evaluation, dashboards, and escalation routing.

### `GuardrailContext`

`GuardrailContext` is the deliberately narrow input contract supplied to policies.

It contains:

```text
customer_message
decision
generated_response
retrieved_evidence
```

The model is immutable and rejects unexpected fields. Customer messages and generated responses are also normalized and bounded in size.

The narrow context is important architecturally: guardrail policies should not mutate orchestration state, depend on pipeline implementation details, access retrieval infrastructure directly, or make business workflow decisions themselves.

### `GuardrailResult`

`GuardrailResult` represents the final disposition produced by evaluation.

It contains:

```text
outcome
reason_code
reason_summary
policy_id
metadata
```

The model is immutable and explicitly prevents empty reason summaries or malformed policy identifiers. Its `passed` property provides a convenient check for `PASS`.

`reason_summary` is diagnostic/audit information and is explicitly not intended to expose private chain-of-thought or internal model reasoning.

---

# `policies.py`

`policies.py` contains the individual deterministic guardrail policies.

All policies implement the common `GuardrailPolicy` contract:

```text
evaluate(context)
        │
        ├── violation → GuardrailResult
        │
        └── no violation → None
```

The evaluator is responsible for combining these results and producing the final `PASS` result.

---

## Response Presence Policy

`ResponsePresencePolicy` verifies that decisions which require customer-visible text actually have generated text.

Response-producing decisions include:

* `ANSWER`
* `RETRIEVE_INFORMATION`
* `ASK_CLARIFICATION`

If such a decision reaches the guardrail layer without a generated response, the policy produces:

```text
ESCALATE
└── MISSING_GENERATED_RESPONSE
```

This protects against an invalid pipeline state where orchestration has decided that a response should be produced but generation did not actually provide one.

---

## Decision Compatibility Policy

`DecisionCompatibilityPolicy` ensures that customer-visible text is compatible with the workflow decision.

Direct responses are allowed for:

* `ANSWER`
* `RETRIEVE_INFORMATION`
* `ASK_CLARIFICATION`

If a generated response exists for an incompatible decision, the result is:

```text
ESCALATE
└── DECISION_RESPONSE_MISMATCH
```

Clarification is treated as response-compatible because orchestration constructs its text from an application-controlled allowlist. Escalation and action-oriented decisions remain incompatible with normal generated responses.

---

## Prompt Manipulation Policy

`PromptManipulationPolicy` detects explicit attempts to manipulate trusted instructions or extract protected prompt content.

It specifically targets patterns associated with:

* instruction override;
* prompt extraction;
* questions requesting hidden instructions;
* system/developer role injection;
* reassignment of trust to customer-supplied text.

The policy deliberately does **not** treat ordinary:

* anger;
* criticism;
* disagreement with company policy;
* requests for human support

as prompt manipulation.

When detected, it produces:

```text
REFUSE
└── PROMPT_MANIPULATION_ATTEMPT
```

The matching customer text itself is not copied into the result or telemetry.

This makes the policy a narrow defense against instruction-boundary attacks rather than a general language classifier.

---

## Sensitive Action Claim Policy

`SensitiveActionClaimPolicy` prevents the model from claiming that a sensitive business operation was actually completed when no trusted action-result contract exists in the guardrail context.

Examples include claims that the assistant:

* issued or processed a refund;
* cancelled an order, subscription, or account;
* changed or reset account credentials or payment information;
* reversed or voided a payment or transaction.

Such a response results in:

```text
ESCALATE
└── SENSITIVE_ACTION_CLAIM
```

The policy is intentionally conservative and narrow. It does not attempt to understand arbitrary natural language or replace a future trusted action-authorization subsystem.

---

## Unsupported Operational Claim Policy

`UnsupportedOperationalClaimPolicy` prevents a generated response from presenting customer-specific operational facts as if they came from a trusted operational system.

Operational claims include information concerning:

* orders;
* payments;
* transactions;
* charges;
* shipments/packages;
* subscriptions;
* accounts.

The policy checks whether trusted operational evidence is present in `retrieved_evidence`.

If such evidence exists, the response is allowed through this policy.

If the response contains an operational claim without operational evidence, the result is:

```text
ESCALATE
└── UNSUPPORTED_OPERATIONAL_CLAIM
```

The implementation is intentionally conservative and currently relies on textual heuristics; the policy documentation identifies structured operational evidence as the eventual stronger approach.

---

# `evaluator.py`

`GuardrailEvaluator` is the deterministic coordinator for all configured policies.

Its responsibilities are intentionally limited to:

1. validating policy configuration;
2. maintaining policy order;
3. invoking policies;
4. validating policy results;
5. stopping at the first violation;
6. producing the final `PASS` result when no policy detects a violation.

It does not contain the policy-specific detection logic.

---

## Evaluation Semantics

Evaluation is deterministic:

```text
for policy in configured_order:
    result = policy.evaluate(context)

    if no violation:
        continue

    return first violation

return PASS
```

The first detected violation terminates evaluation. Therefore, **policy ordering is significant**.

---

## Default Policy Ordering

The default V1 configuration is:

```text
1. ResponsePresencePolicy
2. DecisionCompatibilityPolicy
3. PromptManipulationPolicy
4. SensitiveActionClaimPolicy
5. UnsupportedOperationalClaimPolicy
```

The structural response checks intentionally run before semantic defense-in-depth checks.

Conceptually:

```text
Structural validity
        │
        ▼
Response presence
        │
        ▼
Decision compatibility
        │
        ▼
Prompt manipulation
        │
        ▼
Sensitive action claims
        │
        ▼
Unsupported operational claims
        │
        ▼
PASS
```

---

## Policy Configuration Validation

The evaluator requires at least one policy.

Each configured policy must implement `GuardrailPolicy`.

Policy identifiers must also be unique.

These constraints prevent ambiguous or invalid evaluator configuration.

During evaluation, the evaluator additionally validates that:

* the context is a `GuardrailContext`;
* policies return either `None` or `GuardrailResult`;
* policies do not directly return `PASS`.

A policy returning `PASS` directly violates the policy contract because `None` is the representation for "no violation."

When every policy returns `None`, the evaluator creates a `PASS` result with:

```text
reason_code = SAFE_RESPONSE
policy_id   = None
```

and includes the number of evaluated policies in metadata.

---

# `errors.py`

`errors.py` defines exceptions specific to failures **inside the guardrail subsystem**.

The base exception is:

```text
GuardrailError
```

with specialized exceptions:

```text
GuardrailConfigurationError
GuardrailEvaluationError
InvalidGuardrailContextError
```

These represent configuration, execution, and context-structure failures respectively.

A key distinction is that **policy violations are not represented by these exceptions**.

Policy violations are normal guardrail outcomes represented through `GuardrailResult`.

```text
Policy Violation
      │
      ▼
GuardrailResult
   ├── REFUSE
   └── ESCALATE

Guardrail Subsystem Failure
      │
      ▼
Exception
   ├── Configuration
   ├── Evaluation
   └── Context
```

This distinction keeps expected safety decisions separate from unexpected subsystem failures.

---

# End-to-End Flow

The complete guardrail flow can be summarized as:

```text
AI Pipeline
    │
    ▼
Generated Response
    │
    ▼
Construct GuardrailContext
    │
    ├── Customer Message
    ├── Decision
    ├── Generated Response
    └── Retrieved Evidence
    │
    ▼
GuardrailEvaluator
    │
    ├── Response Presence
    │
    ├── Decision Compatibility
    │
    ├── Prompt Manipulation
    │
    ├── Sensitive Action Claim
    │
    └── Unsupported Operational Claim
    │
    ▼
GuardrailResult
    │
    ├──────────────┬───────────────┐
    ▼              ▼               ▼
   PASS          REFUSE         ESCALATE
    │              │               │
    ▼              ▼               ▼
Expose         Safe refusal    Human-support
response       workflow        workflow
```

---

# Guardrail Decision Matrix

| Situation                                            | Outcome    | Reason                          |
| ---------------------------------------------------- | ---------- | ------------------------------- |
| All policies pass                                    | `PASS`     | `SAFE_RESPONSE`                 |
| Required response missing                            | `ESCALATE` | `MISSING_GENERATED_RESPONSE`    |
| Response incompatible with decision                  | `ESCALATE` | `DECISION_RESPONSE_MISMATCH`    |
| Prompt/instruction manipulation detected             | `REFUSE`   | `PROMPT_MANIPULATION_ATTEMPT`   |
| Unsupported sensitive action claim                   | `ESCALATE` | `SENSITIVE_ACTION_CLAIM`        |
| Operational claim lacks trusted operational evidence | `ESCALATE` | `UNSUPPORTED_OPERATIONAL_CLAIM` |

The guardrail layer therefore distinguishes between situations where the request should receive a controlled refusal and situations where the generated answer should not be trusted and the workflow should move toward human support.

---

# Architectural Boundaries

## Guardrails Do Not Own AI Generation

The guardrails layer evaluates a proposed response. It does not generate the response.

```text
AI Generation
      │
      ▼
Guardrails
```

---

## Guardrails Do Not Own Retrieval

Guardrails consume provider-neutral retrieved evidence through `GuardrailContext`.

They do not directly query retrieval infrastructure. The context model explicitly exists to prevent this coupling.

---

## Guardrails Do Not Mutate AI State

The guardrail context is immutable.

Policies should inspect the supplied context and return a result; they should not modify orchestration state.

---

## Guardrails Do Not Execute Business Actions

The sensitive-action policy specifically protects against the model claiming that an action occurred without a trusted action result.

Actual business operations belong to the appropriate application services.

---

# Extensibility

New deterministic checks should generally be introduced as a new `GuardrailPolicy` rather than adding more policy-specific logic to `GuardrailEvaluator`.

The intended extension pattern is:

```text
New Requirement
      │
      ▼
New GuardrailPolicy
      │
      ▼
evaluate(context)
      │
      ├── violation → GuardrailResult
      └── safe       → None
      │
      ▼
Register in evaluator ordering
```

This preserves the evaluator's role as a coordinator and keeps individual safety rules independently testable.

Policy IDs must remain unique when extending the configured policy set.

---

# Key Design Principles

### Deterministic

The evaluator and included policies are deterministic checks rather than another generative model.

### Ordered

Policy ordering is explicit and significant.

### Fail Closed

Invalid response states and unsupported sensitive claims do not silently pass.

### Narrow

Policies focus on clearly defined safety invariants rather than attempting to solve every possible natural-language safety problem.

### Immutable

The primary guardrail input and output models are immutable.

### Provider-Neutral

Guardrails operate on application-level contracts instead of provider-specific AI or retrieval objects.

### Auditable

Stable outcome and reason codes make decisions suitable for telemetry, persistence, dashboards, and escalation routing.

### Extensible

New rules can be implemented independently behind the `GuardrailPolicy` abstraction.

---

# Summary

The `packages/guardrails/` package forms the **deterministic safety checkpoint between AI response generation and customer exposure**.

Its responsibilities are divided cleanly:

```text
models.py
    ↓
Defines guardrail inputs, outcomes, reason codes, and results

policies.py
    ↓
Defines individual deterministic safety rules

evaluator.py
    ↓
Executes those rules in a controlled order

errors.py
    ↓
Represents guardrail subsystem failures
```

The core architectural contract is:

```text
             Proposed AI Response
                     │
                     ▼
             GuardrailContext
                     │
                     ▼
            GuardrailEvaluator
                     │
             ordered policies
                     │
                     ▼
             GuardrailResult
              /      |       \
             /       |        \
          PASS     REFUSE   ESCALATE
            │         │         │
            ▼         ▼         ▼
        Customer   Safe      Human
        Response   Refusal   Support
```

The package therefore provides a small, deterministic, and composable boundary for preventing invalid, unsupported, or unsafe AI responses from being presented as authoritative customer-support answers.
