from __future__ import annotations

from unittest.mock import Mock

import pytest

from packages.ai.intent.schemas import IntentEntities, IntentResult
from packages.ai.intent.taxonomy import IntentType
from packages.application.knowledge.ai_request_factory import (
    AIKnowledgeRetrievalRequestFactory,
)
from packages.application.knowledge.models import KnowledgeRetrievalRequest
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


def make_service() -> KnowledgeRetrievalContextService:
    return KnowledgeRetrievalContextService(
        ai_request_factory=AIKnowledgeRetrievalRequestFactory(),
        context_factory=KnowledgeRetrievalContextFactory(),
    )


class TestKnowledgeRetrievalContextService:
    def test_create_builds_complete_retrieval_context(self) -> None:
        service = make_service()

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

        filters = RetrievalFilters(
            content_types=("policy", "faq"),
            visibilities=("customer",),
            metadata={
                "region": "india",
                "product": "payments",
            },
        )

        context = service.create(
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

    def test_create_uses_empty_filters_when_none_are_supplied(
        self,
    ) -> None:
        service = make_service()

        context = service.create(
            customer_message="What is your refund policy?",
            intent_result=make_intent_result(),
        )

        assert context.filters == RetrievalFilters()

    def test_create_preserves_trusted_filters_exactly(self) -> None:
        service = make_service()

        filters = RetrievalFilters(
            content_types=("policy",),
            visibilities=("customer",),
            metadata={
                "region": "india",
            },
        )

        context = service.create(
            customer_message="What refund policy applies?",
            intent_result=make_intent_result(),
            trusted_filters=filters,
        )

        assert context.filters == filters

    def test_ai_entities_do_not_override_trusted_filters(
        self,
    ) -> None:
        service = make_service()

        intent_result = make_intent_result(
            entities=IntentEntities(
                issue_type="refund delay",
                attributes={
                    "region": "germany",
                    "product": "premium",
                },
            ),
        )

        filters = RetrievalFilters(
            metadata={
                "region": "india",
                "product": "payments",
            },
        )

        context = service.create(
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

    def test_create_preserves_conversation_context(self) -> None:
        service = make_service()

        context = service.create(
            customer_message="How long will it take?",
            intent_result=make_intent_result(),
            conversation_context=(
                "Customer previously asked about a pending refund."
            ),
        )

        assert context.conversation_context == (
            "Customer previously asked about a pending refund."
        )

    def test_create_preserves_none_conversation_context(self) -> None:
        service = make_service()

        context = service.create(
            customer_message="What is your refund policy?",
            intent_result=make_intent_result(),
        )

        assert context.conversation_context is None

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
        ],
    )
    def test_create_preserves_canonical_intent_key(
        self,
        intent: IntentType,
        expected_key: str,
    ) -> None:
        service = make_service()

        context = service.create(
            customer_message="Customer question",
            intent_result=make_intent_result(
                intent=intent,
            ),
        )

        assert context.intent_key == expected_key

    def test_unknown_intent_translation_remains_policy_neutral(
        self,
    ) -> None:
        """
        Routing policy belongs to the decision layer.

        This service only translates an already-supplied semantic result.
        It must not introduce a second UNKNOWN-intent routing rule.
        """
        service = make_service()

        context = service.create(
            customer_message="Something happened.",
            intent_result=make_intent_result(
                intent=IntentType.UNKNOWN,
                confidence=0.20,
                needs_clarification=True,
                reason_summary="Intent could not be determined.",
            ),
        )

        assert context.intent_key == IntentType.UNKNOWN.value

    def test_create_preserves_typed_and_extended_entity_hints(
        self,
    ) -> None:
        service = make_service()

        context = service.create(
            customer_message="Please check my refund.",
            intent_result=make_intent_result(
                entities=IntentEntities(
                    order_id="ORD-123",
                    transaction_id="TXN-456",
                    subscription_id="SUB-789",
                    account_id="ACC-101",
                    issue_type="refund delay",
                    attributes={
                        "payment_method": "credit card",
                    },
                ),
            ),
        )

        assert context.entities == {
            "order_id": "ORD-123",
            "transaction_id": "TXN-456",
            "subscription_id": "SUB-789",
            "account_id": "ACC-101",
            "issue_type": "refund delay",
            "payment_method": "credit card",
        }

    def test_create_returns_immutable_entity_mapping(self) -> None:
        service = make_service()

        context = service.create(
            customer_message="Where is my refund?",
            intent_result=make_intent_result(
                entities=IntentEntities(
                    order_id="ORD-123",
                    issue_type="refund delay",
                ),
            ),
        )

        with pytest.raises(TypeError):
            context.entities["issue_type"] = "changed"  # type: ignore[index]


