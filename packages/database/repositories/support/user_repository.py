## The API should not perform SQLAlchemy queries everywhere.
## API -> Application Service -> Repository -> SQLAlchemy -> PostgreSQL

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.support.user import UserModel

class UserRepository:
    def __init__(self, session: Session):
        self._session = session
    
    def get_by_id(self, user_id: uuid.UUID) -> UserModel | None:
        statement = select(UserModel).where(
            UserModel.id == user_id
        )

        return self._session.scalar(statement)
    
    def get_by_external_id(self, external_id: str) -> UserModel | None:
        statement = select(UserModel).where(
            UserModel.external_id == external_id
        )

        return self._session.scalar(statement)
    
    def add(self, user: UserModel) -> None:
        self._session.add(user)