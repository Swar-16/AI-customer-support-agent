import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.support.conversation import ConversationModel
from packages.database.models.support.message import MessageModel


class ConversationRepository:
    def __init__(self, session: Session):
        self._session = session

    def add(self, conversation: ConversationModel) -> None:
        self._session.add(conversation)

    def get_by_id(self, conversation_id: uuid.UUID) -> ConversationModel | None:
        statement = select(ConversationModel).where(
            ConversationModel.id == conversation_id
        )

        return self._session.scalar(statement)

    def get_messages(self, conversation_id: uuid.UUID) -> list[MessageModel]:
        statement = (
            select(MessageModel)
            .where(
                MessageModel.conversation_id == conversation_id
            )
            .order_by(MessageModel.sequence_number)
        )

        return list(self._session.scalars(statement))