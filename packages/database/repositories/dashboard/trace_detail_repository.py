# AI-customer-support-agent\packages\database\repositories\dashboard\trace_detail_repository.py
from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import TypeVar
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from packages.database.models.ai.embedding_call import EmbeddingCallModel
from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.models.ai.retrieval_candidate import RetrievalCandidateModel
from packages.database.models.ai.retrieval_run import RetrievalRunModel
from packages.database.models.ai.reranker_call import RerankerCallModel
from packages.database.models.ai.run import AIRunModel
from packages.database.models.ai.stage_event import AIStageEventModel
from packages.database.models.audit.api_request import APIRequestModel
from packages.database.models.audit.audit_event import AuditEventModel
from packages.database.models.support.escalation import EscalationModel
from packages.database.models.support.feedback import FeedbackModel
from packages.database.models.support.ticket import TicketModel

_ModelT = TypeVar("_ModelT")

@dataclass(frozen=True, slots=True)
class TraceDetailRecord:
    """
    Complete persistence snapshot for one trace.

    This is an internal dashboard read model. The application layer must map these ORM records into sanitized API-facing models.

    In particular, the API layer must not expose:

    - LLM or provider error messages
    - ticket descriptions or resolution summaries
    - escalation handoff summaries
    - feedback comments or review notes
    - arbitrary metadata dictionaries without allow-listing their fields
    """
    trace_id: uuid.UUID
    api_requests: tuple[APIRequestModel, ...]
    ai_runs: tuple[AIRunModel, ...]
    stage_events: tuple[AIStageEventModel, ...]
    llm_calls: tuple[LLMCallModel, ...]
    embedding_calls: tuple[EmbeddingCallModel, ...]
    retrieval_runs: tuple[RetrievalRunModel, ...]
    retrieval_candidates: tuple[RetrievalCandidateModel, ...]
    reranker_calls: tuple[RerankerCallModel, ...]
    escalations: tuple[EscalationModel, ...]
    tickets: tuple[TicketModel, ...]
    feedback: tuple[FeedbackModel, ...]
    audit_events: tuple[AuditEventModel, ...]

    @property
    def exists(self) -> bool:
        return any((self.api_requests, self.ai_runs, self.stage_events, self.llm_calls, self.embedding_calls, self.retrieval_runs, 
                    self.reranker_calls, self.escalations, self.tickets, self.feedback, self.audit_events,))

