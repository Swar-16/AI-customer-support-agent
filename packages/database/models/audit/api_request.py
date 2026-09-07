# AI-customer-support-agent\packages\database\models\audit\api_request.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class APIRequestModel(Base):
    """
    Durable operational record for one HTTP request.

    This table answers:

    - which API endpoint was called;
    - when it started and completed;
    - how long it took;
    - whether it succeeded;
    - which trace and authenticated actor initiated it;
    - which stable application error occurred.

    Sensitive headers, authorization tokens, cookies, and unrestricted request/response bodies must never be stored here.
    """

    __tablename__ = "api_requests"

    __table_args__ = (
        CheckConstraint(
            """
            method IN (
                'GET',
                'POST',
                'PUT',
                'PATCH',
                'DELETE',
                'OPTIONS',
                'HEAD'
            )
            """,
            name="valid_method",
        ),
        CheckConstraint(
            """
            outcome IN (
                'success',
                'client_error',
                'server_error'
            )
            """,
            name="valid_outcome",
        ),
        CheckConstraint(
            "status_code BETWEEN 100 AND 599",
            name="valid_status_code",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="non_negative_latency",
        ),
        CheckConstraint(
            """
            request_size_bytes IS NULL
            OR request_size_bytes >= 0
            """,
            name="non_negative_request_size",
        ),
        CheckConstraint(
            """
            response_size_bytes IS NULL
            OR response_size_bytes >= 0
            """,
            name="non_negative_response_size",
        ),
        CheckConstraint(
            "completed_at >= started_at",
            name="valid_completion_time",
        ),
        CheckConstraint(
            """
            (
                outcome = 'success'
                AND status_code < 400
                AND error_code IS NULL
            )
            OR
            (
                outcome = 'client_error'
                AND status_code BETWEEN 400 AND 499
            )
            OR
            (
                outcome = 'server_error'
                AND status_code >= 500
            )
            """,
            name="valid_outcome_status",
        ),
        
        Index(
            "idx_api_requests_trace",
            "trace_id",
        ),
        Index(
            "idx_api_requests_started",
            text("started_at DESC"),
        ),
        Index(
            "idx_api_requests_route_started",
            "route_template",
            text("started_at DESC"),
        ),
        Index(
            "idx_api_requests_status_started",
            "status_code",
            text("started_at DESC"),
        ),
        Index(
            "idx_api_requests_outcome_started",
            "outcome",
            text("started_at DESC"),
        ),
        Index(
            "idx_api_requests_error_started",
            "error_code",
            text("started_at DESC"),
        ),
        Index(
            "idx_api_requests_actor_started",
            "actor_user_id",
            text("started_at DESC"),
        ),
        Index(
            "idx_api_requests_latency",
            text("latency_ms DESC"),
        ),
        
        {
            "schema": "audit",
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    method: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )

    route_template: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    request_path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status_code: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    outcome: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    exception_type: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    actor_role: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    client_ip: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
    )

    user_agent: Mapped[str | None] = mapped_column(
        String(1_024),
        nullable=True,
    )

    request_size_bytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    response_size_bytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    latency_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )