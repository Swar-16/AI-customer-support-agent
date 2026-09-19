// apps/web/src/features/operations/ticket-queue.tsx
import { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  CircleAlert,
  Clock3,
  Eye,
  MessageSquareText,
  RefreshCw,
  Tag,
  TicketCheck,
  UserRound,
  X,
} from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import { useSession } from '../../shared/auth/session-context';
import type { TicketFilters } from './ticket-api';
import {
  ticketCategorySchema,
  ticketIdSchema,
  ticketPrioritySchema,
  ticketStatusSchema,
  type Ticket,
  type TicketCategory,
  type TicketPriority,
  type TicketStatus,
} from './ticket-contract';
import { useTicketDetail, useTicketList } from './ticket-queries';
import { TicketActions } from './ticket-actions';
import { TicketCommentComposer } from './ticket-comment-composer';
import { DashboardJellySwitch } from './dashboard-jelly-switch';
import { useSearchParams } from 'react-router';

type QueueView = 'active' | 'history';
type AssignmentScope = 'all' | 'mine' | 'unassigned';

const PAGE_LIMIT = 20;

const statusLabels: Record<TicketStatus, string> = {
  open: 'Open',
  in_progress: 'In progress',
  waiting_for_customer: 'Waiting for customer',
  resolved: 'Resolved',
  closed: 'Closed',
  reopened: 'Reopened',
};

const priorityLabels: Record<TicketPriority, string> = {
  low: 'Low',
  normal: 'Normal',
  high: 'High',
  urgent: 'Urgent',
};

const categoryLabels: Record<TicketCategory, string> = {
  billing: 'Billing',
  refund: 'Refund',
  order: 'Order',
  account: 'Account',
  technical: 'Technical',
  security: 'Security',
  product: 'Product',
  general: 'General',
  other: 'Other',
};

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function formatCode(value: string): string {
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ');
}

function safeErrorMessage(error: unknown, fallback: string): string {
  return error instanceof SafeApiError ? error.message : fallback;
}

function TicketListSkeleton() {
  return (
    <div className="ticket-list ticket-list--loading" aria-label="Loading tickets" aria-busy="true">
      {Array.from({ length: 5 }, (_, index) => (
        <div className="operations-skeleton ticket-card-skeleton" key={index} />
      ))}
    </div>
  );
}

