from __future__ import annotations
import math
from collections.abc import Sequence
from typing import Any
import httpx

from packages.knowledge.embeddings.errors import EmbeddingDimensionMismatchError, EmbeddingInputValidationError, EmbeddingProviderAuthenticationError
from packages.knowledge.embeddings.errors import EmbeddingProviderAuthorizationError, EmbeddingProviderConnectionError, EmbeddingProviderExecutionError
from packages.knowledge.embeddings.errors import EmbeddingProviderRateLimitError, EmbeddingProviderRequestError, EmbeddingProviderTimeoutError
from packages.knowledge.embeddings.errors import EmbeddingProviderUnavailableError, EmbeddingResponseCardinalityError, EmbeddingResponseOrderingError, InvalidEmbeddingVectorError
from packages.knowledge.embeddings.models import DocumentEmbedding, EmbeddingBatch, EmbeddingProviderDescriptor, EmbeddingVector
from packages.knowledge.embeddings.provider.base import EmbeddingProvider


class JinaEmbeddingProvider(EmbeddingProvider):
    """
    Real embedding provider backed by Jina AI's Embeddings API.

    The provider is deliberately responsible only for the external-provider boundary:
    - request construction
    - document/query task selection
    - transport handling
    - HTTP error translation
    - response validation
    - conversion into provider-neutral embedding models

    It does not know about:
    - knowledge documents
    - chunks
    - repositories
    - pgvector
    - application lifecycle
    - embedding persistence

    Those responsibilities belong to higher layers.
    """
    PROVIDER_NAME = "jina"
    DEFAULT_MODEL = "jina-embeddings-v4"
    DEFAULT_DIMENSIONS = 1024
    DEFAULT_ENDPOINT = "https://api.jina.ai/v1/embeddings"
    DEFAULT_TIMEOUT_SECONDS = 30.0
    DOCUMENT_TASK = "retrieval.passage"
    QUERY_TASK = "retrieval.query"

    def __init__(self, *, api_key: str, model: str = DEFAULT_MODEL, dimensions: int = DEFAULT_DIMENSIONS, endpoint: str = DEFAULT_ENDPOINT,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS, normalized: bool = True, client: httpx.Client | None = None
    ) -> None:
        self._api_key = self._validate_api_key(api_key)
        self._model = self._validate_required_string(model, field_name="model")
        self._endpoint = self._validate_required_string(endpoint, field_name="endpoint")

        if dimensions <= 0:
            raise ValueError("dimensions must be greater than zero.")

        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")

        self._dimensions = dimensions
        self._normalized = normalized
        self._timeout_seconds = float(timeout_seconds)
        self._timeout = httpx.Timeout(self._timeout_seconds)
        self._client = client
        self._descriptor = EmbeddingProviderDescriptor(
            provider=self.PROVIDER_NAME,
            model=self._model,
            revision=None,
            dimensions=self._dimensions,
        )

    @property
    def descriptor(self) -> EmbeddingProviderDescriptor:
        return self._descriptor

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def normalized(self) -> bool:
        return self._normalized

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        validated_texts = self._validate_document_inputs(texts)
        if not validated_texts:
            return EmbeddingBatch(embeddings=(), provider=self.descriptor)

        vectors = self._request_embeddings(texts=validated_texts, task=self.DOCUMENT_TASK)
        embeddings = tuple(
            DocumentEmbedding(input_index=index, vector=vector,)
            for index, vector in enumerate(vectors)
        )

        return EmbeddingBatch(
            embeddings=embeddings,
            provider=self.descriptor,
        )

    def embed_query(self, text: str) -> EmbeddingVector:
        validated_text = self._validate_text(text, field_name="query")
        vectors = self._request_embeddings(texts=(validated_text,), task=self.QUERY_TASK)
        if len(vectors) != 1:
            raise EmbeddingResponseCardinalityError(
                # "Jina returned an unexpected number of query embeddings.",
                expected_count=1,
                actual_count=len(vectors),
                provider=self.descriptor.provider,
                model=self.descriptor.model,
            )

        return vectors[0]

    def health_check(self) -> bool:
        """
        Lightweight provider verification.

        We deliberately use the same public embedding endpoint rather than inventing a separate health endpoint whose semantics may differ.

        A failed check returns False rather than leaking provider exceptions into readiness handling.
        """
        try:
            self.embed_query("health check")
            return True
        
        except Exception:
            return False

    def _request_embeddings(self, *, texts: Sequence[str], task: str) -> tuple[EmbeddingVector, ...]:
        payload = {
            "model": self._model,
            "task": task,
            "dimensions": self._dimensions,
            "normalized": self._normalized,
            "embedding_type": "float",
            "truncate": False,
            "input": list(texts),
        }

        try:
            response = self._post(payload=payload)

        except httpx.TimeoutException as exc:
            raise EmbeddingProviderTimeoutError(provider=self.descriptor.provider, model=self.descriptor.model, timeout_seconds=self._timeout_seconds) from exc

        except httpx.RequestError as exc:
            raise EmbeddingProviderConnectionError(provider=self.descriptor.provider, model=self.descriptor.model) from exc

        except (
            EmbeddingProviderAuthenticationError, EmbeddingProviderAuthorizationError, EmbeddingProviderRateLimitError,
            EmbeddingProviderRequestError, EmbeddingProviderUnavailableError, EmbeddingResponseCardinalityError,
            EmbeddingResponseOrderingError, EmbeddingDimensionMismatchError, InvalidEmbeddingVectorError
        ):
            raise

        except Exception as exc:
            raise EmbeddingProviderExecutionError(
                "Unexpected failure while executing Jina embedding request.",
                provider=self.descriptor.provider,
                model=self.descriptor.model,
                error_type=type(exc).__name__,
            ) from exc

        self._raise_for_status(response)
        return self._parse_response(response=response, expected_count=len(texts))

    def _post(self, *, payload: dict[str, Any]) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if self._client is not None:
            return self._client.post(
                self._endpoint,
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )

        with httpx.Client() as client:
            return client.post(self._endpoint, headers=headers, json=payload, timeout=self._timeout)

    def _raise_for_status(self, response: httpx.Response) -> None:
        status_code = response.status_code
        if 200 <= status_code < 300:
            return

        provider = self.descriptor.provider
        model = self.descriptor.model

        if status_code == 401:
            raise EmbeddingProviderAuthenticationError(provider=provider, model=model)

        if status_code == 403:
            raise EmbeddingProviderAuthorizationError(provider=provider, model=model)

        if status_code == 429:
            raise EmbeddingProviderRateLimitError(
                provider=provider,
                model=model,
                retry_after_seconds=self._parse_retry_after(response),
            )

        if status_code in {408, 504}:
            raise EmbeddingProviderTimeoutError(
                provider=provider,
                model=model,
                timeout_seconds=self._timeout_seconds,
            )

        if status_code >= 500:
            raise EmbeddingProviderUnavailableError(provider=provider, model=model, provider_status_code=status_code)

        if 400 <= status_code < 500:
            raise EmbeddingProviderRequestError(provider=provider, model=model, provider_status_code=status_code)

        raise EmbeddingProviderExecutionError(
            "Jina returned an unexpected HTTP status.",
            provider=provider,
            model=model,
            provider_status_code=status_code,
        )

    def _parse_response(self, *, response: httpx.Response, expected_count: int) -> tuple[EmbeddingVector, ...]:
        try:
            body = response.json()
            
        except ValueError as exc:
            raise EmbeddingProviderExecutionError(
                "Jina returned a non-JSON embedding response.",
                provider=self.descriptor.provider,
                model=self.descriptor.model,
            ) from exc

        if not isinstance(body, dict):
            raise EmbeddingProviderExecutionError(
                "Jina embedding response root must be a JSON object.",
                provider=self.descriptor.provider,
                model=self.descriptor.model,
                actual_type=type(body).__name__,
            )

        data = body.get("data")

        if not isinstance(data, list):
            raise EmbeddingProviderExecutionError(
                "Jina embedding response is missing a valid data array.",
                provider=self.descriptor.provider,
                model=self.descriptor.model,
                actual_type=type(data).__name__,
            )

        if len(data) != expected_count:
            raise EmbeddingResponseCardinalityError(
                # "Jina returned an unexpected number of embeddings.",
                expected_count=expected_count,
                actual_count=len(data),
                provider=self.descriptor.provider,
                model=self.descriptor.model,
            )

        vectors_by_index: dict[int, EmbeddingVector] = {}
        for item_position, item in enumerate(data):
            if not isinstance(item, dict):
                raise EmbeddingProviderExecutionError(
                    "Jina embedding response contains an invalid data item.",
                    provider=self.descriptor.provider,
                    model=self.descriptor.model,
                    item_position=item_position,
                    actual_type=type(item).__name__,
                )

            index = item.get("index")

            if not isinstance(index, int) or isinstance(index, bool):
                raise EmbeddingResponseOrderingError(
                    "Jina embedding response contains an invalid input index.",
                    provider=self.descriptor.provider,
                    model=self.descriptor.model,
                    item_position=item_position,
                    returned_index=index,
                )

            if index < 0 or index >= expected_count:
                raise EmbeddingResponseOrderingError(
                    "Jina embedding response index is outside the request range.",
                    provider=self.descriptor.provider,
                    model=self.descriptor.model,
                    item_position=item_position,
                    returned_index=index,
                    expected_count=expected_count,
                )

            if index in vectors_by_index:
                raise EmbeddingResponseOrderingError(
                    "Jina embedding response contains a duplicate input index.",
                    provider=self.descriptor.provider,
                    model=self.descriptor.model,
                    duplicate_index=index,
                )

            vector = self._parse_vector(raw_embedding=item.get("embedding"), input_index=index)
            vectors_by_index[index] = vector

        expected_indexes = set(range(expected_count))
        actual_indexes = set(vectors_by_index)
        if actual_indexes != expected_indexes:
            raise EmbeddingResponseOrderingError(
                "Jina embedding response does not cover every requested input.",
                provider=self.descriptor.provider,
                model=self.descriptor.model,
                expected_indexes=tuple(sorted(expected_indexes)),
                actual_indexes=tuple(sorted(actual_indexes)),
            )

        return tuple(vectors_by_index[index] for index in range(expected_count))

    def _parse_vector(self, *, raw_embedding: object, input_index: int) -> EmbeddingVector:
        if not isinstance(raw_embedding, (list, tuple)):
            raise InvalidEmbeddingVectorError(
                "Jina returned an embedding that is not a numeric vector.",
                provider=self.descriptor.provider,
                model=self.descriptor.model,
                input_index=input_index,
                actual_type=type(raw_embedding).__name__
            )

        if len(raw_embedding) != self._dimensions:
            raise EmbeddingDimensionMismatchError(
                expected_dimensions=self._dimensions,
                actual_dimensions=len(raw_embedding),
                provider=self.descriptor.provider,
                model=self.descriptor.model,
                input_index=input_index,
            )

        values: list[float] = []
        for dimension_index, raw_value in enumerate(raw_embedding):
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise InvalidEmbeddingVectorError(
                    "Jina embedding contains a non-numeric value.",
                    provider=self.descriptor.provider,
                    model=self.descriptor.model,
                    input_index=input_index,
                    dimension_index=dimension_index,
                    actual_type=type(raw_value).__name__
                )

            value = float(raw_value)
            if not math.isfinite(value):
                raise InvalidEmbeddingVectorError(
                    "Jina embedding contains a non-finite value.",
                    provider=self.descriptor.provider,
                    model=self.descriptor.model,
                    input_index=input_index,
                    dimension_index=dimension_index,
                )

            values.append(value)

        try:
            return EmbeddingVector(values=tuple(values))

        except ValueError as exc:
            raise InvalidEmbeddingVectorError(
                "Jina returned an invalid embedding vector.",
                provider=self.descriptor.provider,
                model=self.descriptor.model,
                input_index=input_index,
            ) from exc

    def _validate_document_inputs(self, texts: Sequence[str]) -> tuple[str, ...]:
        if isinstance(texts, (str, bytes)):
            raise EmbeddingInputValidationError("Document embedding input must be a sequence of strings, not a single string.")

        validated: list[str] = []
        for index, text in enumerate(texts):
            validated.append(self._validate_text(text, field_name=f"texts[{index}]", input_index=index))

        return tuple(validated)

    @staticmethod
    def _validate_text(text: str, *, field_name: str, input_index: int | None = None) -> str:
        if not isinstance(text, str):
            raise EmbeddingInputValidationError(
                f"{field_name} must be a string.",
                input_index=input_index,
                actual_type=type(text).__name__
            )

        normalized = text.strip()
        if not normalized:
            raise EmbeddingInputValidationError(f"{field_name} must not be blank.", input_index=input_index)

        return normalized

    @staticmethod
    def _validate_api_key(api_key: str) -> str:
        if not isinstance(api_key, str):
            raise ValueError("api_key must be a string.")

        normalized = api_key.strip()
        if not normalized:
            raise ValueError("api_key must not be blank.")

        return normalized

    @staticmethod
    def _validate_required_string(value: str, *, field_name: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string.")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must not be blank.")

        return normalized

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")

        if value is None:
            return None

        try:
            seconds = float(value)
        except ValueError:
            return None

        if not math.isfinite(seconds) or seconds < 0:
            return None

        return seconds