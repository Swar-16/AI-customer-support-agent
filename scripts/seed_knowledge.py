from __future__ import annotations
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid5
from uuid6 import uuid7

from packages.database.session import SessionLocal
from packages.database.unit_of_work.knowledge import SQLAlchemyKnowledgeUnitOfWork
from packages.knowledge.application.process_version import ProcessKnowledgeVersion, ProcessKnowledgeVersionCommand, ProcessKnowledgeVersionResult
from packages.knowledge.application.publish_version import PublishKnowledgeVersion, PublishKnowledgeVersionCommand, PublishKnowledgeVersionResult
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.enums import KnowledgeContentType, KnowledgeDocumentStatus, KnowledgeIngestionStatus, KnowledgeSourceType, KnowledgeVersionStatus, KnowledgeVisibility
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.ingestion.parser.resolver import DefaultDocumentParserResolver
from packages.knowledge.ingestion.normalization.resolver import DefaultDocumentNormalizerResolver
from packages.knowledge.ingestion.chunking.resolver import DefaultDocumentChunkerResolver
from packages.knowledge.ingestion.parser.markdown import MarkdownStructuralParser
from packages.knowledge.ingestion.normalization.markdown import MarkdownNormalizer
from packages.knowledge.ingestion.chunking.semantic_text import StructuralTextChunker

# Paths / configuration
PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DATA_ROOT = PROJECT_ROOT / "knowledge_data"
FAQ_DIRECTORY = "faqs"
POLICY_DIRECTORY = "policies"
SUPPORTED_DIRECTORIES: dict[str, KnowledgeContentType] = {
    FAQ_DIRECTORY: KnowledgeContentType.FAQ,
    POLICY_DIRECTORY: KnowledgeContentType.POLICY,
}
SOURCE_TYPE = KnowledgeSourceType.MARKDOWN
DEFAULT_VISIBILITY = KnowledgeVisibility.CUSTOMER
SEED_SOURCE = "repository_bootstrap"

# Stable namespace used to derive deterministic document IDs from source paths.

# DO NOT change this after you've seeded a real environment, otherwise the
# same source file would become a different logical document.
KNOWLEDGE_SEED_NAMESPACE = UUID("c7e942e7-c3bb-4f58-a235-ec02bc668197")

# Models local to the script
@dataclass(frozen=True, slots=True)
class DiscoveredKnowledgeFile:
    path: Path
    relative_path: Path
    content_type: KnowledgeContentType
    seed_key: str
    title: str
    topic: str

@dataclass(frozen=True, slots=True)
class PreparedKnowledgeVersion:
    document_id: UUID
    version_id: UUID | None
    should_process: bool
    should_publish: bool
    skipped: bool
    reason: str | None = None

@dataclass(slots=True)
class SeedSummary:
    discovered: int = 0
    created_documents: int = 0
    created_versions: int = 0
    processed_versions: int = 0
    published_versions: int = 0
    skipped: int = 0
    failed: int = 0
    
@dataclass(frozen=True, slots=True)
class KnowledgeBootstrapServices:
    processor: ProcessKnowledgeVersion
    publisher: PublishKnowledgeVersion
    parser_resolver: DefaultDocumentParserResolver
    normalizer_resolver: DefaultDocumentNormalizerResolver
    chunker_resolver: DefaultDocumentChunkerResolver


# General helpers
def normalize_source_content(content: str) -> str:
    """
    Keep hashing consistent with the domain entity.

    KnowledgeDocumentVersion strips leading/trailing whitespace from source_content, so hashing 
    the stripped representation prevents a trailing newline from creating a false content change.
    """
    return content.strip()

def calculate_content_hash(content: str) -> str:
    normalized = normalize_source_content(content)

    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def humanize_filename(stem: str) -> str:
    return (
        stem
        .replace("_policy", "")
        .replace("-policy", "")
        .replace("_faq", "")
        .replace("-faq", "")
        .replace("_", " ")
        .replace("-", " ")
        .strip()
        .title()
    )

def extract_topic(path: Path, content_type: KnowledgeContentType) -> str:
    """
    Examples:

        faqs/refunds.md
            -> refunds

        policies/refund_policy.md
            -> refund

        policies/privacy_security_policy.md
            -> privacy_security
    """
    topic = path.stem.strip().lower()
    if content_type is KnowledgeContentType.POLICY:
        if topic.endswith("_policy"):
            topic = topic.removesuffix("_policy")

        elif topic.endswith("-policy"):
            topic = topic.removesuffix("-policy")

    elif content_type is KnowledgeContentType.FAQ:
        if topic.endswith("_faq"):
            topic = topic.removesuffix("_faq")

        elif topic.endswith("-faq"):
            topic = topic.removesuffix("-faq")

    return topic.strip("_-")

