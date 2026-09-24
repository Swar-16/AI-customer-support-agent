# Intent Taxonomy

## Overview

The `intent` package defines the **canonical semantic taxonomy** used by the AI customer-support agent to classify customer requests.

This package establishes the vocabulary of supported customer goals and the semantic meaning of each intent. It is deliberately limited to **classification semantics** and does not encode workflow, routing, business actions, or downstream operational behavior.

The current package contains:

```text
AI-customer-support-agent/
└── packages/
    └── ai/
        └── intent/
            ├── taxonomy.py
            └── README.md
```

The primary implementation is `taxonomy.py`.

---

# Purpose

The intent taxonomy provides a stable semantic layer between:

```text
Customer message
       │
       ▼
Intent classification
       │
       ▼
Canonical IntentType
       │
       ▼
Downstream AI workflow
```

Its job is to answer:

> **What is the customer trying to accomplish or understand?**

It is not responsible for answering:

* Which workflow should execute?
* Which tool should be called?
* Should an operation be performed?
* Which team should receive the request?
* How should the request be routed?
* What business action should happen?

Those decisions belong to downstream decision and workflow layers.

---

# Design Principles

The taxonomy is designed around several important principles.

## 1. Canonical semantic identifiers

Each supported customer goal has a stable `IntentType` value.

These values may be persisted in:

* telemetry;
* evaluation datasets;
* dashboards;
* historical AI runs.

Therefore, existing intent values should not be renamed casually.

For example:

```python
IntentType.REFUND_REQUEST
```

has the canonical persisted value:

```text
refund_request
```

---

## 2. Semantics are separate from workflow

An intent describes **what the customer wants**, not **what the system should do**.

For example:

```text
CANCELLATION
```

means the customer wants to cancel something.

It does not mean:

```text
call_cancel_order()
```

or:

```text
route_to_cancellation_workflow()
```

Those behaviors belong elsewhere.

---

## 3. New intents should represent genuinely distinct goals

An intent should not be added merely because a new phrase or wording was encountered.

The taxonomy should grow only when a genuinely distinct customer goal needs to be represented.

---

# `taxonomy.py`

`taxonomy.py` contains the complete semantic taxonomy and its validation mechanisms.

Its major components are:

```text
IntentType
IntentDefinition
_INTENT_DEFINITIONS
INTENT_DEFINITIONS
get_intent_definition()
validate_intent_definitions()
_intent_name()
```

---

# `IntentType`

`IntentType` is a `StrEnum` containing the canonical intent identifiers.

The currently supported intents are:

| Intent               | Canonical value      | Meaning                                                       |
| -------------------- | -------------------- | ------------------------------------------------------------- |
| `REFUND_REQUEST`     | `refund_request`     | Refund-related request                                        |
| `PAYMENT_ISSUE`      | `payment_issue`      | Payment/charge/transaction problem                            |
| `ORDER_STATUS`       | `order_status`       | Status/progress of a specific order                           |
| `SHIPPING_ISSUE`     | `shipping_issue`     | Delivery/shipping problem                                     |
| `CANCELLATION`       | `cancellation`       | Request or question about cancellation                        |
| `SUBSCRIPTION_ISSUE` | `subscription_issue` | Subscription/plan/renewal issue                               |
| `ACCOUNT_ISSUE`      | `account_issue`      | Account access or management issue                            |
| `RETURN_EXCHANGE`    | `return_exchange`    | Return/exchange request                                       |
| `PRIVACY_SECURITY`   | `privacy_security`   | Privacy/security/account-compromise concern                   |
| `GENERAL_QUESTION`   | `general_question`   | Supported general informational question                      |
| `CONVERSATIONAL`     | `conversational`     | Greeting, thanks, goodbye, or support-capability conversation |
| `OUT_OF_SCOPE`       | `out_of_scope`       | Request unrelated to supported customer service               |
| `UNKNOWN`            | `unknown`            | Customer goal cannot be reliably mapped                       |

The enum is defined as the stable canonical semantic vocabulary.

---

# Intent Categories

The taxonomy can conceptually be grouped into several areas.

## Transaction and payment intents

```text
REFUND_REQUEST
PAYMENT_ISSUE
```

These cover financial transaction and refund-related customer goals.

---

## Order and fulfillment intents

```text
ORDER_STATUS
SHIPPING_ISSUE
CANCELLATION
RETURN_EXCHANGE
```

