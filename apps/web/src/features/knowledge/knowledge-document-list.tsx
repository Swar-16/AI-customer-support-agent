// apps/web/src/features/knowledge/knowledge-document-list.tsx

import type { KnowledgeDocument } from './knowledge-contract';
import { KnowledgeDocumentCard } from './knowledge-document-card';

interface KnowledgeDocumentListProps {
  readonly documents: readonly KnowledgeDocument[];

  readonly isInitialLoading: boolean;
}

const skeletonItems = [
  'skeleton-1',
  'skeleton-2',
  'skeleton-3',
  'skeleton-4',
  'skeleton-5',
  'skeleton-6',
] as const;

function KnowledgeDocumentCardSkeleton() {
  return (
    <article
      className="knowledge-document-card knowledge-document-card--skeleton knowledge-surface"
      aria-hidden="true"
    >
      <div className="knowledge-document-card__topline">
        <span className="knowledge-skeleton knowledge-skeleton--icon" />

        <span className="knowledge-skeleton knowledge-skeleton--badge" />
      </div>

      <div className="knowledge-document-card__body">
        <span className="knowledge-skeleton knowledge-skeleton--eyebrow" />

        <span className="knowledge-skeleton knowledge-skeleton--title" />

        <div className="knowledge-document-card__skeleton-copy">
          <span className="knowledge-skeleton knowledge-skeleton--line" />
          <span className="knowledge-skeleton knowledge-skeleton--line" />
          <span className="knowledge-skeleton knowledge-skeleton--line-short" />
        </div>
      </div>

      <div className="knowledge-document-card__metadata">
        <span className="knowledge-skeleton knowledge-skeleton--metadata" />
        <span className="knowledge-skeleton knowledge-skeleton--metadata" />
      </div>
    </article>
  );
}

export function KnowledgeDocumentList({ documents, isInitialLoading }: KnowledgeDocumentListProps) {
  if (isInitialLoading) {
    return (
      <section
        className="knowledge-document-results"
        id="knowledge-library-results"
        aria-busy="true"
        aria-labelledby="knowledge-loading-title"
      >
        <p id="knowledge-loading-title" className="knowledge-visually-hidden" role="status">
          Loading knowledge documents.
        </p>

        <div className="knowledge-document-grid" aria-hidden="true">
          {skeletonItems.map((item) => (
            <KnowledgeDocumentCardSkeleton key={item} />
          ))}
        </div>
      </section>
    );
  }

  return (
    <section
      className="knowledge-document-results"
      id="knowledge-library-results"
      aria-labelledby="knowledge-results-title"
    >
      <h2 id="knowledge-results-title" className="knowledge-visually-hidden">
        Document results
      </h2>

      <ul className="knowledge-document-grid">
        {documents.map((document) => (
          <li key={document.document_id}>
            <KnowledgeDocumentCard document={document} />
          </li>
        ))}
      </ul>
    </section>
  );
}
