from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import Mock, create_autospec
from uuid6 import uuid7

import pytest

from packages.ai.decision.policies import RetrievalKind
from packages.ai.decision.schemas import (
    DecisionReasonCode,
    DecisionResult,
    DecisionType,
)
from packages.ai.generation.generator import (
    GroundedGenerationError,
    GroundedResponseGenerator,
)
from packages.ai.generation.models import (
    Citation,
    GroundedGenerationRequest,
    GroundedGenerationResult,
    GroundingStatus,
)
from packages.ai.intent.schemas import IntentResult
from packages.ai.intent.taxonomy import IntentType
from packages.ai.orchestration.state import (
    EvidenceSourceType,
    RetrievedEvidence,
)
from packages.application.ai.answer_service import (
    AnswerService,
    AnswerServiceResult,
    AnswerServiceRequest,
    InvalidAnswerRequestError,
    InvalidRetrievalDecisionError,
    UnsupportedAnswerDecisionError,
    UnsupportedRetrievalKindError,
)
from packages.application.knowledge.evidence_mapper import (
    KnowledgeEvidenceMapper,
)
from packages.application.knowledge.retrieval_context_service import (
    KnowledgeRetrievalContextService,
)
from packages.knowledge.retrieval.application.build_grounding_context import (
    BuildGroundingContext,
)
from packages.knowledge.retrieval.context.models import (
    GroundingContext,
    GroundingContextBlock,
)
from packages.knowledge.retrieval.errors import RetrievalPipelineError
from packages.knowledge.retrieval.models import (
    RetrievalFilters,
    RetrievalQuery,
)
from packages.knowledge.retrieval.query.models import (
    PreparedRetrievalQuery,
    RetrievalQueryContext,
)
from packages.knowledge.retrieval.query.service import (
    RetrievalQueryPreparationService,
)


# ===========================================================================
# Canonical domain helpers
# ===========================================================================


def make_intent(
    *,
    intent_type: IntentType = IntentType.REFUND_REQUEST,
    confidence: float = 0.95,
) -> IntentResult:
    return IntentResult(
        intent=intent_type,
        confidence=confidence,
        needs_clarification=False,
        reason_summary=(
            "Customer is asking about refund processing."
        ),
    )


def make_knowledge_decision(
    *,
    retrieval_kind: object = RetrievalKind.KNOWLEDGE.value,
) -> DecisionResult:
    return DecisionResult(
        decision=DecisionType.RETRIEVE_INFORMATION,
        reason_code=(
            DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED
        ),
        reason_summary=(
            "Published customer-support knowledge is required."
        ),
        confidence=0.95,
        metadata={
            "retrieval_kind": retrieval_kind,
        },
    )


def make_operational_decision() -> DecisionResult:
    return make_knowledge_decision(
        retrieval_kind=RetrievalKind.OPERATIONAL.value,
    )


def make_answer_decision() -> DecisionResult:
    return DecisionResult(
        decision=DecisionType.ANSWER,
        reason_code=(
            DecisionReasonCode.DIRECT_INFORMATIONAL_RESPONSE
        ),
        reason_summary="Direct answer is appropriate.",
        confidence=0.95,
        metadata={},
    )


def make_clarification_decision() -> DecisionResult:
    return DecisionResult(
        decision=DecisionType.ASK_CLARIFICATION,
        reason_code=(
            DecisionReasonCode.MISSING_REQUIRED_INFORMATION
        ),
        reason_summary=(
            "Additional information is required."
        ),
        confidence=0.95,
        required_information=("order_id",),
        metadata={},
    )


def make_request(
    *,
    customer_message: str = "How long does my refund take?",
    intent_result: IntentResult | None = None,
    decision_result: DecisionResult | None = None,
    trusted_filters: RetrievalFilters | None = None,
    conversation_context: str | None = None,
) -> AnswerServiceRequest:
    return AnswerServiceRequest(
        customer_message=customer_message,
        intent_result=intent_result or make_intent(),
        decision_result=(
            decision_result or make_knowledge_decision()
        ),
        trusted_filters=trusted_filters,
        conversation_context=conversation_context,
    )


def make_retrieval_context(
    *,
    customer_message: str = "How long does my refund take?",
    filters: RetrievalFilters | None = None,
    conversation_context: str | None = None,
) -> RetrievalQueryContext:
    return RetrievalQueryContext(
        customer_message=customer_message,
        intent_key=IntentType.REFUND_REQUEST.value,
        entities={},
        filters=filters or RetrievalFilters(),
        conversation_context=conversation_context,
    )


