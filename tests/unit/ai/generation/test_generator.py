from __future__ import annotations

from unittest.mock import Mock, create_autospec

import pytest

from packages.ai.generation.generator import (
    GroundedGenerationError,
    GroundedGenerationProviderError,
    GroundedGenerationTimeoutError,
    GroundedResponseGenerator,
    InvalidGenerationInputError,
    InvalidGroundedGenerationResponseError,
)
from packages.ai.generation.models import (
    Citation,
    GroundedGenerationRequest,
    GroundedGenerationResult,
    GroundingStatus,
)
from packages.ai.generation.prompts import (
    GroundedGenerationPromptBuilder,
)
from packages.ai.intent.taxonomy import IntentType
from packages.ai.intent.schemas import IntentResult
from packages.ai.orchestration.state import (
    EvidenceSourceType,
    RetrievedEvidence,
)
from packages.ai.providers.base import LLMProvider
from packages.ai.providers.errors import (
    LLMProviderError,
    LLMProviderResponseError,
    LLMProviderTimeoutError,
)
from packages.ai.providers.types import (
    StructuredLLMResponse,
    TokenUsage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_provider():
    """
    Autospecced provider prevents tests from accidentally depending on methods
    that do not exist on the real provider abstraction.
    """
    return create_autospec(
        LLMProvider,
        instance=True,
    )


@pytest.fixture
def generator(mock_provider):
    return GroundedResponseGenerator(
        provider=mock_provider,
    )


# ---------------------------------------------------------------------------
# Domain-object helpers
# ---------------------------------------------------------------------------


def make_evidence(
    *,
    source_id: str | None = "chunk-1",
    title: str | None = "Refund Policy",
    section: str | None = "Refund Processing",
    content: str = (
        "Approved refunds are generally returned to the original "
        "payment method within 5 to 7 business days."
    ),
    relevance_score: float | None = 0.95,
) -> RetrievedEvidence:
    return RetrievedEvidence(
        source_type=EvidenceSourceType.KNOWLEDGE,
        source_id=source_id,
        title=title,
        section=section,
        content=content,
        relevance_score=relevance_score,
        metadata={
            "document_id": "document-1",
            "version_id": "version-1",
            "chunk_id": source_id or "uncitable-chunk",
        },
    )
    
def make_intent(
    *,
    intent_type: IntentType = IntentType.REFUND_REQUEST,
    confidence: float = 0.95,
    needs_clarification: bool = False,
) -> IntentResult:
    """
    Build a genuinely valid canonical intent result.

    Generation consumes the complete IntentResult contract rather than a bare
    IntentType because prompt construction may require semantic information
    such as entities and clarification state.
    """
    return IntentResult(
        intent=intent_type,
        confidence=confidence,
        reason_summary="Customer is asking about refund processing.",
        needs_clarification=needs_clarification,
    )


def make_request(
    *,
    customer_message: str = "How long does a refund take?",
    intent: IntentResult | None = None,
    evidence: tuple[RetrievedEvidence, ...] | None = None,
    conversation_context: str | None = None,
) -> GroundedGenerationRequest:
    """
    Build a valid generation request while allowing individual tests to
    override only the dimension they care about.
    """
    return GroundedGenerationRequest(
        customer_message=customer_message,
        intent=intent or make_intent(),
        evidence=(
            (make_evidence(),)
            if evidence is None
            else evidence
        ),
        conversation_context=conversation_context,
    )


def make_citation(
    *,
    source_id: str = "chunk-1",
    title: str | None = "Refund Policy",
    section: str | None = "Refund Processing",
) -> Citation:
    return Citation(
        source_id=source_id,
        title=title,
        section=section,
    )


def make_result(
    *,
    answer: str = (
        "Approved refunds are generally returned to the original "
        "payment method within 5 to 7 business days."
    ),
    grounding_status: GroundingStatus = GroundingStatus.GROUNDED,
    citations: tuple[Citation, ...] | None = None,
) -> GroundedGenerationResult:
    return GroundedGenerationResult(
        answer=answer,
        grounding_status=grounding_status,
        citations=(
            (make_citation(),)
            if citations is None
            else citations
        ),
    )


def make_provider_response(
    result: GroundedGenerationResult | None = None,
    *,
    input_tokens: int = 40,
    output_tokens: int = 20,
) -> StructuredLLMResponse[GroundedGenerationResult]:
    return StructuredLLMResponse(
        output=result or make_result(),
        provider="mock",
        model="mock-llm-v1",
        usage=TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    )


def get_provider_call_kwargs(mock_provider) -> dict:
    _, kwargs = mock_provider.generate_structured.call_args
    return kwargs


# ===========================================================================
# Construction
# ===========================================================================


class TestGroundedResponseGeneratorConstruction:
    def test_rejects_none_provider(self):
        with pytest.raises(
            TypeError,
            match="provider cannot be None",
        ):
            GroundedResponseGenerator(
                provider=None,  # type: ignore[arg-type]
            )

    def test_accepts_provider(self, mock_provider):
        generator = GroundedResponseGenerator(
            provider=mock_provider,
        )

        assert isinstance(
            generator,
            GroundedResponseGenerator,
        )

    def test_accepts_explicit_prompt_builder(
        self,
        mock_provider,
    ):
        prompt_builder = GroundedGenerationPromptBuilder()

        generator = GroundedResponseGenerator(
            provider=mock_provider,
            prompt_builder=prompt_builder,
        )

        assert isinstance(
            generator,
            GroundedResponseGenerator,
        )

    def test_rejects_wrong_prompt_builder_type(
        self,
        mock_provider,
    ):
        with pytest.raises(
            TypeError,
            match="prompt_builder",
        ):
            GroundedResponseGenerator(
                provider=mock_provider,
                prompt_builder=object(),  # type: ignore[arg-type]
            )


# ===========================================================================
# Happy paths
# ===========================================================================


class TestGroundedGenerationHappyPath:
    def test_generate_returns_semantic_result(
        self,
        generator,
        mock_provider,
    ):
        expected = make_result()

        mock_provider.generate_structured.return_value = (
            make_provider_response(expected)
        )

        result = generator.generate(
            request=make_request(),
        )

        assert result is expected

    def test_generate_calls_provider_once(
        self,
        generator,
        mock_provider,
    ):
        mock_provider.generate_structured.return_value = (
            make_provider_response()
        )

        generator.generate(
            request=make_request(),
        )

        mock_provider.generate_structured.assert_called_once()

    def test_requests_grounded_generation_result_schema(
        self,
        generator,
        mock_provider,
    ):
        mock_provider.generate_structured.return_value = (
            make_provider_response()
        )

        generator.generate(
            request=make_request(),
        )

        kwargs = get_provider_call_kwargs(
            mock_provider
        )

        assert (
            kwargs["response_model"]
            is GroundedGenerationResult
        )

    def test_provider_receives_non_empty_prompts(
        self,
        generator,
        mock_provider,
    ):
        mock_provider.generate_structured.return_value = (
            make_provider_response()
        )

        generator.generate(
            request=make_request(),
        )

        kwargs = get_provider_call_kwargs(
            mock_provider
        )

        assert isinstance(
            kwargs["system_prompt"],
            str,
        )
        assert kwargs["system_prompt"].strip()

        assert isinstance(
            kwargs["user_prompt"],
            str,
        )
        assert kwargs["user_prompt"].strip()

    def test_customer_message_is_present_in_user_prompt(
        self,
        generator,
        mock_provider,
    ):
        request = make_request()

        mock_provider.generate_structured.return_value = (
            make_provider_response()
        )

        generator.generate(
            request=request,
        )

        kwargs = get_provider_call_kwargs(
            mock_provider
        )

        assert (
            request.customer_message
            in kwargs["user_prompt"]
        )

    def test_evidence_content_is_present_in_user_prompt(
        self,
        generator,
        mock_provider,
    ):
        evidence = make_evidence(
            content="Refunds require 5 to 7 business days.",
        )

        request = make_request(
            evidence=(evidence,),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response()
        )

        generator.generate(
            request=request,
        )

        kwargs = get_provider_call_kwargs(
            mock_provider
        )

        assert (
            evidence.content
            in kwargs["user_prompt"]
        )


# ===========================================================================
# Multiple evidence / citation handling
# ===========================================================================


class TestMultipleEvidenceGeneration:
    def test_multiple_valid_citations_are_allowed(
        self,
        generator,
        mock_provider,
    ):
        first = make_evidence(
            source_id="chunk-1",
            title="Refund Policy",
            section="Processing Time",
        )

        second = make_evidence(
            source_id="chunk-2",
            title="Payment Policy",
            section="Payment Method",
            content=(
                "Refunds are returned to the original "
                "payment method."
            ),
        )

        request = make_request(
            evidence=(first, second),
        )

        expected = make_result(
            citations=(
                Citation(
                    source_id="chunk-1",
                    title="Refund Policy",
                    section="Processing Time",
                ),
                Citation(
                    source_id="chunk-2",
                    title="Payment Policy",
                    section="Payment Method",
                ),
            ),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(expected)
        )

        result = generator.generate(
            request=request,
        )

        assert result is expected
        assert len(result.citations) == 2

    def test_citation_may_omit_optional_title_and_section(
        self,
        generator,
        mock_provider,
    ):
        expected = make_result(
            citations=(
                Citation(
                    source_id="chunk-1",
                    title=None,
                    section=None,
                ),
            ),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(expected)
        )

        result = generator.generate(
            request=make_request(),
        )

        assert result is expected


# ===========================================================================
# Legitimate non-grounded outcomes
# ===========================================================================


class TestNonGroundedGenerationOutcomes:
    def test_insufficient_evidence_without_citations_is_valid(
        self,
        generator,
        mock_provider,
    ):
        expected = make_result(
            answer=(
                "I don't have enough verified information "
                "to answer that reliably."
            ),
            grounding_status=(
                GroundingStatus.INSUFFICIENT_EVIDENCE
            ),
            citations=(),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(expected)
        )

        result = generator.generate(
            request=make_request(evidence=()),
        )

        assert result is expected
        assert result.citations == ()

    def test_insufficient_evidence_allowed_even_when_evidence_was_supplied(
        self,
        generator,
        mock_provider,
    ):
        """
        Retrieval returning evidence does not guarantee that the evidence
        actually answers the customer's question.
        """
        expected = make_result(
            answer=(
                "The available information does not answer "
                "that question reliably."
            ),
            grounding_status=(
                GroundingStatus.INSUFFICIENT_EVIDENCE
            ),
            citations=(),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(expected)
        )

        result = generator.generate(
            request=make_request(),
        )

        assert result is expected

    def test_not_required_without_citations_is_valid(
        self,
        generator,
        mock_provider,
    ):
        expected = make_result(
            answer="Could you provide your order ID?",
            grounding_status=GroundingStatus.NOT_REQUIRED,
            citations=(),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(expected)
        )

        result = generator.generate(
            request=make_request(evidence=()),
        )

        assert result is expected


# ===========================================================================
# Provider response preservation
# ===========================================================================


class TestProviderResponsePreservation:
    def test_generate_with_response_returns_complete_wrapper(
        self,
        generator,
        mock_provider,
    ):
        provider_response = make_provider_response(
            input_tokens=123,
            output_tokens=45,
        )

        mock_provider.generate_structured.return_value = (
            provider_response
        )

        response = generator.generate_with_response(
            request=make_request(),
        )

        assert response is provider_response

    def test_provider_identity_is_preserved(
        self,
        generator,
        mock_provider,
    ):
        provider_response = make_provider_response()

        mock_provider.generate_structured.return_value = (
            provider_response
        )

        response = generator.generate_with_response(
            request=make_request(),
        )

        assert response.provider == "mock"
        assert response.model == "mock-llm-v1"

    def test_token_usage_is_preserved(
        self,
        generator,
        mock_provider,
    ):
        provider_response = make_provider_response(
            input_tokens=101,
            output_tokens=37,
        )

        mock_provider.generate_structured.return_value = (
            provider_response
        )

        response = generator.generate_with_response(
            request=make_request(),
        )

        assert response.usage.input_tokens == 101
        assert response.usage.output_tokens == 37


# ===========================================================================
# Request validation
# ===========================================================================


class TestGenerationRequestValidation:
    def test_rejects_wrong_request_type_before_provider_call(
        self,
        generator,
        mock_provider,
    ):
        with pytest.raises(
            InvalidGenerationInputError,
            match="GroundedGenerationRequest",
        ):
            generator.generate(
                request="not-a-request",  # type: ignore[arg-type]
            )

        mock_provider.generate_structured.assert_not_called()

    def test_duplicate_non_null_evidence_source_ids_rejected(
        self,
        generator,
        mock_provider,
    ):
        first = make_evidence(
            source_id="duplicate-id",
        )

        second = make_evidence(
            source_id="duplicate-id",
            content="Different evidence block.",
        )

        request = make_request(
            evidence=(first, second),
        )

        with pytest.raises(
            InvalidGenerationInputError,
            match="duplicate",
        ):
            generator.generate(
                request=request,
            )

        mock_provider.generate_structured.assert_not_called()

    def test_multiple_none_source_ids_are_allowed(
        self,
        generator,
        mock_provider,
    ):
        first = make_evidence(
            source_id=None,
            title=None,
            section=None,
        )

        second = make_evidence(
            source_id=None,
            title=None,
            section=None,
            content="Another uncitable evidence item.",
        )

        request = make_request(
            evidence=(first, second),
        )

        expected = make_result(
            answer=(
                "I don't have enough citable evidence "
                "to answer reliably."
            ),
            grounding_status=(
                GroundingStatus.INSUFFICIENT_EVIDENCE
            ),
            citations=(),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(expected)
        )

        result = generator.generate(
            request=request,
        )

        assert result is expected


# ===========================================================================
# Citation provenance
# ===========================================================================


class TestCitationProvenanceValidation:
    def test_unknown_source_id_is_rejected(
        self,
        generator,
        mock_provider,
    ):
        result = make_result(
            citations=(
                Citation(
                    source_id="hallucinated-chunk",
                    title=None,
                    section=None,
                ),
            ),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(result)
        )

        with pytest.raises(
            InvalidGroundedGenerationResponseError,
            match="not supplied",
        ):
            generator.generate(
                request=make_request(),
            )

    def test_duplicate_citation_source_id_is_rejected(
        self,
        generator,
        mock_provider,
    ):
        result = make_result(
            citations=(
                make_citation(),
                make_citation(),
            ),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(result)
        )

        with pytest.raises(
            InvalidGroundedGenerationResponseError,
            match="duplicate citation",
        ):
            generator.generate(
                request=make_request(),
            )

    def test_fabricated_citation_title_is_rejected(
        self,
        generator,
        mock_provider,
    ):
        result = make_result(
            citations=(
                Citation(
                    source_id="chunk-1",
                    title="Official Guaranteed Refund Policy",
                    section="Refund Processing",
                ),
            ),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(result)
        )

        with pytest.raises(
            InvalidGroundedGenerationResponseError,
            match="title does not match",
        ):
            generator.generate(
                request=make_request(),
            )

    def test_fabricated_citation_section_is_rejected(
        self,
        generator,
        mock_provider,
    ):
        result = make_result(
            citations=(
                Citation(
                    source_id="chunk-1",
                    title="Refund Policy",
                    section="Guaranteed Instant Refunds",
                ),
            ),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(result)
        )

        with pytest.raises(
            InvalidGroundedGenerationResponseError,
            match="section does not match",
        ):
            generator.generate(
                request=make_request(),
            )

    def test_correct_title_and_section_are_accepted(
        self,
        generator,
        mock_provider,
    ):
        result = make_result(
            citations=(
                Citation(
                    source_id="chunk-1",
                    title="Refund Policy",
                    section="Refund Processing",
                ),
            ),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(result)
        )

        generated = generator.generate(
            request=make_request(),
        )

        assert generated is result


# ===========================================================================
# Grounding-status invariants
# ===========================================================================


class TestGroundingStatusContract:
    def test_grounded_response_without_evidence_is_rejected(
        self,
        generator,
        mock_provider,
    ):
        result = make_result()

        mock_provider.generate_structured.return_value = (
            make_provider_response(result)
        )

        with pytest.raises(
            InvalidGroundedGenerationResponseError,
            match="no evidence",
        ):
            generator.generate(
                request=make_request(evidence=()),
            )

    def test_grounded_response_without_citations_is_rejected(
        self,
        generator,
        mock_provider,
    ):
        result = make_result(
            citations=(),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(result)
        )

        with pytest.raises(
            InvalidGroundedGenerationResponseError,
            match="must cite",
        ):
            generator.generate(
                request=make_request(),
            )

    def test_insufficient_evidence_with_citation_is_rejected(
        self,
        generator,
        mock_provider,
    ):
        result = make_result(
            answer="I do not have enough information.",
            grounding_status=(
                GroundingStatus.INSUFFICIENT_EVIDENCE
            ),
            citations=(make_citation(),),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(result)
        )

        with pytest.raises(
            InvalidGroundedGenerationResponseError,
            match="must not contain citations",
        ):
            generator.generate(
                request=make_request(),
            )

    def test_not_required_with_citation_is_rejected(
        self,
        generator,
        mock_provider,
    ):
        result = make_result(
            answer="Could you provide more information?",
            grounding_status=GroundingStatus.NOT_REQUIRED,
            citations=(make_citation(),),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(result)
        )

        with pytest.raises(
            InvalidGroundedGenerationResponseError,
            match="must not contain citations",
        ):
            generator.generate(
                request=make_request(),
            )


# ===========================================================================
# Defensive provider-contract validation
# ===========================================================================


class TestProviderContractValidation:
    def test_wrong_provider_wrapper_is_rejected(
        self,
        generator,
        mock_provider,
    ):
        mock_provider.generate_structured.return_value = (
            make_result()
        )

        with pytest.raises(
            InvalidGroundedGenerationResponseError,
            match="unexpected response wrapper",
        ):
            generator.generate(
                request=make_request(),
            )

    def test_wrong_structured_output_type_is_rejected(
        self,
        generator,
        mock_provider,
    ):
        """
        StructuredLLMResponse itself prevents arbitrary non-Pydantic output.

        A mock wrapper is therefore used to simulate a broken/custom provider
        crossing the generator boundary with the wrong semantic model.
        """
        malformed_response = Mock(
            spec=StructuredLLMResponse
        )
        malformed_response.output = Mock()

        mock_provider.generate_structured.return_value = (
            malformed_response
        )

        with pytest.raises(
            InvalidGroundedGenerationResponseError,
            match="unexpected structured output",
        ):
            generator.generate(
                request=make_request(),
            )


# ===========================================================================
# Provider exception translation
# ===========================================================================


class TestProviderFailureTranslation:
    def test_provider_timeout_is_translated(
        self,
        generator,
        mock_provider,
    ):
        mock_provider.generate_structured.side_effect = (
            LLMProviderTimeoutError(
                provider="mock",
                message="timeout",
            )
        )

        with pytest.raises(
            GroundedGenerationTimeoutError,
        ) as exc_info:
            generator.generate(
                request=make_request(),
            )

        assert isinstance(
            exc_info.value.__cause__,
            LLMProviderTimeoutError,
        )

    def test_provider_response_error_is_translated(
        self,
        generator,
        mock_provider,
    ):
        mock_provider.generate_structured.side_effect = (
            LLMProviderResponseError(
                provider="mock",
                message="invalid response",
            )
        )

        with pytest.raises(
            InvalidGroundedGenerationResponseError,
        ) as exc_info:
            generator.generate(
                request=make_request(),
            )

        assert isinstance(
            exc_info.value.__cause__,
            LLMProviderResponseError,
        )

    def test_generic_provider_error_is_translated(
        self,
        generator,
        mock_provider,
    ):
        mock_provider.generate_structured.side_effect = (
            LLMProviderError(
                provider="mock",
                message="provider unavailable",
            )
        )

        with pytest.raises(
            GroundedGenerationProviderError,
        ) as exc_info:
            generator.generate(
                request=make_request(),
            )

        assert isinstance(
            exc_info.value.__cause__,
            LLMProviderError,
        )

    def test_unexpected_exception_is_translated(
        self,
        generator,
        mock_provider,
    ):
        mock_provider.generate_structured.side_effect = (
            RuntimeError("unexpected bug")
        )

        with pytest.raises(
            GroundedGenerationError,
            match="Unexpected",
        ) as exc_info:
            generator.generate(
                request=make_request(),
            )

        assert isinstance(
            exc_info.value.__cause__,
            RuntimeError,
        )


# ===========================================================================
# Failure isolation / call-count guarantees
# ===========================================================================


class TestFailureIsolation:
    def test_invalid_request_never_reaches_provider(
        self,
        generator,
        mock_provider,
    ):
        with pytest.raises(
            InvalidGenerationInputError,
        ):
            generator.generate(
                request=None,  # type: ignore[arg-type]
            )

        mock_provider.generate_structured.assert_not_called()

    def test_duplicate_evidence_identity_never_reaches_provider(
        self,
        generator,
        mock_provider,
    ):
        request = make_request(
            evidence=(
                make_evidence(
                    source_id="same-id",
                ),
                make_evidence(
                    source_id="same-id",
                    content="Second evidence.",
                ),
            ),
        )

        with pytest.raises(
            InvalidGenerationInputError,
        ):
            generator.generate(
                request=request,
            )

        mock_provider.generate_structured.assert_not_called()

    def test_invalid_model_response_does_not_trigger_second_llm_call(
        self,
        generator,
        mock_provider,
    ):
        invalid = make_result(
            citations=(
                Citation(
                    source_id="invented-source",
                    title=None,
                    section=None,
                ),
            ),
        )

        mock_provider.generate_structured.return_value = (
            make_provider_response(invalid)
        )

        with pytest.raises(
            InvalidGroundedGenerationResponseError,
        ):
            generator.generate(
                request=make_request(),
            )

        mock_provider.generate_structured.assert_called_once()