These cover the lifecycle of purchased items and orders.

---

## Account and service intents

```text
SUBSCRIPTION_ISSUE
ACCOUNT_ISSUE
PRIVACY_SECURITY
```

These cover ongoing services, account access, security, and personal-data concerns.

---

## General interaction intents

```text
GENERAL_QUESTION
CONVERSATIONAL
```

These distinguish informational support questions from ordinary conversational interaction.

---

## Classification fallback intents

```text
OUT_OF_SCOPE
UNKNOWN
```

These provide explicit categories for requests that should not be handled as normal supported customer-service requests or cannot be mapped reliably.

---

# `IntentDefinition`

`IntentDefinition` is an immutable dataclass describing the semantic meaning of one intent.

Its fields are:

```python
intent: IntentType
description: str
examples: tuple[str, ...]
```

The dataclass is declared with:

```python
@dataclass(frozen=True, slots=True)
```

This makes definitions immutable and lightweight.

---

# Definition Validation

`IntentDefinition.__post_init__()` validates and normalizes every definition.

## Intent type

The `intent` field must be an actual `IntentType`.

Otherwise:

```text
TypeError
```

is raised.

---

## Description

The description must be a string.

Whitespace is normalized using:

```python
" ".join(description.split())
```

An empty description is rejected with:

```text
ValueError
```

This ensures definitions remain clean and consistent even if their source formatting changes.

---

## Examples

Examples must be supplied as a tuple:

```python
tuple[str, ...]
```

rather than an arbitrary collection.

Every example must:

1. be a string;
2. be non-empty after normalization;
3. be whitespace-normalized;
4. be unique within the definition.

At least one example is required for every intent.

---

# Example Normalization

An input example such as:

```text
"   When   will   my refund arrive?   "
```

is normalized to:

```text
"When will my refund arrive?"
```

Duplicate examples are removed while preserving their first occurrence.

This ensures the registry contains canonical semantic examples rather than formatting variants.

---

# Intent Registry

The private registry is:

```python
_INTENT_DEFINITIONS
```

It is a dictionary mapping:

```text
IntentType
    →
IntentDefinition
```

For example:

```python
IntentType.REFUND_REQUEST
    →
IntentDefinition(
    intent=IntentType.REFUND_REQUEST,
    description=...,
    examples=...
)
```

The registry contains the complete semantic definition of every supported intent.

---

# Intent Definitions

## `REFUND_REQUEST`

Represents requests concerning:

* receiving money back;
* refund eligibility;
* refund progress;
* refund timing;
* a refund that has not arrived.

Examples include:

```text
"I want a refund."
"When will my refund arrive?"
"Why have I not received my refund yet?"
```

---

## `PAYMENT_ISSUE`

Represents problems involving:

* payments;
* charges;
* transactions;
* payment methods;
* duplicate charges;
* failed payments;
* payment processing.

Examples include:

```text
"My payment keeps failing."
"I was charged twice."
"Why was my card declined?"
```

---

## `ORDER_STATUS`

Represents requests about the current state or progress of a specific order.

Examples include:

```text
"Where is my order?"
"What is the status of order ORD-123?"
"Has my order been processed yet?"
```

---

## `SHIPPING_ISSUE`

Represents delivery or shipping problems, including:

* delays;
* failed deliveries;
* missing deliveries;
* damaged shipments;
* other shipping concerns.

Examples include:

```text
"My package is late."
"The delivery never arrived."
"My shipment was damaged."
```

---

## `CANCELLATION`

Represents requests or questions about cancelling:

* orders;
* services;
* subscriptions;
* other supported customer commitments.

Examples include:

```text
"I want to cancel my order."
"Can I cancel this?"
"How do I cancel my subscription?"
```

---

## `SUBSCRIPTION_ISSUE`

Represents problems or questions involving:

* subscriptions;
* plans;
* renewals;
* subscription state;
* recurring services.

Examples include:

```text
"Why did my subscription renew?"
"My subscription is not working."
"What happened to my plan?"
```

---

## `ACCOUNT_ISSUE`

Represents problems with:

* account access;
* profile management;
* authentication state;
* account settings.

Examples include:

```text
"I cannot log in."
"I am locked out of my account."
"I cannot update my account details."
```

---

## `RETURN_EXCHANGE`

Represents requests concerning:

* returning purchased items;
* exchanging purchased items;
* return eligibility;
* exchange eligibility;
* return procedures;
* exchange procedures;
* return/exchange conditions;
* return/exchange status.

