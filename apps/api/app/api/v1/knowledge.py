# AI-customer-support-agent\apps\api\app\api\v1\knowledge.py
from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Path, Query, status

from apps.api.app.api.dependencies import AdminPrincipalDependency, ApplicationServicesDependency, TraceIdDependency
from apps.api.app.api.schemas.errors import APIErrorResponse
from apps.api.app.api.v1.schemas.knowledge import ArchiveKnowledgeDocumentResponse, CreateKnowledgeDocumentRequest, CreateKnowledgeDocumentResponse
from apps.api.app.api.v1.schemas.knowledge import CreateKnowledgeVersionRequest, CreateKnowledgeVersionResponse, EmbedKnowledgeVersionResponse
from apps.api.app.api.v1.schemas.knowledge import KnowledgeDocumentDetailResponse, KnowledgeDocumentListResponse, KnowledgeVersionDetailResponse
from apps.api.app.api.v1.schemas.knowledge import KnowledgeVersionListResponse, ProcessKnowledgeVersionResponse, PublishKnowledgeVersionResponse
from packages.knowledge.application.archive_document import ArchiveKnowledgeDocumentCommand
from packages.knowledge.application.create_document import CreateKnowledgeDocumentCommand
from packages.knowledge.application.create_version import CreateKnowledgeVersionCommand
from packages.knowledge.application.embed_version import EmbedKnowledgeVersionCommand
from packages.knowledge.application.get_document import GetKnowledgeDocumentQuery
from packages.knowledge.application.get_version import GetKnowledgeVersionQuery
from packages.knowledge.application.list_documents import ListKnowledgeDocumentsQuery
from packages.knowledge.application.list_versions import ListKnowledgeVersionsQuery
from packages.knowledge.application.mutation_context import KnowledgeMutationContext
from packages.knowledge.application.process_version import ProcessKnowledgeVersionCommand
from packages.knowledge.application.publish_version import PublishKnowledgeVersionCommand
from packages.knowledge.domain.enums import KnowledgeContentType, KnowledgeDocumentStatus, KnowledgeIngestionStatus
from packages.knowledge.domain.enums import KnowledgeSourceType, KnowledgeVersionStatus, KnowledgeVisibility

router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
)

_COMMON_RESPONSES = {
    401: {
        "model": APIErrorResponse,
        "description": "Authentication required",
    },
    403: {
        "model": APIErrorResponse,
        "description": "Administrator access required",
    },
    422: {
        "model": APIErrorResponse,
        "description": "Request validation failed",
    },
    500: {
        "model": APIErrorResponse,
        "description": "Unexpected internal failure",
    },
}

_RESOURCE_RESPONSES = {
    **_COMMON_RESPONSES,
    404: {
        "model": APIErrorResponse,
        "description": "Knowledge resource not found",
    },
}

_MUTATION_RESPONSES = {
    **_RESOURCE_RESPONSES,
    409: {
        "model": APIErrorResponse,
        "description": "Knowledge resource lifecycle conflict",
    },
}


# Document queries
@router.get(
    "/documents",
    response_model=KnowledgeDocumentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List knowledge documents",
    responses=_COMMON_RESPONSES,
)
def list_knowledge_documents(services: ApplicationServicesDependency, principal: AdminPrincipalDependency,
                             document_status: KnowledgeDocumentStatus | None = Query(default=None, alias="status"),
                             content_type: KnowledgeContentType | None = Query(default=None),
                             visibility: KnowledgeVisibility | None = Query(default=None),
                             limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)
) -> KnowledgeDocumentListResponse:
    result = services.list_knowledge_documents.execute(
        ListKnowledgeDocumentsQuery(
            principal=principal,
            status=document_status,
            content_type=content_type,
            visibility=visibility,
            limit=limit,
            offset=offset,
        )
    )

    return KnowledgeDocumentListResponse.from_application(result)

