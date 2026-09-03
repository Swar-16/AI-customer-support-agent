from __future__ import annotations

from types import MappingProxyType
from uuid6 import uuid7

import pytest

from packages.ai.intent.schemas import IntentEntities, IntentResult
from packages.ai.intent.taxonomy import IntentType
from packages.application.knowledge.ai_request_factory import (
    AIKnowledgeRetrievalRequestFactory,
)
from packages.application.knowledge.models import (
    KnowledgeRetrievalRequest,
)
from packages.knowledge.retrieval.models import (
    RetrievalFilters,
)


def make_intent_result(
    *,
    intent: IntentType = IntentType.REFUND_REQUEST,
    confidence: float = 0.95,
    entities: IntentEntities | None = None,
    needs_clarification: bool | None = None,
    reason_summary: str = "Customer request classified.",
) -> IntentResult:
    """
    Construct a valid IntentResult using the real application schema.

    Keeping this helper local to the test module makes individual tests focus
    on the adapter behavior rather than repeated intent-schema boilerplate.
    """
    if needs_clarification is None:
        needs_clarification = intent is IntentType.UNKNOWN
        
    return IntentResult(
        intent=intent,
        confidence=confidence,
        entities=entities or IntentEntities(),
        needs_clarification=needs_clarification,
        reason_summary=reason_summary,
    )


