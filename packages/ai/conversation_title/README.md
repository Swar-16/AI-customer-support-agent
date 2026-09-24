# Conversation Title Generation

## Overview

The `conversation_title` package provides the conversation-title generation subsystem for the AI customer-support agent.

Its responsibility is to generate a **short, safe, privacy-conscious title** for a customer-support conversation based primarily on the customer's first message. The subsystem can use an LLM provider to generate a natural title, but title generation is deliberately treated as **non-critical business functionality**: provider failures, malformed responses, privacy violations, and unsafe generated content fall back to deterministic titles.

The package is located at:

```text
packages/ai/conversation_title/
```

The package exposes the title-generation models, prompt construction, sanitization, deterministic fallback logic, and the main `ConversationTitleGenerator` through its package interface.

---

## Responsibilities

The subsystem is responsible for:

* Generating concise conversation titles from the first customer message.
* Preventing customer-sensitive information from being sent to the LLM unnecessarily.
* Treating customer-provided text as **untrusted data**.
* Redacting obvious credentials, identifiers, tokens, URLs, and other sensitive values before provider invocation.
* Bounding the amount of customer text sent to the provider.
* Requesting structured provider output.
* Sanitizing provider-generated titles before they can be persisted or returned.
* Rejecting titles containing sensitive identifiers or prompt-injection language.
* Enforcing the final 80-character title limit.
* Providing deterministic category-based fallback titles.
* Recording only low-cardinality operational metadata when the fallback path is used.
* Ensuring provider failures do not make conversation creation dependent on LLM availability.

The design intentionally separates **generation**, **privacy preprocessing**, **output validation**, **fallback behavior**, and **data models** into separate components.

---

## Package Structure

```text
conversation_title/
├── __init__.py
├── fallback.py
├── generator.py
├── models.py
├── prompts.py
└── sanitizer.py
```

### Component responsibilities

| File           | Responsibility                                                                           |
| -------------- | ---------------------------------------------------------------------------------------- |
| `__init__.py`  | Public package API and exports                                                           |
| `models.py`    | Title-related domain models, constants, and output contracts                             |
| `prompts.py`   | Prompt construction, input normalization, sensitive-data redaction, and input truncation |
| `sanitizer.py` | Deterministic validation and sanitization of provider-generated titles                   |
| `fallback.py`  | Deterministic privacy-conscious title generation                                         |
| `generator.py` | Orchestration of provider generation, sanitization, fallback, and operational logging    |

---

# Architecture

The package follows a defensive pipeline:

```text
Customer Message
      │
      ▼
ConversationTitleGenerator
      │
      ├──────────────► ConversationTitleFallback
      │                 └── deterministic fallback result
      │
      ▼
ConversationTitlePromptBuilder
      │
      ├── normalize text
      ├── redact sensitive values
      ├── truncate input
      └── build untrusted JSON payload
      │
      ▼
LLMProvider
      │
      ├── provider failure ───────────────► fallback
      │
      ▼
Provider Response
      │
      ▼
ConversationTitleSanitizer
      │
      ├── unsafe/invalid ────────────────► fallback
      │
      ▼
ConversationTitleResult
      │
      ├── source = provider
      └── safe title
```

The fallback is computed early so that a deterministic result is already available if the provider path fails.

---

# Public API

The package's public exports include:

* `ConversationTitleOutput`
* `ConversationTitleResult`
* `ConversationTitleSource`
* `GENERATED_TITLE_MAX_LENGTH`
* `ConversationTitleSanitizer`
* `ConversationTitleFallback`
* `CONVERSATION_TITLE_PROMPT_VERSION`
* `ConversationTitlePrompt`
* `ConversationTitlePromptBuilder`
* `ConversationTitleGenerator`

These are explicitly re-exported from `__init__.py`.

Typical consumers can therefore import the primary subsystem components from the package rather than depending directly on individual implementation modules.

---

# Data Models

## `models.py`

`models.py` defines the contracts used throughout the title-generation pipeline.

The module defines two important title length limits:

```python
GENERATED_TITLE_MAX_LENGTH = 80
PROVIDER_TITLE_MAX_LENGTH = 500
```

The provider boundary intentionally accepts a larger value than the final persisted title contract. The sanitizer is responsible for transforming the provider response into the final bounded title.

---

## `ConversationTitleSource`

