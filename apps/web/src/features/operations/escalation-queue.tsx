// apps/web/src/features/operations/escalation-queue.tsx
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Eye,
  Filter,
  RefreshCw,
  ShieldAlert,
  X,
  ExternalLink,
  TicketPlus,
} from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import type { EscalationFilters } from './escalation-api';
import {
  escalationPrioritySchema,
  escalationStatusSchema,
  type Escalation,
  type EscalationPriority,
  type EscalationStatus,
} from './escalation-contract';
import {
  useCreateEscalationTicket,
  useEscalationDetail,
  useEscalationList,
  useUpdateEscalationStatus,
} from './escalation-queries';
import { useNavigate, useSearchParams } from 'react-router';
import { CreateEscalationTicketDialog } from './create-escalation-ticket-dialog';
import { DashboardJellySwitch } from './dashboard-jelly-switch';

type QueueView = 'active' | 'history';
type ButtonTone = 'primary' | 'secondary' | 'danger';

interface TransitionAction {
  readonly status: EscalationStatus;
  readonly label: string;
  readonly tone: ButtonTone;
}

interface PendingTransition {
  readonly escalationId: string;
  readonly fromStatus: EscalationStatus;
  readonly toStatus: EscalationStatus;
}

const PAGE_LIMIT = 20;

const statusLabels: Record<EscalationStatus, string> = {
  open: 'Open',
  in_review: 'In review',
  resolved: 'Resolved',
  dismissed: 'Dismissed',
};

const priorityLabels: Record<EscalationPriority, string> = {
  low: 'Low',
  normal: 'Normal',
  high: 'High',
  urgent: 'Urgent',
};

function formatCode(value: string): string {
  return value
    .toLowerCase()
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof SafeApiError ? error.message : fallback;
}

function availableTransitions(status: EscalationStatus): readonly TransitionAction[] {
  switch (status) {
    case 'open':
      return [
        {
          status: 'in_review',
          label: 'Start review',
          tone: 'primary',
        },
        {
          status: 'resolved',
          label: 'Resolve',
          tone: 'secondary',
        },
        {
          status: 'dismissed',
          label: 'Dismiss',
          tone: 'danger',
        },
      ];

    case 'in_review':
      return [
        {
          status: 'resolved',
          label: 'Resolve',
          tone: 'primary',
        },
        {
          status: 'dismissed',
          label: 'Dismiss',
          tone: 'danger',
        },
      ];

    case 'resolved':
    case 'dismissed':
      return [];
  }
}

function EscalationListSkeleton() {
  return (
    <div
      className="escalation-list escalation-list--loading"
      aria-busy="true"
      aria-label="Loading escalations"
    >
      {Array.from({ length: 5 }, (_, index) => (
        <div className="operations-skeleton escalation-card-skeleton" key={index} />
      ))}
    </div>
  );
}