class TestAIKnowledgeRetrievalRequestFactory:
    def test_create_translates_intent_result_into_application_request(
        self,
    ) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        intent_result = make_intent_result(
            intent=IntentType.REFUND_REQUEST,
            entities=IntentEntities(
                issue_type="refund delay",
                order_id="ORD-123",
            )
        )

        request = factory.create(
            customer_message="How long will my refund take?",
            intent_result=intent_result,
        )

        assert isinstance(request, KnowledgeRetrievalRequest)
        assert request.customer_message == "How long will my refund take?"
        assert request.intent_key == IntentType.REFUND_REQUEST.value
        assert request.entities == {
            "issue_type": "refund delay",
            "order_id": "ORD-123",
        }
        assert request.filters == RetrievalFilters()
        assert request.conversation_context is None

    def test_create_preserves_trusted_filters_exactly(
        self,
    ) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        document_id = uuid7()

        filters = RetrievalFilters(
            content_types=("policy", "faq"),
            visibilities=("customer",),
            document_ids=(document_id,),
            metadata={
                "region": "india",
                "product": "payments",
            },
        )

        request = factory.create(
            customer_message="What is the refund policy?",
            intent_result=make_intent_result(),
            trusted_filters=filters,
        )

        assert request.filters == filters
        assert request.filters is filters

    def test_create_uses_empty_filters_when_none_are_supplied(
        self,
    ) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        request = factory.create(
            customer_message="What is your refund policy?",
            intent_result=make_intent_result(),
            trusted_filters=None,
        )

        assert request.filters == RetrievalFilters()

    def test_ai_entities_never_become_trusted_filters(
        self,
    ) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        trusted_filters = RetrievalFilters(
            metadata={
                "region": "india",
                "product": "payments",
            },
        )

        intent_result = make_intent_result(
            entities=IntentEntities(
                issue_type="refund delay",
                attributes={
                    "region": "germany",
                    "product": "premium",
                },
            )
        )

        request = factory.create(
            customer_message="What is the refund policy for my order?",
            intent_result=intent_result,
            trusted_filters=trusted_filters,
        )

        assert request.entities == {
            "issue_type": "refund delay",
            "region": "germany",
            "product": "premium",
        }

        assert request.filters == trusted_filters
        assert request.filters.metadata == {
            "region": "india",
            "product": "payments",
        }

    def test_create_preserves_conversation_context(
        self,
    ) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        request = factory.create(
            customer_message="How long will it take?",
            intent_result=make_intent_result(),
            conversation_context=(
                "Customer previously asked about a pending refund."
            ),
        )

        assert request.conversation_context == (
            "Customer previously asked about a pending refund."
        )

    def test_create_preserves_none_conversation_context(
        self,
    ) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        request = factory.create(
            customer_message="Can I return this item?",
            intent_result=make_intent_result(
                intent=IntentType.RETURN_EXCHANGE,
            ),
        )

        assert request.conversation_context is None

    @pytest.mark.parametrize(
        ("intent", "expected_key"),
        [
            (
                IntentType.REFUND_REQUEST,
                "refund_request",
            ),
            (
                IntentType.GENERAL_QUESTION,
                "general_question",
            ),
            (
                IntentType.PRIVACY_SECURITY,
                "privacy_security",
            ),
            (
                IntentType.RETURN_EXCHANGE,
                "return_exchange",
            ),
            (
                IntentType.UNKNOWN,
                "unknown",
            ),
        ],
    )
    def test_create_uses_canonical_intent_value_as_intent_key(
        self,
        intent: IntentType,
        expected_key: str,
    ) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        request = factory.create(
            customer_message="Customer message",
            intent_result=make_intent_result(
                intent=intent,
            ),
        )

        assert request.intent_key == expected_key
        
    def test_create_flattens_typed_intent_entities(self) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        intent_result = make_intent_result(
            entities=IntentEntities(
                order_id="ORD-123",
                transaction_id="TXN-456",
                subscription_id="SUB-789",
                account_id="ACC-101",
                issue_type="refund delay",
            ),
        )

        request = factory.create(
            customer_message="Where is my refund?",
            intent_result=intent_result,
        )

        assert request.entities == {
            "order_id": "ORD-123",
            "transaction_id": "TXN-456",
            "subscription_id": "SUB-789",
            "account_id": "ACC-101",
            "issue_type": "refund delay",
        }
        
    def test_create_omits_absent_typed_entities(self) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        intent_result = make_intent_result(
            entities=IntentEntities(
                issue_type="refund delay",
            ),
        )

        request = factory.create(
            customer_message="Where is my refund?",
            intent_result=intent_result,
        )

        assert request.entities == {
            "issue_type": "refund delay",
        }
        
    def test_create_includes_string_entity_attributes(self) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        intent_result = make_intent_result(
            entities=IntentEntities(
                issue_type="refund delay",
                attributes={
                    "region": "germany",
                    "product": "premium",
                },
            ),
        )

        request = factory.create(
            customer_message="What applies to my refund?",
            intent_result=intent_result,
        )

        assert request.entities == {
            "issue_type": "refund delay",
            "region": "germany",
            "product": "premium",
        }
        
    def test_attributes_cannot_override_canonical_entities(self) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        intent_result = make_intent_result(
            entities=IntentEntities(
                order_id="ORD-TRUSTED-SEMANTIC",
                issue_type="refund delay",
                attributes={
                    "order_id": "ORD-OTHER",
                    "issue_type": "different issue",
                },
            ),
        )

        request = factory.create(
            customer_message="Where is my refund?",
            intent_result=intent_result,
        )

        assert request.entities["order_id"] == "ORD-TRUSTED-SEMANTIC"
        assert request.entities["issue_type"] == "refund delay"

    def test_unknown_intent_is_translated_without_making_routing_decision(
        self,
    ) -> None:
        """
        The adapter is intentionally not a routing policy.

        UNKNOWN would normally be stopped by the decision layer before this
        adapter is invoked. If it reaches the adapter, however, translation
        remains deterministic and side-effect free.
        """
        factory = AIKnowledgeRetrievalRequestFactory()

        request = factory.create(
            customer_message="Something happened.",
            intent_result=make_intent_result(
                intent=IntentType.UNKNOWN,
                confidence=0.20,
                needs_clarification=True,
                reason_summary="Intent could not be determined.",
            ),
        )

        assert request.intent_key == IntentType.UNKNOWN.value
        assert request.customer_message == "Something happened."

    def test_created_request_entities_are_immutable(
        self,
    ) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        request = factory.create(
            customer_message="Where is my refund?",
            intent_result=make_intent_result(
                entities={
                    "issue_type": "refund delay",
                },
            ),
        )

        assert isinstance(request.entities, MappingProxyType)

        with pytest.raises(TypeError):
            request.entities["issue_type"] = "changed"  # type: ignore[index]

    def test_created_request_is_isolated_from_source_entity_mutation(
        self,
    ) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        source_entities = {
            "issue_type": "refund delay",
            "order_id": "ORD-123",
        }

        intent_result = make_intent_result(
            entities=source_entities,
        )

        request = factory.create(
            customer_message="Where is my refund?",
            intent_result=intent_result,
        )

        source_entities["issue_type"] = "something else"
        source_entities["new_field"] = "new value"

        assert request.entities == {
            "issue_type": "refund delay",
            "order_id": "ORD-123",
        }

    def test_create_does_not_mutate_intent_result(
        self,
    ) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        intent_result = make_intent_result(
            entities={
                "issue_type": "refund delay",
                "order_id": "ORD-123",
            },
        )

        original_intent = intent_result.intent
        original_confidence = intent_result.confidence
        original_entities = dict(intent_result.entities)
        original_needs_clarification = intent_result.needs_clarification
        original_reason_summary = intent_result.reason_summary

        factory.create(
            customer_message="Where is my refund?",
            intent_result=intent_result,
        )

        assert intent_result.intent == original_intent
        assert intent_result.confidence == original_confidence
        assert dict(intent_result.entities) == original_entities
        assert (
            intent_result.needs_clarification
            == original_needs_clarification
        )
        assert intent_result.reason_summary == original_reason_summary

    @pytest.mark.parametrize(
        "invalid_intent_result",
        [
            None,
            "refund_request",
            {},
            [],
            object(),
        ],
    )
    def test_create_rejects_invalid_intent_result_type(
        self,
        invalid_intent_result: object,
    ) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        with pytest.raises(
            TypeError,
            match="intent_result must be an IntentResult instance",
        ):
            factory.create(
                customer_message="What is your refund policy?",
                intent_result=invalid_intent_result,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "invalid_filters",
        [
            {},
            {"region": "india"},
            "customer",
            [],
            object(),
        ],
    )
    def test_create_rejects_invalid_trusted_filters(
        self,
        invalid_filters: object,
    ) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        with pytest.raises(
            TypeError,
            match=(
                "trusted_filters must be a RetrievalFilters "
                "instance or None"
            ),
        ):
            factory.create(
                customer_message="What is your refund policy?",
                intent_result=make_intent_result(),
                trusted_filters=invalid_filters,  # type: ignore[arg-type]
            )

    def test_invalid_customer_message_is_rejected_by_application_model(
        self,
    ) -> None:
        """
        Customer-message validation belongs to KnowledgeRetrievalRequest.

        The adapter deliberately delegates that invariant rather than
        duplicating validation logic.
        """
        factory = AIKnowledgeRetrievalRequestFactory()

        with pytest.raises(ValueError):
            factory.create(
                customer_message="   ",
                intent_result=make_intent_result(),
            )

    def test_invalid_conversation_context_is_rejected_by_application_model(
        self,
    ) -> None:
        factory = AIKnowledgeRetrievalRequestFactory()

        with pytest.raises(TypeError):
            factory.create(
                customer_message="What is your refund policy?",
                intent_result=make_intent_result(),
                conversation_context=123,  # type: ignore[arg-type]
            )