// apps/web/src/features/knowledge/knowledge-version-detail.tsx

import { useState } from 'react';
import { Link, useParams } from 'react-router';
import {
  AlertTriangle,
  ArrowLeft,
  BookOpenText,
  Boxes,
  CheckCircle2,
  Clock3,
  Database,
  FileCode2,
  Hash,
  LoaderCircle,
  RefreshCcw,
  Rocket,
  Sparkles,
} from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import { knowledgeIdSchema } from './knowledge-contract';
import {
  describeIngestionStatus,
  describeVersionStatus,
  formatCharacterCount,
  formatFailureCode,
  formatIngestionStatus,
  formatKnowledgeDate,
  formatOptionalKnowledgeDate,
  formatSourceType,
  formatVersionNumber,
  formatVersionStatus,
  shortenContentHash,
} from './knowledge-formatters';
import {
  useEmbedKnowledgeVersion,
  useKnowledgeDocument,
  useKnowledgeVersion,
  useProcessKnowledgeVersion,
  usePublishKnowledgeVersion,
} from './knowledge-queries';
import { KnowledgeConfirmationDialog } from './knowledge-confirmation-dialog';

import './knowledge-version-detail.css';

export function KnowledgeVersionDetail() {
  const { documentId: routeDocumentId, versionId: routeVersionId } = useParams<{
    documentId: string;
    versionId: string;
  }>();

  const documentIdResult = knowledgeIdSchema.safeParse(routeDocumentId);

  const versionIdResult = knowledgeIdSchema.safeParse(routeVersionId);

  const documentId = documentIdResult.success ? documentIdResult.data : null;

  const versionId = versionIdResult.success ? versionIdResult.data : null;

  const documentQuery = useKnowledgeDocument(documentId);

  const versionQuery = useKnowledgeVersion(versionId);

  const processVersion = useProcessKnowledgeVersion();

  const embedVersion = useEmbedKnowledgeVersion();

  const publishVersion = usePublishKnowledgeVersion();

  const [publishConfirmationOpen, setPublishConfirmationOpen] = useState(false);

  const [embeddedVersionId, setEmbeddedVersionId] = useState<string | null>(null);

  if (documentId === null || versionId === null) {
    return (
      <VersionPageState
        title="Invalid version address"
        description="The document or version identifier in this address is not valid."
        traceId={null}
        onRetry={null}
      />
    );
  }

  const resolvedDocumentId: string = documentId;

  const resolvedVersionId: string = versionId;

  const initialLoading =
    (documentQuery.isPending && documentQuery.data === undefined) ||
    (versionQuery.isPending && versionQuery.data === undefined);

  if (initialLoading) {
    return (
      <div className="knowledge-version-detail__loading" role="status" aria-live="polite">
        <LoaderCircle size={28} className="is-spinning" aria-hidden="true" />

        <span>Loading version workspace…</span>
      </div>
    );
  }

  const queryError = documentQuery.error ?? versionQuery.error;

  if (queryError !== null || documentQuery.data === undefined || versionQuery.data === undefined) {
    return (
      <VersionPageState
        title={isNotFoundError(queryError) ? 'Version not found' : 'Version could not be loaded'}
        description={queryError?.message ?? 'The requested version is unavailable.'}
        traceId={getTraceId(queryError)}
        onRetry={
          isNotFoundError(queryError)
            ? null
            : () => {
                void Promise.all([documentQuery.refetch(), versionQuery.refetch()]);
              }
        }
      />
    );
  }

  const document = documentQuery.data;
  const version = versionQuery.data;

  if (version.document_id !== document.document_id) {
    return (
      <VersionPageState
        title="Version does not belong to this document"
        description="The requested version exists, but it is not part of the document represented by this address."
        traceId={null}
        onRetry={null}
      />
    );
  }

  const documentActive = document.status === 'active';

  const embeddingConfirmed =
    embeddedVersionId === version.version_id ||
    version.status === 'published' ||
    version.status === 'superseded';

  const canProcess =
    documentActive &&
    ((version.status === 'draft' && version.ingestion_status === 'pending') ||
      (version.status === 'failed' && version.ingestion_status === 'failed'));

  const canEmbed =
    documentActive &&
    version.status === 'ready' &&
    version.ingestion_status === 'completed' &&
    !embeddingConfirmed;

  const canPublish =
    documentActive &&
    version.status === 'ready' &&
    version.ingestion_status === 'completed' &&
    embeddingConfirmed;

  const processing = processVersion.isPending;

  const embedding = embedVersion.isPending;

  const publishing = publishVersion.isPending;

  const lifecyclePending = processing || embedding || publishing;

  const lifecycleError = processVersion.error ?? embedVersion.error ?? publishVersion.error;

  const lifecycleUnconfirmed =
    lifecycleError instanceof SafeApiError &&
    (lifecycleError.kind === 'network' || lifecycleError.kind === 'timeout');

  function resetLifecycleMutations() {
    processVersion.reset();
    embedVersion.reset();
    publishVersion.reset();
  }

  function refreshWorkspace() {
    resetLifecycleMutations();

    void Promise.all([documentQuery.refetch(), versionQuery.refetch()]);
  }

  function runProcessing() {
    if (!canProcess || lifecyclePending) {
      return;
    }

    setEmbeddedVersionId(null);
    resetLifecycleMutations();

    processVersion.mutate({
      documentId: resolvedDocumentId,
      versionId: resolvedVersionId,
    });
  }

  function runEmbedding() {
    if (!canEmbed || lifecyclePending) {
      return;
    }

    resetLifecycleMutations();

    embedVersion.mutate(
      {
        documentId: resolvedDocumentId,
        versionId: resolvedVersionId,
      },
      {
        onSuccess: (response) => {
          setEmbeddedVersionId(response.version_id);
        },
      },
    );
  }

  function confirmPublication() {
    if (!canPublish || lifecyclePending) {
      return;
    }

    resetLifecycleMutations();

    publishVersion.mutate(
      {
        documentId: resolvedDocumentId,
        versionId: resolvedVersionId,
      },
      {
        onSuccess: () => {
          setPublishConfirmationOpen(false);
        },

        onError: () => {
          setPublishConfirmationOpen(false);
        },
      },
    );
  }

  const refreshing = documentQuery.isFetching || versionQuery.isFetching;

  return (
    <section className="knowledge-version-detail">
      <nav className="knowledge-version-detail__breadcrumb" aria-label="Knowledge navigation">
        <Link to="/knowledge">Knowledge library</Link>

        <span aria-hidden="true">/</span>

        <Link to={`/knowledge/documents/${document.document_id}`}>{document.title}</Link>

        <span aria-hidden="true">/</span>

        <span aria-current="page">{formatVersionNumber(version.version_number)}</span>
      </nav>

      <header className="knowledge-version-detail__header">
        <div className="knowledge-version-detail__identity">
          <span className="knowledge-version-detail__icon" aria-hidden="true">
            <FileCode2 size={27} />
          </span>

          <div>
            <div className="knowledge-version-detail__eyebrow">
              <span>{formatVersionNumber(version.version_number)}</span>

              {version.is_current_published_version && (
                <span className="knowledge-version-detail__current">
                  <CheckCircle2 size={14} aria-hidden="true" />
                  Current published
                </span>
              )}
            </div>

            <h2>{version.document_title}</h2>

            <p>
              Inspect the immutable source, ingestion state, and supported lifecycle operations for
              this version.
            </p>
          </div>
        </div>

        <div className="knowledge-version-detail__header-actions">
          {refreshing && (
            <span className="knowledge-version-detail__refreshing" role="status">
              <LoaderCircle size={15} className="is-spinning" aria-hidden="true" />
              Refreshing
            </span>
          )}

          <button
            type="button"
            disabled={refreshing || lifecyclePending}
            onClick={refreshWorkspace}
          >
            <RefreshCcw size={16} aria-hidden="true" />

            <span>Refresh</span>
          </button>
        </div>
      </header>

      {!documentActive && (
        <div className="knowledge-version-detail__notice" role="status">
          <AlertTriangle size={19} aria-hidden="true" />

          <div>
            <strong>Parent document is not active.</strong>

            <span>
              Processing and publication are unavailable. Historical embedding remains available
              only when the version state permits it.
            </span>
          </div>
        </div>
      )}

      {lifecycleError !== null && (
        <div
          className={[
            'knowledge-version-detail__notice',
            lifecycleUnconfirmed
              ? 'knowledge-version-detail__notice--warning'
              : 'knowledge-version-detail__notice--error',
          ].join(' ')}
          role="alert"
        >
          <AlertTriangle size={19} aria-hidden="true" />

          <div>
            <strong>
              {lifecycleUnconfirmed
                ? 'The action result could not be confirmed.'
                : 'The lifecycle action failed.'}
            </strong>

            <span>
              {lifecycleUnconfirmed
                ? 'Refresh this version before attempting the action again.'
                : lifecycleError.message}
            </span>

            {getTraceId(lifecycleError) !== null && (
              <small>
                Reference: <code>{getTraceId(lifecycleError)}</code>
              </small>
            )}
          </div>

          <button
            type="button"
            onClick={lifecycleUnconfirmed ? refreshWorkspace : resetLifecycleMutations}
          >
            {lifecycleUnconfirmed ? 'Refresh' : 'Dismiss'}
          </button>
        </div>
      )}

      <section className="knowledge-version-detail__status-grid">
        <article>
          <span className="knowledge-version-detail__status-icon" aria-hidden="true">
            <Sparkles size={20} />
          </span>

          <div>
            <p>Version state</p>

            <strong>{formatVersionStatus(version.status)}</strong>

            <span>{describeVersionStatus(version.status)}</span>
          </div>
        </article>

        <article>
          <span className="knowledge-version-detail__status-icon" aria-hidden="true">
            <Database size={20} />
          </span>

          <div>
            <p>Ingestion state</p>

            <strong>{formatIngestionStatus(version.ingestion_status)}</strong>

            <span>{describeIngestionStatus(version.ingestion_status)}</span>
          </div>
        </article>
      </section>

      <section
        className="knowledge-version-detail__lifecycle"
        aria-labelledby="knowledge-version-lifecycle-heading"
      >
        <div className="knowledge-version-detail__section-heading">
          <div>
            <p>Controlled workflow</p>

            <h3 id="knowledge-version-lifecycle-heading">Version lifecycle</h3>
          </div>

          <span>Only actions valid for the current backend state are enabled.</span>
        </div>

        <div className="knowledge-version-detail__lifecycle-grid">
          <article className={canProcess ? 'is-available' : ''}>
            <span aria-hidden="true">
              <Boxes size={21} />
            </span>

            <div>
              <p>Step 1</p>
              <h4>{version.status === 'failed' ? 'Retry processing' : 'Process source'}</h4>

              <span>
                Parse, normalize, and divide the immutable source into retrievable chunks.
              </span>
            </div>

            <button
              type="button"
              disabled={!canProcess || lifecyclePending || lifecycleUnconfirmed}
              onClick={runProcessing}
            >
              {processing && <LoaderCircle size={16} className="is-spinning" aria-hidden="true" />}

              <span>
                {processing
                  ? 'Processing…'
                  : version.status === 'failed'
                    ? 'Retry processing'
                    : 'Process version'}
              </span>
            </button>
          </article>

          <article className={embeddingConfirmed ? 'is-complete' : canEmbed ? 'is-available' : ''}>
            <span aria-hidden="true">
              <Database size={21} />
            </span>

            <div>
              <p>Step 2</p>
              <h4>Create embeddings</h4>

              <span>Generate or reconcile vector artifacts for the processed chunks.</span>
            </div>

            <button
              type="button"
              disabled={!canEmbed || lifecyclePending || lifecycleUnconfirmed}
              onClick={runEmbedding}
            >
              {embedding ? (
                <LoaderCircle size={16} className="is-spinning" aria-hidden="true" />
              ) : embeddingConfirmed ? (
                <CheckCircle2 size={16} aria-hidden="true" />
              ) : null}

              <span>
                {embedding
                  ? 'Embedding…'
                  : embeddingConfirmed
                    ? 'Embeddings created'
                    : 'Create embeddings'}
              </span>
            </button>
          </article>

          <article className={canPublish ? 'is-available' : ''}>
            <span aria-hidden="true">
              <Rocket size={21} />
            </span>

            <div>
              <p>Step 3</p>
              <h4>Publish version</h4>

              <span>Make this version the document&apos;s active published source.</span>
            </div>

            <button
              type="button"
              disabled={!canPublish || lifecyclePending || lifecycleUnconfirmed}
              onClick={() => {
                // resetLifecycleMutations();
                setPublishConfirmationOpen(true);
              }}
            >
              <Rocket size={16} aria-hidden="true" />

              <span>Publish version</span>
            </button>
          </article>
        </div>
      </section>

      <section
        className="knowledge-version-detail__metadata"
        aria-labelledby="knowledge-version-metadata-heading"
      >
        <div className="knowledge-version-detail__section-heading">
          <div>
            <p>Immutable record</p>

            <h3 id="knowledge-version-metadata-heading">Source metadata</h3>
          </div>
        </div>

        <dl>
          <MetadataItem
            icon={<FileCode2 size={16} />}
            label="Source type"
            value={formatSourceType(version.source_type)}
          />

          <MetadataItem
            icon={<BookOpenText size={16} />}
            label="Source name"
            value={version.source_name ?? 'Not provided'}
          />

          <MetadataItem
            icon={<Hash size={16} />}
            label="Content hash"
            value={
              <code title={version.content_hash}>{shortenContentHash(version.content_hash)}</code>
            }
          />

          <MetadataItem
            icon={<Boxes size={16} />}
            label="Source length"
            value={formatCharacterCount(version.source_content_length)}
          />

          <MetadataItem
            icon={<Clock3 size={16} />}
            label="Created"
            value={
              <time dateTime={version.created_at}>{formatKnowledgeDate(version.created_at)}</time>
            }
          />

          <MetadataItem
            icon={<RefreshCcw size={16} />}
            label="Updated"
            value={
              <time dateTime={version.updated_at}>{formatKnowledgeDate(version.updated_at)}</time>
            }
          />
        </dl>
      </section>

      <section
        className="knowledge-version-detail__timeline"
        aria-labelledby="knowledge-version-timeline-heading"
      >
        <div className="knowledge-version-detail__section-heading">
          <div>
            <p>Recorded timestamps</p>

            <h3 id="knowledge-version-timeline-heading">Lifecycle timeline</h3>
          </div>
        </div>

        <dl>
          <TimelineItem label="Processing started" value={version.processing_started_at} />

          <TimelineItem label="Processing completed" value={version.processing_completed_at} />

          <TimelineItem label="Ready" value={version.ready_at} />

          <TimelineItem label="Published" value={version.published_at} />

          <TimelineItem label="Superseded" value={version.superseded_at} />

          <TimelineItem label="Archived" value={version.archived_at} />
        </dl>
      </section>

      {version.failure_code !== null && (
        <section
          className="knowledge-version-detail__failure"
          aria-labelledby="knowledge-version-failure-heading"
        >
          <AlertTriangle size={21} aria-hidden="true" />

          <div>
            <p>Processing failure</p>

            <h3 id="knowledge-version-failure-heading">
              {formatFailureCode(version.failure_code)}
            </h3>

            <span>
              The backend does not expose mutable source repair. Correct the source externally or
              retry processing when the version is eligible.
            </span>
          </div>
        </section>
      )}

      <Link
        className="knowledge-version-detail__back"
        to={`/knowledge/documents/${document.document_id}`}
      >
        <ArrowLeft size={16} aria-hidden="true" />

        <span>Back to document versions</span>
      </Link>

      <KnowledgeConfirmationDialog
        open={publishConfirmationOpen}
        title="Publish this version?"
        description={`Publish ${formatVersionNumber(version.version_number).toLowerCase()} of “${document.title}”. Any currently published version will be superseded.`}
        confirmLabel="Publish version"
        pendingLabel="Publishing…"
        pending={publishing}
        onConfirm={confirmPublication}
        onClose={() => {
          if (!publishing) {
            setPublishConfirmationOpen(false);
          }
        }}
      />
    </section>
  );
}

