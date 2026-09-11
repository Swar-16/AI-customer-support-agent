# AI-customer-support-agent\packages\application\observability\record_api_request.py
from __future__ import annotations
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final

from packages.database.models.audit.api_request import APIRequestModel
from packages.database.repositories.audit.api_request_repository import APIRequestRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
VALID_HTTP_METHODS: Final[frozenset[str]] = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD",})
VALID_ACTOR_ROLES: Final[frozenset[str]] = frozenset({"customer", "support_agent", "admin", "system",})
MAX_ROUTE_TEMPLATE_LENGTH: Final[int] = 500
MAX_REQUEST_PATH_LENGTH: Final[int] = 2_000
MAX_ERROR_CODE_LENGTH: Final[int] = 100
MAX_EXCEPTION_TYPE_LENGTH: Final[int] = 255
MAX_CLIENT_IP_LENGTH: Final[int] = 45
MAX_USER_AGENT_LENGTH: Final[int] = 1_024
MAX_METADATA_KEYS: Final[int] = 100
MAX_METADATA_SERIALIZED_LENGTH: Final[int] = 20_000

class RecordAPIRequestError(RuntimeError):
    """Base application error for durable request recording."""

class APIRequestPersistenceContractError(RecordAPIRequestError):
    """Raised when persistence wiring or generated state is invalid."""

