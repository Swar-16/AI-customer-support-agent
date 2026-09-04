from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.ai.generation.models import (
    Citation,
    GroundedGenerationRequest,
    GroundedGenerationResult,
    GroundingStatus,
)
from packages.ai.intent.taxonomy import IntentType
from packages.ai.intent.schemas import IntentResult
from packages.ai.orchestration.state import (
    EvidenceSourceType,
    RetrievedEvidence,
)


def make_intent() -> IntentResult:
    """
    Build a genuinely valid IntentResult.

    GroundedGenerationRequest validates its nested IntentResult, so using
    model_construct() without the intent model's required semantic fields
    would create an invalid object.
    """
    return IntentResult(
        intent=IntentType.GENERAL_QUESTION,
        confidence=0.95,
        needs_clarification=False,
        reason_summary="Customer is asking a general support question.",
    )


def make_evidence(
    *,
    source_id: str = "chunk-123",
    content: str = "Refunds are processed within five business days.",
    title: str | None = "Refund Policy",
    section: str | None = "Processing Time",
    relevance_score: float | None = 0.91,
) -> RetrievedEvidence:
    return RetrievedEvidence(
        source_type=EvidenceSourceType.KNOWLEDGE,
        source_id=source_id,
        content=content,
        title=title,
        section=section,
        relevance_score=relevance_score,
    )


class TestGroundingStatus:
    def test_expected_values_are_stable(self) -> None:
        assert GroundingStatus.GROUNDED == "grounded"
        assert (
            GroundingStatus.INSUFFICIENT_EVIDENCE
            == "insufficient_evidence"
        )
        assert GroundingStatus.NOT_REQUIRED == "not_required"


class TestCitation:
    def test_minimal_valid_citation(self) -> None:
        citation = Citation(
            source_id="chunk-123",
        )

        assert citation.source_id == "chunk-123"
        assert citation.title is None
        assert citation.section is None

    def test_full_citation(self) -> None:
        citation = Citation(
            source_id="chunk-123",
            title="Refund Policy",
            section="Processing Time",
        )

        assert citation.source_id == "chunk-123"
        assert citation.title == "Refund Policy"
        assert citation.section == "Processing Time"

    def test_source_id_is_trimmed(self) -> None:
        citation = Citation(
            source_id="  chunk-123  ",
        )

        assert citation.source_id == "chunk-123"

    def test_blank_source_id_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Citation(
                source_id="   ",
            )

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Citation(
                source_id="chunk-123",
                internal_score=0.97,  # type: ignore[call-arg]
            )

    def test_citation_is_frozen(self) -> None:
        citation = Citation(
            source_id="chunk-123",
        )

        with pytest.raises(ValidationError):
            citation.source_id = "different"  # type: ignore[misc]