class DashboardTraceDetailRepository:
    """
    Read-only repository for assembling a complete correlated trace.

    The repository performs no writes and does not own the transaction.
    """
    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    def get_trace_detail(self, trace_id: uuid.UUID) -> TraceDetailRecord | None:
        self._validate_uuid(trace_id, field_name="trace_id")

        api_requests = self._all(select(APIRequestModel)
                                 .where(APIRequestModel.trace_id == trace_id)
                                 .order_by(APIRequestModel.started_at.asc(),
                                           APIRequestModel.id.asc())
        )
        ai_runs = self._all(select(AIRunModel)
                            .where(AIRunModel.trace_id == trace_id)
                            .order_by(AIRunModel.started_at.asc(),
                                      AIRunModel.id.asc())
        )
        ai_run_ids = tuple(run.id for run in ai_runs)
        stage_events = self._all(select(AIStageEventModel)
                                 .where(AIStageEventModel.trace_id == trace_id)
                                 .order_by(AIStageEventModel.occurred_at.asc(),
                                           AIStageEventModel.id.asc())
        )
        llm_calls = self._load_llm_calls(ai_run_ids)
        embedding_calls = self._load_embedding_calls(trace_id=trace_id, ai_run_ids=ai_run_ids)
        retrieval_runs = self._load_retrieval_runs(trace_id=trace_id, ai_run_ids=ai_run_ids)
        retrieval_run_ids = tuple(retrieval_run.id for retrieval_run in retrieval_runs)
        retrieval_candidates = self._load_retrieval_candidates(retrieval_run_ids)
        reranker_calls = self._load_reranker_calls(trace_id=trace_id, retrieval_run_ids=retrieval_run_ids)
        audit_events = self._all(select(AuditEventModel)
                                 .where(AuditEventModel.trace_id == trace_id)
                                 .order_by(AuditEventModel.occurred_at.asc(),
                                           AuditEventModel.id.asc())
        )
        audited_escalation_ids = self._audited_entity_ids(audit_events, entity_type="escalation")
        audited_ticket_ids = self._audited_entity_ids(audit_events, entity_type="ticket")
        audited_feedback_ids = self._audited_entity_ids(audit_events, entity_type="feedback")
        escalations = self._load_escalations(ai_run_ids=ai_run_ids, audited_ids=audited_escalation_ids)
        escalation_ids = tuple(escalation.id for escalation in escalations)
        tickets = self._load_tickets(escalation_ids=escalation_ids, audited_ids=audited_ticket_ids)
        feedback = self._load_feedback(ai_run_ids=ai_run_ids, audited_ids=audited_feedback_ids)

        detail = TraceDetailRecord(
            trace_id=trace_id,
            api_requests=api_requests,
            ai_runs=ai_runs,
            stage_events=stage_events,
            llm_calls=llm_calls,
            embedding_calls=embedding_calls,
            retrieval_runs=retrieval_runs,
            retrieval_candidates=retrieval_candidates,
            reranker_calls=reranker_calls,
            escalations=escalations,
            tickets=tickets,
            feedback=feedback,
            audit_events=audit_events,
        )

        if not detail.exists:
            return None

        return detail

    def _load_llm_calls(self, ai_run_ids: tuple[uuid.UUID, ...]) -> tuple[LLMCallModel, ...]:
        if not ai_run_ids:
            return ()

        return self._all(select(LLMCallModel)
                         .where(LLMCallModel.ai_run_id.in_(ai_run_ids))
                         .order_by(LLMCallModel.started_at.asc(),
                                   LLMCallModel.id.asc())
        )

    def _load_embedding_calls(self, *, trace_id: uuid.UUID, ai_run_ids: tuple[uuid.UUID, ...]) -> tuple[EmbeddingCallModel, ...]:
        conditions = [EmbeddingCallModel.trace_id == trace_id,]
        if ai_run_ids:
            conditions.append(EmbeddingCallModel.ai_run_id.in_(ai_run_ids))

        return self._all(select(EmbeddingCallModel)
                         .where(or_(*conditions))
                         .order_by(EmbeddingCallModel.started_at.asc(),
                                   EmbeddingCallModel.id.asc())
        )

    def _load_retrieval_runs(self, *, trace_id: uuid.UUID, ai_run_ids: tuple[uuid.UUID, ...]) -> tuple[RetrievalRunModel, ...]:
        conditions = [RetrievalRunModel.trace_id == trace_id]
        if ai_run_ids:
            conditions.append(RetrievalRunModel.ai_run_id.in_(ai_run_ids))

        return self._all(select(RetrievalRunModel)
                         .where(or_(*conditions))
                         .order_by(RetrievalRunModel.started_at.asc(),
                                   RetrievalRunModel.id.asc())
        )

    def _load_retrieval_candidates(self, retrieval_run_ids: tuple[uuid.UUID, ...]) -> tuple[RetrievalCandidateModel, ...]:
        if not retrieval_run_ids:
            return ()

        return self._all(select(RetrievalCandidateModel)
                         .where(RetrievalCandidateModel.retrieval_run_id.in_(retrieval_run_ids))
                         .order_by(RetrievalCandidateModel.retrieval_run_id.asc(),
                                   RetrievalCandidateModel.final_rank.asc().nulls_last(),
                                   RetrievalCandidateModel.id.asc())
        )

    def _load_reranker_calls(self, *, trace_id: uuid.UUID, retrieval_run_ids: tuple[uuid.UUID, ...]) -> tuple[RerankerCallModel, ...]:
        conditions = [RerankerCallModel.trace_id == trace_id]
        if retrieval_run_ids:
            conditions.append(RerankerCallModel.retrieval_run_id.in_(retrieval_run_ids))

        return self._all(select(RerankerCallModel)
                         .where(or_(*conditions))
                         .order_by(RerankerCallModel.started_at.asc(),
                                   RerankerCallModel.id.asc())
        )

    def _load_escalations(self, *, ai_run_ids: tuple[uuid.UUID, ...], audited_ids: tuple[uuid.UUID, ...]) -> tuple[EscalationModel, ...]:
        conditions = []
        if ai_run_ids:
            conditions.append(EscalationModel.ai_run_id.in_(ai_run_ids))

        if audited_ids:
            conditions.append(EscalationModel.id.in_(audited_ids))

        if not conditions:
            return ()

        return self._all(select(EscalationModel)
                         .where(or_(*conditions))
                         .order_by(EscalationModel.created_at.asc(),
                                   EscalationModel.id.asc())
        )

    def _load_tickets(self, *, escalation_ids: tuple[uuid.UUID, ...], audited_ids: tuple[uuid.UUID, ...]) -> tuple[TicketModel, ...]:
        conditions = []
        if escalation_ids:
            conditions.append(TicketModel.escalation_id.in_(escalation_ids))

        if audited_ids:
            conditions.append(TicketModel.id.in_(audited_ids))

        if not conditions:
            return ()

        return self._all(select(TicketModel)
                         .where(or_(*conditions))
                         .order_by(TicketModel.created_at.asc(),
                                   TicketModel.id.asc())
        )

    def _load_feedback(self, *, ai_run_ids: tuple[uuid.UUID, ...], audited_ids: tuple[uuid.UUID, ...]) -> tuple[FeedbackModel, ...]:
        conditions = []
        if ai_run_ids:
            conditions.append(FeedbackModel.ai_run_id.in_(ai_run_ids))

        if audited_ids:
            conditions.append(FeedbackModel.id.in_(audited_ids))

        if not conditions:
            return ()

        return self._all(select(FeedbackModel)
                         .where(or_(*conditions))
                         .order_by(FeedbackModel.created_at.asc(),
                                   FeedbackModel.id.asc())
        )

    def _all(self, statement: Select[tuple[_ModelT]]) -> tuple[_ModelT, ...]:
        return tuple(self._session.scalars(statement).all())

    @staticmethod
    def _audited_entity_ids(events: tuple[AuditEventModel, ...], *, entity_type: str) -> tuple[uuid.UUID, ...]:
        return tuple(dict.fromkeys(event.entity_id for event in events if event.entity_type == entity_type))

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")