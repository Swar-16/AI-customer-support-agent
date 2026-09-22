// apps/web/src/features/chat/message-composer.tsx
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { ArrowUp, RefreshCcw, Sparkles } from 'lucide-react';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

import type { TransportResult } from '../../shared/api/transport';
import { customerMessageSchema, type Conversation, type SendMessageResult } from './chat-contract';
import { useDraftUnloadWarning } from './use-draft-unload-warning';
import { useNavigationProtection } from '../../shared/navigation/navigation-protection';

import './message-composer.css';

const formSchema = z.object({
  message: customerMessageSchema,
});

type MessageForm = z.infer<typeof formSchema>;

interface MessageComposerProps {
  readonly status: Conversation['status'];
  readonly disabled?: boolean;

  /*
   * Retained temporarily for compatibility with the parent component.
   * The simplified recovery flow no longer requires explicit discarding.
   */
  readonly onDiscardOutgoing?: () => void;

  readonly onSend: (message: string) => Promise<TransportResult<SendMessageResult>>;

  /**
   * Refresh the authorized conversation and history.
   * Return true only when reconciliation reads succeed.
   * This callback must never resubmit a message.
   */
  readonly onReconcile: () => Promise<boolean>;
}

interface Notice {
  readonly kind: 'fallback' | 'alert' | 'status';
  readonly text: string;
  readonly allowRefresh?: boolean;
}

const FALLBACK_MESSAGE =
  'I’m sorry, but I couldn’t prepare a reliable answer to that request. Please try rephrasing your question, or request human support if you would like help from a support agent.';

function resizeMessageInput(element: HTMLTextAreaElement) {
  const maximum = Number.parseFloat(window.getComputedStyle(element).maxHeight);

  const limit = Number.isFinite(maximum) ? maximum : 200;

  element.style.height = '0px';

  const needed = element.scrollHeight;

  element.style.height = `${Math.min(needed, limit)}px`;
  element.style.overflowY = needed > limit ? 'auto' : 'hidden';
}

