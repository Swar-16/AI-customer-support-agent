# LLM Providers

## Overview

The `packages/ai/providers` package provides the **provider-agnostic abstraction layer** for Large Language Models (LLMs) used across the AI customer-support system.

It insulates application use cases, intent classifiers, decision engines, and response generation services from vendor-specific SDKs, HTTP protocols, error models, and wire formats.

```text
Orchestration / Intent / Generation
                 │
                 ▼
      LLMProvider Interface
                 │
  ┌──────────────┼──────────────┐
  ▼              ▼              ▼
GeminiProvider  GroqProvider  MockLLMProvider
(Google AI)      (Groq)        (In-memory test)
```

The package also provides layered decorators for:
1. **Capacity limiting and pacing** (`CapacityLimitedLLMProvider`)
2. **Resilience, retries, and jitter** (`ResilientLLMProvider`)
3. **Audit, lifecycle, and telemetry recording** (`InstrumentedLLMProvider`)

---

# Architecture and Layering

Every outgoing LLM interaction passes through a structured composition pipeline:

```text
Application Request
        │
        ▼
InstrumentedLLMProvider
  ├── Records call start/end timestamp
  ├── Captures input/output token usage
  ├── Associates call with logical ai_run_id
  └── Captures vendor request IDs and error codes
        │
        ▼
ResilientLLMProvider
  ├── Catches transient errors (timeouts, 503s, 429s)
  ├── Applies exponential backoff with jitter
  └── Honors maximum retry thresholds
        │
        ▼
CapacityLimitedLLMProvider
  ├── Enforces process-local concurrency limits (e.g., max 2)
  ├── Implements queue timeouts
  └── Enforces minimum start interval spacing (e.g., 1.0s for free-tier rate limits)
        │
        ▼
Base LLM Provider (GeminiProvider / GroqProvider / MockLLMProvider)
  ├── Constructs vendor HTTP payload
  ├── Sanitizes response schemas
  ├── Dispatches HTTP request
  └── Normalizes vendor response & errors into canonical types
```

---

# Package Structure

```text
packages/ai/providers/
├── base.py                 # Abstract LLMProvider interface
├── types.py                # Normalized LLMResponse, StructuredLLMResponse, TokenUsage
├── errors.py               # Canonical exception hierarchy (LLMProviderError, etc.)
├── gemini.py               # Google Gemini REST provider (gemini-3.5-flash-lite)
├── groq.py                 # Groq cloud provider (openai/gpt-oss-20b, llama3)
├── mock.py                 # Deterministic in-memory provider for tests
├── capacity_limited.py     # Concurrency and start-interval rate limiting decorator
├── resilient.py            # Retry, backoff, and transient error recovery decorator
├── instrumented.py         # Request-scoped telemetry and usage recording decorator
└── README.md               # Package documentation
```

---

# Core Contracts

## 1. `LLMProvider` (`base.py`)

All provider implementations satisfy the `LLMProvider` abstract base class:

```python
class LLMProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Canonical provider identifier (e.g. 'gemini', 'groq', 'mock')."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Configured model name (e.g. 'gemini-3.5-flash-lite')."""
        ...

    @abstractmethod
    def generate(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        """Generate unstructured text with normalized metadata and token usage."""
        ...

    @abstractmethod
    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> StructuredLLMResponse[T]:
        """Generate output validated against a Pydantic schema model."""
        ...
```

## 2. Normalized Response Models (`types.py`)

* `LLMResponse`: Contains raw `content`, `metadata: ProviderMetadata`, and `usage: TokenUsage`.
* `StructuredLLMResponse[T]`: Contains validated `data: T`, `raw_content: str`, `metadata`, and `usage`.
* `TokenUsage`: Normalized `prompt_tokens`, `completion_tokens`, and `total_tokens`.
* `ProviderMetadata`: Contains `provider_name`, `model_name`, `finish_reason`, `latency_ms`, and optional `provider_request_id`.

## 3. Canonical Error Taxonomy (`errors.py`)

All vendor-specific HTTP and network errors are caught and converted into standard exception types:

| Exception | Condition | Retryable? |
|---|---|---|
| `LLMProviderAuthenticationError` | 401 Unauthorized, 403 Forbidden | No |
| `LLMProviderRateLimitError` | 429 Too Many Requests | Yes |
| `LLMProviderUnavailableError` | 503 Service Unavailable, 502/504 Gateway errors | Yes |
| `LLMProviderTimeoutError` | Socket read/connect timeout | Yes |
| `LLMProviderResponseError` | Unparseable or schema-violating JSON from model | No |
| `LLMProviderError` | Base class for all provider failures | Varies |

---

# Supported Providers

## Google Gemini (`gemini.py`)

The `GeminiProvider` provides native HTTP REST integration with the Google AI Studio / Gemini API (`v1beta`).

### Highlights:
* **Recommended Default Model**: `gemini-3.5-flash-lite` (fast, economical, reliable).
* **Wire Protocol**: Standard REST via `httpx.Client` to `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`.
* **API Key Authentication**: Delivered securely via `x-goog-api-key` HTTP header.
* **OpenAPI 3.0 Schema Sanitization**: The Google AI Studio REST endpoint rejects JSON Schema Draft 2020-12 constructs such as `$defs`, `additionalProperties`, `$schema`, and nullable `anyOf: [{"type": "null"}, ...]` unions. `GeminiProvider._clean_schema_for_gemini()` inlines `$defs`, collapses nullable `anyOf` unions into OpenAPI 3.0 `nullable: true`, and removes unsupported fields before transmitting `responseSchema`.
* **Token Accounting**: Maps `promptTokenCount` and `candidatesTokenCount` from the Gemini response metadata to `TokenUsage`.
* **Error Translation**: Translates Google AI Studio JSON errors (e.g. `RESOURCE_EXHAUSTED` -> `LLMProviderRateLimitError`, `UNAVAILABLE` -> `LLMProviderUnavailableError`).

