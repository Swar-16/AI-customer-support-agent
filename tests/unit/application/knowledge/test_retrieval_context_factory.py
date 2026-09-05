from __future__ import annotations

from uuid import uuid4

import pytest

from packages.application.knowledge.models import (
    KnowledgeRetrievalRequest,
)
from packages.application.knowledge.retrieval_context_factory import (
    KnowledgeRetrievalContextFactory,
)
from packages.knowledge.retrieval.models import (
    RetrievalFilters,
)
from packages.knowledge.retrieval.query.models import (
    RetrievalQueryContext,
)


def test_create_translates_application_request_to_retrieval_context() -> None:
    factory = KnowledgeRetrievalContextFactory()

    filters = RetrievalFilters(
        content_types=("policy",),
        visibilities=("customer",),
    )

    request = KnowledgeRetrievalRequest(
        customer_message="How long does a refund take?",
        intent_key="refund_request",
        entities={
            "issue_type": "refund delay",
            "order_id": "ORD-123",
        },
        filters=filters,
        conversation_context="Customer already requested a refund.",
    )

    context = factory.create(request=request)

    assert isinstance(context, RetrievalQueryContext)
    assert context.customer_message == "How long does a refund take?"
    assert context.intent_key == "refund_request"
    assert context.entities == {
        "issue_type": "refund delay",
        "order_id": "ORD-123",
    }
    assert context.filters == filters
    assert context.conversation_context == (
        "Customer already requested a refund."
    )


def test_create_preserves_trusted_filters_exactly() -> None:
    factory = KnowledgeRetrievalContextFactory()

    document_id = uuid4()

    filters = RetrievalFilters(
        content_types=("policy", "faq"),
        visibilities=("customer",),
        document_ids=(document_id,),
        metadata={
            "region": "india",
            "product": "payments",
        },
    )

    request = KnowledgeRetrievalRequest(
        customer_message="What is the refund policy?",
        intent_key="refund_request",
        filters=filters,
    )

    context = factory.create(request=request)

    assert context.filters == filters


def test_create_does_not_convert_entities_into_filters() -> None:
    factory = KnowledgeRetrievalContextFactory()

    filters = RetrievalFilters(
        metadata={
            "region": "india",
        },
    )

    request = KnowledgeRetrievalRequest(
        customer_message="Where is order ORD-123?",
        intent_key="order_status",
        entities={
            "order_id": "ORD-123",
            "region": "europe",
            "email": "customer@example.com",
        },
        filters=filters,
    )

    context = factory.create(request=request)

    assert context.entities["order_id"] == "ORD-123"
    assert context.entities["region"] == "europe"
    assert context.entities["email"] == "customer@example.com"

    assert context.filters == filters
    assert context.filters.metadata == {
        "region": "india",
    }


def test_create_preserves_empty_entities() -> None:
    factory = KnowledgeRetrievalContextFactory()

    request = KnowledgeRetrievalRequest(
        customer_message="What payment methods do you accept?",
        intent_key="general_question",
    )

    context = factory.create(request=request)

    assert context.entities == {}


def test_create_preserves_none_conversation_context() -> None:
    factory = KnowledgeRetrievalContextFactory()

    request = KnowledgeRetrievalRequest(
        customer_message="Can I exchange an item?",
        intent_key="return_exchange",
        conversation_context=None,
    )

    context = factory.create(request=request)

    assert context.conversation_context is None


def test_create_does_not_mutate_request() -> None:
    factory = KnowledgeRetrievalContextFactory()

    request = KnowledgeRetrievalRequest(
        customer_message="How do I cancel my subscription?",
        intent_key="subscription_issue",
        entities={
            "issue_type": "cancellation",
        },
    )

    original_message = request.customer_message
    original_intent = request.intent_key
    original_entities = dict(request.entities)
    original_filters = request.filters
    original_conversation_context = request.conversation_context

    factory.create(request=request)

    assert request.customer_message == original_message
    assert request.intent_key == original_intent
    assert dict(request.entities) == original_entities
    assert request.filters == original_filters
    assert request.conversation_context == original_conversation_context


def test_create_rejects_non_request_object() -> None:
    factory = KnowledgeRetrievalContextFactory()

    with pytest.raises(
        TypeError,
        match="request must be a KnowledgeRetrievalRequest instance",
    ):
        factory.create(request="invalid")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "invalid_request",
    [
        None,
        {},
        [],
        object(),
    ],
)
def test_create_rejects_invalid_request_types(
    invalid_request: object,
) -> None:
    factory = KnowledgeRetrievalContextFactory()

    with pytest.raises(TypeError):
        factory.create(
            request=invalid_request,  # type: ignore[arg-type]
        )