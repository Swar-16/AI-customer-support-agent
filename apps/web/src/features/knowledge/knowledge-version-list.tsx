// apps/web/src/features/knowledge/knowledge-version-list.tsx

import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileCode2,
  FileStack,
  Hash,
  RefreshCcw,
} from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import type { KnowledgeVersion } from './knowledge-contract';
import {
  formatIngestionStatus,
  formatKnowledgeDate,
  formatSourceType,
  formatVersionStatus,
  shortenContentHash,
} from './knowledge-formatters';
import { useKnowledgeVersions } from './knowledge-queries';

interface KnowledgeVersionListProps {
  readonly documentId: string;

  readonly publishedVersionId: string | null;
}

const PAGE_SIZE = 10;

export function KnowledgeVersionList({
  documentId,
  publishedVersionId,
}: KnowledgeVersionListProps) {
  const [offset, setOffset] = useState(0);

  const filters = useMemo(
    () => ({
      status: null,
      ingestionStatus: null,
      sourceType: null,
      limit: PAGE_SIZE,
      offset,
    }),
    [offset],
  );

  const versionsQuery = useKnowledgeVersions(documentId, filters);

  if (versionsQuery.isPending && versionsQuery.data === undefined) {
    return <KnowledgeVersionSkeleton />;
  }

  if (versionsQuery.isError && versionsQuery.data === undefined) {
    return (
      <KnowledgeVersionError
        error={versionsQuery.error}
        onRetry={() => {
          void versionsQuery.refetch();
        }}
      />
    );
  }

  const page = versionsQuery.data;

  if (page === undefined) {
    return null;
  }

  if (page.items.length === 0 && page.offset === 0) {
    return (
      <div className="knowledge-version-list__empty">
        <span aria-hidden="true">
          <FileStack size={26} />
        </span>

        <h4>No versions yet</h4>

        <p>Upload the first source version to begin this document&apos;s immutable history.</p>
      </div>
    );
  }

  if (page.items.length === 0 && page.offset > 0) {
    return (
      <div className="knowledge-version-list__empty">
        <span aria-hidden="true">
          <FileStack size={26} />
        </span>

        <h4>This page is empty</h4>

        <p>Return to the previous page to continue browsing versions.</p>

        <button
          type="button"
          onClick={() => {
            setOffset(Math.max(0, page.offset - page.limit));
          }}
        >
          <ArrowLeft size={16} aria-hidden="true" />

          <span>Previous page</span>
        </button>
      </div>
    );
  }

  const firstVisible = page.offset + 1;

  const lastVisible = page.offset + page.count;

  return (
    <div className="knowledge-version-list" aria-busy={versionsQuery.isFetching}>
      {versionsQuery.isError && (
        <div className="knowledge-version-list__stale-warning" role="alert">
          <AlertTriangle size={17} aria-hidden="true" />

          <span>The latest version data could not be loaded. Showing the previous result.</span>

          <button
            type="button"
            onClick={() => {
              void versionsQuery.refetch();
            }}
          >
            Retry
          </button>
        </div>
      )}

      <ol className="knowledge-version-list__items">
        {page.items.map((version) => (
          <KnowledgeVersionRow
            key={version.version_id}
            version={version}
            published={version.version_id === publishedVersionId}
          />
        ))}
      </ol>

      <footer className="knowledge-version-list__pagination">
        <p>
          Showing{' '}
          <strong>
            {firstVisible}–{lastVisible}
          </strong>{' '}
          of <strong>{new Intl.NumberFormat().format(page.total)}</strong> versions
        </p>

        <div>
          <button
            type="button"
            disabled={page.offset === 0 || versionsQuery.isFetching}
            onClick={() => {
              setOffset(Math.max(0, page.offset - page.limit));
            }}
          >
            <ArrowLeft size={16} aria-hidden="true" />

            <span>Previous</span>
          </button>

          <button
            type="button"
            disabled={page.next_offset === null || versionsQuery.isFetching}
            onClick={() => {
              if (page.next_offset !== null) {
                setOffset(page.next_offset);
              }
            }}
          >
            <span>Next</span>

            <ArrowRight size={16} aria-hidden="true" />
          </button>
        </div>
      </footer>
    </div>
  );
}