def build_document_title(*, topic: str, content_type: KnowledgeContentType) -> str:
    topic_title = humanize_filename(topic)
    if content_type is KnowledgeContentType.FAQ:
        return f"{topic_title} FAQ"

    if content_type is KnowledgeContentType.POLICY:
        return f"{topic_title} Policy"

    return topic_title

def build_seed_key(relative_path: Path) -> str:
    """
    Stable repository-level identity.

    Examples:

        faqs/refunds.md
        policies/refund_policy.md

    FAQ and policy remain independent logical documents.
    """
    return relative_path.as_posix().lower()

def deterministic_document_id(seed_key: str) -> UUID:
    """
    Avoid querying arbitrary JSON metadata merely to discover whether the
    bootstrap document already exists.

    The same repository source path always maps to the same document UUID.
    """
    return uuid5(KNOWLEDGE_SEED_NAMESPACE, seed_key) ## same UUID every time the seed script runs


# Discovery
def validate_knowledge_root() -> None:
    if not KNOWLEDGE_DATA_ROOT.exists():
        raise FileNotFoundError(f"Knowledge data directory does not exist: {KNOWLEDGE_DATA_ROOT}")

    if not KNOWLEDGE_DATA_ROOT.is_dir():
        raise NotADirectoryError(f"Knowledge data path is not a directory: {KNOWLEDGE_DATA_ROOT}")

def discover_knowledge_files() -> list[DiscoveredKnowledgeFile]:
    validate_knowledge_root()
    discovered: list[DiscoveredKnowledgeFile] = []
    for directory_name, content_type in SUPPORTED_DIRECTORIES.items():
        directory = KNOWLEDGE_DATA_ROOT / directory_name
        if not directory.exists():
            print(f"[WARN] Knowledge directory is missing: {directory.relative_to(PROJECT_ROOT)}")
            continue

        if not directory.is_dir():
            raise NotADirectoryError(f"Expected knowledge directory: {directory}")

        for path in sorted(directory.rglob("*.md")):
            if not path.is_file():
                continue

            relative_path = path.relative_to(KNOWLEDGE_DATA_ROOT)
            topic = extract_topic(path, content_type)
            discovered.append(
                DiscoveredKnowledgeFile(
                    path=path,
                    relative_path=relative_path,
                    content_type=content_type,
                    seed_key=build_seed_key(relative_path),
                    title=build_document_title(topic=topic, content_type=content_type),
                    topic=topic,
                )
            )

    return discovered


# Application composition
def build_uow_factory():
    return lambda: SQLAlchemyKnowledgeUnitOfWork(SessionLocal)

def build_process_version_service() -> ProcessKnowledgeVersion:
    """
    Bootstrap composition.

    Later this should ideally be extracted into the application's knowledge composition module so the Admin API, workers, 
    CLI and seed script all use exactly the same configured ingestion graph.
    """
    parser_resolver = DefaultDocumentParserResolver([MarkdownStructuralParser(),])
    normalizer_resolver = DefaultDocumentNormalizerResolver([MarkdownNormalizer(),])
    chunker_resolver = DefaultDocumentChunkerResolver([StructuralTextChunker(),])

    return ProcessKnowledgeVersion(
        uow_factory=build_uow_factory(),
        parser_resolver=parser_resolver,
        normalizer_resolver=normalizer_resolver,
        chunker_resolver=chunker_resolver,
    )

def build_publish_version_service() -> PublishKnowledgeVersion:
    return PublishKnowledgeVersion(uow_factory=build_uow_factory())


# Document/version preparation
def create_document(*, item: DiscoveredKnowledgeFile, document_id: UUID) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=document_id,
        title=item.title,
        content_type=item.content_type,
        visibility=DEFAULT_VISIBILITY,
        status=KnowledgeDocumentStatus.ACTIVE,
        description=f"Bootstrap knowledge source for {item.title}.",
        metadata={
            "seed_key": item.seed_key,
            "seed_source": SEED_SOURCE,
            "topic": item.topic,
            "source_relative_path": item.relative_path.as_posix(),
        },
    )


