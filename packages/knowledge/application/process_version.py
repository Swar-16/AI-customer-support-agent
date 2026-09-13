# AI-customer-support-agent\packages\knowledge\application\process_version.py
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from uuid6 import uuid7

from packages.knowledge.application.exceptions import KnowledgeProcessingDocumentDoesNotExistError
from packages.knowledge.application.exceptions import KnowledgeProcessingDocumentNotActiveError, KnowledgeVersionNotFoundError
from packages.knowledge.application.exceptions import KnowledgeVersionNotProcessableError, KnowledgeVersionProcessingConflictError
from packages.knowledge.application.exceptions import KnowledgeProcessingContractError, KnowledgeProcessingPersistenceError
from packages.knowledge.application.mutation_context import KnowledgeMutationContext
from packages.knowledge.domain.chunk import KnowledgeChunk
from packages.knowledge.domain.enums import KnowledgeDocumentStatus, KnowledgeIngestionStatus, KnowledgeSourceType, KnowledgeVersionStatus
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.ingestion.chunking.base import DocumentChunkerResolver
from packages.knowledge.ingestion.chunking.models import ChunkedDocument
from packages.knowledge.ingestion.models import IngestionSource, ParsedDocument
from packages.knowledge.ingestion.normalization.base import DocumentNormalizerResolver
from packages.knowledge.ingestion.normalization.models import NormalizedDocument
from packages.knowledge.ingestion.parser.base import DocumentParserResolver
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory
from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder

