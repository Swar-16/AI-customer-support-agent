# AI-customer-support-agent\packages\database\repositories\support\errors.py
class RepositoryError(RuntimeError):
    pass


class ConversationNotFoundError(RepositoryError):
    def __init__(self, *, conversation_id: object, ) -> None:
        self.conversation_id = conversation_id

        super().__init__(f"Conversation not found: {conversation_id}")