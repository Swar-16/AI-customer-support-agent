// apps/web/src/features/chat/chat-page.tsx

import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import { ArrowLeft, ArrowRight, LogOut, Plus, RefreshCw } from 'lucide-react';

import { ChatWelcome } from './chat-welcome';
import { useSession } from '../../shared/auth/session-context';
import { identity } from '../../shared/branding/identity';
import { conversationIdSchema } from './chat-contract';
import { useConversations } from './chat-queries';
import { ConversationDraft } from './conversation-draft';
import { ConversationHistory } from './conversation-history';
import { useConversationCapacity } from './use-conversation-capacity';
import { useLogoutDialog } from '../auth/logout-dialog-context';
import { DraftExitDialog } from './draft-exit-dialog';

import './chat-page.css';

function readOffset(value: string | null): number {
  if (value === null || !/^\d+$/u.test(value)) return 0;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : 0;
}

export default function ChatPage() {
  const session = useSession();
  const navigate = useNavigate();
  const { conversationId } = useParams<{ conversationId: string }>();
  const [search, setSearch] = useSearchParams();
  const isDraft = conversationId === undefined && search.get('draft') === '1';

  const listOffset = readOffset(search.get('conversationsOffset'));
  const messageOffset = readOffset(search.get('messagesOffset'));
  const { listAreaRef, limit: conversationLimit } = useConversationCapacity();
  const conversations = useConversations(listOffset, conversationLimit);

  const heading = useRef<HTMLHeadingElement>(null);

  const [draftRevision, setDraftRevision] = useState(0);
  const [draftExit, setDraftExit] = useState<
    { readonly kind: 'new' } | { readonly kind: 'navigate'; readonly to: string } | null
  >(null);

  function draftNeedsConfirmation() {
    return document.querySelector('.conversation-draft[data-navigation-blocked="true"]') !== null;
  }

  function requestDraftNavigation(to: string) {
    if (draftNeedsConfirmation()) {
      setDraftExit({ kind: 'navigate', to });
    } else {
      setExitNotice(null);
      navigate(to);
    }
  }

  function confirmDraftExit() {
    const action = draftExit;
    setDraftExit(null);
    setExitNotice(null);

    if (action?.kind === 'new') {
      setDraftRevision((revision) => revision + 1);
    } else if (action?.kind === 'navigate') {
      navigate(action.to);
    }
  }

  const requestLogout = useLogoutDialog();
  const [exitNotice, setExitNotice] = useState<string | null>(null);

  useEffect(() => {
    document.title = `Customer Chat · ${identity.productName}`;
    heading.current?.focus();
  }, [conversationId, isDraft]);

  const parsedId = conversationId ? conversationIdSchema.safeParse(conversationId) : null;

  function changePage(name: string, offset: number, replace = false) {
    setSearch(
      (previous) => {
        const next = new URLSearchParams(previous);

        // An explicit messagesOffset=0 means the user selected the
        // first page. Do not confuse it with "open the latest page".
        if (offset === 0 && name !== 'messagesOffset') {
          next.delete(name);
        } else {
          next.set(name, String(offset));
        }

        return next;
      },
      { replace },
    );
  }

  function conversationPath(id: string): string {
    const query = new URLSearchParams();
    if (listOffset > 0) query.set('conversationsOffset', String(listOffset));
    const suffix = query.toString();
    return `/chat/${id}${suffix ? `?${suffix}` : ''}`;
  }

  function createConversation() {
    if (session.phase !== 'authenticated' || session.user?.role !== 'customer') {
      return;
    }

    if (isDraft) {
      if (draftNeedsConfirmation()) {
        setDraftExit({ kind: 'new' });
      } else {
        setExitNotice(null);
        setDraftRevision((revision) => revision + 1);
      }
      return;
    }

    const query = new URLSearchParams();
    query.set('draft', '1');

    if (listOffset > 0) {
      query.set('conversationsOffset', String(listOffset));
    }

    navigate(`/chat?${query.toString()}`);
  }

  return (
    <div
      className="chat-workspace"
      onClickCapture={(event) => {
        if (!isDraft || !(event.target instanceof Element)) return;

        const link = event.target.closest('a[href]');
        const href = link?.getAttribute('href');

        if (href == null || href.startsWith('#') || !draftNeedsConfirmation()) {
          return;
        }

        event.preventDefault();
        event.stopPropagation();
        setDraftExit({ kind: 'navigate', to: href });
      }}
      onKeyDown={(event) => {
        if (event.defaultPrevented || event.nativeEvent.isComposing || event.repeat) return;

        if (event.key !== 'Escape') {
          if (exitNotice !== null) setExitNotice(null);
          return;
        }

        if (!parsedId?.success && !isDraft) return;

        // Let dialogs and support details handle their own dismissal first.
        if (
          document.querySelector('dialog[open]') ||
          event.currentTarget.querySelector('.conversation-support-drawer')
        ) {
          return;
        }

        const blockedComposer = event.currentTarget.querySelector(
          '.message-composer[data-navigation-blocked="true"]',
        );

        if (blockedComposer) {
          event.preventDefault();

          setExitNotice(
            'Finish the current request or clear your unsent draft before leaving this conversation. If recovery is required, resolve it first.',
          );

          const textarea = blockedComposer?.querySelector<HTMLTextAreaElement>('textarea');

          if (textarea && !textarea.disabled) {
            textarea.focus({ preventScroll: true });
          }

          return;
        }

        event.preventDefault();
        setExitNotice(null);

        const query = new URLSearchParams();
        if (listOffset > 0) {
          query.set('conversationsOffset', String(listOffset));
        }

        const suffix = query.toString();
        navigate(`/chat${suffix ? `?${suffix}` : ''}`);
      }}
    >
      <a className="chat-skip" href="#chat-content">
        Skip to conversation
      </a>

      <aside className="chat-rail">
        <Link to="/chat" className="chat-brand">
          <svg width="36" height="36" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
            <path
              d="M8 7h32v27H22L10 42v-8H8Z"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinejoin="round"
            />
            <path
              d="M24 11C26 19 29 21 36 23C29 25 26 28 24 35C22 28 19 25 12 23C19 21 22 19 24 11Z"
              fill="currentColor"
            />
          </svg>
          <span>{identity.productName}</span>
        </Link>

        <button
          type="button"
          className="chat-primary chat-new-conversation"
          disabled={session.phase !== 'authenticated'}
          onClick={createConversation}
        >
          <span className="chat-new-conversation__icon" aria-hidden="true">
            <Plus size={17} strokeWidth={2.6} />
          </span>
          <span>New conversation</span>
        </button>

        <section className="chat-conversations" aria-labelledby="conversations-heading">
          <div className="chat-conversations__heading">
            <h2 id="conversations-heading">Conversations</h2>

            <button
              type="button"
              className="chat-icon-button"
              aria-label="Refresh conversations"
              title="Refresh conversations"
              disabled={conversations.isFetching}
              onClick={() => {
                void conversations.refetch();
              }}
            >
              <RefreshCw size={18} aria-hidden="true" />
            </button>
          </div>

          <div className="chat-conversations__list-area" ref={listAreaRef}>
            {conversations.isPending ? (
              <p role="status">Loading conversations…</p>
            ) : conversations.isError ? (
              <p role="alert">Conversations could not be loaded.</p>
            ) : (
              <>
                {conversations.isFetching && (
                  <p className="chat-conversations__announcement" role="status">
                    Updating conversations…
                  </p>
                )}

                {conversations.data.items.length === 0 ? (
                  <p>
                    {listOffset === 0 ? 'No conversations yet.' : 'No conversations on this page.'}
                  </p>
                ) : (
                  <nav aria-label="Conversations" aria-busy={conversations.isFetching}>
                    {conversations.data.items.map((conversation) => {
                      const title = conversation.title || 'Untitled conversation';

                      return (
                        <Link
                          key={conversation.conversation_id}
                          to={conversationPath(conversation.conversation_id)}
                          title={title}
                          aria-current={
                            parsedId?.success && parsedId.data === conversation.conversation_id
                              ? 'page'
                              : undefined
                          }
                        >
                          <span>{title}</span>
                        </Link>
                      );
                    })}
                  </nav>
                )}
              </>
            )}
          </div>

          <div className="chat-conversations__footer">
            {(listOffset > 0 || (conversations.isSuccess && conversations.data.has_more)) && (
              <nav className="chat-conversations__pagination" aria-label="Conversation pages">
                {listOffset > 0 && (
                  <button
                    type="button"
                    className="chat-icon-button chat-conversations__previous"
                    aria-label="Previous conversations"
                    title="Previous conversations"
                    disabled={conversations.isFetching}
                    onClick={() =>
                      changePage('conversationsOffset', Math.max(0, listOffset - conversationLimit))
                    }
                  >
                    <ArrowLeft size={18} aria-hidden="true" />
                  </button>
                )}

                {conversations.isSuccess && conversations.data.has_more && (
                  <button
                    type="button"
                    className="chat-icon-button chat-conversations__next"
                    aria-label="Next conversations"
                    title="Next conversations"
                    disabled={conversations.isFetching}
                    onClick={() => {
                      const next = conversations.data.next_offset;

                      if (next != null) {
                        changePage('conversationsOffset', next);
                      }
                    }}
                  >
                    <ArrowRight size={18} aria-hidden="true" />
                  </button>
                )}
              </nav>
            )}
          </div>
        </section>

        <nav className="chat-rail__account" aria-label="Account">
          <button
            type="button"
            className="chat-icon-button"
            aria-label="Sign out"
            title="Sign out"
            onClick={requestLogout}
          >
            <LogOut size={20} aria-hidden="true" />
          </button>
        </nav>
      </aside>

      <main
        id="chat-content"
        className={
          isDraft
            ? 'chat-reading chat-reading--draft'
            : parsedId === null
              ? 'chat-reading chat-reading--welcome'
              : parsedId.success
                ? 'chat-reading chat-reading--conversation'
                : 'chat-reading'
        }
        tabIndex={-1}
        aria-labelledby="chat-title"
      >
        <h1 id="chat-title" ref={heading} tabIndex={-1}>
          Customer Chat
        </h1>

        {(parsedId?.success || isDraft) && exitNotice && (
          <p className="chat-exit-notice" role="status">
            {exitNotice}
          </p>
        )}

        {parsedId === null ? (
          isDraft ? (
            <ConversationDraft
              key={draftRevision}
              onRequestLeave={() => requestDraftNavigation('/chat')}
            />
          ) : (
            <ChatWelcome />
          )
        ) : !parsedId.success ? (
          <p role="alert">This conversation address is invalid.</p>
        ) : (
          <ConversationHistory
            key={parsedId.data}
            conversationId={parsedId.data}
            offset={messageOffset}
            openLatest={!search.has('messagesOffset')}
            onPageChange={(offset, replace) => changePage('messagesOffset', offset, replace)}
          />
        )}
      </main>
      {draftExit !== null && (
        <DraftExitDialog
          startingNew={draftExit.kind === 'new'}
          onCancel={() => setDraftExit(null)}
          onConfirm={confirmDraftExit}
        />
      )}
    </div>
  );
}
