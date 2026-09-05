from __future__ import annotations

import json
import math

import httpx
import pytest

from packages.knowledge.embeddings.errors import (
    EmbeddingDimensionMismatchError,
    EmbeddingInputValidationError,
    EmbeddingProviderAuthenticationError,
    EmbeddingProviderAuthorizationError,
    EmbeddingProviderConnectionError,
    EmbeddingProviderExecutionError,
    EmbeddingProviderRateLimitError,
    EmbeddingProviderRequestError,
    EmbeddingProviderTimeoutError,
    EmbeddingProviderUnavailableError,
    EmbeddingResponseCardinalityError,
    EmbeddingResponseOrderingError,
    InvalidEmbeddingVectorError,
)
from packages.knowledge.embeddings.provider.jina import (
    JinaEmbeddingProvider,
)


def build_vector(
    *,
    dimensions: int,
    seed: float = 0.1,
) -> list[float]:
    return [
        seed + (index * 0.001)
        for index in range(dimensions)
    ]


def make_json_response(
    *,
    request: httpx.Request,
    status_code: int = 200,
    body: object | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    response_headers = {
        "Content-Type": "application/json",
    }

    if headers:
        response_headers.update(
            headers
        )

    return httpx.Response(
        status_code=status_code,
        content=json.dumps(
            body,
            allow_nan=True,
        ).encode("utf-8"),
        headers=response_headers,
        request=request,
    )


def make_raw_response(
    *,
    request: httpx.Request,
    status_code: int = 200,
    content: bytes,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers,
        request=request,
    )


def create_provider(
    handler,
    *,
    dimensions: int = 8,
    api_key: str = "test-api-key",
    normalized: bool = True,
) -> JinaEmbeddingProvider:
    transport = httpx.MockTransport(
        handler
    )

    client = httpx.Client(
        transport=transport
    )

    return JinaEmbeddingProvider(
        api_key=api_key,
        dimensions=dimensions,
        normalized=normalized,
        client=client,
    )


class TestJinaEmbeddingProviderConfiguration:
    def test_default_descriptor(self) -> None:
        provider = JinaEmbeddingProvider(
            api_key="secret",
        )

        descriptor = provider.descriptor

        assert descriptor.provider == "jina"
        assert descriptor.model == "jina-embeddings-v4"
        assert descriptor.revision is None
        assert descriptor.dimensions == 1024

    def test_custom_configuration_is_reflected_in_descriptor(
        self,
    ) -> None:
        provider = JinaEmbeddingProvider(
            api_key="secret",
            model="custom-model",
            dimensions=512,
            endpoint="https://example.test/embeddings",
            normalized=False,
        )

        assert provider.descriptor.provider == "jina"
        assert provider.descriptor.model == "custom-model"
        assert provider.descriptor.dimensions == 512

        assert provider.endpoint == (
            "https://example.test/embeddings"
        )

        assert provider.normalized is False

    @pytest.mark.parametrize(
        "dimensions",
        [
            0,
            -1,
            -100,
        ],
    )
    def test_non_positive_dimensions_are_rejected(
        self,
        dimensions: int,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="dimensions must be greater than zero",
        ):
            JinaEmbeddingProvider(
                api_key="secret",
                dimensions=dimensions,
            )

    @pytest.mark.parametrize(
        "timeout",
        [
            0,
            -1,
            -10.0,
        ],
    )
    def test_non_positive_timeout_is_rejected(
        self,
        timeout: float,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="timeout_seconds must be greater than zero",
        ):
            JinaEmbeddingProvider(
                api_key="secret",
                timeout_seconds=timeout,
            )

    @pytest.mark.parametrize(
        "api_key",
        [
            "",
            " ",
            "\t",
            "\n",
        ],
    )
    def test_blank_api_key_is_rejected(
        self,
        api_key: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="api_key must not be blank",
        ):
            JinaEmbeddingProvider(
                api_key=api_key,
            )

    @pytest.mark.parametrize(
        "api_key",
        [
            None,
            123,
            b"secret",
            object(),
        ],
    )
    def test_non_string_api_key_is_rejected(
        self,
        api_key: object,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="api_key must be a string",
        ):
            JinaEmbeddingProvider(
                api_key=api_key,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        ("field", "kwargs"),
        [
            (
                "model",
                {
                    "model": " ",
                },
            ),
            (
                "endpoint",
                {
                    "endpoint": "\n",
                },
            ),
        ],
    )
    def test_required_string_configuration_cannot_be_blank(
        self,
        field: str,
        kwargs: dict[str, str],
    ) -> None:
        with pytest.raises(
            ValueError,
            match=rf"{field} must not be blank",
        ):
            JinaEmbeddingProvider(
                api_key="secret",
                **kwargs,
            )


class TestDocumentEmbeddingRequest:
    def test_document_embedding_sends_expected_payload(
        self,
    ) -> None:
        captured_request: httpx.Request | None = None

        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            nonlocal captured_request

            captured_request = request

            body = json.loads(
                request.content.decode(
                    "utf-8"
                )
            )

            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": build_vector(
                                dimensions=8,
                            ),
                        },
                        {
                            "index": 1,
                            "embedding": build_vector(
                                dimensions=8,
                                seed=0.2,
                            ),
                        },
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=8,
        )

        result = provider.embed_documents(
            [
                "Refund policy.",
                "Shipping policy.",
            ]
        )

        assert result.size == 2

        assert captured_request is not None

        request_body = json.loads(
            captured_request.content.decode(
                "utf-8"
            )
        )

        assert request_body == {
            "model": "jina-embeddings-v4",
            "task": "retrieval.passage",
            "dimensions": 8,
            "normalized": True,
            "embedding_type": "float",
            "truncate": False,
            "input": [
                "Refund policy.",
                "Shipping policy.",
            ],
        }

    def test_document_request_contains_authorization_header(
        self,
    ) -> None:
        captured_authorization: str | None = None

        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            nonlocal captured_authorization

            captured_authorization = (
                request.headers.get(
                    "Authorization"
                )
            )

            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": build_vector(
                                dimensions=8,
                            ),
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=8,
            api_key="super-secret-key",
        )

        provider.embed_documents(
            ["Refund policy."]
        )

        assert captured_authorization == (
            "Bearer super-secret-key"
        )

    def test_document_embeddings_preserve_input_order(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 2,
                            "embedding": build_vector(
                                dimensions=4,
                                seed=0.3,
                            ),
                        },
                        {
                            "index": 0,
                            "embedding": build_vector(
                                dimensions=4,
                                seed=0.1,
                            ),
                        },
                        {
                            "index": 1,
                            "embedding": build_vector(
                                dimensions=4,
                                seed=0.2,
                            ),
                        },
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        batch = provider.embed_documents(
            [
                "first",
                "second",
                "third",
            ]
        )

        assert [
            embedding.input_index
            for embedding in batch.embeddings
        ] == [
            0,
            1,
            2,
        ]

        assert (
            batch.embeddings[0].vector.values[0]
            == pytest.approx(0.1)
        )

        assert (
            batch.embeddings[1].vector.values[0]
            == pytest.approx(0.2)
        )

        assert (
            batch.embeddings[2].vector.values[0]
            == pytest.approx(0.3)
        )

    def test_empty_document_batch_does_not_call_transport(
        self,
    ) -> None:
        call_count = 0

        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            nonlocal call_count

            call_count += 1

            raise AssertionError(
                "Transport should not be called."
            )

        provider = create_provider(
            handler,
            dimensions=8,
        )

        batch = provider.embed_documents(
            []
        )

        assert batch.size == 0
        assert batch.embeddings == ()
        assert batch.provider == (
            provider.descriptor
        )

        assert call_count == 0


