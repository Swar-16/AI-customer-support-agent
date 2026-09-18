# AI-customer-support-agent\packages\database\repositories\support\conversation_start_request_repository.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Literal
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from packages.database.models.support.conversation_start_request import ConversationStartRequestModel

TerminalStatus = Literal["completed", "failed"]

class ConversationStartRequestRepository:
    """
    Persistence adapter for idempotent conversation starts.

    This repository:
    - never receives or stores the raw idempotency key;
    - atomically acquires processing leases;
    - prevents stale processors from completing another processor's work;
    - does not commit transactions;
    - does not invoke AI providers.
    """
    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Creation
    def add(self, request: ConversationStartRequestModel) -> None:
        self._validate_model(request)
        self._session.add(request)

    def flush(self) -> None:
        self._session.flush()

    # Lookups
    def get_by_id(self, request_id: uuid.UUID) -> ConversationStartRequestModel | None:
        self._validate_uuid(request_id, field_name="request_id")

        statement = (select(ConversationStartRequestModel)
                     .where(ConversationStartRequestModel.id == request_id)
        )

        return self._session.scalar(statement)

    def get_by_customer_and_key_hash(self, *, customer_id: uuid.UUID, idempotency_key_hash: str) -> ConversationStartRequestModel | None:
        self._validate_uuid(customer_id, field_name="customer_id")
        self._validate_sha256_hex(idempotency_key_hash, field_name="idempotency_key_hash")
        statement = (select(ConversationStartRequestModel)
                     .where(ConversationStartRequestModel.customer_id == customer_id,
                            ConversationStartRequestModel.idempotency_key_hash == idempotency_key_hash)
        )

        return self._session.scalar(statement)

    def get_by_customer_and_key_hash_for_update(self, *, customer_id: uuid.UUID, idempotency_key_hash: str) -> ConversationStartRequestModel | None:
        self._validate_uuid(customer_id, field_name="customer_id")
        self._validate_sha256_hex(idempotency_key_hash, field_name="idempotency_key_hash")
        statement = (select(ConversationStartRequestModel)
                     .where(ConversationStartRequestModel.customer_id == customer_id,
                            ConversationStartRequestModel.idempotency_key_hash == idempotency_key_hash)
                     .with_for_update()
        )

        return self._session.scalar(statement)

    def get_by_conversation_id(self, conversation_id: uuid.UUID) -> ConversationStartRequestModel | None:
        self._validate_uuid(conversation_id, field_name="conversation_id")
        statement = (select(ConversationStartRequestModel)
                     .where(ConversationStartRequestModel.conversation_id == conversation_id)
        )

        return self._session.scalar(statement)

    # Processing lease
    def acquire_processing_lease(self, *, request_id: uuid.UUID, processing_token: uuid.UUID, acquired_at: datetime, processing_expires_at: datetime) -> ConversationStartRequestModel | None:
        """
        Claim an accepted request or reclaim an expired processing request.

        Returns the updated record when the lease was acquired. Returns None when another processor owns an
        active lease, the request is terminal, expired by retention policy, or does not exist.
        """
        self._validate_uuid(request_id, field_name="request_id")
        self._validate_uuid(processing_token, field_name="processing_token")
        self._validate_aware_datetime(acquired_at, field_name="acquired_at")
        self._validate_aware_datetime(processing_expires_at, field_name="processing_expires_at")
        if processing_expires_at <= acquired_at:
            raise ValueError("processing_expires_at must be later than acquired_at")

        claimable_state = or_(ConversationStartRequestModel.status == "accepted",
                              and_(ConversationStartRequestModel.status == "processing",
                                   ConversationStartRequestModel.processing_expires_at <= acquired_at),
        )
        statement = (update(ConversationStartRequestModel)
                     .where(ConversationStartRequestModel.id == request_id,
                            ConversationStartRequestModel.expires_at > acquired_at,
                            claimable_state)
                     .values(status="processing",
                             processing_token=processing_token, processing_expires_at=processing_expires_at,
                             attempt_count=ConversationStartRequestModel.attempt_count + 1, updated_at=acquired_at)
                     .returning(ConversationStartRequestModel)
                     .execution_options(synchronize_session=False, populate_existing=True)
        )

        return self._session.execute(statement).scalar_one_or_none()

    # Terminal transitions
    def mark_completed(self, *, request_id: uuid.UUID, processing_token: uuid.UUID, latest_ai_run_id: uuid.UUID, 
                       response_snapshot: dict[str, Any], completed_at: datetime
    ) -> ConversationStartRequestModel | None:
        return self._finish(
            request_id=request_id,
            processing_token=processing_token,
            latest_ai_run_id=latest_ai_run_id,
            response_snapshot=response_snapshot,
            completed_at=completed_at,
            terminal_status="completed",
        )

    def mark_failed(self, *, request_id: uuid.UUID, processing_token: uuid.UUID, latest_ai_run_id: uuid.UUID | None, 
                    response_snapshot: dict[str, Any], completed_at: datetime
    ) -> ConversationStartRequestModel | None:
        return self._finish(
            request_id=request_id,
            processing_token=processing_token,
            latest_ai_run_id=latest_ai_run_id,
            response_snapshot=response_snapshot,
            completed_at=completed_at,
            terminal_status="failed",
        )

    def _finish(self, *, request_id: uuid.UUID, processing_token: uuid.UUID, latest_ai_run_id: uuid.UUID | None, 
                response_snapshot: dict[str, Any], completed_at: datetime, terminal_status: TerminalStatus,
    ) -> ConversationStartRequestModel | None:
        self._validate_uuid(request_id, field_name="request_id")
        self._validate_uuid(processing_token, field_name="processing_token")
        if latest_ai_run_id is not None:
            self._validate_uuid(latest_ai_run_id, field_name="latest_ai_run_id")

        if not isinstance(response_snapshot, dict):
            raise TypeError("response_snapshot must be a dictionary")

        if not response_snapshot:
            raise ValueError("response_snapshot cannot be empty")

        self._validate_aware_datetime(completed_at, field_name="completed_at")

        if terminal_status not in {"completed", "failed"}:
            raise ValueError("terminal_status must be completed or failed")

        statement = (update(ConversationStartRequestModel)
                     .where(ConversationStartRequestModel.id == request_id,
                            ConversationStartRequestModel.status == "processing",
                            ConversationStartRequestModel.processing_token == processing_token)
                     .values(status=terminal_status, latest_ai_run_id=latest_ai_run_id, processing_token=None, processing_expires_at=None,
                             response_snapshot=dict(response_snapshot), completed_at=completed_at, updated_at=completed_at)
                     .returning(ConversationStartRequestModel)
                     .execution_options(synchronize_session=False, populate_existing=True)
        )

        return self._session.execute(statement).scalar_one_or_none()

    # Validation
    @staticmethod
    def _validate_model(request: ConversationStartRequestModel) -> None:
        if not isinstance(request, ConversationStartRequestModel):
            raise TypeError("request must be a ConversationStartRequestModel")

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _validate_sha256_hex(value: str, *, field_name: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        if len(value) != 64:
            raise ValueError(f"{field_name} must contain 64 hexadecimal characters")

        try:
            int(value, 16)
            
        except ValueError as exc:
            raise ValueError(f"{field_name} must be lowercase hexadecimal") from exc

        if value != value.lower():
            raise ValueError(f"{field_name} must be lowercase hexadecimal")

    @staticmethod
    def _validate_aware_datetime(value: datetime, *, field_name: str) -> None:
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")