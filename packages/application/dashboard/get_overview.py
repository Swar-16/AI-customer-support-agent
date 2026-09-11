# AI-customer-support-agent\packages\application\dashboard\get_overview.py
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from packages.application.dashboard.models import DashboardMetric, DashboardTimeRange
from packages.database.repositories.dashboard import DashboardOverviewRepository, DashboardOverviewSnapshot
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

class GetDashboardOverviewError(RuntimeError):
    """Base error for dashboard-overview retrieval."""

class DashboardOverviewPersistenceContractError(GetDashboardOverviewError):
    """Raised when the Unit of Work lacks the required read repository."""

@dataclass(frozen=True, slots=True)
class GetDashboardOverviewCommand:
    time_range: DashboardTimeRange

    def __post_init__(self) -> None:
        if not isinstance(self.time_range, DashboardTimeRange):
            raise TypeError("time_range must be a DashboardTimeRange")

@dataclass(frozen=True, slots=True)
class DashboardOverviewSection:
    key: str
    title: str
    metrics: tuple[DashboardMetric, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.key, str):
            raise TypeError("key must be a string")

        if not isinstance(self.title, str):
            raise TypeError("title must be a string")

        normalized_key = self.key.strip().lower()
        normalized_title = self.title.strip()
        if not normalized_key:
            raise ValueError("key cannot be blank")

        if not normalized_title:
            raise ValueError("title cannot be blank")

        if not isinstance(self.metrics, tuple):
            raise TypeError("metrics must be a tuple")

        if not self.metrics:
            raise ValueError("metrics cannot be empty")

        if not all(isinstance(metric, DashboardMetric) for metric in self.metrics):
            raise TypeError("every metric must be a DashboardMetric")

        metric_keys = tuple(metric.key for metric in self.metrics)

        if len(metric_keys) != len(set(metric_keys)):
            raise ValueError("metric keys must be unique within a section")

        object.__setattr__(self, "key", normalized_key)
        object.__setattr__(self, "title", normalized_title)

@dataclass(frozen=True, slots=True)
class DashboardOverviewResult:
    time_range: DashboardTimeRange
    generated_at: datetime
    sections: tuple[DashboardOverviewSection, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.time_range, DashboardTimeRange):
            raise TypeError("time_range must be a DashboardTimeRange")

        if not isinstance(self.generated_at, datetime):
            raise TypeError("generated_at must be a datetime")

        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")

        if not isinstance(self.sections, tuple):
            raise TypeError("sections must be a tuple")

        if not self.sections:
            raise ValueError("sections cannot be empty")

        if not all(isinstance(section, DashboardOverviewSection) for section in self.sections):
            raise TypeError("every section must be a DashboardOverviewSection")

        section_keys = tuple(section.key for section in self.sections)

        if len(section_keys) != len(set(section_keys)):
            raise ValueError("section keys must be unique")

        object.__setattr__(self, "generated_at", self.generated_at.astimezone(timezone.utc))

    def get_section(self, key: str) -> DashboardOverviewSection | None:
        if not isinstance(key, str):
            raise TypeError("key must be a string")

        normalized = key.strip().lower()
        for section in self.sections:
            if section.key == normalized:
                return section

        return None