class TestKnowledgeRetrievalContextServiceConstruction:
    def test_rejects_invalid_ai_request_factory(self) -> None:
        with pytest.raises(
            TypeError,
            match=(
                "ai_request_factory must be an "
                "AIKnowledgeRetrievalRequestFactory instance"
            ),
        ):
            KnowledgeRetrievalContextService(
                ai_request_factory=object(),  # type: ignore[arg-type]
                context_factory=KnowledgeRetrievalContextFactory(),
            )

    def test_rejects_invalid_context_factory(self) -> None:
        with pytest.raises(
            TypeError,
            match=(
                "context_factory must be a "
                "KnowledgeRetrievalContextFactory instance"
            ),
        ):
            KnowledgeRetrievalContextService(
                ai_request_factory=(
                    AIKnowledgeRetrievalRequestFactory()
                ),
                context_factory=object(),  # type: ignore[arg-type]
            )


class TestKnowledgeRetrievalContextServiceCoordination:
    def test_service_passes_application_request_to_context_factory(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ai_factory = AIKnowledgeRetrievalRequestFactory()
        context_factory = KnowledgeRetrievalContextFactory()

        request = KnowledgeRetrievalRequest(
            customer_message="What is your refund policy?",
            intent_key="refund_request",
        )

        expected_context = RetrievalQueryContext(
            customer_message="What is your refund policy?",
            intent_key="refund_request",
        )

        ai_create = Mock(return_value=request)
        context_create = Mock(return_value=expected_context)

        monkeypatch.setattr(
            ai_factory,
            "create",
            ai_create,
        )
        monkeypatch.setattr(
            context_factory,
            "create",
            context_create,
        )

        service = KnowledgeRetrievalContextService(
            ai_request_factory=ai_factory,
            context_factory=context_factory,
        )

        result = service.create(
            customer_message="What is your refund policy?",
            intent_result=make_intent_result(),
        )

        assert result is expected_context

        context_create.assert_called_once_with(
            request=request,
        )

    def test_service_passes_all_inputs_to_ai_request_factory(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ai_factory = AIKnowledgeRetrievalRequestFactory()
        context_factory = KnowledgeRetrievalContextFactory()

        filters = RetrievalFilters(
            metadata={
                "region": "india",
            },
        )

        intent_result = make_intent_result(
            entities=IntentEntities(
                issue_type="refund delay",
            ),
        )

        request = KnowledgeRetrievalRequest(
            customer_message="Where is my refund?",
            intent_key="refund_request",
            entities={
                "issue_type": "refund delay",
            },
            filters=filters,
            conversation_context="Refund was previously initiated.",
        )

        expected_context = RetrievalQueryContext(
            customer_message=request.customer_message,
            intent_key=request.intent_key,
            entities=request.entities,
            filters=request.filters,
            conversation_context=request.conversation_context,
        )

        ai_create = Mock(return_value=request)
        context_create = Mock(return_value=expected_context)

        monkeypatch.setattr(
            ai_factory,
            "create",
            ai_create,
        )
        monkeypatch.setattr(
            context_factory,
            "create",
            context_create,
        )

        service = KnowledgeRetrievalContextService(
            ai_request_factory=ai_factory,
            context_factory=context_factory,
        )

        result = service.create(
            customer_message="Where is my refund?",
            intent_result=intent_result,
            trusted_filters=filters,
            conversation_context="Refund was previously initiated.",
        )

        assert result is expected_context

        ai_create.assert_called_once_with(
            customer_message="Where is my refund?",
            intent_result=intent_result,
            trusted_filters=filters,
            conversation_context="Refund was previously initiated.",
        )

    def test_ai_factory_exception_propagates_without_calling_context_factory(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ai_factory = AIKnowledgeRetrievalRequestFactory()
        context_factory = KnowledgeRetrievalContextFactory()

        ai_create = Mock(
            side_effect=ValueError("invalid application request")
        )
        context_create = Mock()

        monkeypatch.setattr(
            ai_factory,
            "create",
            ai_create,
        )
        monkeypatch.setattr(
            context_factory,
            "create",
            context_create,
        )

        service = KnowledgeRetrievalContextService(
            ai_request_factory=ai_factory,
            context_factory=context_factory,
        )

        with pytest.raises(
            ValueError,
            match="invalid application request",
        ):
            service.create(
                customer_message="Where is my refund?",
                intent_result=make_intent_result(),
            )

        context_create.assert_not_called()

    def test_context_factory_exception_propagates(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ai_factory = AIKnowledgeRetrievalRequestFactory()
        context_factory = KnowledgeRetrievalContextFactory()

        request = KnowledgeRetrievalRequest(
            customer_message="Where is my refund?",
            intent_key="refund_request",
        )

        ai_create = Mock(return_value=request)
        context_create = Mock(
            side_effect=ValueError("invalid retrieval context")
        )

        monkeypatch.setattr(
            ai_factory,
            "create",
            ai_create,
        )
        monkeypatch.setattr(
            context_factory,
            "create",
            context_create,
        )

        service = KnowledgeRetrievalContextService(
            ai_request_factory=ai_factory,
            context_factory=context_factory,
        )

        with pytest.raises(
            ValueError,
            match="invalid retrieval context",
        ):
            service.create(
                customer_message="Where is my refund?",
                intent_result=make_intent_result(),
            )

        context_create.assert_called_once_with(
            request=request,
        )