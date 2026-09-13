# AI-customer-support-agent\packages\knowledge\application\mutation_context.py
from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID

from packages.application.audit.models import AuditActor, AuditActorType
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.knowledge.application.exceptions import KnowledgeMutationAccessDeniedError

@dataclass(frozen=True, slots=True)
class KnowledgeMutationContext:
    """
    Trusted execution identity for a knowledge mutation.

    HTTP endpoints create an administrator context from a verified principal.
    Offline maintenance scripts create an explicitly system-attributed   context without pretending to own an authentication session.
    """
    actor: AuditActor
    trace_id: UUID
    initiating_admin_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.actor, AuditActor):
            raise TypeError("actor must be an AuditActor.")

        if not isinstance(self.trace_id, UUID):
            raise TypeError("trace_id must be a UUID.")

        if self.initiating_admin_id is not None and not isinstance(self.initiating_admin_id, UUID):
            raise TypeError("initiating_admin_id must be a UUID or None.")

        if self.actor.actor_type is AuditActorType.ADMIN:
            if self.actor.actor_id is None:
                raise ValueError("An administrator context requires actor_id.")

            if self.initiating_admin_id != self.actor.actor_id:
                raise ValueError("initiating_admin_id must match the administrator actor ID.")

        elif self.actor.actor_type is AuditActorType.SYSTEM:
            if self.actor.actor_id is not None:
                raise ValueError("A system context cannot contain actor_id.")

            if self.initiating_admin_id is not None:
                raise ValueError("A system context cannot claim an initiating administrator.")

        else:
            raise KnowledgeMutationAccessDeniedError("Knowledge mutations require an administrator or trusted system context.")

    @classmethod
    def from_admin(cls, *, principal: AuthenticatedPrincipal, trace_id: UUID) -> KnowledgeMutationContext:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal.")

        if principal.role is not AuthRole.ADMIN:
            raise KnowledgeMutationAccessDeniedError("Only administrators may mutate knowledge.")

        return cls(
            actor=AuditActor(actor_type=AuditActorType.ADMIN, actor_id=principal.user_id),
            trace_id=trace_id,
            initiating_admin_id=principal.user_id,
        )

    @classmethod
    def for_system(cls, *, trace_id: UUID) -> KnowledgeMutationContext:
        return cls(
            actor=AuditActor(actor_type=AuditActorType.SYSTEM),
            trace_id=trace_id,
            initiating_admin_id=None,
        )

    @property
    def is_admin(self) -> bool:
        return self.actor.actor_type is AuditActorType.ADMIN

    @property
    def is_system(self) -> bool:
        return self.actor.actor_type is AuditActorType.SYSTEM