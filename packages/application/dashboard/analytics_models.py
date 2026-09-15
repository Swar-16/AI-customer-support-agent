# AI-customer-support-agent\packages\application\dashboard\analytics_models.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Final

from packages.application.dashboard.analytics_contract import AnalyticsWindow

UTC: Final = timezone.utc
ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")

def _require_nonnegative(*, field_name: str, value: int | Decimal) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must not be negative.")

def _require_rate(*, field_name: str, value: Decimal | None) -> None:
    if value is None:
        return

    if value < ZERO or value > ONE:
        raise ValueError(f"{field_name} must be between 0 and 1.")

def _normalize_utc(*, field_name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime.")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")

    return value.astimezone(UTC)

@dataclass(frozen=True, slots=True)
class AnalyticsMetadata:
    window: AnalyticsWindow
    generated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.window, AnalyticsWindow):
            raise TypeError("window must be an AnalyticsWindow.")

        object.__setattr__(self, "generated_at", _normalize_utc(field_name="generated_at", value=self.generated_at))

@dataclass(frozen=True, slots=True)
class CategoryCount:
    category: str
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.category, str):
            raise TypeError("category must be a string.")

        normalized = self.category.strip()
        if not normalized:
            raise ValueError("category must not be blank.")

        _require_nonnegative(field_name="count", value=self.count)
        object.__setattr__(self, "category", normalized)

@dataclass(frozen=True, slots=True)
class DurationSummary:
    sample_count: int
    average_ms: Decimal | None
    p50_ms: Decimal | None
    p95_ms: Decimal | None

    def __post_init__(self) -> None:
        _require_nonnegative(field_name="sample_count", value=self.sample_count)

        for field_name, value in (("average_ms", self.average_ms), ("p50_ms", self.p50_ms), ("p95_ms", self.p95_ms),):
            if value is not None:
                _require_nonnegative(field_name=field_name, value=value)

        if self.sample_count == 0:
            if any(value is not None for value in (self.average_ms, self.p50_ms, self.p95_ms,)):
                raise ValueError("Duration values must be None when sample_count is zero.")

@dataclass(frozen=True, slots=True)
class ConversationAnalyticsPoint:
    bucket_started_at: datetime
    conversations_created: int
    conversations_closed: int
    customer_messages: int
    assistant_messages: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "bucket_started_at", _normalize_utc(field_name="bucket_started_at", value=self.bucket_started_at))

        for field_name in ("conversations_created", "conversations_closed", "customer_messages", "assistant_messages",):
            _require_nonnegative(field_name=field_name, value=getattr(self, field_name))

@dataclass(frozen=True, slots=True)
class ConversationAnalyticsResult:
    metadata: AnalyticsMetadata
    total_conversations: int
    closed_conversations: int
    escalated_conversations: int
    customer_messages: int
    assistant_messages: int
    average_messages_per_conversation: Decimal | None
    escalation_rate: Decimal | None
    closure_duration: DurationSummary
    status_distribution: tuple[CategoryCount, ...]
    timeline: tuple[ConversationAnalyticsPoint, ...]

    def __post_init__(self) -> None:
        for field_name in ("total_conversations", "closed_conversations", "escalated_conversations", "customer_messages", "assistant_messages",):
            _require_nonnegative(field_name=field_name, value=getattr(self, field_name))

        if self.average_messages_per_conversation is not None:
            _require_nonnegative(field_name="average_messages_per_conversation", value=self.average_messages_per_conversation)

        _require_rate(field_name="escalation_rate", value=self.escalation_rate)

@dataclass(frozen=True, slots=True)
class AIAnalyticsPoint:
    bucket_started_at: datetime

    runs: int
    successful_runs: int
    failed_runs: int
    cancelled_runs: int

    llm_calls: int
    successful_llm_calls: int
    failed_llm_calls: int
    timed_out_llm_calls: int

    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    estimated_cost_usd: Decimal

    retrieval_runs: int
    failed_retrieval_runs: int
    timed_out_retrieval_runs: int
    zero_result_retrievals: int

    reranker_calls: int
    failed_reranker_calls: int
    timed_out_reranker_calls: int

    embedding_calls: int
    failed_embedding_calls: int
    timed_out_embedding_calls: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "bucket_started_at", _normalize_utc(field_name="bucket_started_at", value=self.bucket_started_at))

        for field_name in (
            "runs", "successful_runs", "failed_runs", "cancelled_runs", "llm_calls", "successful_llm_calls", "failed_llm_calls", "timed_out_llm_calls", "input_tokens",
            "output_tokens", "cached_input_tokens", "retrieval_runs", "failed_retrieval_runs", "timed_out_retrieval_runs", "zero_result_retrievals", "reranker_calls",
            "failed_reranker_calls", "timed_out_reranker_calls", "embedding_calls", "failed_embedding_calls", "timed_out_embedding_calls",
        ):
            _require_nonnegative(field_name=field_name, value=getattr(self, field_name))

        _require_nonnegative(field_name="estimated_cost_usd", value=self.estimated_cost_usd)