interface KnowledgeVersionRowProps {
  readonly version: KnowledgeVersion;

  readonly published: boolean;
}

function KnowledgeVersionRow({ version, published }: KnowledgeVersionRowProps) {
  const failed = version.status === 'failed' || version.ingestion_status === 'failed';

  return (
    <li>
      <article
        className={[
          'knowledge-version-row',
          published ? 'is-current-published' : '',
          failed ? 'has-failed' : '',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        <div className="knowledge-version-row__rail">
          <span aria-hidden="true">
            {published ? <CheckCircle2 size={18} /> : <Clock3 size={18} />}
          </span>
        </div>

        <div className="knowledge-version-row__content">
          <div className="knowledge-version-row__heading">
            <div>
              <p>Version {version.version_number}</p>

              {published && (
                <span className="knowledge-version-row__published">Current published</span>
              )}
            </div>

            <div className="knowledge-version-row__statuses">
              <span className={`knowledge-status knowledge-status--${version.status}`}>
                {formatVersionStatus(version.status)}
              </span>

              <span
                className={`knowledge-ingestion-status knowledge-ingestion-status--${version.ingestion_status}`}
              >
                {formatIngestionStatus(version.ingestion_status)}
              </span>
            </div>
          </div>

          <dl className="knowledge-version-row__metadata">
            <div>
              <dt>
                <FileCode2 size={15} aria-hidden="true" />
                Source
              </dt>

              <dd>{version.source_name ?? formatSourceType(version.source_type)}</dd>
            </div>

            <div>
              <dt>
                <Hash size={15} aria-hidden="true" />
                Content hash
              </dt>

              <dd>
                <code title={version.content_hash}>{shortenContentHash(version.content_hash)}</code>
              </dd>
            </div>

            <div>
              <dt>
                <Clock3 size={15} aria-hidden="true" />
                Created
              </dt>

              <dd>
                <time dateTime={version.created_at}>{formatKnowledgeDate(version.created_at)}</time>
              </dd>
            </div>
          </dl>

          {failed && version.failure_code !== null && (
            <div className="knowledge-version-row__failure" role="status">
              <AlertTriangle size={15} aria-hidden="true" />

              <span>
                Failure code: <code>{version.failure_code}</code>
              </span>
            </div>
          )}

          <Link
            className="knowledge-version-row__link"
            to={`/knowledge/documents/${version.document_id}/versions/${version.version_id}`}
            aria-label={`Inspect version ${version.version_number}`}
          >
            <span>Inspect version</span>

            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
      </article>
    </li>
  );
}

function KnowledgeVersionSkeleton() {
  return (
    <div
      className="knowledge-version-list__skeleton"
      role="status"
      aria-label="Loading document versions"
    >
      {Array.from({ length: 4 }, (_, index) => (
        <div
          className="knowledge-version-row knowledge-version-row--skeleton"
          key={index}
          aria-hidden="true"
        >
          <span className="knowledge-version-skeleton knowledge-version-skeleton--rail" />

          <div>
            <span className="knowledge-version-skeleton knowledge-version-skeleton--title" />

            <span className="knowledge-version-skeleton knowledge-version-skeleton--line" />

            <span className="knowledge-version-skeleton knowledge-version-skeleton--line-short" />
          </div>
        </div>
      ))}

      <span className="knowledge-visually-hidden">Loading document versions…</span>
    </div>
  );
}

interface KnowledgeVersionErrorProps {
  readonly error: Error;
  readonly onRetry: () => void;
}

function KnowledgeVersionError({ error, onRetry }: KnowledgeVersionErrorProps) {
  const traceId = error instanceof SafeApiError ? error.traceId : null;

  return (
    <div className="knowledge-version-list__error" role="alert">
      <span aria-hidden="true">
        <AlertTriangle size={25} />
      </span>

      <h4>Versions could not be loaded</h4>

      <p>{error.message}</p>

      {traceId !== null && (
        <small>
          Reference: <code>{traceId}</code>
        </small>
      )}

      <button type="button" onClick={onRetry}>
        <RefreshCcw size={16} aria-hidden="true" />

        <span>Try again</span>
      </button>
    </div>
  );
}