export function MessageComposer({
  status,
  disabled = false,
  onSend,
  onReconcile,
}: MessageComposerProps) {
  const id = useId();
  const inFlight = useRef(false);
  const formRef = useRef<HTMLFormElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const focusAfterSubmitRef = useRef(false);

  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<MessageForm>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      message: '',
    },
  });

  const message = useWatch({
    control,
    name: 'message',
    defaultValue: '',
  });

  useNavigationProtection(message.length > 0 || busy);
  useDraftUnloadWarning(message.length > 0 || busy);

  const messageField = register('message');

  useEffect(() => {
    function trackFocus(event: FocusEvent) {
      const target = event.target;

      if (
        target instanceof Node &&
        target !== document.body &&
        !formRef.current?.contains(target)
      ) {
        focusAfterSubmitRef.current = false;
      }
    }

    document.addEventListener('focusin', trackFocus);

    return () => {
      document.removeEventListener('focusin', trackFocus);
    };
  }, []);

  useLayoutEffect(() => {
    const textarea = textareaRef.current;

    if (textarea !== null) {
      resizeMessageInput(textarea);
    }
  }, [message]);

  useEffect(() => {
    function resize() {
      const current = textareaRef.current;

      if (current === null) {
        return;
      }

      resizeMessageInput(current);
    }

    const initialElement = textareaRef.current;

    if (initialElement === null) {
      return;
    }

    window.addEventListener('resize', resize);

    let observer: ResizeObserver | undefined;

    if (typeof ResizeObserver === 'function') {
      let previousWidth = initialElement.clientWidth;

      observer = new ResizeObserver(() => {
        const current = textareaRef.current;

        if (current === null) {
          return;
        }

        if (current.clientWidth !== previousWidth) {
          previousWidth = current.clientWidth;
          resizeMessageInput(current);
        }
      });

      observer.observe(initialElement);
    }

    return () => {
      window.removeEventListener('resize', resize);
      observer?.disconnect();
    };
  }, []);

  const canAcceptMessages =
    status === 'open' ||
    status === 'waiting_for_customer' ||
    status === 'waiting_for_agent' ||
    status === 'escalated';

  const unavailable = disabled || !canAcceptMessages;
  const inputDisabled = unavailable || busy;

  useEffect(() => {
    if (!inputDisabled && focusAfterSubmitRef.current) {
      focusAfterSubmitRef.current = false;
      textareaRef.current?.focus({ preventScroll: true });
    }
  }, [inputDisabled]);

  async function reconcile(): Promise<boolean> {
    try {
      return await onReconcile();
    } catch {
      return false;
    }
  }

  async function submit(values: MessageForm) {
    setNotice(null);

    // The submitted value remains available inside this function if recovery
    // is required. The visible composer is cleared immediately.
    reset({ message: '' });

    let result: TransportResult<SendMessageResult>;

    try {
      result = await onSend(values.message);
    } catch {
      reset({ message: values.message });

      const refreshed = await reconcile();

      setNotice({
        kind: 'alert',
        text: refreshed
          ? 'We could not confirm whether that message was delivered. The latest conversation history has been refreshed; please check it before trying again.'
          : 'We could not confirm whether that message was delivered. Please refresh the conversation history before trying again.',
        allowRefresh: true,
      });

      return;
    }

    if (result.ok) {
      const refreshed = await reconcile();

      if (!result.data.succeeded) {
        setNotice({
          kind: 'fallback',
          text: FALLBACK_MESSAGE,
        });

        return;
      }

      if (!refreshed) {
        setNotice({
          kind: 'alert',
          text: 'Your message was saved, but the latest response could not be loaded. Refresh the conversation history to see it.',
          allowRefresh: true,
        });

        return;
      }

      // The refreshed history now displays the authoritative backend response.
      setNotice(null);
      return;
    }

    reset({ message: values.message });

    const uncertain =
      result.error.kind !== 'http' || result.error.status === null || result.error.status >= 500;

    if (uncertain) {
      const refreshed = await reconcile();

      setNotice({
        kind: 'alert',
        text: refreshed
          ? 'Delivery could not be confirmed. The latest conversation history has been refreshed; please check it before resending.'
          : 'Delivery could not be confirmed. Refresh the conversation history before resending.',
        allowRefresh: true,
      });

      return;
    }

    if (result.error.status === 409) {
      await reconcile();

      setNotice({
        kind: 'status',
        text: 'The conversation state changed before this message could be accepted. Its latest status has been loaded.',
      });

      return;
    }

    setNotice({
      kind: 'alert',
      text: result.error.message,
    });
  }

  async function refreshHistory() {
    if (inFlight.current) {
      return;
    }

    inFlight.current = true;
    setBusy(true);

    try {
      const refreshed = await reconcile();

      if (refreshed) {
        setNotice((current) => (current?.kind === 'fallback' ? current : null));
      } else {
        setNotice({
          kind: 'alert',
          text: 'The latest conversation history is still unavailable. You can continue writing, but avoid resending the same message until its delivery is confirmed.',
          allowRefresh: true,
        });
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <section
      className="message-composer"
      aria-label="Message composer"
      data-navigation-blocked={busy || message.length > 0}
    >
      {notice !== null && (
        <div
          className={`message-composer__notice message-composer__notice--${notice.kind}`}
          role={notice.kind === 'alert' ? 'alert' : 'status'}
        >
          <span className="message-composer__notice-icon" aria-hidden="true">
            {notice.kind === 'fallback' ? <Sparkles size={18} /> : <RefreshCcw size={17} />}
          </span>

          <div>
            <strong>
              {notice.kind === 'fallback'
                ? 'Support assistant'
                : notice.kind === 'alert'
                  ? 'Delivery update'
                  : 'Conversation updated'}
            </strong>

            <p>{notice.text}</p>

            {notice.allowRefresh === true && (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  void refreshHistory();
                }}
              >
                <RefreshCcw
                  size={15}
                  className={busy ? 'is-spinning' : undefined}
                  aria-hidden="true"
                />

                <span>{busy ? 'Refreshing…' : 'Refresh history'}</span>
              </button>
            )}
          </div>
        </div>
      )}

      {!canAcceptMessages && (
        <p role="status">This conversation is {status}. New messages cannot be sent.</p>
      )}

      <form
        ref={formRef}
        aria-label="Send a message"
        aria-busy={busy}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();

          if (inFlight.current || inputDisabled) {
            return;
          }

          const activeElement = document.activeElement;

          focusAfterSubmitRef.current =
            activeElement === document.body ||
            (activeElement !== null && event.currentTarget.contains(activeElement));

          inFlight.current = true;
          setBusy(true);

          void handleSubmit(submit)(event)
            .catch(() => {
              setNotice({
                kind: 'alert',
                text: 'The message could not be submitted. Please try again.',
              });
            })
            .finally(() => {
              inFlight.current = false;
              setBusy(false);
            });
        }}
      >
        <label htmlFor={`${id}-message`} className="message-composer__label">
          Your message
        </label>

        <div className="message-composer__input-row">
          <textarea
            {...messageField}
            ref={(element) => {
              messageField.ref(element);
              textareaRef.current = element;
            }}
            id={`${id}-message`}
            rows={1}
            placeholder="How can we help?"
            disabled={inputDisabled}
            aria-invalid={errors.message ? true : undefined}
            aria-describedby={errors.message ? `${id}-help ${id}-error` : `${id}-help`}
            aria-keyshortcuts="Control+Enter"
            onKeyDown={(event) => {
              if (event.key === 'Enter' && event.ctrlKey && !event.nativeEvent.isComposing) {
                event.preventDefault();

                if (!inputDisabled && !inFlight.current) {
                  event.currentTarget.form?.requestSubmit();
                }
              }
            }}
          />

          <button
            type="submit"
            className="message-composer__send"
            disabled={inputDisabled || message.trim().length === 0}
            aria-label="Send message"
            title="Send message (Ctrl+Enter)"
          >
            <ArrowUp size={21} strokeWidth={2.2} aria-hidden="true" />
          </button>
        </div>

        <p id={`${id}-help`} className="message-composer__help">
          Enter for a new line · Ctrl+Enter to send · Up to 20,000 characters
        </p>

        {errors.message && (
          <p id={`${id}-error`} role="alert">
            {errors.message.message}
          </p>
        )}
      </form>

      {busy && (
        <div className="message-composer__processing" role="status">
          <span className="message-composer__dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>

          <span>Preparing the latest response…</span>
        </div>
      )}
    </section>
  );
}
