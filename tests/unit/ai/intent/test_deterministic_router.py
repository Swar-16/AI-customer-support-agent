# AI-customer-support-agent\tests\unit\ai\intent\test_deterministic_router.py
import pytest

from packages.ai.intent.deterministic_router import DeterministicIntentRouter
from packages.ai.intent.schemas import EscalationSignal
from packages.ai.intent.taxonomy import IntentType


@pytest.fixture
def router() -> DeterministicIntentRouter:
    return DeterministicIntentRouter()


@pytest.mark.parametrize(
    ("message", "route_kind"),
    [
        ("Hello", "greeting"),
        ("Hi!", "greeting"),
        ("Good morning", "greeting"),
        ("Thank you", "thanks"),
        ("Thanks!", "thanks"),
        ("Goodbye", "goodbye"),
        ("Have a great day", "goodbye"),
        ("What can you help me with?", "capabilities"),
        ("What can you do?", "capabilities"),
        ("Show me your capabilities", "capabilities"),
    ],
)
def test_routes_safe_conversational_messages(
    router: DeterministicIntentRouter,
    message: str,
    route_kind: str,
) -> None:
    route = router.route(customer_message=message)

    assert route is not None
    assert route.route_kind == route_kind
    assert route.intent_result.intent is IntentType.CONVERSATIONAL
    assert route.intent_result.confidence == 1.0
    assert route.intent_result.needs_clarification is False
    assert route.intent_result.escalation_signals == ()


@pytest.mark.parametrize(
    "message",
    [
        "Connect me to a human agent",
        "I want to speak with a support agent",
        "Transfer this to a representative",
        "Human agent please",
    ],
)
def test_routes_explicit_human_requests(
    router: DeterministicIntentRouter,
    message: str,
) -> None:
    route = router.route(customer_message=message)

    assert route is not None
    assert route.route_kind == "explicit_human_request"
    assert route.intent_result.intent is IntentType.CONVERSATIONAL
    assert route.intent_result.escalation_signals == (
        EscalationSignal.EXPLICIT_HUMAN_REQUEST,
    )


@pytest.mark.parametrize(
    "message",
    [
        "Hello, where is my order?",
        "Hi, I need a refund",
        "Thanks, but my payment is still failing",
        "Goodbye, but first cancel my subscription",
        "My account credentials were stolen",
        "My return was rejected",
        "I was charged twice",
        "Where is order ORD-123?",
        "Can you help me with my refund?",
        "I need help",
        "This has failed three times and nobody has helped me",
        "Write a sorting algorithm",
        "asdjkh qweqwe",
    ],
)
def test_defers_substantive_or_ambiguous_messages(
    router: DeterministicIntentRouter,
    message: str,
) -> None:
    assert router.route(customer_message=message) is None


def test_blank_message_is_not_routed(
    router: DeterministicIntentRouter,
) -> None:
    assert router.route(customer_message="   ") is None


def test_rejects_non_string_input(
    router: DeterministicIntentRouter,
) -> None:
    with pytest.raises(TypeError):
        router.route(customer_message=None)  # type: ignore[arg-type]