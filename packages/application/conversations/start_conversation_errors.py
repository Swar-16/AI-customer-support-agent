# AI-customer-support-agent\packages\application\conversations\start_conversation_errors.py
from __future__ import annotations
import uuid

class StartConversationError(RuntimeError):
    """Base error for idempotent conversation-start operations."""

class StartConversationValidationError(StartConversationError):
    """The supplied message or idempotency key is invalid."""

class StartConversationAccessDeniedError(StartConversationError):
    """The authenticated principal cannot start customer conversations."""

class ConversationStarterDoesNotExistError(StartConversationError):
    def __init__(self, customer_id: uuid.UUID) -> None:
        self.customer_id = customer_id
        super().__init__("The authenticated customer does not exist.")

class ConversationStarterNotActiveError(StartConversationError):
    def __init__(self, customer_id: uuid.UUID) -> None:
        self.customer_id = customer_id
        super().__init__("The authenticated customer is not active.")

class ConversationStarterRoleMismatchError(StartConversationError):
    """Authenticated and persisted customer roles do not agree."""

class ConversationStartIdempotencyConflictError(StartConversationError):
    """
    The same customer reused an idempotency key for different input.

    Request hashes and message content must not appear in the public error.
    """
    def __init__(self, *, request_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        self.request_id = request_id
        self.conversation_id = conversation_id
        super().__init__("The idempotency key was already used for a different conversation-start request.")

class ConversationStartRequestExpiredError(StartConversationError):
    """
    The durable idempotency record exists but its replay period ended.

    The caller must generate a new idempotency key. The existing conversation and accepted customer message are never deleted here.
    """
    def __init__(self, *, request_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        self.request_id = request_id
        self.conversation_id = conversation_id
        super().__init__("The idempotency replay period has expired. Use a new idempotency key.")

class ConversationStartProcessingInProgressError(StartConversationError):
    """
    Another request currently owns the processing lease.

    The API may translate this into a safe 202 response containing only stable identifiers and retry guidance.
    """
    def __init__(self, *, request_id: uuid.UUID, conversation_id: uuid.UUID, retry_after_seconds: int) -> None:
        if isinstance(retry_after_seconds, bool) or not isinstance(retry_after_seconds, int):
            raise TypeError("retry_after_seconds must be an integer")

        if retry_after_seconds <= 0:
            raise ValueError("retry_after_seconds must be greater than zero")

        self.request_id = request_id
        self.conversation_id = conversation_id
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Conversation-start processing is already in progress.")

class ConversationStartLeaseLostError(StartConversationError):
    """The processor no longer owns the lease and must not persist a terminal result over a newer processing attempt."""
    def __init__(self, request_id: uuid.UUID) -> None:
        self.request_id = request_id
        super().__init__("Conversation-start processing lease is no longer owned.")

class ConversationStartReplayUnavailableError(StartConversationError):
    """
    A terminal record exists but its safe response snapshot is unavailable.

    This indicates corrupt or inconsistent persistence rather than invalid customer input.
    """
    def __init__(self, request_id: uuid.UUID) -> None:
        self.request_id = request_id
        super().__init__("The stored conversation-start result is unavailable.")

class ConversationStartPersistenceContractError(StartConversationError):
    """Required repositories, session state, or generated IDs are missing."""