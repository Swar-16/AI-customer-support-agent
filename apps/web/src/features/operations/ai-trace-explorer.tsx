// apps/web/src/features/operations/ai-trace-explorer.tsx
import { type FormEvent, useCallback, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  CircleAlert,
  Clock3,
  Eye,
  Filter,
  RefreshCw,
  Search,
  Server,
  Sparkles,
  X,
} from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import type { AIAnalyticsWindow } from './ai-activity-api';
import type { TraceFilters } from './ai-trace-api';
import {
  traceIdSchema,
  traceStatusSchema,
  type TraceDetail,
  type TraceStatus,
  type TraceSummary,
  type TraceTimelineEvent,
} from './ai-trace-contract';
import { useAITraceDetail, useAITraceList } from './ai-trace-queries';

import './ai-trace-explorer.css';

const TRACE_PAGE_LIMIT = 25;

const statusLabels: Record<TraceStatus, string> = {
  success: 'Success',
  error: 'Error',
  running: 'Running',
};

interface AppliedTraceFilters {
  readonly traceId: string | null;
  readonly conversationId: string | null;
  readonly aiRunId: string | null;
  readonly status: TraceStatus | null;
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat().format(value);
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function formatDuration(value: number | null): string {
  if (value === null) {
    return '—';
  }

  if (value < 1_000) {
    return `${formatInteger(value)} ms`;
  }

  return `${(value / 1_000).toFixed(2)} s`;
}

function formatCode(value: string): string {
  return value
    .split(/[._-]/u)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ');
}

function shortIdentifier(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-4)}`;
}

function safeErrorMessage(error: unknown, fallback: string): string {
  return error instanceof SafeApiError ? error.message : fallback;
}

function validOptionalUuid(value: string): boolean {
  const normalized = value.trim();

  return normalized.length === 0 || traceIdSchema.safeParse(normalized).success;
}

function normalizedOptionalUuid(value: string): string | null {
  const normalized = value.trim();

  return normalized.length === 0 ? null : normalized.toLowerCase();
}

function TraceCard({
  trace,
  selected,
  onSelect,
}: {
  readonly trace: TraceSummary;
  readonly selected: boolean;
  readonly onSelect: () => void;
}) {
  const failures = trace.failed_api_request_count + trace.failed_ai_run_count;

  return (
    <button
      type="button"
      className={`trace-card trace-card--${trace.status}${selected ? ' is-selected' : ''}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="trace-card__topline">
        <span className={`trace-status trace-status--${trace.status}`}>
          {statusLabels[trace.status]}
        </span>

        <span title={trace.trace_id}>{shortIdentifier(trace.trace_id)}</span>
      </span>

      <strong>
        {failures > 0
          ? `${formatInteger(failures)} failure ${failures === 1 ? 'signal' : 'signals'}`
          : 'No recorded failures'}
      </strong>

      <span className="trace-card__counts">
        <span>
          <Server size={14} aria-hidden="true" />
          {formatInteger(trace.api_request_count)} API
        </span>

        <span>
          <Bot size={14} aria-hidden="true" />
          {formatInteger(trace.ai_run_count)} AI {trace.ai_run_count === 1 ? 'run' : 'runs'}
        </span>
      </span>

      <span className="trace-card__footer">
        <span>
          <Clock3 size={14} aria-hidden="true" />
          {formatTimestamp(trace.last_seen_at)}
        </span>

        <span>
          Peak {formatDuration(trace.maximum_ai_latency_ms ?? trace.maximum_api_latency_ms)}
        </span>
      </span>
    </button>
  );
}