### Structured Generation Flow:

```text
Pydantic Model (e.g. IntentResult, GroundedGenerationResult)
      │
      ▼ model_json_schema()
Raw JSON Schema (contains $defs, anyOf null unions, additionalProperties, $schema)
      │
      ▼ _clean_schema_for_gemini()
Sanitized OpenAPI 3.0 Schema (nullable: true, Google AI Studio REST compatible)
      │
      ▼
POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent
  ├── Header: x-goog-api-key: <KEY>
  ├── system_instruction: <SYSTEM PROMPT>
  ├── contents: [{ role: "user", parts: [{ text: <USER PROMPT> }] }]
  └── generationConfig: { responseMimeType: "application/json", responseSchema: <SANITIZED_SCHEMA> }
      │
      ▼
Gemini HTTP Response (200 OK)
  ├── candidates[0].content.parts[0].text (JSON string)
  ├── usageMetadata (promptTokenCount, candidatesTokenCount)
      │
      ▼ Pydantic Validation & Token Normalization
StructuredLLMResponse[T]
```

### Configuration (`GeminiProviderConfig`):
```python
@dataclass(frozen=True, slots=True)
class GeminiProviderConfig:
    api_key: str
    model: str = "gemini-3.5-flash-lite"
    timeout_seconds: float = 30.0
    max_completion_tokens: int = 1024
    temperature: Decimal = Decimal("0")
```

---

## Groq Cloud (`groq.py`)

The `GroqProvider` provides fast inference using Groq's OpenAI-compatible REST API.

### Configuration (`GroqProviderConfig`):
* `api_key`: Groq API token.
* `model`: Default `openai/gpt-oss-20b` or Llama 3 variants.
* `timeout_seconds`: Request timeout.
* `structured_output_strict`: Enables JSON mode or structured outputs.

---

## Mock Provider (`mock.py`)

`MockLLMProvider` is an in-memory, deterministic provider used by unit and integration tests. It can simulate pre-canned responses, structured outputs, simulated latency, and injected errors without making outbound network calls or consuming API quotas.

---

# Capacity Limitation & Rate Pacing (`capacity_limited.py`)

Free and standard tiers of external AI APIs enforce strict requests-per-minute (RPM) and concurrency limits.

```text
Request arrives at CapacityLimitedLLMProvider
           │
           ▼
Acquire queue semaphore (timeout = ai_provider_queue_timeout_seconds)
           │
           ├── Timeout exceeded? ──► Raise LLMProviderTimeoutError
           │
           ▼ Acquired
Check time since last request start
           │
           ├── elapsed < minimum_start_interval_seconds (e.g., 1.0s)?
           │      └── sleep(minimum_start_interval_seconds - elapsed)
           │
           ▼
Record current timestamp as last_start_time
           │
           ▼
Execute underlying provider call
           │
           ▼
Release semaphore
```

`CapacityLimitedLLMProvider` protects the application from hitting provider rate limits through two mechanisms:
1. **Process-Local Semaphore**: Bounds active concurrent requests (`ai_provider_max_concurrency`).
2. **Start-Rate Pacing (`minimum_start_interval_seconds`)**: Ensures a minimum time delay between starting subsequent HTTP calls (e.g., 1.0s for Google AI Studio), preventing burst 503 / 429 errors during multi-turn or rapid test executions.

---

# Resilience & Retries (`resilient.py`)

`ResilientLLMProvider` wraps any provider with automated retry policies:

```text
Attempt Provider Call (attempt = 1)
           │
           ├── Success ────────► Return Response
           │
           ▼ Exception caught
Is exception retryable? (RateLimit, Unavailable, Timeout)
           │
           ├── No ─────────────► Raise immediately (e.g., AuthenticationError, ResponseError)
           │
           ▼ Yes
Have we exceeded max_retries (e.g., 3)?
           │
           ├── Yes ────────────► Re-raise exception
           │
           ▼ No
Calculate delay = base_delay * (2 ** (attempt - 1)) + random_jitter
Sleep for calculated delay
Increment attempt and retry
```

* Recognizes retryable exceptions (`LLMProviderRateLimitError`, `LLMProviderUnavailableError`, `LLMProviderTimeoutError`).
* Applies truncated exponential backoff with full randomized jitter to prevent thundering herd problems.
* Configurable `max_retries` (default 3) and `base_delay_seconds` (default 1.5s).

---

# Telemetry & Instrumentation (`instrumented.py`)

`InstrumentedLLMProvider` wraps provider calls within a request scope:

```text
Start LLM Call
      │
      ├── Capture monotonic start timestamp
      │
      ▼
Invoke Provider (Resilient -> CapacityLimited -> Base)
      │
      ├── Success: capture finish timestamp, token usage, finish reason
      │
      └── Exception: capture finish timestamp, error class, error message
      │
      ▼
Publish to LLMCallRecorder
  ├── purpose: intent_classification / answer_generation / title_generation
  ├── ai_run_id: request tracking UUID
  ├── duration_ms: total execution latency
  ├── usage: prompt, completion, total tokens
  └── provider_metadata: model, provider, request_id
```

* Records provider start, end, duration, and token usage into an `LLMCallRecorder`.
* Associates each call with the current `ai_run_id` and semantic `purpose` (`intent_classification`, `answer_generation`, `title_generation`).
* Feeds into the audit trail and operations dashboard without logging customer sensitive payloads.
