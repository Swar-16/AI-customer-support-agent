// apps/web/src/features/chat/customer-escalation-panel.tsx
import { useId } from 'react';
import { RefreshCw, Ticket } from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import { useCustomerEscalation } from './customer-escalation-query';

interface CustomerEscalationPanelProps {
  readonly conversationId: string;
  readonly enabled: boolean;
}

const statusLabels = {
  open: 'Open',
  in_review: 'In review',
  resolved: 'Resolved',
  dismissed: 'Dismissed',
} as const;

const priorityLabels = {
  low: 'Low',
  normal: 'Normal',
  high: 'High',
  urgent: 'Urgent',
} as const;

const ticketStatusLabels = {
  open: 'Open',
  in_progress: 'In progress',
  waiting_for_customer: 'Waiting for customer',
  resolved: 'Resolved',
  closed: 'Closed',
  reopened: 'Reopened',
} as const;

export function CustomerEscalationPanel({ conversationId, enabled }: CustomerEscalationPanelProps) {
  const titleId = useId();

  const query = useCustomerEscalation(conversationId, enabled);

  const status = query.error instanceof SafeApiError ? query.error.status : null;

  /*
   * Never retain customer-visible data after authentication, authorization,
   * or not-found responses.
   */
  const hidePrevious = status === 401 || status === 403 || status === 404;

  const data = enabled && !hidePrevious ? query.data : undefined;

  const linkedTicket = data?.linked_ticket ?? null;

  return (
    <section className="chat-support" aria-labelledby={titleId} aria-busy={query.isFetching}>
      <div className="chat-support__heading">
        <h3 id={titleId}>Human support</h3>

        <button
          type="button"
          className="chat-action chat-action--outline"
          disabled={!enabled || query.isFetching}
          onClick={() => {
            void query.refetch();
          }}
        >
          <RefreshCw size={16} aria-hidden="true" />

          {query.isFetching ? 'Refreshing…' : 'Refresh status'}
        </button>
      </div>

      {!enabled ? (
        <p>Support status is unavailable while the conversation cannot be verified.</p>
      ) : query.isPending ? (
        <p role="status">Loading support status…</p>
      ) : (
        <>
          {query.isFetching && <p role="status">Refreshing support status…</p>}

          {query.isError && (
            <p role={status === 404 ? 'status' : 'alert'}>
              {status === 404
                ? 'No support status is available for this conversation.'
                : hidePrevious
                  ? 'Support status is unavailable. Your access may have changed.'
                  : data
                    ? 'Support status could not be refreshed. The last known status is shown below.'
                    : 'Support status could not be loaded. You can try refreshing it.'}
            </p>
          )}

          {data && (
            <>
              <p className="chat-support__scope">
                {query.isError ? 'Last known escalation' : 'Latest escalation'}
              </p>

              {/*
               * Do not generate lifecycle explanations here. The backend
               * provides authoritative customer-facing lifecycle messages in
               * conversation history.
               */}
              <dl className="chat-support__details">
                <div>
                  <dt>Status</dt>

                  <dd>
                    <span className="chat-support__status" data-status={data.status}>
                      {statusLabels[data.status]}
                    </span>
                  </dd>
                </div>

                <div>
                  <dt>Priority</dt>
                  <dd>{priorityLabels[data.priority]}</dd>
                </div>

                <div>
                  <dt>Created</dt>

                  <dd>
                    <time dateTime={data.created_at}>
                      {new Date(data.created_at).toLocaleString()}
                    </time>
                  </dd>
                </div>

                <div>
                  <dt>Updated</dt>

                  <dd>
                    <time dateTime={data.updated_at}>
                      {new Date(data.updated_at).toLocaleString()}
                    </time>
                  </dd>
                </div>

                {data.resolved_at != null && (
                  <div>
                    <dt>Resolved at</dt>

                    <dd>
                      <time dateTime={data.resolved_at}>
                        {new Date(data.resolved_at).toLocaleString()}
                      </time>
                    </dd>
                  </div>
                )}
              </dl>

              {linkedTicket !== null && (
                <section className="chat-support__ticket" aria-labelledby={`${titleId}-ticket`}>
                  <div className="chat-support__ticket-heading">
                    <Ticket size={18} aria-hidden="true" />

                    <h4 id={`${titleId}-ticket`}>Linked support ticket</h4>
                  </div>

                  <dl className="chat-support__ticket-details">
                    <div>
                      <dt>Reference</dt>

                      <dd className="chat-support__ticket-reference">
                        {linkedTicket.ticket_reference}
                      </dd>
                    </div>

                    <div>
                      <dt>Status</dt>

                      <dd>
                        <span
                          className="chat-support__ticket-status"
                          data-status={linkedTicket.status}
                        >
                          {ticketStatusLabels[linkedTicket.status]}
                        </span>
                      </dd>
                    </div>
                  </dl>
                </section>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
