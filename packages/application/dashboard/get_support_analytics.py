# AI-customer-support-agent\packages\application\dashboard\get_support_analytics.py
from __future__ import annotations
from dataclasses import dataclass

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.application.dashboard.analytics_contract import AnalyticsWindow, DashboardAnalyticsAccessDeniedError
from packages.application.dashboard.analytics_models import SupportAnalyticsResult
from packages.application.dashboard.analytics_repository import DashboardAnalyticsRepository, DashboardAnalyticsRepositoryFactory

@dataclass(frozen=True, slots=True)
class GetSupportAnalyticsQuery:
    principal: AuthenticatedPrincipal
    window: AnalyticsWindow

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal.")

        if not isinstance(self.window, AnalyticsWindow):
            raise TypeError("window must be an AnalyticsWindow.")

class GetSupportAnalytics:
    """
    Return sanitized operational support analytics.

    Windowed metrics describe events occurring inside the requested half-open interval. Current backlog and
    status distributions are point-in-time snapshots and are labelled with snapshot_measured_at.
    """
    def __init__(self, *, repository_factory: DashboardAnalyticsRepositoryFactory) -> None:
        if not callable(repository_factory):
            raise TypeError("repository_factory must be callable.")

        self._repository_factory = repository_factory

    def execute(self, query: GetSupportAnalyticsQuery) -> SupportAnalyticsResult:
        if not isinstance(query, GetSupportAnalyticsQuery):
            raise TypeError("query must be a GetSupportAnalyticsQuery.")

        if query.principal.role is not AuthRole.ADMIN:
            raise DashboardAnalyticsAccessDeniedError()

        repository = self._repository_factory()
        if not isinstance(repository, DashboardAnalyticsRepository):
            raise TypeError("repository_factory must return a DashboardAnalyticsRepository.")

        result = repository.get_support_analytics(window=query.window)
        if not isinstance(result, SupportAnalyticsResult):
            raise TypeError("repository must return a SupportAnalyticsResult.")

        return result