class TestGroundedGenerationRequest:
    def test_minimal_valid_request(self) -> None:
        request = GroundedGenerationRequest(
            customer_message="How long does a refund take?",
            intent=make_intent(),
        )

        assert request.customer_message == "How long does a refund take?"
        assert request.intent is not None
        assert request.evidence == ()
        assert request.conversation_context is None

    def test_request_with_evidence(self) -> None:
        evidence = (
            make_evidence(),
        )

        request = GroundedGenerationRequest(
            customer_message="How long does a refund take?",
            intent=make_intent(),
            evidence=evidence,
        )

        assert request.evidence == evidence
        assert isinstance(request.evidence, tuple)

    def test_customer_message_is_trimmed(self) -> None:
        request = GroundedGenerationRequest(
            customer_message="  How long does a refund take?  ",
            intent=make_intent(),
        )

        assert request.customer_message == "How long does a refund take?"

    def test_blank_customer_message_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GroundedGenerationRequest(
                customer_message="   ",
                intent=make_intent(),
            )

    def test_conversation_context_is_trimmed(self) -> None:
        request = GroundedGenerationRequest(
            customer_message="Where is my order?",
            intent=make_intent(),
            conversation_context="  Customer previously asked about order 42.  ",
        )

        assert (
            request.conversation_context
            == "Customer previously asked about order 42."
        )

    def test_blank_conversation_context_becomes_none(self) -> None:
        request = GroundedGenerationRequest(
            customer_message="Where is my order?",
            intent=make_intent(),
            conversation_context="   ",
        )

        assert request.conversation_context is None

    def test_multiple_evidence_items_preserve_order(self) -> None:
        first = make_evidence(
            source_id="chunk-1",
            content="First source.",
        )

        second = make_evidence(
            source_id="chunk-2",
            content="Second source.",
        )

        request = GroundedGenerationRequest(
            customer_message="Tell me about refunds.",
            intent=make_intent(),
            evidence=(first, second),
        )

        assert request.evidence[0].source_id == "chunk-1"
        assert request.evidence[1].source_id == "chunk-2"

    def test_non_intent_instance_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GroundedGenerationRequest(
                customer_message="Hello",
                intent="not-an-intent",  # type: ignore[arg-type]
            )

    def test_wrong_evidence_item_type_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GroundedGenerationRequest(
                customer_message="Hello",
                intent=make_intent(),
                evidence=("not-evidence",),  # type: ignore[arg-type]
            )

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GroundedGenerationRequest(
                customer_message="Hello",
                intent=make_intent(),
                decision="answer",  # type: ignore[call-arg]
            )

    def test_request_is_frozen(self) -> None:
        request = GroundedGenerationRequest(
            customer_message="Hello",
            intent=make_intent(),
        )

        with pytest.raises(ValidationError):
            request.customer_message = "Changed"  # type: ignore[misc]


class TestGroundedGenerationResult:
    def test_grounded_result_with_citation(self) -> None:
        citation = Citation(
            source_id="chunk-123",
            title="Refund Policy",
            section="Processing Time",
        )

        result = GroundedGenerationResult(
            answer="Refunds are generally processed within five business days.",
            grounding_status=GroundingStatus.GROUNDED,
            citations=(citation,),
        )

        assert (
            result.answer
            == "Refunds are generally processed within five business days."
        )
        assert result.grounding_status is GroundingStatus.GROUNDED
        assert result.citations == (citation,)

    def test_insufficient_evidence_result_can_have_no_citations(self) -> None:
        result = GroundedGenerationResult(
            answer=(
                "I don't have enough verified information to answer that "
                "reliably."
            ),
            grounding_status=GroundingStatus.INSUFFICIENT_EVIDENCE,
        )

        assert (
            result.grounding_status
            is GroundingStatus.INSUFFICIENT_EVIDENCE
        )
        assert result.citations == ()

    def test_not_required_result_can_have_no_citations(self) -> None:
        result = GroundedGenerationResult(
            answer="Could you share your order ID?",
            grounding_status=GroundingStatus.NOT_REQUIRED,
        )

        assert result.grounding_status is GroundingStatus.NOT_REQUIRED
        assert result.citations == ()

    def test_answer_is_trimmed(self) -> None:
        result = GroundedGenerationResult(
            answer="  Please share your order ID.  ",
            grounding_status=GroundingStatus.NOT_REQUIRED,
        )

        assert result.answer == "Please share your order ID."

    def test_blank_answer_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GroundedGenerationResult(
                answer="   ",
                grounding_status=GroundingStatus.NOT_REQUIRED,
            )

    def test_wrong_grounding_status_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GroundedGenerationResult(
                answer="Response",
                grounding_status="invented-status",  # type: ignore[arg-type]
            )

    def test_wrong_citation_item_type_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GroundedGenerationResult(
                answer="Response",
                grounding_status=GroundingStatus.GROUNDED,
                citations=("chunk-123",),  # type: ignore[arg-type]
            )

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GroundedGenerationResult(
                answer="Response",
                grounding_status=GroundingStatus.GROUNDED,
                confidence=0.99,  # type: ignore[call-arg]
            )

    def test_result_is_frozen(self) -> None:
        result = GroundedGenerationResult(
            answer="Response",
            grounding_status=GroundingStatus.NOT_REQUIRED,
        )

        with pytest.raises(ValidationError):
            result.answer = "Changed"  # type: ignore[misc]