def create_version(*, document_id: UUID, version_number: int, content: str, content_hash: str, item: DiscoveredKnowledgeFile) -> KnowledgeDocumentVersion:
    return KnowledgeDocumentVersion(
        id=uuid7(),
        document_id=document_id,
        version_number=version_number,
        source_type=SOURCE_TYPE,
        source_content=content,
        content_hash=content_hash,
        status=KnowledgeVersionStatus.DRAFT,
        ingestion_status=KnowledgeIngestionStatus.PENDING,
        source_name=item.path.name,

        # Keep this relative and portable.
        # Do NOT persist C:\\... developer-specific paths into knowledge provenance.
        source_uri=item.relative_path.as_posix(),
        metadata={
            "seed_key": item.seed_key,
            "seed_source": SEED_SOURCE,
            "topic": item.topic,
            "content_type": item.content_type.value,
            "source_relative_path": item.relative_path.as_posix(),
        },
    )

def ensure_existing_document_is_compatible(*, document: KnowledgeDocument, item: DiscoveredKnowledgeFile) -> None:
    """
    A deterministic ID collision with incompatible business identity should
    fail loudly instead of silently changing an existing document.
    """
    if document.status is not KnowledgeDocumentStatus.ACTIVE:
        raise RuntimeError(f"Bootstrap document '{document.id}' already exists but is '{document.status.value}'. Refusing to modify it automatically.")

    if document.content_type is not item.content_type:
        raise RuntimeError(f"Bootstrap document '{document.id}' has content_type='{document.content_type.value}', but '{item.relative_path.as_posix()}' maps to '{item.content_type.value}'.")

def prepare_document_version(item: DiscoveredKnowledgeFile, *, summary: SeedSummary) -> PreparedKnowledgeVersion:
    raw_content = item.path.read_text(encoding="utf-8")
    content = normalize_source_content(raw_content)
    if not content:
        return PreparedKnowledgeVersion(
            document_id=deterministic_document_id(item.seed_key),
            version_id=None,
            should_process=False,
            should_publish=False,
            skipped=True,
            reason="source file is empty",
        )

    content_hash = calculate_content_hash(content)
    document_id = deterministic_document_id(item.seed_key)

    with build_uow_factory()() as uow:
        document = uow.documents.get_by_id(document_id)
        if document is None:
            document = create_document(item=item, document_id=document_id)
            uow.documents.add(document)
            uow.flush()
            summary.created_documents += 1

        else:
            ensure_existing_document_is_compatible(document=document, item=item)

        current_published = uow.versions.get_published_for_document(document_id)
        # True idempotency: Same published source -> nothing to do.
        if current_published is not None and current_published.content_hash == content_hash:
            uow.commit()
            return PreparedKnowledgeVersion(
                document_id=document_id,
                version_id=current_published.id,
                should_process=False,
                should_publish=False,
                skipped=True,
                reason="identical content is already published",
            )

        existing_versions = uow.versions.list_for_document(document_id)

        # Crash recovery: Suppose an earlier run:
        #   created version
        #   -> processed it
        #   -> READY
        #   -> process died before publish
        
        # Do not create another identical version. Reuse READY.
        same_ready = next(
            (
                version for version in reversed(existing_versions)
                if (
                    version.content_hash == content_hash
                    and version.status is KnowledgeVersionStatus.READY
                    and version.ingestion_status is KnowledgeIngestionStatus.COMPLETED
                )
            ),
            None,
        )

        if same_ready is not None:
            uow.commit()
            return PreparedKnowledgeVersion(
                document_id=document_id,
                version_id=same_ready.id,
                should_process=False,
                should_publish=True,
                skipped=False,
            )

        # Similar recovery for a committed DRAFT.
        same_draft = next(
            (
                version for version in reversed(existing_versions)
                if (
                    version.content_hash == content_hash
                    and version.status is KnowledgeVersionStatus.DRAFT
                    and version.ingestion_status is KnowledgeIngestionStatus.PENDING
                )
            ),
            None,
        )

        if same_draft is not None:
            uow.commit()

            return PreparedKnowledgeVersion(
                document_id=document_id,
                version_id=same_draft.id,
                should_process=True,
                should_publish=True,
                skipped=False,
            )

        # New source content -> immutable new version.
        # next_version_number() owns the version allocation concurrency invariant.
        version_number = uow.versions.next_version_number(document_id)
        version = create_version(
            document_id=document_id,
            version_number=version_number,
            content=content,
            content_hash=content_hash,
            item=item,
        )
        uow.versions.add(version)
        uow.flush()
        uow.commit()
        summary.created_versions += 1

        return PreparedKnowledgeVersion(
            document_id=document_id,
            version_id=version.id,
            should_process=True,
            should_publish=True,
            skipped=False,
        )