def make_prepared_query(
    *,
    original_query: str = "How long does my refund take?",
    filters: RetrievalFilters | None = None,
) -> PreparedRetrievalQuery:
    return PreparedRetrievalQuery(
        original_query=original_query,
        semantic_query=original_query,
        lexical_queries=("refund processing time",),
        filters=filters or RetrievalFilters(),
    )


def make_canonical_query(
    *,
    text: str = "How long does my refund take?",
    filters: RetrievalFilters | None = None,
) -> RetrievalQuery:
    return RetrievalQuery(
        text=text,
        filters=filters or RetrievalFilters(),
    )


def make_grounding_block(
    *,
    content: str = (
        "Approved refunds are processed within "
        "five business days."
    ),
) -> GroundingContextBlock:
    return GroundingContextBlock(
        chunk_id=uuid7(),
        version_id=uuid7(),
        document_id=uuid7(),
        chunk_index=0,
        content=content,
        document_title="Refund Policy",
        section_title="Processing Time",
        metadata={
            "language": "en",
        },
        retrieval_score=0.91,
    )


def make_grounding_context(
    *,
    query: RetrievalQuery | None = None,
    blocks: tuple[GroundingContextBlock, ...] | None = None,
) -> GroundingContext:
    resolved_blocks = (
        (make_grounding_block(),)
        if blocks is None
        else blocks
    )

    return GroundingContext(
        query=query or make_canonical_query(),
        blocks=resolved_blocks,
        estimated_token_count=(
            100 if resolved_blocks else 0
        ),
        truncated=False,
    )


def make_evidence(
    *,
    source_id: str = "chunk-1",
    content: str = (
        "Approved refunds are processed within "
        "five business days."
    ),
) -> RetrievedEvidence:
    return RetrievedEvidence(
        source_type=EvidenceSourceType.KNOWLEDGE,
        source_id=source_id,
        title="Refund Policy",
        section="Processing Time",
        content=content,
        relevance_score=0.91,
        metadata={
            "document_id": "document-1",
            "version_id": "version-1",
        },
    )


def make_generation_result(
    *,
    evidence_present: bool = True,
) -> GroundedGenerationResult:
    if evidence_present:
        return GroundedGenerationResult(
            answer=(
                "Approved refunds are processed within "
                "five business days."
            ),
            grounding_status=GroundingStatus.GROUNDED,
            citations=(
                Citation(
                    source_id="chunk-1",
                    title="Refund Policy",
                    section="Processing Time",
                ),
            ),
        )

    return GroundedGenerationResult(
        answer=(
            "I do not have enough verified information "
            "to answer that reliably."
        ),
        grounding_status=(
            GroundingStatus.INSUFFICIENT_EVIDENCE
        ),
        citations=(),
    )


# ===========================================================================
# Collaborator fixtures
# ===========================================================================


@pytest.fixture
def retrieval_context_service():
    return create_autospec(
        KnowledgeRetrievalContextService,
        instance=True,
        spec_set=True,
    )


@pytest.fixture
def query_preparation_service():
    return create_autospec(
        RetrievalQueryPreparationService,
        instance=True,
        spec_set=True,
    )


@pytest.fixture
def build_grounding_context():
    return create_autospec(
        BuildGroundingContext,
        instance=True,
        spec_set=True,
    )


@pytest.fixture
def evidence_mapper():
    return create_autospec(
        KnowledgeEvidenceMapper,
        instance=True,
        spec_set=True,
    )


@pytest.fixture
def response_generator():
    return create_autospec(
        GroundedResponseGenerator,
        instance=True,
        spec_set=True,
    )


@pytest.fixture
def service(
    retrieval_context_service,
    query_preparation_service,
    build_grounding_context,
    evidence_mapper,
    response_generator,
):
    return AnswerService(
        retrieval_context_service=(
            retrieval_context_service
        ),
        query_preparation_service=(
            query_preparation_service
        ),
        build_grounding_context=(
            build_grounding_context
        ),
        evidence_mapper=evidence_mapper,
        response_generator=response_generator,
    )


