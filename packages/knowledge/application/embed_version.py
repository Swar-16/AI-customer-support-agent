from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID
from uuid6 import uuid7

from packages.knowledge.domain.chunk import KnowledgeChunk
from packages.knowledge.domain.embedding import KnowledgeChunkEmbedding
from packages.knowledge.domain.enums import KnowledgeIngestionStatus, KnowledgeVersionStatus
from packages.knowledge.embeddings.errors import EmbeddingArtifactConflictError, EmbeddingBatchConfigurationError, EmbeddingProviderIdentityMismatchError
from packages.knowledge.embeddings.errors import EmbeddingResponseCardinalityError, EmbeddingResponseOrderingError, EmbeddingVersionError
from packages.knowledge.embeddings.errors import EmbeddingVersionHasNoChunksError, EmbeddingVersionNotFoundError, EmbeddingVersionNotReadyError
from packages.knowledge.embeddings.models import EmbeddingInputDescriptor, EmbeddingProviderDescriptor, PreparedEmbeddingInput
from packages.knowledge.embeddings import EmbeddingInputBuilder, EmbeddingProvider
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory


# Public contracts
@dataclass(frozen=True, slots=True)
class EmbedKnowledgeVersionCommand:
    """
    Request creation of embedding artifacts for one canonical knowledge document version.

    The operation is intentionally idempotent:

        same chunk
        + same exact prepared input
        + same input strategy
        + same provider/model/revision
        = same logical embedding artifact
    """
    version_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.version_id, UUID):
            raise TypeError("version_id must be a UUID.")

@dataclass(frozen=True, slots=True)
class EmbedKnowledgeVersionResult:
    """
    Summary of one embedding execution.

    existing_count:
        Artifacts already present before this execution.

    created_count:
        New artifacts produced and persisted by this execution.

    total_chunks:
        Number of canonical chunks belonging to the version.
    """
    version_id: UUID
    document_id: UUID
    total_chunks: int
    existing_count: int
    created_count: int
    provider_identity: str
    input_strategy_identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.version_id, UUID):
            raise TypeError("version_id must be a UUID.")

        if not isinstance(self.document_id, UUID):
            raise TypeError("document_id must be a UUID.")

        for field_name, value in (
            ("total_chunks", self.total_chunks),
            ("existing_count", self.existing_count),
            ("created_count", self.created_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer.")

            if value < 0:
                raise ValueError(f"{field_name} must not be negative.")

        if self.total_chunks <= 0:
            raise ValueError("total_chunks must be greater than zero.")

        if self.existing_count + self.created_count != self.total_chunks:
            raise ValueError("existing_count + created_count must equal total_chunks.")

        if not self.provider_identity.strip():
            raise ValueError("provider_identity must not be blank.")

        if not self.input_strategy_identity.strip():
            raise ValueError("input_strategy_identity must not be blank.")

# Internal immutable snapshots
@dataclass(frozen=True, slots=True)
class _EmbeddingVersionSnapshot:
    """
    Immutable data needed after the read transaction has closed.

    No SQLAlchemy model or live Session escapes the transaction.
    """
    version_id: UUID
    document_id: UUID
    document_title: str
    chunks: tuple[KnowledgeChunk, ...]

@dataclass(frozen=True, slots=True)
class _PreparedWorkItem:
    """
    Connect one canonical chunk to the exact model-facing representation produced by the configured embedding-input strategy.
    """
    chunk: KnowledgeChunk
    prepared_input: PreparedEmbeddingInput

    def __post_init__(self) -> None:
        if self.chunk.id != self.prepared_input.chunk_id:
            raise ValueError("Prepared embedding input belongs to a different chunk.")


# Application service
class EmbedKnowledgeVersion:
    """
    Generate model-dependent embedding artifacts for one processed knowledge document version.

    High-level execution:

        Transaction A
        --------------
        read version
        validate canonical ingestion state
        read document
        read canonical chunks
        snapshot immutable data
        close transaction

                ↓

        No DB transaction
        ------------------
        build exact embedding inputs
        inspect existing artifacts
        embed only missing inputs

                ↓

        Transaction B
        --------------
        re-check existing artifacts
        persist still-missing immutable embeddings
        commit

    Important properties:

    - external embedding calls never run while a DB transaction is open;
    - existing valid embeddings are reused;
    - exact input fingerprints protect against stale embeddings;
    - provider/model/input-strategy provenance is preserved;
    - repeated execution is idempotent at the application level;
    - embedding does not mutate KnowledgeDocumentVersion lifecycle state.
    """
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory, provider: EmbeddingProvider, input_builder: EmbeddingInputBuilder, batch_size: int = 32) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        if not isinstance(provider, EmbeddingProvider):
            raise TypeError("provider must satisfy the EmbeddingProvider contract.")

        if not isinstance(input_builder, EmbeddingInputBuilder):
            raise TypeError("input_builder must satisfy the EmbeddingInputBuilder contract.")

        if isinstance(batch_size, bool) or not isinstance(batch_size, int):
            raise TypeError("batch_size must be an integer.")

        if batch_size <= 0:
            raise EmbeddingBatchConfigurationError("batch_size must be greater than zero.", batch_size=batch_size)

        self._uow_factory = uow_factory
        self._provider = provider
        self._input_builder = input_builder
        self._batch_size = batch_size

    # Public API
    def execute(self, command: EmbedKnowledgeVersionCommand) -> EmbedKnowledgeVersionResult:
        if not isinstance(command, EmbedKnowledgeVersionCommand):
            raise TypeError("command must be an EmbedKnowledgeVersionCommand.")

        provider_descriptor = self._provider.descriptor
        input_descriptor = self._input_builder.descriptor
        self._validate_descriptors(provider_descriptor=provider_descriptor, input_descriptor=input_descriptor)
        snapshot = self._load_snapshot(command.version_id)
        prepared_items = self._prepare_inputs(snapshot)
        existing_keys = self._load_existing_keys(
            prepared_items=prepared_items,
            provider_descriptor=provider_descriptor,
            input_descriptor=input_descriptor,
        )

        missing_items = [
            item for item in prepared_items
            if self._artifact_key(chunk_id=item.chunk.id, input_fingerprint=item.prepared_input.input_fingerprint)
            not in existing_keys
        ]

        # Fast idempotent path: everything already exists.
        if not missing_items:
            return EmbedKnowledgeVersionResult(
                version_id=snapshot.version_id,
                document_id=snapshot.document_id,
                total_chunks=len(prepared_items),
                existing_count=len(prepared_items),
                created_count=0,
                provider_identity=provider_descriptor.identity,
                input_strategy_identity=input_descriptor.identity,
            )

        generated = self._generate_embeddings(
            items=missing_items,
            expected_provider=provider_descriptor,
            input_descriptor=input_descriptor,
        )

        created_count = self._persist_generated(
            version_id=snapshot.version_id,
            generated=generated,
            provider_descriptor=provider_descriptor,
            input_descriptor=input_descriptor,
        )

        # Some artifacts may have appeared concurrently between our initial read and persistence re-check.
        existing_count = len(prepared_items) - created_count
        return EmbedKnowledgeVersionResult(
            version_id=snapshot.version_id,
            document_id=snapshot.document_id,
            total_chunks=len(prepared_items),
            existing_count=existing_count,
            created_count=created_count,
            provider_identity=provider_descriptor.identity,
            input_strategy_identity=input_descriptor.identity,
        )

    # Phase A: snapshot canonical state
    def _load_snapshot(self, version_id: UUID) -> _EmbeddingVersionSnapshot:
        with self._uow_factory() as uow:
            version = uow.versions.get_by_id(version_id)
            if version is None:
                raise EmbeddingVersionNotFoundError(version_id=version_id)

            self._ensure_version_embeddable(version)
            document = uow.documents.get_by_id(version.document_id)
            if document is None:
                # This should normally be impossible because of FK integrity. 
                # Treat it as corrupted/inconsistent application state rather than pretending the version itself does not exist.
                raise EmbeddingVersionError(
                    "Parent knowledge document does not exist.",
                    code="embedding_document_not_found",
                    version_id=version.id,
                    document_id=version.document_id,
                )

            chunks = uow.chunks.list_for_version(version.id)
            if not chunks:
                raise EmbeddingVersionHasNoChunksError(version_id=version.id)

            self._validate_chunk_snapshot(version_id=version.id, chunks=chunks)

            return _EmbeddingVersionSnapshot(
                version_id=version.id,
                document_id=version.document_id,
                document_title=document.title,
                chunks=tuple(chunks),
            )

    # Input preparation
    def _prepare_inputs(self, snapshot: _EmbeddingVersionSnapshot) -> tuple[_PreparedWorkItem, ...]:
        items: list[_PreparedWorkItem] = []
        for chunk in snapshot.chunks:
            prepared = self._input_builder.build(chunk=chunk, document_title=snapshot.document_title)
            if prepared.chunk_id != chunk.id:
                raise EmbeddingArtifactConflictError(
                    "Embedding input builder returned an input for a different chunk.",
                    version_id=snapshot.version_id,
                    chunk_id=chunk.id,
                    prepared_chunk_id=prepared.chunk_id,
                )

            items.append(_PreparedWorkItem(chunk=chunk, prepared_input=prepared))

        if len(items) != len(snapshot.chunks):
            raise EmbeddingArtifactConflictError(
                "Embedding input preparation changed chunk cardinality.",
                version_id=snapshot.version_id,
                expected_count=len(snapshot.chunks),
                actual_count=len(items),
            )

        return tuple(items)

    # Existing-artifact detection
    def _load_existing_keys(self, *, prepared_items: Sequence[_PreparedWorkItem], 
                            provider_descriptor: EmbeddingProviderDescriptor, input_descriptor: EmbeddingInputDescriptor
    ) -> set[tuple[UUID, str]]:
        chunk_ids = [item.chunk.id for item in prepared_items]
        with self._uow_factory() as uow:
            existing = uow.embeddings.list_for_chunks(
                chunk_ids,
                provider=provider_descriptor,
                input_descriptor=input_descriptor,
            )

        result: set[tuple[UUID, str]] = set()
        for artifact in existing:
            key = self._artifact_key(chunk_id=artifact.chunk_id, input_fingerprint=artifact.input_fingerprint)
            if key in result:
                raise EmbeddingArtifactConflictError(
                    "Multiple persisted embedding artifacts represent the same logical artifact.",
                    chunk_id=artifact.chunk_id,
                    provider=provider_descriptor.provider,
                    model=provider_descriptor.model,
                    input_fingerprint=artifact.input_fingerprint,
                )

            result.add(key)

        return result

    # Provider execution
    def _generate_embeddings(self, *, items: Sequence[_PreparedWorkItem],
                             expected_provider: EmbeddingProviderDescriptor, input_descriptor: EmbeddingInputDescriptor
    ) -> tuple[KnowledgeChunkEmbedding, ...]:
        generated: list[KnowledgeChunkEmbedding] = []
        for batch_start in range(0, len(items), self._batch_size):
            batch_items = items[batch_start:batch_start + self._batch_size]
            texts = [item.prepared_input.text for item in batch_items]
            # Provider adapters own HTTP/SDK exception translation.
            batch = self._provider.embed_documents(texts)
            self._validate_provider_response(
                batch=batch,
                expected_provider=expected_provider,
                expected_count=len(batch_items),
            )

            ordered_embeddings = batch.ordered()
            for expected_index, (item, document_embedding,) in enumerate(zip(batch_items, ordered_embeddings, strict=True)):
                if document_embedding.input_index != expected_index:
                    raise EmbeddingResponseOrderingError(
                        "Embedding provider response indexes are not contiguous for the request batch.",
                        provider=expected_provider.provider,
                        model=expected_provider.model,
                        expected_index=expected_index,
                        actual_index=document_embedding.input_index,
                    )

                generated.append(
                    KnowledgeChunkEmbedding(
                        id=uuid7(),
                        chunk_id=item.chunk.id,
                        provider=expected_provider,
                        input_descriptor=input_descriptor,
                        input_fingerprint=item.prepared_input.input_fingerprint,
                        vector=document_embedding.vector,
                    )
                )

        if len(generated) != len(items):
            raise EmbeddingResponseCardinalityError(
                expected_count=len(items),
                actual_count=len(generated),
                provider=expected_provider.provider,
                model=expected_provider.model,
            )

        return tuple(generated)

    # Phase B: persistence
    def _persist_generated(self, *, version_id: UUID, generated: Sequence[KnowledgeChunkEmbedding],
                           provider_descriptor: EmbeddingProviderDescriptor, input_descriptor: EmbeddingInputDescriptor
    ) -> int:
        if not generated:
            return 0

        chunk_ids = [artifact.chunk_id for artifact in generated]
        with self._uow_factory() as uow:
            # Re-read version before writing.

            # We do not want to persist embeddings against a version that became invalid while the external provider call was running.
            version = uow.versions.get_by_id(version_id)
            if version is None:
                raise EmbeddingVersionNotFoundError(version_id=version_id)

            self._ensure_version_embeddable(version)
            # Re-read existing artifacts because another worker may have embedded the same chunks while we were calling the provider.
            existing = uow.embeddings.list_for_chunks(
                chunk_ids,
                provider=provider_descriptor,
                input_descriptor=input_descriptor,
            )

            existing_keys = {
                self._artifact_key(
                    chunk_id=artifact.chunk_id,
                    input_fingerprint=artifact.input_fingerprint,
                ) for artifact in existing
            }

            to_persist = [artifact for artifact in generated if self._artifact_key(
                chunk_id=artifact.chunk_id,
                input_fingerprint=artifact.input_fingerprint) not in existing_keys
            ]

            if not to_persist:
                return 0

            created_count = uow.embeddings.add_many_if_absent(list(to_persist))

            # Force PostgreSQL to validate:
            # - chunk FK,
            # - dimensions constraint,
            # - exact-artifact uniqueness,
            # before commit.
            uow.flush()
            uow.commit()

            return created_count


    # Validation helpers
    @staticmethod
    def _ensure_version_embeddable(version) -> None:
        """
        Embedding depends on completed canonical ingestion, not publication.

        READY:
            normal pre-publication embedding path.

        PUBLISHED:
            permits re-embedding with a newer model/input strategy without mutating the canonical version.

        SUPERSEDED:
            permits rebuilding historical retrieval artifacts for reproducibility/audit purposes.

        DRAFT / PROCESSING / FAILED / ARCHIVED:
            not valid embedding sources.
        """
        allowed_statuses = {
            KnowledgeVersionStatus.READY,
            KnowledgeVersionStatus.PUBLISHED,
            KnowledgeVersionStatus.SUPERSEDED,
        }

        if version.status not in allowed_statuses or version.ingestion_status is not KnowledgeIngestionStatus.COMPLETED:
            raise EmbeddingVersionNotReadyError(
                version_id=version.id,
                version_status=version.status.value,
                ingestion_status=version.ingestion_status.value,
            )

    @staticmethod
    def _validate_chunk_snapshot(*, version_id: UUID, chunks: Sequence[KnowledgeChunk]) -> None:
        seen_ids: set[UUID] = set()
        seen_indexes: set[int] = set()
        expected_index = 0
        for chunk in chunks:
            if chunk.version_id != version_id:
                raise EmbeddingArtifactConflictError(
                    "Chunk repository returned a chunk belonging to a different knowledge version.",
                    version_id=version_id,
                    chunk_id=chunk.id,
                    actual_version_id=chunk.version_id,
                )

            if chunk.id in seen_ids:
                raise EmbeddingArtifactConflictError("Chunk repository returned duplicate chunk IDs.", version_id=version_id, chunk_id=chunk.id)

            if chunk.chunk_index in seen_indexes:
                raise EmbeddingArtifactConflictError(
                    "Chunk repository returned duplicate chunk indexes.",
                    version_id=version_id,
                    chunk_id=chunk.id,
                    chunk_index=chunk.chunk_index,
                )

            if chunk.chunk_index != expected_index:
                raise EmbeddingArtifactConflictError(
                    "Knowledge chunks must be contiguous and zero-based before embedding.",
                    version_id=version_id,
                    chunk_id=chunk.id,
                    expected_chunk_index=expected_index,
                    actual_chunk_index=chunk.chunk_index,
                )

            seen_ids.add(chunk.id)
            seen_indexes.add(chunk.chunk_index)
            expected_index += 1

    @staticmethod
    def _validate_descriptors(*, provider_descriptor: EmbeddingProviderDescriptor, input_descriptor: EmbeddingInputDescriptor) -> None:
        if not isinstance(provider_descriptor, EmbeddingProviderDescriptor):
            raise TypeError("Embedding provider descriptor must be an EmbeddingProviderDescriptor.")

        if not isinstance(input_descriptor, EmbeddingInputDescriptor):
            raise TypeError("Embedding input builder descriptor must be an EmbeddingInputDescriptor.")

    @staticmethod
    def _validate_provider_response(*, batch, expected_provider: EmbeddingProviderDescriptor, expected_count: int) -> None:
        if batch.provider != expected_provider:
            raise EmbeddingProviderIdentityMismatchError(
                expected_provider=expected_provider.provider,
                expected_model=expected_provider.model,
                actual_provider=batch.provider.provider,
                actual_model=batch.provider.model,
            )

        if batch.size != expected_count:
            raise EmbeddingResponseCardinalityError(
                expected_count=expected_count,
                actual_count=batch.size,
                provider=expected_provider.provider,
                model=expected_provider.model,
            )

        indexes = {embedding.input_index for embedding in batch.embeddings}
        expected_indexes = set(range(expected_count)
        )

        if indexes != expected_indexes:
            raise EmbeddingResponseOrderingError(
                "Embedding provider response indexes do not match the request batch.",
                provider=expected_provider.provider,
                model=expected_provider.model,
                expected_indexes=sorted(expected_indexes),
                actual_indexes=sorted(indexes),
            )

    @staticmethod
    def _artifact_key(*, chunk_id: UUID, input_fingerprint: str) -> tuple[UUID, str]:
        return (chunk_id, input_fingerprint,)