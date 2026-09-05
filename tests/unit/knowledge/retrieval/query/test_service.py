from __future__ import annotations

from typing import cast

import pytest

from packages.knowledge.retrieval.query.builder import (
    RetrievalQueryBuilder,
)
from packages.knowledge.retrieval.query.errors import (
    QueryConstructionError,
    RetrievalQueryPreparationUnavailableError,
    UnexpectedRetrievalQueryPreparationError,
)
from packages.knowledge.retrieval.query.models import (
    PreparedRetrievalQuery,
    RetrievalQueryContext,
)
from packages.knowledge.retrieval.query.service import (
    RetrievalQueryPreparationService,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class SuccessfulBuilder(RetrievalQueryBuilder):
    def __init__(
        self,
        result: PreparedRetrievalQuery,
    ) -> None:
        self._result = result
        self.calls: list[RetrievalQueryContext] = []

    def build(
        self,
        *,
        context: RetrievalQueryContext,
    ) -> PreparedRetrievalQuery:
        self.calls.append(context)
        return self._result


class DomainFailingBuilder(RetrievalQueryBuilder):
    def build(
        self,
        *,
        context: RetrievalQueryContext,
    ) -> PreparedRetrievalQuery:
        raise QueryConstructionError(
            "Unable to construct retrieval query."
        )


class UnexpectedFailingBuilder(RetrievalQueryBuilder):
    def build(
        self,
        *,
        context: RetrievalQueryContext,
    ) -> PreparedRetrievalQuery:
        raise RuntimeError(
            "unexpected implementation failure"
        )


class InvalidResultBuilder(RetrievalQueryBuilder):
    def build(
        self,
        *,
        context: RetrievalQueryContext,
    ) -> PreparedRetrievalQuery:
        return cast(
            PreparedRetrievalQuery,
            "not-a-prepared-query",
        )


class CustomBuilder(RetrievalQueryBuilder):
    """
    Proves that the service depends on the abstraction rather than the
    deterministic concrete implementation.
    """

    def build(
        self,
        *,
        context: RetrievalQueryContext,
    ) -> PreparedRetrievalQuery:
        return PreparedRetrievalQuery(
            original_query=context.customer_message,
            semantic_query=f"semantic::{context.customer_message}",
            lexical_queries=("custom lexical query",),
            filters=context.filters,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context() -> RetrievalQueryContext:
    return RetrievalQueryContext(
        customer_message="How long does my refund take?",
        intent_key="refund_request",
        entities={
            "issue_type": "delayed refund",
        },
    )


def _make_prepared_result() -> PreparedRetrievalQuery:
    return PreparedRetrievalQuery(
        original_query="How long does my refund take?",
        semantic_query="How long does my refund take?",
        lexical_queries=("long refund take",),
    )


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_constructor_accepts_query_builder_abstraction() -> None:
    builder = CustomBuilder()

    service = RetrievalQueryPreparationService(
        builder=builder,
    )

    result = service.prepare(
        context=_make_context(),
    )

    assert result.semantic_query.startswith(
        "semantic::"
    )


def test_constructor_rejects_invalid_builder() -> None:
    with pytest.raises(
        RetrievalQueryPreparationUnavailableError,
        match="valid retrieval query builder",
    ):
        RetrievalQueryPreparationService(
            builder=cast(
                RetrievalQueryBuilder,
                object(),
            ),
        )


def test_constructor_rejects_none_builder() -> None:
    with pytest.raises(
        RetrievalQueryPreparationUnavailableError,
        match="valid retrieval query builder",
    ):
        RetrievalQueryPreparationService(
            builder=cast(
                RetrievalQueryBuilder,
                None,
            ),
        )


# ---------------------------------------------------------------------------
# Successful delegation
# ---------------------------------------------------------------------------


def test_prepare_delegates_context_to_builder() -> None:
    context = _make_context()
    prepared = _make_prepared_result()

    builder = SuccessfulBuilder(
        prepared
    )

    service = RetrievalQueryPreparationService(
        builder=builder,
    )

    result = service.prepare(
        context=context,
    )

    assert builder.calls == [context]
    assert result is prepared


def test_prepare_invokes_builder_exactly_once() -> None:
    context = _make_context()
    prepared = _make_prepared_result()

    builder = SuccessfulBuilder(
        prepared
    )

    service = RetrievalQueryPreparationService(
        builder=builder,
    )

    service.prepare(
        context=context,
    )

    assert len(builder.calls) == 1


def test_prepare_returns_builder_result_without_rewriting_it() -> None:
    prepared = _make_prepared_result()

    service = RetrievalQueryPreparationService(
        builder=SuccessfulBuilder(
            prepared
        )
    )

    result = service.prepare(
        context=_make_context(),
    )

    assert result is prepared


def test_service_does_not_mutate_input_context() -> None:
    context = _make_context()

    original_message = context.customer_message
    original_intent = context.intent_key
    original_entities = dict(
        context.entities
    )
    original_filters = context.filters

    service = RetrievalQueryPreparationService(
        builder=SuccessfulBuilder(
            _make_prepared_result()
        )
    )

    service.prepare(
        context=context,
    )

    assert (
        context.customer_message
        == original_message
    )

    assert (
        context.intent_key
        == original_intent
    )

    assert (
        dict(context.entities)
        == original_entities
    )

    assert (
        context.filters
        is original_filters
    )


# ---------------------------------------------------------------------------
# Context validation
# ---------------------------------------------------------------------------


def test_prepare_rejects_non_context_input() -> None:
    service = RetrievalQueryPreparationService(
        builder=SuccessfulBuilder(
            _make_prepared_result()
        )
    )

    with pytest.raises(
        TypeError,
        match=(
            "context must be a "
            "RetrievalQueryContext instance"
        ),
    ):
        service.prepare(
            context=cast(
                RetrievalQueryContext,
                "refund",
            ),
        )


def test_invalid_context_does_not_invoke_builder() -> None:
    builder = SuccessfulBuilder(
        _make_prepared_result()
    )

    service = RetrievalQueryPreparationService(
        builder=builder,
    )

    with pytest.raises(TypeError):
        service.prepare(
            context=cast(
                RetrievalQueryContext,
                object(),
            ),
        )

    assert builder.calls == []


# ---------------------------------------------------------------------------
# Domain-error propagation
# ---------------------------------------------------------------------------


def test_query_preparation_domain_error_is_preserved() -> None:
    service = RetrievalQueryPreparationService(
        builder=DomainFailingBuilder(),
    )

    with pytest.raises(
        QueryConstructionError,
        match="Unable to construct",
    ):
        service.prepare(
            context=_make_context(),
        )


def test_domain_error_is_not_wrapped_as_unexpected_error() -> None:
    service = RetrievalQueryPreparationService(
        builder=DomainFailingBuilder(),
    )

    with pytest.raises(
        QueryConstructionError
    ) as exc_info:
        service.prepare(
            context=_make_context(),
        )

    assert not isinstance(
        exc_info.value,
        UnexpectedRetrievalQueryPreparationError,
    )


# ---------------------------------------------------------------------------
# Unexpected-error translation
# ---------------------------------------------------------------------------


def test_unexpected_builder_error_is_translated() -> None:
    service = RetrievalQueryPreparationService(
        builder=UnexpectedFailingBuilder(),
    )

    with pytest.raises(
        UnexpectedRetrievalQueryPreparationError,
        match=(
            "Unexpected failure while "
            "preparing retrieval query"
        ),
    ):
        service.prepare(
            context=_make_context(),
        )


def test_unexpected_error_preserves_original_exception_as_cause() -> None:
    service = RetrievalQueryPreparationService(
        builder=UnexpectedFailingBuilder(),
    )

    with pytest.raises(
        UnexpectedRetrievalQueryPreparationError
    ) as exc_info:
        service.prepare(
            context=_make_context(),
        )

    cause = exc_info.value.__cause__

    assert isinstance(
        cause,
        RuntimeError,
    )

    assert str(cause) == (
        "unexpected implementation failure"
    )


# ---------------------------------------------------------------------------
# Invalid builder output
# ---------------------------------------------------------------------------


def test_invalid_builder_result_type_is_rejected() -> None:
    service = RetrievalQueryPreparationService(
        builder=InvalidResultBuilder(),
    )

    with pytest.raises(
        UnexpectedRetrievalQueryPreparationError,
        match=(
            "builder returned an invalid "
            "result type"
        ),
    ):
        service.prepare(
            context=_make_context(),
        )


def test_invalid_result_is_not_returned_to_caller() -> None:
    service = RetrievalQueryPreparationService(
        builder=InvalidResultBuilder(),
    )

    with pytest.raises(
        UnexpectedRetrievalQueryPreparationError
    ):
        service.prepare(
            context=_make_context(),
        )


# ---------------------------------------------------------------------------
# Architectural boundary
# ---------------------------------------------------------------------------


def test_service_supports_arbitrary_builder_implementation() -> None:
    service = RetrievalQueryPreparationService(
        builder=CustomBuilder(),
    )

    result = service.prepare(
        context=RetrievalQueryContext(
            customer_message=(
                "Can I claim warranty?"
            ),
            intent_key="warranty_claim",
        ),
    )

    assert result.original_query == (
        "Can I claim warranty?"
    )

    assert result.semantic_query == (
        "semantic::Can I claim warranty?"
    )

    assert result.lexical_queries == (
        "custom lexical query",
    )


def test_service_contains_no_intent_specific_behavior() -> None:
    service = RetrievalQueryPreparationService(
        builder=CustomBuilder(),
    )

    contexts = (
        RetrievalQueryContext(
            customer_message="Question one",
            intent_key="refund_request",
        ),
        RetrievalQueryContext(
            customer_message="Question two",
            intent_key="future_unknown_intent",
        ),
    )

    first = service.prepare(
        context=contexts[0],
    )

    second = service.prepare(
        context=contexts[1],
    )

    assert first.semantic_query == (
        "semantic::Question one"
    )

    assert second.semantic_query == (
        "semantic::Question two"
    )