@router.get(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a knowledge document",
    responses=_RESOURCE_RESPONSES,
)
def get_knowledge_document(services: ApplicationServicesDependency, principal: AdminPrincipalDependency,
                           document_id: UUID = Path(...)
) -> KnowledgeDocumentDetailResponse:
    result = services.get_knowledge_document.execute(GetKnowledgeDocumentQuery(principal=principal, document_id=document_id))

    return KnowledgeDocumentDetailResponse.from_application(result)

# Version queries
@router.get(
    "/documents/{document_id}/versions",
    response_model=KnowledgeVersionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List knowledge document versions",
    responses=_RESOURCE_RESPONSES,
)
def list_knowledge_versions(services: ApplicationServicesDependency, principal: AdminPrincipalDependency, document_id: UUID = Path(...),
                            version_status: KnowledgeVersionStatus | None = Query(default=None, alias="status"),
                            ingestion_status: KnowledgeIngestionStatus | None = Query(default=None),
                            source_type: KnowledgeSourceType | None = Query(default=None),
                            limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)
) -> KnowledgeVersionListResponse:
    result = services.list_knowledge_versions.execute(
        ListKnowledgeVersionsQuery(
            principal=principal,
            document_id=document_id,
            status=version_status,
            ingestion_status=ingestion_status,
            source_type=source_type,
            limit=limit,
            offset=offset,
        )
    )

    return KnowledgeVersionListResponse.from_application(result)


@router.get(
    "/versions/{version_id}",
    response_model=KnowledgeVersionDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a knowledge version",
    responses=_RESOURCE_RESPONSES,
)
def get_knowledge_version(services: ApplicationServicesDependency, principal: AdminPrincipalDependency, version_id: UUID = Path(...)
) -> KnowledgeVersionDetailResponse:
    result = services.get_knowledge_version.execute(GetKnowledgeVersionQuery(principal=principal, version_id=version_id))

    return KnowledgeVersionDetailResponse.from_application(result)


# Document and version creation
@router.post(
    "/documents",
    response_model=CreateKnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a knowledge document",
    responses=_COMMON_RESPONSES,
)
def create_knowledge_document(payload: CreateKnowledgeDocumentRequest, services: ApplicationServicesDependency, 
                              principal: AdminPrincipalDependency, trace_id: TraceIdDependency
) -> CreateKnowledgeDocumentResponse:
    context = KnowledgeMutationContext.from_admin(principal=principal, trace_id=trace_id)
    result = services.create_knowledge_document.execute(
        CreateKnowledgeDocumentCommand(
            context=context,
            title=payload.title,
            description=payload.description,
            content_type=payload.content_type,
            visibility=payload.visibility,
            metadata={},
        )
    )

    return CreateKnowledgeDocumentResponse(document_id=result.document_id, created_at=result.created_at)

@router.post(
    "/documents/{document_id}/versions",
    response_model=CreateKnowledgeVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a knowledge document version",
    responses=_MUTATION_RESPONSES,
)
def create_knowledge_version(payload: CreateKnowledgeVersionRequest, services: ApplicationServicesDependency, 
                             principal: AdminPrincipalDependency, trace_id: TraceIdDependency, document_id: UUID = Path(...)
) -> CreateKnowledgeVersionResponse:
    context = KnowledgeMutationContext.from_admin(principal=principal, trace_id=trace_id)
    result = services.create_knowledge_version.execute(
        CreateKnowledgeVersionCommand(
            context=context,
            document_id=document_id,
            source_type=payload.source_type,
            source_content=payload.source_content,
            source_name=payload.source_name,
            source_uri=None,
            metadata={},
        )
    )

    return CreateKnowledgeVersionResponse(
        version_id=result.version_id,
        document_id=result.document_id,
        version_number=result.version_number,
        content_hash=result.content_hash,
        created_at=result.created_at,
    )


