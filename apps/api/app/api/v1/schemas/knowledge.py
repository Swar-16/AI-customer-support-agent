# AI-customer-support-agent\apps\api\app\api\v1\schemas\knowledge.py
from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.knowledge.application.get_document import GetKnowledgeDocumentResult
from packages.knowledge.application.get_version import GetKnowledgeVersionResult
from packages.knowledge.application.list_documents import ListKnowledgeDocumentsResult
from packages.knowledge.application.list_versions import ListKnowledgeVersionsResult
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.enums import KnowledgeContentType, KnowledgeDocumentStatus, KnowledgeIngestionStatus
from packages.knowledge.domain.enums import KnowledgeSourceType, KnowledgeVersionStatus, KnowledgeVisibility
from packages.knowledge.domain.version import KnowledgeDocumentVersion

MAX_SOURCE_CONTENT_LENGTH = 2_000_000

class KnowledgeAPIModel(BaseModel):
    """
    Base contract for Knowledge Management endpoints.

    Unexpected fields are rejected. String normalization is performed explicitly because source content must not be silently modified.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

# Shared response models
class KnowledgeDocumentSummaryResponse(KnowledgeAPIModel):
    document_id: UUID
    title: str
    description: str | None = None
    content_type: KnowledgeContentType
    visibility: KnowledgeVisibility
    status: KnowledgeDocumentStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None

    @classmethod
    def from_domain(cls, document: KnowledgeDocument) -> "KnowledgeDocumentSummaryResponse":
        if not isinstance(document, KnowledgeDocument):
            raise TypeError("document must be a KnowledgeDocument.")

        return cls(
            document_id=document.id,
            title=document.title,
            description=document.description,
            content_type=document.content_type,
            visibility=document.visibility,
            status=document.status,
            created_at=document.created_at,
            updated_at=document.updated_at,
            archived_at=document.archived_at,
        )

class KnowledgeDocumentDetailResponse(KnowledgeDocumentSummaryResponse):
    published_version_id: UUID | None = None
    version_count: int = Field(ge=0)

    @classmethod
    def from_application(cls, result: GetKnowledgeDocumentResult) -> "KnowledgeDocumentDetailResponse":
        if not isinstance(result, GetKnowledgeDocumentResult):
            raise TypeError("result must be a GetKnowledgeDocumentResult.")

        document = result.document
        return cls(
            document_id=document.id,
            title=document.title,
            description=document.description,
            content_type=document.content_type,
            visibility=document.visibility,
            status=document.status,
            created_at=document.created_at,
            updated_at=document.updated_at,
            archived_at=document.archived_at,
            published_version_id=result.published_version_id,
            version_count=result.version_count,
        )

class KnowledgeDocumentListResponse(KnowledgeAPIModel):
    items: tuple[KnowledgeDocumentSummaryResponse, ...]
    total: int = Field(ge=0)
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(default=None, ge=0)

    @classmethod
    def from_application(cls, result: ListKnowledgeDocumentsResult) -> "KnowledgeDocumentListResponse":
        if not isinstance(result, ListKnowledgeDocumentsResult):
            raise TypeError("result must be a ListKnowledgeDocumentsResult.")

        return cls(
            items=tuple(KnowledgeDocumentSummaryResponse.from_domain(document) for document in result.documents),
            total=result.total,
            count=result.count,
            limit=result.limit,
            offset=result.offset,
            has_more=result.has_more,
            next_offset=result.next_offset,
        )

class KnowledgeVersionSummaryResponse(KnowledgeAPIModel):
    version_id: UUID
    document_id: UUID
    version_number: int = Field(ge=1)
    source_type: KnowledgeSourceType
    source_name: str | None = None
    content_hash: str = Field(min_length=64, max_length=64)
    status: KnowledgeVersionStatus
    ingestion_status: KnowledgeIngestionStatus
    created_at: datetime
    updated_at: datetime
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    ready_at: datetime | None = None
    published_at: datetime | None = None
    superseded_at: datetime | None = None
    archived_at: datetime | None = None
    failure_code: str | None = Field(default=None, max_length=200)

    @classmethod
    def from_domain(cls, version: KnowledgeDocumentVersion) -> "KnowledgeVersionSummaryResponse":
        if not isinstance(version, KnowledgeDocumentVersion):
            raise TypeError("version must be a KnowledgeDocumentVersion.")

        return cls(
            version_id=version.id,
            document_id=version.document_id,
            version_number=version.version_number,
            source_type=version.source_type,
            source_name=version.source_name,
            content_hash=version.content_hash,
            status=version.status,
            ingestion_status=version.ingestion_status,
            created_at=version.created_at,
            updated_at=version.updated_at,
            processing_started_at=version.processing_started_at,
            processing_completed_at=version.processing_completed_at,
            ready_at=version.ready_at,
            published_at=version.published_at,
            superseded_at=version.superseded_at,
            archived_at=version.archived_at,
            failure_code=version.failure_code,
        )

class KnowledgeVersionDetailResponse(KnowledgeVersionSummaryResponse):
    document_title: str
    is_current_published_version: bool
    source_content_length: int = Field(ge=1)

    @classmethod
    def from_application(cls, result: GetKnowledgeVersionResult) -> "KnowledgeVersionDetailResponse":
        if not isinstance(result, GetKnowledgeVersionResult):
            raise TypeError("result must be a GetKnowledgeVersionResult.")

        version = result.version
        return cls(
            version_id=version.id,
            document_id=version.document_id,
            version_number=version.version_number,
            source_type=version.source_type,
            source_name=version.source_name,
            content_hash=version.content_hash,
            status=version.status,
            ingestion_status=version.ingestion_status,
            created_at=version.created_at,
            updated_at=version.updated_at,
            processing_started_at=version.processing_started_at,
            processing_completed_at=version.processing_completed_at,
            ready_at=version.ready_at,
            published_at=version.published_at,
            superseded_at=version.superseded_at,
            archived_at=version.archived_at,
            failure_code=version.failure_code,
            document_title=result.document.title,
            is_current_published_version=result.is_current_published_version,
            source_content_length=len(version.source_content),
        )

class KnowledgeVersionListResponse(KnowledgeAPIModel):
    document_id: UUID
    items: tuple[KnowledgeVersionSummaryResponse, ...]
    total: int = Field(ge=0)
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(default=None, ge=0)

    @classmethod
    def from_application(cls, result: ListKnowledgeVersionsResult) -> "KnowledgeVersionListResponse":
        if not isinstance(result, ListKnowledgeVersionsResult):
            raise TypeError("result must be a ListKnowledgeVersionsResult.")

        return cls(
            document_id=result.document_id,
            items=tuple(KnowledgeVersionSummaryResponse.from_domain(version) for version in result.versions),
            total=result.total,
            count=result.count,
            limit=result.limit,
            offset=result.offset,
            has_more=result.has_more,
            next_offset=result.next_offset,
        )

# Mutation requests
class CreateKnowledgeDocumentRequest(KnowledgeAPIModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2_000)
    content_type: KnowledgeContentType
    visibility: KnowledgeVisibility = KnowledgeVisibility.CUSTOMER

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be blank.")

        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

class CreateKnowledgeVersionRequest(KnowledgeAPIModel):
    source_type: KnowledgeSourceType
    source_content: str = Field(min_length=1, max_length=MAX_SOURCE_CONTENT_LENGTH)
    source_name: str | None = Field(default=None, max_length=500)

    @field_validator("source_content")
    @classmethod
    def validate_source_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_content must not be blank.")

        # Preserve the exact submitted source representation.
        return value

    @field_validator("source_name")
    @classmethod
    def normalize_source_name(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None
    
    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, value: KnowledgeSourceType) -> KnowledgeSourceType:
        supported = {KnowledgeSourceType.MARKDOWN, KnowledgeSourceType.PLAIN_TEXT,}

        if value not in supported:
            raise ValueError("Only markdown and plain_text sources are supported.")

        return value

# Mutation responses
class CreateKnowledgeDocumentResponse(KnowledgeAPIModel):
    document_id: UUID
    created_at: datetime

class CreateKnowledgeVersionResponse(KnowledgeAPIModel):
    version_id: UUID
    document_id: UUID
    version_number: int = Field(ge=1)
    content_hash: str = Field(min_length=64, max_length=64)
    created_at: datetime

class ProcessKnowledgeVersionResponse(KnowledgeAPIModel):
    version_id: UUID
    document_id: UUID
    chunk_count: int = Field(ge=1)
    parser_identity: str = Field(min_length=1, max_length=300)
    normalizer_identity: str = Field(min_length=1, max_length=300)
    chunker_identity: str = Field(min_length=1, max_length=300)
    version_status: KnowledgeVersionStatus
    ingestion_status: KnowledgeIngestionStatus

class EmbedKnowledgeVersionResponse(KnowledgeAPIModel):
    version_id: UUID
    document_id: UUID
    total_chunks: int = Field(ge=1)
    existing_count: int = Field(ge=0)
    created_count: int = Field(ge=0)
    provider_identity: str = Field(min_length=1, max_length=300)
    input_strategy_identity: str = Field(min_length=1, max_length=300)

class PublishKnowledgeVersionResponse(KnowledgeAPIModel):
    version_id: UUID
    document_id: UUID
    version_number: int = Field(ge=1)
    status: KnowledgeVersionStatus
    published_at: datetime
    superseded_version_id: UUID | None = None

class ArchiveKnowledgeDocumentResponse(KnowledgeAPIModel):
    document_id: UUID
    status: KnowledgeDocumentStatus
    archived_at: datetime
    superseded_version_id: UUID | None = None