`ConversationTitleSource` is a `StrEnum` describing where the final title originated:

```text
provider
fallback
```

The values are deliberately low-cardinality and safe for telemetry/audit metadata because they do not contain customer-authored content.

---

## `ConversationTitleOutput`

`ConversationTitleOutput` is the structured output contract requested from the LLM provider.

It is a Pydantic model with:

* `extra="forbid"`
* automatic whitespace stripping
* a required `title`
* minimum title length of 1
* maximum provider-boundary title length of 500

The model also normalizes internal whitespace and rejects blank titles.

Importantly, successfully parsing this model **does not mean the title is safe to persist**. Provider output must still pass through `ConversationTitleSanitizer`.

---

## `ConversationTitleResult`

`ConversationTitleResult` represents the final title produced by the subsystem.

It is an immutable, slotted dataclass containing:

```python
title: str
source: ConversationTitleSource
```

Its invariants require:

* normalized single-line plain text;
* title length ≤ 80 characters;
* a valid `ConversationTitleSource`;
* no raw provider response;
* no raw customer message.

The constructor normalizes whitespace and validates the final length and source.

---

# Prompt Construction

## `prompts.py`

`ConversationTitlePromptBuilder` prepares the customer message before it reaches the LLM provider.

The current prompt version is:

```text
conversation-title-v2-plain
```

The default maximum input length is:

```text
800 characters
```

These values are defined as package-level constants.

---

## Prompt Contract

`ConversationTitlePrompt` stores the two prompts sent to the provider:

```python
system_prompt
user_prompt
```

Both must be non-empty strings.

The generated system prompt instructs the model to:

* produce one short navigation title;
* preferably use 3–8 words;
* stay within 80 characters;
* describe the support topic rather than the customer;
* return plain text;
* avoid JSON, Markdown, quotes, prefixes, labels, and explanations;
* avoid names and personal information;
* avoid URLs, credentials, secrets, payment-card data, and similar sensitive information;
* avoid order, transaction, account, ticket, invoice, subscription, case, and reference identifiers;
* use general categories when details could be sensitive.

The prompt also explicitly establishes that the supplied customer message is **untrusted data** and must not be treated as instructions.

---

# Privacy Preprocessing

Before provider invocation, the prompt builder performs several defensive transformations.

### 1. Unicode normalization

Input is normalized using Unicode NFKC normalization.

Unicode control and format characters are replaced with spaces, and whitespace is collapsed.

### 2. Sensitive-value redaction

The builder recognizes and replaces several categories of sensitive content, including:

* email addresses;
* URLs;
* UUIDs;
* JWTs;
* bearer tokens;
* passwords and other explicitly assigned secrets;
* labeled customer identifiers;
* contextual customer identifiers;
* prefixed order/transaction/payment/etc. identifiers;
* card-like numbers;
* phone-like numbers;
* long numeric identifiers.

These are replaced with category-specific redaction markers before the provider receives the content.

### 3. Input truncation

The builder limits customer text to the configured maximum input length.

If truncation occurs, it attempts to end at a whitespace boundary. If a suitable boundary would result in an excessively short prompt, it uses the configured character boundary instead.

### 4. Untrusted JSON payload

The processed message is embedded in a JSON payload containing:

```text
customer_message
data_classification = untrusted_customer_text
```

The payload is JSON encoded and explicitly described as data rather than instructions.

---

# Conversation Title Sanitization

## `sanitizer.py`

`ConversationTitleSanitizer` is the deterministic security and formatting boundary between an LLM provider and the rest of the application.

Its core rule is:

> A provider-generated title must be proven safe before it can be returned.

If the title cannot be safely validated, `sanitize()` returns `None`, allowing the caller to use the deterministic fallback.

---

## Sanitization Pipeline

The sanitizer performs the following operations:

```text
Provider Output
      │
      ▼
Unicode normalization
      │
      ▼
Control/format character removal
      │
      ▼
Whitespace normalization
      │
      ▼
Initial safety scan
      │
      ├── unsafe ──► None
      │
      ▼
Remove title prefixes
      │
      ▼
Remove Markdown prefixes/links
      │
      ▼
Remove HTML tags
      │
      ▼
Remove Markdown decoration
      │
      ▼
Strip enclosing quotes
      │
      ▼
Trim cosmetic punctuation
      │
      ▼
80-character validation
      │
      ▼
Second safety scan
      │
      ▼
Structural validation
      │
      ▼
Final title
```

