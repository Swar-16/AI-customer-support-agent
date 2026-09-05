from __future__ import annotations

import pytest

from packages.ai.intent.schemas import IntentEntities, IntentResult
from packages.ai.intent.taxonomy import IntentType
from packages.application.composition.knowledge_application_factory import (
    KnowledgeApplicationComponents,
    create_knowledge_application_components,
)
from packages.application.knowledge.ai_request_factory import (
    AIKnowledgeRetrievalRequestFactory,
)
from packages.application.knowledge.retrieval_context_factory import (
    KnowledgeRetrievalContextFactory,
)
from packages.application.knowledge.retrieval_context_service import (
    KnowledgeRetrievalContextService,
)
from packages.knowledge.retrieval.models import RetrievalFilters
from packages.knowledge.retrieval.query.models import RetrievalQueryContext


def make_intent_result(
    *,
    intent: IntentType = IntentType.REFUND_REQUEST,
    confidence: float = 0.95,
    entities: IntentEntities | None = None,
    needs_clarification: bool | None = None,
    reason_summary: str = "Customer request classified.",
) -> IntentResult:
    if needs_clarification is None:
        needs_clarification = intent is IntentType.UNKNOWN

    return IntentResult(
        intent=intent,
        confidence=confidence,
        entities=entities or IntentEntities(),
        needs_clarification=needs_clarification,
        reason_summary=reason_summary,
    )


class TestKnowledgeApplicationFactory:
    def test_create_default_components(self) -> None:
        components = create_knowledge_application_components()

        assert isinstance(
            components,
            KnowledgeApplicationComponents,
        )

        assert isinstance(
            components.retrieval_context_service,
            KnowledgeRetrievalContextService,
        )

    def test_default_components_are_independent_between_factory_calls(
        self,
    ) -> None:
        first = create_knowledge_application_components()
        second = create_knowledge_application_components()

        assert first is not second
        assert (
            first.retrieval_context_service
            is not second.retrieval_context_service
        )

    def test_create_accepts_explicit_factories(self) -> None:
        ai_request_factory = AIKnowledgeRetrievalRequestFactory()
        retrieval_context_factory = KnowledgeRetrievalContextFactory()

        components = create_knowledge_application_components(
            ai_request_factory=ai_request_factory,
            retrieval_context_factory=retrieval_context_factory,
        )

        assert isinstance(
            components.retrieval_context_service,
            KnowledgeRetrievalContextService,
        )

    def test_create_accepts_explicit_ai_request_factory_only(
        self,
    ) -> None:
        ai_request_factory = AIKnowledgeRetrievalRequestFactory()

        components = create_knowledge_application_components(
            ai_request_factory=ai_request_factory,
        )

        assert isinstance(
            components.retrieval_context_service,
            KnowledgeRetrievalContextService,
        )

    def test_create_accepts_explicit_retrieval_context_factory_only(
        self,
    ) -> None:
        retrieval_context_factory = KnowledgeRetrievalContextFactory()

        components = create_knowledge_application_components(
            retrieval_context_factory=retrieval_context_factory,
        )

        assert isinstance(
            components.retrieval_context_service,
            KnowledgeRetrievalContextService,
        )


class TestKnowledgeApplicationFactoryValidation:
    @pytest.mark.parametrize(
        "invalid_ai_request_factory",
        [
            object(),
            "factory",
            {},
            [],
            123,
        ],
    )
    def test_rejects_invalid_ai_request_factory(
        self,
        invalid_ai_request_factory: object,
    ) -> None:
        with pytest.raises(
            TypeError,
            match=(
                "ai_request_factory must be an "
                "AIKnowledgeRetrievalRequestFactory instance"
            ),
        ):
            create_knowledge_application_components(
                ai_request_factory=invalid_ai_request_factory,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "invalid_context_factory",
        [
            object(),
            "factory",
            {},
            [],
            123,
        ],
    )
    def test_rejects_invalid_retrieval_context_factory(
        self,
        invalid_context_factory: object,
    ) -> None:
        with pytest.raises(
            TypeError,
            match=(
                "retrieval_context_factory must be a "
                "KnowledgeRetrievalContextFactory instance"
            ),
        ):
            create_knowledge_application_components(
                retrieval_context_factory=invalid_context_factory,  # type: ignore[arg-type]
            )


class TestKnowledgeApplicationFactoryFunctionalWiring:
    def test_composed_service_translates_ai_result_to_retrieval_context(
        self,
    ) -> None:
        components = create_knowledge_application_components()

        filters = RetrievalFilters(
            content_types=("policy", "faq"),
            visibilities=("customer",),
            metadata={
                "region": "india",
                "product": "payments",
            },
        )

        intent_result = make_intent_result(
            intent=IntentType.REFUND_REQUEST,
            entities=IntentEntities(
                order_id="ORD-123",
                issue_type="refund delay",
                attributes={
                    "payment_method": "credit card",
                },
            ),
        )

        context = components.retrieval_context_service.create(
            customer_message="How long will my refund take?",
            intent_result=intent_result,
            trusted_filters=filters,
            conversation_context=(
                "Customer previously said the refund was initiated."
            ),
        )

        assert isinstance(context, RetrievalQueryContext)

        assert context.customer_message == (
            "How long will my refund take?"
        )
        assert context.intent_key == IntentType.REFUND_REQUEST.value

        assert context.entities == {
            "order_id": "ORD-123",
            "issue_type": "refund delay",
            "payment_method": "credit card",
        }

        assert context.filters == filters

        assert context.conversation_context == (
            "Customer previously said the refund was initiated."
        )

    def test_composed_service_preserves_trusted_filter_boundary(
        self,
    ) -> None:
        components = create_knowledge_application_components()

        filters = RetrievalFilters(
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
            ),
        )

        context = components.retrieval_context_service.create(
            customer_message="What applies to my refund?",
            intent_result=intent_result,
            trusted_filters=filters,
        )

        assert context.entities["region"] == "germany"
        assert context.entities["product"] == "premium"

        assert context.filters.metadata == {
            "region": "india",
            "product": "payments",
        }

    def test_composed_service_supports_empty_entities(self) -> None:
        components = create_knowledge_application_components()

        context = components.retrieval_context_service.create(
            customer_message="What payment methods do you accept?",
            intent_result=make_intent_result(
                intent=IntentType.GENERAL_QUESTION,
            ),
        )

        assert context.entities == {}
        assert context.intent_key == "general_question"

    def test_composed_service_remains_policy_neutral_for_unknown_intent(
        self,
    ) -> None:
        """
        UNKNOWN would normally be stopped by the decision layer.

        The composition root must not introduce a second routing policy.
        It only composes translation infrastructure.
        """
        components = create_knowledge_application_components()

        context = components.retrieval_context_service.create(
            customer_message="Something happened.",
            intent_result=make_intent_result(
                intent=IntentType.UNKNOWN,
                confidence=0.20,
                needs_clarification=True,
                reason_summary="Intent could not be determined.",
            ),
        )

        assert context.intent_key == IntentType.UNKNOWN.value