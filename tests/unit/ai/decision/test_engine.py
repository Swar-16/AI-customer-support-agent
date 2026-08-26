from packages.ai.decision.engine import DecisionEngine, DecisionEngineConfig
from packages.ai.decision.schemas import DecisionReasonCode, DecisionType
from packages.ai.intent.schemas import IntentEntities, IntentResult
from packages.ai.intent.taxonomy import IntentType


def test_unknown_intent_requests_clarification() -> None:
    engine = DecisionEngine()

    intent = IntentResult(
        intent=IntentType.UNKNOWN,
        confidence=0.25,
        needs_clarification=True,
        reason_summary="Intent is unclear.",
    )

    result = engine.decide(intent_result=intent)

    assert result.decision is DecisionType.ASK_CLARIFICATION
    assert result.reason_code is DecisionReasonCode.UNKNOWN_INTENT


def test_low_confidence_requests_clarification() -> None:
    engine = DecisionEngine(
        config=DecisionEngineConfig(
            low_confidence_threshold=0.60
        )
    )

    intent = IntentResult(
        intent=IntentType.PAYMENT_ISSUE,
        confidence=0.45,
        reason_summary="Payment issue may be present.",
    )

    result = engine.decide(intent_result=intent)

    assert result.decision is DecisionType.ASK_CLARIFICATION
    assert (
        result.reason_code
        is DecisionReasonCode.LOW_INTENT_CONFIDENCE
    )


def test_order_status_missing_order_id() -> None:
    engine = DecisionEngine()

    intent = IntentResult(
        intent=IntentType.ORDER_STATUS,
        confidence=0.98,
        entities=IntentEntities(),
        needs_clarification=True,
        reason_summary="Customer wants order status.",
    )

    result = engine.decide(intent_result=intent)

    assert result.decision is DecisionType.ASK_CLARIFICATION
    assert result.required_information == ("order_id",)


def test_order_status_with_order_id_requires_lookup() -> None:
    engine = DecisionEngine()

    intent = IntentResult(
        intent=IntentType.ORDER_STATUS,
        confidence=0.99,
        entities=IntentEntities(
            order_id="ORD-123"
        ),
        needs_clarification=False,
        reason_summary="Customer wants status of ORD-123.",
    )

    result = engine.decide(intent_result=intent)

    assert (
        result.decision
        is DecisionType.RETRIEVE_INFORMATION
    )

    assert (
        result.reason_code
        is DecisionReasonCode.OPERATIONAL_LOOKUP_REQUIRED
    )


def test_refund_request_requires_policy_retrieval() -> None:
    engine = DecisionEngine()

    intent = IntentResult(
        intent=IntentType.REFUND_REQUEST,
        confidence=0.97,
        reason_summary="Customer requests a refund.",
    )

    result = engine.decide(intent_result=intent)

    assert (
        result.decision
        is DecisionType.RETRIEVE_INFORMATION
    )

    assert (
        result.reason_code
        is DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED
    )