# AI-customer-support-agent\packages\database\repositories\dashboard\sqlalchemy_analytics_repository.py
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Final
from sqlalchemy import distinct, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from packages.application.dashboard.analytics_contract import AnalyticsBucket, AnalyticsWindow
from packages.application.dashboard.analytics_models import AIAnalyticsResult, AnalyticsMetadata, CategoryCount, SupportAnalyticsPoint
from packages.application.dashboard.analytics_models import ConversationAnalyticsResult, DurationSummary, KnowledgeHealthResult
from packages.application.dashboard.analytics_models import AIAnalyticsPoint, ConversationAnalyticsPoint, SupportAnalyticsResult
from packages.application.dashboard.analytics_models import KnowledgeHealthPoint
from packages.application.dashboard.analytics_repository import DashboardAnalyticsRepository
from packages.database.models.support.conversation import ConversationModel
from packages.database.models.support.escalation import EscalationModel
from packages.database.models.support.message import MessageModel
from packages.database.models.ai.decision import AIDecisionModel
from packages.database.models.ai.embedding_call import EmbeddingCallModel
from packages.database.models.ai.intent_prediction import IntentPredictionModel
from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.models.ai.reranker_call import RerankerCallModel
from packages.database.models.ai.retrieval_run import RetrievalRunModel
from packages.database.models.ai.run import AIRunModel
from packages.database.models.ai.stage_event import AIStageEventModel
from packages.database.models.support.feedback import FeedbackModel
from packages.database.models.support.ticket import TicketModel
from packages.database.models.knowledge.chunk import KnowledgeChunkModel
from packages.database.models.knowledge.chunk_embedding import KnowledgeChunkEmbeddingModel
from packages.database.models.knowledge.document import KnowledgeDocumentModel
from packages.database.models.knowledge.document_version import KnowledgeDocumentVersionModel

UTC: Final = timezone.utc
_BUCKET_INTERVALS: Final[dict[AnalyticsBucket, str]] = {
    AnalyticsBucket.HOUR: "1 hour",
    AnalyticsBucket.DAY: "1 day",
    AnalyticsBucket.WEEK: "1 week",
}

