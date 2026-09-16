// apps/web/src/features/chat/close-conversation.tsx

import { useEffect, useId, useRef } from 'react';
import { Check, CircleCheck, LoaderCircle, X } from 'lucide-react';

interface CloseConversationProps {
  readonly closed: boolean;
  readonly disabled: boolean;
  readonly phase: 'idle' | 'pending' | 'uncertain' | 'confirmed';
  readonly notice: string | null;
  readonly checking: boolean;
  readonly canRetry: boolean;
  readonly onClose: () => Promise<void>;
  readonly onCheckStatus: () => Promise<void>;
}

export function CloseConversation({
  closed,
  disabled,
  phase,
  notice,
  checking,
  canRetry,
  onClose,
  onCheckStatus,
}: CloseConversationProps) {
  const id = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const outcomeRef = useRef<HTMLParagraphElement>(null);

  const confirmed = closed || phase === 'confirmed';
  const busy = phase === 'pending' || checking;

  useEffect(() => {
    const dialog = dialogRef.current;

    if (dialog?.open && (confirmed || phase === 'uncertain')) {
      dialog.close();
      outcomeRef.current?.focus({ preventScroll: true });
    }
  }, [confirmed, phase]);

  function openConfirmation() {
    if (disabled || busy || confirmed) return;

    const dialog = dialogRef.current;
    if (!dialog || dialog.open) return;

    dialog.showModal();
    cancelRef.current?.focus({ preventScroll: true });
  }

  function dismissConfirmation() {
    if (busy) return;

    dialogRef.current?.close();
    triggerRef.current?.focus({ preventScroll: true });
  }

  return (
    <div className="chat-close">
      {confirmed ? (
        <p ref={outcomeRef} className="chat-close__confirmed" role="status" tabIndex={-1}>
          <Check size={16} aria-hidden="true" />
          {notice ?? 'This conversation is closed.'}
        </p>
      ) : phase === 'uncertain' ? (
        <div className="chat-close__recovery">
          <p ref={outcomeRef} role="alert" tabIndex={-1}>
            {notice ?? 'Closure could not be confirmed. Check the conversation status.'}
          </p>

          <div className="chat-close__actions">
            <button
              type="button"
              className="chat-action chat-action--outline"
              disabled={busy}
              onClick={() => {
                void onCheckStatus();
              }}
            >
              {checking ? 'Checking status…' : 'Check conversation status'}
            </button>

            {canRetry && (
              <button
                ref={triggerRef}
                type="button"
                className="chat-action chat-action--solid"
                disabled={busy || disabled}
                onClick={openConfirmation}
              >
                Confirm close again
              </button>
            )}
          </div>
        </div>
      ) : (
        <button
          ref={triggerRef}
          type="button"
          className="chat-action chat-action--outline"
          disabled={disabled || busy}
          aria-haspopup="dialog"
          onClick={openConfirmation}
        >
          <CircleCheck size={18} aria-hidden="true" />
          Close conversation
        </button>
      )}

      <dialog
        ref={dialogRef}
        className="chat-close-dialog"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-description`}
        aria-busy={phase === 'pending'}
        onCancel={(event) => {
          event.preventDefault();
          dismissConfirmation();
        }}
      >
        <div className="chat-close-dialog__top">
          <span className="chat-close-dialog__emblem" aria-hidden="true">
            <CircleCheck size={27} />
          </span>

          <button
            type="button"
            className="chat-close-dialog__dismiss"
            aria-label="Dismiss close confirmation"
            title="Dismiss close confirmation"
            disabled={busy}
            onClick={dismissConfirmation}
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        <h2 id={`${id}-title`}>Close this conversation?</h2>

        <p id={`${id}-description`}>
          Your messages will remain available to read. You won’t be able to send more messages here,
          and this conversation cannot be reopened.
        </p>

        <div className="chat-close-dialog__actions">
          <button
            ref={cancelRef}
            type="button"
            className="chat-action chat-action--outline"
            disabled={busy}
            onClick={dismissConfirmation}
          >
            Keep conversation open
          </button>

          <button
            type="button"
            className="chat-action chat-action--solid"
            disabled={disabled || busy || confirmed}
            onClick={() => {
              void onClose();
            }}
          >
            {phase === 'pending' ? (
              <LoaderCircle size={18} className="chat-close-dialog__spinner" aria-hidden="true" />
            ) : (
              <Check size={18} aria-hidden="true" />
            )}
            {phase === 'pending' ? 'Closing…' : 'Confirm close'}
          </button>
        </div>

        <p className="chat-close-dialog__progress" role="status">
          {phase === 'pending' ? 'Waiting for closure confirmation…' : ''}
        </p>

        {notice && phase === 'idle' && (
          <p role="alert" className="chat-close-dialog__error">
            {notice}
          </p>
        )}
      </dialog>
    </div>
  );
}