def configure_knowledge_happy_path(
    *,
    retrieval_context_service,
    query_preparation_service,
    build_grounding_context,
    evidence_mapper,
    response_generator,
    filters: RetrievalFilters | None = None,
    conversation_context: str | None = None,
):
    retrieval_context = make_retrieval_context(
        filters=filters,
        conversation_context=conversation_context,
    )

    prepared_query = make_prepared_query(
        filters=filters,
    )

    canonical_query = make_canonical_query(
        filters=filters,
    )

    grounding_context = make_grounding_context(
        query=canonical_query,
    )

    evidence = (
        make_evidence(),
    )

    generation = make_generation_result()

    retrieval_context_service.create.return_value = (
        retrieval_context
    )

    query_preparation_service.prepare.return_value = (
        prepared_query
    )

    build_grounding_context.build.return_value = (
        grounding_context
    )

    evidence_mapper.map.return_value = evidence

    response_generator.generate.return_value = generation

    return {
        "retrieval_context": retrieval_context,
        "prepared_query": prepared_query,
        "grounding_context": grounding_context,
        "evidence": evidence,
        "generation": generation,
    }


# ===========================================================================
# Request contract
# ===========================================================================


class TestAnswerServiceRequest:
    def test_valid_request_is_created(self):
        request = make_request()

        assert (
            request.customer_message
            == "How long does my refund take?"
        )
        assert isinstance(
            request.intent_result,
            IntentResult,
        )
        assert isinstance(
            request.decision_result,
            DecisionResult,
        )

    def test_customer_message_is_trimmed(self):
        request = make_request(
            customer_message="  Refund timing?  ",
        )

        assert request.customer_message == "Refund timing?"

    @pytest.mark.parametrize(
        "message",
        [
            "",
            "   ",
            "\n\t ",
        ],
    )
    def test_blank_customer_message_rejected(
        self,
        message,
    ):
        with pytest.raises(
            ValueError,
            match="customer_message cannot be empty",
        ):
            make_request(
                customer_message=message,
            )

    def test_non_string_customer_message_rejected(self):
        with pytest.raises(
            TypeError,
            match="customer_message",
        ):
            AnswerServiceRequest(
                customer_message=123,  # type: ignore[arg-type]
                intent_result=make_intent(),
                decision_result=make_knowledge_decision(),
            )

    def test_invalid_intent_result_rejected(self):
        with pytest.raises(
            TypeError,
            match="intent_result",
        ):
            AnswerServiceRequest(
                customer_message="Refund?",
                intent_result=object(),  # type: ignore[arg-type]
                decision_result=make_knowledge_decision(),
            )

    def test_invalid_decision_result_rejected(self):
        with pytest.raises(
            TypeError,
            match="decision_result",
        ):
            AnswerServiceRequest(
                customer_message="Refund?",
                intent_result=make_intent(),
                decision_result=object(),  # type: ignore[arg-type]
            )

    def test_invalid_trusted_filters_rejected(self):
        with pytest.raises(
            TypeError,
            match="trusted_filters",
        ):
            make_request(
                trusted_filters=object(),  # type: ignore[arg-type]
            )

    def test_conversation_context_is_trimmed(self):
        request = make_request(
            conversation_context=(
                "  Customer previously asked about refund.  "
            ),
        )

        assert request.conversation_context == (
            "Customer previously asked about refund."
        )

    def test_blank_conversation_context_becomes_none(self):
        request = make_request(
            conversation_context="   ",
        )

        assert request.conversation_context is None

    def test_non_string_conversation_context_rejected(
        self,
    ):
        with pytest.raises(
            TypeError,
            match="conversation_context",
        ):
            make_request(
                conversation_context=123,  # type: ignore[arg-type]
            )

    def test_request_is_immutable(self):
        request = make_request()

        with pytest.raises(
            (FrozenInstanceError, AttributeError),
        ):
            request.customer_message = "changed"  # type: ignore[misc]


# ===========================================================================
# Result contract
# ===========================================================================