class TestQueryEmbeddingRequest:
    def test_query_embedding_uses_query_task(
        self,
    ) -> None:
        captured_body: dict[str, object] | None = None

        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            nonlocal captured_body

            captured_body = json.loads(
                request.content.decode(
                    "utf-8"
                )
            )

            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": build_vector(
                                dimensions=8,
                            ),
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=8,
        )

        vector = provider.embed_query(
            "Where is my order?"
        )

        assert vector.dimensions == 8

        assert captured_body is not None

        assert captured_body[
            "task"
        ] == "retrieval.query"

        assert captured_body[
            "input"
        ] == [
            "Where is my order?"
        ]

        assert captured_body[
            "truncate"
        ] is False

    def test_query_embedding_returns_expected_vector(
        self,
    ) -> None:
        expected = build_vector(
            dimensions=8,
            seed=0.25,
        )

        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": expected,
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=8,
        )

        vector = provider.embed_query(
            "refund"
        )

        assert vector.values == tuple(
            expected
        )


class TestInputValidation:
    def test_single_string_document_input_is_rejected(
        self,
    ) -> None:
        provider = JinaEmbeddingProvider(
            api_key="secret",
        )

        with pytest.raises(
            EmbeddingInputValidationError,
            match=(
                "Document embedding input must be a sequence of strings"
            ),
        ):
            provider.embed_documents(
                "not-a-sequence-of-documents"
            )  # type: ignore[arg-type]

    def test_bytes_document_input_is_rejected(
        self,
    ) -> None:
        provider = JinaEmbeddingProvider(
            api_key="secret",
        )

        with pytest.raises(
            EmbeddingInputValidationError,
        ):
            provider.embed_documents(
                b"invalid"
            )  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "value",
        [
            "",
            " ",
            "\t",
            "\n",
        ],
    )
    def test_blank_document_is_rejected(
        self,
        value: str,
    ) -> None:
        provider = JinaEmbeddingProvider(
            api_key="secret",
        )

        with pytest.raises(
            EmbeddingInputValidationError,
            match=r"texts\[0\] must not be blank",
        ) as exc_info:
            provider.embed_documents(
                [value]
            )

        assert (
            exc_info.value.details[
                "input_index"
            ]
            == 0
        )

    def test_non_string_document_is_rejected(
        self,
    ) -> None:
        provider = JinaEmbeddingProvider(
            api_key="secret",
        )

        with pytest.raises(
            EmbeddingInputValidationError,
            match=r"texts\[1\] must be a string",
        ) as exc_info:
            provider.embed_documents(
                [
                    "valid",
                    123,  # type: ignore[list-item]
                ]
            )

        assert (
            exc_info.value.details[
                "input_index"
            ]
            == 1
        )

        assert (
            exc_info.value.details[
                "actual_type"
            ]
            == "int"
        )

    @pytest.mark.parametrize(
        "value",
        [
            "",
            " ",
            "\n",
            "\t",
        ],
    )
    def test_blank_query_is_rejected(
        self,
        value: str,
    ) -> None:
        provider = JinaEmbeddingProvider(
            api_key="secret",
        )

        with pytest.raises(
            EmbeddingInputValidationError,
            match="query must not be blank",
        ):
            provider.embed_query(
                value
            )

    def test_non_string_query_is_rejected(
        self,
    ) -> None:
        provider = JinaEmbeddingProvider(
            api_key="secret",
        )

        with pytest.raises(
            EmbeddingInputValidationError,
            match="query must be a string",
        ) as exc_info:
            provider.embed_query(
                123  # type: ignore[arg-type]
            )

        assert (
            exc_info.value.details[
                "actual_type"
            ]
            == "int"
        )

    def test_outer_whitespace_is_trimmed_before_request(
        self,
    ) -> None:
        captured_input: list[str] | None = None

        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            nonlocal captured_input

            payload = json.loads(
                request.content.decode(
                    "utf-8"
                )
            )

            captured_input = payload[
                "input"
            ]

            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": build_vector(
                                dimensions=4,
                            ),
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        provider.embed_query(
            "\n  refund status  \t"
        )

        assert captured_input == [
            "refund status"
        ]


