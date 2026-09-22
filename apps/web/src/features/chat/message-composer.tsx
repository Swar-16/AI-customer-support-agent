import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { ArrowUp } from 'lucide-react';
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
  readonly onDiscardOutgoing?: () => void;
  readonly onSend: (message: string) => Promise<TransportResult<SendMessageResult>>;

  /**
   * Refresh the authorized conversation and history.
   * Return true only when reconciliation reads succeed.
   * This callback must never resubmit a message.
   */
  readonly onReconcile: () => Promise<boolean>;
}

type Notice = {
  readonly tone: 'status' | 'alert';
  readonly text: string;
};

const UNCERTAIN_MESSAGE =
  'The outcome could not be confirmed. Your message may already be saved or still processing. Review the latest history before writing another message.';

function successfulNotice(result: SendMessageResult): Notice {
  if (!result.succeeded) {
    return {
      tone: 'alert',
      text: 'Your message was received, but processing did not complete. Review the conversation before continuing.',
    };
  }

  return {
    tone: 'status',
    text: 'Your message was received successfully.',
  };
}

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
  onDiscardOutgoing,
}: MessageComposerProps) {
  const id = useId();
  const inFlight = useRef(false);
  const formRef = useRef<HTMLFormElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const focusAfterSubmitRef = useRef(false);

  useEffect(() => {
    function trackFocus(event: FocusEvent) {
      const target = event.target;

      if (
        target instanceof Node &&
        target !== document.body &&
        !formRef.current?.contains(target)
      ) {
        // Do not steal focus from support details or another control.
        focusAfterSubmitRef.current = false;
      }
    }

    document.addEventListener('focusin', trackFocus);

    return () => {
      document.removeEventListener('focusin', trackFocus);
    };
  }, []);

  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [reviewRequired, setReviewRequired] = useState(false);
  const [historyRefreshed, setHistoryRefreshed] = useState(false);
  const [reviewed, setReviewed] = useState(false);

  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<MessageForm>({
    resolver: zodResolver(formSchema),
    defaultValues: { message: '' },
  });

  const message = useWatch({
    control,
    name: 'message',
    defaultValue: '',
  });

  useNavigationProtection(message.length > 0 || busy || reviewRequired);

  useDraftUnloadWarning(message.length > 0 || busy || reviewRequired);

  const messageField = register('message');

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) resizeMessageInput(textarea);
  }, [message]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    function resize() {
      if (textarea) resizeMessageInput(textarea);
    }

    window.addEventListener('resize', resize);

    let observer: ResizeObserver | undefined;

    if (typeof ResizeObserver === 'function') {
      let previousWidth = textarea.clientWidth;

      observer = new ResizeObserver(() => {
        if (textarea.clientWidth !== previousWidth) {
          previousWidth = textarea.clientWidth;
          resize();
        }
      });

      observer.observe(textarea);
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
  const inputDisabled = unavailable || busy || reviewRequired;
  useEffect(() => {
    if (!busy && !inputDisabled && focusAfterSubmitRef.current) {
      focusAfterSubmitRef.current = false;
      textareaRef.current?.focus({ preventScroll: true });
    }
  }, [busy, inputDisabled]);

  function requireReview(text: string) {
    setReviewRequired(true);
    setHistoryRefreshed(false);
    setReviewed(false);
    setNotice({ tone: 'alert', text });
  }

  async function reconcile(): Promise<boolean> {
    try {
      return await onReconcile();
    } catch {
      // Never expose exceptions from networking or query callbacks.
      return false;
    }
  }

  async function submit(values: MessageForm) {
    setNotice(null);
    setHistoryRefreshed(false);
    setReviewed(false);
    // The validated draft remains in this function's memory while sending.
    // Clear the visible input immediately, without persisting it anywhere.
    reset({ message: '' });

    let result: TransportResult<SendMessageResult>;

    try {
      result = await onSend(values.message);
    } catch {
      reset({ message: values.message });
      requireReview(UNCERTAIN_MESSAGE);
      setHistoryRefreshed(await reconcile());
      return;
    }

    if (result.ok) {
      // A confirmed response identifies the persisted customer message.
      // Clear the draft even if subsequent history refresh fails.
      // reset({ message: '' });
      setNotice(successfulNotice(result.data));

      const refreshed = await reconcile();

      if (!refreshed) {
        requireReview(
          'Your message was received, but the latest history could not be loaded. Refresh the history before continuing.',
        );
      } else if (!result.data.succeeded) {
        requireReview(
          'Your message was received, but processing did not complete. Review the refreshed history before continuing.',
        );
        setHistoryRefreshed(true);
      }

      return;
    }

    // The submission was not acknowledged. Restore the draft for recovery.
    reset({ message: values.message });

    const uncertain =
      result.error.kind !== 'http' || result.error.status === null || result.error.status >= 500;

    if (uncertain) {
      requireReview(UNCERTAIN_MESSAGE);
      setHistoryRefreshed(await reconcile());
      return;
    }

    // SafeApiError owns this allowlisted message; never use raw API errors.
    setNotice({ tone: 'alert', text: result.error.message });

    // A conflict may mean another request changed the lifecycle.
    if (result.error.status === 409) {
      requireReview(
        'The conversation could not accept this message. Review its current status and history before continuing.',
      );
      setHistoryRefreshed(await reconcile());
    }
  }

  async function refreshHistory() {
    if (inFlight.current) return;

    inFlight.current = true;
    setBusy(true);
    setReviewed(false);

    try {
      const refreshed = await reconcile();
      setHistoryRefreshed(refreshed);

      if (!refreshed) {
        setNotice({
          tone: 'alert',
          text: 'The latest history could not be loaded. Sending remains paused.',
        });
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  function beginNewMessage() {
    if (inFlight.current || unavailable || !historyRefreshed || !reviewed) {
      return;
    }

    focusAfterSubmitRef.current = true;
    // Explicitly discard the old draft; this action never sends anything.
    reset({ message: '' });
    onDiscardOutgoing?.();
    setReviewRequired(false);
    setHistoryRefreshed(false);
    setReviewed(false);
    setNotice({
      tone: 'status',
      text: 'Write a new message. The previous message will not be resent automatically.',
    });
  }

  return (
    <section
      className="message-composer"
      aria-label="Message composer"
      data-navigation-blocked={busy || reviewRequired || message.length > 0}
    >
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

          if (inFlight.current || inputDisabled) return;

          const activeElement = document.activeElement;
          focusAfterSubmitRef.current =
            activeElement === document.body ||
            (activeElement !== null && event.currentTarget.contains(activeElement));

          // Acquire the lock before asynchronous validation.
          inFlight.current = true;
          setBusy(true);

          void handleSubmit(submit)(event)
            .catch(() => {
              requireReview(UNCERTAIN_MESSAGE);
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
            disabled={inputDisabled}
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

      {busy && reviewRequired && <p role="status">Refreshing message history…</p>}

      {notice && <p role={notice.tone}>{notice.text}</p>}

      {reviewRequired && (
        <div className="message-composer__review">
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              void refreshHistory();
            }}
          >
            Refresh message history
          </button>

          <label>
            <input
              type="checkbox"
              checked={reviewed}
              disabled={busy || !historyRefreshed || unavailable}
              onChange={(event) => setReviewed(event.target.checked)}
            />
            I have reviewed the latest messages and conversation status.
          </label>

          <button
            type="button"
            disabled={busy || unavailable || !historyRefreshed || !reviewed}
            onClick={beginNewMessage}
          >
            Discard draft and write a new message
          </button>

          <p className="message-composer__help">
            Refreshing history does not prove that an earlier request stopped processing. Avoid
            repeating the same request.
          </p>
        </div>
      )}
    </section>
  );
}