class SQLAlchemyDashboardAnalyticsRepository(DashboardAnalyticsRepository):
    """PostgreSQL-backed dashboard aggregate repository."""
    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable.")

        self._session_factory = session_factory

    def get_conversation_analytics(self, *, window: AnalyticsWindow) -> ConversationAnalyticsResult:
        if not isinstance(window, AnalyticsWindow):
            raise TypeError("window must be an AnalyticsWindow.")

        generated_at = datetime.now(UTC)

        with self._session_factory() as session:
            total_conversations = self._count_conversations_created(session=session, window=window)
            closed_conversations = self._count_conversations_closed(session=session, window=window)
            escalated_conversations = self._count_escalated_conversations(session=session, window=window)

            (customer_messages, assistant_messages, conversations_with_messages,) = self._get_message_totals(session=session, window=window)
            status_distribution = self._get_conversation_status_distribution(session=session, window=window)
            closure_duration = self._get_closure_duration(session=session, window=window)
            timeline = self._get_conversation_timeline(session=session, window=window)

        total_messages = customer_messages + assistant_messages
        average_messages = (Decimal(total_messages) / Decimal(conversations_with_messages)) if conversations_with_messages > 0 else None
        escalation_rate = (Decimal(escalated_conversations) / Decimal(total_conversations)) if total_conversations > 0 else None

        return ConversationAnalyticsResult(
            metadata=AnalyticsMetadata(window=window, generated_at=generated_at),
            total_conversations=total_conversations,
            closed_conversations=closed_conversations,
            escalated_conversations=escalated_conversations,
            customer_messages=customer_messages,
            assistant_messages=assistant_messages,
            average_messages_per_conversation=average_messages,
            escalation_rate=escalation_rate,
            closure_duration=closure_duration,
            status_distribution=status_distribution,
            timeline=timeline,
        )

    def get_ai_analytics(self, *, window: AnalyticsWindow) -> AIAnalyticsResult:
        if not isinstance(window, AnalyticsWindow):
            raise TypeError("window must be an AnalyticsWindow.")

        generated_at = datetime.now(UTC)

        with self._session_factory() as session:
            run_totals = self._get_ai_run_totals(session=session, window=window)
            llm_totals = self._get_llm_totals(session=session, window=window)
            retrieval_totals = self._get_retrieval_totals(session=session, window=window)
            reranker_totals = self._get_reranker_totals(session=session, window=window)
            embedding_totals = self._get_embedding_totals(session=session, window=window)

            run_duration = self._get_duration_summary(
                session=session,
                duration_column=AIRunModel.total_latency_ms,
                timestamp_column=AIRunModel.started_at,
                window=window,
            )
            llm_duration = self._get_duration_summary(
                session=session,
                duration_column=LLMCallModel.latency_ms,
                timestamp_column=LLMCallModel.started_at,
                window=window,
            )
            retrieval_duration = self._get_duration_summary(
                session=session,
                duration_column=RetrievalRunModel.total_latency_ms,
                timestamp_column=RetrievalRunModel.started_at,
                window=window,
            )
            reranker_duration = self._get_duration_summary(
                session=session,
                duration_column=RerankerCallModel.latency_ms,
                timestamp_column=RerankerCallModel.started_at,
                window=window,
            )
            embedding_duration = self._get_duration_summary(
                session=session,
                duration_column=EmbeddingCallModel.latency_ms,
                timestamp_column=EmbeddingCallModel.started_at,
                window=window,
            )

            intent_distribution = self._get_category_distribution(
                session=session,
                category_column=IntentPredictionModel.intent,
                timestamp_column=IntentPredictionModel.created_at,
                window=window,
            )
            decision_distribution = self._get_category_distribution(
                session=session,
                category_column=AIDecisionModel.decision_type,
                timestamp_column=AIDecisionModel.created_at,
                window=window,
            )
            decision_reason_distribution = self._get_category_distribution(
                session=session,
                category_column=AIDecisionModel.reason_code,
                timestamp_column=AIDecisionModel.created_at,
                window=window,
                exclude_null=True,
            )

            guardrail_event_distribution = self._get_category_distribution(
                session=session,
                category_column=AIStageEventModel.event_type,
                timestamp_column=AIStageEventModel.occurred_at,
                window=window,
                additional_conditions=(AIStageEventModel.stage == "guardrails_completed",),
            )
            guardrail_error_distribution = self._get_category_distribution(
                session=session,
                category_column=AIStageEventModel.error_code,
                timestamp_column=AIStageEventModel.occurred_at,
                window=window,
                exclude_null=True,
                additional_conditions=(AIStageEventModel.stage == "guardrails_completed",),
            )

            llm_provider_distribution = self._get_category_distribution(
                session=session,
                category_column=LLMCallModel.provider,
                timestamp_column=LLMCallModel.started_at,
                window=window,
            )
            llm_model_distribution = self._get_category_distribution(
                session=session,
                category_column=LLMCallModel.model,
                timestamp_column=LLMCallModel.started_at,
                window=window,
            )
            llm_error_distribution = self._get_category_distribution(
                session=session,
                category_column=LLMCallModel.error_code,
                timestamp_column=LLMCallModel.started_at,
                window=window,
                exclude_null=True,
            )

            retrieval_error_distribution = self._get_category_distribution(
                session=session,
                category_column=RetrievalRunModel.error_code,
                timestamp_column=RetrievalRunModel.started_at,
                window=window,
                exclude_null=True,
            )

            reranker_provider_distribution = self._get_category_distribution(
                session=session,
                category_column=RerankerCallModel.provider,
                timestamp_column=RerankerCallModel.started_at,
                window=window,
            )
            reranker_model_distribution = self._get_category_distribution(
                session=session,
                category_column=RerankerCallModel.model,
                timestamp_column=RerankerCallModel.started_at,
                window=window,
                exclude_null=True,
            )
            reranker_error_distribution = self._get_category_distribution(
                session=session,
                category_column=RerankerCallModel.error_code,
                timestamp_column=RerankerCallModel.started_at,
                window=window,
                exclude_null=True,
            )

            embedding_provider_distribution = self._get_category_distribution(
                session=session,
                category_column=EmbeddingCallModel.provider,
                timestamp_column=EmbeddingCallModel.started_at,
                window=window,
            )
            embedding_model_distribution = self._get_category_distribution(
                session=session,
                category_column=EmbeddingCallModel.model,
                timestamp_column=EmbeddingCallModel.started_at,
                window=window,
            )
            embedding_error_distribution = self._get_category_distribution(
                session=session,
                category_column=EmbeddingCallModel.error_code,
                timestamp_column=EmbeddingCallModel.started_at,
                window=window,
                exclude_null=True,
            )

            timeline = self._get_ai_timeline(session=session, window=window)

        terminal_runs = (run_totals["successful"] + run_totals["failed"] + run_totals["cancelled"])
        success_rate = (Decimal(run_totals["successful"]) / Decimal(terminal_runs)) if terminal_runs > 0 else None
        successful_retrievals = retrieval_totals["successful"]
        zero_result_rate = (Decimal(retrieval_totals["zero_result"]) / Decimal(successful_retrievals)) if successful_retrievals > 0 else None

        return AIAnalyticsResult(
            metadata=AnalyticsMetadata(window=window, generated_at=generated_at),
            total_runs=run_totals["total"],
            running_runs=run_totals["running"],
            successful_runs=run_totals["successful"],
            failed_runs=run_totals["failed"],
            cancelled_runs=run_totals["cancelled"],
            success_rate=success_rate,
            run_duration=run_duration,
            total_llm_calls=llm_totals["total"],
            started_llm_calls=llm_totals["started"],
            successful_llm_calls=llm_totals["successful"],
            failed_llm_calls=llm_totals["failed"],
            timed_out_llm_calls=llm_totals["timeout"],
            llm_call_duration=llm_duration,
            input_tokens=llm_totals["input_tokens"],
            output_tokens=llm_totals["output_tokens"],
            cached_input_tokens=llm_totals["cached_input_tokens"],
            estimated_cost_usd=llm_totals["cost"],
            retrieval_runs=retrieval_totals["total"],
            started_retrieval_runs=retrieval_totals["started"],
            successful_retrieval_runs=retrieval_totals["successful"],
            failed_retrieval_runs=retrieval_totals["failed"],
            timed_out_retrieval_runs=retrieval_totals["timeout"],
            zero_result_retrievals=retrieval_totals["zero_result"],
            zero_result_rate=zero_result_rate,
            average_retrieval_result_count=retrieval_totals["average_result_count"],
            retrieval_duration=retrieval_duration,
            reranker_calls=reranker_totals["total"],
            started_reranker_calls=reranker_totals["started"],
            successful_reranker_calls=reranker_totals["successful"],
            failed_reranker_calls=reranker_totals["failed"],
            timed_out_reranker_calls=reranker_totals["timeout"],
            reranker_duration=reranker_duration,
            embedding_calls=embedding_totals["total"],
            started_embedding_calls=embedding_totals["started"],
            successful_embedding_calls=embedding_totals["successful"],
            failed_embedding_calls=embedding_totals["failed"],
            timed_out_embedding_calls=embedding_totals["timeout"],
            embedding_duration=embedding_duration,
            intent_distribution=intent_distribution,
            decision_distribution=decision_distribution,
            decision_reason_distribution=decision_reason_distribution,
            guardrail_event_distribution=guardrail_event_distribution,
            guardrail_error_code_distribution=guardrail_error_distribution,
            llm_provider_distribution=llm_provider_distribution,
            llm_model_distribution=llm_model_distribution,
            llm_error_code_distribution=llm_error_distribution,
            retrieval_error_code_distribution=retrieval_error_distribution,
            reranker_provider_distribution=reranker_provider_distribution,
            reranker_model_distribution=reranker_model_distribution,
            reranker_error_code_distribution=reranker_error_distribution,
            embedding_provider_distribution=embedding_provider_distribution,
            embedding_model_distribution=embedding_model_distribution,
            embedding_error_code_distribution=embedding_error_distribution,
            timeline=timeline,
        )

    def get_support_analytics(self, *, window: AnalyticsWindow) -> SupportAnalyticsResult:
        if not isinstance(window, AnalyticsWindow):
            raise TypeError("window must be an AnalyticsWindow.")

        snapshot_measured_at = datetime.now(UTC)
        with self._session_factory() as session:
            ticket_totals = self._get_ticket_totals(session=session, window=window)
            escalation_totals = self._get_escalation_totals(session=session, window=window)
            feedback_totals = self._get_feedback_totals(session=session, window=window)
            current_ticket_backlog = self._count_current_ticket_backlog(session=session)
            ticket_resolution_duration = self._get_resolution_duration(
                session=session,
                created_column=TicketModel.created_at,
                resolved_column=TicketModel.resolved_at,
                window=window,
            )
            escalation_resolution_duration = self._get_resolution_duration(
                session=session,
                created_column=EscalationModel.created_at,
                resolved_column=EscalationModel.resolved_at,
                window=window,
            )

            # These are current-state snapshots, not historical distributions.
            ticket_status_distribution = self._get_current_category_distribution(session=session, category_column=TicketModel.status)
            ticket_priority_distribution = self._get_current_category_distribution(session=session, category_column=TicketModel.priority)
            ticket_category_distribution = self._get_current_category_distribution(session=session, category_column=TicketModel.category)
            escalation_status_distribution = self._get_current_category_distribution(session=session, category_column=EscalationModel.status)
            feedback_status_distribution = self._get_current_category_distribution(session=session, category_column=FeedbackModel.status)

            # Ratings are based on feedback submitted inside the requested window.
            feedback_rating_distribution = self._get_category_distribution(
                session=session,
                category_column=FeedbackModel.rating,
                timestamp_column=FeedbackModel.created_at,
                window=window,
            )

            timeline = self._get_support_timeline(session=session, window=window)

        return SupportAnalyticsResult(
            metadata=AnalyticsMetadata(window=window, generated_at=snapshot_measured_at),
            snapshot_measured_at=snapshot_measured_at,
            tickets_created=ticket_totals["created"],
            tickets_resolved=ticket_totals["resolved"],
            tickets_closed=ticket_totals["closed"],
            current_ticket_backlog=current_ticket_backlog,
            escalations_created=escalation_totals["created"],
            escalations_resolved=escalation_totals["resolved"],
            feedback_submitted=feedback_totals["submitted"],
            average_feedback_rating=feedback_totals["average_rating"],
            ticket_resolution_duration=ticket_resolution_duration,
            escalation_resolution_duration=escalation_resolution_duration,
            ticket_status_distribution=ticket_status_distribution,
            ticket_priority_distribution=ticket_priority_distribution,
            ticket_category_distribution=ticket_category_distribution,
            escalation_status_distribution=escalation_status_distribution,
            feedback_rating_distribution=feedback_rating_distribution,
            feedback_status_distribution=feedback_status_distribution,
            timeline=timeline,
        )

    def get_knowledge_health(self, *, window: AnalyticsWindow) -> KnowledgeHealthResult:
        if not isinstance(window, AnalyticsWindow):
            raise TypeError("window must be an AnalyticsWindow.")

        snapshot_measured_at = datetime.now(UTC)
        with self._session_factory() as session:
            inventory = self._get_knowledge_inventory(session=session)
            document_status_distribution = self._get_current_category_distribution(session=session, category_column=KnowledgeDocumentModel.status)
            document_content_type_distribution = self._get_current_category_distribution(session=session, category_column=KnowledgeDocumentModel.content_type)
            document_visibility_distribution = self._get_current_category_distribution(session=session, category_column=KnowledgeDocumentModel.visibility)
            version_status_distribution = self._get_current_category_distribution(session=session, category_column=KnowledgeDocumentVersionModel.status)
            ingestion_status_distribution = self._get_current_category_distribution(session=session, category_column=KnowledgeDocumentVersionModel.ingestion_status)

            # Failure codes describe failures completed inside the window.
            failure_code_distribution = self._get_category_distribution(
                session=session,
                category_column=KnowledgeDocumentVersionModel.failure_code,
                timestamp_column=KnowledgeDocumentVersionModel.processing_completed_at,
                window=window,
                exclude_null=True,
                additional_conditions=(KnowledgeDocumentVersionModel.ingestion_status == "failed",),
            )

            processing_duration = self._get_knowledge_processing_duration(session=session, window=window)
            timeline = self._get_knowledge_health_timeline(session=session, window=window)

        total_chunks = inventory["total_chunks"]
        embedded_chunks = inventory["embedded_chunks"]
        embedding_coverage_rate = (Decimal(embedded_chunks) / Decimal(total_chunks)) if total_chunks > 0 else None

        return KnowledgeHealthResult(
            metadata=AnalyticsMetadata(window=window, generated_at=snapshot_measured_at),
            snapshot_measured_at=snapshot_measured_at,
            total_documents=inventory["total_documents"],
            total_versions=inventory["total_versions"],
            total_chunks=total_chunks,
            total_embeddings=inventory["total_embeddings"],
            versions_without_chunks=inventory["versions_without_chunks"],
            versions_missing_embeddings=inventory["versions_missing_embeddings"],
            processing_backlog=inventory["processing_backlog"],
            embedding_coverage_rate=embedding_coverage_rate,
            processing_duration=processing_duration,
            document_status_distribution=document_status_distribution,
            document_content_type_distribution=document_content_type_distribution,
            document_visibility_distribution=document_visibility_distribution,
            version_status_distribution=version_status_distribution,
            ingestion_status_distribution=ingestion_status_distribution,
            failure_code_distribution=failure_code_distribution,
            timeline=timeline,
        )


    @staticmethod
    def _count_conversations_created(*, session: Session, window: AnalyticsWindow) -> int:
        value = session.scalar(select(func.count(ConversationModel.id))
                               .where(ConversationModel.created_at >= window.started_at,
                                      ConversationModel.created_at < window.ended_at)
        )

        return int(value or 0)

    @staticmethod
    def _count_conversations_closed(*, session: Session, window: AnalyticsWindow) -> int:
        value = session.scalar(select(func.count(ConversationModel.id))
                               .where(ConversationModel.closed_at.is_not(None), 
                                      ConversationModel.closed_at >= window.started_at,
                                      ConversationModel.closed_at < window.ended_at)
        )

        return int(value or 0)

    @staticmethod
    def _count_escalated_conversations(*, session: Session, window: AnalyticsWindow) -> int:
        """
        Count the created-conversation cohort that has ever escalated.

        Using the same creation cohort keeps escalation_rate bounded between zero and one.
        """
        value = session.scalar(select(func.count(distinct(EscalationModel.conversation_id)))
                               .join(ConversationModel, ConversationModel.id == EscalationModel.conversation_id)
                               .where(ConversationModel.created_at >= window.started_at,
                                      ConversationModel.created_at < window.ended_at)
        )

        return int(value or 0)

    @staticmethod
    def _get_message_totals(*, session: Session, window: AnalyticsWindow) -> tuple[int, int, int]:
        row = session.execute(select(func.count(MessageModel.id).filter(MessageModel.role == "customer").label("customer_messages"),
                                     func.count(MessageModel.id).filter(MessageModel.role == "assistant").label("assistant_messages"),
                                     func.count(distinct(MessageModel.conversation_id)).label("conversations_with_messages"))
                              .where(MessageModel.created_at >= window.started_at,
                                     MessageModel.created_at < window.ended_at)
        ).one()

        return (
            int(row.customer_messages or 0),
            int(row.assistant_messages or 0),
            int(row.conversations_with_messages or 0),
        )

    @staticmethod
    def _get_conversation_status_distribution(*, session: Session, window: AnalyticsWindow) -> tuple[CategoryCount, ...]:
        rows = session.execute(select(ConversationModel.status,
                                      func.count(ConversationModel.id).label("count"))
                               .where(ConversationModel.created_at >= window.started_at,
                                      ConversationModel.created_at < window.ended_at)
                               .group_by(ConversationModel.status)
                               .order_by(func.count(ConversationModel.id).desc(),
                                         ConversationModel.status.asc())
        ).all()

        return tuple(CategoryCount(category=str(row.status), count=int(row.count)) for row in rows)

    @staticmethod
    def _get_closure_duration(*, session: Session, window: AnalyticsWindow) -> DurationSummary:
        duration_ms = (func.extract("epoch", ConversationModel.closed_at - ConversationModel.created_at) * 1000)
        row = session.execute(select(func.count(ConversationModel.id).label("sample_count"),
                                     func.avg(duration_ms).label("average_ms"),
                                     func.percentile_cont(0.50).within_group(duration_ms).label("p50_ms"),
                                     func.percentile_cont(0.95).within_group(duration_ms).label("p95_ms"))
                              .where(ConversationModel.closed_at.is_not(None),
                                     ConversationModel.closed_at >= window.started_at,
                                     ConversationModel.closed_at < window.ended_at,
                                     ConversationModel.closed_at >= ConversationModel.created_at)
        ).one()

        sample_count = int(row.sample_count or 0)

        return DurationSummary(
            sample_count=sample_count,
            average_ms=_decimal_or_none(row.average_ms),
            p50_ms=_decimal_or_none(row.p50_ms),
            p95_ms=_decimal_or_none(row.p95_ms),
        )

    @staticmethod
    def _get_conversation_timeline(*, session: Session, window: AnalyticsWindow) -> tuple[ConversationAnalyticsPoint, ...]:
        if not isinstance(window, AnalyticsWindow):
            raise TypeError("window must be an AnalyticsWindow.")

        try:
            bucket_interval = _BUCKET_INTERVALS[window.bucket]
            
        except KeyError as exc:
            raise ValueError("Unsupported analytics bucket.") from exc

        statement = text(
            """
            WITH buckets AS (
                SELECT generate_series(
                    date_trunc(CAST(:bucket_unit AS text), CAST(:started_at AS timestamptz), 'UTC'),
                    date_trunc(CAST(:bucket_unit AS text), CAST(:ended_at AS timestamptz) - interval '1 microsecond', 'UTC'),
                    CAST(:bucket_interval AS interval)
                ) AS bucket_started_at
            ),
            created_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), created_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS count
                FROM support.conversations
                WHERE created_at >= :started_at
                AND created_at < :ended_at
                GROUP BY 1
            ),
            closed_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), closed_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS count
                FROM support.conversations
                WHERE closed_at IS NOT NULL
                AND closed_at >= :started_at
                AND closed_at < :ended_at
                GROUP BY 1
            ),
            message_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), created_at, 'UTC') AS bucket_started_at,
                    COUNT(*) FILTER (WHERE role = 'customer') AS customer_messages,
                    COUNT(*) FILTER (WHERE role = 'assistant') AS assistant_messages
                FROM support.messages
                WHERE created_at >= :started_at
                AND created_at < :ended_at
                GROUP BY 1
            )
            SELECT
                buckets.bucket_started_at,
                COALESCE(created_counts.count, 0) AS conversations_created,
                COALESCE(closed_counts.count, 0) AS conversations_closed,
                COALESCE(message_counts.customer_messages, 0) AS customer_messages,
                COALESCE(message_counts.assistant_messages, 0) AS assistant_messages
            FROM buckets
            LEFT JOIN created_counts
                USING (bucket_started_at)
            LEFT JOIN closed_counts
                USING (bucket_started_at)
            LEFT JOIN message_counts
                USING (bucket_started_at)
            ORDER BY buckets.bucket_started_at ASC
            """
        )

        rows = session.execute(statement,
            {
                "bucket_unit": window.bucket.value,
                "bucket_interval": bucket_interval,
                "started_at": window.started_at,
                "ended_at": window.ended_at,
            },
        ).mappings()

        return tuple(ConversationAnalyticsPoint(
            bucket_started_at=row["bucket_started_at"],
            conversations_created=int(row["conversations_created"]),
            conversations_closed=int(row["conversations_closed"]),
            customer_messages=int(row["customer_messages"]),
            assistant_messages=int(row["assistant_messages"]),
        ) for row in rows)
        
    @staticmethod
    def _get_ai_run_totals(*, session: Session, window: AnalyticsWindow) -> dict[str, int]:
        row = session.execute(select(func.count(AIRunModel.id).label("total"),
                                     func.count(AIRunModel.id).filter(AIRunModel.status == "running").label("running"),
                                     func.count(AIRunModel.id).filter(AIRunModel.status == "completed").label("successful"),
                                     func.count(AIRunModel.id).filter(AIRunModel.status == "failed").label("failed"),
                                     func.count(AIRunModel.id).filter(AIRunModel.status == "cancelled").label("cancelled"))
                              .where(AIRunModel.started_at >= window.started_at,
                                     AIRunModel.started_at < window.ended_at)
        ).one()

        return {
            "total": int(row.total or 0),
            "running": int(row.running or 0),
            "successful": int(row.successful or 0),
            "failed": int(row.failed or 0),
            "cancelled": int(row.cancelled or 0),
        }

    @staticmethod
    def _get_llm_totals(*, session: Session, window: AnalyticsWindow) -> dict[str, Any]:
        row = session.execute(select(func.count(LLMCallModel.id).label("total"),
                                     func.count(LLMCallModel.id).filter(LLMCallModel.status == "started").label("started"),
                                     func.count(LLMCallModel.id).filter(LLMCallModel.status == "success").label("successful"),
                                     func.count(LLMCallModel.id).filter(LLMCallModel.status == "failed").label("failed"),
                                     func.count(LLMCallModel.id).filter(LLMCallModel.status == "timeout").label("timeout"),
                                     func.coalesce(func.sum(LLMCallModel.input_tokens), 0).label("input_tokens"),
                                     func.coalesce(func.sum(LLMCallModel.output_tokens), 0).label("output_tokens"),
                                     func.coalesce(func.sum(LLMCallModel.cached_input_tokens), 0).label("cached_input_tokens"),
                                     func.coalesce(func.sum(LLMCallModel.estimated_cost_usd), 0).label("cost"))
                              .where(LLMCallModel.started_at >= window.started_at,
                                     LLMCallModel.started_at < window.ended_at)
        ).one()

        return {
            "total": int(row.total or 0),
            "started": int(row.started or 0),
            "successful": int(row.successful or 0),
            "failed": int(row.failed or 0),
            "timeout": int(row.timeout or 0),
            "input_tokens": int(row.input_tokens or 0),
            "output_tokens": int(row.output_tokens or 0),
            "cached_input_tokens": int(row.cached_input_tokens or 0),
            "cost": _decimal_or_zero(row.cost),
        }

    @staticmethod
    def _get_retrieval_totals(*, session: Session, window: AnalyticsWindow) -> dict[str, Any]:
        row = session.execute(select(func.count(RetrievalRunModel.id).label("total"),
                                     func.count(RetrievalRunModel.id).filter(RetrievalRunModel.status == "started").label("started"),
                                     func.count(RetrievalRunModel.id).filter(RetrievalRunModel.status == "success").label("successful"),
                                     func.count(RetrievalRunModel.id).filter(RetrievalRunModel.status == "failed").label("failed"),
                                     func.count(RetrievalRunModel.id).filter(RetrievalRunModel.status == "timeout").label("timeout"),
                                     func.count(RetrievalRunModel.id).filter(RetrievalRunModel.status == "success",
                                                                             RetrievalRunModel.zero_result.is_(True)).label("zero_result"),
                                     func.avg(RetrievalRunModel.selected_candidate_count).filter(RetrievalRunModel.status == "success").label("average_result_count"))
                              .where(RetrievalRunModel.started_at >= window.started_at,
                                     RetrievalRunModel.started_at < window.ended_at)
        ).one()

        return {
            "total": int(row.total or 0),
            "started": int(row.started or 0),
            "successful": int(row.successful or 0),
            "failed": int(row.failed or 0),
            "timeout": int(row.timeout or 0),
            "zero_result": int(row.zero_result or 0),
            "average_result_count": _decimal_or_none(row.average_result_count),
        }

    @staticmethod
    def _get_reranker_totals(*, session: Session, window: AnalyticsWindow) -> dict[str, int]:
        row = session.execute(select(func.count(RerankerCallModel.id).label("total"),
                                     func.count(RerankerCallModel.id).filter(RerankerCallModel.status == "started").label("started"),
                                     func.count(RerankerCallModel.id).filter(RerankerCallModel.status == "success").label("successful"),
                                     func.count(RerankerCallModel.id).filter(RerankerCallModel.status == "failed").label("failed"),
                                     func.count(RerankerCallModel.id).filter(RerankerCallModel.status == "timeout").label("timeout"))
                              .where(RerankerCallModel.started_at >= window.started_at,
                                     RerankerCallModel.started_at < window.ended_at)
        ).one()

        return {
            "total": int(row.total or 0),
            "started": int(row.started or 0),
            "successful": int(row.successful or 0),
            "failed": int(row.failed or 0),
            "timeout": int(row.timeout or 0),
        }

    @staticmethod
    def _get_embedding_totals(*, session: Session, window: AnalyticsWindow) -> dict[str, int]:
        row = session.execute(select(func.count(EmbeddingCallModel.id).label("total"),
                                     func.count(EmbeddingCallModel.id).filter(EmbeddingCallModel.status == "started").label("started"),
                                     func.count(EmbeddingCallModel.id).filter(EmbeddingCallModel.status == "success").label("successful"),
                                     func.count(EmbeddingCallModel.id).filter(EmbeddingCallModel.status == "failed").label("failed"),
                                     func.count(EmbeddingCallModel.id).filter(EmbeddingCallModel.status == "timeout").label("timeout"))
                              .where(EmbeddingCallModel.started_at >= window.started_at,
                                     EmbeddingCallModel.started_at < window.ended_at)
        ).one()

        return {
            "total": int(row.total or 0),
            "started": int(row.started or 0),
            "successful": int(row.successful or 0),
            "failed": int(row.failed or 0),
            "timeout": int(row.timeout or 0),
        }

    @staticmethod
    def _get_duration_summary(*, session: Session, duration_column: Any, timestamp_column: Any, window: AnalyticsWindow) -> DurationSummary:
        row = session.execute(select(func.count(duration_column).label("sample_count"),
                                     func.avg(duration_column).label("average_ms"),
                                     func.percentile_cont(0.50).within_group(duration_column).label("p50_ms"),
                                     func.percentile_cont(0.95).within_group(duration_column).label("p95_ms"))
                              .where(timestamp_column >= window.started_at,
                                     timestamp_column < window.ended_at,
                                     duration_column.is_not(None),
                                     duration_column >= 0)
        ).one()

        sample_count = int(row.sample_count or 0)

        return DurationSummary(
            sample_count=sample_count,
            average_ms=_decimal_or_none(row.average_ms),
            p50_ms=_decimal_or_none(row.p50_ms),
            p95_ms=_decimal_or_none(row.p95_ms),
        )

    @staticmethod
    def _get_category_distribution(*, session: Session, category_column: Any, timestamp_column: Any, window: AnalyticsWindow,
                                   exclude_null: bool = False, additional_conditions: tuple[Any, ...] = ()
    ) -> tuple[CategoryCount, ...]:
        conditions: list[Any] = [timestamp_column >= window.started_at, timestamp_column < window.ended_at, *additional_conditions,]
        if exclude_null:
            conditions.append(category_column.is_not(None))

        rows = session.execute(select(category_column.label("category"),
                                      func.count().label("count"))
                               .where(*conditions)
                               .group_by(category_column)
                               .order_by(func.count().desc(),
                                         category_column.asc())
        ).all()

        return tuple(CategoryCount(category=str(row.category), count=int(row.count)) for row in rows if row.category is not None)
    
    @staticmethod
    def _get_ai_timeline(*, session: Session, window: AnalyticsWindow) -> tuple[AIAnalyticsPoint, ...]:
        bucket_interval = _BUCKET_INTERVALS[window.bucket]
        statement = text(
            """
            WITH buckets AS (
                SELECT generate_series(
                    date_trunc(CAST(:bucket_unit AS text), CAST(:started_at AS timestamptz), 'UTC'),
                    date_trunc(CAST(:bucket_unit AS text), CAST(:ended_at AS timestamptz) - interval '1 microsecond', 'UTC'),
                    CAST(:bucket_interval AS interval)
                ) AS bucket_started_at
            ),
            run_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), started_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS runs,
                    COUNT(*) FILTER (WHERE status = 'completed') AS successful_runs,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed_runs,
                    COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_runs
                FROM ai.runs
                WHERE started_at >= :started_at
                AND started_at < :ended_at
                GROUP BY 1
            ),
            llm_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), started_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS llm_calls,
                    COUNT(*) FILTER (WHERE status = 'success') AS successful_llm_calls,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed_llm_calls,
                    COUNT(*) FILTER (WHERE status = 'timeout') AS timed_out_llm_calls,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
                FROM ai.llm_calls
                WHERE started_at >= :started_at
                AND started_at < :ended_at
                GROUP BY 1
            ),
            retrieval_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), started_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS retrieval_runs,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed_retrieval_runs,
                    COUNT(*) FILTER (WHERE status = 'timeout') AS timed_out_retrieval_runs,
                    COUNT(*) FILTER (WHERE status = 'success' AND zero_result IS TRUE) AS zero_result_retrievals
                FROM ai.retrieval_runs
                WHERE started_at >= :started_at
                AND started_at < :ended_at
                GROUP BY 1
            ),
            reranker_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), started_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS reranker_calls,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed_reranker_calls,
                    COUNT(*) FILTER (WHERE status = 'timeout') AS timed_out_reranker_calls
                FROM ai.reranker_calls
                WHERE started_at >= :started_at
                AND started_at < :ended_at
                GROUP BY 1
            ),
            embedding_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), started_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS embedding_calls,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed_embedding_calls,
                    COUNT(*) FILTER (WHERE status = 'timeout') AS timed_out_embedding_calls
                FROM ai.embedding_calls
                WHERE started_at >= :started_at
                AND started_at < :ended_at
                GROUP BY 1
            )
            SELECT
                buckets.bucket_started_at,
                COALESCE(run_counts.runs, 0) AS runs,
                COALESCE(run_counts.successful_runs, 0) AS successful_runs,
                COALESCE(run_counts.failed_runs, 0) AS failed_runs,
                COALESCE(run_counts.cancelled_runs, 0) AS cancelled_runs,
                COALESCE(llm_counts.llm_calls, 0) AS llm_calls,
                COALESCE(llm_counts.successful_llm_calls, 0) AS successful_llm_calls,
                COALESCE(llm_counts.failed_llm_calls, 0) AS failed_llm_calls,
                COALESCE(llm_counts.timed_out_llm_calls, 0) AS timed_out_llm_calls,
                COALESCE(llm_counts.input_tokens, 0) AS input_tokens,
                COALESCE(llm_counts.output_tokens, 0) AS output_tokens,
                COALESCE(llm_counts.cached_input_tokens, 0) AS cached_input_tokens,
                COALESCE(llm_counts.estimated_cost_usd, 0) AS estimated_cost_usd,
                COALESCE(retrieval_counts.retrieval_runs, 0) AS retrieval_runs,
                COALESCE(retrieval_counts.failed_retrieval_runs, 0) AS failed_retrieval_runs,
                COALESCE(retrieval_counts.timed_out_retrieval_runs, 0) AS timed_out_retrieval_runs,
                COALESCE(retrieval_counts.zero_result_retrievals, 0) AS zero_result_retrievals,
                COALESCE(reranker_counts.reranker_calls, 0) AS reranker_calls,
                COALESCE(reranker_counts.failed_reranker_calls, 0) AS failed_reranker_calls,
                COALESCE(reranker_counts.timed_out_reranker_calls, 0) AS timed_out_reranker_calls,
                COALESCE(embedding_counts.embedding_calls, 0) AS embedding_calls,
                COALESCE(embedding_counts.failed_embedding_calls, 0) AS failed_embedding_calls,
                COALESCE(embedding_counts.timed_out_embedding_calls, 0) AS timed_out_embedding_calls
            FROM buckets
            LEFT JOIN run_counts USING (bucket_started_at)
            LEFT JOIN llm_counts USING (bucket_started_at)
            LEFT JOIN retrieval_counts USING (bucket_started_at)
            LEFT JOIN reranker_counts USING (bucket_started_at)
            LEFT JOIN embedding_counts USING (bucket_started_at)
            ORDER BY buckets.bucket_started_at ASC
            """
        )

        rows = session.execute(statement,
            {
                "bucket_unit": window.bucket.value,
                "bucket_interval": bucket_interval,
                "started_at": window.started_at,
                "ended_at": window.ended_at,
            },
        ).mappings()

        return tuple(AIAnalyticsPoint(
            bucket_started_at=row["bucket_started_at"],
            runs=int(row["runs"]),
            successful_runs=int(row["successful_runs"]),
            failed_runs=int(row["failed_runs"]),
            cancelled_runs=int(row["cancelled_runs"]),
            llm_calls=int(row["llm_calls"]),
            successful_llm_calls=int(row["successful_llm_calls"]),
            failed_llm_calls=int(row["failed_llm_calls"]),
            timed_out_llm_calls=int(row["timed_out_llm_calls"]),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            cached_input_tokens=int(row["cached_input_tokens"]),
            estimated_cost_usd=_decimal_or_zero(row["estimated_cost_usd"]),
            retrieval_runs=int(row["retrieval_runs"]),
            failed_retrieval_runs=int(row["failed_retrieval_runs"]),
            timed_out_retrieval_runs=int(row["timed_out_retrieval_runs"]),
            zero_result_retrievals=int(row["zero_result_retrievals"]),
            reranker_calls=int(row["reranker_calls"]),
            failed_reranker_calls=int(row["failed_reranker_calls"]),
            timed_out_reranker_calls=int(row["timed_out_reranker_calls"]),
            embedding_calls=int(row["embedding_calls"]),
            failed_embedding_calls=int(row["failed_embedding_calls"]),
            timed_out_embedding_calls=int(row["timed_out_embedding_calls"]),
        ) for row in rows)
        
    @staticmethod
    def _get_ticket_totals(*, session: Session, window: AnalyticsWindow) -> dict[str, int]:
        created = session.scalar(select(func.count(TicketModel.id))
                                 .where(TicketModel.created_at >= window.started_at,
                                        TicketModel.created_at < window.ended_at)
        )

        resolved = session.scalar(select(func.count(TicketModel.id))
                                  .where(TicketModel.resolved_at.is_not(None),
                                         TicketModel.resolved_at >= window.started_at,
                                         TicketModel.resolved_at < window.ended_at)
        )

        closed = session.scalar(select(func.count(TicketModel.id))
                                .where(TicketModel.closed_at.is_not(None),
                                       TicketModel.closed_at >= window.started_at,
                                       TicketModel.closed_at < window.ended_at)
        )

        return {
            "created": int(created or 0),
            "resolved": int(resolved or 0),
            "closed": int(closed or 0),
        }

    @staticmethod
    def _get_escalation_totals(*, session: Session, window: AnalyticsWindow) -> dict[str, int]:
        created = session.scalar(select(func.count(EscalationModel.id))
                                 .where(EscalationModel.created_at >= window.started_at,
                                        EscalationModel.created_at < window.ended_at)
        )

        # Both resolved and dismissed are terminal escalation outcomes.
        resolved = session.scalar(select(func.count(EscalationModel.id))
                                  .where(EscalationModel.resolved_at.is_not(None),
                                         EscalationModel.resolved_at >= window.started_at,
                                         EscalationModel.resolved_at < window.ended_at)
        )

        return {
            "created": int(created or 0),
            "resolved": int(resolved or 0),
        }

    @staticmethod
    def _get_feedback_totals(*, session: Session, window: AnalyticsWindow) -> dict[str, Any]:
        row = session.execute(select(func.count(FeedbackModel.id).label("submitted"),
                                     func.avg(FeedbackModel.rating).label("average_rating"))
                              .where(FeedbackModel.created_at >= window.started_at,
                                     FeedbackModel.created_at < window.ended_at)
        ).one()

        return {
            "submitted": int(row.submitted or 0),
            "average_rating": _decimal_or_none(row.average_rating),
        }

    @staticmethod
    def _count_current_ticket_backlog(*, session: Session) -> int:
        value = session.scalar(select(func.count(TicketModel.id))
                               .where(TicketModel.status.not_in(("resolved", "closed")))
        )

        return int(value or 0)

    @staticmethod
    def _get_current_category_distribution(*, session: Session, category_column: Any) -> tuple[CategoryCount, ...]:
        rows = session.execute(select(category_column.label("category"),
                                      func.count().label("count"))
                               .where(category_column.is_not(None))
                               .group_by(category_column)
                               .order_by(func.count().desc(),
                                         category_column.asc())
        ).all()

        return tuple(CategoryCount(category=str(row.category), count=int(row.count)) for row in rows)

    @staticmethod
    def _get_resolution_duration(*, session: Session, created_column: Any, resolved_column: Any, window: AnalyticsWindow) -> DurationSummary:
        duration_ms = func.extract("epoch", resolved_column - created_column) * 1000
        row = session.execute(select(func.count(resolved_column).label("sample_count"),
                                     func.avg(duration_ms).label("average_ms"),
                                     func.percentile_cont(0.50).within_group(duration_ms).label("p50_ms"),
                                     func.percentile_cont(0.95).within_group(duration_ms).label("p95_ms"))
                              .where(resolved_column.is_not(None),
                                     resolved_column >= window.started_at,
                                     resolved_column < window.ended_at,
                                     resolved_column >= created_column)
        ).one()

        return DurationSummary(
            sample_count=int(row.sample_count or 0),
            average_ms=_decimal_or_none(row.average_ms),
            p50_ms=_decimal_or_none(row.p50_ms),
            p95_ms=_decimal_or_none(row.p95_ms),
        )
    
    @staticmethod
    def _get_support_timeline(*, session: Session, window: AnalyticsWindow) -> tuple[SupportAnalyticsPoint, ...]:
        bucket_interval = _BUCKET_INTERVALS[window.bucket]
        statement = text(
            """
            WITH buckets AS (
                SELECT generate_series(
                    date_trunc(CAST(:bucket_unit AS text), CAST(:started_at AS timestamptz), 'UTC'),
                    date_trunc(CAST(:bucket_unit AS text), CAST(:ended_at AS timestamptz) - interval '1 microsecond', 'UTC'),
                    CAST(:bucket_interval AS interval)
                ) AS bucket_started_at
            ),
            ticket_created_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), created_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS count
                FROM support.tickets
                WHERE created_at >= :started_at
                AND created_at < :ended_at
                GROUP BY 1
            ),
            ticket_resolved_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), resolved_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS count
                FROM support.tickets
                WHERE resolved_at IS NOT NULL
                AND resolved_at >= :started_at
                AND resolved_at < :ended_at
                GROUP BY 1
            ),
            ticket_closed_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), closed_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS count
                FROM support.tickets
                WHERE closed_at IS NOT NULL
                AND closed_at >= :started_at
                AND closed_at < :ended_at
                GROUP BY 1
            ),
            escalation_created_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), created_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS count
                FROM support.escalations
                WHERE created_at >= :started_at
                AND created_at < :ended_at
                GROUP BY 1
            ),
            escalation_resolved_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), resolved_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS count
                FROM support.escalations
                WHERE resolved_at IS NOT NULL
                AND resolved_at >= :started_at
                AND resolved_at < :ended_at
                GROUP BY 1
            ),
            feedback_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), created_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS count
                FROM support.feedback
                WHERE created_at >= :started_at
                AND created_at < :ended_at
                GROUP BY 1
            )
            SELECT
                buckets.bucket_started_at,
                COALESCE(ticket_created_counts.count, 0) AS tickets_created,
                COALESCE(ticket_resolved_counts.count, 0) AS tickets_resolved,
                COALESCE(ticket_closed_counts.count, 0) AS tickets_closed,
                COALESCE(escalation_created_counts.count, 0) AS escalations_created,
                COALESCE(escalation_resolved_counts.count, 0) AS escalations_resolved,
                COALESCE(feedback_counts.count, 0) AS feedback_submitted
            FROM buckets
            LEFT JOIN ticket_created_counts
                USING (bucket_started_at)
            LEFT JOIN ticket_resolved_counts
                USING (bucket_started_at)
            LEFT JOIN ticket_closed_counts
                USING (bucket_started_at)
            LEFT JOIN escalation_created_counts
                USING (bucket_started_at)
            LEFT JOIN escalation_resolved_counts
                USING (bucket_started_at)
            LEFT JOIN feedback_counts
                USING (bucket_started_at)
            ORDER BY buckets.bucket_started_at ASC
            """
        )

        rows = session.execute(statement,
            {
                "bucket_unit": window.bucket.value,
                "bucket_interval": bucket_interval,
                "started_at": window.started_at,
                "ended_at": window.ended_at,
            },
        ).mappings()

        return tuple(SupportAnalyticsPoint(
            bucket_started_at=row["bucket_started_at"],
            tickets_created=int(row["tickets_created"]),
            tickets_resolved=int(row["tickets_resolved"]),
            tickets_closed=int(row["tickets_closed"]),
            escalations_created=int(row["escalations_created"]),
            escalations_resolved=int(row["escalations_resolved"]),
            feedback_submitted=int(row["feedback_submitted"]),
        ) for row in rows)
    
    @staticmethod
    def _get_knowledge_inventory(*, session: Session) -> dict[str, int]:
        """
        Return current Knowledge Management inventory and health counters.

        An embedding-covered chunk is a distinct chunk having at least one persisted embedding artifact.
        Multiple provider/model artifacts for the same chunk do not inflate the coverage numerator.
        """
        statement = text(
            """
            SELECT
                (
                    SELECT COUNT(*)
                    FROM knowledge.knowledge_documents
                ) AS total_documents,
                (
                    SELECT COUNT(*)
                    FROM knowledge.knowledge_document_versions
                ) AS total_versions,
                (
                    SELECT COUNT(*)
                    FROM knowledge.knowledge_chunks
                ) AS total_chunks,
                (
                    SELECT COUNT(*)
                    FROM knowledge.knowledge_chunk_embeddings
                ) AS total_embeddings,
                (
                    SELECT COUNT(DISTINCT embedding.chunk_id)
                    FROM knowledge.knowledge_chunk_embeddings AS embedding
                ) AS embedded_chunks,
                (
                    SELECT COUNT(*)
                    FROM knowledge.knowledge_document_versions AS version
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM knowledge.knowledge_chunks AS chunk
                        WHERE chunk.version_id = version.id
                    )
                ) AS versions_without_chunks,
                (
                    SELECT COUNT(*)
                    FROM knowledge.knowledge_document_versions AS version
                    WHERE version.status IN ('ready', 'published')
                    AND EXISTS (
                        SELECT 1
                        FROM knowledge.knowledge_chunks AS chunk
                        WHERE chunk.version_id = version.id
                    )
                    AND EXISTS (
                        SELECT 1
                        FROM knowledge.knowledge_chunks AS chunk
                        WHERE chunk.version_id = version.id
                            AND NOT EXISTS (
                                SELECT 1
                                FROM knowledge.knowledge_chunk_embeddings AS embedding
                                WHERE embedding.chunk_id = chunk.id
                            )
                    )
                ) AS versions_missing_embeddings,
                (
                    SELECT COUNT(*)
                    FROM knowledge.knowledge_document_versions AS version
                    WHERE version.status IN ('draft', 'processing')
                    AND version.ingestion_status IN ('pending', 'running')
                ) AS processing_backlog
            """
        )

        row = session.execute(statement).mappings().one()

        return {
            "total_documents": int(row["total_documents"] or 0),
            "total_versions": int(row["total_versions"] or 0),
            "total_chunks": int(row["total_chunks"] or 0),
            "total_embeddings": int(row["total_embeddings"] or 0),
            "embedded_chunks": int(row["embedded_chunks"] or 0),
            "versions_without_chunks": int(row["versions_without_chunks"] or 0),
            "versions_missing_embeddings": int(row["versions_missing_embeddings"] or 0),
            "processing_backlog": int(row["processing_backlog"] or 0),
        }

    @staticmethod
    def _get_knowledge_processing_duration(*, session: Session, window: AnalyticsWindow) -> DurationSummary:
        duration_ms = func.extract(
            "epoch", (KnowledgeDocumentVersionModel.processing_completed_at - KnowledgeDocumentVersionModel.processing_started_at)
        ) * 1000

        row = session.execute(select(func.count(KnowledgeDocumentVersionModel.id).label("sample_count"),
                                     func.avg(duration_ms).label("average_ms"),
                                     func.percentile_cont(0.50).within_group(duration_ms).label("p50_ms"),
                                     func.percentile_cont(0.95).within_group(duration_ms).label("p95_ms"))
                              .where(KnowledgeDocumentVersionModel.processing_started_at.is_not(None),
                                     KnowledgeDocumentVersionModel.processing_completed_at.is_not(None),
                                     KnowledgeDocumentVersionModel.processing_completed_at >= window.started_at,
                                     KnowledgeDocumentVersionModel.processing_completed_at < window.ended_at,
                                     KnowledgeDocumentVersionModel.processing_completed_at >= KnowledgeDocumentVersionModel.processing_started_at,
                                     KnowledgeDocumentVersionModel.ingestion_status.in_(("completed", "failed")))
        ).one()

        return DurationSummary(
            sample_count=int(row.sample_count or 0),
            average_ms=_decimal_or_none(row.average_ms),
            p50_ms=_decimal_or_none(row.p50_ms),
            p95_ms=_decimal_or_none(row.p95_ms),
        )
    
    @staticmethod
    def _get_knowledge_health_timeline(*, session: Session, window: AnalyticsWindow) -> tuple[KnowledgeHealthPoint, ...]:
        bucket_interval = _BUCKET_INTERVALS[window.bucket]

        statement = text(
            """
            WITH buckets AS (
                SELECT generate_series(
                    date_trunc(CAST(:bucket_unit AS text), CAST(:started_at AS timestamptz), 'UTC'),
                    date_trunc(CAST(:bucket_unit AS text), CAST(:ended_at AS timestamptz) - interval '1 microsecond', 'UTC'),
                    CAST(:bucket_interval AS interval)
                ) AS bucket_started_at
            ),
            version_created_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), created_at, 'UTC') AS bucket_started_at,
                    COUNT(*) AS versions_created
                FROM knowledge.knowledge_document_versions
                WHERE created_at >= :started_at
                AND created_at < :ended_at
                GROUP BY 1
            ),
            processing_outcome_counts AS (
                SELECT
                    date_trunc(CAST(:bucket_unit AS text), processing_completed_at, 'UTC') AS bucket_started_at,
                    COUNT(*) FILTER (WHERE ingestion_status = 'completed') AS processing_completed,
                    COUNT(*) FILTER (WHERE ingestion_status = 'failed') AS processing_failed
                FROM knowledge.knowledge_document_versions
                WHERE processing_completed_at IS NOT NULL
                AND processing_completed_at >= :started_at
                AND processing_completed_at < :ended_at
                AND ingestion_status IN ('completed', 'failed')
                GROUP BY 1
            )
            SELECT
                buckets.bucket_started_at,
                COALESCE(version_created_counts.versions_created, 0) AS versions_created,
                COALESCE(processing_outcome_counts.processing_completed, 0) AS processing_completed,
                COALESCE(processing_outcome_counts.processing_failed, 0) AS processing_failed
            FROM buckets
            LEFT JOIN version_created_counts
                USING (bucket_started_at)
            LEFT JOIN processing_outcome_counts
                USING (bucket_started_at)
            ORDER BY buckets.bucket_started_at ASC
            """
        )

        rows = session.execute(statement, {
            "bucket_unit": window.bucket.value,
            "bucket_interval": bucket_interval,
            "started_at": window.started_at,
            "ended_at": window.ended_at,
        }).mappings()

        return tuple(KnowledgeHealthPoint(
            bucket_started_at=row["bucket_started_at"],
            versions_created=int(row["versions_created"]),
            processing_completed=int(row["processing_completed"]),
            processing_failed=int(row["processing_failed"]),
        ) for row in rows)

def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None

    if isinstance(value, Decimal):
        return value

    return Decimal(str(value))

def _decimal_or_zero(value: Any) -> Decimal:
    converted = _decimal_or_none(value)
    return converted if converted is not None else Decimal("0")