@dataclass(frozen=True, slots=True)
class AIAnalyticsResult:
    metadata: AnalyticsMetadata

    # AI pipeline runs
    total_runs: int
    running_runs: int
    successful_runs: int
    failed_runs: int
    cancelled_runs: int
    success_rate: Decimal | None
    run_duration: DurationSummary

    # LLM calls
    total_llm_calls: int
    started_llm_calls: int
    successful_llm_calls: int
    failed_llm_calls: int
    timed_out_llm_calls: int
    llm_call_duration: DurationSummary

    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    estimated_cost_usd: Decimal

    # Retrieval
    retrieval_runs: int
    started_retrieval_runs: int
    successful_retrieval_runs: int
    failed_retrieval_runs: int
    timed_out_retrieval_runs: int
    zero_result_retrievals: int
    zero_result_rate: Decimal | None
    average_retrieval_result_count: Decimal | None
    retrieval_duration: DurationSummary

    # Reranking
    reranker_calls: int
    started_reranker_calls: int
    successful_reranker_calls: int
    failed_reranker_calls: int
    timed_out_reranker_calls: int
    reranker_duration: DurationSummary

    # Embeddings
    embedding_calls: int
    started_embedding_calls: int
    successful_embedding_calls: int
    failed_embedding_calls: int
    timed_out_embedding_calls: int
    embedding_duration: DurationSummary

    # Structured categorical analytics
    intent_distribution: tuple[CategoryCount, ...]
    decision_distribution: tuple[CategoryCount, ...]
    decision_reason_distribution: tuple[CategoryCount, ...]

    # Stage-event based guardrail telemetry. This does not infer
    # business reason codes from metadata or text.
    guardrail_event_distribution: tuple[CategoryCount, ...]
    guardrail_error_code_distribution: tuple[CategoryCount, ...]

    # LLM provider telemetry
    llm_provider_distribution: tuple[CategoryCount, ...]
    llm_model_distribution: tuple[CategoryCount, ...]
    llm_error_code_distribution: tuple[CategoryCount, ...]

    retrieval_error_code_distribution: tuple[CategoryCount, ...]
    reranker_provider_distribution: tuple[CategoryCount, ...]
    reranker_model_distribution: tuple[CategoryCount, ...]
    reranker_error_code_distribution: tuple[CategoryCount, ...]
    embedding_provider_distribution: tuple[CategoryCount, ...]
    embedding_model_distribution: tuple[CategoryCount, ...]
    embedding_error_code_distribution: tuple[CategoryCount, ...]

    timeline: tuple[AIAnalyticsPoint, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, AnalyticsMetadata):
            raise TypeError("metadata must be an AnalyticsMetadata.")

        for field_name in (
            "total_runs", "running_runs", "successful_runs", "failed_runs", "cancelled_runs", "total_llm_calls", "started_llm_calls", "successful_llm_calls", 
            "failed_llm_calls", "timed_out_llm_calls", "input_tokens", "output_tokens", "cached_input_tokens", "retrieval_runs", "started_retrieval_runs", 
            "successful_retrieval_runs", "failed_retrieval_runs", "timed_out_retrieval_runs", "zero_result_retrievals", "reranker_calls", "started_reranker_calls",
            "successful_reranker_calls", "failed_reranker_calls", "timed_out_reranker_calls", "embedding_calls", "started_embedding_calls", 
            "successful_embedding_calls", "failed_embedding_calls", "timed_out_embedding_calls",
        ):
            _require_nonnegative(field_name=field_name, value=getattr(self, field_name))

        _require_nonnegative(field_name="estimated_cost_usd", value=self.estimated_cost_usd)

        for field_name in ("run_duration", "llm_call_duration", "retrieval_duration", "reranker_duration", "embedding_duration",):
            if not isinstance(getattr(self, field_name), DurationSummary):
                raise TypeError(f"{field_name} must be a DurationSummary.")

        _require_rate(field_name="success_rate", value=self.success_rate)
        _require_rate(field_name="zero_result_rate", value=self.zero_result_rate)

        if self.average_retrieval_result_count is not None:
            _require_nonnegative(field_name="average_retrieval_result_count", value=self.average_retrieval_result_count)