# Command / result
@dataclass(frozen=True, slots=True)
class ProcessKnowledgeVersionCommand:
    context: KnowledgeMutationContext
    version_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.context, KnowledgeMutationContext):
            raise TypeError("context must be a KnowledgeMutationContext.")

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
    initiated_by_admin_id: UUID | None
    trace_id: UUID

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

        snapshot = self._claim_version(command)
        try:
            artifacts = self._process(snapshot)
            return self._complete(snapshot=snapshot, artifacts=artifacts)

        except Exception as processing_error:
            self._record_failure_best_effort(snapshot=snapshot, processing_error=processing_error)
            raise

    # Phase A: claim
    def _claim_version(self, command: ProcessKnowledgeVersionCommand) -> _ProcessingSnapshot:
        """
        Claim a processable version in a short transaction.

        The parent document is locked before the version, matching the lock ordering used by publication and archival.
        """
        with self._uow_factory() as uow:
            preliminary = uow.versions.get_by_id(command.version_id)
            if preliminary is None:
                raise KnowledgeVersionNotFoundError(command.version_id)

            document = uow.documents.get_by_id_for_update(preliminary.document_id)
            if document is None:
                raise KnowledgeProcessingDocumentDoesNotExistError(preliminary.document_id)

            if document.status is not KnowledgeDocumentStatus.ACTIVE:
                raise KnowledgeProcessingDocumentNotActiveError(document_id=document.id, status=document.status)

            version = uow.versions.get_by_id_for_update(command.version_id)
            if version is None:
                raise KnowledgeVersionNotFoundError(command.version_id)

            if version.document_id != document.id:
                raise KnowledgeVersionProcessingConflictError("Knowledge version no longer belongs to the locked document.")

            self._ensure_claimable(version)
            before_state = self._audit_state(version)
            started_at = self._utc_now()
            claimed = version.start_processing(occurred_at=started_at)
            uow.versions.save(claimed)
            uow.flush()

            AuditRecorder(repository=uow.audit_events).record(
                RecordAuditEventCommand(
                    event_type="knowledge_version.processing_started",
                    entity_type="knowledge_version",
                    entity_id=claimed.id,
                    action="processing_started",
                    actor=command.context.actor,
                    trace_id=command.context.trace_id,
                    before_state=before_state,
                    after_state=self._audit_state(claimed),
                    metadata={
                        "document_id": str(claimed.document_id),
                        "version_number": claimed.version_number,
                        "source_type": claimed.source_type.value,
                    },
                    occurred_at=started_at,
                )
            )

            snapshot = self._snapshot_from_version(claimed, initiated_by_admin_id=command.context.initiating_admin_id, trace_id=command.context.trace_id)

            uow.commit()
            return snapshot

    @staticmethod
    def _ensure_claimable(version: KnowledgeDocumentVersion) -> None:
        is_initial_attempt = version.status is KnowledgeVersionStatus.DRAFT and version.ingestion_status is KnowledgeIngestionStatus.PENDING
        is_retry = version.status is KnowledgeVersionStatus.FAILED and version.ingestion_status is KnowledgeIngestionStatus.FAILED
        if not is_initial_attempt and not is_retry:
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
            before_state = self._audit_state(version)

            # Derived artifacts are replaceable for an unpublished processing version.
            # This also gives us deterministic cleanup if a previous attempt left stale chunks.
            uow.chunks.delete_for_version(snapshot.version_id)
            uow.chunks.add_many(persisted_chunks)
            completed_at = self._utc_now()
            ready_version = version.mark_processing_completed(
                occurred_at=completed_at
            )

            uow.versions.save(ready_version)

            # Force all INSERTs / constraints before commit.
            uow.flush()
            
            AuditRecorder(repository=uow.audit_events).record(
                RecordAuditEventCommand(
                    event_type="knowledge_version.processing_completed",
                    entity_type="knowledge_version",
                    entity_id=ready_version.id,
                    action="processing_completed",
                    actor=AuditActor(actor_type=AuditActorType.SYSTEM),
                    trace_id=snapshot.trace_id,
                    before_state=before_state,
                    after_state=self._audit_state(ready_version),
                    metadata={
                        "document_id": str(ready_version.document_id),
                        "version_number": ready_version.version_number,
                        "chunk_count": len(persisted_chunks),
                        "parser_identity": artifacts.parsed.parser_identity,
                        "normalizer_identity": artifacts.normalized.normalizer_identity,
                        "chunker_identity": artifacts.chunked.chunker_identity,
                        **({"initiated_by_admin_id": str(snapshot.initiated_by_admin_id)} 
                           if snapshot.initiated_by_admin_id is not None else {}),
                    },
                    occurred_at=completed_at,
                )
            )
            
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

            before_state = self._audit_state(version)
            completed_at = self._utc_now()
            failed = version.mark_processing_failed(
                failure_code=failure_code,
                failure_message=failure_message,
                occurred_at=completed_at,
            )

            uow.versions.save(failed)
            uow.flush()
            
            AuditRecorder(repository=uow.audit_events).record(
                RecordAuditEventCommand(
                    event_type="knowledge_version.processing_failed",
                    entity_type="knowledge_version",
                    entity_id=failed.id,
                    action="processing_failed",
                    actor=AuditActor(actor_type=AuditActorType.SYSTEM),
                    trace_id=snapshot.trace_id,
                    before_state=before_state,
                    after_state=self._audit_state(failed),
                    metadata={
                        "document_id": str(failed.document_id),
                        "version_number": failed.version_number,
                        "failure_code": failure_code,
                        "exception_type": type(processing_error).__name__,
                        "initiated_by_admin_id": str(snapshot.initiated_by_user_id),
                    },
                    occurred_at=completed_at,
                )
            )
            
            uow.commit()

    # Pipeline validation
    @staticmethod
    def _validate_artifacts(*, snapshot: _ProcessingSnapshot, source: IngestionSource, parsed: ParsedDocument,
                            normalized: NormalizedDocument, chunked: ChunkedDocument
    ) -> None:
        expected_version_id = snapshot.version_id
        for stage_name, artifact in (("source", source), ("parsed", parsed), ("normalized", normalized), ("chunked", chunked),):
            if artifact.version_id != expected_version_id:
                raise KnowledgeProcessingContractError(f"{stage_name} artifact belongs to a different knowledge version.")

        expected_source_type = snapshot.source_type
        for stage_name, artifact in (("source", source), ("parsed", parsed), ("normalized", normalized), ("chunked", chunked),):
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
        
    @staticmethod
    def _audit_state(version: KnowledgeDocumentVersion) -> dict[str, object]:
        return {
            "status": version.status.value,
            "ingestion_status": version.ingestion_status.value,
            "processing_started_at": version.processing_started_at.isoformat() if version.processing_started_at is not None else None,
            "processing_completed_at": version.processing_completed_at.isoformat() if version.processing_completed_at is not None else None,
            "ready_at": version.ready_at.isoformat() if version.ready_at is not None else None,
            "failure_code": version.failure_code,
        }

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
    def _snapshot_from_version(version: KnowledgeDocumentVersion, *, initiated_by_admin_id: UUID | None, trace_id: UUID) -> _ProcessingSnapshot:
        return _ProcessingSnapshot(
            version_id=version.id,
            document_id=version.document_id,
            version_number=version.version_number,
            source_type=version.source_type,
            source_content=version.source_content,
            source_name=version.source_name,
            source_uri=version.source_uri,
            metadata=dict(version.metadata),
            initiated_by_admin_id=initiated_by_admin_id,
            trace_id=trace_id,
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