# AI-customer-support-agent\packages\application\dashboard\get_conversation_analytics.py
from __future__ import annotations
from dataclasses import dataclass

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.application.dashboard.analytics_contract import AnalyticsWindow, DashboardAnalyticsAccessDeniedError
from packages.application.dashboard.analytics_models import ConversationAnalyticsResult
from packages.application.dashboard.analytics_repository import DashboardAnalyticsRepository, DashboardAnalyticsRepositoryFactory

@dataclass(frozen=True, slots=True)
class GetConversationAnalyticsQuery:
    principal: AuthenticatedPrincipal
    window: AnalyticsWindow

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal.")

        if not isinstance(self.window, AnalyticsWindow):
            raise TypeError("window must be an AnalyticsWindow.")

class GetConversationAnalytics:
    """Return sanitized conversation analytics for administrators."""
    def __init__(self, *, repository_factory: DashboardAnalyticsRepositoryFactory) -> None:
        if not callable(repository_factory):
            raise TypeError("repository_factory must be callable.")

        self._repository_factory = repository_factory

    def execute(self, query: GetConversationAnalyticsQuery) -> ConversationAnalyticsResult:
        if not isinstance(query, GetConversationAnalyticsQuery):
            raise TypeError("query must be a GetConversationAnalyticsQuery.")

        if query.principal.role is not AuthRole.ADMIN:
            raise DashboardAnalyticsAccessDeniedError()

        repository = self._repository_factory()
        if not isinstance(repository, DashboardAnalyticsRepository):
            raise TypeError("repository_factory must return a DashboardAnalyticsRepository.")

        result = repository.get_conversation_analytics(window=query.window)
        if not isinstance(result, ConversationAnalyticsResult):
            raise TypeError("repository must return a ConversationAnalyticsResult.")

        return result