@dataclass(frozen=True, slots=True)
class SupportAnalyticsPoint:
    bucket_started_at: datetime
    tickets_created: int
    tickets_resolved: int
    tickets_closed: int
    escalations_created: int
    escalations_resolved: int
    feedback_submitted: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "bucket_started_at", _normalize_utc(field_name="bucket_started_at", value=self.bucket_started_at))

        for field_name in (
            "tickets_created", "tickets_resolved", "tickets_closed", "escalations_created", "escalations_resolved", "feedback_submitted",
        ):
            _require_nonnegative(field_name=field_name, value=getattr(self, field_name))

@dataclass(frozen=True, slots=True)
class SupportAnalyticsResult:
    metadata: AnalyticsMetadata
    snapshot_measured_at: datetime
    tickets_created: int
    tickets_resolved: int
    tickets_closed: int
    current_ticket_backlog: int
    escalations_created: int
    escalations_resolved: int
    feedback_submitted: int
    average_feedback_rating: Decimal | None
    ticket_resolution_duration: DurationSummary
    escalation_resolution_duration: DurationSummary
    ticket_status_distribution: tuple[CategoryCount, ...]
    ticket_priority_distribution: tuple[CategoryCount, ...]
    ticket_category_distribution: tuple[CategoryCount, ...]
    escalation_status_distribution: tuple[CategoryCount, ...]
    feedback_rating_distribution: tuple[CategoryCount, ...]
    feedback_status_distribution: tuple[CategoryCount, ...]
    timeline: tuple[SupportAnalyticsPoint, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_measured_at", _normalize_utc(field_name="snapshot_measured_at", value=self.snapshot_measured_at))
        
        for field_name in (
            "tickets_created", "tickets_resolved", "tickets_closed", "current_ticket_backlog",
            "escalations_created", "escalations_resolved", "feedback_submitted",
        ):
            _require_nonnegative(field_name=field_name, value=getattr(self, field_name))

        if self.average_feedback_rating is not None:
            _require_nonnegative(field_name="average_feedback_rating", value=self.average_feedback_rating)

@dataclass(frozen=True, slots=True)
class KnowledgeHealthPoint:
    bucket_started_at: datetime
    versions_created: int
    processing_completed: int
    processing_failed: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "bucket_started_at", _normalize_utc(field_name="bucket_started_at", value=self.bucket_started_at))

        for field_name in ("versions_created", "processing_completed", "processing_failed",):
            _require_nonnegative(field_name=field_name, value=getattr(self, field_name),)

@dataclass(frozen=True, slots=True)
class KnowledgeHealthResult:
    metadata: AnalyticsMetadata
    snapshot_measured_at: datetime

    total_documents: int
    total_versions: int
    total_chunks: int
    total_embeddings: int

    versions_without_chunks: int
    versions_missing_embeddings: int
    processing_backlog: int
    embedding_coverage_rate: Decimal | None

    processing_duration: DurationSummary

    document_status_distribution: tuple[CategoryCount, ...]
    document_content_type_distribution: tuple[CategoryCount, ...]
    document_visibility_distribution: tuple[CategoryCount, ...]

    version_status_distribution: tuple[CategoryCount, ...]
    ingestion_status_distribution: tuple[CategoryCount, ...]
    failure_code_distribution: tuple[CategoryCount, ...]

    timeline: tuple[KnowledgeHealthPoint, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_measured_at", _normalize_utc(field_name="snapshot_measured_at", value=self.snapshot_measured_at))
        
        for field_name in (
            "total_documents", "total_versions", "total_chunks", "total_embeddings", 
            "versions_without_chunks", "versions_missing_embeddings", "processing_backlog",
        ):
            _require_nonnegative(field_name=field_name, value=getattr(self, field_name))

        _require_rate(field_name="embedding_coverage_rate", value=self.embedding_coverage_rate)