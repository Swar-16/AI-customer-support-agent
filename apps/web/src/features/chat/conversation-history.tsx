// apps/web/src/features/chat/conversation-history.tsx

import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Headphones, RefreshCw } from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import { CloseConversation } from './close-conversation';
import { useConversationClosure } from './use-conversation-closure';
import { useConversation, useConversationHistory } from './chat-queries';
import { MessageComposer } from './message-composer';
import { useChatSubmission } from './use-chat-submission';
import { AssistantMessage } from './assistant-message';
import { MessageScrollBoundary } from './message-scroll-boundary';
import { useCustomerEscalation } from './customer-escalation-query';
import { ConversationSupportDrawer } from './conversation-support-drawer';
import { ResponseRating } from './response-rating';
import { OutgoingTurn } from './outgoing-turn';
import { shouldShowOutgoing } from './outgoing-message';

interface ConversationHistoryProps {
  readonly conversationId: string;
  readonly offset: number;
  readonly openLatest?: boolean;
  readonly onPageChange: (offset: number, replace?: boolean) => void;
}

const speakerNames = {
  customer: 'You',
  assistant: 'Assistant',
  support_agent: 'Support agent',
} as const;

const statusNames = {
  open: 'Open',
  waiting_for_customer: 'Waiting for customer',
  waiting_for_agent: 'Waiting for agent',
  escalated: 'Escalated',
  resolved: 'Resolved',
  closed: 'Closed',
} as const;

const supportStatusNames = {
  open: 'Requested',
  in_review: 'In review',
  resolved: 'Resolved',
  dismissed: 'Closed',
} as const;