The first safety scan intentionally occurs **before markup removal**, preventing sensitive data from being hidden inside Markdown links or other formatting.

---

## Formatting Cleanup

The sanitizer can remove harmless provider formatting such as:

* `Title:` prefixes;
* Markdown headings;
* Markdown list prefixes;
* Markdown links;
* HTML tags;
* Markdown emphasis/decorators;
* enclosing quotation marks;
* cosmetic punctuation surrounding the complete title.

It does not attempt to repair unsafe content.

---

## Sensitive Content Handling

Sensitive patterns include:

* email addresses;
* URLs;
* UUIDs;
* JWTs;
* bearer tokens;
* secrets;
* customer identifiers;
* prefixed business identifiers;
* card-like numbers;
* long numbers;
* phone-like numbers.

These patterns are grouped into `_SENSITIVE_PATTERNS`.

The sanitizer deliberately **rejects** sensitive output rather than partially redacting it.

This distinction is important: partial redaction could leave enough information to identify a customer, transaction, or credential.

---

## Prompt-Injection Detection

The sanitizer also detects instruction-like language such as attempts to:

* ignore previous instructions;
* reveal the system prompt;
* reference hidden instructions;
* reference developer messages;
* change the model's role.

Such output is rejected.

The title is also rejected if it contains disallowed structural characters such as:

```text
{ } [ ] < > |
```

and must contain at least one alphanumeric character.

---

# Deterministic Fallback

## `fallback.py`

`ConversationTitleFallback` produces a deterministic title without depending on an LLM.

The fallback is intentionally privacy-conscious. Rather than truncating the original customer message, it maps the request to allowlisted category titles. This prevents customer names, order IDs, account details, credentials, and similar data from leaking into navigation elements or logs.

When a canonical intent is available, the fallback prefers that intent. Keyword matching is only used when the intent is absent or unknown.

---

## Intent-Based Titles

The fallback contains an allowlist covering categories such as:

* general support;
* FAQ/general information;
* returns and exchanges;
* refunds;
* orders;
* order status;
* shipping/delivery;
* payments;
* billing;
* duplicate charges;
* subscriptions;
* cancellation;
* account access;
* account security;
* technical support;
* product information;
* complaints;
* human support/escalation.

Examples include:

```text
return / return_exchange → Return and exchange help
refund / refund_request → Refund assistance
order_status → Order status request
shipping → Shipping assistance
billing → Billing assistance
account_security → Account security help
technical → Technical support
human_support → Human support request
```

The complete mapping is maintained in `_INTENT_TITLES`.

---

## Keyword-Based Classification

If there is no recognized intent, the fallback scans the normalized customer message against ordered category patterns.

The patterns cover categories including:

1. account security
2. duplicate charges
3. refunds
4. returns/exchanges
5. payments
6. order status
7. delivery
8. orders
9. subscriptions
10. accounts
11. technical issues
12. product information
13. complaints
14. human support

The ordering is significant because specific categories should take precedence over broader categories.

For example, a message such as:

```text
Hello, I need a refund
```

should produce a refund title rather than being classified merely as a greeting. The implementation explicitly documents this behavior.

---

## Greeting and General Help

Two special patterns are handled after category matching:

* general help requests → `General support question`
* greeting-only messages → `General support`

If no category is recognized, the fallback uses:

```text
Support request
```

as the default.

---

# Main Orchestrator

## `generator.py`

`ConversationTitleGenerator` coordinates the entire subsystem.

It depends on:

```text
LLMProvider
ConversationTitlePromptBuilder
ConversationTitleSanitizer
ConversationTitleFallback
```

It also handles `LLMProviderError` explicitly.

---

## Construction

The constructor accepts:

```python
ConversationTitleGenerator(
    provider=...,
    prompt_builder=...,
    sanitizer=...,
    fallback=...,
)
```

The provider is mandatory.

The prompt builder, sanitizer, and fallback are optional and receive default implementations when omitted. The constructor validates the supplied component types rather than silently accepting invalid implementations.

---

# Generation Flow

The primary method is:

```python
generate(
    *,
    customer_message: str,
    intent: str | None = None,
) -> ConversationTitleResult
```

