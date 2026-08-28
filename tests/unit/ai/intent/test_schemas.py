import pytest
from pydantic import ValidationError

from packages.ai.intent.schemas import (
    IntentEntities,
    IntentResult,
)
from packages.ai.intent.taxonomy import IntentType


def test_valid_intent_result() -> None:
    result = IntentResult(
        intent=IntentType.PAYMENT_ISSUE,
        confidence=0.97,
        entities=IntentEntities(
            order_id="ORD-123",
            issue_type="duplicate_charge",
        ),
        needs_clarification=False,
        reason_summary=(
            "Customer reports being charged twice."
        ),
    )

    assert result.intent is IntentType.PAYMENT_ISSUE
    assert result.confidence == 0.97
    assert result.entities.order_id == "ORD-123"


def test_confidence_cannot_exceed_one() -> None:
    with pytest.raises(ValidationError):
        IntentResult(
            intent=IntentType.PAYMENT_ISSUE,
            confidence=1.5,
            reason_summary="Payment problem detected.",
        )


def test_confidence_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        IntentResult(
            intent=IntentType.PAYMENT_ISSUE,
            confidence=-0.1,
            reason_summary="Payment problem detected.",
        )


def test_unknown_requires_clarification() -> None:
    with pytest.raises(ValidationError):
        IntentResult(
            intent=IntentType.UNKNOWN,
            confidence=0.3,
            needs_clarification=False,
            reason_summary="Intent cannot be determined.",
        )


def test_unknown_with_clarification_is_valid() -> None:
    result = IntentResult(
        intent=IntentType.UNKNOWN,
        confidence=0.3,
        needs_clarification=True,
        reason_summary="More information is required.",
    )

    assert result.intent is IntentType.UNKNOWN


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        IntentResult(
            intent=IntentType.REFUND_REQUEST,
            confidence=0.95,
            reason_summary="Customer wants a refund.",
            unauthorized_action="issue_refund",
        )


def test_blank_entity_values_become_none() -> None:
    entities = IntentEntities(
        order_id="   ",
    )

    assert entities.order_id is None


def test_reason_summary_whitespace_is_normalized() -> None:
    result = IntentResult(
        intent=IntentType.REFUND_REQUEST,
        confidence=0.9,
        reason_summary=(
            "Customer   explicitly   requested   a refund."
        ),
    )

    assert (
        result.reason_summary
        == "Customer explicitly requested a refund."
    )