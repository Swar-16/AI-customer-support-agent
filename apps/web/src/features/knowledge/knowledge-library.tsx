// apps/web/src/features/knowledge/knowledge-library.tsx

import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { BookX, RefreshCw, TriangleAlert, WifiOff } from 'lucide-react';

import {
  knowledgeContentTypeSchema,
  knowledgeDocumentStatusSchema,
  knowledgeVisibilitySchema,
  type KnowledgeDocumentFilters,
} from './knowledge-contract';
import { useKnowledgeDocuments } from './knowledge-queries';
import { CreateDocumentDialog } from './create-document-dialog';
import { KnowledgeDocumentList } from './knowledge-document-list';
import { KnowledgeLibraryToolbar } from './knowledge-library-toolbar';
import { KnowledgePagination } from './knowledge-pagination';
import { KnowledgeUploadDialog } from './knowledge-upload-dialog';

import './knowledge-library.css';

const DOCUMENT_PAGE_SIZE = 8;

type LibraryDialog = 'create-document' | 'upload-document' | null;

function parseOffset(value: string | null): number {
  if (value === null) {
    return 0;
  }

  const parsed = Number(value);

  if (!Number.isSafeInteger(parsed) || parsed < 0) {
    return 0;
  }

  return parsed;
}

function readFilters(searchParams: URLSearchParams): KnowledgeDocumentFilters {
  const statusResult = knowledgeDocumentStatusSchema.safeParse(searchParams.get('status'));

  const contentTypeResult = knowledgeContentTypeSchema.safeParse(searchParams.get('content_type'));

  const visibilityResult = knowledgeVisibilitySchema.safeParse(searchParams.get('visibility'));

  return {
    status: statusResult.success ? statusResult.data : null,

    contentType: contentTypeResult.success ? contentTypeResult.data : null,

    visibility: visibilityResult.success ? visibilityResult.data : null,

    limit: DOCUMENT_PAGE_SIZE,

    offset: parseOffset(searchParams.get('offset')),
  };
}