function TraceEvent({ event }: { readonly event: TraceTimelineEvent }) {
  const details = Object.entries(event.details);

  return (
    <li className="trace-event">
      <span
        className={`trace-event__marker${
          event.status === 'failed' || event.status === 'error' || event.status === 'timeout'
            ? ' is-error'
            : ''
        }`}
        aria-hidden="true"
      />

      <article>
        <header>
          <div>
            <span>{formatCode(event.category)}</span>
            <strong>{formatCode(event.event_type)}</strong>
          </div>

          <time dateTime={event.occurred_at}>{formatTimestamp(event.occurred_at)}</time>
        </header>

        <div className="trace-event__metadata">
          {event.status ? <span>{formatCode(event.status)}</span> : null}

          {event.duration_ms !== null ? <span>{formatDuration(event.duration_ms)}</span> : null}
        </div>

        {details.length > 0 ? (
          <dl>
            {details.map(([key, value]) => (
              <div key={key}>
                <dt>{formatCode(key)}</dt>
                <dd>{String(value ?? '—')}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </article>
    </li>
  );
}

function TraceDetailDrawer({
  traceId,
  onClose,
}: {
  readonly traceId: string;
  readonly onClose: () => void;
}) {
  const trace = useAITraceDetail(traceId);

  return (
    <aside className="trace-drawer" aria-label="Trace details">
      <div className="trace-drawer__header">
        <div>
          <p className="operations-kicker">Distributed trace</p>

          <h2>{trace.data ? shortIdentifier(trace.data.trace_id) : 'Trace detail'}</h2>
        </div>

        <div className="trace-drawer__header-actions">
          <button
            type="button"
            className="operations-icon-button trace-icon-button"
            aria-label="Refresh trace"
            title="Refresh trace"
            disabled={trace.isFetching}
            onClick={() => {
              void trace.refetch();
            }}
          >
            <RefreshCw
              size={18}
              aria-hidden="true"
              className={trace.isFetching ? 'is-spinning' : undefined}
            />
          </button>

          <button
            type="button"
            className="operations-icon-button trace-icon-button"
            aria-label="Close trace details"
            title="Close trace details"
            onClick={onClose}
          >
            <X size={19} aria-hidden="true" />
          </button>
        </div>
      </div>

      {trace.isPending ? (
        <div className="trace-drawer__loading" aria-busy="true">
          <div className="operations-skeleton" />
          <div className="operations-skeleton" />
          <div className="operations-skeleton" />
        </div>
      ) : null}

      {trace.isError ? (
        <div className="trace-error" role="alert">
          <CircleAlert size={21} aria-hidden="true" />

          <div>
            <strong>Trace unavailable</strong>

            <p>{safeErrorMessage(trace.error, 'The trace detail could not be loaded.')}</p>

            <button
              type="button"
              className="operations-button operations-button--secondary"
              onClick={() => {
                void trace.refetch();
              }}
            >
              Try again
            </button>
          </div>
        </div>
      ) : null}

      {trace.data ? <TraceDetailContent trace={trace.data} /> : null}
    </aside>
  );
}

function TraceDetailContent({ trace }: { readonly trace: TraceDetail }) {
  const componentEntries = Object.entries(trace.component_counts).filter(([, count]) => count > 0);

  return (
    <>
      <section className="trace-drawer__summary">
        <div>
          <span className={`trace-status trace-status--${trace.status}`}>
            {statusLabels[trace.status]}
          </span>

          <span className="trace-duration">{formatDuration(trace.duration_ms)}</span>
        </div>

        <dl>
          <div>
            <dt>Started</dt>
            <dd>{formatTimestamp(trace.started_at)}</dd>
          </div>

          <div>
            <dt>Ended</dt>
            <dd>{trace.ended_at ? formatTimestamp(trace.ended_at) : 'Still running'}</dd>
          </div>

          <div>
            <dt>Trace ID</dt>
            <dd title={trace.trace_id}>{shortIdentifier(trace.trace_id)}</dd>
          </div>
        </dl>
      </section>

      <section className="trace-drawer__section">
        <p className="operations-kicker">Related records</p>

        {trace.conversation_ids.length > 0 ? (
          <div className="trace-related-list">
            <strong>Conversations</strong>

            {trace.conversation_ids.map((conversationId) => (
              <Link
                key={conversationId}
                to={`/operations/conversations?conversation=${conversationId}`}
              >
                {shortIdentifier(conversationId)}
              </Link>
            ))}
          </div>
        ) : null}

        {trace.ai_run_ids.length > 0 ? (
          <div className="trace-related-list">
            <strong>AI runs</strong>

            {trace.ai_run_ids.map((aiRunId) => (
              <span key={aiRunId} title={aiRunId}>
                <Sparkles size={14} aria-hidden="true" />
                {shortIdentifier(aiRunId)}
              </span>
            ))}
          </div>
        ) : null}

        {trace.conversation_ids.length === 0 && trace.ai_run_ids.length === 0 ? (
          <p>No related identifiers were recorded.</p>
        ) : null}
      </section>

      <section className="trace-drawer__section">
        <p className="operations-kicker">Component activity</p>

        {componentEntries.length > 0 ? (
          <dl className="trace-component-grid">
            {componentEntries.map(([name, count]) => (
              <div key={name}>
                <dt>{formatCode(name)}</dt>
                <dd>{formatInteger(count)}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p>No component activity was recorded.</p>
        )}
      </section>

      <section className="trace-drawer__section">
        <div className="trace-timeline-heading">
          <div>
            <p className="operations-kicker">Chronological evidence</p>
            <h3>Trace timeline</h3>
          </div>

          <span>
            {formatInteger(trace.timeline.length)}{' '}
            {trace.timeline.length === 1 ? 'event' : 'events'}
          </span>
        </div>

        {trace.timeline.length > 0 ? (
          <ol className="trace-timeline">
            {trace.timeline.map((event) => (
              <TraceEvent event={event} key={event.id} />
            ))}
          </ol>
        ) : (
          <p>No timeline events were recorded.</p>
        )}
      </section>
    </>
  );
}

function TraceListSkeleton() {
  return (
    <div className="trace-list" aria-label="Loading traces" aria-busy="true">
      {Array.from({ length: 5 }, (_, index) => (
        <div className="operations-skeleton trace-card-skeleton" key={index} />
      ))}
    </div>
  );
}

export function AITraceExplorer({ window }: { readonly window: AIAnalyticsWindow }) {
  const [searchParams, setSearchParams] = useSearchParams();

  const requestedTraceId = searchParams.get('trace');

  const parsedSelectedTrace = traceIdSchema.safeParse(requestedTraceId);

  const selectedTraceId = parsedSelectedTrace.success ? parsedSelectedTrace.data : null;

  const invalidSelectedTrace = requestedTraceId !== null && !parsedSelectedTrace.success;

  const [traceInput, setTraceInput] = useState('');
  const [conversationInput, setConversationInput] = useState('');
  const [aiRunInput, setAiRunInput] = useState('');
  const [statusInput, setStatusInput] = useState<TraceStatus | null>(null);

  const [appliedFilters, setAppliedFilters] = useState<AppliedTraceFilters>({
    traceId: null,
    conversationId: null,
    aiRunId: null,
    status: null,
  });

  const [offset, setOffset] = useState(0);

  const invalidTraceInput = !validOptionalUuid(traceInput);

  const invalidConversationInput = !validOptionalUuid(conversationInput);

  const invalidAiRunInput = !validOptionalUuid(aiRunInput);

  const invalidForm = invalidTraceInput || invalidConversationInput || invalidAiRunInput;

  const setTraceInUrl = useCallback(
    (traceId: string | null, replace = true) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);

          if (traceId === null) {
            next.delete('trace');
          } else {
            next.set('trace', traceId);
          }

          return next;
        },
        { replace },
      );
    },
    [setSearchParams],
  );

  const filters = useMemo<TraceFilters>(
    () => ({
      startedAt: window.startedAt,
      endedAt: window.endedAt,
      traceId: appliedFilters.traceId,
      conversationId: appliedFilters.conversationId,
      aiRunId: appliedFilters.aiRunId,
      status: appliedFilters.status,
      limit: TRACE_PAGE_LIMIT,
      offset,
    }),
    [appliedFilters, offset, window],
  );

  const traces = useAITraceList(filters);

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (invalidForm) {
      return;
    }

    setAppliedFilters({
      traceId: normalizedOptionalUuid(traceInput),
      conversationId: normalizedOptionalUuid(conversationInput),
      aiRunId: normalizedOptionalUuid(aiRunInput),
      status: statusInput,
    });

    setOffset(0);
    setTraceInUrl(null);
  }

  function clearFilters() {
    setTraceInput('');
    setConversationInput('');
    setAiRunInput('');
    setStatusInput(null);

    setAppliedFilters({
      traceId: null,
      conversationId: null,
      aiRunId: null,
      status: null,
    });

    setOffset(0);
    setTraceInUrl(null);
  }

  const startNumber = traces.data ? traces.data.offset + 1 : 0;

  const endNumber = traces.data ? traces.data.offset + traces.data.count : 0;

  return (
    <section className="trace-explorer">
      <div className="trace-explorer__heading">
        <div>
          <p className="operations-kicker">Trace explorer</p>

          <h2>Follow one request across the system</h2>

          <p>Search distributed traces by trace, conversation, AI run, or derived status.</p>
        </div>

        <button
          type="button"
          className="operations-icon-button trace-refresh"
          aria-label="Refresh traces"
          title="Refresh traces"
          disabled={traces.isFetching}
          onClick={() => {
            void traces.refetch();
          }}
        >
          <RefreshCw
            size={19}
            aria-hidden="true"
            className={traces.isFetching ? 'is-spinning' : undefined}
          />
        </button>
      </div>

      <form className="trace-filter-form" onSubmit={applyFilters}>
        <label>
          <span>Trace ID</span>

          <input
            type="text"
            value={traceInput}
            aria-invalid={invalidTraceInput}
            placeholder="UUID"
            onChange={(event) => {
              setTraceInput(event.target.value);
            }}
          />
        </label>

        <label>
          <span>Conversation ID</span>

          <input
            type="text"
            value={conversationInput}
            aria-invalid={invalidConversationInput}
            placeholder="UUID"
            onChange={(event) => {
              setConversationInput(event.target.value);
            }}
          />
        </label>

        <label>
          <span>AI run ID</span>

          <input
            type="text"
            value={aiRunInput}
            aria-invalid={invalidAiRunInput}
            placeholder="UUID"
            onChange={(event) => {
              setAiRunInput(event.target.value);
            }}
          />
        </label>

        <label>
          <span>Status</span>

          <select
            value={statusInput ?? ''}
            onChange={(event) => {
              const parsed = traceStatusSchema.safeParse(event.target.value);

              setStatusInput(parsed.success ? parsed.data : null);
            }}
          >
            <option value="">All statuses</option>
            <option value="success">Success</option>
            <option value="error">Error</option>
            <option value="running">Running</option>
          </select>
        </label>

        <div className="trace-filter-form__actions">
          <button
            type="submit"
            className="operations-button operations-button--primary"
            disabled={invalidForm}
          >
            <Search size={17} aria-hidden="true" />
            Search traces
          </button>

          <button
            type="button"
            className="operations-button operations-button--secondary"
            onClick={clearFilters}
          >
            <Filter size={17} aria-hidden="true" />
            Clear
          </button>
        </div>

        {invalidForm ? (
          <p className="trace-filter-form__error">Search identifiers must be valid UUIDs.</p>
        ) : null}
      </form>

      {invalidSelectedTrace ? (
        <div className="trace-link-warning" role="alert">
          <CircleAlert size={19} aria-hidden="true" />

          <div>
            <strong>Invalid trace link</strong>
            <p>The requested trace identifier is not valid.</p>
          </div>

          <button
            type="button"
            aria-label="Dismiss invalid trace link"
            onClick={() => {
              setTraceInUrl(null);
            }}
          >
            <X size={17} aria-hidden="true" />
          </button>
        </div>
      ) : null}

      <div className={`trace-results-layout${selectedTraceId ? ' has-selection' : ''}`}>
        <div className="trace-results">
          {traces.isPending && traces.data === undefined ? <TraceListSkeleton /> : null}

          {traces.isError && traces.data === undefined ? (
            <div className="trace-empty-state" role="alert">
              <CircleAlert size={27} aria-hidden="true" />

              <h3>Traces unavailable</h3>

              <p>{safeErrorMessage(traces.error, 'Trace results could not be loaded.')}</p>

              <button
                type="button"
                className="operations-button operations-button--primary"
                onClick={() => {
                  void traces.refetch();
                }}
              >
                Try again
              </button>
            </div>
          ) : null}

          {traces.data?.items.length === 0 ? (
            <div className="trace-empty-state">
              <Search size={27} aria-hidden="true" />

              <h3>No traces matched</h3>

              <p>Change the search identifiers, status, or reporting window.</p>
            </div>
          ) : null}

          {traces.data && traces.data.items.length > 0 ? (
            <>
              <div className="trace-list-summary">
                <span>
                  Showing {startNumber}–{endNumber} of {traces.data.total}
                </span>

                {traces.isFetching ? <span role="status">Refreshing…</span> : null}
              </div>

              <div className="trace-list">
                {traces.data.items.map((trace) => (
                  <TraceCard
                    trace={trace}
                    selected={selectedTraceId === trace.trace_id}
                    key={trace.trace_id}
                    onSelect={() => {
                      setTraceInUrl(trace.trace_id, false);
                    }}
                  />
                ))}
              </div>

              <nav className="trace-pagination" aria-label="Trace result pages">
                <div>
                  {traces.data.offset > 0 ? (
                    <button
                      type="button"
                      className="operations-button operations-button--secondary"
                      onClick={() => {
                        setOffset(Math.max(0, traces.data.offset - traces.data.limit));
                        setTraceInUrl(null);
                      }}
                    >
                      <ArrowLeft size={17} aria-hidden="true" />
                      Previous
                    </button>
                  ) : null}
                </div>

                <span>Page {Math.floor(traces.data.offset / traces.data.limit) + 1}</span>

                <div>
                  {traces.data.has_more ? (
                    <button
                      type="button"
                      className="operations-button operations-button--secondary"
                      onClick={() => {
                        setOffset(
                          traces.data.next_offset ?? traces.data.offset + traces.data.limit,
                        );
                        setTraceInUrl(null);
                      }}
                    >
                      Next
                      <ArrowRight size={17} aria-hidden="true" />
                    </button>
                  ) : null}
                </div>
              </nav>
            </>
          ) : null}
        </div>

        {selectedTraceId ? (
          <TraceDetailDrawer
            key={selectedTraceId}
            traceId={selectedTraceId}
            onClose={() => {
              setTraceInUrl(null);
            }}
          />
        ) : (
          <aside className="trace-detail-placeholder">
            <span>
              <Eye size={25} aria-hidden="true" />
            </span>

            <h3>Inspect a trace</h3>

            <p>
              Select a trace to inspect chronological API, AI, retrieval, provider, support, and
              audit evidence.
            </p>
          </aside>
        )}
      </div>
    </section>
  );
}
