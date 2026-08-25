from sqlalchemy.orm import Session

from packages.database.repositories.conversation_repository import (
    ConversationRepository,
)
from packages.database.repositories.user_repository import (
    UserRepository,
)
from packages.database.session import SessionLocal


class SqlAlchemyUnitOfWork:
    def __init__(self):
        self.session: Session | None = None

    def __enter__(self):
        self.session = SessionLocal()

        self.users = UserRepository(self.session)
        self.conversations = ConversationRepository(self.session)

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.session is None:
            return

        if exc_type is not None:
            self.session.rollback()

        self.session.close()

    def commit(self):
        if self.session is None:
            raise RuntimeError("Unit of work not started")

        self.session.commit()

    def rollback(self):
        if self.session is not None:
            self.session.rollback()