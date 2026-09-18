# AI-customer-support-agent\packages\application\dashboard\analytics_repository.py
from __future__ import annotations
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from packages.application.dashboard.analytics_contract import AnalyticsWindow
from packages.application.dashboard.analytics_models import AIAnalyticsResult, ConversationAnalyticsResult, KnowledgeHealthResult, SupportAnalyticsResult

@runtime_checkable
class DashboardAnalyticsRepository(Protocol):
    """
    Read-side persistence boundary for dashboard aggregates.

    Implementations must aggregate inside the backing data store and return sanitized analytical results. 
    They must not expose ORM models, SQLAlchemy rows, message content, prompts, source documents, or provider payloads.

    Every timestamp query must apply the AnalyticsWindow half-open interval:

        started_at <= timestamp < ended_at
    """
    def get_conversation_analytics(self, *, window: AnalyticsWindow) -> ConversationAnalyticsResult:
        """Return conversation and message aggregates."""
        ...

    def get_ai_analytics(self, *, window: AnalyticsWindow) -> AIAnalyticsResult:
        """Return AI quality, usage, cost, and retrieval aggregates."""
        ...

    def get_support_analytics(self, *, window: AnalyticsWindow) -> SupportAnalyticsResult:
        """Return ticket, escalation, and feedback aggregates."""
        ...

    def get_knowledge_health(self, *, window: AnalyticsWindow) -> KnowledgeHealthResult:
        """Return knowledge lifecycle and embedding-health aggregates."""
        ...

DashboardAnalyticsRepositoryFactory = Callable[[], DashboardAnalyticsRepository,]