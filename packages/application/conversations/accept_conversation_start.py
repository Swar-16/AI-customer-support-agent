# AI-customer-support-agent\packages\application\conversations\accept_conversation_start.py
from __future__ import annotations
import hashlib
import hmac
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.application.conversations.process_customer_message import MAX_CUSTOMER_MESSAGE_LENGTH
from packages.application.conversations.start_conversation_errors import ConversationStarterDoesNotExistError, ConversationStarterNotActiveError
from packages.application.conversations.start_conversation_errors import ConversationStarterRoleMismatchError, ConversationStartIdempotencyConflictError
from packages.application.conversations.start_conversation_errors import ConversationStartPersistenceContractError, ConversationStartRequestExpiredError
from packages.application.conversations.start_conversation_errors import StartConversationAccessDeniedError, StartConversationValidationError
from packages.database.models.support.conversation import ConversationModel
from packages.database.models.support.conversation_start_request import ConversationStartRequestModel
from packages.database.models.support.message import MessageModel
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
VALID_CHANNELS: Final[frozenset[str]] = frozenset({"web", "mobile", "email", "api"})
MAX_TITLE_LENGTH: Final[int] = 500
MIN_IDEMPOTENCY_KEY_LENGTH: Final[int] = 16
MAX_IDEMPOTENCY_KEY_LENGTH: Final[int] = 255
_IDEMPOTENCY_UNIQUE_CONSTRAINT: Final[str] = "uq_conversation_start_requests_customer_key"

@dataclass(frozen=True, slots=True)
class AcceptConversationStartCommand:
    principal: AuthenticatedPrincipal
    idempotency_key: str
    customer_message: str
    trace_id: uuid.UUID
    channel: str = "web"
    title: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if self.principal.role is not AuthRole.CUSTOMER:
            raise StartConversationAccessDeniedError("Only customers may start customer conversations.")

        if not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID")

        object.__setattr__(self, "idempotency_key", _normalize_idempotency_key(self.idempotency_key))
        object.__setattr__(self, "customer_message", _normalize_customer_message(self.customer_message))
        object.__setattr__(self, "channel", _normalize_channel(self.channel))
        object.__setattr__(self, "title", _normalize_title(self.title))

@dataclass(frozen=True, slots=True)
class AcceptConversationStartResult:
    request_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_message_id: uuid.UUID
    status: str
    created: bool
    expires_at: datetime

