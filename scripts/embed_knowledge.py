from __future__ import annotations
import argparse
import sys
import traceback
from uuid import UUID

from packages.application.composition.knowledge_embedding_factory import create_knowledge_embedding_services
from packages.config.settings import get_settings
from packages.database.session import create_session_factory
from packages.database.unit_of_work.knowledge import SQLAlchemyKnowledgeUnitOfWork
from packages.knowledge.application.embed_version import EmbedKnowledgeVersion, EmbedKnowledgeVersionCommand
from packages.knowledge.embeddings.input.contextual import ContextualEmbeddingInputBuilder


def parse_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    
    except (ValueError, AttributeError) as exc:
        raise argparse.ArgumentTypeError(f"Invalid UUID: {value!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill embeddings for published knowledge versions.")
    parser.add_argument("--version-id", type=parse_uuid, default=None,
                        help="Embed one specific version. If omitted, all eligible published versions are processed.")

    parser.add_argument("--environment", choices=("development", "test"), default="development")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings(args.environment)
    session_factory = create_session_factory(database_url=settings.database_url, echo=settings.database_echo)

    def uow_factory() -> SQLAlchemyKnowledgeUnitOfWork:
        return SQLAlchemyKnowledgeUnitOfWork(session_factory)

    embedding_services = create_knowledge_embedding_services(settings)
    provider = embedding_services.provider

    input_builder = ContextualEmbeddingInputBuilder()

    service = EmbedKnowledgeVersion(
        uow_factory=uow_factory,
        provider=provider,
        input_builder=input_builder,
        batch_size=settings.embedding_batch_size,
    )


    # Resolve versions
    if args.version_id is not None:
        version_ids = [args.version_id]
    else:
        with uow_factory() as uow:
            versions = uow.versions.list_embedding_candidates()
            version_ids = [version.id for version in versions]

    print("=" * 72)
    print("Knowledge Embedding Backfill")
    print("=" * 72)
    print(f"Environment : {args.environment}")
    print(f"Provider    : {provider.descriptor.provider}/{provider.descriptor.model}")
    print(f"Dimensions  : {provider.descriptor.dimensions}")
    print(f"Versions    : {len(version_ids)}")
    print("=" * 72)

    if not version_ids:
        print("\nNo eligible knowledge versions found.")
        return 0

    successful = 0
    failed = 0
    total_chunks = 0
    total_created = 0
    total_existing = 0

    # Process independently
    for index, version_id in enumerate(version_ids, start=1):
        print()
        print(f"[{index}/{len(version_ids)}] Version {version_id}")

        try:
            result = service.execute(EmbedKnowledgeVersionCommand(version_id=version_id))

        except KeyboardInterrupt:
            print("\n[INTERRUPTED] Embedding backfill cancelled.", file=sys.stderr)
            return 130

        except Exception as exc:
            failed += 1
            print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            # Continue with other independent versions.
            continue

        successful += 1
        total_chunks += result.total_chunks
        total_created += result.created_count
        total_existing += result.existing_count

        print(f"  chunks   : {result.total_chunks}")
        print(f"  existing : {result.existing_count}")
        print(f"  created  : {result.created_count}")
        print("  status   : OK")

    # Summary
    print()
    print("=" * 72)
    print("Embedding Backfill Summary")
    print("=" * 72)

    print(f"Versions discovered : {len(version_ids)}")
    print(f"Successful          : {successful}")
    print(f"Failed              : {failed}")
    print(f"Chunks processed    : {total_chunks}")
    print(f"Already existing    : {total_existing}")
    print(f"New embeddings      : {total_created}")

    print("=" * 72)

    if failed:
        print("\nBackfill completed with failures.", file=sys.stderr)
        return 1

    print("\nBackfill completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())