function TicketCard({
  ticket,
  selected,
  onSelect,
}: {
  readonly ticket: Ticket;
  readonly selected: boolean;
  readonly onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`ticket-card${selected ? ' is-selected' : ''}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="ticket-card__topline">
        <span className="ticket-card__reference">{ticket.ticket_reference}</span>

        <span className={`ticket-priority ticket-priority--${ticket.priority}`}>
          {priorityLabels[ticket.priority]}
        </span>
      </span>

      <strong>{ticket.subject}</strong>

      <span className="ticket-card__description">{ticket.description}</span>

      <span className="ticket-card__metadata">
        <span>
          <Tag size={14} aria-hidden="true" />
          {categoryLabels[ticket.category]}
        </span>

        <span className={`ticket-status ticket-status--${ticket.status}`}>
          {statusLabels[ticket.status]}
        </span>
      </span>

      <span className="ticket-card__footer">
        <span>
          <Clock3 size={14} aria-hidden="true" />
          {formatTimestamp(ticket.updated_at)}
        </span>

        <span className="ticket-card__assignment">
          <UserRound size={14} aria-hidden="true" />
          {ticket.assigned_agent_id ? 'Assigned' : 'Unassigned'}
        </span>
      </span>
    </button>
  );
}

function TicketDetailDrawer({
  ticketId,
  currentOperatorId,
  onClose,
}: {
  readonly ticketId: string;
  readonly currentOperatorId: string;
  readonly onClose: () => void;
}) {
  const detail = useTicketDetail(ticketId);

  return (
    <aside className="ticket-drawer" aria-label="Ticket details">
      <div className="ticket-drawer__header">
        <div>
          <p className="operations-kicker">Ticket detail</p>
          <h2>{detail.data?.ticket.ticket_reference ?? 'Ticket'}</h2>
        </div>

        <button
          type="button"
          className="ticket-drawer__close"
          aria-label="Close ticket details"
          title="Close details"
          onClick={onClose}
        >
          <X size={20} aria-hidden="true" />
        </button>
      </div>

      {detail.isPending ? (
        <div className="ticket-drawer__loading" aria-busy="true">
          <div className="operations-skeleton" />
          <div className="operations-skeleton" />
          <div className="operations-skeleton" />
        </div>
      ) : null}

      {detail.isError ? (
        <div className="ticket-drawer__error" role="alert">
          <CircleAlert size={22} aria-hidden="true" />

          <div>
            <strong>Ticket unavailable</strong>

            <p>{safeErrorMessage(detail.error, 'The ticket details could not be loaded.')}</p>

            <button
              type="button"
              className="operations-button operations-button--secondary"
              onClick={() => {
                void detail.refetch();
              }}
            >
              Try again
            </button>
          </div>
        </div>
      ) : null}

      {detail.data ? (
        <>
          <div className="ticket-drawer__badges">
            <span className={`ticket-priority ticket-priority--${detail.data.ticket.priority}`}>
              {priorityLabels[detail.data.ticket.priority]} priority
            </span>

            <span className={`ticket-status ticket-status--${detail.data.ticket.status}`}>
              {statusLabels[detail.data.ticket.status]}
            </span>

            <span className="ticket-category">{categoryLabels[detail.data.ticket.category]}</span>
          </div>

          <section className="ticket-drawer__section">
            <p className="operations-kicker">Subject</p>
            <h3>{detail.data.ticket.subject}</h3>
            <p>{detail.data.ticket.description}</p>
          </section>

          {detail.data.ticket.resolution_summary ? (
            <section className="ticket-drawer__section ticket-resolution">
              <p className="operations-kicker">Resolution</p>
              <p>{detail.data.ticket.resolution_summary}</p>
            </section>
          ) : null}

          <TicketActions ticket={detail.data.ticket} currentOperatorId={currentOperatorId} />
          <section className="ticket-drawer__section">
            <p className="operations-kicker">Ownership</p>

            <dl className="ticket-detail-list">
              <div>
                <dt>Assignment</dt>
                <dd>
                  {detail.data.ticket.assigned_agent_id === null
                    ? 'Unassigned'
                    : detail.data.ticket.assigned_agent_id === currentOperatorId
                      ? 'Assigned to you'
                      : 'Assigned to another operator'}
                </dd>
              </div>

              {detail.data.ticket.assigned_at ? (
                <div>
                  <dt>Assigned at</dt>
                  <dd>{formatTimestamp(detail.data.ticket.assigned_at)}</dd>
                </div>
              ) : null}

              <div>
                <dt>Source</dt>
                <dd>{formatCode(detail.data.ticket.source)}</dd>
              </div>

              <div>
                <dt>Created</dt>
                <dd>{formatTimestamp(detail.data.ticket.created_at)}</dd>
              </div>

              <div>
                <dt>Updated</dt>
                <dd>{formatTimestamp(detail.data.ticket.updated_at)}</dd>
              </div>

              <div>
                <dt>Row version</dt>
                <dd>{detail.data.ticket.row_version}</dd>
              </div>
            </dl>
          </section>

          <section className="ticket-drawer__section">
            <p className="operations-kicker">Identifiers</p>

            <dl className="ticket-detail-list">
              <div>
                <dt>Conversation ID</dt>
                <dd className="is-monospace">{detail.data.ticket.conversation_id}</dd>
              </div>

              <div>
                <dt>Customer ID</dt>
                <dd className="is-monospace">{detail.data.ticket.customer_id}</dd>
              </div>

              {detail.data.ticket.escalation_id ? (
                <div>
                  <dt>Escalation ID</dt>
                  <dd className="is-monospace">{detail.data.ticket.escalation_id}</dd>
                </div>
              ) : null}
            </dl>
          </section>

          <section
            className="ticket-drawer__section ticket-comments"
            aria-labelledby="ticket-comments-title"
          >
            <div className="ticket-comments__heading">
              <div>
                <p className="operations-kicker">Communication</p>
                <h3 id="ticket-comments-title">Comments</h3>
              </div>

              <span>{detail.data.comments.length}</span>
            </div>
            <TicketCommentComposer
              key={detail.data.ticket.ticket_id}
              ticketId={detail.data.ticket.ticket_id}
            />

            {detail.data.comments.length === 0 ? (
              <div className="ticket-comments__empty">
                <MessageSquareText size={21} aria-hidden="true" />
                <p>No comments have been added yet.</p>
              </div>
            ) : (
              <ol className="ticket-comment-list">
                {detail.data.comments.map((comment) => (
                  <li
                    className={`ticket-comment ticket-comment--${comment.visibility}`}
                    key={comment.comment_id}
                  >
                    <div className="ticket-comment__header">
                      <strong>{formatCode(comment.author_role)}</strong>

                      <span
                        className={`ticket-comment__visibility ticket-comment__visibility--${comment.visibility}`}
                      >
                        {comment.visibility === 'internal' ? 'Internal note' : 'Customer visible'}
                      </span>
                    </div>

                    <p>{comment.content}</p>

                    <time dateTime={comment.created_at}>{formatTimestamp(comment.created_at)}</time>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      ) : null}
    </aside>
  );
}

export function TicketQueue() {
  const session = useSession();

  const currentOperatorId =
    session.phase === 'authenticated' &&
    (session.user?.role === 'admin' || session.user?.role === 'support_agent')
      ? session.user.id
      : null;

  const [searchParams, setSearchParams] = useSearchParams();
  const [view, setView] = useState<QueueView>(() =>
    searchParams.get('view') === 'history' ? 'history' : 'active',
  );

  const [assignmentScope, setAssignmentScope] = useState<AssignmentScope>(() => {
    const requestedScope = searchParams.get('scope');

    if (requestedScope === 'mine' || requestedScope === 'unassigned') {
      return requestedScope;
    }

    return 'all';
  });

  const [priority, setPriority] = useState<TicketPriority | null>(() => {
    const parsed = ticketPrioritySchema.safeParse(searchParams.get('priority'));

    return parsed.success ? parsed.data : null;
  });

  const [category, setCategory] = useState<TicketCategory | null>(null);
  const [status, setStatus] = useState<TicketStatus | null>(null);

  const [offset, setOffset] = useState(0);
  const requestedTicketId = searchParams.get('ticket');
  const parsedTicketId = ticketIdSchema.safeParse(requestedTicketId);
  const selectedId = parsedTicketId.success ? parsedTicketId.data : null;
  const invalidTicketLink = requestedTicketId !== null && !parsedTicketId.success;

  const filters = useMemo<TicketFilters>(
    () => ({
      activeOnly: view === 'active',
      status: view === 'history' ? status : null,
      priority,
      category,
      assignedAgentId: assignmentScope === 'mine' ? currentOperatorId : null,
      unassignedOnly: assignmentScope === 'unassigned',
      limit: PAGE_LIMIT,
      offset,
    }),
    [assignmentScope, category, currentOperatorId, offset, priority, status, view],
  );

  const queue = useTicketList(filters);

  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key !== 'Escape' || event.defaultPrevented || selectedId === null) {
        return;
      }

      event.preventDefault();

      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);

          next.delete('ticket');
          return next;
        },
        { replace: true },
      );
    }

    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('keydown', handleEscape);
    };
  }, [selectedId, setSearchParams]);

  function setSelectedTicket(ticketId: string | null, replace = true) {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);

        if (ticketId === null) {
          next.delete('ticket');
        } else {
          next.set('ticket', ticketId);
        }

        return next;
      },
      { replace },
    );
  }

  function resetPageAndSelection() {
    setOffset(0);
    setSelectedTicket(null);
  }

  function changeView(nextView: QueueView) {
    setView(nextView);
    setStatus(null);
    resetPageAndSelection();
  }

  const startNumber = queue.data && queue.data.items.length > 0 ? queue.data.offset + 1 : 0;

  const endNumber = queue.data?.items.length ? queue.data.offset + queue.data.items.length : 0;

  if (currentOperatorId === null) {
    return null;
  }

  return (
    <div className={`ticket-workspace${selectedId ? ' has-detail' : ''}`}>
      <section className="ticket-queue-panel">
        <div className="ticket-queue-toolbar">
          <DashboardJellySwitch
            label="Ticket queue view"
            value={view}
            tone="accent"
            options={[
              {
                value: 'active',
                label: 'Active queue',
              },
              {
                value: 'history',
                label: 'History',
              },
            ]}
            onChange={changeView}
          />

          <button
            type="button"
            className="operations-icon-button"
            aria-label="Refresh tickets"
            title="Refresh tickets"
            disabled={queue.isFetching}
            onClick={() => {
              void queue.refetch();
            }}
          >
            <RefreshCw
              size={18}
              aria-hidden="true"
              className={queue.isFetching ? 'is-spinning' : undefined}
            />
          </button>
        </div>

        <div className="ticket-scope-picker">
          <span>Assignment</span>

          <DashboardJellySwitch
            label="Ticket assignment"
            value={assignmentScope}
            tone="accent"
            options={[
              {
                value: 'all',
                label: 'All',
              },
              {
                value: 'mine',
                label: 'Mine',
              },
              {
                value: 'unassigned',
                label: 'Unassigned',
              },
            ]}
            onChange={(nextScope) => {
              setAssignmentScope(nextScope);
              resetPageAndSelection();
            }}
          />
        </div>

        <div className="ticket-filter-bar">
          <label>
            <span>Priority</span>

            <select
              value={priority ?? ''}
              onChange={(event) => {
                const parsed = ticketPrioritySchema.safeParse(event.target.value);

                setPriority(parsed.success ? parsed.data : null);
                resetPageAndSelection();
              }}
            >
              <option value="">All priorities</option>
              <option value="urgent">Urgent</option>
              <option value="high">High</option>
              <option value="normal">Normal</option>
              <option value="low">Low</option>
            </select>
          </label>

          <label>
            <span>Category</span>

            <select
              value={category ?? ''}
              onChange={(event) => {
                const parsed = ticketCategorySchema.safeParse(event.target.value);

                setCategory(parsed.success ? parsed.data : null);
                resetPageAndSelection();
              }}
            >
              <option value="">All categories</option>

              {Object.entries(categoryLabels).map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          {view === 'history' ? (
            <label>
              <span>Status</span>

              <select
                value={status ?? ''}
                onChange={(event) => {
                  const parsed = ticketStatusSchema.safeParse(event.target.value);

                  setStatus(parsed.success ? parsed.data : null);
                  resetPageAndSelection();
                }}
              >
                <option value="">All statuses</option>

                {Object.entries(statusLabels).map(([value, label]) => (
                  <option value={value} key={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>

        {invalidTicketLink ? (
          <div className="ticket-link-warning" role="alert">
            <CircleAlert size={19} aria-hidden="true" />

            <div>
              <strong>Invalid ticket link</strong>
              <p>
                The requested ticket identifier is not valid. You can continue browsing the ticket
                queue.
              </p>
            </div>

            <button
              type="button"
              aria-label="Dismiss invalid ticket link"
              onClick={() => {
                setSelectedTicket(null);
              }}
            >
              <X size={17} aria-hidden="true" />
            </button>
          </div>
        ) : null}

        {queue.isPending && queue.data === undefined ? <TicketListSkeleton /> : null}

        {queue.isError && queue.data === undefined ? (
          <div className="ticket-empty-state" role="alert">
            <span>
              <CircleAlert size={27} aria-hidden="true" />
            </span>

            <h2>Tickets unavailable</h2>

            <p>{safeErrorMessage(queue.error, 'The ticket queue could not be loaded.')}</p>

            <button
              type="button"
              className="operations-button operations-button--primary"
              onClick={() => {
                void queue.refetch();
              }}
            >
              Try again
            </button>
          </div>
        ) : null}

        {queue.data?.items.length === 0 ? (
          <div className="ticket-empty-state">
            <span>
              <TicketCheck size={27} aria-hidden="true" />
            </span>

            <h2>
              {view === 'active' ? 'The active ticket queue is clear' : 'No ticket history matched'}
            </h2>

            <p>
              Adjust the assignment, priority, category, or status filters to inspect another queue.
            </p>
          </div>
        ) : null}

        {queue.data && queue.data.items.length > 0 ? (
          <>
            <div className="ticket-list-summary">
              <span>
                Showing {startNumber}–{endNumber}
              </span>

              {queue.isFetching ? <span role="status">Refreshing…</span> : null}
            </div>

            <div className="ticket-list">
              {queue.data.items.map((ticket) => (
                <TicketCard
                  ticket={ticket}
                  selected={selectedId === ticket.ticket_id}
                  key={ticket.ticket_id}
                  onSelect={() => {
                    if (selectedId !== ticket.ticket_id) {
                      setSelectedTicket(ticket.ticket_id, false);
                    }
                  }}
                />
              ))}
            </div>

            <nav className="ticket-pagination" aria-label="Ticket pages">
              <div>
                {queue.data.offset > 0 ? (
                  <button
                    type="button"
                    className="operations-button operations-button--secondary"
                    onClick={() => {
                      setOffset(Math.max(0, queue.data.offset - queue.data.limit));
                      setSelectedTicket(null);
                    }}
                  >
                    <ArrowLeft size={17} aria-hidden="true" />
                    Previous
                  </button>
                ) : null}
              </div>

              <span>Page {Math.floor(queue.data.offset / queue.data.limit) + 1}</span>

              <div>
                {queue.data.has_more ? (
                  <button
                    type="button"
                    className="operations-button operations-button--secondary"
                    onClick={() => {
                      setOffset(queue.data.offset + queue.data.limit);
                      setSelectedTicket(null);
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
      </section>

      {selectedId ? (
        <TicketDetailDrawer
          key={selectedId}
          ticketId={selectedId}
          currentOperatorId={currentOperatorId}
          onClose={() => {
            setSelectedTicket(null);
          }}
        />
      ) : (
        <aside className="ticket-detail-placeholder" aria-label="Ticket selection">
          <span>
            <Eye size={25} aria-hidden="true" />
          </span>

          <h2>Inspect a ticket</h2>

          <p>
            Select a ticket to review its description, ownership, lifecycle, identifiers, and
            communication history.
          </p>
        </aside>
      )}
    </div>
  );
}