Examples include:

```text
"Can I return this item?"
"I want to exchange this for another size."
"How do I send this product back?"
```

---

## `PRIVACY_SECURITY`

Represents concerns involving:

* privacy;
* security;
* suspicious access;
* credentials;
* personal data;
* account compromise.

Examples include:

```text
"Someone may have accessed my account."
"How is my personal data used?"
"I think my account has been compromised."
```

---

## `GENERAL_QUESTION`

Represents supported informational questions about the company, service, or policies that do not fit a more specific canonical intent.

A key characteristic is:

> This intent requires trusted knowledge retrieval.

Examples include:

```text
"What payment methods do you accept?"
"What are your support hours?"
"How does your service work?"
```

This distinction is important because `GENERAL_QUESTION` is still within the supported customer-service domain but does not correspond to a specialized operational intent.

---

## `CONVERSATIONAL`

Represents ordinary customer-support conversation that does not require company facts, policy retrieval, operational lookup, or business action.

This includes:

* greetings;
* thanks;
* goodbyes;
* questions about what support topics the assistant can handle.

Examples include:

```text
"Hello!"
"Thank you for your help."
"What types of help can I get from you?"
"Goodbye."
```

This category is therefore distinct from `GENERAL_QUESTION`.

For example:

```text
"What are your support hours?"
```

requires company information and belongs to `GENERAL_QUESTION`.

Whereas:

```text
"What types of help can I get from you?"
```

is conversational and does not require company-policy retrieval.

---

## `OUT_OF_SCOPE`

Represents requests unrelated to the supported customer-service domain.

Examples of out-of-scope requests include:

* general trivia;
* programming help;
* unrelated professional advice;
* creative writing;
* unrelated questions.

Examples include:

```text
"Write a sorting algorithm for me."
"Who won the football match yesterday?"
"Write a poem about the ocean."
"Help me solve my mathematics homework."
```

This provides an explicit boundary for the customer-support assistant.

---

## `UNKNOWN`

Represents a request whose customer goal cannot be reliably mapped to any supported canonical intent.

Examples include:

```text
"I need help with something else."
"This does not match any supported request."
"I am not sure how to describe my problem."
```

`UNKNOWN` should be understood as a classification uncertainty/fallback category rather than a business domain.

---

# Public Registry

The internal dictionary is exposed through:

```python
INTENT_DEFINITIONS
```

It is wrapped using:

```python
MappingProxyType
```

so consumers receive a read-only mapping rather than the mutable underlying dictionary.

Conceptually:

```text
_INTENT_DEFINITIONS
        │
        ▼
MappingProxyType
        │
        ▼
INTENT_DEFINITIONS
```

This prevents consumers from accidentally mutating the canonical taxonomy at runtime.

---

# `get_intent_definition()`

The helper:

```python
get_intent_definition(
    intent: IntentType
) -> IntentDefinition
```

retrieves the canonical definition for an intent.

It first validates that the argument is an `IntentType`.

An invalid type produces:

```text
TypeError
```

with the received type name included in the error message.

For valid values, the function returns:

```python
INTENT_DEFINITIONS[intent]
```

---

# `validate_intent_definitions()`

This function verifies that the taxonomy and its definition registry cannot drift apart.

Its central invariant is:

```text
Every IntentType
        ⇔
Exactly one IntentDefinition
```

The function compares:

```python
canonical_intents = set(IntentType)
defined_intents = set(INTENT_DEFINITIONS)
```

and calculates:

```text
missing
unexpected
```

---

# Registry Consistency Checks

The validation function checks several invariants.

## 1. No missing definitions

Every enum member must have a corresponding `IntentDefinition`.

If an enum member is added without a definition, validation fails.

For example, adding:

```python
IntentType.NEW_INTENT
```

without adding:

```python
_INTENT_DEFINITIONS[IntentType.NEW_INTENT]
```

causes validation failure.

---

## 2. No unexpected definitions

The registry must not contain an intent key that is absent from `IntentType`.

This protects against stale or orphaned definitions.

---

## 3. Registry keys must be `IntentType`

Every registry key must actually be an `IntentType`.

Otherwise validation raises a `RuntimeError`.

---

## 4. Registry values must be `IntentDefinition`

Every value must be an `IntentDefinition`.

Otherwise validation fails.

---

## 5. Definition key/value identity must match

For every entry:

```python
definition.intent is intent
```

must be true.

This catches situations where the dictionary key says one intent but the stored definition describes another.

For example, this inconsistency would be rejected:

```text
key:
    IntentType.REFUND_REQUEST

definition.intent:
    IntentType.PAYMENT_ISSUE
```

---

# `_intent_name()`

`_intent_name()` is a small internal formatting helper used when constructing validation error messages.

If the value is an `IntentType`, it returns:

```python
value.value
```

Otherwise it falls back to:

```python
str(value)
```

This keeps consistency errors readable without coupling error formatting to assumptions about the object type.

---

# Taxonomy Integrity Model

The package enforces the following relationship:

```text
                  IntentType
                     │
                     │ exactly one
                     ▼
              IntentDefinition
                 │         │
                 ▼         ▼
            description   examples
```

And the registry enforces:

```text
IntentType set
      =
IntentDefinition key set
```

while each entry additionally satisfies:

```text
registry_key
      =
definition.intent
```

---

# Classification Boundary

The taxonomy establishes a clear distinction between different types of customer interaction.

For example:

```text
Refund problem
    → REFUND_REQUEST

Payment failed
    → PAYMENT_ISSUE

Where is my order?
    → ORDER_STATUS

Package delayed
    → SHIPPING_ISSUE

Cancel my order
    → CANCELLATION

Subscription renewed unexpectedly
    → SUBSCRIPTION_ISSUE

Cannot log in
    → ACCOUNT_ISSUE

Return this product
    → RETURN_EXCHANGE

Account may be compromised
    → PRIVACY_SECURITY

What payment methods do you accept?
    → GENERAL_QUESTION

Hello / Thanks / Goodbye
    → CONVERSATIONAL

Write a sorting algorithm
    → OUT_OF_SCOPE

Unclear unsupported goal
    → UNKNOWN
```

The definitions and examples in `taxonomy.py` provide the authoritative semantics for these distinctions.

---

# Relationship With Downstream Components

The taxonomy should be viewed as a **semantic contract** consumed by other AI components.

A typical flow is:

```text
Customer Message
       │
       ▼
Intent Classifier
       │
       ▼
IntentType
       │
       ▼
IntentDefinition
       │
       ├──────────────► Retrieval
       │
       ├──────────────► Decision / Routing
       │
       └──────────────► Response Generation
```

The taxonomy itself should remain unaware of those downstream consumers.

This keeps semantic classification independent from implementation-specific workflow behavior.

---

# Persistence Considerations

The enum values are explicitly described as stable identifiers that may appear in:

* telemetry;
* evaluation datasets;
* dashboards;
* historical AI runs.

Therefore changing an existing canonical value can have compatibility consequences beyond the Python code itself.

For example:

```python
REFUND_REQUEST = "refund_request"
```

should not casually become:

```python
REFUND_REQUEST = "refund"
```

because historical records may already contain:

```text
refund_request
```

---

# Adding a New Intent

When adding a new canonical intent, the expected sequence is:

## Step 1 — Add the enum value

Add a new `IntentType` member with a stable canonical value.

Example:

```python
NEW_INTENT = "new_intent"
```

The value should be chosen as a durable semantic identifier because it may be persisted externally.

---

## Step 2 — Add the definition

Add a corresponding `IntentDefinition` to `_INTENT_DEFINITIONS`.

It must contain:

```text
intent
description
examples
```

---

## Step 3 — Ensure the definition is semantically distinct

The new intent should represent a genuinely different customer goal rather than merely another wording of an existing intent.

---

## Step 4 — Add representative examples

Examples should reflect real customer phrasing and cover the semantic boundary of the new intent.

The definition validator requires at least one non-empty example.

---

## Step 5 — Validate the registry

Run:

```python
validate_intent_definitions()
```

This confirms:

```text
every enum value has a definition
no unexpected definitions exist
all keys are IntentType
all values are IntentDefinition
key and definition.intent match
```

---

## Step 6 — Update downstream classification behavior

Adding a taxonomy entry alone does not automatically guarantee correct classifier behavior.

Any classifier, prompt, evaluator, routing logic, or retrieval configuration that depends on the canonical taxonomy may also need corresponding updates.

The taxonomy itself should remain responsible only for semantic definitions.

---

# Removing an Intent

Removing an intent requires more caution than deleting an enum member.

Because canonical values may already exist in telemetry, evaluation datasets, dashboards, and historical AI runs, removal can create compatibility issues.

