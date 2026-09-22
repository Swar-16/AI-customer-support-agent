// apps/web/src/features/knowledge/knowledge-document-detail.tsx

import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import {
  AlertTriangle,
  Archive,
  ArrowLeft,
  BookOpenText,
  CalendarDays,
  Eye,
  FileStack,
  LoaderCircle,
  RefreshCcw,
  Upload,
} from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import { knowledgeIdSchema } from './knowledge-contract';
import {
  formatContentType,
  formatDocumentStatus,
  formatKnowledgeDate,
  formatKnowledgeVisibility,
} from './knowledge-formatters';
import { useArchiveKnowledgeDocument, useKnowledgeDocument } from './knowledge-queries';
import { KnowledgeConfirmationDialog } from './knowledge-confirmation-dialog';
import { KnowledgeUploadVersionDialog } from './knowledge-upload-version-dialog';
import { KnowledgeVersionList } from './knowledge-version-list';

import './knowledge-document-detail.css';

function getTraceId(error: Error | null): string | null {
  return error instanceof SafeApiError ? error.traceId : null;
}

function isNotFoundError(error: Error | null): boolean {
  return error instanceof SafeApiError && error.status === 404;
}

export function KnowledgeDocumentDetail() {
  const navigate = useNavigate();

  const { documentId: routeDocumentId } = useParams<{
    documentId: string;
  }>();

  const parsedDocumentId = knowledgeIdSchema.safeParse(routeDocumentId);

  const documentId = parsedDocumentId.success ? parsedDocumentId.data : null;

  const documentQuery = useKnowledgeDocument(documentId);

  const archiveDocument = useArchiveKnowledgeDocument();

  const [archiveOpen, setArchiveOpen] = useState(false);

  const [uploadVersionOpen, setUploadVersionOpen] = useState(false);

  function openArchiveDialog() {
    archiveDocument.reset();
    setArchiveOpen(true);
  }

  function closeArchiveDialog() {
    if (archiveDocument.isPending) {
      return;
    }

    archiveDocument.reset();
    setArchiveOpen(false);
  }

  function confirmArchive() {
    if (documentId === null || archiveDocument.isPending) {
      return;
    }

    archiveDocument.mutate(documentId, {
      onSuccess: () => {
        setArchiveOpen(false);
      },
      onError: () => {
        setArchiveOpen(false);
      },
    });
  }

  if (documentId === null) {
    return (
      <DocumentState
        kind="invalid"
        title="Invalid document address"
        description="The document identifier in this address is not valid."
        onRetry={null}
      />
    );
  }

  if (documentQuery.isPending) {
    return (
      <div className="knowledge-document-detail__loading" role="status" aria-live="polite">
        <LoaderCircle size={28} className="is-spinning" aria-hidden="true" />

        <span>Loading the document workspace…</span>
      </div>
    );
  }

  if (documentQuery.isError) {
    const notFound = isNotFoundError(documentQuery.error);

    return (
      <DocumentState
        kind={notFound ? 'not-found' : 'error'}
        title={notFound ? 'Document not found' : 'Document could not be loaded'}
        description={
          notFound
            ? 'This document may have been removed, or the address may no longer be available.'
            : documentQuery.error.message
        }
        traceId={getTraceId(documentQuery.error)}
        onRetry={
          notFound
            ? null
            : () => {
                void documentQuery.refetch();
              }
        }
      />
    );
  }

  const document = documentQuery.data;

  const isActive = document.status === 'active';

  const hasPublishedVersion = document.published_version_id !== null;

  const archiveUnconfirmed =
    archiveDocument.isError &&
    (archiveDocument.error.kind === 'network' || archiveDocument.error.kind === 'timeout');

  return (
    <section className="knowledge-document-detail">
      <nav className="knowledge-document-detail__breadcrumb" aria-label="Knowledge navigation">
        <Link to="/knowledge">
          <ArrowLeft size={16} aria-hidden="true" />

          <span>Knowledge library</span>
        </Link>

        <span aria-hidden="true">/</span>

        <span aria-current="page">{document.title}</span>
      </nav>

      <header className="knowledge-document-detail__header">
        <div className="knowledge-document-detail__identity">
          <span className="knowledge-document-detail__icon" aria-hidden="true">
            <BookOpenText size={27} />
          </span>

          <div>
            <div className="knowledge-document-detail__eyebrow">
              <span>{formatContentType(document.content_type)}</span>

              <span className={`knowledge-status knowledge-status--${document.status}`}>
                {formatDocumentStatus(document.status)}
              </span>
            </div>

            <h2>{document.title}</h2>

            <p>{document.description ?? 'No description has been provided for this document.'}</p>
          </div>
        </div>

        <div className="knowledge-document-detail__actions">
          {isActive && (
            <>
              <button
                type="button"
                className="knowledge-document-detail__action knowledge-document-detail__action--outline"
                onClick={() => {
                  setUploadVersionOpen(true);
                }}
              >
                <Upload size={17} aria-hidden="true" />

                <span>Upload version</span>
              </button>

              <button
                type="button"
                className="knowledge-document-detail__action knowledge-document-detail__action--danger"
                onClick={openArchiveDialog}
              >
                <Archive size={17} aria-hidden="true" />

                <span>Archive</span>
              </button>
            </>
          )}
        </div>
      </header>

      {document.status !== 'active' && (
        <div className="knowledge-document-detail__notice" role="status">
          <AlertTriangle size={19} aria-hidden="true" />

          <div>
            <strong>This document is {formatDocumentStatus(document.status).toLowerCase()}.</strong>

            <span>New versions and lifecycle actions are unavailable for this document.</span>
          </div>
        </div>
      )}

      {archiveUnconfirmed && (
        <div
          className="knowledge-document-detail__notice knowledge-document-detail__notice--warning"
          role="alert"
        >
          <AlertTriangle size={19} aria-hidden="true" />

          <div>
            <strong>The archive result could not be confirmed.</strong>

            <span>Refresh this document before attempting the action again.</span>
          </div>

          <button
            type="button"
            onClick={() => {
              archiveDocument.reset();
              void documentQuery.refetch();
            }}
          >
            <RefreshCcw size={15} aria-hidden="true" />

            <span>Refresh</span>
          </button>
        </div>
      )}

      {archiveDocument.isError && !archiveUnconfirmed && (
        <div
          className="knowledge-document-detail__notice knowledge-document-detail__notice--error"
          role="alert"
        >
          <AlertTriangle size={19} aria-hidden="true" />

          <div>
            <strong>The document could not be archived.</strong>

            <span>{archiveDocument.error.message}</span>

            {archiveDocument.error.traceId !== null && (
              <small>
                Reference: <code>{archiveDocument.error.traceId}</code>
              </small>
            )}
          </div>

          <button
            type="button"
            onClick={() => {
              archiveDocument.reset();
            }}
          >
            Dismiss
          </button>
        </div>
      )}

      <dl className="knowledge-document-detail__metadata">
        <div>
          <dt>
            <Eye size={17} aria-hidden="true" />
            Visibility
          </dt>

          <dd>{formatKnowledgeVisibility(document.visibility)}</dd>
        </div>

        <div>
          <dt>
            <FileStack size={17} aria-hidden="true" />
            Versions
          </dt>

          <dd>{new Intl.NumberFormat().format(document.version_count)}</dd>
        </div>

        <div>
          <dt>
            <BookOpenText size={17} aria-hidden="true" />
            Published version
          </dt>

          <dd>{hasPublishedVersion ? 'Available' : 'Not published'}</dd>
        </div>

        <div>
          <dt>
            <CalendarDays size={17} aria-hidden="true" />
            Created
          </dt>

          <dd>
            <time dateTime={document.created_at}>{formatKnowledgeDate(document.created_at)}</time>
          </dd>
        </div>

        <div>
          <dt>
            <RefreshCcw size={17} aria-hidden="true" />
            Last updated
          </dt>

          <dd>
            <time dateTime={document.updated_at}>{formatKnowledgeDate(document.updated_at)}</time>
          </dd>
        </div>
      </dl>

      <section
        className="knowledge-document-detail__versions"
        aria-labelledby="knowledge-document-versions-heading"
      >
        <div className="knowledge-document-detail__section-heading">
          <div>
            <p>Immutable history</p>

            <h3 id="knowledge-document-versions-heading">Document versions</h3>

            <span>Inspect processing, embedding, and publication state for every version.</span>
          </div>

          {documentQuery.isFetching && (
            <span className="knowledge-document-detail__refreshing" role="status">
              <LoaderCircle size={15} className="is-spinning" aria-hidden="true" />
              Refreshing
            </span>
          )}
        </div>

        <KnowledgeVersionList
          key={document.document_id}
          documentId={document.document_id}
          publishedVersionId={document.published_version_id}
        />
      </section>

      <KnowledgeConfirmationDialog
        open={archiveOpen}
        title="Archive this document?"
        description={`Archive “${document.title}” and prevent new versions or publication actions. Existing history will remain available for audit purposes.`}
        confirmLabel="Archive document"
        pendingLabel="Archiving…"
        pending={archiveDocument.isPending}
        onConfirm={confirmArchive}
        onClose={closeArchiveDialog}
      />

      <KnowledgeUploadVersionDialog
        open={uploadVersionOpen}
        documentId={document.document_id}
        documentTitle={document.title}
        onClose={() => {
          setUploadVersionOpen(false);
        }}
        onUploaded={(versionId: string) => {
          setUploadVersionOpen(false);

          navigate(`/knowledge/documents/${document.document_id}/versions/${versionId}`);
        }}
      />
    </section>
  );
}

interface DocumentStateProps {
  readonly kind: 'invalid' | 'not-found' | 'error';

  readonly title: string;
  readonly description: string;
  readonly traceId?: string | null;
  readonly onRetry: (() => void) | null;
}

function DocumentState({ kind, title, description, traceId = null, onRetry }: DocumentStateProps) {
  return (
    <section
      className={`knowledge-document-detail__state knowledge-document-detail__state--${kind}`}
    >
      <div>
        <span className="knowledge-document-detail__state-icon" aria-hidden="true">
          <AlertTriangle size={27} />
        </span>

        <h2>{title}</h2>

        <p>{description}</p>

        {traceId !== null && (
          <small>
            Reference: <code>{traceId}</code>
          </small>
        )}

        <div className="knowledge-document-detail__state-actions">
          {onRetry !== null && (
            <button type="button" onClick={onRetry}>
              <RefreshCcw size={16} aria-hidden="true" />

              <span>Try again</span>
            </button>
          )}

          <Link to="/knowledge">
            <ArrowLeft size={16} aria-hidden="true" />

            <span>Return to knowledge library</span>
          </Link>
        </div>
      </div>
    </section>
  );
}