# Version lifecycle
@router.post(
    "/versions/{version_id}/process",
    response_model=ProcessKnowledgeVersionResponse,
    status_code=status.HTTP_200_OK,
    summary="Process a knowledge version",
    responses=_MUTATION_RESPONSES,
)
def process_knowledge_version(services: ApplicationServicesDependency, principal: AdminPrincipalDependency, 
                              trace_id: TraceIdDependency, version_id: UUID = Path(...)
) -> ProcessKnowledgeVersionResponse:
    context = KnowledgeMutationContext.from_admin(principal=principal, trace_id=trace_id)
    result = services.process_knowledge_version.execute(ProcessKnowledgeVersionCommand(context=context, version_id=version_id))

    return ProcessKnowledgeVersionResponse(
        version_id=result.version_id,
        document_id=result.document_id,
        chunk_count=result.chunk_count,
        parser_identity=result.parser_identity,
        normalizer_identity=result.normalizer_identity,
        chunker_identity=result.chunker_identity,
        version_status=result.version_status,
        ingestion_status=result.ingestion_status,
    )

@router.post(
    "/versions/{version_id}/embed",
    response_model=EmbedKnowledgeVersionResponse,
    status_code=status.HTTP_200_OK,
    summary="Embed a knowledge version",
    responses=_MUTATION_RESPONSES,
)
def embed_knowledge_version(services: ApplicationServicesDependency, principal: AdminPrincipalDependency,
                            trace_id: TraceIdDependency, version_id: UUID = Path(...),
) -> EmbedKnowledgeVersionResponse:
    context = KnowledgeMutationContext.from_admin(principal=principal, trace_id=trace_id)
    result = services.embed_knowledge_version.execute(EmbedKnowledgeVersionCommand(context=context, version_id=version_id))

    return EmbedKnowledgeVersionResponse(
        version_id=result.version_id,
        document_id=result.document_id,
        total_chunks=result.total_chunks,
        existing_count=result.existing_count,
        created_count=result.created_count,
        provider_identity=result.provider_identity,
        input_strategy_identity=result.input_strategy_identity,
    )

@router.post(
    "/versions/{version_id}/publish",
    response_model=PublishKnowledgeVersionResponse,
    status_code=status.HTTP_200_OK,
    summary="Publish a knowledge version",
    responses=_MUTATION_RESPONSES,
)
def publish_knowledge_version(services: ApplicationServicesDependency, principal: AdminPrincipalDependency, 
                              trace_id: TraceIdDependency, version_id: UUID = Path(...)
) -> PublishKnowledgeVersionResponse:
    context = KnowledgeMutationContext.from_admin(principal=principal, trace_id=trace_id)
    result = services.publish_knowledge_version.execute(PublishKnowledgeVersionCommand(context=context, version_id=version_id))

    return PublishKnowledgeVersionResponse(
        version_id=result.version_id,
        document_id=result.document_id,
        version_number=result.version_number,
        status=result.status,
        published_at=result.published_at,
        superseded_version_id=result.superseded_version_id,
    )


# Document lifecycle
@router.post(
    "/documents/{document_id}/archive",
    response_model=ArchiveKnowledgeDocumentResponse,
    status_code=status.HTTP_200_OK,
    summary="Archive a knowledge document",
    responses=_MUTATION_RESPONSES,
)
def archive_knowledge_document(services: ApplicationServicesDependency, principal: AdminPrincipalDependency, 
                               trace_id: TraceIdDependency, document_id: UUID = Path(...)
) -> ArchiveKnowledgeDocumentResponse:
    context = KnowledgeMutationContext.from_admin(principal=principal, trace_id=trace_id)
    result = services.archive_knowledge_document.execute(ArchiveKnowledgeDocumentCommand(context=context, document_id=document_id))

    return ArchiveKnowledgeDocumentResponse(
        document_id=result.document_id,
        status=result.status,
        archived_at=result.archived_at,
        superseded_version_id=result.superseded_version_id,
    )