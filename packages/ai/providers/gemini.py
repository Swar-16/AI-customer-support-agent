# AI-customer-support-agent\packages\ai\providers\gemini.py
from __future__ import annotations
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, TypeVar
import httpx
from pydantic import BaseModel, ValidationError

from packages.ai.providers.base import LLMProvider
from packages.ai.providers.errors import (
    LLMProviderAuthenticationError,
    LLMProviderError,
    LLMProviderRateLimitError,
    LLMProviderResponseError,
    LLMProviderTimeoutError,
    LLMProviderUnavailableError,
)
from packages.ai.providers.types import LLMResponse, ProviderMetadata, StructuredLLMResponse, TokenUsage

T = TypeVar("T", bound=BaseModel)

DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


@dataclass(frozen=True, slots=True)
class GeminiProviderConfig:
    """
    Runtime configuration for the Google Gemini provider adapter.

    Retry and concurrency limits are managed at the outer resilience layers.
    """

    api_key: str
    model: str = "gemini-3.5-flash-lite"
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


class GeminiProvider(LLMProvider):
    """
    Google Gemini implementation of the provider-neutral LLMProvider contract.

    Responsibilities:
    - invoke Google Gemini generateContent REST API
    - normalize responses into provider contracts
    - normalize token usage from usageMetadata
    - validate structured responses with Pydantic
    - translate HTTP/API exceptions into provider-neutral errors
    """

    PROVIDER_NAME = "gemini"

    def __init__(
        self,
        *,
        config: GeminiProviderConfig,
        client: httpx.Client | None = None,
        base_url: str = DEFAULT_GEMINI_BASE_URL,
    ) -> None:
        if not isinstance(config, GeminiProviderConfig):
            raise TypeError("config must be GeminiProviderConfig")

        self._config = config
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=config.timeout_seconds)

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

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "system_instruction": {
                "parts": [{"text": system_prompt}],
            },
            "generationConfig": {
                "temperature": float(self._config.temperature),
                "maxOutputTokens": self._config.max_completion_tokens,
            },
        }

        url = f"{self._base_url}/models/{self._config.model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._config.api_key,
        }

        try:
            response = self._client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                self._translate_http_status(response)

            data = response.json()

        except Exception as exc:
            self._translate_exception(exc)

        candidate = self._first_candidate(data)
        content = self._extract_candidate_text(candidate)

        if not isinstance(content, str) or not content.strip():
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message="Gemini returned an empty text response.",
                metadata=self._response_metadata(data, response),
            )

        finish_reason = candidate.get("finishReason")
        return LLMResponse(
            content=content,
            provider=self.PROVIDER_NAME,
            model=self._config.model,
            usage=self._extract_usage(data),
            metadata=ProviderMetadata(
                provider_request_id=self._extract_request_id(response),
                finish_reason=str(finish_reason) if finish_reason else None,
                raw_model_name=self._config.model,
            ),
            estimated_cost_usd=None,
        )

    # Structured generation
    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> StructuredLLMResponse[T]:
        self._validate_prompts(system_prompt=system_prompt, user_prompt=user_prompt)

        if not isinstance(response_model, type) or not issubclass(response_model, BaseModel):
            raise TypeError("response_model must be a Pydantic BaseModel subclass")

        clean_schema = self._clean_schema_for_gemini(response_model.model_json_schema())

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "system_instruction": {
                "parts": [{"text": system_prompt}],
            },
            "generationConfig": {
                "temperature": float(self._config.temperature),
                "maxOutputTokens": self._config.max_completion_tokens,
                "responseMimeType": "application/json",
                "responseSchema": clean_schema,
            },
        }

        url = f"{self._base_url}/models/{self._config.model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._config.api_key,
        }

        try:
            response = self._client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                self._translate_http_status(response)

            data = response.json()

        except Exception as exc:
            self._translate_exception(exc)

        candidate = self._first_candidate(data)
        content = self._extract_candidate_text(candidate)

        if not isinstance(content, str) or not content.strip():
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message="Gemini returned an empty structured response.",
                metadata=self._response_metadata(data, response),
            )

        try:
            raw_payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message="Gemini returned malformed JSON.",
                metadata=self._response_metadata(data, response),
            ) from exc

        try:
            output = response_model.model_validate(raw_payload)
        except ValidationError as exc:
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message=f"Gemini structured response did not satisfy {response_model.__name__}.",
                metadata=self._response_metadata(data, response),
            ) from exc

        finish_reason = candidate.get("finishReason")
        return StructuredLLMResponse(
            output=output,
            provider=self.PROVIDER_NAME,
            model=self._config.model,
            usage=self._extract_usage(data),
            metadata=ProviderMetadata(
                provider_request_id=self._extract_request_id(response),
                finish_reason=str(finish_reason) if finish_reason else None,
                raw_model_name=self._config.model,
            ),
            estimated_cost_usd=None,
        )

    # Health check
    def health_check(self) -> bool:
        """
        Verify Gemini API connectivity and API key validity.
        """
        try:
            url = f"{self._base_url}/models?pageSize=1"
            headers = {"x-goog-api-key": self._config.api_key}
            response = self._client.get(url, headers=headers)
            return response.status_code == 200
        except Exception:
            return False

    # Response extraction helpers
    @staticmethod
    def _first_candidate(data: dict[str, Any]) -> dict[str, Any]:
        candidates = data.get("candidates")
        if not candidates or not isinstance(candidates, list):
            raise LLMProviderResponseError(
                provider="gemini",
                message="Gemini response contained no candidates.",
            )
        return candidates[0]

    @staticmethod
    def _extract_candidate_text(candidate: dict[str, Any]) -> str:
        content = candidate.get("content")
        if not content or not isinstance(content, dict):
            return ""
        parts = content.get("parts")
        if not parts or not isinstance(parts, list):
            return ""
        text_parts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        return "".join(text_parts)

    @staticmethod
    def _extract_usage(data: dict[str, Any]) -> TokenUsage:
        usage = data.get("usageMetadata")
        if not usage or not isinstance(usage, dict):
            return TokenUsage()

        input_tokens = int(usage.get("promptTokenCount", 0) or 0)
        output_tokens = int(usage.get("candidatesTokenCount", 0) or 0)
        cached_tokens = int(usage.get("cachedContentTokenCount", 0) or 0)

        # Defensive bounds check: cached tokens cannot exceed input tokens
        if cached_tokens > input_tokens:
            cached_tokens = input_tokens

        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_tokens,
        )

    @staticmethod
    def _extract_request_id(response: Any) -> str | None:
        if response is None:
            return None
        headers = getattr(response, "headers", None)
        if headers is None:
            return None
        req_id = headers.get("x-goog-request-id") or headers.get("x-request-id")
        return str(req_id).strip() if req_id else None

    @classmethod
    def _response_metadata(cls, data: dict[str, Any], response: Any) -> dict[str, Any]:
        req_id = cls._extract_request_id(response)
        return {"provider_request_id": req_id}

    # Error translation
    def _translate_http_status(self, response: httpx.Response) -> None:
        metadata: dict[str, Any] = {"http_status_code": response.status_code}
        req_id = self._extract_request_id(response)
        if req_id:
            metadata["provider_request_id"] = req_id

        # Try to parse Gemini error response
        error_msg = response.text
        try:
            error_json = response.json()
            if isinstance(error_json, dict) and "error" in error_json:
                error_msg = error_json["error"].get("message", error_msg)
        except Exception:
            pass

        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    metadata["retry_after_seconds"] = float(str(retry_after).strip())
                except ValueError:
                    pass
            raise LLMProviderRateLimitError(provider=self.PROVIDER_NAME, metadata=metadata)

        if response.status_code in (401, 403):
            raise LLMProviderAuthenticationError(provider=self.PROVIDER_NAME, metadata=metadata)

        if response.status_code in (500, 502, 503, 504):
            raise LLMProviderUnavailableError(provider=self.PROVIDER_NAME, metadata=metadata)

        if response.status_code == 400:
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message=f"Gemini rejected the model request: {error_msg}",
                metadata=metadata,
            )

        raise LLMProviderError(
            provider=self.PROVIDER_NAME,
            message=f"Gemini provider request failed ({response.status_code}): {error_msg}",
            error_code="GEMINI_API_ERROR",
            retryable=False,
            metadata=metadata,
        )

    def _translate_exception(self, exc: Exception) -> None:
        if isinstance(exc, (LLMProviderError,)):
            raise exc

        metadata = {"exception_type": type(exc).__name__}
        if isinstance(exc, httpx.TimeoutException):
            raise LLMProviderTimeoutError(
                provider=self.PROVIDER_NAME,
                message="Gemini request timed out.",
                metadata=metadata,
            ) from exc

        if isinstance(exc, httpx.NetworkError):
            raise LLMProviderUnavailableError(
                provider=self.PROVIDER_NAME,
                message="Failed to connect to Gemini API.",
                metadata=metadata,
            ) from exc

        raise exc

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
    def _clean_schema_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
        """
        Convert Pydantic JSON schema into a format compatible with Gemini responseSchema.

        Dereferences all $defs / definitions inline, converts anyOf nullable schemas
        to OpenAPI 3.0 nullable: true, and removes fields not accepted
        by the Gemini OpenAPI schema parser (such as $defs, title, additionalProperties).
        """
        defs = schema.get("$defs", {}) or schema.get("definitions", {})

        def _resolve(node: Any) -> Any:
            if isinstance(node, dict):
                if "$ref" in node:
                    ref_key = node["$ref"].split("/")[-1]
                    if ref_key in defs:
                        resolved = dict(defs[ref_key])
                        return _resolve(resolved)

                if "anyOf" in node:
                    branches = node["anyOf"]
                    non_null = [b for b in branches if isinstance(b, dict) and b.get("type") != "null"]
                    has_null = any(isinstance(b, dict) and b.get("type") == "null" for b in branches)
                    if has_null and len(non_null) == 1:
                        target = dict(non_null[0])
                        target["nullable"] = True
                        for extra_k in ("default", "description"):
                            if extra_k in node:
                                target[extra_k] = node[extra_k]
                        return _resolve(target)

                cleaned: dict[str, Any] = {}
                for k, v in node.items():
                    if k in ("$defs", "definitions", "title", "additionalProperties", "$schema"):
                        continue
                    cleaned[k] = _resolve(v)
                return cleaned
            elif isinstance(node, list):
                return [_resolve(item) for item in node]
            return node

        return _resolve(schema)
