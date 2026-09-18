// apps/web/src/features/chat/conversation-draft.tsx
import { useContext, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { ArrowUp, LoaderCircle } from 'lucide-react';

import { TransportContext } from '../../shared/api/transport-context';
import { useSessionController } from '../../shared/auth/session-context';

import { customerMessageSchema } from './chat-contract';
import { chatKeys } from './chat-queries';
import { createStartConversationApi } from './start-conversation-api';
import {
  createStartConversationCoordinator,
  type StartConversationCoordinator,
  type StartConversationState,
} from './start-conversation-coordinator';
import { useDraftUnloadWarning } from './use-draft-unload-warning';
import { useNavigationProtection } from '../../shared/navigation/navigation-protection';

import { OutgoingTurn } from './outgoing-turn';
import type { OutgoingMessage } from './outgoing-message';

import './conversation-draft.css';

interface ConversationDraftProps {
  readonly onRequestLeave: () => void;
}

export function ConversationDraft({ onRequestLeave }: ConversationDraftProps) {
  const request = useContext(TransportContext);
  const session = useSessionController();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const coordinatorRef = useRef<StartConversationCoordinator | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [state, setState] = useState<StartConversationState>({
    phase: 'idle',
  });
  const [message, setMessage] = useState('');
  const [validationError, setValidationError] = useState<string | null>(null);
  const [recoveryReady, setRecoveryReady] = useState(false);
  const [submitted, setSubmitted] = useState<OutgoingMessage | null>(null);

  const draftNeedsProtection =
    state.phase !== 'disposed' &&
    state.phase !== 'terminal' &&
    (state.phase !== 'idle' || message.length > 0);

  const releaseNavigationProtection = useNavigationProtection(draftNeedsProtection);

  const needsUnloadWarning =
    (state.phase === 'idle' && message.length > 0) ||
    state.phase === 'pending' ||
    state.phase === 'processing' ||
    state.phase === 'uncertain';

  useDraftUnloadWarning(needsUnloadWarning);

  useEffect(() => {
    if (request === null || request === undefined) {
      return;
    }

    const startingSession = session.getSnapshot();

    if (startingSession.phase !== 'authenticated' || startingSession.user?.role !== 'customer') {
      return;
    }

    const ownerId = startingSession.user.id;
    const coordinator = createStartConversationCoordinator({
      api: createStartConversationApi(request),
    });

    coordinatorRef.current = coordinator;

    function ownsSession() {
      const current = session.getSnapshot();

      return (
        current.phase === 'authenticated' &&
        current.user?.id === ownerId &&
        current.user.role === 'customer'
      );
    }

    const unsubscribeCoordinator = coordinator.subscribe(() => {
      if (!ownsSession()) {
        return;
      }

      const next = coordinator.getSnapshot();
      setState(next);

      if (next.phase === 'terminal') {
        // History and detail remain authoritative, including the generated title.
        void queryClient.invalidateQueries({
          queryKey: chatKeys.all(ownerId),
        });

        if (next.result.outcome !== 'failed') {
          releaseNavigationProtection();
          void navigate(`/chat/${next.result.data.conversation_id}`, {
            replace: true,
          });
        }
      }
    });

    const unsubscribeSession = session.subscribe(() => {
      if (!ownsSession()) {
        coordinator.dispose();
        setMessage('');
        setSubmitted(null);
        setState({ phase: 'disposed' });
      }
    });

    return () => {
      unsubscribeCoordinator();
      unsubscribeSession();
      coordinator.dispose();

      if (coordinatorRef.current === coordinator) {
        coordinatorRef.current = null;
      }
    };
  }, [request, session, queryClient, navigate, releaseNavigationProtection]);

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (textarea === null) return;

    textarea.style.height = 'auto';
    const height = Math.min(200, Math.max(48, textarea.scrollHeight));
    textarea.style.height = `${height}px`;
    textarea.style.overflowY = textarea.scrollHeight > 200 ? 'auto' : 'hidden';
  }, [message]);

  const retryAt =
    state.phase === 'processing' || state.phase === 'uncertain' ? state.retryAt : null;

  useEffect(() => {
    if (retryAt === null) return;

    const timer = window.setTimeout(
      () => {
        setRecoveryReady(true);
      },
      Math.max(0, retryAt - Date.now()),
    );

    return () => window.clearTimeout(timer);
  }, [retryAt]);

  const editable = state.phase === 'idle';

  function submit() {
    const coordinator = coordinatorRef.current;
    if (coordinator === null || coordinator.getSnapshot().phase !== 'idle') {
      return;
    }

    const parsed = customerMessageSchema.safeParse(message);

    if (!parsed.success) {
      setValidationError('Enter a message using 20,000 characters or fewer.');
      textareaRef.current?.focus();
      return;
    }

    setValidationError(null);
    setRecoveryReady(false);

    setSubmitted({
      localId: 'first-message',
      content: parsed.data,
      createdAt: new Date().toISOString(),
      messageId: null,
      phase: 'sending',
    });

    // The coordinator retains the immutable submitted text for recovery.
    setMessage('');
    void coordinator.submit(parsed.data);
  }

  function recover() {
    setRecoveryReady(false);
    void coordinatorRef.current?.recover();
  }

  function openConversation(id: string) {
    releaseNavigationProtection();
    void navigate(`/chat/${id}`, { replace: true });
  }

  const recoverable = state.phase === 'processing' || state.phase === 'uncertain';
  const outgoing: OutgoingMessage | null =
    submitted === null || state.phase === 'disposed'
      ? null
      : {
          ...submitted,
          phase:
            state.phase === 'pending'
              ? 'sending'
              : state.phase === 'processing'
                ? 'processing'
                : state.phase === 'terminal'
                  ? 'saved'
                  : state.phase === 'blocked' || state.phase === 'uncertain'
                    ? 'uncertain'
                    : submitted.phase,
        };

  return (
    <section
      className={`conversation-draft message-composer${outgoing ? ' conversation-draft--submitted' : ''}`}
      aria-labelledby="draft-title"
      data-navigation-blocked={draftNeedsProtection ? 'true' : 'false'}
    >
      <header hidden={outgoing !== null}>
        <h2 id="draft-title">What can we help you with?</h2>
        <p>Your conversation begins when you send your first message.</p>
      </header>

      {outgoing && (
        <div className="conversation-draft__transcript" data-chat-scroll>
          <OutgoingTurn message={outgoing} />
        </div>
      )}

      <form
        noValidate
        aria-label="Start a conversation"
        aria-busy={state.phase === 'pending'}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label className="conversation-draft__label" htmlFor="draft-message">
          Your message
        </label>

        <div className="conversation-draft__input">
          <textarea
            id="draft-message"
            ref={textareaRef}
            value={message}
            rows={1}
            disabled={!editable}
            placeholder="How can we help?"
            aria-describedby={validationError ? 'draft-help draft-validation' : 'draft-help'}
            aria-invalid={validationError !== null}
            onChange={(event) => {
              setMessage(event.target.value);
              setValidationError(null);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && event.ctrlKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                submit();
              }
            }}
          />

          <button
            className="conversation-draft__send"
            type="submit"
            aria-label="Send first message"
            title="Send first message"
            disabled={!editable || message.trim().length === 0}
          >
            {state.phase === 'pending' ? (
              <LoaderCircle className="conversation-draft__spinner" size={21} aria-hidden="true" />
            ) : (
              <ArrowUp size={21} aria-hidden="true" />
            )}
          </button>
        </div>

        <p id="draft-help" className="conversation-draft__hint">
          Enter for a new line · Ctrl+Enter to send · Up to 20,000 characters
        </p>

        {validationError && (
          <p id="draft-validation" role="alert">
            {validationError}
          </p>
        )}
      </form>

      {state.phase === 'uncertain' && (
        <div>
          <p role="alert">{state.error.message}</p>

          {state.error.traceId && (
            <p className="conversation-draft__hint">Request reference: {state.error.traceId}</p>
          )}
        </div>
      )}

      {recoverable && (
        <div className="conversation-draft__status">
          <p role="status">
            {state.phase === 'processing'
              ? 'Your conversation has been created. The response is still being processed.'
              : 'We could not confirm the result. Check the same submission before starting another conversation.'}
          </p>

          {state.attemptsRemaining > 0 ? (
            <button
              type="button"
              className="conversation-draft__action"
              disabled={!recoveryReady}
              onClick={recover}
            >
              {recoveryReady ? 'Check again' : 'Please wait before checking'}
            </button>
          ) : (
            <p>
              The checking limit has been reached. Refresh the conversation list and inspect your
              recent conversations before starting again.
            </p>
          )}

          {state.phase === 'processing' && state.attemptsRemaining === 0 && (
            <button
              type="button"
              className="conversation-draft__action"
              onClick={() => openConversation(state.conversationId)}
            >
              Open saved conversation
            </button>
          )}
        </div>
      )}

      {state.phase === 'terminal' && state.result.outcome === 'failed' && (
        <div className="conversation-draft__status">
          <p role="alert">
            Your conversation and message were saved, but a response could not be completed. Open
            the saved conversation to review its history.
          </p>
          <button
            type="button"
            className="conversation-draft__action"
            onClick={() => openConversation(state.result.data.conversation_id)}
          >
            Open saved conversation
          </button>
        </div>
      )}

      {state.phase === 'blocked' && (
        <p role="alert">
          {state.error.message} Refresh the conversation list before attempting another start.
        </p>
      )}

      {state.phase === 'disposed' && (
        <p role="status">Your session changed. Please sign in again.</p>
      )}
      <button type="button" className="conversation-draft__action" onClick={onRequestLeave}>
        Back to conversations
      </button>
    </section>
  );
}
