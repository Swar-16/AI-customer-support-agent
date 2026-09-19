// apps/web/src/features/operations/create-escalation-ticket-dialog.tsx
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { CircleAlert, LoaderCircle, TicketPlus, X } from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import {
  escalationPrioritySchema,
  escalationTicketDraftSchema,
  ticketCategorySchema,
  type EscalationDetail,
  type EscalationTicketDraft,
} from './escalation-contract';

interface CreateEscalationTicketDialogProps {
  readonly escalation: EscalationDetail;
  readonly pending: boolean;
  readonly error: unknown;
  readonly onCancel: () => void;
  readonly onSubmit: (draft: EscalationTicketDraft) => Promise<void>;
}

function humanizeCode(value: string): string {
  return value
    .toLowerCase()
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function suggestedCategory(reasonCode: string): EscalationTicketDraft['category'] {
  const reason = reasonCode.toLowerCase();

  if (reason.includes('security') || reason.includes('credential') || reason.includes('fraud')) {
    return 'security';
  }

  if (reason.includes('refund')) return 'refund';

  if (reason.includes('billing') || reason.includes('payment') || reason.includes('charge')) {
    return 'billing';
  }

  if (reason.includes('order') || reason.includes('delivery') || reason.includes('shipping')) {
    return 'order';
  }

  if (reason.includes('account') || reason.includes('login')) {
    return 'account';
  }

  if (reason.includes('technical') || reason.includes('error')) {
    return 'technical';
  }

  if (reason.includes('product')) return 'product';

  return 'general';
}

function initialDraft(escalation: EscalationDetail): EscalationTicketDraft {
  const reason = escalation.reason_summary?.trim() || humanizeCode(escalation.reason_code);

  const descriptionSections = [
    `Escalation reason:\n${reason}`,
    escalation.handoff_summary ? `Handoff summary:\n${escalation.handoff_summary}` : null,
  ].filter((section): section is string => section !== null);

  return {
    subject: reason.slice(0, 300),
    description: descriptionSections.join('\n\n'),
    category: suggestedCategory(escalation.reason_code),
    priority: escalation.priority,
  };
}

function submissionError(error: unknown): string | null {
  if (error === null || error === undefined) {
    return null;
  }

  return error instanceof SafeApiError ? error.message : 'The ticket could not be created.';
}

function ContextValue({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="escalation-ticket-context__item">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function CreateEscalationTicketDialog({
  escalation,
  pending,
  error,
  onCancel,
  onSubmit,
}: CreateEscalationTicketDialogProps) {
  const dialogRef = useRef<HTMLElement>(null);
  const [draft, setDraft] = useState(() => initialDraft(escalation));
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (pending) return;

    const parsed = escalationTicketDraftSchema.safeParse(draft);

    if (!parsed.success) {
      setValidationError(
        'Review the subject, description, category, and priority before creating the ticket.',
      );
      return;
    }

    setValidationError(null);
    void onSubmit(parsed.data);
  }

  const visibleError = validationError ?? submissionError(error);

  return (
    <div
      className="operations-dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !pending) {
          onCancel();
        }
      }}
    >
      <section
        ref={dialogRef}
        className="escalation-ticket-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-ticket-title"
        aria-describedby="create-ticket-description"
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && !pending) {
            event.preventDefault();
            event.stopPropagation();
            onCancel();
          }
        }}
      >
        <header className="escalation-ticket-dialog__header">
          <span className="operations-confirmation-card__icon">
            <TicketPlus size={27} aria-hidden="true" />
          </span>

          <button
            type="button"
            className="escalation-ticket-dialog__close"
            aria-label="Close ticket creation"
            disabled={pending}
            onClick={onCancel}
          >
            <X size={20} aria-hidden="true" />
          </button>
        </header>

        <p className="operations-kicker">Create durable support case</p>

        <h2 id="create-ticket-title">Create ticket from escalation</h2>

        <p id="create-ticket-description">
          Review the suggested details before creating the trackable support ticket.
        </p>

        <dl className="escalation-ticket-context">
          <ContextValue label="Escalation" value={escalation.escalation_id} />

          <ContextValue label="Conversation" value={escalation.conversation_id} />

          {escalation.trigger_message_id ? (
            <ContextValue label="Trigger message" value={escalation.trigger_message_id} />
          ) : null}
        </dl>

        <form className="escalation-ticket-form" onSubmit={submit}>
          <label>
            <span>Subject</span>

            <input
              required
              maxLength={300}
              value={draft.subject}
              disabled={pending}
              onChange={(event) => {
                setDraft((current) => ({
                  ...current,
                  subject: event.target.value,
                }));
              }}
            />
          </label>

          <label>
            <span>Description</span>

            <textarea
              required
              rows={7}
              maxLength={20_000}
              value={draft.description}
              disabled={pending}
              onChange={(event) => {
                setDraft((current) => ({
                  ...current,
                  description: event.target.value,
                }));
              }}
            />
          </label>

          <div className="escalation-ticket-form__row">
            <label>
              <span>Category</span>

              <select
                value={draft.category}
                disabled={pending}
                onChange={(event) => {
                  const parsed = ticketCategorySchema.safeParse(event.target.value);

                  if (!parsed.success) return;

                  setDraft((current) => ({
                    ...current,
                    category: parsed.data,
                  }));
                }}
              >
                <option value="billing">Billing</option>
                <option value="refund">Refund</option>
                <option value="order">Order</option>
                <option value="account">Account</option>
                <option value="technical">Technical</option>
                <option value="security">Security</option>
                <option value="product">Product</option>
                <option value="general">General</option>
                <option value="other">Other</option>
              </select>
            </label>

            <label>
              <span>Priority</span>

              <select
                value={draft.priority}
                disabled={pending}
                onChange={(event) => {
                  const parsed = escalationPrioritySchema.safeParse(event.target.value);

                  if (!parsed.success) return;

                  setDraft((current) => ({
                    ...current,
                    priority: parsed.data,
                  }));
                }}
              >
                <option value="low">Low</option>
                <option value="normal">Normal</option>
                <option value="high">High</option>
                <option value="urgent">Urgent</option>
              </select>
            </label>
          </div>

          {visibleError ? (
            <div className="operations-dialog-error escalation-ticket-dialog__error" role="alert">
              <CircleAlert size={18} aria-hidden="true" />
              <span>{visibleError}</span>
            </div>
          ) : null}

          <div className="operations-confirmation-card__actions">
            <button
              type="button"
              className="operations-button operations-button--secondary"
              disabled={pending}
              onClick={onCancel}
            >
              Cancel
            </button>

            <button
              type="submit"
              className="operations-button operations-button--primary"
              aria-busy={pending}
              disabled={pending || !draft.subject.trim() || !draft.description.trim()}
            >
              {pending ? (
                <>
                  <LoaderCircle className="is-spinning" size={17} aria-hidden="true" />
                  Creating ticket…
                </>
              ) : (
                <>
                  <TicketPlus size={17} aria-hidden="true" />
                  Create ticket
                </>
              )}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
