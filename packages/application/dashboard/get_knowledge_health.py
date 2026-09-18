# AI-customer-support-agent\packages\application\dashboard\get_knowledge_health.py
from __future__ import annotations
from dataclasses import dataclass

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.application.dashboard.analytics_contract import AnalyticsWindow, DashboardAnalyticsAccessDeniedError
from packages.application.dashboard.analytics_models import KnowledgeHealthResult
from packages.application.dashboard.analytics_repository import DashboardAnalyticsRepository, DashboardAnalyticsRepositoryFactory

@dataclass(frozen=True, slots=True)
class GetKnowledgeHealthQuery:
    principal: AuthenticatedPrincipal
    window: AnalyticsWindow

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal.")

        if not isinstance(self.window, AnalyticsWindow):
            raise TypeError("window must be an AnalyticsWindow.")

class GetKnowledgeHealth:
    """
    Return administrator-only Knowledge Management health analytics.

    Current inventory, coverage, backlog, and categorical distributions are snapshot metrics.
    Version creation and processing outcomes are event metrics restricted to the requested half-open time window.
    """
    def __init__(self, *, repository_factory: DashboardAnalyticsRepositoryFactory) -> None:
        if not callable(repository_factory):
            raise TypeError("repository_factory must be callable.")

        self._repository_factory = repository_factory

    def execute(self, query: GetKnowledgeHealthQuery) -> KnowledgeHealthResult:
        if not isinstance(query, GetKnowledgeHealthQuery):
            raise TypeError("query must be a GetKnowledgeHealthQuery.")

        if query.principal.role is not AuthRole.ADMIN:
            raise DashboardAnalyticsAccessDeniedError()

        repository = self._repository_factory()
        if not isinstance(repository, DashboardAnalyticsRepository):
            raise TypeError("repository_factory must return a DashboardAnalyticsRepository.")

        result = repository.get_knowledge_health(window=query.window)
        if not isinstance(result, KnowledgeHealthResult):
            raise TypeError("repository must return a KnowledgeHealthResult.")

        return result