function EscalationCard({
  escalation,
  selected,
  onSelect,
}: {
  readonly escalation: Escalation;
  readonly selected: boolean;
  readonly onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`escalation-card${selected ? ' is-selected' : ''}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="escalation-card__topline">
        <span className={`escalation-priority escalation-priority--${escalation.priority}`}>
          {priorityLabels[escalation.priority]}
        </span>

        <span className={`escalation-status escalation-status--${escalation.status}`}>
          {statusLabels[escalation.status]}
        </span>
      </span>

      <strong>{formatCode(escalation.reason_code)}</strong>

      <span className="escalation-card__summary">
        {escalation.reason_summary ??
          escalation.handoff_summary ??
          'Open this escalation to inspect its operational details.'}
      </span>

      <span className="escalation-card__footer">
        <span>
          <Clock3 size={14} aria-hidden="true" />
          {formatTimestamp(escalation.created_at)}
        </span>

        <span className="escalation-card__open">
          Open
          <ArrowRight size={14} aria-hidden="true" />
        </span>
      </span>
    </button>
  );
}

function DetailField({
  label,
  children,
  monospace = false,
}: {
  readonly label: string;
  readonly children: ReactNode;
  readonly monospace?: boolean;
}) {
  return (
    <div className="escalation-detail-field">
      <dt>{label}</dt>
      <dd className={monospace ? 'is-monospace' : undefined}>{children}</dd>
    </div>
  );
}

function EscalationDrawer({
  escalationId,
  onClose,
  onOpenTicket,
  onTicketCreated,
  onRequestTransition,
  transitionPending,
}: {
  readonly escalationId: string;
  readonly onClose: () => void;
  readonly onOpenTicket: (ticketId: string) => void;
  readonly onTicketCreated: (message: string) => void;
  readonly onRequestTransition: (action: TransitionAction, escalation: Escalation) => void;
  readonly transitionPending: boolean;
}) {
  const [ticketDialogOpen, setTicketDialogOpen] = useState(false);

  const detail = useEscalationDetail(escalationId);
  const createTicket = useCreateEscalationTicket();

  const operationPending = transitionPending || createTicket.isPending;

  const linkedTicket = detail.data?.linked_ticket ?? null;

  return (
    <aside className="escalation-drawer" aria-label="Escalation details">
      <div className="escalation-drawer__header">
        <div>
          <p className="operations-kicker">Case detail</p>
          <h2>Escalation</h2>
        </div>

        <button
          type="button"
          className="escalation-drawer__close"
          aria-label="Close escalation details"
          title="Close details"
          disabled={operationPending}
          onClick={onClose}
        >
          <X size={20} aria-hidden="true" />
        </button>
      </div>

      {detail.isPending ? (
        <div className="escalation-drawer__loading" aria-busy="true">
          <div className="operations-skeleton" />
          <div className="operations-skeleton" />
          <div className="operations-skeleton" />
        </div>
      ) : null}

      {detail.isError ? (
        <div className="escalation-drawer__error" role="alert">
          <CircleAlert size={22} aria-hidden="true" />

          <div>
            <strong>Details unavailable</strong>
            <p>{errorMessage(detail.error, 'The escalation details could not be loaded.')}</p>

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
          <div className="escalation-drawer__badges">
            <span className={`escalation-priority escalation-priority--${detail.data.priority}`}>
              {priorityLabels[detail.data.priority]} priority
            </span>

            <span className={`escalation-status escalation-status--${detail.data.status}`}>
              {statusLabels[detail.data.status]}
            </span>
          </div>

          <section className="escalation-drawer__section">
            <p className="operations-kicker">Reason</p>
            <h3>{formatCode(detail.data.reason_code)}</h3>

            <p>{detail.data.reason_summary ?? 'No additional reason summary was provided.'}</p>
          </section>

          {detail.data.handoff_summary ? (
            <section className="escalation-drawer__section">
              <p className="operations-kicker">Handoff summary</p>
              <p>{detail.data.handoff_summary}</p>
            </section>
          ) : null}

          <section className="escalation-ticket-action">
            <div className="escalation-ticket-action__heading">
              <span className="escalation-ticket-action__icon">
                <TicketPlus size={20} aria-hidden="true" />
              </span>

              <div>
                <p className="operations-kicker">Durable support case</p>

                <h3>{linkedTicket ? 'Ticket linked' : 'Create a ticket'}</h3>
              </div>
            </div>

            {linkedTicket ? (
              <>
                <p>
                  This escalation is tracked as <strong>{linkedTicket.ticket_reference}</strong>.
                </p>

                <div className="escalation-ticket-action__meta">
                  <span>{formatCode(linkedTicket.status)}</span>
                </div>

                <button
                  type="button"
                  className="operations-button operations-button--primary escalation-ticket-action__button"
                  disabled={operationPending}
                  onClick={() => {
                    onOpenTicket(linkedTicket.ticket_id);
                  }}
                >
                  Open {linkedTicket.ticket_reference}
                  <ExternalLink size={17} aria-hidden="true" />
                </button>
              </>
            ) : detail.data.status === 'open' || detail.data.status === 'in_review' ? (
              <>
                <p>
                  Convert this human-review request into a durable case with ownership, comments,
                  priority, and resolution tracking.
                </p>

                <button
                  type="button"
                  className="operations-button operations-button--primary escalation-ticket-action__button"
                  disabled={operationPending}
                  onClick={() => {
                    createTicket.reset();
                    setTicketDialogOpen(true);
                  }}
                >
                  <TicketPlus size={17} aria-hidden="true" />
                  Create ticket
                </button>
              </>
            ) : (
              <div className="escalation-ticket-action__unavailable">
                <CircleAlert size={18} aria-hidden="true" />

                <span>
                  No ticket was created before this escalation became{' '}
                  {statusLabels[detail.data.status].toLowerCase()}.
                </span>
              </div>
            )}
          </section>

          <section className="escalation-drawer__section">
            <p className="operations-kicker">Case information</p>

            <dl className="escalation-detail-list">
              <DetailField label="Source">{formatCode(detail.data.source)}</DetailField>

              <DetailField label="Created">{formatTimestamp(detail.data.created_at)}</DetailField>

              <DetailField label="Last updated">
                {formatTimestamp(detail.data.updated_at)}
              </DetailField>

              {detail.data.resolved_at ? (
                <DetailField label="Resolved">
                  {formatTimestamp(detail.data.resolved_at)}
                </DetailField>
              ) : null}

              <DetailField label="Conversation ID" monospace>
                {detail.data.conversation_id}
              </DetailField>

              <DetailField label="Escalation ID" monospace>
                {detail.data.escalation_id}
              </DetailField>

              {detail.data.ai_run_id ? (
                <DetailField label="AI run ID" monospace>
                  {detail.data.ai_run_id}
                </DetailField>
              ) : null}
            </dl>
          </section>

          <div className="escalation-drawer__actions">
            {availableTransitions(detail.data.status).map((action) => (
              <button
                type="button"
                className={`operations-button operations-button--${action.tone}`}
                disabled={operationPending}
                key={action.status}
                onClick={() => {
                  onRequestTransition(action, detail.data);
                }}
              >
                {action.label}
              </button>
            ))}

            {availableTransitions(detail.data.status).length === 0 ? (
              <div className="escalation-terminal-state">
                <CheckCircle2 size={19} aria-hidden="true" />
                <span>This escalation is {statusLabels[detail.data.status].toLowerCase()}.</span>
              </div>
            ) : null}
          </div>
        </>
      ) : null}
      {ticketDialogOpen && detail.data ? (
        <CreateEscalationTicketDialog
          escalation={detail.data}
          pending={createTicket.isPending}
          error={createTicket.error}
          onCancel={() => {
            if (createTicket.isPending) return;

            setTicketDialogOpen(false);
            createTicket.reset();
          }}
          onSubmit={async (draft) => {
            const escalation = detail.data;

            if (!escalation) return;

            const result = await createTicket.mutateAsync({
              escalationId: escalation.escalation_id,
              draft,
            });

            setTicketDialogOpen(false);

            onTicketCreated(
              result.created
                ? `${result.ticket_reference} was created and linked to this escalation.`
                : `${result.ticket_reference} was already linked to this escalation.`,
            );
          }}
        />
      ) : null}
    </aside>
  );
}

function TransitionDialog({
  transition,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  readonly transition: PendingTransition;
  readonly pending: boolean;
  readonly error: unknown;
  readonly onCancel: () => void;
  readonly onConfirm: () => void;
}) {
  const destructive = transition.toStatus === 'dismissed';

  return (
    <div
      className="operations-dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !pending) {
          onCancel();
        }
      }}
    >
      <section
        className="operations-confirmation-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="escalation-confirmation-title"
        aria-describedby="escalation-confirmation-description"
      >
        <span className={`operations-confirmation-card__icon${destructive ? ' is-danger' : ''}`}>
          {destructive ? (
            <ShieldAlert size={27} aria-hidden="true" />
          ) : (
            <CheckCircle2 size={27} aria-hidden="true" />
          )}
        </span>

        <p className="operations-kicker">Confirm status change</p>

        <h2 id="escalation-confirmation-title">
          Mark as {statusLabels[transition.toStatus].toLowerCase()}?
        </h2>

        <p id="escalation-confirmation-description">
          This will move the escalation from{' '}
          <strong>{statusLabels[transition.fromStatus].toLowerCase()}</strong> to{' '}
          <strong>{statusLabels[transition.toStatus].toLowerCase()}</strong>.
        </p>

        {error ? (
          <p className="operations-dialog-error" role="alert">
            {errorMessage(error, 'The escalation status could not be updated.')}
          </p>
        ) : null}

        <div className="operations-confirmation-card__actions">
          <button
            type="button"
            className="operations-button operations-button--secondary"
            disabled={pending}
            onClick={onCancel}
          >
            Keep current status
          </button>

          <button
            type="button"
            className={`operations-button ${
              destructive ? 'operations-button--danger-solid' : 'operations-button--primary'
            }`}
            aria-busy={pending}
            disabled={pending}
            onClick={onConfirm}
          >
            {pending ? 'Updating…' : `Confirm ${statusLabels[transition.toStatus].toLowerCase()}`}
          </button>
        </div>
      </section>
    </div>
  );
}

export function EscalationQueue() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [view, setView] = useState<QueueView>(() =>
    searchParams.get('view') === 'history' ? 'history' : 'active',
  );
  const [priority, setPriority] = useState<EscalationPriority | null>(() => {
    const parsed = escalationPrioritySchema.safeParse(searchParams.get('priority'));

    return parsed.success ? parsed.data : null;
  });
  const [status, setStatus] = useState<EscalationStatus | null>(null);
  const [reasonDraft, setReasonDraft] = useState('');
  const [reasonCode, setReasonCode] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [transition, setTransition] = useState<PendingTransition | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const filters = useMemo<EscalationFilters>(
    () => ({
      activeOnly: view === 'active',
      status: view === 'history' ? status : null,
      priority,
      reasonCode: view === 'history' ? reasonCode : null,
      limit: PAGE_LIMIT,
      offset,
    }),
    [offset, priority, reasonCode, status, view],
  );

  const queue = useEscalationList(filters);
  const updateStatus = useUpdateEscalationStatus();

  /*
   * A selected escalation remains visible while its request is loading or its
   * status is being updated. Once a refreshed page no longer contains it, the
   * drawer disappears without synchronizing derived state through an effect.
   */
  const visibleSelectedId =
    selectedId !== null &&
    (queue.data === undefined ||
      updateStatus.isPending ||
      queue.data.items.some((item) => item.escalation_id === selectedId))
      ? selectedId
      : null;

  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key !== 'Escape' || event.defaultPrevented) return;

      if (transition !== null && !updateStatus.isPending) {
        event.preventDefault();
        setTransition(null);
        updateStatus.reset();
        return;
      }

      if (visibleSelectedId !== null) {
        event.preventDefault();
        setSelectedId(null);
      }
    }

    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('keydown', handleEscape);
    };
  }, [transition, updateStatus, updateStatus.isPending, visibleSelectedId]);

  function changeView(nextView: QueueView) {
    setView(nextView);
    setOffset(0);
    setStatus(null);
    setReasonDraft('');
    setReasonCode(null);
    setSelectedId(null);
    setNotice(null);
  }

  function submitReasonFilter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const normalized = reasonDraft.trim();

    setReasonCode(normalized.length > 0 ? normalized : null);
    setOffset(0);
    setSelectedId(null);
  }

  async function confirmTransition() {
    if (transition === null || updateStatus.isPending) return;

    try {
      const result = await updateStatus.mutateAsync({
        escalationId: transition.escalationId,
        status: transition.toStatus,
      });

      setNotice(
        result.changed
          ? `Escalation moved to ${statusLabels[result.current_status].toLowerCase()}.`
          : `The escalation was already ${statusLabels[result.current_status].toLowerCase()}.`,
      );

      setTransition(null);

      if (
        view === 'active' &&
        (result.current_status === 'resolved' || result.current_status === 'dismissed')
      ) {
        setSelectedId(null);
      }
    } catch {
      // The mutation error remains available to the dialog.
    }
  }

  const startNumber = queue.data && queue.data.items.length > 0 ? queue.data.offset + 1 : 0;

  const endNumber = queue.data?.items.length ? queue.data.offset + queue.data.items.length : 0;

  return (
    <div className={`escalation-workspace${visibleSelectedId ? ' has-detail' : ''}`}>
      <section className="escalation-queue-panel">
        <div className="escalation-queue-toolbar">
          <DashboardJellySwitch
            label="Escalation queue view"
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
            aria-label="Refresh escalations"
            title="Refresh escalations"
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

        <div className="escalation-filter-bar">
          <span className="escalation-filter-bar__label">
            <Filter size={16} aria-hidden="true" />
            Filters
          </span>

          <label>
            <span>Priority</span>

            <select
              value={priority ?? ''}
              onChange={(event) => {
                const parsed = escalationPrioritySchema.safeParse(event.target.value);

                setPriority(parsed.success ? parsed.data : null);
                setOffset(0);
                setSelectedId(null);
              }}
            >
              <option value="">All priorities</option>
              <option value="urgent">Urgent</option>
              <option value="high">High</option>
              <option value="normal">Normal</option>
              <option value="low">Low</option>
            </select>
          </label>

          {view === 'history' ? (
            <>
              <label>
                <span>Status</span>

                <select
                  value={status ?? ''}
                  onChange={(event) => {
                    const parsed = escalationStatusSchema.safeParse(event.target.value);

                    setStatus(parsed.success ? parsed.data : null);
                    setOffset(0);
                    setSelectedId(null);
                  }}
                >
                  <option value="">All statuses</option>
                  <option value="open">Open</option>
                  <option value="in_review">In review</option>
                  <option value="resolved">Resolved</option>
                  <option value="dismissed">Dismissed</option>
                </select>
              </label>

              <form className="escalation-reason-filter" onSubmit={submitReasonFilter}>
                <label>
                  <span>Reason code</span>

                  <input
                    type="search"
                    maxLength={100}
                    value={reasonDraft}
                    placeholder="e.g. HUMAN_REVIEW_REQUIRED"
                    onChange={(event) => {
                      setReasonDraft(event.target.value);
                    }}
                  />
                </label>

                <button type="submit" className="operations-button operations-button--secondary">
                  Apply
                </button>
              </form>
            </>
          ) : null}
        </div>

        {notice ? (
          <div className="escalation-success-notice" role="status">
            <CheckCircle2 size={18} aria-hidden="true" />
            <span>{notice}</span>

            <button
              type="button"
              aria-label="Dismiss notification"
              onClick={() => {
                setNotice(null);
              }}
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>
        ) : null}

        {queue.isPending && queue.data === undefined ? <EscalationListSkeleton /> : null}

        {queue.isError && queue.data === undefined ? (
          <div className="escalation-empty-state" role="alert">
            <span className="escalation-empty-state__icon">
              <CircleAlert size={27} aria-hidden="true" />
            </span>

            <h2>Escalations unavailable</h2>

            <p>{errorMessage(queue.error, 'The escalation queue could not be loaded.')}</p>

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
          <div className="escalation-empty-state">
            <span className="escalation-empty-state__icon">
              <ShieldAlert size={27} aria-hidden="true" />
            </span>

            <h2>
              {view === 'active' ? 'The active queue is clear' : 'No escalation history matched'}
            </h2>

            <p>
              {view === 'active'
                ? 'There are no active escalations matching the selected priority.'
                : 'Adjust the status, priority, or reason-code filters and try again.'}
            </p>
          </div>
        ) : null}

        {queue.data && queue.data.items.length > 0 ? (
          <>
            <div className="escalation-list-summary">
              <span>
                Showing {startNumber}–{endNumber}
              </span>

              {queue.isFetching ? <span role="status">Refreshing…</span> : null}
            </div>

            <div className="escalation-list">
              {queue.data.items.map((item) => (
                <EscalationCard
                  escalation={item}
                  selected={visibleSelectedId === item.escalation_id}
                  key={item.escalation_id}
                  onSelect={() => {
                    setSelectedId(item.escalation_id);
                    setNotice(null);
                  }}
                />
              ))}
            </div>

            <nav className="escalation-pagination" aria-label="Escalation pages">
              <div>
                {queue.data.offset > 0 ? (
                  <button
                    type="button"
                    className="operations-button operations-button--secondary"
                    onClick={() => {
                      setOffset(Math.max(0, queue.data.offset - queue.data.limit));
                      setSelectedId(null);
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
                      setSelectedId(null);
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

      {visibleSelectedId ? (
        <EscalationDrawer
          key={visibleSelectedId}
          escalationId={visibleSelectedId}
          transitionPending={updateStatus.isPending}
          onClose={() => {
            setSelectedId(null);
          }}
          onOpenTicket={(ticketId) => {
            navigate(`/operations/tickets?ticket=${encodeURIComponent(ticketId)}`);
          }}
          onTicketCreated={(message) => {
            setNotice(message);
          }}
          onRequestTransition={(action, escalation) => {
            updateStatus.reset();
            setTransition({
              escalationId: escalation.escalation_id,
              fromStatus: escalation.status,
              toStatus: action.status,
            });
          }}
        />
      ) : (
        <aside className="escalation-detail-placeholder" aria-label="Escalation selection">
          <span>
            <Eye size={25} aria-hidden="true" />
          </span>
          <h2>Inspect a case</h2>
          <p>
            Select an escalation to see the reason, handoff context, lifecycle, and available
            actions.
          </p>
        </aside>
      )}

      {transition ? (
        <TransitionDialog
          transition={transition}
          pending={updateStatus.isPending}
          error={updateStatus.error}
          onCancel={() => {
            setTransition(null);
            updateStatus.reset();
          }}
          onConfirm={() => {
            void confirmTransition();
          }}
        />
      ) : null}
    </div>
  );
}