class TestAuthenticationAndAuthorizationErrors:
    def test_401_maps_to_authentication_error(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                status_code=401,
                body={
                    "detail": "unauthorized"
                },
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderAuthenticationError,
        ) as exc_info:
            provider.embed_query(
                "refund"
            )

        error = exc_info.value

        assert error.retryable is False
        # assert error.details[
        #     "status_code"
        # ] == 401
        assert error.details[
            "provider"
        ] == "jina"
        assert error.details["model"] == "jina-embeddings-v4"

    def test_403_maps_to_authorization_error(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                status_code=403,
                body={
                    "detail": "forbidden"
                },
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderAuthorizationError,
        ) as exc_info:
            provider.embed_query(
                "refund"
            )

        error = exc_info.value

        assert error.retryable is False
        assert error.details["provider"] == "jina"
        assert error.details["model"] == "jina-embeddings-v4"


class TestRateLimitErrors:
    def test_429_maps_to_rate_limit_error(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                status_code=429,
                headers={
                    "Retry-After": "5",
                },
                body={
                    "detail": "rate limited"
                },
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderRateLimitError,
        ) as exc_info:
            provider.embed_query(
                "refund"
            )

        error = exc_info.value

        assert error.retryable is True
        assert error.retryable is True
        assert error.details["retry_after_seconds"] == 5.0
        # assert error.retry_after_seconds == 5.0
        # assert error.details[
        #     "status_code"
        # ] == 429

    @pytest.mark.parametrize(
        "retry_after",
        [
            "invalid",
            "-5",
            "nan",
            "inf",
        ],
    )
    def test_invalid_retry_after_is_ignored(
        self,
        retry_after: str,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                status_code=429,
                headers={
                    "Retry-After": retry_after,
                },
                body={},
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderRateLimitError,
        ) as exc_info:
            provider.embed_query(
                "refund"
            )

        assert (
            exc_info.value.details.get(
                "retry_after_seconds"
            )
            is None
        )