class TestAnswerServiceResult:
    def test_valid_result_is_created(self):
        evidence = (
            make_evidence(),
        )

        generation = make_generation_result()

        result = AnswerServiceResult(
            evidence=evidence,
            generation=generation,
        )

        assert result.evidence is evidence
        assert result.generation is generation

    def test_evidence_must_be_tuple(self):
        with pytest.raises(
            TypeError,
            match="evidence must be a tuple",
        ):
            AnswerServiceResult(
                evidence=[make_evidence()],  # type: ignore[arg-type]
                generation=make_generation_result(),
            )

    def test_all_evidence_items_must_be_retrieved_evidence(
        self,
    ):
        with pytest.raises(
            TypeError,
            match="RetrievedEvidence",
        ):
            AnswerServiceResult(
                evidence=(object(),),  # type: ignore[arg-type]
                generation=make_generation_result(),
            )

    def test_generation_must_have_correct_type(self):
        with pytest.raises(
            TypeError,
            match="GroundedGenerationResult",
        ):
            AnswerServiceResult(
                evidence=(),
                generation=object(),  # type: ignore[arg-type]
            )

    def test_result_is_immutable(self):
        result = AnswerServiceResult(
            evidence=(make_evidence(),),
            generation=make_generation_result(),
        )

        with pytest.raises(
            (FrozenInstanceError, AttributeError),
        ):
            result.evidence = ()  # type: ignore[misc]


# ===========================================================================
# Construction validation
# ===========================================================================


