from __future__ import annotations

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker
from uuid6 import uuid7

from apps.api.app.main import create_api_app

from packages.ai.intent.schemas import IntentResult
from packages.ai.providers.mock import MockLLMProvider

from packages.application.composition.application_factory import (
    ApplicationServices,
    create_application,
)

from packages.config.settings import get_settings

from packages.database.models.ai.decision import AIDecisionModel
from packages.database.models.ai.intent_prediction import IntentPredictionModel
from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.conversation import ConversationModel
from packages.database.models.support.message import MessageModel
from packages.database.models.support.user import UserModel

from packages.database.session import create_session_factory


# ---------------------------------------------------------------------------
# Settings / database
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_settings():
    settings = get_settings("test")

    if settings.database_url.database != "support_ai_test":
        raise RuntimeError(
            "Integration tests must run against support_ai_test."
        )

    return settings


@pytest.fixture(scope="session")
def test_session_factory(test_settings):
    return create_session_factory(
        database_url=test_settings.database_url,
        echo=False,
    )


# ---------------------------------------------------------------------------
# Database cleanup
# ---------------------------------------------------------------------------


@pytest.fixture()
def clean_database(test_session_factory) -> Generator[None, None, None]:
    """
    Keep API integration tests isolated.

    The application service owns and commits its own transactions, so wrapping
    tests in an outer rollback transaction would not isolate committed writes.
    """

    _clear_database(test_session_factory)

    yield

    _clear_database(test_session_factory)


def _clear_database(session_factory: sessionmaker) -> None:
    with session_factory() as session:
        # Delete child tables before FK parents.

        session.execute(delete(AIDecisionModel))
        session.execute(delete(IntentPredictionModel))
        session.execute(delete(LLMCallModel))
        session.execute(delete(AIRunModel))

        session.execute(delete(MessageModel))
        session.execute(delete(ConversationModel))
        session.execute(delete(UserModel))

        session.commit()


# ---------------------------------------------------------------------------
# Deterministic LLM
# ---------------------------------------------------------------------------


def _structured_llm_resolver(
    system_prompt: str,
    user_prompt: str,
    response_model: type[BaseModel],
) -> dict[str, Any] | BaseModel:
    """
    Deterministic boundary for API integration tests.

    We keep the real:
        FastAPI
        application service
        UoW
        repositories
        PostgreSQL
        orchestration
        IntentClassifier
        DecisionEngine
        telemetry

    Only the external LLM behaviour is controlled.
    """

    if response_model is IntentResult:
        return {
            "intent": "order_status",
            "confidence": 0.99,
            "entities": {
                "order_id": "ORD-12345",
            },
            "needs_clarification": False,
            "reason_summary": (
                "Customer is asking for the status of a specific order."
            ),
        }

    raise AssertionError(
        f"Unexpected structured response model: "
        f"{response_model.__name__}"
    )


@pytest.fixture()
def mock_llm_provider() -> MockLLMProvider:
    return MockLLMProvider(
        structured_resolver=_structured_llm_resolver,
    )


# ---------------------------------------------------------------------------
# Real application composition
# ---------------------------------------------------------------------------


@pytest.fixture()
def application_services(
    test_settings,
    test_session_factory,
    mock_llm_provider,
) -> ApplicationServices:
    return create_application(
        settings=test_settings,
        session_factory=test_session_factory,
        base_provider=mock_llm_provider,
    )


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch,
    application_services: ApplicationServices,
) -> Generator[TestClient, None, None]:

    monkeypatch.setattr(
        "apps.api.app.main.get_application_services",
        lambda: application_services,
    )

    app = create_api_app()

    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_conversation(test_session_factory) -> uuid.UUID:
    user_id = uuid7()
    conversation_id = uuid7()

    with test_session_factory() as session:
        user = UserModel(
            id=user_id,
        )

        session.add(user)

        # Explicitly establish FK parent before conversation insert.
        session.flush()

        conversation = ConversationModel(
            id=conversation_id,
            user_id=user_id,
        )

        session.add(conversation)
        session.commit()

    return conversation_id