// apps/web/src/features/operations/operations-conversation-queue.tsx
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  CircleAlert,
  Clock3,
  Eye,
  MessageSquareText,
  RefreshCw,
  Sparkles,
  Star,
  UserRound,
  X,
} from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import type { OperationsConversationFilters } from './operations-conversation-api';
import {
  operationsConversationChannelSchema,
  operationsConversationIdSchema,
  operationsConversationStatusSchema,
  type OperationsConversation,
  type OperationsConversationChannel,
  type OperationsConversationMessage,
  type OperationsConversationStatus,
} from './operations-conversation-contract';
import {
  useOperationsConversationDetail,
  useOperationsConversationList,
  useOperationsConversationMessages,
} from './operations-conversation-queries';

import './operations-conversation-queue.css';

const CONVERSATION_PAGE_LIMIT = 20;
const MESSAGE_PAGE_LIMIT = 50;

const statusLabels: Record<OperationsConversationStatus, string> = {
  open: 'Open',
  waiting_for_customer: 'Waiting for customer',
  waiting_for_agent: 'Waiting for agent',
  escalated: 'Escalated',
  resolved: 'Resolved',
  closed: 'Closed',
};

const channelLabels: Record<OperationsConversationChannel, string> = {
  web: 'Web',
  mobile: 'Mobile',
  email: 'Email',
  api: 'API',
};

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function shortIdentifier(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-4)}`;
}

function safeErrorMessage(error: unknown, fallback: string): string {
  return error instanceof SafeApiError ? error.message : fallback;
}

function ConversationCard({
  conversation,
  selected,
  onSelect,
}: {
  readonly conversation: OperationsConversation;
  readonly selected: boolean;
  readonly onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`oversight-conversation-card${
        conversation.status === 'escalated' ? ' is-escalated' : ''
      }${selected ? ' is-selected' : ''}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="oversight-conversation-card__topline">
        <span className={`oversight-status oversight-status--${conversation.status}`}>
          {statusLabels[conversation.status]}
        </span>

        <span className="oversight-channel">{channelLabels[conversation.channel]}</span>
      </span>

      <strong>{conversation.title?.trim() || 'Untitled conversation'}</strong>

      <span className="oversight-conversation-card__customer">
        <UserRound size={14} aria-hidden="true" />
        Customer {shortIdentifier(conversation.customer_id)}
      </span>

      <span className="oversight-conversation-card__footer">
        <span>
          <Clock3 size={14} aria-hidden="true" />
          Updated {formatTimestamp(conversation.updated_at)}
        </span>

        <span title={conversation.conversation_id}>
          {shortIdentifier(conversation.conversation_id)}
        </span>
      </span>
    </button>
  );
}

function ConversationMessage({ message }: { readonly message: OperationsConversationMessage }) {
  const roleLabel =
    message.role === 'customer'
      ? 'Customer'
      : message.role === 'assistant'
        ? 'Assistant'
        : 'Support agent';

  return (
    <article className={`oversight-message oversight-message--${message.role}`}>
      <header>
        <span>
          {message.role === 'customer' ? (
            <UserRound size={16} aria-hidden="true" />
          ) : message.role === 'assistant' ? (
            <Bot size={16} aria-hidden="true" />
          ) : (
            <MessageSquareText size={16} aria-hidden="true" />
          )}

          <strong>{roleLabel}</strong>
        </span>

        <time dateTime={message.created_at}>{formatTimestamp(message.created_at)}</time>
      </header>

      <p>{message.content}</p>

      <footer>
        <span>Message #{message.sequence_number}</span>

        {message.ai_run_id ? (
          <span title={message.ai_run_id}>
            <Sparkles size={13} aria-hidden="true" />
            AI run {shortIdentifier(message.ai_run_id)}
          </span>
        ) : null}
      </footer>

      {message.feedback ? (
        <Link
          className="oversight-message__feedback"
          to={`/operations/feedback?feedback=${message.feedback.feedback_id}`}
        >
          <Star size={15} fill="currentColor" aria-hidden="true" />

          <span>{message.feedback.rating}/5 customer feedback</span>

          {message.feedback.helpful === true ? (
            <small>Helpful</small>
          ) : message.feedback.helpful === false ? (
            <small>Not helpful</small>
          ) : null}
        </Link>
      ) : null}
    </article>
  );
}

