# AI-customer-support-agent\packages\database\repositories\dashboard\overview_repository.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.models.ai.retrieval_run import RetrievalRunModel
from packages.database.models.ai.run import AIRunModel
from packages.database.models.audit.api_request import APIRequestModel
from packages.database.models.knowledge.document import KnowledgeDocumentModel
from packages.database.models.knowledge.document_version import KnowledgeDocumentVersionModel
from packages.database.models.support.escalation import EscalationModel
from packages.database.models.support.feedback import FeedbackModel
from packages.database.models.support.ticket import TicketModel

@dataclass(frozen=True, slots=True)
class APITrafficOverview:
    total_requests: int
    successful_requests: int
    client_error_requests: int
    server_error_requests: int
    average_latency_ms: float | None
    p95_latency_ms: float | None

@dataclass(frozen=True, slots=True)
class AIRunOverview:
    total_runs: int
    completed_runs: int
    failed_runs: int
    cancelled_runs: int
    running_runs: int
    average_latency_ms: float | None

@dataclass(frozen=True, slots=True)
class LLMUsageOverview:
    total_calls: int
    successful_calls: int
    failed_calls: int
    timeout_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int
    estimated_cost_usd: Decimal
    average_latency_ms: float | None

@dataclass(frozen=True, slots=True)
class RetrievalOverview:
    total_runs: int
    successful_runs: int
    failed_runs: int
    timeout_runs: int
    zero_result_runs: int
    reranked_runs: int
    average_latency_ms: float | None
    average_selected_candidates: float | None
    average_context_tokens: float | None

@dataclass(frozen=True, slots=True)
class EscalationOverview:
    created_escalations: int
    open_escalations: int
    in_review_escalations: int
    resolved_escalations: int
    dismissed_escalations: int
    high_priority_active: int
    urgent_priority_active: int

@dataclass(frozen=True, slots=True)
class TicketOverview:
    created_tickets: int
    active_tickets: int
    unassigned_active_tickets: int
    resolved_tickets: int
    closed_tickets: int
    high_priority_active: int
    urgent_priority_active: int
    average_resolution_minutes: float | None

@dataclass(frozen=True, slots=True)
class FeedbackOverview:
    submitted_feedback: int
    reviewed_feedback: int
    pending_feedback: int
    rated_feedback: int
    average_rating: float | None
    helpful_feedback: int
    unhelpful_feedback: int
    helpful_percentage: float | None

@dataclass(frozen=True, slots=True)
class KnowledgeOverview:
    created_documents: int
    active_documents: int
    archived_documents: int
    created_versions: int
    published_versions: int
    processing_versions: int
    ready_versions: int
    failed_versions: int

@dataclass(frozen=True, slots=True)
class DashboardOverviewSnapshot:
    started_at: datetime
    ended_at: datetime
    api: APITrafficOverview
    ai_runs: AIRunOverview
    llm: LLMUsageOverview
    retrieval: RetrievalOverview
    escalations: EscalationOverview
    tickets: TicketOverview
    feedback: FeedbackOverview
    knowledge: KnowledgeOverview