class TestAnswerServiceConstruction:
    def test_rejects_invalid_retrieval_context_service(
        self,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        with pytest.raises(
            TypeError,
            match="retrieval_context_service",
        ):
            AnswerService(
                retrieval_context_service=object(),  # type: ignore[arg-type]
                query_preparation_service=(
                    query_preparation_service
                ),
                build_grounding_context=(
                    build_grounding_context
                ),
                evidence_mapper=evidence_mapper,
                response_generator=response_generator,
            )

    def test_rejects_invalid_query_preparation_service(
        self,
        retrieval_context_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        with pytest.raises(
            TypeError,
            match="query_preparation_service",
        ):
            AnswerService(
                retrieval_context_service=(
                    retrieval_context_service
                ),
                query_preparation_service=object(),  # type: ignore[arg-type]
                build_grounding_context=(
                    build_grounding_context
                ),
                evidence_mapper=evidence_mapper,
                response_generator=response_generator,
            )

    def test_rejects_invalid_grounding_context_service(
        self,
        retrieval_context_service,
        query_preparation_service,
        evidence_mapper,
        response_generator,
    ):
        with pytest.raises(
            TypeError,
            match="build_grounding_context",
        ):
            AnswerService(
                retrieval_context_service=(
                    retrieval_context_service
                ),
                query_preparation_service=(
                    query_preparation_service
                ),
                build_grounding_context=object(),  # type: ignore[arg-type]
                evidence_mapper=evidence_mapper,
                response_generator=response_generator,
            )

    def test_rejects_invalid_evidence_mapper(
        self,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        response_generator,
    ):
        with pytest.raises(
            TypeError,
            match="evidence_mapper",
        ):
            AnswerService(
                retrieval_context_service=(
                    retrieval_context_service
                ),
                query_preparation_service=(
                    query_preparation_service
                ),
                build_grounding_context=(
                    build_grounding_context
                ),
                evidence_mapper=object(),  # type: ignore[arg-type]
                response_generator=response_generator,
            )

    def test_rejects_invalid_response_generator(
        self,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
    ):
        with pytest.raises(
            TypeError,
            match="response_generator",
        ):
            AnswerService(
                retrieval_context_service=(
                    retrieval_context_service
                ),
                query_preparation_service=(
                    query_preparation_service
                ),
                build_grounding_context=(
                    build_grounding_context
                ),
                evidence_mapper=evidence_mapper,
                response_generator=object(),  # type: ignore[arg-type]
            )


# ===========================================================================
# Knowledge-backed happy path
# ===========================================================================


class TestKnowledgeAnswerPath:
    def test_returns_evidence_and_generation(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        expected = configure_knowledge_happy_path(
            retrieval_context_service=(
                retrieval_context_service
            ),
            query_preparation_service=(
                query_preparation_service
            ),
            build_grounding_context=(
                build_grounding_context
            ),
            evidence_mapper=evidence_mapper,
            response_generator=response_generator,
        )

        result = service.answer(
            request=make_request(),
        )

        assert isinstance(
            result,
            AnswerServiceResult,
        )

        assert result.evidence is expected["evidence"]
        assert (
            result.generation
            is expected["generation"]
        )

    def test_retrieval_context_is_built_from_request(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        configure_knowledge_happy_path(
            retrieval_context_service=(
                retrieval_context_service
            ),
            query_preparation_service=(
                query_preparation_service
            ),
            build_grounding_context=(
                build_grounding_context
            ),
            evidence_mapper=evidence_mapper,
            response_generator=response_generator,
        )

        intent = make_intent()

        request = make_request(
            customer_message="When will my refund arrive?",
            intent_result=intent,
        )

        service.answer(
            request=request,
        )

        retrieval_context_service.create.assert_called_once_with(
            customer_message="When will my refund arrive?",
            intent_result=intent,
            trusted_filters=None,
            conversation_context=None,
        )

    def test_prepares_query_from_retrieval_context(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        expected = configure_knowledge_happy_path(
            retrieval_context_service=(
                retrieval_context_service
            ),
            query_preparation_service=(
                query_preparation_service
            ),
            build_grounding_context=(
                build_grounding_context
            ),
            evidence_mapper=evidence_mapper,
            response_generator=response_generator,
        )

        service.answer(
            request=make_request(),
        )

        query_preparation_service.prepare.assert_called_once_with(
            context=expected["retrieval_context"],
        )

    def test_builds_grounding_context_from_prepared_query(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        expected = configure_knowledge_happy_path(
            retrieval_context_service=(
                retrieval_context_service
            ),
            query_preparation_service=(
                query_preparation_service
            ),
            build_grounding_context=(
                build_grounding_context
            ),
            evidence_mapper=evidence_mapper,
            response_generator=response_generator,
        )

        service.answer(
            request=make_request(),
        )

        build_grounding_context.build.assert_called_once_with(
            prepared_query=expected["prepared_query"],
        )

    def test_maps_grounding_context_to_neutral_evidence(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        expected = configure_knowledge_happy_path(
            retrieval_context_service=(
                retrieval_context_service
            ),
            query_preparation_service=(
                query_preparation_service
            ),
            build_grounding_context=(
                build_grounding_context
            ),
            evidence_mapper=evidence_mapper,
            response_generator=response_generator,
        )

        service.answer(
            request=make_request(),
        )

        evidence_mapper.map.assert_called_once_with(
            context=expected["grounding_context"],
        )


# ===========================================================================
# Generation request construction
# ===========================================================================


class TestGenerationRequestConstruction:
    def test_generator_receives_grounded_generation_request(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        expected = configure_knowledge_happy_path(
            retrieval_context_service=(
                retrieval_context_service
            ),
            query_preparation_service=(
                query_preparation_service
            ),
            build_grounding_context=(
                build_grounding_context
            ),
            evidence_mapper=evidence_mapper,
            response_generator=response_generator,
        )

        request = make_request()

        service.answer(
            request=request,
        )

        response_generator.generate.assert_called_once()

        _, kwargs = (
            response_generator.generate.call_args
        )

        generation_request = kwargs["request"]

        assert isinstance(
            generation_request,
            GroundedGenerationRequest,
        )

        assert (
            generation_request.customer_message
            == request.customer_message
        )

        assert (
            generation_request.intent
            is request.intent_result
        )

        assert (
            generation_request.evidence
            == expected["evidence"]
        )

        assert (
            generation_request.conversation_context
            is None
        )

    def test_conversation_context_reaches_generation(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        context = (
            "Customer previously asked about refund timing."
        )

        configure_knowledge_happy_path(
            retrieval_context_service=(
                retrieval_context_service
            ),
            query_preparation_service=(
                query_preparation_service
            ),
            build_grounding_context=(
                build_grounding_context
            ),
            evidence_mapper=evidence_mapper,
            response_generator=response_generator,
            conversation_context=context,
        )

        service.answer(
            request=make_request(
                conversation_context=context,
            ),
        )

        _, kwargs = (
            response_generator.generate.call_args
        )

        assert (
            kwargs["request"].conversation_context
            == context
        )


# ===========================================================================
# Trusted filter preservation
# ===========================================================================


class TestTrustedFilterPropagation:
    def test_trusted_filters_pass_to_retrieval_context_boundary(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        filters = RetrievalFilters(
            visibilities=("customer",),
            content_types=("policy",),
            metadata={
                "region": "india",
                "product": "payments",
            },
        )

        configure_knowledge_happy_path(
            retrieval_context_service=(
                retrieval_context_service
            ),
            query_preparation_service=(
                query_preparation_service
            ),
            build_grounding_context=(
                build_grounding_context
            ),
            evidence_mapper=evidence_mapper,
            response_generator=response_generator,
            filters=filters,
        )

        request = make_request(
            trusted_filters=filters,
        )

        service.answer(
            request=request,
        )

        retrieval_context_service.create.assert_called_once_with(
            customer_message=request.customer_message,
            intent_result=request.intent_result,
            trusted_filters=filters,
            conversation_context=None,
        )

    def test_filters_are_not_added_to_generation_request(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        """
        Retrieval constraints affect source selection.

        They are not additional free-form LLM prompt data.
        """
        filters = RetrievalFilters(
            metadata={
                "region": "india",
            }
        )

        configure_knowledge_happy_path(
            retrieval_context_service=(
                retrieval_context_service
            ),
            query_preparation_service=(
                query_preparation_service
            ),
            build_grounding_context=(
                build_grounding_context
            ),
            evidence_mapper=evidence_mapper,
            response_generator=response_generator,
            filters=filters,
        )

        service.answer(
            request=make_request(
                trusted_filters=filters,
            ),
        )

        _, kwargs = (
            response_generator.generate.call_args
        )

        generation_request = kwargs["request"]

        assert not hasattr(
            generation_request,
            "trusted_filters",
        )


# ===========================================================================
# Empty retrieval semantics
# ===========================================================================


class TestEmptyKnowledgeRetrieval:
    def test_empty_grounding_context_still_runs_generation(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        retrieval_context = make_retrieval_context()
        prepared_query = make_prepared_query()

        empty_grounding_context = (
            make_grounding_context(
                blocks=(),
            )
        )

        insufficient = make_generation_result(
            evidence_present=False,
        )

        retrieval_context_service.create.return_value = (
            retrieval_context
        )

        query_preparation_service.prepare.return_value = (
            prepared_query
        )

        build_grounding_context.build.return_value = (
            empty_grounding_context
        )

        evidence_mapper.map.return_value = ()

        response_generator.generate.return_value = (
            insufficient
        )

        result = service.answer(
            request=make_request(),
        )

        assert result.evidence == ()
        assert (
            result.generation.grounding_status
            is GroundingStatus.INSUFFICIENT_EVIDENCE
        )

        response_generator.generate.assert_called_once()

    def test_empty_evidence_is_passed_exactly_to_generator(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        retrieval_context_service.create.return_value = (
            make_retrieval_context()
        )

        query_preparation_service.prepare.return_value = (
            make_prepared_query()
        )

        build_grounding_context.build.return_value = (
            make_grounding_context(
                blocks=(),
            )
        )

        evidence_mapper.map.return_value = ()

        response_generator.generate.return_value = (
            make_generation_result(
                evidence_present=False,
            )
        )

        service.answer(
            request=make_request(),
        )

        _, kwargs = (
            response_generator.generate.call_args
        )

        assert kwargs["request"].evidence == ()


# ===========================================================================
# Exact collaborator ordering
# ===========================================================================


class TestKnowledgePipelineOrdering:
    def test_collaborators_execute_in_required_order(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        expected = configure_knowledge_happy_path(
            retrieval_context_service=(
                retrieval_context_service
            ),
            query_preparation_service=(
                query_preparation_service
            ),
            build_grounding_context=(
                build_grounding_context
            ),
            evidence_mapper=evidence_mapper,
            response_generator=response_generator,
        )

        calls: list[str] = []

        retrieval_context_service.create.side_effect = (
            lambda **_: (
                calls.append("context")
                or expected["retrieval_context"]
            )
        )

        query_preparation_service.prepare.side_effect = (
            lambda **_: (
                calls.append("prepare")
                or expected["prepared_query"]
            )
        )

        build_grounding_context.build.side_effect = (
            lambda **_: (
                calls.append("ground")
                or expected["grounding_context"]
            )
        )

        evidence_mapper.map.side_effect = (
            lambda **_: (
                calls.append("map")
                or expected["evidence"]
            )
        )

        response_generator.generate.side_effect = (
            lambda **_: (
                calls.append("generate")
                or expected["generation"]
            )
        )

        service.answer(
            request=make_request(),
        )

        assert calls == [
            "context",
            "prepare",
            "ground",
            "map",
            "generate",
        ]


# ===========================================================================
# Decision routing
# ===========================================================================


class TestDecisionRouting:
    def test_answer_decision_is_rejected(
        self,
        service,
        retrieval_context_service,
        response_generator,
    ):
        request = make_request(
            decision_result=make_answer_decision(),
        )

        with pytest.raises(
            UnsupportedAnswerDecisionError,
            match="RETRIEVE_INFORMATION",
        ):
            service.answer(
                request=request,
            )

        retrieval_context_service.create.assert_not_called()
        response_generator.generate.assert_not_called()

    def test_clarification_decision_is_rejected(
        self,
        service,
        retrieval_context_service,
        response_generator,
    ):
        request = make_request(
            decision_result=(
                make_clarification_decision()
            ),
        )

        with pytest.raises(
            UnsupportedAnswerDecisionError,
            match="RETRIEVE_INFORMATION",
        ):
            service.answer(
                request=request,
            )

        retrieval_context_service.create.assert_not_called()
        response_generator.generate.assert_not_called()

    def test_operational_retrieval_is_rejected_explicitly(
        self,
        service,
        retrieval_context_service,
        response_generator,
    ):
        request = make_request(
            decision_result=(
                make_operational_decision()
            ),
        )

        with pytest.raises(
            UnsupportedRetrievalKindError,
            match="Operational retrieval",
        ):
            service.answer(
                request=request,
            )

        retrieval_context_service.create.assert_not_called()
        response_generator.generate.assert_not_called()


# ===========================================================================
# Malformed retrieval metadata
# ===========================================================================


class TestRetrievalMetadataValidation:
    def test_missing_retrieval_kind_rejected(
        self,
        service,
    ):
        decision = DecisionResult(
            decision=DecisionType.RETRIEVE_INFORMATION,
            reason_code=(
                DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED
            ),
            reason_summary="Knowledge is required.",
            confidence=0.95,
            metadata={},
        )

        with pytest.raises(
            InvalidRetrievalDecisionError,
            match="retrieval_kind",
        ):
            service.answer(
                request=make_request(
                    decision_result=decision,
                )
            )

    @pytest.mark.parametrize(
        "value",
        [
            None,
            123,
            True,
            ["knowledge"],
            {"kind": "knowledge"},
        ],
    )
    def test_non_string_retrieval_kind_rejected(
        self,
        service,
        value,
    ):
        decision = make_knowledge_decision(
            retrieval_kind=value,
        )

        with pytest.raises(
            InvalidRetrievalDecisionError,
            match="string retrieval_kind",
        ):
            service.answer(
                request=make_request(
                    decision_result=decision,
                )
            )

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "\t",
        ],
    )
    def test_blank_retrieval_kind_rejected(
        self,
        service,
        value,
    ):
        decision = make_knowledge_decision(
            retrieval_kind=value,
        )

        with pytest.raises(
            InvalidRetrievalDecisionError,
            match="cannot be empty",
        ):
            service.answer(
                request=make_request(
                    decision_result=decision,
                )
            )

    def test_unknown_retrieval_kind_rejected(
        self,
        service,
    ):
        decision = make_knowledge_decision(
            retrieval_kind="quantum_database",
        )

        with pytest.raises(
            InvalidRetrievalDecisionError,
            match="Unknown retrieval_kind",
        ):
            service.answer(
                request=make_request(
                    decision_result=decision,
                )
            )

    def test_valid_kind_with_surrounding_whitespace_is_accepted(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        configure_knowledge_happy_path(
            retrieval_context_service=(
                retrieval_context_service
            ),
            query_preparation_service=(
                query_preparation_service
            ),
            build_grounding_context=(
                build_grounding_context
            ),
            evidence_mapper=evidence_mapper,
            response_generator=response_generator,
        )

        decision = make_knowledge_decision(
            retrieval_kind="  knowledge  ",
        )

        result = service.answer(
            request=make_request(
                decision_result=decision,
            )
        )

        assert isinstance(
            result,
            AnswerServiceResult,
        )


# ===========================================================================
# answer() boundary validation
# ===========================================================================


class TestAnswerBoundaryValidation:
    def test_wrong_request_type_rejected(
        self,
        service,
        retrieval_context_service,
        response_generator,
    ):
        with pytest.raises(
            InvalidAnswerRequestError,
            match="AnswerServiceRequest",
        ):
            service.answer(
                request=object(),  # type: ignore[arg-type]
            )

        retrieval_context_service.create.assert_not_called()
        response_generator.generate.assert_not_called()


# ===========================================================================
# Failure propagation
# ===========================================================================


class TestFailurePropagation:
    def test_retrieval_context_failure_propagates_unchanged(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
    ):
        failure = RuntimeError(
            "retrieval-context translation failed"
        )

        retrieval_context_service.create.side_effect = failure

        with pytest.raises(
            RuntimeError,
        ) as exc_info:
            service.answer(
                request=make_request(),
            )

        assert exc_info.value is failure

        query_preparation_service.prepare.assert_not_called()

    def test_query_preparation_failure_propagates_unchanged(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
    ):
        retrieval_context_service.create.return_value = (
            make_retrieval_context()
        )

        failure = RetrievalPipelineError(
            "query preparation failed"
        )

        query_preparation_service.prepare.side_effect = (
            failure
        )

        with pytest.raises(
            RetrievalPipelineError,
        ) as exc_info:
            service.answer(
                request=make_request(),
            )

        assert exc_info.value is failure

        build_grounding_context.build.assert_not_called()

    def test_grounding_failure_propagates_unchanged(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
    ):
        retrieval_context_service.create.return_value = (
            make_retrieval_context()
        )

        query_preparation_service.prepare.return_value = (
            make_prepared_query()
        )

        failure = RetrievalPipelineError(
            "retrieval pipeline unavailable"
        )

        build_grounding_context.build.side_effect = failure

        with pytest.raises(
            RetrievalPipelineError,
        ) as exc_info:
            service.answer(
                request=make_request(),
            )

        assert exc_info.value is failure

        evidence_mapper.map.assert_not_called()

    def test_evidence_mapping_failure_propagates_unchanged(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        retrieval_context_service.create.return_value = (
            make_retrieval_context()
        )

        query_preparation_service.prepare.return_value = (
            make_prepared_query()
        )

        build_grounding_context.build.return_value = (
            make_grounding_context()
        )

        failure = RuntimeError(
            "evidence mapping failed"
        )

        evidence_mapper.map.side_effect = failure

        with pytest.raises(
            RuntimeError,
        ) as exc_info:
            service.answer(
                request=make_request(),
            )

        assert exc_info.value is failure

        response_generator.generate.assert_not_called()

    def test_generation_failure_propagates_unchanged(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        configure_knowledge_happy_path(
            retrieval_context_service=(
                retrieval_context_service
            ),
            query_preparation_service=(
                query_preparation_service
            ),
            build_grounding_context=(
                build_grounding_context
            ),
            evidence_mapper=evidence_mapper,
            response_generator=response_generator,
        )

        failure = GroundedGenerationError(
            "generation failed"
        )

        response_generator.generate.side_effect = failure

        with pytest.raises(
            GroundedGenerationError,
        ) as exc_info:
            service.answer(
                request=make_request(),
            )

        assert exc_info.value is failure


# ===========================================================================
# Failure short-circuiting
# ===========================================================================


class TestFailureShortCircuiting:
    def test_invalid_decision_performs_no_knowledge_work(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        with pytest.raises(
            UnsupportedAnswerDecisionError,
        ):
            service.answer(
                request=make_request(
                    decision_result=(
                        make_clarification_decision()
                    ),
                )
            )

        retrieval_context_service.create.assert_not_called()
        query_preparation_service.prepare.assert_not_called()
        build_grounding_context.build.assert_not_called()
        evidence_mapper.map.assert_not_called()
        response_generator.generate.assert_not_called()

    def test_operational_decision_performs_no_knowledge_work(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        with pytest.raises(
            UnsupportedRetrievalKindError,
        ):
            service.answer(
                request=make_request(
                    decision_result=(
                        make_operational_decision()
                    ),
                )
            )

        retrieval_context_service.create.assert_not_called()
        query_preparation_service.prepare.assert_not_called()
        build_grounding_context.build.assert_not_called()
        evidence_mapper.map.assert_not_called()
        response_generator.generate.assert_not_called()

    def test_generation_occurs_only_after_evidence_mapping(
        self,
        service,
        retrieval_context_service,
        query_preparation_service,
        build_grounding_context,
        evidence_mapper,
        response_generator,
    ):
        retrieval_context_service.create.return_value = (
            make_retrieval_context()
        )

        query_preparation_service.prepare.return_value = (
            make_prepared_query()
        )

        build_grounding_context.build.return_value = (
            make_grounding_context()
        )

        evidence_mapper.map.side_effect = RuntimeError(
            "mapping failed"
        )

        with pytest.raises(
            RuntimeError,
            match="mapping failed",
        ):
            service.answer(
                request=make_request(),
            )

        response_generator.generate.assert_not_called()