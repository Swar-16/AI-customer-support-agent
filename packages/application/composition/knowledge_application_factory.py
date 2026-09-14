# AI-customer-support-agent\packages\application\composition\knowledge_application_factory.py
from __future__ import annotations
from dataclasses import dataclass

from packages.application.composition.knowledge_ingestion_factory import KnowledgeIngestionComponents, create_knowledge_ingestion_components
from packages.application.knowledge.ai_request_factory import AIKnowledgeRetrievalRequestFactory
from packages.application.knowledge.retrieval_context_factory import KnowledgeRetrievalContextFactory
from packages.application.knowledge.retrieval_context_service import KnowledgeRetrievalContextService
from packages.knowledge.application.archive_document import ArchiveKnowledgeDocument
from packages.knowledge.application.create_document import CreateKnowledgeDocument
from packages.knowledge.application.create_version import CreateKnowledgeVersion
from packages.knowledge.application.embed_version import EmbedKnowledgeVersion
from packages.knowledge.application.get_document import GetKnowledgeDocument
from packages.knowledge.application.get_version import GetKnowledgeVersion
from packages.knowledge.application.list_documents import ListKnowledgeDocuments
from packages.knowledge.application.list_versions import ListKnowledgeVersions
from packages.knowledge.application.process_version import ProcessKnowledgeVersion
from packages.knowledge.application.publish_version import PublishKnowledgeVersion
from packages.knowledge.application.knowledge_upload_policy import KnowledgeUploadPolicy
from packages.knowledge.application.upload_document import UploadKnowledgeDocument
from packages.knowledge.application.upload_version import UploadKnowledgeVersion
from packages.knowledge.embeddings import EmbeddingInputBuilder, EmbeddingProvider
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory

@dataclass(frozen=True, slots=True)
class KnowledgeApplicationComponents:
    """
    Complete application-layer knowledge subsystem.

    Query services expose administrative catalog information.

    Mutation services coordinate document/version lifecycle operations, ingestion, embedding, publication and archival.

    RetrievalContextService bridges AI-understood customer requests into the retrieval subsystem; it does not mutate knowledge.
    """
    retrieval_context_service: KnowledgeRetrievalContextService

    list_documents: ListKnowledgeDocuments
    get_document: GetKnowledgeDocument
    list_versions: ListKnowledgeVersions
    get_version: GetKnowledgeVersion

    create_document: CreateKnowledgeDocument
    create_version: CreateKnowledgeVersion
    process_version: ProcessKnowledgeVersion
    embed_version: EmbedKnowledgeVersion
    publish_version: PublishKnowledgeVersion
    archive_document: ArchiveKnowledgeDocument
    
    upload_document: UploadKnowledgeDocument
    upload_version: UploadKnowledgeVersion

    ingestion: KnowledgeIngestionComponents

def create_knowledge_application_components(*, uow_factory: KnowledgeUnitOfWorkFactory, embedding_provider: EmbeddingProvider, 
                                            embedding_input_builder: EmbeddingInputBuilder, embedding_batch_size: int, knowledge_upload_max_bytes: int,
                                            ingestion: KnowledgeIngestionComponents | None = None,
                                            ai_request_factory: AIKnowledgeRetrievalRequestFactory | None = None,
                                            retrieval_context_factory: KnowledgeRetrievalContextFactory | None = None
) -> KnowledgeApplicationComponents:
    """
    Compose the complete knowledge application boundary.

    Provider instances and the UoW factory are supplied by the root composition layer so this module
    remains independent from environment variables and concrete database-session construction.
    """
    _validate_inputs(
        uow_factory=uow_factory,
        embedding_provider=embedding_provider,
        embedding_input_builder=embedding_input_builder,
        embedding_batch_size=embedding_batch_size,
        ingestion=ingestion,
        ai_request_factory=ai_request_factory,
        retrieval_context_factory=retrieval_context_factory,
    )
    
    upload_policy = KnowledgeUploadPolicy(max_upload_bytes=knowledge_upload_max_bytes)
    upload_document = UploadKnowledgeDocument(uow_factory=uow_factory, upload_policy=upload_policy)
    upload_version = UploadKnowledgeVersion(uow_factory=uow_factory, upload_policy=upload_policy)

    effective_ingestion = ingestion if ingestion is not None else create_knowledge_ingestion_components()
    effective_ai_request_factory = ai_request_factory if ai_request_factory is not None else AIKnowledgeRetrievalRequestFactory()
    effective_retrieval_context_factory = retrieval_context_factory if retrieval_context_factory is not None else KnowledgeRetrievalContextFactory()
    retrieval_context_service = KnowledgeRetrievalContextService(
        ai_request_factory=effective_ai_request_factory,
        context_factory=effective_retrieval_context_factory,
    )

    return KnowledgeApplicationComponents(
        retrieval_context_service=retrieval_context_service,

        list_documents=ListKnowledgeDocuments(uow_factory=uow_factory),
        get_document=GetKnowledgeDocument(uow_factory=uow_factory),
        list_versions=ListKnowledgeVersions(uow_factory=uow_factory),
        get_version=GetKnowledgeVersion(uow_factory=uow_factory),

        create_document=CreateKnowledgeDocument(uow_factory=uow_factory),
        create_version=CreateKnowledgeVersion(uow_factory=uow_factory),
        process_version=ProcessKnowledgeVersion(
            uow_factory=uow_factory,
            parser_resolver=effective_ingestion.parser_resolver,
            normalizer_resolver=effective_ingestion.normalizer_resolver,
            chunker_resolver=effective_ingestion.chunker_resolver,
        ),
        embed_version=EmbedKnowledgeVersion(
            uow_factory=uow_factory,
            provider=embedding_provider,
            input_builder=embedding_input_builder,
            batch_size=embedding_batch_size,
        ),
        publish_version=PublishKnowledgeVersion(uow_factory=uow_factory),
        archive_document=ArchiveKnowledgeDocument(uow_factory=uow_factory),
        
        upload_document=upload_document,
        upload_version=upload_version,

        ingestion=effective_ingestion,
    )

def _validate_inputs(*, uow_factory: KnowledgeUnitOfWorkFactory, embedding_provider: EmbeddingProvider, 
                     embedding_input_builder: EmbeddingInputBuilder, embedding_batch_size: int,
                     ingestion: KnowledgeIngestionComponents | None, ai_request_factory: AIKnowledgeRetrievalRequestFactory | None,
                     retrieval_context_factory: KnowledgeRetrievalContextFactory | None,
) -> None:
    if not callable(uow_factory):
        raise TypeError("uow_factory must be callable.")

    if not isinstance(embedding_provider, EmbeddingProvider):
        raise TypeError("embedding_provider must satisfy the EmbeddingProvider contract.")

    if not isinstance(embedding_input_builder, EmbeddingInputBuilder):
        raise TypeError("embedding_input_builder must satisfy the EmbeddingInputBuilder contract.")

    if isinstance(embedding_batch_size, bool) or not isinstance(embedding_batch_size, int):
        raise TypeError("embedding_batch_size must be an integer.")

    if embedding_batch_size <= 0:
        raise ValueError("embedding_batch_size must be greater than zero.")

    if ingestion is not None and not isinstance(ingestion, KnowledgeIngestionComponents):
        raise TypeError("ingestion must be a KnowledgeIngestionComponents instance or None.")

    if ai_request_factory is not None and not isinstance(ai_request_factory, AIKnowledgeRetrievalRequestFactory):
        raise TypeError("ai_request_factory must be an AIKnowledgeRetrievalRequestFactory instance or None.")

    if retrieval_context_factory is not None and not isinstance(retrieval_context_factory, KnowledgeRetrievalContextFactory):
        raise TypeError("retrieval_context_factory must be a KnowledgeRetrievalContextFactory instance or None.")