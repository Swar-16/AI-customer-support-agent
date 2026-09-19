// apps/web/src/features/chat/customer-escalation-panel.tsx
import { useId } from 'react';

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

const statusDescriptions = {
  open: 'Your request for human support has been received.',
  in_review: 'A support specialist is reviewing your conversation.',
  resolved: 'Your human-support request has been marked as resolved.',
  dismissed: 'Your human-support request has been closed.',
} as const;

export function CustomerEscalationPanel({ conversationId, enabled }: CustomerEscalationPanelProps) {
  const titleId = useId();
  const query = useCustomerEscalation(conversationId, enabled);

  const status = query.error instanceof SafeApiError ? query.error.status : null;

  // Do not retain a previous status on screen after access/not-found errors.
  const hidePrevious = status === 401 || status === 403 || status === 404;

  const data = enabled && !hidePrevious ? query.data : undefined;

  return (
    <section className="chat-support" aria-labelledby={titleId} aria-busy={query.isFetching}>
      <div className="chat-support__heading">
        <h3 id={titleId}>Human support</h3>

        <button
          type="button"
          disabled={!enabled || query.isFetching}
          onClick={() => {
            void query.refetch();
          }}
        >
          Refresh support status
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

              <p className="chat-support__summary" role="status">
                {statusDescriptions[data.status]}
              </p>

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
            </>
          )}
        </>
      )}
    </section>
  );
}
