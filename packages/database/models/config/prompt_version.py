import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class PromptVersionModel(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="valid_status",
        ),
        
        UniqueConstraint(
            "prompt_name",
            "version",
            name="uq_prompt_name_version",
        ),
        
        {"schema": "config"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    prompt_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    template: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    purpose: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    model_parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="draft",
    )

    checksum: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )