from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from uuid6 import uuid7

from packages.knowledge.domain.chunk import KnowledgeChunk
from packages.knowledge.domain.enums import KnowledgeIngestionStatus, KnowledgeSourceType, KnowledgeVersionStatus
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.ingestion.chunking.base import DocumentChunkerResolver
from packages.knowledge.ingestion.chunking.models import ChunkedDocument
from packages.knowledge.ingestion.models import IngestionSource, ParsedDocument
from packages.knowledge.ingestion.normalization.base import DocumentNormalizerResolver
from packages.knowledge.ingestion.normalization.models import NormalizedDocument
from packages.knowledge.ingestion.parser.base import DocumentParserResolver
from packages.knowledge.uow import KnowledgeUnitOfWork, KnowledgeUnitOfWorkFactory


# Errors
class ProcessKnowledgeVersionError(RuntimeError):
    """
    Base application-layer exception for ProcessKnowledgeVersion.

    These errors represent use-case failures, not HTTP concerns and not persistence-provider-specific failures.
    """

class KnowledgeVersionNotFoundError(ProcessKnowledgeVersionError):
    def __init__(self, version_id: UUID) -> None:
        self.version_id = version_id
        super().__init__(f"Knowledge version '{version_id}' does not exist.")

class KnowledgeVersionNotProcessableError(ProcessKnowledgeVersionError):
    def __init__(self, *, version_id: UUID, version_status: KnowledgeVersionStatus, ingestion_status: KnowledgeIngestionStatus) -> None:
        self.version_id = version_id
        self.version_status = version_status
        self.ingestion_status = ingestion_status
        super().__init__(
            f"Knowledge version '{version_id}' cannot be processed while version_status='{version_status.value}' and ingestion_status='{ingestion_status.value}'."
        )

class KnowledgeVersionProcessingConflictError(ProcessKnowledgeVersionError):
    """
    Raised when the version changed after it was claimed but before this processing attempt could complete.
    """

class KnowledgeProcessingContractError(ProcessKnowledgeVersionError):
    """
    Raised when parser/normalizer/chunker output violates cross-stage application invariants.
    """

class KnowledgeProcessingPersistenceError(ProcessKnowledgeVersionError):
    """
    Raised when persistence fails while completing or recording failure state.
    """

# Command / result
@dataclass(frozen=True, slots=True)
class ProcessKnowledgeVersionCommand:
    version_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.version_id, UUID):
            raise TypeError("version_id must be a UUID.")


@dataclass(frozen=True, slots=True)
class ProcessKnowledgeVersionResult:
    version_id: UUID
    document_id: UUID
    chunk_count: int
    parser_identity: str
    normalizer_identity: str
    chunker_identity: str
    version_status: KnowledgeVersionStatus
    ingestion_status: KnowledgeIngestionStatus

    def __post_init__(self) -> None:
        if not isinstance(self.version_id, UUID):
            raise TypeError("version_id must be a UUID.")

        if not isinstance(self.document_id, UUID):
            raise TypeError("document_id must be a UUID.")

        if isinstance(self.chunk_count, bool) or not isinstance(self.chunk_count, int):
            raise TypeError("chunk_count must be an integer.")

        if self.chunk_count <= 0:
            raise ValueError("chunk_count must be greater than zero.")

        for field_name, value in (
            ("parser_identity", self.parser_identity,),
            ("normalizer_identity", self.normalizer_identity,),
            ("chunker_identity", self.chunker_identity,),
        ):
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string.")

            if not value.strip():
                raise ValueError(f"{field_name} must not be blank.")

        if not isinstance(self.version_status, KnowledgeVersionStatus):
            raise TypeError("version_status must be a KnowledgeVersionStatus.")

        if not isinstance(self.ingestion_status, KnowledgeIngestionStatus):
            raise TypeError("ingestion_status must be a KnowledgeIngestionStatus.")


# Internal immutable structures
@dataclass(frozen=True, slots=True)
class _ProcessingSnapshot:
    """
    Immutable source snapshot captured while the version is claimed.

    No SQLAlchemy entity or open Session escapes the claim transaction.
    """
    version_id: UUID
    document_id: UUID
    version_number: int
    source_type: KnowledgeSourceType
    source_content: str
    source_name: str | None
    source_uri: str | None
    metadata: Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class _ProcessingArtifacts:
    parsed: ParsedDocument
    normalized: NormalizedDocument
    chunked: ChunkedDocument

# Service
class ProcessKnowledgeVersion:
    """
    Process one immutable knowledge-document version.

    Lifecycle:

        Transaction A:
            DRAFT / PENDING -> PROCESSING / RUNNING -> COMMIT

        No DB transaction:
            parse -- normalize -- chunk

        Transaction B:
            verify still PROCESSING / RUNNING -> replace derived chunks -> READY / COMPLETED -> COMMIT

    Failure path:

        Transaction C:
            PROCESSING / RUNNING -> FAILED / FAILED -> COMMIT

    This deliberately avoids holding a database transaction or row lock while potentially expensive parsing/chunking work is running.
    """
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory, parser_resolver: DocumentParserResolver,
                 normalizer_resolver: DocumentNormalizerResolver, chunker_resolver: DocumentChunkerResolver) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        if not isinstance(parser_resolver, DocumentParserResolver):
            raise TypeError("parser_resolver must satisfy DocumentParserResolver.")

        if not isinstance(normalizer_resolver, DocumentNormalizerResolver):
            raise TypeError("normalizer_resolver must satisfy DocumentNormalizerResolver.")

        if not isinstance(chunker_resolver, DocumentChunkerResolver):
            raise TypeError("chunker_resolver must satisfy DocumentChunkerResolver.")

        self._uow_factory = uow_factory
        self._parser_resolver = parser_resolver
        self._normalizer_resolver = normalizer_resolver
        self._chunker_resolver = chunker_resolver

    def execute(self, command: ProcessKnowledgeVersionCommand) -> ProcessKnowledgeVersionResult:
        if not isinstance(command, ProcessKnowledgeVersionCommand):
            raise TypeError("command must be a ProcessKnowledgeVersionCommand.")

        snapshot = self._claim_version(command.version_id)

        try:
            artifacts = self._process(snapshot)
            return self._complete(snapshot=snapshot, artifacts=artifacts)

        except Exception as processing_error:
            self._record_failure_best_effort(snapshot=snapshot, processing_error=processing_error)
            raise

    # Phase A: claim
    def _claim_version(self, version_id: UUID) -> _ProcessingSnapshot:
        """
        Atomically claim a DRAFT/PENDING version for processing.

        PostgreSQL row locking prevents multiple workers from successfully claiming the same version.
        """
        with self._uow_factory() as uow:
            version = uow.versions.get_by_id_for_update(version_id)
            if version is None:
                raise KnowledgeVersionNotFoundError(version_id)

            self._ensure_claimable(version)
            now = self._utc_now()
            claimed = self._copy_version(
                version,
                status=KnowledgeVersionStatus.PROCESSING,
                ingestion_status=KnowledgeIngestionStatus.RUNNING,
                updated_at=now,
                processing_started_at=now,
                processing_completed_at=None,
                ready_at=None,
                failure_code=None,
                failure_message=None,
            )
            
            uow.versions.save(claimed)
            # Ensure state-transition constraints fail here rather than after the expensive ingestion work.
            uow.flush()
            snapshot = self._snapshot_from_version(claimed)
            uow.commit()

            return snapshot

    @staticmethod
    def _ensure_claimable(version: KnowledgeDocumentVersion) -> None:
        if version.status is not KnowledgeVersionStatus.DRAFT or version.ingestion_status is not KnowledgeIngestionStatus.PENDING:
            raise KnowledgeVersionNotProcessableError(
                version_id=version.id,
                version_status=version.status,
                ingestion_status=version.ingestion_status,
            )

    # Processing: deliberately no database transaction
    def _process(self, snapshot: _ProcessingSnapshot) -> _ProcessingArtifacts:
        source = IngestionSource(
            version_id=snapshot.version_id,
            source_type=snapshot.source_type,
            content=snapshot.source_content,
            source_name=snapshot.source_name,
            source_uri=snapshot.source_uri,
            metadata=self._build_ingestion_metadata(snapshot),
        )
        parser = self._parser_resolver.resolve(snapshot.source_type)
        parsed = parser.parse(source)
        normalizer = self._normalizer_resolver.resolve(snapshot.source_type)
        normalized = normalizer.normalize(parsed)
        chunker = self._chunker_resolver.resolve(snapshot.source_type)
        chunked = chunker.chunk(normalized)
        self._validate_artifacts(
            snapshot=snapshot,
            source=source,
            parsed=parsed,
            normalized=normalized,
            chunked=chunked,
        )

        return _ProcessingArtifacts(
            parsed=parsed,
            normalized=normalized,
            chunked=chunked,
        )

    # Phase B: successful completion
    def _complete(self, *, snapshot: _ProcessingSnapshot, artifacts: _ProcessingArtifacts) -> ProcessKnowledgeVersionResult:
        chunked = artifacts.chunked
        persisted_chunks = self._to_domain_chunks(snapshot=snapshot, chunked=chunked)
        if not persisted_chunks:
            raise KnowledgeProcessingContractError("Successful chunking produced zero persistent chunk artifacts.")

        with self._uow_factory() as uow:
            version = uow.versions.get_by_id_for_update(snapshot.version_id)
            if version is None:
                raise KnowledgeProcessingPersistenceError("Knowledge version disappeared before processing completion.")

            self._ensure_still_owned_for_processing(version)

            # Derived artifacts are replaceable for an unpublished processing version.
            # This also gives us deterministic cleanup if a previous attempt left stale chunks.
            uow.chunks.delete_for_version(snapshot.version_id)
            uow.chunks.add_many(persisted_chunks)
            completed_at = self._utc_now()
            ready_version = self._copy_version(
                version,
                status=KnowledgeVersionStatus.READY,
                ingestion_status=KnowledgeIngestionStatus.COMPLETED,
                updated_at=completed_at,
                processing_completed_at=completed_at,
                ready_at=completed_at,
                failure_code=None,
                failure_message=None,
            )

            uow.versions.save(ready_version)

            # Force all INSERTs / constraints before commit.
            uow.flush()
            uow.commit()

        return ProcessKnowledgeVersionResult(
            version_id=snapshot.version_id,
            document_id=snapshot.document_id,
            chunk_count=len(persisted_chunks),
            parser_identity=artifacts.parsed.parser_identity,
            normalizer_identity=artifacts.normalized.normalizer_identity,
            chunker_identity=chunked.chunker_identity,
            version_status=KnowledgeVersionStatus.READY,
            ingestion_status=KnowledgeIngestionStatus.COMPLETED,
        )

    # Phase C: failure recording
    def _record_failure_best_effort(self, *, snapshot: _ProcessingSnapshot, processing_error: Exception) -> None:
        """
        Persist a safe FAILED state without replacing the original processing exception.

        Failure-state persistence is deliberately best-effort from the
        perspective of execute(): the ingestion exception remains the
        primary failure.

        A future observability layer should log persistence failures separately.
        """
        try:
            self._fail(snapshot=snapshot, processing_error=processing_error)

        except Exception:
            # Do not mask the actual parser/normalizer/chunker/completion failure.
            return

    def _fail(self, *, snapshot: _ProcessingSnapshot, processing_error: Exception) -> None:
        failure_code = self._safe_failure_code(processing_error)
        failure_message = self._safe_failure_message(processing_error)
        
        with self._uow_factory() as uow:
            version = uow.versions.get_by_id_for_update(snapshot.version_id)
            if version is None:
                return

            # Another actor may already have completed/recovered this version. Never overwrite terminal state with FAILED.
            if version.status is not KnowledgeVersionStatus.PROCESSING or version.ingestion_status is not KnowledgeIngestionStatus.RUNNING:
                return

            completed_at = self._utc_now()
            failed = self._copy_version(
                version,
                status=KnowledgeVersionStatus.FAILED,
                ingestion_status=KnowledgeIngestionStatus.FAILED,
                updated_at=completed_at,
                processing_completed_at=completed_at,
                ready_at=None,
                failure_code=failure_code,
                failure_message=failure_message,
            )

            uow.versions.save(failed)
            uow.flush()
            uow.commit()

    # Pipeline validation
    @staticmethod
    def _validate_artifacts(*, snapshot: _ProcessingSnapshot, source: IngestionSource, parsed: ParsedDocument,
                            normalized: NormalizedDocument, chunked: ChunkedDocument
    ) -> None:
        expected_version_id = snapshot.version_id
        for stage_name, artifact in (
            ("source", source),
            ("parsed", parsed),
            ("normalized", normalized),
            ("chunked", chunked),
        ):
            if artifact.version_id != expected_version_id:
                raise KnowledgeProcessingContractError(f"{stage_name} artifact belongs to a different knowledge version.")

        expected_source_type = snapshot.source_type
        for stage_name, artifact in (
            ("source", source),
            ("parsed", parsed),
            ("normalized", normalized),
            ("chunked", chunked),
        ):
            if artifact.source_type is not expected_source_type:
                raise KnowledgeProcessingContractError(f"{stage_name} artifact changed the knowledge source type.")

        if (
            normalized.source_parser_strategy_id != parsed.parser_strategy_id
            or normalized.source_parser_version != parsed.parser_version
            or normalized.source_parser_config_fingerprint != parsed.parser_config_fingerprint
        ):
            raise KnowledgeProcessingContractError("Normalizer output does not preserve parser provenance.")

        if (
            chunked.source_parser_strategy_id != parsed.parser_strategy_id
            or chunked.source_parser_version != parsed.parser_version
            or chunked.source_parser_config_fingerprint != parsed.parser_config_fingerprint
        ):
            raise KnowledgeProcessingContractError("Chunker output does not preserve parser provenance.")

        if (
            chunked.source_normalizer_strategy_id != normalized.normalizer_strategy_id
            or chunked.source_normalizer_version != normalized.normalizer_version
            or chunked.source_normalizer_config_fingerprint != normalized.normalizer_config_fingerprint
        ):
            raise KnowledgeProcessingContractError("Chunker output does not preserve normalizer provenance.")

        if chunked.chunk_count <= 0:
            raise KnowledgeProcessingContractError("Chunking completed without producing any chunks.")

        if len(chunked.chunks) != chunked.chunk_count:
            raise KnowledgeProcessingContractError("Chunk count does not match chunk artifacts.")

    # Chunk persistence mapping
    @classmethod
    def _to_domain_chunks(cls, *, snapshot: _ProcessingSnapshot, chunked: ChunkedDocument) -> list[KnowledgeChunk]:
        now = cls._utc_now()
        result: list[KnowledgeChunk] = []
        for candidate in chunked.chunks:
            spans = tuple(candidate.source_spans)
            metadata = dict(candidate.metadata)

            # Preserve exact many-to-many-ish provenance even though
            # the current SQL chunk table exposes only one pair of
            # top-level offsets.
            metadata["source_spans"] = [
                {
                    "source_segment_index": (
                        span.source_segment_index
                    ),
                    "start_offset": (
                        span.start_offset
                    ),
                    "end_offset": (
                        span.end_offset
                    ),
                }
                for span in spans
            ]

            metadata["section_path"] = list(candidate.section_path)
            metadata["transformation_provenance"] = {
                "parser": {
                    "strategy_id": chunked.source_parser_strategy_id,
                    "version": chunked.source_parser_version,
                    "config_fingerprint": chunked.source_parser_config_fingerprint,
                },
                "normalizer": {
                    "strategy_id": chunked.source_normalizer_strategy_id,
                    "version": chunked.source_normalizer_version,
                    "config_fingerprint": chunked.source_normalizer_config_fingerprint,
                },
                "chunker": {
                    "strategy_id": chunked.chunker_strategy_id,
                    "version": chunked.chunker_version,
                    "config_fingerprint": chunked.chunker_config_fingerprint,
                },
            }

            # The existing persistence model can represent top-level offsets truthfully
            # only when the chunk comes from one normalized source span.
            if len(spans) == 1:
                start_offset = spans[0].start_offset
                end_offset = spans[0].end_offset
            else:
                start_offset = None
                end_offset = None

            result.append(
                KnowledgeChunk(
                    id=uuid7(),
                    version_id=snapshot.version_id,
                    chunk_index=candidate.index,
                    content=candidate.text,
                    section_title=candidate.section_title,
                    start_offset=start_offset,
                    end_offset=end_offset,
                    token_count=None, # Character-based chunking does not know the embedding tokenizer yet. Do not fake it.
                    metadata=metadata,
                    created_at=now,
                    updated_at=now,
                )
            )

        return result

    # State helpers
    @staticmethod
    def _ensure_still_owned_for_processing(version: KnowledgeDocumentVersion) -> None:
        if version.status is not KnowledgeVersionStatus.PROCESSING or version.ingestion_status is not KnowledgeIngestionStatus.RUNNING:
            raise KnowledgeVersionProcessingConflictError(
                f"Knowledge version changed state while processing was in progress. version_id='{version.id}', "
                f"status='{version.status.value}', ingestion_status='{version.ingestion_status.value}'."
            )

    @staticmethod
    def _snapshot_from_version(version: KnowledgeDocumentVersion) -> _ProcessingSnapshot:
        return _ProcessingSnapshot(
            version_id=version.id,
            document_id=version.document_id,
            version_number=version.version_number,
            source_type=version.source_type,
            source_content=version.source_content,
            source_name=version.source_name,
            source_uri=version.source_uri,
            metadata=dict(version.metadata),
        )

    @staticmethod
    def _build_ingestion_metadata(snapshot: _ProcessingSnapshot) -> dict[str, Any]:
        metadata = dict(snapshot.metadata)
        # System-owned values override caller metadata so provenance cannot accidentally lie about document/version identity.
        metadata.update(
            {
                "document_id": str(snapshot.document_id),
                "version_number": snapshot.version_number,
            }
        )

        return metadata

    # Domain version copying
    @staticmethod
    def _copy_version(version: KnowledgeDocumentVersion, *, status: KnowledgeVersionStatus, ingestion_status: KnowledgeIngestionStatus,
                      updated_at: datetime, processing_started_at: datetime | None = None, processing_completed_at: datetime | None = None,
                      ready_at: datetime | None = None, failure_code: str | None = None, failure_message: str | None = None
    ) -> KnowledgeDocumentVersion:
        """
        Build a new domain entity containing the same immutable version
        identity/source and updated lifecycle state.

        This deliberately does not assume the domain entity is mutable.
        It also aligns with update_version_model(), which persists only
        lifecycle/mutable fields.
        """
        return KnowledgeDocumentVersion(
            id=version.id,
            document_id=version.document_id,
            version_number=version.version_number,
            source_type=version.source_type,
            source_content=version.source_content,
            content_hash=version.content_hash,
            status=status,
            ingestion_status=ingestion_status,
            source_name=version.source_name,
            source_uri=version.source_uri,
            metadata=dict(version.metadata),
            created_at=version.created_at,
            updated_at=updated_at,
            processing_started_at=(processing_started_at if processing_started_at is not None else version.processing_started_at),
            processing_completed_at=processing_completed_at,
            ready_at=ready_at,
            published_at=version.published_at,
            superseded_at=version.superseded_at,
            archived_at=version.archived_at,
            failure_code=failure_code,
            failure_message=failure_message,
        )

    # Safe failure persistence
    @staticmethod
    def _safe_failure_code(error: Exception) -> str:
        raw_code = getattr(error, "code", None)
        if isinstance(raw_code, str) and raw_code.strip():
            code = raw_code.strip()
        else:
            code = type(error).__name__

        # Keep persisted error codes bounded and predictable.
        return code[:128]

    @staticmethod
    def _safe_failure_message(error: Exception) -> str:
        """
        Persist a conservative failure description.

        Do not store arbitrary full exception representations because parser/provider exceptions 
        may contain paths, credentials, or source-document content.
        """
        safe_message = getattr(error, "message", None)
        if isinstance(safe_message, str) and safe_message.strip():
            message = safe_message.strip()
        else:
            message = f"Knowledge ingestion failed during {type(error).__name__}."

        return message[:1000]

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)