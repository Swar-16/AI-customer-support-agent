from __future__ import annotations
from typing import Any
from sqlalchemy import Select, func, literal, select, String, cast, literal_column
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import TSVECTOR, TSQUERY

from packages.database.models.knowledge.chunk import KnowledgeChunkModel
from packages.database.models.knowledge.document import KnowledgeDocumentModel
from packages.database.models.knowledge.document_version import KnowledgeDocumentVersionModel
from packages.knowledge.domain.enums import KnowledgeDocumentStatus, KnowledgeIngestionStatus, KnowledgeVersionStatus
from packages.knowledge.retrieval.errors import LexicalRetrievalRepositoryError
from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalMethod
from packages.knowledge.retrieval.lexical.repository import LexicalSearchMatch, LexicalSearchRequest


class SQLAlchemyLexicalRetrievalRepository:
    """
    PostgreSQL full-text-search implementation of lexical knowledge retrieval.

    Responsibilities:
      - translate natural-language text into a PostgreSQL tsquery;
      - search canonical published knowledge chunks;
      - rank results using PostgreSQL full-text relevance;
      - enforce retrieval lifecycle invariants;
      - apply caller-supplied business filters;
      - return infrastructure-independent lexical search matches.
    """
    _TEXT_SEARCH_CONFIGURATION = "english"
    _WEIGHT_A = literal_column("'A'::\"char\"")
    _WEIGHT_B = literal_column("'B'::\"char\"")
    _WEIGHT_C = literal_column("'C'::\"char\"")

    def __init__(self, session: Session) -> None:
        self._session = session

    def search(self, request: LexicalSearchRequest) -> tuple[LexicalSearchMatch, ...]:
        if not isinstance(request, LexicalSearchRequest):
            raise TypeError("request must be a LexicalSearchRequest instance.")

        statement = self._build_search_statement(request)

        try:
            rows = self._session.execute(statement).all()

        except SQLAlchemyError as exc:
            raise LexicalRetrievalRepositoryError("Lexical retrieval query failed.") from exc

        matches: list[LexicalSearchMatch] = []

        for row in rows:
            try:
                matches.append(self._row_to_match(row))
            except (TypeError, ValueError) as exc:
                raise LexicalRetrievalRepositoryError("Lexical retrieval returned invalid persisted data.") from exc

        return tuple(matches)

    def _build_search_statement(self, request: LexicalSearchRequest) -> Select[Any]:
        search_vector = self._build_search_vector()
        search_query = func.websearch_to_tsquery(self._TEXT_SEARCH_CONFIGURATION, request.query_text, type_=TSQUERY)
        lexical_score = func.ts_rank_cd(search_vector, search_query).label("lexical_score")

        statement = (select(KnowledgeChunkModel.id.label("chunk_id"),
                            KnowledgeChunkModel.version_id.label("version_id"),
                            KnowledgeDocumentModel.id.label("document_id"),
                            KnowledgeChunkModel.chunk_index.label("chunk_index"),
                            KnowledgeChunkModel.content.label("content"),
                            KnowledgeChunkModel.section_title.label("section_title"),
                            KnowledgeChunkModel.metadata_.label("chunk_metadata"),
                            KnowledgeDocumentModel.title.label("document_title"),
                            lexical_score)
                     .select_from(KnowledgeChunkModel)
                     .join(KnowledgeDocumentVersionModel,
                           KnowledgeDocumentVersionModel.id == KnowledgeChunkModel.version_id)
                     .join(KnowledgeDocumentModel,
                           KnowledgeDocumentModel.id == KnowledgeDocumentVersionModel.document_id)
                     # Knowledge lifecycle invariants.
                     # Callers cannot accidentally retrieve stale/draft/deleted knowledge.
                     .where(KnowledgeDocumentModel.status == KnowledgeDocumentStatus.ACTIVE.value,
                            KnowledgeDocumentVersionModel.status== KnowledgeVersionStatus.PUBLISHED.value,
                            KnowledgeDocumentVersionModel.ingestion_status == KnowledgeIngestionStatus.COMPLETED.value,
                            search_vector.op("@@")(search_query))) # Actual PostgreSQL full-text match.

        statement = self._apply_business_filters(statement=statement, request=request)

        return (statement
                .order_by(lexical_score.desc(), KnowledgeChunkModel.id.asc())
                .limit(request.limit)
        )

    def _build_search_vector(self):
        """
        Construct the lexical representation of a knowledge chunk.

        We search more than raw chunk content:

            document title  -> weight A
            section title   -> weight B
            chunk content   -> weight C

        This means a query matching a policy/document title or section heading receives stronger
        lexical evidence than the same token appearing casually in the body.

        Example:

            Document: "Refund Policy"
            Section:  "Refund Eligibility"
            Content:  "...customer may request..."

        Query:
            "refund eligibility"

        receives stronger lexical relevance than a random occurrence of "refund" deep inside unrelated prose.
        """
        document_title_vector = func.setweight(
            func.to_tsvector(self._TEXT_SEARCH_CONFIGURATION, func.coalesce(KnowledgeDocumentModel.title, "")),
            literal_column("'A'::\"char\""),
            type_=TSVECTOR,
        )

        section_title_vector = func.setweight(
            func.to_tsvector(self._TEXT_SEARCH_CONFIGURATION, func.coalesce(KnowledgeChunkModel.section_title, "")),
            literal_column("'B'::\"char\""),
            type_=TSVECTOR,
        )

        content_vector = func.setweight(
            func.to_tsvector(self._TEXT_SEARCH_CONFIGURATION, func.coalesce(KnowledgeChunkModel.content, "")),
            literal_column("'C'::\"char\""),
            type_=TSVECTOR,
        )

        title_and_section = document_title_vector.op("||", return_type=TSVECTOR)(section_title_vector)

        return title_and_section.op("||", return_type=TSVECTOR)(content_vector)

    @staticmethod
    def _apply_business_filters(*, statement: Select[Any], request: LexicalSearchRequest) -> Select[Any]:
        filters = request.filters

        if filters.document_ids:
            statement = statement.where(KnowledgeDocumentModel.id.in_(filters.document_ids))

        if filters.content_types:
            statement = statement.where(KnowledgeDocumentModel.content_type.in_(filters.content_types))

        if filters.visibilities:
            statement = statement.where(KnowledgeDocumentModel.visibility.in_(filters.visibilities))

        if filters.metadata:
            statement = statement.where(KnowledgeDocumentModel.metadata_.contains(dict(filters.metadata)))

        return statement

    @staticmethod
    def _row_to_match(row: Any) -> LexicalSearchMatch:
        score = float(row.lexical_score)

        candidate = RetrievalCandidate(
            chunk_id=row.chunk_id,
            version_id=row.version_id,
            document_id=row.document_id,
            chunk_index=row.chunk_index,
            content=row.content,
            document_title=row.document_title,
            section_title=row.section_title,
            methods=frozenset({RetrievalMethod.LEXICAL,}),
            metadata=(
                dict(row.chunk_metadata)
                if row.chunk_metadata is not None
                else {}
            ),
        )

        return LexicalSearchMatch(candidate=candidate, score=score)