@dataclass(frozen=True, slots=True)
class RecordAPIRequestCommand:
    """
    Sanitized HTTP request information ready for persistence.

    Raw request bodies, response bodies, cookies, authorization headers, API keys, and arbitrary headers must never be placed in this command.
    """
    trace_id: uuid.UUID
    method: str
    request_path: str
    status_code: int
    latency_ms: int
    started_at: datetime
    completed_at: datetime
    route_template: str | None = None
    error_code: str | None = None
    exception_type: str | None = None
    actor_user_id: uuid.UUID | None = None
    actor_role: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    request_size_bytes: int | None = None
    response_size_bytes: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_uuid(self.trace_id, field_name="trace_id")
        method = self._normalize_method(self.method)
        request_path = self._normalize_required_text(self.request_path, field_name="request_path", max_length=MAX_REQUEST_PATH_LENGTH)
        route_template = self._normalize_optional_text(self.route_template, field_name="route_template", max_length=MAX_ROUTE_TEMPLATE_LENGTH)
        self._validate_status_code(self.status_code)
        self._validate_non_negative_integer(self.latency_ms, field_name="latency_ms")
        self._validate_datetime(self.started_at, field_name="started_at")
        self._validate_datetime(self.completed_at, field_name="completed_at")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be earlier than started_at")

        error_code = self._normalize_optional_code(self.error_code, field_name="error_code", max_length=MAX_ERROR_CODE_LENGTH)
        exception_type = self._normalize_optional_text(self.exception_type, field_name="exception_type", max_length=MAX_EXCEPTION_TYPE_LENGTH)
        actor_role = self._normalize_optional_actor_role(self.actor_role)
        if self.actor_user_id is not None:
            self._validate_uuid(self.actor_user_id, field_name="actor_user_id")

        if self.actor_user_id is None and actor_role is not None:
            raise ValueError("actor_role cannot be supplied without actor_user_id")

        if self.actor_user_id is not None and actor_role is None:
            raise ValueError("actor_role is required when actor_user_id is supplied")

        client_ip = self._normalize_optional_text(self.client_ip, field_name="client_ip", max_length=MAX_CLIENT_IP_LENGTH)
        user_agent = self._normalize_optional_text(self.user_agent, field_name="user_agent", max_length=MAX_USER_AGENT_LENGTH)
        if self.request_size_bytes is not None:
            self._validate_non_negative_integer(self.request_size_bytes, field_name="request_size_bytes")

        if self.response_size_bytes is not None:
            self._validate_non_negative_integer(self.response_size_bytes, field_name="response_size_bytes")

        outcome = self._outcome_for_status(self.status_code)
        if outcome == "success":
            error_code = None
            exception_type = None

        normalized_metadata = self._normalize_metadata(self.metadata)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "request_path", request_path)
        object.__setattr__(self, "route_template", route_template)
        object.__setattr__(self, "error_code", error_code)
        object.__setattr__(self, "exception_type", exception_type)
        object.__setattr__(self, "actor_role", actor_role)
        object.__setattr__(self, "client_ip", client_ip)
        object.__setattr__(self, "user_agent", user_agent)
        object.__setattr__(self, "metadata", MappingProxyType(normalized_metadata))

    @property
    def outcome(self) -> str:
        return self._outcome_for_status(self.status_code)

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _normalize_method(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("method must be a string")

        normalized = value.strip().upper()
        if normalized not in VALID_HTTP_METHODS:
            expected = ", ".join(sorted(VALID_HTTP_METHODS))
            raise ValueError(f"method must be one of: {expected}")

        return normalized

    @staticmethod
    def _validate_status_code(value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("status_code must be an integer")

        if value < 100 or value > 599:
            raise ValueError("status_code must be between 100 and 599")

    @staticmethod
    def _validate_non_negative_integer(value: int, *, field_name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer")

        if value < 0:
            raise ValueError(f"{field_name} cannot be negative")

    @staticmethod
    def _validate_datetime(value: datetime, *, field_name: str) -> None:
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")

    @staticmethod
    def _normalize_required_text(value: str, *, field_name: str, max_length: int) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        if len(normalized) > max_length:
            raise ValueError(f"{field_name} exceeds {max_length} characters")

        return normalized

    @staticmethod
    def _normalize_optional_text(value: str | None, *, field_name: str, max_length: int) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = value.strip()
        if not normalized:
            return None

        if len(normalized) > max_length:
            # Request telemetry must not fail merely because an external user-agent or path value is unexpectedly large.
            return normalized[:max_length]

        return normalized

    @staticmethod
    def _normalize_optional_code(value: str | None, *, field_name: str, max_length: int) -> str | None:
        normalized = RecordAPIRequestCommand._normalize_optional_text(value, field_name=field_name, max_length=max_length)
        if normalized is None:
            return None

        return normalized.upper()

    @staticmethod
    def _normalize_optional_actor_role(value: str | None) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError("actor_role must be a string or None")

        normalized = value.strip().lower()
        if not normalized:
            return None

        if normalized not in VALID_ACTOR_ROLES:
            expected = ", ".join(sorted(VALID_ACTOR_ROLES))
            raise ValueError(f"actor_role must be one of: {expected}")

        return normalized

    @staticmethod
    def _outcome_for_status(status_code: int) -> str:
        if status_code < 400:
            return "success"

        if status_code < 500:
            return "client_error"

        return "server_error"

    @staticmethod
    def _normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping")

        if len(metadata) > MAX_METADATA_KEYS:
            raise ValueError("metadata contains too many keys")

        normalized: dict[str, Any] = {}
        for key, value in metadata.items():
            if not isinstance(key, str):
                raise TypeError("metadata keys must be strings")

            normalized_key = key.strip()
            if not normalized_key:
                raise ValueError("metadata keys cannot be blank")

            if normalized_key in normalized:
                raise ValueError("metadata contains duplicate keys after normalization")

            normalized[normalized_key] = value

        try:
            serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
            
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must contain only JSON-serializable values") from exc

        if len(serialized) > MAX_METADATA_SERIALIZED_LENGTH:
            raise ValueError(f"serialized metadata exceeds {MAX_METADATA_SERIALIZED_LENGTH} characters")

        return normalized

@dataclass(frozen=True, slots=True)
class RecordAPIRequestResult:
    request_id: uuid.UUID
    trace_id: uuid.UUID
    status_code: int
    outcome: str
    recorded_at: datetime

class RecordAPIRequest:
    """
    Persist one completed HTTP-request record.

    The middleware must call this service through a best-effort boundary. This service itself remains strict
    so invalid telemetry is detectable and logged rather than silently stored.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def execute(self, command: RecordAPIRequestCommand) -> RecordAPIRequestResult:
        if not isinstance(command, RecordAPIRequestCommand):
            raise TypeError("command must be a RecordAPIRequestCommand")

        with self._uow_factory() as uow:
            repository = self._require_repository(uow)

            request_record = APIRequestModel(
                trace_id=command.trace_id,
                method=command.method,
                route_template=command.route_template,
                request_path=command.request_path,
                status_code=command.status_code,
                outcome=command.outcome,
                error_code=command.error_code,
                exception_type=command.exception_type,
                actor_user_id=command.actor_user_id,
                actor_role=command.actor_role,
                client_ip=command.client_ip,
                user_agent=command.user_agent,
                request_size_bytes=command.request_size_bytes,
                response_size_bytes=command.response_size_bytes,
                latency_ms=command.latency_ms,
                metadata_=dict(command.metadata),
                started_at=command.started_at,
                completed_at=command.completed_at,
            )

            repository.add(request_record)
            repository.flush()
            if request_record.id is None:
                raise APIRequestPersistenceContractError("API request ID was not generated after flush")

            if request_record.recorded_at is None:
                raise APIRequestPersistenceContractError("API request recorded_at was not generated after flush")

            result = RecordAPIRequestResult(
                request_id=request_record.id,
                trace_id=request_record.trace_id,
                status_code=request_record.status_code,
                outcome=request_record.outcome,
                recorded_at=request_record.recorded_at,
            )

            uow.commit()
            return result

    @staticmethod
    def _require_repository(uow: SqlAlchemyUnitOfWork) -> APIRequestRepository:
        if uow.session is None:
            raise APIRequestPersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.api_requests is None:
            raise APIRequestPersistenceContractError("APIRequestRepository unavailable")

        return uow.api_requests