class GetDashboardOverview:
    """
    Build the fixed MVP dashboard overview.

    Responsibilities:

    - validate the reporting interval;
    - execute efficient SQL aggregates through the dashboard repository;
    - calculate derived rates safely;
    - expose repository-independent dashboard sections and metrics;
    - never mutate or commit database state.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def execute(self, command: GetDashboardOverviewCommand) -> DashboardOverviewResult:
        if not isinstance(command, GetDashboardOverviewCommand):
            raise TypeError("command must be a GetDashboardOverviewCommand")

        with self._uow_factory() as uow:
            repository = self._require_repository(uow)
            snapshot = repository.get_overview(started_at=command.time_range.started_at, ended_at=command.time_range.ended_at)
            return self._build_result(snapshot=snapshot, time_range=command.time_range)

    @staticmethod
    def _require_repository(uow: SqlAlchemyUnitOfWork) -> DashboardOverviewRepository:
        repository = uow.dashboard_overview
        if repository is None:
            raise DashboardOverviewPersistenceContractError("DashboardOverviewRepository unavailable")

        if not isinstance(repository, DashboardOverviewRepository):
            raise DashboardOverviewPersistenceContractError("dashboard_overview has an invalid repository type")

        return repository

    @classmethod
    def _build_result(cls, *, snapshot: DashboardOverviewSnapshot, time_range: DashboardTimeRange) -> DashboardOverviewResult:
        return DashboardOverviewResult(
            time_range=time_range,
            generated_at=datetime.now(timezone.utc),
            sections=(
                cls._api_section(snapshot),
                cls._ai_run_section(snapshot),
                cls._llm_section(snapshot),
                cls._retrieval_section(snapshot),
                cls._escalation_section(snapshot),
                cls._ticket_section(snapshot),
                cls._feedback_section(snapshot),
                cls._knowledge_section(snapshot),
            ),
        )

    @classmethod
    def _api_section(cls, snapshot: DashboardOverviewSnapshot) -> DashboardOverviewSection:
        api = snapshot.api
        error_count = api.client_error_requests + api.server_error_requests
        return DashboardOverviewSection(
            key="api",
            title="API Traffic",
            metrics=(
                DashboardMetric(key="total_requests", value=api.total_requests, unit="requests"),
                DashboardMetric(key="successful_requests", value=api.successful_requests, unit="requests"),
                DashboardMetric(key="client_error_requests", value=api.client_error_requests, unit="requests"),
                DashboardMetric(key="server_error_requests", value=api.server_error_requests, unit="requests"),
                DashboardMetric(key="error_rate", value=cls._percentage(numerator=error_count, denominator=api.total_requests), unit="percent"),
                DashboardMetric(key="average_latency", value=api.average_latency_ms or 0.0, unit="milliseconds", metadata={"has_data": api.average_latency_ms is not None}),
                DashboardMetric(key="p95_latency", value=api.p95_latency_ms or 0.0, unit="milliseconds", metadata={"has_data": api.p95_latency_ms is not None}),
            ),
        )

    @classmethod
    def _ai_run_section(cls, snapshot: DashboardOverviewSnapshot) -> DashboardOverviewSection:
        runs = snapshot.ai_runs
        return DashboardOverviewSection(
            key="ai_runs",
            title="AI Runs",
            metrics=(
                DashboardMetric(key="total_runs", value=runs.total_runs, unit="runs"),
                DashboardMetric(key="completed_runs", value=runs.completed_runs, unit="runs"),
                DashboardMetric(key="failed_runs", value=runs.failed_runs, unit="runs"),
                DashboardMetric(key="cancelled_runs", value=runs.cancelled_runs, unit="runs"),
                DashboardMetric(key="running_runs", value=runs.running_runs, unit="runs"),
                DashboardMetric(key="success_rate", value=cls._percentage(numerator=runs.completed_runs, denominator=runs.total_runs), unit="percent"),
                DashboardMetric(key="average_latency", value=runs.average_latency_ms or 0.0, unit="milliseconds", metadata={"has_data": runs.average_latency_ms is not None}),
            ),
        )

    @classmethod
    def _llm_section(cls, snapshot: DashboardOverviewSnapshot) -> DashboardOverviewSection:
        llm = snapshot.llm
        return DashboardOverviewSection(
            key="llm",
            title="LLM Usage",
            metrics=(
                DashboardMetric(key="total_calls", value=llm.total_calls, unit="calls"),
                DashboardMetric(key="successful_calls", value=llm.successful_calls, unit="calls"),
                DashboardMetric(key="failed_calls", value=llm.failed_calls, unit="calls"),
                DashboardMetric(key="timeout_calls", value=llm.timeout_calls, unit="calls"),
                DashboardMetric(key="total_tokens", value=llm.total_tokens, unit="tokens"),
                DashboardMetric(key="input_tokens", value=llm.input_tokens, unit="tokens"),
                DashboardMetric(key="output_tokens", value=llm.output_tokens, unit="tokens"),
                DashboardMetric(key="cached_input_tokens", value=llm.cached_input_tokens, unit="tokens"),
                DashboardMetric(key="estimated_cost", value=float(llm.estimated_cost_usd), unit="usd"),
                DashboardMetric(key="average_latency", value=llm.average_latency_ms or 0.0, unit="milliseconds", metadata={"has_data": llm.average_latency_ms is not None}),
            ),
        )

    @classmethod
    def _retrieval_section(cls, snapshot: DashboardOverviewSnapshot) -> DashboardOverviewSection:
        retrieval = snapshot.retrieval
        return DashboardOverviewSection(
            key="retrieval",
            title="Knowledge Retrieval",
            metrics=(
                DashboardMetric(key="total_runs", value=retrieval.total_runs, unit="runs"),
                DashboardMetric(key="successful_runs", value=retrieval.successful_runs, unit="runs"),
                DashboardMetric(key="failed_runs", value=retrieval.failed_runs, unit="runs"),
                DashboardMetric(key="timeout_runs", value=retrieval.timeout_runs, unit="runs"),
                DashboardMetric(key="zero_result_runs", value=retrieval.zero_result_runs, unit="runs"),
                DashboardMetric(key="zero_result_rate", value=cls._percentage(numerator=retrieval.zero_result_runs, denominator=retrieval.total_runs), unit="percent"),
                DashboardMetric(key="reranked_runs", value=retrieval.reranked_runs, unit="runs"),
                DashboardMetric(key="average_latency", value=retrieval.average_latency_ms or 0.0, unit="milliseconds", metadata={"has_data": retrieval.average_latency_ms is not None}),
                DashboardMetric(key="average_selected_candidates", value=retrieval.average_selected_candidates or 0.0, unit="candidates", metadata={"has_data": retrieval.average_selected_candidates is not None}),
                DashboardMetric(key="average_context_tokens", value=retrieval.average_context_tokens or 0.0, unit="tokens", metadata={"has_data": retrieval.average_context_tokens is not None}),
            ),
        )

    @staticmethod
    def _escalation_section(snapshot: DashboardOverviewSnapshot) -> DashboardOverviewSection:
        escalations = snapshot.escalations
        return DashboardOverviewSection(
            key="escalations",
            title="Escalations",
            metrics=(
                DashboardMetric(key="created_escalations", value=escalations.created_escalations, unit="escalations"),
                DashboardMetric(key="open_escalations", value=escalations.open_escalations, unit="escalations"),
                DashboardMetric(key="in_review_escalations", value=escalations.in_review_escalations, unit="escalations"),
                DashboardMetric(key="resolved_escalations", value=escalations.resolved_escalations, unit="escalations"),
                DashboardMetric(key="dismissed_escalations", value=escalations.dismissed_escalations, unit="escalations"),
                DashboardMetric(key="high_priority_active", value=escalations.high_priority_active, unit="escalations"),
                DashboardMetric(key="urgent_priority_active", value=escalations.urgent_priority_active, unit="escalations"),
            ),
        )

    @staticmethod
    def _ticket_section(snapshot: DashboardOverviewSnapshot) -> DashboardOverviewSection:
        tickets = snapshot.tickets
        return DashboardOverviewSection(
            key="tickets",
            title="Support Tickets",
            metrics=(
                DashboardMetric(key="created_tickets", value=tickets.created_tickets, unit="tickets"),
                DashboardMetric(key="active_tickets", value=tickets.active_tickets, unit="tickets"),
                DashboardMetric(key="unassigned_active_tickets", value=tickets.unassigned_active_tickets, unit="tickets"),
                DashboardMetric(key="resolved_tickets", value=tickets.resolved_tickets, unit="tickets"),
                DashboardMetric(key="closed_tickets", value=tickets.closed_tickets, unit="tickets"),
                DashboardMetric(key="high_priority_active", value=tickets.high_priority_active, unit="tickets"),
                DashboardMetric(key="urgent_priority_active", value=tickets.urgent_priority_active, unit="tickets"),
                DashboardMetric(key="average_resolution_time", value=tickets.average_resolution_minutes or 0.0, unit="minutes", metadata={"has_data": tickets.average_resolution_minutes is not None}),
            ),
        )

    @staticmethod
    def _feedback_section(snapshot: DashboardOverviewSnapshot) -> DashboardOverviewSection:
        feedback = snapshot.feedback
        return DashboardOverviewSection(
            key="feedback",
            title="Customer Feedback",
            metrics=(
                DashboardMetric(key="submitted_feedback", value=feedback.submitted_feedback, unit="responses"),
                DashboardMetric(key="reviewed_feedback", value=feedback.reviewed_feedback, unit="responses"),
                DashboardMetric(key="pending_feedback", value=feedback.pending_feedback, unit="responses"),
                DashboardMetric(key="rated_feedback", value=feedback.rated_feedback, unit="responses"),
                DashboardMetric(key="average_rating", value=feedback.average_rating or 0.0, unit="rating", metadata={"has_data": feedback.average_rating is not None}),
                DashboardMetric(key="helpful_feedback", value=feedback.helpful_feedback, unit="responses"),
                DashboardMetric(key="unhelpful_feedback", value=feedback.unhelpful_feedback, unit="responses"),
                DashboardMetric(key="helpful_percentage", value=feedback.helpful_percentage or 0.0, unit="percent", metadata={"has_data": feedback.helpful_percentage is not None}),
            ),
        )

    @staticmethod
    def _knowledge_section(snapshot: DashboardOverviewSnapshot) -> DashboardOverviewSection:
        knowledge = snapshot.knowledge
        return DashboardOverviewSection(
            key="knowledge",
            title="Knowledge Management",
            metrics=(
                DashboardMetric(key="created_documents", value=knowledge.created_documents, unit="documents"),
                DashboardMetric(key="active_documents", value=knowledge.active_documents, unit="documents"),
                DashboardMetric(key="archived_documents", value=knowledge.archived_documents, unit="documents"),
                DashboardMetric(key="created_versions", value=knowledge.created_versions, unit="versions"),
                DashboardMetric(key="published_versions", value=knowledge.published_versions, unit="versions"),
                DashboardMetric(key="processing_versions", value=knowledge.processing_versions, unit="versions"),
                DashboardMetric(key="ready_versions", value=knowledge.ready_versions, unit="versions"),
                DashboardMetric(key="failed_versions", value=knowledge.failed_versions, unit="versions"),
            ),
        )

    @staticmethod
    def _percentage(*, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0

        return round((numerator / denominator) * 100.0, 2)