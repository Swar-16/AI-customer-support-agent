from collections.abc import Generator
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from packages.config.settings import get_settings
from packages.database.session import create_session_factory
from packages.database.models.ai.decision import AIDecisionModel
from packages.database.models.ai.intent_prediction import IntentPredictionModel
from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.conversation import ConversationModel
from packages.database.models.support.message import MessageModel
from packages.database.models.support.user import UserModel
from packages.database.models.knowledge.chunk import KnowledgeChunkModel
from packages.database.models.knowledge.document_version import KnowledgeDocumentVersionModel
from packages.database.models.knowledge.document import KnowledgeDocumentModel
from packages.database.models.knowledge.chunk_embedding import KnowledgeChunkEmbeddingModel


@pytest.fixture(scope="session")
def test_settings():
    settings = get_settings("test")
    if settings.database_url.database != "support_ai_test":
        raise RuntimeError("Integration tests must run against support_ai_test.")

    return settings


@pytest.fixture(scope="session")
def test_session_factory(test_settings):
    return create_session_factory(database_url=test_settings.database_url, echo=False)


@pytest.fixture()
def clean_database(test_session_factory) -> Generator[None, None, None]:
    _clear_database(test_session_factory)

    yield

    _clear_database(test_session_factory)


def _clear_database(session_factory: sessionmaker) -> None:
    with session_factory() as session:
        session.execute(delete(AIDecisionModel))
        session.execute(delete(IntentPredictionModel))
        session.execute(delete(LLMCallModel))
        session.execute(delete(AIRunModel))

        session.execute(delete(MessageModel))
        session.execute(delete(ConversationModel))
        session.execute(delete(UserModel))
        
        session.execute(delete(KnowledgeChunkEmbeddingModel))
        session.execute(delete(KnowledgeChunkModel))
        session.execute(delete(KnowledgeDocumentVersionModel))
        session.execute(delete(KnowledgeDocumentModel))

        session.commit()