The input types are explicitly validated.

The generation sequence is:

### Step 1 — Generate fallback first

A deterministic fallback result is generated immediately.

This ensures that a safe result is available before the provider is contacted.

### Step 2 — Handle blank input

Blank customer messages return the fallback result immediately.

The generator records the reason as:

```text
blank_input
```

The comment notes that the normal start-message API already rejects blank input; this is defensive behavior for other callers.

### Step 3 — Build the provider prompt

The prompt builder prepares the normalized, redacted, bounded customer message.

### Step 4 — Invoke the LLM

The provider receives:

```python
system_prompt=prompt.system_prompt
user_prompt=prompt.user_prompt
```

The generator only treats `LLMProviderError` as a provider failure.

### Step 5 — Fall back on provider failure

Provider errors result in:

```text
provider_failure
```

being recorded and the previously generated deterministic fallback being returned.

### Step 6 — Sanitize provider output

The provider's response content is passed to:

```python
self._sanitizer.sanitize(response.content)
```

If sanitization returns `None`, the provider output is rejected and the deterministic fallback is returned. The recorded reason is:

```text
unsafe_or_invalid_output
```

### Step 7 — Return validated provider result

Only after successful sanitization is a provider-generated `ConversationTitleResult` returned:

```text
source = ConversationTitleSource.PROVIDER
```

---

# Failure Strategy

The subsystem distinguishes between **expected provider/runtime failures** and **programming/configuration errors**.

Provider failures are intentionally non-fatal to title generation.

However, invalid dependency implementations are not silently converted into fallback results. For example, supplying an invalid provider implementation raises during construction. This prevents configuration/programming defects from being hidden as ordinary provider failures.

Conceptually:

```text
Configuration/programming error
        │
        └──► raise

Provider/runtime failure
        │
        └──► deterministic fallback

Unsafe provider output
        │
        └──► deterministic fallback

Valid provider output
        │
        └──► provider title
```

---

# Privacy and Security Design

Privacy is a core design constraint of this package rather than an afterthought.

## Before the LLM

The prompt builder:

* normalizes the message;
* removes control/format characters;
* redacts sensitive values;
* limits input size;
* labels the customer text as untrusted data;
* excludes conversation history;
* excludes retrieved knowledge;
* excludes application hidden instructions;
* excludes previous assistant responses.

These behaviors are explicitly documented by `ConversationTitlePromptBuilder`.

## At the LLM boundary

The system prompt instructs the provider to generate only a category-oriented title and not reproduce sensitive information.

## After the LLM

The sanitizer:

* scans for sensitive values;
* detects prompt-injection language;
* removes harmless formatting;
* enforces the 80-character limit;
* rejects unsafe structures;
* rejects punctuation-only output.

Unsafe results are discarded instead of repaired.

## In fallback behavior

The fallback uses predefined category labels rather than customer-message truncation, reducing the possibility of sensitive information appearing in titles.

## In logging

Fallback logging records only low-cardinality operational metadata.

The implementation explicitly avoids logging:

* customer text;
* prompts;
* provider responses;
* exception messages.

It records the fallback reason, provider name, and model name.

---

# End-to-End Example

Given a customer message such as:

```text
Hello, I was charged twice for my order.
```

the system can proceed as follows:

```text
Customer message
      │
      ▼
PromptBuilder
      │
      ├── normalize
      ├── redact sensitive values if present
      ├── truncate if necessary
      └── construct untrusted JSON payload
      │
      ▼
LLM Provider
      │
      ▼
Potential title:
"Duplicate charge assistance"
      │
      ▼
Sanitizer
      │
      ▼
ConversationTitleResult
{
    title: "Duplicate charge assistance",
    source: "provider"
}
```

If the provider fails:

```text
LLMProviderError
      │
      ▼
Fallback
      │
      ▼
"Duplicate charge assistance"
      │
      ▼
source = fallback
```

If the provider instead returns an unsafe title containing a customer identifier, the sanitizer rejects it and the deterministic fallback is used.

---

# Component Dependency Map

```text
__init__.py
    │
    ├── models.py
    ├── sanitizer.py
    ├── fallback.py
    ├── prompts.py
    └── generator.py
             │
             ├── prompts.py
             ├── sanitizer.py
             ├── fallback.py
             ├── models.py
             └── packages.ai.providers.base
```