function ConversationDetail({
  conversationId,
  onClose,
}: {
  readonly conversationId: string;
  readonly onClose: () => void;
}) {
  const [messageOffset, setMessageOffset] = useState(0);

  const conversation = useOperationsConversationDetail(conversationId);

  const messageFilters = useMemo(
    () => ({
      conversationId,
      limit: MESSAGE_PAGE_LIMIT,
      offset: messageOffset,
    }),
    [conversationId, messageOffset],
  );

  const messages = useOperationsConversationMessages(messageFilters);

  const refreshing = conversation.isFetching || messages.isFetching;

  function refreshDetail() {
    void Promise.all([conversation.refetch(), messages.refetch()]);
  }

  return (
    <aside className="oversight-detail" aria-label="Conversation details">
      <div className="oversight-detail__header">
        <div>
          <p className="operations-kicker">Read-only inspection</p>

          <h2>{conversation.data?.title?.trim() || 'Conversation'}</h2>
        </div>

        <div className="oversight-detail__header-actions">
          <button
            type="button"
            className="operations-icon-button oversight-detail__icon-button"
            aria-label="Refresh conversation"
            title="Refresh conversation"
            disabled={refreshing}
            onClick={refreshDetail}
          >
            <RefreshCw
              size={18}
              aria-hidden="true"
              className={refreshing ? 'is-spinning' : undefined}
            />
          </button>

          <button
            type="button"
            className="operations-icon-button oversight-detail__icon-button"
            aria-label="Close conversation details"
            title="Close details"
            onClick={onClose}
          >
            <X size={19} aria-hidden="true" />
          </button>
        </div>
      </div>

      {conversation.isPending ? (
        <div className="oversight-detail__loading" aria-busy="true">
          <div className="operations-skeleton" />
          <div className="operations-skeleton" />
        </div>
      ) : null}

      {conversation.isError ? (
        <div className="oversight-error" role="alert">
          <CircleAlert size={21} aria-hidden="true" />

          <div>
            <strong>Conversation unavailable</strong>

            <p>{safeErrorMessage(conversation.error, 'The conversation could not be loaded.')}</p>

            <button
              type="button"
              className="operations-button operations-button--secondary"
              onClick={() => {
                void conversation.refetch();
              }}
            >
              Try again
            </button>
          </div>
        </div>
      ) : null}

      {conversation.data ? (
        <section className="oversight-detail__summary">
          <div>
            <span className={`oversight-status oversight-status--${conversation.data.status}`}>
              {statusLabels[conversation.data.status]}
            </span>

            <span className="oversight-channel">{channelLabels[conversation.data.channel]}</span>
          </div>

          <dl>
            <div>
              <dt>Customer</dt>
              <dd title={conversation.data.customer_id}>
                {shortIdentifier(conversation.data.customer_id)}
              </dd>
            </div>

            <div>
              <dt>Conversation</dt>
              <dd title={conversation.data.conversation_id}>
                {shortIdentifier(conversation.data.conversation_id)}
              </dd>
            </div>

            <div>
              <dt>Created</dt>
              <dd>{formatTimestamp(conversation.data.created_at)}</dd>
            </div>

            <div>
              <dt>Updated</dt>
              <dd>{formatTimestamp(conversation.data.updated_at)}</dd>
            </div>
          </dl>
        </section>
      ) : null}

      <section className="oversight-history">
        <div className="oversight-history__heading">
          <div>
            <p className="operations-kicker">Message history</p>

            <h3>Customer and assistant timeline</h3>
          </div>

          {messages.data ? (
            <span>
              {messages.data.total} {messages.data.total === 1 ? 'message' : 'messages'}
            </span>
          ) : null}
        </div>

        {messages.isPending ? (
          <div className="oversight-message-list" aria-busy="true">
            <div className="operations-skeleton oversight-message-skeleton" />
            <div className="operations-skeleton oversight-message-skeleton" />
            <div className="operations-skeleton oversight-message-skeleton" />
          </div>
        ) : null}

        {messages.isError ? (
          <div className="oversight-error" role="alert">
            <CircleAlert size={21} aria-hidden="true" />

            <div>
              <strong>History unavailable</strong>

              <p>
                {safeErrorMessage(messages.error, 'The conversation history could not be loaded.')}
              </p>

              <button
                type="button"
                className="operations-button operations-button--secondary"
                onClick={() => {
                  void messages.refetch();
                }}
              >
                Try again
              </button>
            </div>
          </div>
        ) : null}

        {messages.data?.items.length === 0 ? (
          <div className="oversight-history__empty">
            <MessageSquareText size={24} aria-hidden="true" />

            <p>This conversation has no messages.</p>
          </div>
        ) : null}

        {messages.data && messages.data.items.length > 0 ? (
          <>
            <div className="oversight-message-list">
              {messages.data.items.map((message) => (
                <ConversationMessage message={message} key={message.message_id} />
              ))}
            </div>

            <nav className="oversight-message-pagination" aria-label="Conversation message pages">
              <div>
                {messages.data.offset > 0 ? (
                  <button
                    type="button"
                    className="operations-button operations-button--secondary"
                    onClick={() => {
                      setMessageOffset(Math.max(0, messages.data.offset - messages.data.limit));
                    }}
                  >
                    <ArrowLeft size={16} aria-hidden="true" />
                    Earlier
                  </button>
                ) : null}
              </div>

              <span>
                {messages.data.offset + 1}–{messages.data.offset + messages.data.count}
              </span>

              <div>
                {messages.data.has_more ? (
                  <button
                    type="button"
                    className="operations-button operations-button--secondary"
                    onClick={() => {
                      setMessageOffset(
                        messages.data.next_offset ?? messages.data.offset + messages.data.limit,
                      );
                    }}
                  >
                    Later
                    <ArrowRight size={16} aria-hidden="true" />
                  </button>
                ) : null}
              </div>
            </nav>
          </>
        ) : null}
      </section>

      <div className="oversight-readonly-notice">
        <Eye size={18} aria-hidden="true" />

        <span>
          This workspace is read-only. Administrators cannot send messages or impersonate customers.
        </span>
      </div>
    </aside>
  );
}

