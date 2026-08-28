from __future__ import annotations
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, TypeVar
import groq
from groq import Groq
from pydantic import BaseModel, ValidationError

from packages.ai.providers.base import LLMProvider
from packages.ai.providers.errors import LLMProviderAuthenticationError, LLMProviderError, LLMProviderRateLimitError
from packages.ai.providers.errors import LLMProviderResponseError, LLMProviderTimeoutError, LLMProviderUnavailableError
from packages.ai.providers.types import LLMResponse, ProviderMetadata, StructuredLLMResponse, TokenUsage

T = TypeVar("T", bound=BaseModel)

@dataclass(frozen=True, slots=True)
class GroqProviderConfig:
    """
    Runtime configuration for the Groq provider adapter.

    Retry policy is intentionally disabled at the SDK layer.
    A dedicated resilience layer will own retries/backoff.
    """

    api_key: str
    model: str
    timeout_seconds: float = 30.0
    max_completion_tokens: int = 1024
    temperature: Decimal = Decimal("0")
    structured_output_strict: bool = False

    def __post_init__(self) -> None:
        api_key = self.api_key.strip()

        if not api_key:
            raise ValueError("api_key cannot be empty")

        model = self.model.strip()
        if not model:
            raise ValueError("model cannot be empty")

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        if isinstance(self.max_completion_tokens, bool) or not isinstance(self.max_completion_tokens, int):
            raise TypeError("max_completion_tokens must be an integer")

        if self.max_completion_tokens <= 0:
            raise ValueError("max_completion_tokens must be greater than zero")

        if not isinstance(self.temperature, Decimal):
            raise TypeError("temperature must be Decimal")

        if not (Decimal("0") <= self.temperature <= Decimal("2")):
            raise ValueError("temperature must be between 0 and 2")

        object.__setattr__(self, "api_key", api_key)
        object.__setattr__(self, "model", model)


class GroqProvider(LLMProvider):
    """
    Groq implementation of the provider-neutral LLMProvider contract.

    Responsibilities:
    - invoke Groq Chat Completions
    - normalize responses into our provider contracts
    - normalize token usage
    - validate structured responses with Pydantic
    - translate Groq SDK exceptions into provider-neutral errors

    Explicitly NOT responsible for:
    - persistence
    - telemetry timing
    - retry/backoff policy
    - model pricing
    - intent classification logic
    """
    PROVIDER_NAME = "groq"

    def __init__(self, *, config: GroqProviderConfig, client: Groq | None = None) -> None:
        if not isinstance(config, GroqProviderConfig):
            raise TypeError("config must be GroqProviderConfig")

        self._config = config

        # Dependency injection of client makes provider unit-testable.
        self._client = client or Groq(api_key=config.api_key, timeout=config.timeout_seconds,max_retries=0)
        # retries belong to resilience layer, not hidden SDK logic.

    # Identity
    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    @property
    def model_name(self) -> str:
        return self._config.model

    # Text generation
    def generate(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        self._validate_prompts(system_prompt=system_prompt, user_prompt=user_prompt)

        try:
            completion = (
                self._client.chat.completions.create(
                    model=self._config.model,
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": user_prompt,
                        },
                    ],
                    temperature=float(self._config.temperature),
                    max_completion_tokens=self._config.max_completion_tokens,
                )
            )

        except Exception as exc:
            self._translate_exception(exc)

        choice = self._first_choice(completion)
        content = choice.message.content
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message="Groq returned an empty text response.",
                metadata=self._response_metadata(completion),
            )

        return LLMResponse(
            content=content,
            provider=self.PROVIDER_NAME,
            model=self._response_model(completion),
            usage=self._extract_usage(completion),
            metadata=ProviderMetadata(
                provider_request_id=self._response_id(completion),
                finish_reason=choice.finish_reason,
                raw_model_name=self._response_model(completion),
            ),

            # Pricing should eventually be calculated by a versioned
            # pricing service rather than hardcoded in a provider adapter.
            estimated_cost_usd=None,
        )

    # Structured generation
    def generate_structured(self, *, system_prompt: str, user_prompt: str, response_model: type[T]) -> StructuredLLMResponse[T]:
        self._validate_prompts(system_prompt=system_prompt, user_prompt=user_prompt)

        if not isinstance(response_model, type) or not issubclass(response_model, BaseModel):
            raise TypeError("response_model must be a Pydantic BaseModel subclass")

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": self._schema_name(response_model),
                "strict": (self._config.structured_output_strict),
                "schema": (response_model.model_json_schema()),
            },
        }

        try:
            completion = self._client.chat.completions.create(
                    model=self._config.model,
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": user_prompt,
                        },
                    ],
                    temperature=float(self._config.temperature),
                    max_completion_tokens=self._config.max_completion_tokens,
                    response_format=response_format,
            )

        except Exception as exc:
            self._translate_exception(exc)

        choice = self._first_choice(completion)
        content = choice.message.content
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message="Groq returned an empty structured response.",
                metadata=self._response_metadata(completion),
            )

        try:
            raw_payload = json.loads(content)
            
        except json.JSONDecodeError as exc:
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message="Groq returned malformed JSON.",
                metadata=self._response_metadata(completion)
            ) from exc

        try:
            output = response_model.model_validate(raw_payload)

        except ValidationError as exc:
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message=f"Groq structured response did not satisfy {response_model.__name__}.",
                metadata=self._response_metadata(completion),
            ) from exc

        return StructuredLLMResponse(
            output=output,
            provider=self.PROVIDER_NAME,
            model=self._response_model(completion),
            usage=self._extract_usage(completion),
            metadata=ProviderMetadata(
                provider_request_id=self._response_id(completion),
                finish_reason=choice.finish_reason,
                raw_model_name=self._response_model(completion),
            ),
            estimated_cost_usd=None,
        )

    # Health
    def health_check(self) -> bool:
        """
        Verify provider connectivity/authentication.

        Health checks deliberately do not use InstrumentedLLMProvider,
        therefore they do not create ai.llm_calls records.
        """

        try:
            self._client.models.list()
            return True

        except groq.APIError:
            return False
        except Exception:
            return False

    # Groq response normalization
    @staticmethod
    def _first_choice(completion: Any) -> Any:
        choices = getattr(completion, "choices", None)
        if not choices:
            raise LLMProviderResponseError(provider="groq", message="Groq response contained no choices.")

        return choices[0]

    @staticmethod
    def _extract_usage(completion: Any) -> TokenUsage:
        usage = getattr(completion, "usage", None)
        if usage is None:
            # Not every provider response is guaranteed to expose usage.
            # Missing telemetry must not fabricate token values.
            return TokenUsage()

        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        cached_tokens = 0
        
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        if prompt_details is not None:
            cached_tokens = int(getattr(prompt_details, "cached_tokens", 0) or 0)

        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_tokens,
        )

    @staticmethod
    def _response_id(completion: Any) -> str | None:
        value = getattr(completion, "id", None)
        if not isinstance(value, str):
            return None

        normalized = value.strip()
        return normalized or None

    def _response_model(self, completion: Any) -> str:
        value = getattr(completion, "model", None)
        if isinstance(value, str) and value.strip():
            return value.strip()

        return self._config.model

    @staticmethod
    def _response_metadata(completion: Any) -> dict[str, Any]:
        response_id = getattr(completion, "id", None)

        return { "provider_request_id": response_id if isinstance(response_id, str) else None }

    # Error translation
    def _translate_exception(self, exc: Exception, ) -> None:
        metadata = self._exception_metadata(exc)
        if isinstance(exc, groq.APITimeoutError):
            raise LLMProviderTimeoutError(provider=self.PROVIDER_NAME, message="Groq request timed out.", metadata=metadata) from exc

        if isinstance(exc, groq.RateLimitError):
            raise LLMProviderRateLimitError(provider=self.PROVIDER_NAME, metadata=metadata) from exc

        if isinstance(exc, (groq.AuthenticationError, groq.PermissionDeniedError,)):
            raise LLMProviderAuthenticationError(provider=self.PROVIDER_NAME, metadata=metadata) from exc

        if isinstance(exc, (groq.APIConnectionError, groq.InternalServerError,)):
            raise LLMProviderUnavailableError(provider=self.PROVIDER_NAME, metadata=metadata) from exc

        if isinstance(exc, (groq.BadRequestError, groq.UnprocessableEntityError,)):
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message="Groq rejected the model request or structured-response schema.",
                metadata=metadata,
            ) from exc

        if isinstance(exc, groq.APIError):
            raise LLMProviderError(
                provider=self.PROVIDER_NAME,
                message="Groq provider request failed.",
                error_code="GROQ_API_ERROR",
                retryable=False,
                metadata=metadata,
            ) from exc

        # Unexpected SDK/programming errors remain visible as
        # implementation defects rather than being mislabeled as an
        # external provider outage.
        raise exc

    @staticmethod
    def _exception_metadata(exc: Exception) -> dict[str, Any]:
        metadata: dict[str, Any] = { "exception_type": type(exc).__name__ }
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            metadata["http_status_code"] = status_code

        response = getattr(exc, "response", None)
        if response is not None:
            headers = getattr(response, "headers", None)
            if headers is not None:
                request_id = headers.get("x-request-id") or headers.get("request-id")
                if request_id:
                    metadata["provider_request_id"] = str(request_id)

        return metadata

    # Input validation
    @staticmethod
    def _validate_prompts(*, system_prompt: str, user_prompt: str) -> None:
        if not isinstance(system_prompt, str):
            raise TypeError("system_prompt must be a string")

        if not isinstance(user_prompt, str):
            raise TypeError("user_prompt must be a string")

        if not system_prompt.strip():
            raise ValueError("system_prompt cannot be empty")

        if not user_prompt.strip():
            raise ValueError("user_prompt cannot be empty")

    @staticmethod
    def _schema_name(response_model: type[BaseModel]) -> str:
        """
        Generate a stable API-safe schema identifier.
        """
        name = response_model.__name__
        normalized = "".join(char.lower() if char.isalnum() else "_" for char in name)
        return normalized[:64]