interface MetadataItemProps {
  readonly icon: React.ReactNode;
  readonly label: string;
  readonly value: React.ReactNode;
}

function MetadataItem({ icon, label, value }: MetadataItemProps) {
  return (
    <div>
      <dt>
        <span aria-hidden="true">{icon}</span>

        {label}
      </dt>

      <dd>{value}</dd>
    </div>
  );
}

interface TimelineItemProps {
  readonly label: string;
  readonly value: string | null | undefined;
}

function TimelineItem({ label, value }: TimelineItemProps) {
  return (
    <div className={value === null || value === undefined ? 'is-empty' : 'is-complete'}>
      <dt>
        <span aria-hidden="true" />
        {label}
      </dt>

      <dd>
        {value === null || value === undefined ? (
          'Not recorded'
        ) : (
          <time dateTime={value}>{formatOptionalKnowledgeDate(value)}</time>
        )}
      </dd>
    </div>
  );
}

interface VersionPageStateProps {
  readonly title: string;
  readonly description: string;
  readonly traceId: string | null;
  readonly onRetry: (() => void) | null;
}

function VersionPageState({ title, description, traceId, onRetry }: VersionPageStateProps) {
  return (
    <section className="knowledge-version-detail__state">
      <div>
        <span className="knowledge-version-detail__state-icon" aria-hidden="true">
          <AlertTriangle size={27} />
        </span>

        <h2>{title}</h2>
        <p>{description}</p>

        {traceId !== null && (
          <small>
            Reference: <code>{traceId}</code>
          </small>
        )}

        <div className="knowledge-version-detail__state-actions">
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

function getTraceId(error: Error | null): string | null {
  return error instanceof SafeApiError ? error.traceId : null;
}

function isNotFoundError(error: Error | null): boolean {
  return error instanceof SafeApiError && error.status === 404;
}