export function ConversationHistory({
  conversationId,
  offset,
  openLatest = false,
  onPageChange,
}: ConversationHistoryProps) {
  const conversation = useConversation(conversationId);
  const history = useConversationHistory(conversationId, offset);
  const [historyAtSend, setHistoryAtSend] = useState<typeof history.data>(undefined);
  useEffect(() => {
    if (!openLatest || !history.isSuccess) return;

    const latestOffset =
      history.data.total === 0 ? 0 : Math.floor((history.data.total - 1) / 50) * 50;

    onPageChange(latestOffset, true);
  }, [openLatest, history.isSuccess, history.data, onPageChange]);

  const support = useCustomerEscalation(conversationId, conversation.isSuccess);

  const [openEscalationId, setOpenEscalationId] = useState<string | null>(null);
  const supportButtonRef = useRef<HTMLButtonElement>(null);

  const supportHttpStatus = support.error instanceof SafeApiError ? support.error.status : null;

  const supportAccessUnavailable =
    supportHttpStatus === 401 || supportHttpStatus === 403 || supportHttpStatus === 404;

  const escalation = conversation.isSuccess && !supportAccessUnavailable ? support.data : undefined;

  const supportOpen = escalation !== undefined && openEscalationId === escalation.escalation_id;

  const supportCheckFailed = conversation.isSuccess && support.isError && supportHttpStatus !== 404;

  function closeSupportPanel() {
    setOpenEscalationId(null);
    supportButtonRef.current?.focus({ preventScroll: true });
  }
  const mutationLockRef = useRef<'send' | 'close' | null>(null);

  const closure = useConversationClosure({
    conversationId,
    mutationLockRef,
  });
  const submission = useChatSubmission({
    conversationId,
    onPageChange,
  });

  async function sendMessage(message: string) {
    if (mutationLockRef.current !== null) {
      return {
        ok: false as const,
        error: SafeApiError.fromLocal('aborted'),
        retryAfterMs: null,
      };
    }

    mutationLockRef.current = 'send';
    setHistoryAtSend(history.data);

    try {
      return await submission.send(message);
    } finally {
      mutationLockRef.current = null;
    }
  }

  if (conversation.isPending) {
    return <p role="status">Opening conversation…</p>;
  }

  if (conversation.isError && conversation.data === undefined) {
    return (
      <section aria-label="Conversation unavailable">
        <h2>Conversation unavailable</h2>
        <p role="alert">
          This conversation could not be loaded. It may be unavailable or inaccessible to your
          account.
        </p>
        <button type="button" onClick={() => void conversation.refetch()}>
          Reload conversation
        </button>
      </section>
    );
  }

  const visibleHistory =
    submission.outgoing?.phase === 'sending' ? (historyAtSend ?? history.data) : history.data;
  const lastSequence = visibleHistory?.items.at(-1)?.sequence_number ?? null;
  const outgoing = submission.outgoing;
  const showOutgoing = shouldShowOutgoing(outgoing, visibleHistory?.items ?? []);

  return (
    <section
      className={supportOpen ? 'chat-thread chat-thread--support-open' : 'chat-thread'}
      aria-labelledby="conversation-title"
    >
      <header className="chat-thread__header">
        <div className="chat-thread__identity">
          <h2 id="conversation-title">{conversation.data.title || 'Untitled conversation'}</h2>
          <p className="chat-thread__status">
            <span aria-hidden="true" />
            Status: {statusNames[conversation.data.status]}
          </p>
        </div>

        <div className="chat-thread__actions">
          <CloseConversation
            closed={conversation.data.status === 'closed'}
            disabled={conversation.isError || conversation.isFetching || submission.isPending}
            phase={closure.phase}
            notice={closure.notice}
            checking={closure.checking}
            canRetry={closure.canRetry}
            onClose={closure.close}
            onCheckStatus={closure.checkStatus}
          />

          {escalation && (
            <button
              ref={supportButtonRef}
              type="button"
              className="chat-action chat-action--outline"
              aria-label="Human support"
              aria-expanded={supportOpen}
              aria-controls={supportOpen ? 'conversation-support-panel' : undefined}
              data-support-status={escalation.status}
              onClick={() => {
                if (supportOpen) {
                  closeSupportPanel();
                } else {
                  setOpenEscalationId(escalation.escalation_id);
                }
              }}
            >
              <Headphones size={18} aria-hidden="true" />

              <span>Human support</span>

              <span className="chat-action__status">{supportStatusNames[escalation.status]}</span>

              {support.isError && <span className="chat-thread__stale">Last known</span>}
            </button>
          )}

          {supportCheckFailed && (
            <div className="chat-thread__support-error">
              <p role="status">Support status could not be verified.</p>
              <button
                type="button"
                className="chat-icon-button"
                aria-label="Retry support status"
                title="Retry support status"
                disabled={support.isFetching}
                onClick={() => {
                  void support.refetch();
                }}
              >
                <RefreshCw size={17} aria-hidden="true" />
              </button>
            </div>
          )}
        </div>
      </header>

      <div className="chat-thread__body">
        <div className="chat-thread__main">
          <div
            className="chat-thread__messages"
            data-chat-scroll
            role="region"
            aria-label="Conversation messages"
            tabIndex={0}
          >
            <MessageScrollBoundary
              pageKey={`${conversationId}:${offset}`}
              ready={history.isSuccess && !openLatest}
              lastSequence={lastSequence}
              layoutKey={supportOpen ? 'support-open' : 'support-closed'}
              startAtBottom
            >
              <div className="chat-thread__message-content">
                {conversation.isError && (
                  <p role="alert">
                    The conversation status could not be refreshed. Sending is paused until the
                    current status is available.
                  </p>
                )}

                {(history.isPending && !visibleHistory) || (openLatest && history.isSuccess) ? (
                  <p role="status">Loading messages…</p>
                ) : history.isError && !visibleHistory ? (
                  <div>
                    <p role="alert">Message history could not be loaded.</p>
                    <button
                      type="button"
                      className="chat-action chat-action--outline"
                      onClick={() => void history.refetch()}
                    >
                      Reload messages
                    </button>
                  </div>
                ) : visibleHistory ? (
                  <>
                    {history.isFetching && <p role="status">Updating messages…</p>}

                    {visibleHistory.items.length === 0 && !outgoing ? (
                      <p>
                        {offset === 0 ? 'No messages yet.' : 'There are no messages on this page.'}
                      </p>
                    ) : (
                      <ol className="chat-history__messages" aria-label="Messages">
                        {visibleHistory.items.map((message) => {
                          const isSupportUpdate =
                            message.role === 'assistant' && message.feedback_eligible !== true;

                          const speakerName = isSupportUpdate
                            ? 'Support update'
                            : speakerNames[message.role];

                          return (
                            <li
                              key={message.message_id}
                              className="chat-history__message"
                              data-speaker={message.role}
                              data-message-kind={isSupportUpdate ? 'support-update' : 'standard'}
                              data-chat-message=""
                              tabIndex={-1}
                            >
                              <article aria-label={`Message from ${speakerName}`}>
                                <header>
                                  <strong>{speakerName}</strong>
                                  <time dateTime={message.created_at}>
                                    {new Date(message.created_at).toLocaleString()}
                                  </time>
                                </header>

                                {message.role === 'assistant' ? (
                                  <>
                                    <AssistantMessage content={message.content} />

                                    {message.feedback_eligible === true && (
                                      <ResponseRating
                                        conversationId={conversationId}
                                        responseMessageId={message.message_id}
                                        message={message}
                                      />
                                    )}
                                  </>
                                ) : (
                                  <p className="chat-history__content">{message.content}</p>
                                )}
                              </article>
                            </li>
                          );
                        })}
                      </ol>
                    )}

                    {outgoing && (
                      <OutgoingTurn
                        key={outgoing.localId}
                        message={outgoing}
                        showBubble={showOutgoing}
                      />
                    )}

                    {(offset > 0 || visibleHistory.has_more) && (
                      <nav className="chat-pagination" aria-label="Message pages">
                        {offset > 0 && (
                          <button
                            type="button"
                            className="chat-icon-button"
                            aria-label="Earlier messages"
                            title="Earlier messages"
                            disabled={history.isFetching || submission.isPending}
                            onClick={() => onPageChange(Math.max(0, offset - 50))}
                          >
                            <ArrowLeft size={18} aria-hidden="true" />
                          </button>
                        )}

                        <span className="chat-pagination__count">
                          {visibleHistory.total} messages total
                        </span>

                        {visibleHistory.has_more && (
                          <button
                            type="button"
                            className="chat-icon-button"
                            aria-label="Later messages"
                            title="Later messages"
                            disabled={history.isFetching || submission.isPending}
                            onClick={() => {
                              const next = visibleHistory.next_offset;
                              if (next !== null) onPageChange(next);
                            }}
                          >
                            <ArrowRight size={18} aria-hidden="true" />
                          </button>
                        )}
                      </nav>
                    )}
                  </>
                ) : null}
              </div>
            </MessageScrollBoundary>
          </div>

          <div className="chat-thread__composer">
            <MessageComposer
              status={conversation.data.status}
              disabled={
                openLatest ||
                conversation.isError ||
                history.isPending ||
                history.isError ||
                closure.blocksSending
              }
              onDiscardOutgoing={submission.clearOutgoing}
              onSend={sendMessage}
              onReconcile={submission.reconcile}
            />
          </div>
        </div>

        {supportOpen && (
          <ConversationSupportDrawer conversationId={conversationId} onClose={closeSupportPanel} />
        )}
      </div>
    </section>
  );
}
