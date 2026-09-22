// apps/web/src/features/knowledge/knowledge-confirmation-dialog.tsx

import { useEffect, useId, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { LoaderCircle, X } from 'lucide-react';

import './knowledge-dialog.css';

export type KnowledgeConfirmationVariant = 'default' | 'danger';

interface KnowledgeConfirmationDialogProps {
  readonly open: boolean;
  readonly title: string;
  readonly description: string;
  readonly confirmLabel: string;
  readonly pendingLabel: string;

  readonly cancelLabel?: string;

  readonly variant?: KnowledgeConfirmationVariant;

  readonly icon?: ReactNode;
  readonly children?: ReactNode;

  readonly pending: boolean;
  readonly confirmDisabled?: boolean;

  readonly onConfirm: () => void;
  readonly onClose: () => void;
}

export function KnowledgeConfirmationDialog({
  open,
  title,
  description,
  confirmLabel,
  pendingLabel,
  cancelLabel = 'Cancel',
  variant = 'default',
  icon,
  children,
  pending,
  confirmDisabled = false,
  onConfirm,
  onClose,
}: KnowledgeConfirmationDialogProps) {
  const titleId = useId();
  const descriptionId = useId();

  const dialogRef = useRef<HTMLDialogElement>(null);

  const cancelButtonRef = useRef<HTMLButtonElement>(null);

  const triggerRef = useRef<HTMLElement | null>(null);

  const previouslyOpenRef = useRef(false);

  /*
   * Open and close the native dialog in response to React
   * state. Trigger focus is captured only when moving from
   * closed to open.
   */
  useEffect(() => {
    const dialog = dialogRef.current;

    if (dialog === null) {
      return;
    }

    if (open && !previouslyOpenRef.current) {
      triggerRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;

      if (!dialog.open) {
        dialog.showModal();
      }

      cancelButtonRef.current?.focus({
        preventScroll: true,
      });
    }

    if (!open && previouslyOpenRef.current) {
      if (dialog.open) {
        dialog.close();
      }

      if (triggerRef.current?.isConnected) {
        triggerRef.current.focus({
          preventScroll: true,
        });
      }

      triggerRef.current = null;
    }

    previouslyOpenRef.current = open;
  }, [open]);

  /*
   * Ensure the native top-layer dialog is closed if its
   * owning component unmounts while open.
   */
  useEffect(
    () => () => {
      const dialog = dialogRef.current;

      if (dialog?.open) {
        dialog.close();
      }
    },
    [],
  );

  function requestClose() {
    if (pending) {
      return;
    }

    onClose();
  }

  function confirm() {
    if (pending || confirmDisabled) {
      return;
    }

    onConfirm();
  }

  if (!open) {
    return null;
  }

  return createPortal(
    <dialog
      ref={dialogRef}
      className={[
        'knowledge-confirmation-dialog',
        `knowledge-confirmation-dialog--${variant}`,
      ].join(' ')}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      aria-modal="true"
      aria-busy={pending}
      onCancel={(event) => {
        /*
         * Prevent the browser from independently closing
         * the dialog. React state remains authoritative.
         */
        event.preventDefault();
        requestClose();
      }}
      onClick={(event) => {
        /*
         * A click whose target is the dialog itself came
         * from the backdrop rather than the card.
         */
        if (event.target === event.currentTarget) {
          requestClose();
        }
      }}
    >
      <section className="knowledge-confirmation-dialog__card">
        <div className="knowledge-confirmation-dialog__topline">
          {icon !== undefined && (
            <span className="knowledge-confirmation-dialog__icon" aria-hidden="true">
              {icon}
            </span>
          )}

          <button
            type="button"
            className="knowledge-confirmation-dialog__dismiss"
            aria-label="Close confirmation"
            disabled={pending}
            onClick={requestClose}
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        <div className="knowledge-confirmation-dialog__copy">
          <h2 id={titleId} tabIndex={-1}>
            {title}
          </h2>

          <p id={descriptionId}>{description}</p>
        </div>

        {children !== undefined && (
          <div className="knowledge-confirmation-dialog__content">{children}</div>
        )}

        <div className="knowledge-confirmation-dialog__actions">
          <button
            ref={cancelButtonRef}
            type="button"
            className="knowledge-confirmation-dialog__action knowledge-confirmation-dialog__action--outline"
            disabled={pending}
            onClick={requestClose}
          >
            {cancelLabel}
          </button>

          <button
            type="button"
            className={[
              'knowledge-confirmation-dialog__action',
              'knowledge-confirmation-dialog__action--solid',

              variant === 'danger' ? 'knowledge-confirmation-dialog__action--danger' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            disabled={pending || confirmDisabled}
            onClick={confirm}
          >
            {pending && <LoaderCircle size={18} className="is-spinning" aria-hidden="true" />}

            {pending ? pendingLabel : confirmLabel}
          </button>
        </div>

        <p
          className="knowledge-confirmation-dialog__status"
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          {pending ? `${pendingLabel}. Please wait for confirmation.` : ''}
        </p>
      </section>
    </dialog>,
    document.body,
  );
}
