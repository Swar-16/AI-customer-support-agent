from __future__ import annotations

from packages.database.models.knowledge.chunk import KnowledgeChunkModel
from packages.database.models.knowledge.document import KnowledgeDocumentModel
from packages.database.models.knowledge.document_version import KnowledgeDocumentVersionModel
from packages.knowledge.domain.chunk import KnowledgeChunk
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.enums import KnowledgeContentType, KnowledgeDocumentStatus, KnowledgeIngestionStatus
from packages.knowledge.domain.enums import KnowledgeSourceType, KnowledgeVersionStatus, KnowledgeVisibility
from packages.knowledge.domain.version import KnowledgeDocumentVersion


# Knowledge Document
def document_to_domain(model: KnowledgeDocumentModel) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=model.id,
        title=model.title,
        description=model.description,
        content_type=KnowledgeContentType(model.content_type),
        visibility=KnowledgeVisibility(model.visibility),
        status=KnowledgeDocumentStatus(model.status),
        metadata=model.metadata_,
        created_at=model.created_at,
        updated_at=model.updated_at,
        archived_at=model.archived_at,
        deleted_at=model.deleted_at,
    )

def document_to_model(document: KnowledgeDocument) -> KnowledgeDocumentModel:
    return KnowledgeDocumentModel(
        id=document.id,
        title=document.title,
        description=document.description,
        content_type=document.content_type.value,
        visibility=document.visibility.value,
        status=document.status.value,
        metadata_=dict(document.metadata),
        created_at=document.created_at,
        updated_at=document.updated_at,
        archived_at=document.archived_at,
        deleted_at=document.deleted_at,
    )

def update_document_model(model: KnowledgeDocumentModel, document: KnowledgeDocument) -> None:
    """
    Copy mutable persisted state from the domain entity onto an existing
    SQLAlchemy model.

    Identity is deliberately not modified.
    """
    model.title = document.title
    model.description = document.description
    model.content_type = document.content_type.value
    model.visibility = document.visibility.value
    model.status = document.status.value
    model.metadata_ = dict(document.metadata)
    model.updated_at = document.updated_at
    model.archived_at = document.archived_at
    model.deleted_at = document.deleted_at

# Knowledge Document Version
def version_to_domain(model: KnowledgeDocumentVersionModel) -> KnowledgeDocumentVersion:
    return KnowledgeDocumentVersion(
        id=model.id,
        document_id=model.document_id,
        version_number=model.version_number,
        source_type=KnowledgeSourceType(model.source_type),
        source_content=model.source_content,
        content_hash=model.content_hash,
        status=KnowledgeVersionStatus(model.status),
        ingestion_status=KnowledgeIngestionStatus(model.ingestion_status),
        source_name=model.source_name,
        source_uri=model.source_uri,
        metadata=model.metadata_,
        created_at=model.created_at,
        updated_at=model.updated_at,
        processing_started_at=model.processing_started_at,
        processing_completed_at=model.processing_completed_at,
        ready_at=model.ready_at,
        published_at=model.published_at,
        superseded_at=model.superseded_at,
        archived_at=model.archived_at,
        failure_code=model.failure_code,
        failure_message=model.failure_message,
    )

def version_to_model(version: KnowledgeDocumentVersion) -> KnowledgeDocumentVersionModel:
    return KnowledgeDocumentVersionModel(
        id=version.id,
        document_id=version.document_id,
        version_number=version.version_number,
        source_type=version.source_type.value,
        source_content=version.source_content,
        content_hash=version.content_hash,
        status=version.status.value,
        ingestion_status=version.ingestion_status.value,
        source_name=version.source_name,
        source_uri=version.source_uri,
        metadata_=dict(version.metadata),
        created_at=version.created_at,
        updated_at=version.updated_at,
        processing_started_at=version.processing_started_at,
        processing_completed_at=version.processing_completed_at,
        ready_at=version.ready_at,
        published_at=version.published_at,
        superseded_at=version.superseded_at,
        archived_at=version.archived_at,
        failure_code=version.failure_code,
        failure_message=version.failure_message,
    )

def update_version_model(model: KnowledgeDocumentVersionModel, version: KnowledgeDocumentVersion) -> None:
    """
    Update lifecycle/mutable state without changing version identity or
    immutable source data.
    """
    model.status = version.status.value
    model.ingestion_status = version.ingestion_status.value
    model.source_name = version.source_name
    model.source_uri = version.source_uri
    model.metadata_ = dict(version.metadata)

    model.updated_at = version.updated_at
    model.processing_started_at = version.processing_started_at
    model.processing_completed_at = version.processing_completed_at
    model.ready_at = version.ready_at
    model.published_at = version.published_at
    model.superseded_at = version.superseded_at
    model.archived_at = version.archived_at

    model.failure_code = version.failure_code
    model.failure_message = version.failure_message

# Knowledge Chunk
def chunk_to_domain(model: KnowledgeChunkModel) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=model.id,
        version_id=model.version_id,
        chunk_index=model.chunk_index,
        content=model.content,
        section_title=model.section_title,
        start_offset=model.start_offset,
        end_offset=model.end_offset,
        token_count=model.token_count,
        metadata=model.metadata_,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )

def chunk_to_model(chunk: KnowledgeChunk) -> KnowledgeChunkModel:
    return KnowledgeChunkModel(
        id=chunk.id,
        version_id=chunk.version_id,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        section_title=chunk.section_title,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
        token_count=chunk.token_count,
        metadata_=dict(chunk.metadata),
        created_at=chunk.created_at,
        updated_at=chunk.updated_at,
    )