class TestTimeoutAndAvailabilityErrors:
    @pytest.mark.parametrize(
        "status_code",
        [
            408,
            504,
        ],
    )
    def test_timeout_statuses_map_to_timeout_error(
        self,
        status_code: int,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                status_code=status_code,
                body={},
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderTimeoutError,
        ) as exc_info:
            provider.embed_query(
                "refund"
            )

        assert exc_info.value.retryable is True

    @pytest.mark.parametrize(
        "status_code",
        [
            500,
            502,
            503,
            505,
        ],
    )
    def test_server_errors_map_to_unavailable(
        self,
        status_code: int,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                status_code=status_code,
                body={},
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderUnavailableError,
        ) as exc_info:
            provider.embed_query(
                "refund"
            )

        error = exc_info.value

        assert error.retryable is True
        assert error.details[
            "provider_status_code"
        ] == status_code


class TestClientRequestErrors:
    @pytest.mark.parametrize(
        "status_code",
        [
            400,
            404,
            409,
            422,
        ],
    )
    def test_other_4xx_maps_to_request_error(
        self,
        status_code: int,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                status_code=status_code,
                body={},
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderRequestError,
        ) as exc_info:
            provider.embed_query(
                "refund"
            )

        assert exc_info.value.retryable is False

        assert (
            exc_info.value.details[
                "provider_status_code"
            ]
            == status_code
        )


class TestTransportErrors:
    def test_timeout_exception_maps_to_provider_timeout(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            raise httpx.ReadTimeout(
                "timed out",
                request=request,
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderTimeoutError,
        ) as exc_info:
            provider.embed_query(
                "refund"
            )

        assert exc_info.value.retryable is True

    @pytest.mark.parametrize(
        "exception_factory",
        [
            lambda request: httpx.ConnectError(
                "connection failed",
                request=request,
            ),
            lambda request: httpx.NetworkError(
                "network failed",
                request=request,
            ),
        ],
    )
    def test_request_errors_map_to_connection_error(
        self,
        exception_factory,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            raise exception_factory(
                request
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderConnectionError,
        ) as exc_info:
            provider.embed_query(
                "refund"
            )

        assert exc_info.value.retryable is True


class TestMalformedResponses:
    def test_non_json_response_is_rejected(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_raw_response(
                request=request,
                content=b"<html>failure</html>",
                headers={
                    "Content-Type": "text/html",
                },
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderExecutionError,
            match="non-JSON",
        ):
            provider.embed_query(
                "refund"
            )

    @pytest.mark.parametrize(
        "body",
        [
            [],
            "string",
            123,
            None,
        ],
    )
    def test_response_root_must_be_object(
        self,
        body: object,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body=body,
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderExecutionError,
            match="root must be a JSON object",
        ):
            provider.embed_query(
                "refund"
            )

    @pytest.mark.parametrize(
        "data",
        [
            None,
            {},
            "invalid",
            123,
        ],
    )
    def test_data_must_be_array(
        self,
        data: object,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": data,
                },
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderExecutionError,
            match="valid data array",
        ):
            provider.embed_query(
                "refund"
            )

    def test_data_item_must_be_object(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        "invalid"
                    ],
                },
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderExecutionError,
            match="invalid data item",
        ):
            provider.embed_query(
                "refund"
            )


class TestResponseCardinality:
    def test_too_few_embeddings_are_rejected(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": build_vector(
                                dimensions=4,
                            ),
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        with pytest.raises(
            EmbeddingResponseCardinalityError,
        ) as exc_info:
            provider.embed_documents(
                [
                    "one",
                    "two",
                ]
            )

        assert (
            exc_info.value.details[
                "expected_count"
            ]
            == 2
        )

        assert (
            exc_info.value.details[
                "actual_count"
            ]
            == 1
        )

    def test_too_many_query_embeddings_are_rejected(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": build_vector(
                                dimensions=4,
                            ),
                        },
                        {
                            "index": 1,
                            "embedding": build_vector(
                                dimensions=4,
                            ),
                        },
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        with pytest.raises(
            EmbeddingResponseCardinalityError,
        ):
            provider.embed_query(
                "refund"
            )


