# AI-customer-support-agent\packages\database\repositories\support\message_repository.py
## The API should not perform SQLAlchemy queries everywhere.
## API -> Application Service -> Repository -> SQLAlchemy -> PostgreSQL

import uuid

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from packages.database.models.support.user import UserModel

# Stable application-specific PostgreSQL advisory-lock key used only to serialize initial administrator provisioning.
_INITIAL_ADMIN_LOCK_ID = 4_821_947_031

class UserRepository:
    def __init__(self, session: Session):
        self._session = session
    
    def get_by_id(self, user_id: uuid.UUID) -> UserModel | None:
        statement = select(UserModel).where(
            UserModel.id == user_id
        )

        return self._session.scalar(statement)
    
    def get_by_id_for_update(self, user_id: uuid.UUID) -> UserModel | None:
        statement = (select(UserModel)
                     .where(UserModel.id == user_id)
                     .with_for_update()
        )

        return self._session.scalar(statement)
    
    def get_by_external_id(self, external_id: str) -> UserModel | None:
        statement = select(UserModel).where(
            UserModel.external_id == external_id
        )

        return self._session.scalar(statement)
    
    def add(self, user: UserModel) -> None:
        self._session.add(user)
        
    def flush(self) -> None:
        self._session.flush()

    def acquire_initial_admin_lock(self) -> None:
        """
        Serialize initial-administrator provisioning across processes.

        This PostgreSQL transaction-level advisory lock is automatically released when the transaction commits or rolls back.
        """
        self._session.execute(select(func.pg_advisory_xact_lock(_INITIAL_ADMIN_LOCK_ID)))
        
    def acquire_admin_management_lock(self) -> None:
        """
        Serialize administrator provisioning and access mutations.

        This prevents concurrent requests from disabling or demoting the final active administrator.
        """
        self._session.execute(select(func.pg_advisory_xact_lock(_INITIAL_ADMIN_LOCK_ID)))

    def acquire_initial_admin_lock(self) -> None:
        self.acquire_admin_management_lock()

    def count_active_admins(self) -> int:
        statement = (select(func.count(UserModel.id))
                     .where(UserModel.role == "admin",
                            UserModel.status == "active")
        )

        return int(self._session.scalar(statement) or 0)