class AcceptConversationStart:
    """
    Atomically accept the first message of a new conversation.

    A successful new acceptance commits exactly:

    - one conversation;
    - one first customer message;
    - one durable idempotency record;
    - one immutable conversation-created audit event.

    No AI/provider operation occurs in this transaction.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory, idempotency_ttl: timedelta = timedelta(hours=24)) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if not isinstance(idempotency_ttl, timedelta):
            raise TypeError("idempotency_ttl must be a timedelta")

        if idempotency_ttl <= timedelta(0):
            raise ValueError("idempotency_ttl must be positive")

        self._uow_factory = uow_factory
        self._idempotency_ttl = idempotency_ttl

    def execute(self, command: AcceptConversationStartCommand) -> AcceptConversationStartResult:
        if not isinstance(command, AcceptConversationStartCommand):
            raise TypeError("command must be an AcceptConversationStartCommand")

        key_hash = _sha256_hex(command.idempotency_key)
        request_fingerprint = _request_fingerprint(customer_message=command.customer_message, channel=command.channel, title=command.title)
        try:
            return self._execute_once(command=command, key_hash=key_hash, request_fingerprint=request_fingerprint)
        
        except IntegrityError as exc:
            if _constraint_name(exc) != _IDEMPOTENCY_UNIQUE_CONSTRAINT:
                raise

        # A concurrent request committed the same scoped key first.
        return self._load_existing_after_conflict(command=command, key_hash=key_hash, request_fingerprint=request_fingerprint)

    def _execute_once(self, *, command: AcceptConversationStartCommand, key_hash: str, request_fingerprint: str) -> AcceptConversationStartResult:
        now = datetime.now(timezone.utc)

        with self._uow_factory() as uow:
            self._require_uow(uow)
            self._validate_customer(principal=command.principal, uow=uow)
            existing = uow.conversation_start_requests.get_by_customer_and_key_hash(customer_id=command.principal.user_id, idempotency_key_hash=key_hash)
            if existing is not None:
                return self._existing_result(existing=existing, request_fingerprint=request_fingerprint, measured_at=now)

            conversation_id = uuid7()
            customer_message_id = uuid7()
            request_id = uuid7()
            conversation = ConversationModel(
                id=conversation_id,
                user_id=command.principal.user_id,
                status="open",
                channel=command.channel,
                title=command.title,
                # Sequence 1 is consumed by the first message.
                next_message_sequence=2,
                resolved_at=None,
                closed_at=None,
            )

            customer_message = MessageModel(
                id=customer_message_id,
                conversation_id=conversation_id,
                role="customer",
                content=command.customer_message,
                sequence_number=1,
                metadata_={},
            )

            start_request = ConversationStartRequestModel(
                id=request_id,
                customer_id=command.principal.user_id,
                idempotency_key_hash=key_hash,
                request_fingerprint=request_fingerprint,
                status="accepted",
                conversation_id=conversation_id,
                customer_message_id=customer_message_id,
                latest_ai_run_id=None,
                processing_token=None,
                processing_expires_at=None,
                response_snapshot=None,
                attempt_count=0,
                created_at=now,
                updated_at=now,
                completed_at=None,
                expires_at=(now + self._idempotency_ttl),
            )

            # Persist in explicit foreign-key dependency order.

            # These flushes do not commit anything. All three records still belong to the same transaction and 
            # will be rolled back together if any later insert, constraint, audit operation, or commit fails.
            
            uow.conversations.add(conversation)
            uow.conversations.flush()
            
            uow.messages.add(customer_message)
            uow.messages.flush()
            
            uow.conversation_start_requests.add(start_request)
            uow.conversation_start_requests.flush()

            self._validate_persisted_state(conversation=conversation, customer_message=customer_message, start_request=start_request)

            AuditRecorder(repository=uow.audit_events).record(
                RecordAuditEventCommand(
                    event_type="conversation.created",
                    entity_type="conversation",
                    entity_id=conversation.id,
                    action="created",
                    actor=AuditActor(actor_type=AuditActorType.CUSTOMER, actor_id=command.principal.user_id),
                    trace_id=command.trace_id,
                    conversation_id=conversation.id,
                    before_state=None,
                    after_state={
                        "status": conversation.status,
                        "channel": conversation.channel,
                        "title_present": conversation.title is not None,
                        "initial_message_accepted": True,
                    },
                    metadata={"creation_mode": "idempotent_first_message",},
                    occurred_at=conversation.created_at,
                )
            )

            result = AcceptConversationStartResult(
                request_id=start_request.id,
                conversation_id=conversation.id,
                customer_message_id=customer_message.id,
                status=start_request.status,
                created=True,
                expires_at=start_request.expires_at,
            )

            uow.commit()
            return result

    def _load_existing_after_conflict(self, *, command: AcceptConversationStartCommand, key_hash: str, request_fingerprint: str) -> AcceptConversationStartResult:
        now = datetime.now(timezone.utc)
        with self._uow_factory() as uow:
            self._require_uow(uow)
            self._validate_customer(principal=command.principal, uow=uow)
            existing = uow.conversation_start_requests.get_by_customer_and_key_hash(customer_id=command.principal.user_id, idempotency_key_hash=key_hash)
            if existing is None:
                raise ConversationStartPersistenceContractError("The competing idempotency request could not be reloaded.")

            return self._existing_result(existing=existing, request_fingerprint=request_fingerprint, measured_at=now)

    @staticmethod
    def _existing_result(*, existing: ConversationStartRequestModel, request_fingerprint: str, measured_at: datetime) -> AcceptConversationStartResult:
        if not hmac.compare_digest(existing.request_fingerprint, request_fingerprint):
            raise ConversationStartIdempotencyConflictError(request_id=existing.id, conversation_id=existing.conversation_id)

        if existing.expires_at <= measured_at:
            raise ConversationStartRequestExpiredError(request_id=existing.id, conversation_id=existing.conversation_id)

        return AcceptConversationStartResult(
            request_id=existing.id,
            conversation_id=existing.conversation_id,
            customer_message_id=existing.customer_message_id,
            status=existing.status,
            created=False,
            expires_at=existing.expires_at,
        )

    @staticmethod
    def _validate_customer(*, principal: AuthenticatedPrincipal, uow: SqlAlchemyUnitOfWork) -> None:
        customer = uow.users.get_by_id(principal.user_id)
        if customer is None:
            raise ConversationStarterDoesNotExistError(principal.user_id)

        if customer.status != "active":
            raise ConversationStarterNotActiveError(principal.user_id)

        if customer.role != principal.role.value:
            raise ConversationStarterRoleMismatchError("Authenticated and persisted roles differ.")

        if customer.role != "customer":
            raise StartConversationAccessDeniedError("Only customers may start customer conversations.")

    @staticmethod
    def _require_uow(uow: SqlAlchemyUnitOfWork) -> None:
        if uow.session is None:
            raise ConversationStartPersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.users is None:
            raise ConversationStartPersistenceContractError("UserRepository unavailable")

        if uow.conversations is None:
            raise ConversationStartPersistenceContractError("ConversationRepository unavailable")

        if uow.messages is None:
            raise ConversationStartPersistenceContractError("MessageRepository unavailable")

        if uow.conversation_start_requests is None:
            raise ConversationStartPersistenceContractError(
                "ConversationStartRequestRepository unavailable"
            )

        if uow.audit_events is None:
            raise ConversationStartPersistenceContractError(
                "AuditEventRepository unavailable"
            )

    @staticmethod
    def _validate_persisted_state(
        *,
        conversation: ConversationModel,
        customer_message: MessageModel,
        start_request: ConversationStartRequestModel,
    ) -> None:
        if conversation.id is None:
            raise ConversationStartPersistenceContractError(
                "Conversation ID was not persisted"
            )

        if conversation.created_at is None:
            raise ConversationStartPersistenceContractError(
                "Conversation created_at was not generated"
            )

        if conversation.next_message_sequence != 2:
            raise ConversationStartPersistenceContractError(
                "Conversation sequence was not advanced "
                "past its first message"
            )

        if customer_message.id is None:
            raise ConversationStartPersistenceContractError(
                "Customer message ID was not persisted"
            )

        if customer_message.sequence_number != 1:
            raise ConversationStartPersistenceContractError(
                "Initial customer message must use sequence 1"
            )

        if start_request.id is None:
            raise ConversationStartPersistenceContractError(
                "Conversation-start request ID was not persisted"
            )


def _normalize_idempotency_key(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(
            "idempotency_key must be a string"
        )

    if value != value.strip():
        raise StartConversationValidationError(
            "idempotency_key cannot contain surrounding whitespace"
        )

    if not (
        MIN_IDEMPOTENCY_KEY_LENGTH
        <= len(value)
        <= MAX_IDEMPOTENCY_KEY_LENGTH
    ):
        raise StartConversationValidationError(
            "idempotency_key must contain between "
            f"{MIN_IDEMPOTENCY_KEY_LENGTH} and "
            f"{MAX_IDEMPOTENCY_KEY_LENGTH} characters"
        )

    if any(
        ord(character) < 33
        or ord(character) > 126
        for character in value
    ):
        raise StartConversationValidationError(
            "idempotency_key must contain only visible "
            "ASCII characters"
        )

    return value


def _normalize_customer_message(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(
            "customer_message must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise StartConversationValidationError(
            "customer_message cannot be empty"
        )

    if len(normalized) > MAX_CUSTOMER_MESSAGE_LENGTH:
        raise StartConversationValidationError(
            "customer_message exceeds "
            f"{MAX_CUSTOMER_MESSAGE_LENGTH} characters"
        )

    return normalized


def _normalize_channel(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("channel must be a string")

    normalized = value.strip().lower()

    if normalized not in VALID_CHANNELS:
        expected = ", ".join(
            sorted(VALID_CHANNELS)
        )
        raise StartConversationValidationError(
            f"channel must be one of: {expected}"
        )

    return normalized


def _normalize_title(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError(
            "title must be a string or None"
        )

    normalized = " ".join(value.split())

    if not normalized:
        return None

    if len(normalized) > MAX_TITLE_LENGTH:
        raise StartConversationValidationError(
            f"title exceeds {MAX_TITLE_LENGTH} characters"
        )

    return normalized


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def _request_fingerprint(
    *,
    customer_message: str,
    channel: str,
    title: str | None,
) -> str:
    canonical_payload = json.dumps(
        {
            "version": 1,
            "customer_message": customer_message,
            "channel": channel,
            "title": title,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return _sha256_hex(canonical_payload)


def _constraint_name(
    error: IntegrityError,
) -> str | None:
    original = error.orig
    diagnostic = getattr(original, "diag", None)

    if diagnostic is None:
        return None

    return getattr(
        diagnostic,
        "constraint_name",
        None,
    )