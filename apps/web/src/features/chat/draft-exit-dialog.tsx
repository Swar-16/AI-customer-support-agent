// apps/web/src/features/chat/draft-exit-dialog.tsx
import { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';

import './draft-exit-dialog.css';

interface DraftExitDialogProps {
  readonly startingNew: boolean;
  readonly onCancel: () => void;
  readonly onConfirm: () => void;
}

export function DraftExitDialog({ startingNew, onCancel, onConfirm }: DraftExitDialogProps) {
  const id = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return;

    const previousFocus = document.activeElement;

    if (!dialog.open) {
      dialog.showModal();
    }

    cancelRef.current?.focus();

    return () => {
      dialog.close();

      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) {
        previousFocus.focus({ preventScroll: true });
      }
    };
  }, []);

  return createPortal(
    <dialog
      ref={dialogRef}
      className="draft-exit-dialog"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-description`}
      onCancel={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onCancel();
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.stopPropagation();
        }
      }}
    >
      <div className="draft-exit-dialog__spark" aria-hidden="true">
        ✦
      </div>

      <h2 id={`${id}-title`}>
        {startingNew ? 'Start a separate conversation?' : 'Leave this draft?'}
      </h2>

      <p id={`${id}-description`}>
        Unsent text will be discarded. If you already sent a message, it may be saved in your
        history. Leaving stops checking its result here; it does not cancel processing or resend the
        message.
      </p>

      <div className="draft-exit-dialog__actions">
        <button
          ref={cancelRef}
          type="button"
          className="draft-exit-dialog__button draft-exit-dialog__button--outline"
          onClick={onCancel}
        >
          Stay here
        </button>

        <button
          type="button"
          className="draft-exit-dialog__button draft-exit-dialog__button--primary"
          onClick={onConfirm}
        >
          {startingNew ? 'Start new conversation' : 'Leave draft'}
        </button>
      </div>
    </dialog>,
    document.body,
  );
}