export function KnowledgeLibrary() {
  const navigate = useNavigate();

  const [searchParams, setSearchParams] = useSearchParams();

  const [openDialog, setOpenDialog] = useState<LibraryDialog>(null);

  const filters = useMemo(() => readFilters(searchParams), [searchParams]);

  const documentsQuery = useKnowledgeDocuments(filters);

  const page = documentsQuery.data;

  const documents = page?.items ?? [];

  const hasData = page !== undefined;

  const isInitialLoading = documentsQuery.isPending && !hasData;

  const isRefreshing = documentsQuery.isFetching && !isInitialLoading;

  const hasBlockingError = documentsQuery.isError && !hasData;

  const hasStaleError = documentsQuery.isError && hasData;

  const hasActiveFilters =
    filters.status !== null || filters.contentType !== null || filters.visibility !== null;

  const hasOutOfRangePage =
    !isInitialLoading &&
    page !== undefined &&
    page.total > 0 &&
    page.items.length === 0 &&
    page.offset > 0;

  function updateFilters(
    nextFilters: Pick<KnowledgeDocumentFilters, 'status' | 'contentType' | 'visibility'>,
  ) {
    const next = new URLSearchParams(searchParams);

    if (nextFilters.status === null) {
      next.delete('status');
    } else {
      next.set('status', nextFilters.status);
    }

    if (nextFilters.contentType === null) {
      next.delete('content_type');
    } else {
      next.set('content_type', nextFilters.contentType);
    }

    if (nextFilters.visibility === null) {
      next.delete('visibility');
    } else {
      next.set('visibility', nextFilters.visibility);
    }

    /*
     * Every filter change starts from the
     * first page.
     */
    next.delete('offset');

    setSearchParams(next, {
      replace: true,
    });
  }

  function updateOffset(offset: number) {
    const next = new URLSearchParams(searchParams);

    if (offset <= 0) {
      next.delete('offset');
    } else {
      next.set('offset', String(offset));
    }

    setSearchParams(next, {
      replace: true,
    });

    window.requestAnimationFrame(() => {
      document.getElementById('knowledge-library-results')?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      });
    });
  }

  function refreshDocuments() {
    if (documentsQuery.isFetching) {
      return;
    }

    void documentsQuery.refetch();
  }

  function closeDialog() {
    setOpenDialog(null);
  }

  function openCreatedDocument(documentId: string) {
    setOpenDialog(null);

    void navigate(`/knowledge/documents/${documentId}`);
  }

  return (
    <section className="knowledge-library" aria-labelledby="knowledge-library-title">
      <div className="knowledge-library__heading">
        <div>
          <p className="knowledge-library__eyebrow">Trusted source material</p>

          <h2 id="knowledge-library-title">Knowledge documents</h2>

          <p>Create, process, and publish immutable source versions for the support AI.</p>
        </div>

        {page !== undefined && (
          <p className="knowledge-library__count" aria-live="polite">
            <strong>{new Intl.NumberFormat().format(page.total)}</strong>

            <span>{page.total === 1 ? 'document' : 'documents'}</span>
          </p>
        )}
      </div>

      <KnowledgeLibraryToolbar
        filters={filters}
        isRefreshing={isRefreshing}
        onFiltersChange={updateFilters}
        onRefresh={refreshDocuments}
        onCreateDocument={() => {
          setOpenDialog('create-document');
        }}
        onUploadDocument={() => {
          setOpenDialog('upload-document');
        }}
      />

      {isRefreshing && (
        <div
          className="knowledge-library__status"
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          <RefreshCw size={16} className="is-spinning" aria-hidden="true" />

          <span>Updating document library…</span>
        </div>
      )}

      {hasStaleError && (
        <section className="knowledge-library__notice" role="alert">
          <WifiOff size={19} aria-hidden="true" />

          <div>
            <strong>The latest document state could not be loaded</strong>

            <p>Showing the most recently available data. No automatic mutation was retried.</p>
          </div>

          <button type="button" onClick={refreshDocuments} disabled={documentsQuery.isFetching}>
            <RefreshCw size={17} aria-hidden="true" />

            <span>Try again</span>
          </button>
        </section>
      )}

      {hasBlockingError ? (
        <section className="knowledge-library__error knowledge-surface" role="alert">
          <span className="knowledge-library__state-icon" aria-hidden="true">
            <TriangleAlert size={27} />
          </span>

          <p className="knowledge-library__eyebrow">Library unavailable</p>

          <h2>Documents could not be loaded</h2>

          <p>{documentsQuery.error.message}</p>

          {documentsQuery.error.traceId !== null && (
            <p className="knowledge-library__trace">
              Reference: <code>{documentsQuery.error.traceId}</code>
            </p>
          )}

          <button
            type="button"
            className="knowledge-library__retry"
            disabled={documentsQuery.isFetching}
            onClick={refreshDocuments}
          >
            <RefreshCw
              size={18}
              aria-hidden="true"
              className={documentsQuery.isFetching ? 'is-spinning' : undefined}
            />

            <span>{documentsQuery.isFetching ? 'Trying again…' : 'Try again'}</span>
          </button>
        </section>
      ) : hasOutOfRangePage ? (
        <section
          className="knowledge-library__empty knowledge-surface"
          aria-labelledby="knowledge-empty-page-title"
        >
          <span className="knowledge-library__state-icon" aria-hidden="true">
            <BookX size={28} />
          </span>

          <p className="knowledge-library__eyebrow">Page unavailable</p>

          <h2 id="knowledge-empty-page-title">This document page is empty</h2>

          <p>
            The library may have changed since this page was opened. Return to the previous page to
            continue browsing.
          </p>

          <div className="knowledge-library__empty-actions">
            <button
              type="button"
              className="knowledge-library__primary-action"
              onClick={() => {
                updateOffset(Math.max(0, filters.offset - filters.limit));
              }}
            >
              Previous page
            </button>
          </div>
        </section>
      ) : !isInitialLoading && documents.length === 0 ? (
        <section
          className="knowledge-library__empty knowledge-surface"
          aria-labelledby="knowledge-empty-title"
        >
          <span className="knowledge-library__state-icon" aria-hidden="true">
            <BookX size={28} />
          </span>

          <p className="knowledge-library__eyebrow">Nothing to show</p>

          <h2 id="knowledge-empty-title">No documents match this view</h2>

          <p>
            {hasActiveFilters
              ? 'Change or clear the filters to inspect another part of the library.'
              : 'Create document metadata or upload a source file to begin building the knowledge library.'}
          </p>

          <div className="knowledge-library__empty-actions">
            {hasActiveFilters ? (
              <button
                type="button"
                className="knowledge-library__secondary-action"
                onClick={() => {
                  updateFilters({
                    status: null,
                    contentType: null,
                    visibility: null,
                  });
                }}
              >
                Clear filters
              </button>
            ) : (
              <>
                <button
                  type="button"
                  className="knowledge-library__secondary-action"
                  onClick={() => {
                    setOpenDialog('create-document');
                  }}
                >
                  Create document
                </button>

                <button
                  type="button"
                  className="knowledge-library__primary-action"
                  onClick={() => {
                    setOpenDialog('upload-document');
                  }}
                >
                  Upload document
                </button>
              </>
            )}
          </div>
        </section>
      ) : (
        <>
          <KnowledgeDocumentList documents={documents} isInitialLoading={isInitialLoading} />

          {page !== undefined && page.total > 0 && (
            <KnowledgePagination
              page={page}
              disabled={documentsQuery.isFetching}
              onOffsetChange={updateOffset}
            />
          )}
        </>
      )}

      <CreateDocumentDialog
        open={openDialog === 'create-document'}
        onClose={closeDialog}
        onCreated={openCreatedDocument}
      />

      <KnowledgeUploadDialog
        open={openDialog === 'upload-document'}
        onClose={closeDialog}
        onUploaded={openCreatedDocument}
      />
    </section>
  );
}