class DashboardOverviewRepository:
    """
    Read-optimized SQL aggregation repository for the dashboard overview.

    It does not load full ORM collections into Python and does not mutate or commit database state.

    Time-range metrics describe events occurring within [started_at, ended_at].

    Queue metrics such as active tickets and active escalations represent their current persisted state at query time.
    """
    ACTIVE_ESCALATION_STATUSES = ("open", "in_review")
    ACTIVE_TICKET_STATUSES = ("open", "assigned", "in_progress", "waiting_for_customer",)

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session instance")

        self._session = session

    def get_overview(self, *, started_at: datetime, ended_at: datetime) -> DashboardOverviewSnapshot:
        self._validate_time_range(started_at=started_at, ended_at=ended_at)
        return DashboardOverviewSnapshot(
            started_at=started_at,
            ended_at=ended_at,
            api=self._get_api_overview(started_at=started_at, ended_at=ended_at),
            ai_runs=self._get_ai_run_overview(started_at=started_at, ended_at=ended_at),
            llm=self._get_llm_overview(started_at=started_at, ended_at=ended_at),
            retrieval=self._get_retrieval_overview(started_at=started_at, ended_at=ended_at),
            escalations=self._get_escalation_overview(started_at=started_at, ended_at=ended_at),
            tickets=self._get_ticket_overview(started_at=started_at, ended_at=ended_at),
            feedback=self._get_feedback_overview(started_at=started_at, ended_at=ended_at),
            knowledge=self._get_knowledge_overview(started_at=started_at, ended_at=ended_at),
        )

    def _get_api_overview(self, *, started_at: datetime, ended_at: datetime) -> APITrafficOverview:
        row = self._session.execute(
            select(func.count(APIRequestModel.id),
                   func.count(APIRequestModel.id).filter(APIRequestModel.status_code < 400),
                   func.count(APIRequestModel.id).filter(APIRequestModel.status_code.between(400, 499)),
                   func.count(APIRequestModel.id).filter(APIRequestModel.status_code >= 500),
                   func.avg(APIRequestModel.latency_ms),
                   func.percentile_cont(0.95).within_group(APIRequestModel.latency_ms),
            ).where(APIRequestModel.started_at >= started_at, APIRequestModel.started_at <= ended_at)
        ).one()

        return APITrafficOverview(
            total_requests=self._as_int(row[0]),
            successful_requests=self._as_int(row[1]),
            client_error_requests=self._as_int(row[2]),
            server_error_requests=self._as_int(row[3]),
            average_latency_ms=self._as_optional_float(row[4]),
            p95_latency_ms=self._as_optional_float(row[5]),
        )

    def _get_ai_run_overview(self, *, started_at: datetime, ended_at: datetime) -> AIRunOverview:
        row = self._session.execute(
            select(func.count(AIRunModel.id),
                   func.count(AIRunModel.id).filter(AIRunModel.status == "completed"),
                   func.count(AIRunModel.id).filter(AIRunModel.status == "failed"),
                   func.count(AIRunModel.id).filter(AIRunModel.status == "cancelled"),
                   func.count(AIRunModel.id).filter(AIRunModel.status == "running"),
                   func.avg(AIRunModel.total_latency_ms).filter(AIRunModel.total_latency_ms.is_not(None)),
            ).where(AIRunModel.started_at >= started_at, AIRunModel.started_at <= ended_at)
        ).one()

        return AIRunOverview(
            total_runs=self._as_int(row[0]),
            completed_runs=self._as_int(row[1]),
            failed_runs=self._as_int(row[2]),
            cancelled_runs=self._as_int(row[3]),
            running_runs=self._as_int(row[4]),
            average_latency_ms=self._as_optional_float(row[5]),
        )

    def _get_llm_overview(self, *, started_at: datetime, ended_at: datetime) -> LLMUsageOverview:
        row = self._session.execute(
            select(func.count(LLMCallModel.id),
                   func.count(LLMCallModel.id).filter(LLMCallModel.status == "success"),
                   func.count(LLMCallModel.id).filter(LLMCallModel.status == "failed"),
                   func.count(LLMCallModel.id).filter(LLMCallModel.status == "timeout"),
                   func.coalesce(func.sum(LLMCallModel.input_tokens), 0),
                   func.coalesce(func.sum(LLMCallModel.output_tokens), 0),
                   func.coalesce(func.sum(LLMCallModel.total_tokens), 0),
                   func.coalesce(func.sum(LLMCallModel.cached_input_tokens), 0),
                   func.coalesce(func.sum(LLMCallModel.estimated_cost_usd), Decimal("0")),
                   func.avg(LLMCallModel.latency_ms).filter(LLMCallModel.latency_ms.is_not(None)),
            ).where(LLMCallModel.started_at >= started_at, LLMCallModel.started_at <= ended_at)
        ).one()

        return LLMUsageOverview(
            total_calls=self._as_int(row[0]),
            successful_calls=self._as_int(row[1]),
            failed_calls=self._as_int(row[2]),
            timeout_calls=self._as_int(row[3]),
            input_tokens=self._as_int(row[4]),
            output_tokens=self._as_int(row[5]),
            total_tokens=self._as_int(row[6]),
            cached_input_tokens=self._as_int(row[7]),
            estimated_cost_usd=self._as_decimal(row[8]),
            average_latency_ms=self._as_optional_float(row[9]),
        )

    def _get_retrieval_overview(self, *, started_at: datetime, ended_at: datetime) -> RetrievalOverview:
        row = self._session.execute(
            select(func.count(RetrievalRunModel.id),
                   func.count(RetrievalRunModel.id).filter(RetrievalRunModel.status == "success"),
                   func.count(RetrievalRunModel.id).filter(RetrievalRunModel.status == "failed"),
                   func.count(RetrievalRunModel.id).filter(RetrievalRunModel.status == "timeout"),
                   func.count(RetrievalRunModel.id).filter(RetrievalRunModel.zero_result.is_(True)),
                   func.count(RetrievalRunModel.id).filter(RetrievalRunModel.reranker_used.is_(True)),
                   func.avg(RetrievalRunModel.total_latency_ms).filter(RetrievalRunModel.total_latency_ms.is_not(None)),
                   func.avg(RetrievalRunModel.selected_candidate_count),
                   func.avg(RetrievalRunModel.context_token_count),
            ).where(RetrievalRunModel.started_at >= started_at, RetrievalRunModel.started_at <= ended_at)
        ).one()

        return RetrievalOverview(
            total_runs=self._as_int(row[0]),
            successful_runs=self._as_int(row[1]),
            failed_runs=self._as_int(row[2]),
            timeout_runs=self._as_int(row[3]),
            zero_result_runs=self._as_int(row[4]),
            reranked_runs=self._as_int(row[5]),
            average_latency_ms=self._as_optional_float(row[6]),
            average_selected_candidates=self._as_optional_float(row[7]),
            average_context_tokens=self._as_optional_float(row[8]),
        )

    def _get_escalation_overview(self, *, started_at: datetime, ended_at: datetime) -> EscalationOverview:
        created = self._session.execute(
            select(func.count(EscalationModel.id),
                   func.count(EscalationModel.id).filter(EscalationModel.status == "resolved"),
                   func.count(EscalationModel.id).filter(EscalationModel.status == "dismissed"),
            ).where(EscalationModel.created_at >= started_at, EscalationModel.created_at <= ended_at)
        ).one()

        active = self._session.execute(
            select(func.count(EscalationModel.id).filter(EscalationModel.status == "open"),
                   func.count(EscalationModel.id).filter(EscalationModel.status == "in_review"),
                   func.count(EscalationModel.id).filter(EscalationModel.status.in_(self.ACTIVE_ESCALATION_STATUSES),
                                                         EscalationModel.priority == "high"),
                   func.count(EscalationModel.id).filter(EscalationModel.status.in_(self.ACTIVE_ESCALATION_STATUSES),
                                                         EscalationModel.priority == "urgent"),
            )
        ).one()

        return EscalationOverview(
            created_escalations=self._as_int(created[0]),
            open_escalations=self._as_int(active[0]),
            in_review_escalations=self._as_int(active[1]),
            resolved_escalations=self._as_int(created[1]),
            dismissed_escalations=self._as_int(created[2]),
            high_priority_active=self._as_int(active[2]),
            urgent_priority_active=self._as_int(active[3]),
        )

    def _get_ticket_overview(self, *, started_at: datetime, ended_at: datetime) -> TicketOverview:
        created = self._session.execute(
            select(func.count(TicketModel.id),
                   func.count(TicketModel.id).filter(TicketModel.status == "resolved"),
                   func.count(TicketModel.id).filter(TicketModel.status == "closed"),
                   func.avg(func.extract("epoch", TicketModel.resolved_at - TicketModel.created_at) / 60.0).filter(TicketModel.resolved_at.is_not(None)),
            ).where(TicketModel.created_at >= started_at, TicketModel.created_at <= ended_at)
        ).one()

        active = self._session.execute(
            select(func.count(TicketModel.id).filter(TicketModel.status.in_(self.ACTIVE_TICKET_STATUSES)),
                   func.count(TicketModel.id).filter(TicketModel.status.in_(self.ACTIVE_TICKET_STATUSES),
                                                     TicketModel.assigned_agent_id.is_(None)),
                   func.count(TicketModel.id).filter(TicketModel.status.in_(self.ACTIVE_TICKET_STATUSES),
                                                     TicketModel.priority == "high"),
                   func.count(TicketModel.id).filter(TicketModel.status.in_(self.ACTIVE_TICKET_STATUSES),
                                                     TicketModel.priority == "urgent"),
            )
        ).one()

        return TicketOverview(
            created_tickets=self._as_int(created[0]),
            active_tickets=self._as_int(active[0]),
            unassigned_active_tickets=self._as_int(active[1]),
            resolved_tickets=self._as_int(created[1]),
            closed_tickets=self._as_int(created[2]),
            high_priority_active=self._as_int(active[2]),
            urgent_priority_active=self._as_int(active[3]),
            average_resolution_minutes=self._as_optional_float(created[3]),
        )

    def _get_feedback_overview(self, *, started_at: datetime, ended_at: datetime) -> FeedbackOverview:
        row = self._session.execute(
            select(func.count(FeedbackModel.id),
                   func.count(FeedbackModel.id).filter(FeedbackModel.status == "reviewed"),
                   func.count(FeedbackModel.id).filter(FeedbackModel.status == "pending"),
                   func.count(FeedbackModel.id).filter(FeedbackModel.rating.is_not(None)),
                   func.avg(FeedbackModel.rating).filter(FeedbackModel.rating.is_not(None)),
                   func.count(FeedbackModel.id).filter(FeedbackModel.helpful.is_(True)),
                   func.count(FeedbackModel.id).filter(FeedbackModel.helpful.is_(False)),
            ).where(FeedbackModel.created_at >= started_at, FeedbackModel.created_at <= ended_at)
        ).one()

        helpful_count = self._as_int(row[5])
        unhelpful_count = self._as_int(row[6])
        helpful_denominator = helpful_count + unhelpful_count
        helpful_percentage = (helpful_count / helpful_denominator) * 100.0 if helpful_denominator > 0 else None

        return FeedbackOverview(
            submitted_feedback=self._as_int(row[0]),
            reviewed_feedback=self._as_int(row[1]),
            pending_feedback=self._as_int(row[2]),
            rated_feedback=self._as_int(row[3]),
            average_rating=self._as_optional_float(row[4]),
            helpful_feedback=helpful_count,
            unhelpful_feedback=unhelpful_count,
            helpful_percentage=helpful_percentage,
        )

    def _get_knowledge_overview(self, *, started_at: datetime, ended_at: datetime) -> KnowledgeOverview:
        document_row = self._session.execute(
            select(func.count(KnowledgeDocumentModel.id).filter(KnowledgeDocumentModel.created_at >= started_at,
                                                                KnowledgeDocumentModel.created_at <= ended_at),
                   func.count(KnowledgeDocumentModel.id).filter(KnowledgeDocumentModel.status == "active"),
                   func.count(KnowledgeDocumentModel.id).filter(KnowledgeDocumentModel.status == "archived"),
            )
        ).one()

        version_row = self._session.execute(
            select(func.count(KnowledgeDocumentVersionModel.id).filter(KnowledgeDocumentVersionModel.created_at >= started_at,
                                                                       KnowledgeDocumentVersionModel.created_at <= ended_at),
                   func.count(KnowledgeDocumentVersionModel.id).filter(KnowledgeDocumentVersionModel.published_at >= started_at,
                                                                       KnowledgeDocumentVersionModel.published_at <= ended_at),
                   func.count(KnowledgeDocumentVersionModel.id).filter(KnowledgeDocumentVersionModel.status == "processing"),
                   func.count(KnowledgeDocumentVersionModel.id).filter(KnowledgeDocumentVersionModel.status == "ready"),
                   func.count(KnowledgeDocumentVersionModel.id).filter(KnowledgeDocumentVersionModel.status == "failed"),
            )
        ).one()

        return KnowledgeOverview(
            created_documents=self._as_int(document_row[0]),
            active_documents=self._as_int(document_row[1]),
            archived_documents=self._as_int(document_row[2]),
            created_versions=self._as_int(version_row[0]),
            published_versions=self._as_int(version_row[1]),
            processing_versions=self._as_int(version_row[2]),
            ready_versions=self._as_int(version_row[3]),
            failed_versions=self._as_int(version_row[4]),
        )

    @staticmethod
    def _validate_time_range(*, started_at: datetime, ended_at: datetime) -> None:
        for field_name, value in (("started_at", started_at), ("ended_at", ended_at),):
            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime")

            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")

        if started_at > ended_at:
            raise ValueError("started_at cannot be later than ended_at")

    @staticmethod
    def _as_int(value: object) -> int:
        return int(value or 0)

    @staticmethod
    def _as_optional_float(value: object) -> float | None:
        if value is None:
            return None

        return float(value)

    @staticmethod
    def _as_decimal(value: object) -> Decimal:
        if value is None:
            return Decimal("0")

        if isinstance(value, Decimal):
            return value

        return Decimal(str(value))