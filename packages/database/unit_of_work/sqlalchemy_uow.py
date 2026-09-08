# AI-customer-support-agent\packages\database\unit_of_work\sqlalchemy_uow.py
from __future__ import annotations
from types import TracebackType
from typing import TypeAlias
from sqlalchemy.orm import Session, sessionmaker

from packages.database.repositories.ai.ai_run_repository import AIRunRepository
from packages.database.repositories.ai.decision_repository import AIDecisionRepository
from packages.database.repositories.ai.intent_prediction_repository import IntentPredictionRepository
from packages.database.repositories.ai.llm_call_repository import LLMCallRepository
from packages.database.repositories.audit.api_request_repository import APIRequestRepository
from packages.database.repositories.audit.audit_event_repository import AuditEventRepository
from packages.database.repositories.support.conversation_repository import ConversationRepository
from packages.database.repositories.support.message_repository import MessageRepository
from packages.database.repositories.support.user_repository import UserRepository
from packages.database.repositories.support.escalation_repository import EscalationRepository
from packages.database.repositories.support.ticket_repository import TicketRepository
from packages.database.repositories.support.ticket_comment_repository import TicketCommentRepository
from packages.database.repositories.support.feedback_repository import FeedbackRepository
from packages.database.repositories.ai.stage_event_repository import AIStageEventRepository
from packages.database.repositories.ai.embedding_call_repository import EmbeddingCallRepository
from packages.database.repositories.ai.retrieval_repository import RetrievalRepository
from packages.database.repositories.ai.reranker_call_repository import RerankerCallRepository
from packages.database.session import SessionLocal

SessionFactory: TypeAlias = sessionmaker[Session]

class SqlAlchemyUnitOfWork:
    """
    SQLAlchemy-backed Unit of Work.
    One instance represents one database transaction boundary. All repositories exposed by this object share the exact same Session.

    Typical usage:
        with SqlAlchemyUnitOfWork() as uow:
            ...
            uow.commit()

    If:
      - an exception escapes the block, or
      - commit() is never called,

    the transaction is rolled back when the context exits.
    """
    def __init__(self, session_factory: SessionFactory = SessionLocal) -> None:
        if session_factory is None:
            raise TypeError("session_factory cannot be None")

        self._session_factory = session_factory
        self.session: Session | None = None
        
        self.api_requests: APIRequestRepository | None = None
        self.audit_events: AuditEventRepository | None = None
        
        self.users: UserRepository | None = None
        self.conversations: ConversationRepository | None = None
        self.messages: MessageRepository | None = None
        self.escalations: EscalationRepository | None = None
        self.tickets: TicketRepository | None = None
        self.ticket_comments: TicketCommentRepository | None = None
        self.feedback: FeedbackRepository | None = None
        
        self.ai_runs: AIRunRepository | None = None
        self.llm_calls: LLMCallRepository | None = None
        self.intent_predictions: IntentPredictionRepository | None = None
        self.ai_decisions: AIDecisionRepository | None = None
        self.stage_events: AIStageEventRepository | None = None
        self.embedding_calls: EmbeddingCallRepository | None = None
        self.retrieval: RetrievalRepository | None = None
        self.reranker_calls: RerankerCallRepository | None = None

        self._committed = False
        self._entered = False

    # Context-manager lifecycle
    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        if self._entered:
            raise RuntimeError("Unit of work cannot be entered more than once")

        self.session = self._session_factory()
        
        self.api_requests = APIRequestRepository(self.session)
        self.audit_events = AuditEventRepository(self.session)

        self.users = UserRepository(self.session)
        self.conversations = ConversationRepository(self.session)
        self.messages = MessageRepository(self.session)
        self.escalations = EscalationRepository(self.session)
        self.tickets = TicketRepository(self.session)
        self.ticket_comments = TicketCommentRepository(self.session)
        self.feedback = FeedbackRepository(self.session)

        self.ai_runs = AIRunRepository(self.session)
        self.llm_calls = LLMCallRepository(self.session)
        self.intent_predictions = IntentPredictionRepository(self.session)
        self.ai_decisions = AIDecisionRepository(self.session)
        self.stage_events = AIStageEventRepository(self.session)
        self.embedding_calls = EmbeddingCallRepository(self.session)
        self.retrieval = RetrievalRepository(self.session)
        self.reranker_calls = RerankerCallRepository(self.session)

        self._entered = True
        self._committed = False

        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        if self.session is None:
            return

        try:
            # Explicit transaction semantics:
            #
            # exception → rollback
            # no explicit commit → rollback
            #
            # This prevents accidental partial persistence simply because
            # application code forgot to call commit().
            if exc_type is not None or not self._committed:
                self.session.rollback()

        finally:
            self.session.close()
            self._clear_state()
            
    ## This design helps to follow this
    # explicit commit      → persist
    # exception            → rollback
    # forgot commit        → rollback

    # Transaction operations
    def commit(self) -> None:
        session = self._require_session()
        session.commit()
        self._committed = True

    def rollback(self) -> None:
        session = self._require_session()
        session.rollback()
        self._committed = False

    def flush(self) -> None:
        """
        Flush pending ORM changes without committing the transaction.
        """
        session = self._require_session()
        session.flush()

    # Internal helpers
    def _require_session(self) -> Session:
        if not self._entered or self.session is None:
            raise RuntimeError("Unit of work has not been started. Use it inside a 'with' block.")

        return self.session

    def _clear_state(self) -> None:
        """
        Drop references after the context ends.
        Prevents accidental reuse of repositories backed by a closed Session.
        """

        self.session = None
        
        self.api_requests = None
        self.audit_events = None
        
        self.users = None
        self.conversations = None
        self.messages = None
        self.escalations = None
        self.tickets = None
        self.ticket_comments = None
        self.feedback = None

        self.ai_runs = None
        self.llm_calls = None
        self.intent_predictions = None
        self.ai_decisions = None
        self.stage_events = None
        self.embedding_calls = None
        self.retrieval = None
        self.reranker_calls = None

        self._entered = False
        self._committed = False