### Dependency direction

```text
models
  ▲
  │
prompts ─────────┐
  │              │
sanitizer ───────┤
  │              │
fallback ────────┤
  │              │
  └────── generator
               │
               ▼
           LLMProvider
```

`generator.py` is the primary orchestration layer, while the other modules provide focused responsibilities.

---

# Important Invariants

The package maintains several important invariants:

### Final title

A final `ConversationTitleResult` must:

* be a string;
* be non-empty;
* have normalized whitespace;
* be no longer than 80 characters;
* have a valid source.

### Provider output

Provider output may be up to 500 characters at the structured-output boundary, but it must subsequently pass deterministic sanitization before becoming a final title.

### Provider-generated titles

A provider title containing sensitive or instruction-like content must not be persisted.

### Fallback

The fallback must not reproduce arbitrary customer text.

### Logging

Operational logging must not expose customer-authored content, prompts, provider responses, or exception messages.

---

# Configuration Points

The primary configurable behavior visible in this package is the prompt input limit:

```python
ConversationTitlePromptBuilder(
    max_input_characters=800
)
```

The constructor requires an integer greater than zero and rejects values above 20,000.

The generator also supports dependency injection for:

* `LLMProvider`
* `ConversationTitlePromptBuilder`
* `ConversationTitleSanitizer`
* `ConversationTitleFallback`

This allows callers/tests to provide controlled implementations while retaining safe defaults.

---

# Error Handling

The package intentionally uses different mechanisms for different error classes.

| Situation                            | Behavior                     |
| ------------------------------------ | ---------------------------- |
| Invalid `customer_message` type      | `TypeError`                  |
| Invalid `intent` type                | `TypeError`                  |
| Invalid generator dependency         | `TypeError`                  |
| Blank customer message               | Deterministic fallback       |
| Provider failure                     | Deterministic fallback       |
| Unsafe provider output               | Deterministic fallback       |
| Invalid provider-generated title     | Deterministic fallback       |
| Invalid prompt-builder configuration | Constructor validation error |
| Invalid sanitizer input type         | `TypeError`                  |
| Invalid final title invariant        | `ValueError` / `TypeError`   |

This keeps expected AI/provider unreliability separate from actual application programming errors.

---

# Design Principles

The package is built around the following principles:

1. **LLM generation is optional.**
   Conversation titles must remain functional when the provider is unavailable.

2. **Privacy before convenience.**
   Customer-sensitive information is redacted before provider invocation.

3. **Untrusted input remains untrusted.**
   Customer text is explicitly labelled as data and not instructions.

4. **Validation after generation.**
   Provider output is never trusted merely because it is syntactically valid.

5. **Reject rather than partially repair sensitive output.**
   This avoids accidental information leakage.

6. **Deterministic fallback over message truncation.**
   Generic category titles are safer than exposing fragments of customer messages.

7. **Low-cardinality telemetry.**
   Operational logs contain metadata about the path taken rather than customer content.

8. **Clear separation of responsibilities.**
   Prompt construction, sanitization, fallback classification, models, and orchestration are independently implemented.

---

# Maintenance Guidance

When modifying this package:

### Changing title length

Update the final title contract in:

```text
models.py
```

and verify the sanitizer behavior remains aligned.

### Changing LLM instructions

Update:

```text
prompts.py
```

and increment the prompt version when the prompt contract changes.

### Adding sensitive-data patterns

Update the preprocessing patterns in:

```text
prompts.py
```

and the provider-output security patterns in:

```text
sanitizer.py
```

as appropriate.

### Adding fallback categories

Update:

```text
fallback.py
```

and ensure the ordering of keyword patterns still preserves more-specific categories over broad categories.

### Changing provider behavior

Update:

```text
generator.py
```

while preserving the invariant that provider failure and unsafe output remain non-fatal to title generation.

---

# Summary

The `conversation_title` package is a defensive title-generation subsystem for the AI customer-support agent.

Its architecture deliberately separates:

```text
Input protection
      ↓
Prompt construction
      ↓
LLM generation
      ↓
Output sanitization
      ↓
Validated title
```

with a deterministic fallback available throughout the process.

The central design goal is that **conversation-title generation can benefit from an LLM without making customer privacy, conversation creation, or system reliability dependent on trusting the LLM output**.