function ConversationListSkeleton() {
  return (
    <div
      className="oversight-conversation-list"
      aria-label="Loading conversations"
      aria-busy="true"
    >
      {Array.from({ length: 6 }, (_, index) => (
        <div className="operations-skeleton oversight-conversation-skeleton" key={index} />
      ))}
    </div>
  );
}

export function OperationsConversationQueue() {
  const [searchParams, setSearchParams] = useSearchParams();

  const requestedConversationId = searchParams.get('conversation');

  const parsedConversationId = operationsConversationIdSchema.safeParse(requestedConversationId);

  const selectedId = parsedConversationId.success ? parsedConversationId.data : null;

  const invalidConversationLink = requestedConversationId !== null && !parsedConversationId.success;

  const [status, setStatus] = useState<OperationsConversationStatus | null>(null);

  const [channel, setChannel] = useState<OperationsConversationChannel | null>(null);

  const [offset, setOffset] = useState(0);

  const setConversationInUrl = useCallback(
    (conversationId: string | null, replace = true) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);

          if (conversationId === null) {
            next.delete('conversation');
          } else {
            next.set('conversation', conversationId);
          }

          return next;
        },
        { replace },
      );
    },
    [setSearchParams],
  );

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setConversationInUrl(null);
      }
    }

    window.addEventListener('keydown', handleKeyDown);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [setConversationInUrl]);

  const filters = useMemo<OperationsConversationFilters>(
    () => ({
      status,
      channel,
      customerId: null,
      limit: CONVERSATION_PAGE_LIMIT,
      offset,
    }),
    [channel, offset, status],
  );

  const conversations = useOperationsConversationList(filters);

  function resetPageAndSelection() {
    setOffset(0);
    setConversationInUrl(null);
  }

  const startNumber = conversations.data ? conversations.data.offset + 1 : 0;

  const endNumber = conversations.data ? conversations.data.offset + conversations.data.count : 0;

  return (
    <div className="oversight-workspace">
      <section className="oversight-queue-panel">
        <div className="oversight-queue-toolbar">
          <div>
            <p className="operations-kicker">Administrative oversight</p>

            <h2>Conversation inspection</h2>

            <p>Review authorized customer and AI history without changing the conversation.</p>
          </div>

          <button
            type="button"
            className="operations-icon-button oversight-refresh"
            aria-label="Refresh conversations"
            title="Refresh conversations"
            disabled={conversations.isFetching}
            onClick={() => {
              void conversations.refetch();
            }}
          >
            <RefreshCw
              size={19}
              aria-hidden="true"
              className={conversations.isFetching ? 'is-spinning' : undefined}
            />
          </button>
        </div>

        <div className="oversight-filter-bar">
          <label>
            <span>Status</span>

            <select
              value={status ?? ''}
              onChange={(event) => {
                const parsed = operationsConversationStatusSchema.safeParse(event.target.value);

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

          <label>
            <span>Channel</span>

            <select
              value={channel ?? ''}
              onChange={(event) => {
                const parsed = operationsConversationChannelSchema.safeParse(event.target.value);

                setChannel(parsed.success ? parsed.data : null);

                resetPageAndSelection();
              }}
            >
              <option value="">All channels</option>

              {Object.entries(channelLabels).map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {invalidConversationLink ? (
          <div className="oversight-link-warning" role="alert">
            <CircleAlert size={19} aria-hidden="true" />

            <div>
              <strong>Invalid conversation link</strong>
              <p>The requested conversation identifier is invalid.</p>
            </div>

            <button
              type="button"
              aria-label="Dismiss invalid conversation link"
              onClick={() => {
                setConversationInUrl(null);
              }}
            >
              <X size={17} aria-hidden="true" />
            </button>
          </div>
        ) : null}

        {conversations.isPending && conversations.data === undefined ? (
          <ConversationListSkeleton />
        ) : null}

        {conversations.isError && conversations.data === undefined ? (
          <div className="oversight-empty-state" role="alert">
            <CircleAlert size={27} aria-hidden="true" />

            <h2>Conversations unavailable</h2>

            <p>
              {safeErrorMessage(conversations.error, 'The conversation list could not be loaded.')}
            </p>

            <button
              type="button"
              className="operations-button operations-button--primary"
              onClick={() => {
                void conversations.refetch();
              }}
            >
              Try again
            </button>
          </div>
        ) : null}

        {conversations.data?.items.length === 0 ? (
          <div className="oversight-empty-state">
            <MessageSquareText size={27} aria-hidden="true" />

            <h2>No conversations matched</h2>

            <p>Adjust the status or channel filter.</p>
          </div>
        ) : null}

        {conversations.data && conversations.data.items.length > 0 ? (
          <>
            <div className="oversight-list-summary">
              <span>
                Showing {startNumber}–{endNumber} of {conversations.data.total}
              </span>

              {conversations.isFetching ? <span role="status">Refreshing…</span> : null}
            </div>

            <div className="oversight-conversation-list">
              {conversations.data.items.map((conversation) => (
                <ConversationCard
                  conversation={conversation}
                  selected={selectedId === conversation.conversation_id}
                  key={conversation.conversation_id}
                  onSelect={() => {
                    setConversationInUrl(conversation.conversation_id, false);
                  }}
                />
              ))}
            </div>

            <nav className="oversight-pagination" aria-label="Conversation pages">
              <div>
                {conversations.data.offset > 0 ? (
                  <button
                    type="button"
                    className="operations-button operations-button--secondary"
                    onClick={() => {
                      setOffset(Math.max(0, conversations.data.offset - conversations.data.limit));

                      setConversationInUrl(null);
                    }}
                  >
                    <ArrowLeft size={17} aria-hidden="true" />
                    Previous
                  </button>
                ) : null}
              </div>

              <span>
                Page {Math.floor(conversations.data.offset / conversations.data.limit) + 1}
              </span>

              <div>
                {conversations.data.has_more ? (
                  <button
                    type="button"
                    className="operations-button operations-button--secondary"
                    onClick={() => {
                      setOffset(
                        conversations.data.next_offset ??
                          conversations.data.offset + conversations.data.limit,
                      );

                      setConversationInUrl(null);
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
        <ConversationDetail
          key={selectedId}
          conversationId={selectedId}
          onClose={() => {
            setConversationInUrl(null);
          }}
        />
      ) : (
        <aside className="oversight-detail-placeholder" aria-label="Conversation selection">
          <span>
            <Eye size={25} aria-hidden="true" />
          </span>

          <h2>Inspect a conversation</h2>

          <p>
            Select a conversation to review its customer, assistant, support-agent, feedback, and
            AI-run history.
          </p>
        </aside>
      )}
    </div>
  );
}