class TestResponseOrdering:
    def test_non_integer_index_is_rejected(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": "0",
                            "embedding": build_vector(
                                dimensions=4,
                            ),
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        with pytest.raises(
            EmbeddingResponseOrderingError,
            match="invalid input index",
        ):
            provider.embed_query(
                "refund"
            )

    def test_boolean_index_is_rejected(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": True,
                            "embedding": build_vector(
                                dimensions=4,
                            ),
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        with pytest.raises(
            EmbeddingResponseOrderingError,
        ):
            provider.embed_query(
                "refund"
            )

    def test_out_of_range_index_is_rejected(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 3,
                            "embedding": build_vector(
                                dimensions=4,
                            ),
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        with pytest.raises(
            EmbeddingResponseOrderingError,
            match="outside the request range",
        ):
            provider.embed_query(
                "refund"
            )

    def test_duplicate_index_is_rejected(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": build_vector(
                                dimensions=4,
                            ),
                        },
                        {
                            "index": 0,
                            "embedding": build_vector(
                                dimensions=4,
                                seed=0.2,
                            ),
                        },
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        with pytest.raises(
            EmbeddingResponseOrderingError,
            match="duplicate input index",
        ):
            provider.embed_documents(
                [
                    "one",
                    "two",
                ]
            )


class TestVectorValidation:
    def test_wrong_dimensions_are_rejected(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": build_vector(
                                dimensions=3,
                            ),
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        with pytest.raises(
            EmbeddingDimensionMismatchError,
        ) as exc_info:
            provider.embed_query(
                "refund"
            )

        assert (
            exc_info.value.details[
                "expected_dimensions"
            ]
            == 4
        )

        assert (
            exc_info.value.details[
                "actual_dimensions"
            ]
            == 3
        )

    @pytest.mark.parametrize(
        "embedding",
        [
            None,
            "invalid",
            {},
            123,
        ],
    )
    def test_embedding_must_be_sequence(
        self,
        embedding: object,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": embedding,
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        with pytest.raises(
            InvalidEmbeddingVectorError,
        ):
            provider.embed_query(
                "refund"
            )

    @pytest.mark.parametrize(
        "bad_value",
        [
            "0.5",
            None,
            {},
            [],
            True,
            False,
        ],
    )
    def test_non_numeric_vector_value_is_rejected(
        self,
        bad_value: object,
    ) -> None:
        vector: list[object] = [
            0.1,
            0.2,
            0.3,
            0.4,
        ]

        vector[2] = bad_value

        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": vector,
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        with pytest.raises(
            InvalidEmbeddingVectorError,
            match="non-numeric value",
        ) as exc_info:
            provider.embed_query(
                "refund"
            )

        assert (
            exc_info.value.details[
                "dimension_index"
            ]
            == 2
        )

    @pytest.mark.parametrize(
        "bad_value",
        [
            math.nan,
            math.inf,
            -math.inf,
        ],
    )
    def test_non_finite_vector_value_is_rejected(
        self,
        bad_value: float,
    ) -> None:
        vector = [
            0.1,
            0.2,
            bad_value,
            0.4,
        ]

        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": vector,
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        with pytest.raises(
            InvalidEmbeddingVectorError,
            match="non-finite value",
        ) as exc_info:
            provider.embed_query(
                "refund"
            )

        assert (
            exc_info.value.details[
                "dimension_index"
            ]
            == 2
        )

    def test_integer_values_are_accepted_and_converted_to_float(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": [
                                1,
                                2,
                                3,
                                4,
                            ],
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        vector = provider.embed_query(
            "refund"
        )

        assert vector.values == (
            1.0,
            2.0,
            3.0,
            4.0,
        )


class TestProviderSafety:
    def test_api_key_is_not_exposed_in_authentication_error_details(
        self,
    ) -> None:
        secret = "very-secret-key"

        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                status_code=401,
                body={
                    "detail": secret,
                },
            )

        provider = create_provider(
            handler,
            api_key=secret,
        )

        with pytest.raises(
            EmbeddingProviderAuthenticationError,
        ) as exc_info:
            provider.embed_query(
                "customer secret text"
            )

        serialized_details = repr(
            exc_info.value.details
        )

        assert secret not in serialized_details
        assert (
            "customer secret text"
            not in serialized_details
        )

    def test_raw_provider_response_body_is_not_exposed_in_error_details(
        self,
    ) -> None:
        sensitive_provider_body = (
            "internal-provider-debug-data"
        )

        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_raw_response(
                request=request,
                status_code=500,
                content=(
                    sensitive_provider_body.encode(
                        "utf-8"
                    )
                ),
            )

        provider = create_provider(
            handler,
        )

        with pytest.raises(
            EmbeddingProviderUnavailableError,
        ) as exc_info:
            provider.embed_query(
                "refund"
            )

        assert (
            sensitive_provider_body
            not in repr(
                exc_info.value.details
            )
        )


class TestHealthCheck:
    def test_health_check_returns_true_when_embedding_succeeds(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                body={
                    "data": [
                        {
                            "index": 0,
                            "embedding": build_vector(
                                dimensions=4,
                            ),
                        }
                    ]
                },
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        assert provider.health_check() is True

    def test_health_check_returns_false_on_provider_failure(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            return make_json_response(
                request=request,
                status_code=503,
                body={},
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        assert provider.health_check() is False

    def test_health_check_returns_false_on_transport_failure(
        self,
    ) -> None:
        def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            raise httpx.ConnectError(
                "connection failed",
                request=request,
            )

        provider = create_provider(
            handler,
            dimensions=4,
        )

        assert provider.health_check() is False