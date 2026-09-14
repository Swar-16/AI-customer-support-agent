# AI-customer-support-agent\packages\database\repositories\support\auth_repository.py
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

from packages.database.models.support.auth_session import AuthSessionModel
from packages.database.models.support.user import UserModel
from packages.database.models.support.user_credential import UserCredentialModel

class AuthRepository:
    """
    Persistence operations for local credentials and refresh-token sessions.

    Password hashing, token generation, and token verification belong to the application/security layer—not this repository.
    """
    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Credentials
    def get_credential_by_user_id(self, user_id: uuid.UUID, *, for_update: bool = False) -> UserCredentialModel | None:
        statement: Select[tuple[UserCredentialModel]] = (select(UserCredentialModel)
                                                         .where(UserCredentialModel.user_id == user_id)
        )

        if for_update:
            statement = statement.with_for_update()

        return self._session.scalar(statement)

    def get_credential_by_email(self, email_normalized: str, *, for_update: bool = False) -> UserCredentialModel | None:
        statement: Select[tuple[UserCredentialModel]] = (select(UserCredentialModel)
                                                         .where(UserCredentialModel.email_normalized == email_normalized)
        )

        if for_update:
            statement = statement.with_for_update()

        return self._session.scalar(statement)

    def get_user_by_email(self, email_normalized: str, *, for_update: bool = False) -> UserModel | None:
        statement: Select[tuple[UserModel]] = (select(UserModel)
                                               .join(UserCredentialModel, UserCredentialModel.user_id == UserModel.id)
                                               .where(UserCredentialModel.email_normalized == email_normalized)
        )

        if for_update:
            statement = statement.with_for_update(of=UserModel)

        return self._session.scalar(statement)

    def add_credential(self, credential: UserCredentialModel) -> None:
        self._session.add(credential)

    # Refresh-token sessions
    def get_session_by_id(self, session_id: uuid.UUID, *, for_update: bool = False) -> AuthSessionModel | None:
        statement: Select[tuple[AuthSessionModel]] = (select(AuthSessionModel)
                                                      .where(AuthSessionModel.id == session_id)
        )

        if for_update:
            statement = statement.with_for_update()

        return self._session.scalar(statement)

    def get_session_by_token_hash(self, refresh_token_hash: str, *, for_update: bool = False) -> AuthSessionModel | None:
        statement: Select[tuple[AuthSessionModel]] = (select(AuthSessionModel)
                                                      .where(AuthSessionModel.refresh_token_hash == refresh_token_hash)
        )

        if for_update:
            statement = statement.with_for_update()

        return self._session.scalar(statement)

    def add_session(self, auth_session: AuthSessionModel) -> None:
        self._session.add(auth_session)

    def list_active_sessions_for_user(self, user_id: uuid.UUID, *, now: datetime) -> tuple[AuthSessionModel, ...]:
        statement = (select(AuthSessionModel)
                     .where(AuthSessionModel.user_id == user_id,
                            AuthSessionModel.revoked_at.is_(None),
                            AuthSessionModel.expires_at > now)
                     .order_by(AuthSessionModel.created_at.desc())
        )

        return tuple(self._session.scalars(statement))

    def revoke_active_family(self, *, family_id: uuid.UUID, revoked_at: datetime, reason: str) -> int:
        """
        Revoke all currently active sessions in a refresh-token family.

        This is used when refresh-token reuse is detected.
        """
        statement = (update(AuthSessionModel)
                     .where(AuthSessionModel.family_id == family_id,
                            AuthSessionModel.revoked_at.is_(None))
                     .values(revoked_at=revoked_at, revocation_reason=reason)
                     .execution_options(synchronize_session=False)
        )

        result = self._session.execute(statement)
        return result.rowcount or 0

    def revoke_all_for_user(self, *, user_id: uuid.UUID, revoked_at: datetime, reason: str) -> int:
        """
        Revoke every active refresh-token session owned by a user.

        This supports password changes, account disabling, and an explicit 'log out from all devices' operation.
        """
        statement = (update(AuthSessionModel)
                     .where(AuthSessionModel.user_id == user_id,
                            AuthSessionModel.revoked_at.is_(None))
                     .values(revoked_at=revoked_at, revocation_reason=reason)
                     .execution_options(synchronize_session=False)
        )

        result = self._session.execute(statement)
        return result.rowcount or 0

    def flush(self) -> None:
        """Assign database-generated values without committing the transaction."""
        self._session.flush()