# One-file seed workflow
def seed_one(item: DiscoveredKnowledgeFile, *, process_service: ProcessKnowledgeVersion, publish_service: PublishKnowledgeVersion, summary: SeedSummary) -> None:
    display_path = item.relative_path.as_posix()
    print(f"\n[KNOWLEDGE] {display_path}")
    prepared = prepare_document_version(item, summary=summary)
    if prepared.skipped:
        summary.skipped += 1

        print(f"  [SKIP] {prepared.reason}")
        return

    if prepared.version_id is None:
        raise RuntimeError("Prepared knowledge version unexpectedly contains no version_id.")

    process_result: ProcessKnowledgeVersionResult | None = None
    publish_result: PublishKnowledgeVersionResult | None = None
    if prepared.should_process:
        print(f"  [PROCESS] version={prepared.version_id}")
        
        process_result = process_service.execute(ProcessKnowledgeVersionCommand(version_id=prepared.version_id))
        summary.processed_versions += 1
        print(
            f"  [READY] chunks={process_result.chunk_count}, "
            f"parser={process_result.parser_identity}, "
            f"normalizer={process_result.normalizer_identity}, "
            f"chunker={process_result.chunker_identity}"
        )

    if prepared.should_publish:
        print(f"  [PUBLISH] version={prepared.version_id}")
        publish_result = publish_service.execute(PublishKnowledgeVersionCommand(version_id=prepared.version_id))
        
        summary.published_versions += 1
        print(f"  [PUBLISHED] v{publish_result.version_number}")
        if publish_result.superseded_version_id is not None:
            print(f"  [SUPERSEDED] {publish_result.superseded_version_id}")

# Preflight
def preflight(*, services: KnowledgeBootstrapServices) -> None:
    """
    Fail before writing anything if the configured ingestion graph cannot handle Markdown.
    """
    for name, resolver in (
        ("parser", services.parser_resolver),
        ("normalizer", services.normalizer_resolver),
        ("chunker", services.chunker_resolver),
    ):
        if not resolver.supports(KnowledgeSourceType.MARKDOWN):
            raise RuntimeError(f"Configured {name} resolver does not support markdown.")
        
def build_services() -> KnowledgeBootstrapServices:
    parser_resolver = DefaultDocumentParserResolver(
        [MarkdownStructuralParser()]
    )

    normalizer_resolver = DefaultDocumentNormalizerResolver(
        [MarkdownNormalizer()]
    )

    chunker_resolver = DefaultDocumentChunkerResolver(
        [StructuralTextChunker()]
    )

    processor = ProcessKnowledgeVersion(
        uow_factory=build_uow_factory(),
        parser_resolver=parser_resolver,
        normalizer_resolver=normalizer_resolver,
        chunker_resolver=chunker_resolver,
    )

    publisher = PublishKnowledgeVersion(
        uow_factory=build_uow_factory(),
    )

    return KnowledgeBootstrapServices(
        processor=processor,
        publisher=publisher,
        parser_resolver=parser_resolver,
        normalizer_resolver=normalizer_resolver,
        chunker_resolver=chunker_resolver,
    )
            
# Main
def main() -> int:
    print("=" * 72)
    print("Knowledge Bootstrap")
    print("=" * 72)

    print(f"Project root:   {PROJECT_ROOT}")
    print(f"Knowledge root: {KNOWLEDGE_DATA_ROOT}")
    files = discover_knowledge_files()
    summary = SeedSummary(discovered=len(files))
    if not files:
        print("\n[WARN] No Markdown knowledge files were discovered.")
        return 0

    print(f"Discovered:     {len(files)} file(s)")
    services = build_services()
    preflight(services=services)

    for item in files:
        try:
            seed_one(item, process_service=services.processor, publish_service=services.publisher, summary=summary)

        except Exception as exc:
            summary.failed += 1
            print(f"  [FAILED] {type(exc).__name__}: {exc}")
            # Continue with independent knowledge documents.

            # A broken refund document should not prevent us from discovering whether shipping/payment/etc. 
            # also contain ingestion problems.
            continue

    print()
    print("=" * 72)
    print("Knowledge Bootstrap Summary")
    print("=" * 72)

    print(f"Discovered documents : {summary.discovered}")
    print(f"Created documents    : {summary.created_documents}")
    print(f"Created versions     : {summary.created_versions}")
    print(f"Processed versions   : {summary.processed_versions}")
    print(f"Published versions   : {summary.published_versions}")
    print(f"Skipped unchanged    : {summary.skipped}")
    print(f"Failures             : {summary.failed}")
    print("=" * 72)

    if summary.failed:
        print("\nKnowledge bootstrap completed with failures.", file=sys.stderr)
        return 1

    print("\nKnowledge bootstrap completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())