Before removing an intent, dependent systems and persisted data should be considered.

The registry validator will correctly identify the resulting mismatch if the enum and definitions are changed inconsistently.

---

# Renaming an Intent

There are two distinct operations:

```text
Python member rename
```

versus:

```text
canonical string value rename
```

Both can have downstream consequences.

For example:

```python
REFUND_REQUEST = "refund_request"
```

is not merely an implementation detail. The value can become part of historical records.

Therefore canonical intent values should be treated as stable API/data identifiers.

---

# Testing Expectations

Tests around this package should cover at least:

## Enum integrity

* all expected canonical intents exist;
* canonical values remain stable.

## Definition integrity

* every intent has a definition;
* every definition has a valid intent;
* every definition has a non-empty description;
* every definition has at least one example.

## Normalization

* descriptions have normalized whitespace;
* examples have normalized whitespace;
* duplicate examples are removed;
* blank examples are rejected.

## Registry integrity

* missing definitions fail;
* unexpected definitions fail;
* invalid registry key types fail;
* invalid registry value types fail;
* key/definition mismatches fail.

## Lookup behavior

* valid `IntentType` returns the correct definition;
* invalid argument types raise `TypeError`.

---

# Example Registry Lookup

A consumer can conceptually perform:

```python
definition = get_intent_definition(IntentType.REFUND_REQUEST)
```

and receive the canonical semantic definition containing:

```text
intent
description
examples
```

The caller should use that definition for semantic understanding rather than reimplementing intent descriptions independently.

---

# Immutability and Safety

There are multiple layers of immutability:

```text
IntentDefinition
    frozen=True

INTENT_DEFINITIONS
    MappingProxyType
```

This prevents accidental runtime modification of the taxonomy through normal consumers.

The underlying private dictionary remains an implementation detail.

Consumers should use:

```python
INTENT_DEFINITIONS
```

and:

```python
get_intent_definition()
```

rather than directly depending on `_INTENT_DEFINITIONS`.

---

# Error Behavior Summary

| Condition                                       | Behavior                                |
| ----------------------------------------------- | --------------------------------------- |
| `IntentDefinition.intent` is not `IntentType`   | `TypeError`                             |
| Description is not a string                     | `TypeError`                             |
| Description becomes empty after normalization   | `ValueError`                            |
| Examples is not a tuple                         | `TypeError`                             |
| Example is not a string                         | `TypeError`                             |
| Example becomes empty after normalization       | `ValueError`                            |
| No examples provided                            | `ValueError`                            |
| `get_intent_definition()` receives invalid type | `TypeError`                             |
| Enum contains undefined intent                  | `RuntimeError` from registry validation |
| Registry contains unexpected intent             | `RuntimeError`                          |
| Registry key has wrong type                     | `RuntimeError`                          |
| Registry value has wrong type                   | `RuntimeError`                          |
| Definition/key mismatch                         | `RuntimeError`                          |

These behaviors are implemented directly in `taxonomy.py`.

---

# Component Map

```text
intent/
│
├── taxonomy.py
│   │
│   ├── IntentType
│   │   └── Canonical intent identifiers
│   │
│   ├── IntentDefinition
│   │   └── Semantic definition + examples
│   │
│   ├── _INTENT_DEFINITIONS
│   │   └── Internal canonical registry
│   │
│   ├── INTENT_DEFINITIONS
│   │   └── Read-only public registry
│   │
│   ├── get_intent_definition()
│   │   └── Definition lookup
│   │
│   ├── validate_intent_definitions()
│   │   └── Registry integrity validation
│   │
│   └── _intent_name()
│       └── Error-message helper
│
└── README.md
    └── Package documentation
```

---

# Summary

The `intent` package is the **canonical semantic vocabulary** for the AI customer-support agent.

Its central contract is:

```text
IntentType
    ↓
stable semantic identifier

IntentDefinition
    ↓
meaning + representative examples

INTENT_DEFINITIONS
    ↓
immutable canonical registry

validate_intent_definitions()
    ↓
taxonomy consistency guarantee
```

The package deliberately stops at semantic classification.

It defines **what an intent means**, while downstream components determine:

```text
what to retrieve,
what workflow to execute,
what action to take,
how to respond,
and how to route the request.
```

This separation keeps the taxonomy stable, reusable, testable, and safe to persist across telemetry, evaluations, dashboards, and historical AI runs.
