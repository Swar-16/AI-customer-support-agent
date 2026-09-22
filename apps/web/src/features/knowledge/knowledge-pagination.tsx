// apps/web/src/features/knowledge/knowledge-pagination.tsx

import { ChevronLeft, ChevronRight } from 'lucide-react';

import type { KnowledgeDocumentPage } from './knowledge-contract';

interface KnowledgePaginationProps {
  readonly page: KnowledgeDocumentPage;
  readonly disabled?: boolean;

  readonly onOffsetChange: (offset: number) => void;
}

export function KnowledgePagination({
  page,
  disabled = false,
  onOffsetChange,
}: KnowledgePaginationProps) {
  if (page.total <= page.limit) {
    return null;
  }

  const hasPrevious = page.offset > 0;

  const hasNext = page.next_offset !== null;

  const currentPage = Math.floor(page.offset / page.limit) + 1;

  const totalPages = Math.ceil(page.total / page.limit);

  const firstVisible = page.offset + 1;

  const lastVisible = page.offset + page.count;

  return (
    <nav className="knowledge-pagination" aria-label="Knowledge document pages">
      {hasPrevious && (
        <button
          type="button"
          className="knowledge-pagination__button knowledge-pagination__previous"
          disabled={disabled}
          onClick={() => {
            onOffsetChange(Math.max(0, page.offset - page.limit));
          }}
        >
          <ChevronLeft size={18} aria-hidden="true" />

          <span>Previous</span>
        </button>
      )}

      <div className="knowledge-pagination__summary">
        <strong>
          Page {currentPage} of {totalPages}
        </strong>

        <span>
          Showing {firstVisible}–{lastVisible} of {page.total}
        </span>
      </div>

      {hasNext && (
        <button
          type="button"
          className="knowledge-pagination__button knowledge-pagination__next"
          disabled={disabled}
          onClick={() => {
            if (page.next_offset !== null) {
              onOffsetChange(page.next_offset);
            }
          }}
        >
          <span>Next</span>

          <ChevronRight size={18} aria-hidden="true" />
        </button>
      )}
    </nav>
  );
}
