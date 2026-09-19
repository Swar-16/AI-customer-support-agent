// apps/web/src/features/operations/ticket-actions.tsx
import { useEffect, useState, type FormEvent } from 'react';
import { CheckCircle2, CircleAlert, RotateCcw, UserMinus, UserRoundCheck, X } from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TicketUpdateInput } from './ticket-api';
import {
  ticketCategorySchema,
  ticketPrioritySchema,
  type Ticket,
  type TicketStatus,
} from './ticket-contract';
import { useUpdateTicket } from './ticket-queries';

interface StatusAction {
  readonly status: TicketStatus;
  readonly label: string;
  readonly tone: 'primary' | 'secondary';
}

const statusLabels: Record<TicketStatus, string> = {
  open: 'Open',
  in_progress: 'In progress',
  waiting_for_customer: 'Waiting for customer',
  resolved: 'Resolved',
  closed: 'Closed',
  reopened: 'Reopened',
};

function availableStatusActions(status: TicketStatus): readonly StatusAction[] {
  switch (status) {
    case 'open':
      return [
        {
          status: 'in_progress',
          label: 'Start progress',
          tone: 'primary',
        },
        {
          status: 'waiting_for_customer',
          label: 'Wait for customer',
          tone: 'secondary',
        },
        {
          status: 'resolved',
          label: 'Resolve',
          tone: 'secondary',
        },
      ];

    case 'in_progress':
      return [
        {
          status: 'waiting_for_customer',
          label: 'Wait for customer',
          tone: 'secondary',
        },
        {
          status: 'resolved',
          label: 'Resolve',
          tone: 'primary',
        },
      ];

    case 'waiting_for_customer':
      return [
        {
          status: 'in_progress',
          label: 'Resume progress',
          tone: 'primary',
        },
        {
          status: 'resolved',
          label: 'Resolve',
          tone: 'secondary',
        },
      ];

    case 'resolved':
      return [
        {
          status: 'closed',
          label: 'Close ticket',
          tone: 'primary',
        },
        {
          status: 'reopened',
          label: 'Reopen',
          tone: 'secondary',
        },
      ];

    case 'closed':
      return [
        {
          status: 'reopened',
          label: 'Reopen ticket',
          tone: 'primary',
        },
      ];

    case 'reopened':
      return [
        {
          status: 'in_progress',
          label: 'Start progress',
          tone: 'primary',
        },
        {
          status: 'waiting_for_customer',
          label: 'Wait for customer',
          tone: 'secondary',
        },
        {
          status: 'resolved',
          label: 'Resolve',
          tone: 'secondary',
        },
      ];
  }
}

function updateErrorMessage(error: unknown): string {
  if (error instanceof SafeApiError && error.status === 409) {
    return 'This ticket changed after it was opened. Its latest state is being loaded; review it before trying again.';
  }

  return error instanceof SafeApiError ? error.message : 'The ticket could not be updated.';
}

function TicketTransitionDialog({
  targetStatus,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  readonly targetStatus: TicketStatus;
  readonly pending: boolean;
  readonly error: unknown;
  readonly onCancel: () => void;
  readonly onConfirm: (resolutionSummary: string | null) => void;
}) {
  const [resolutionSummary, setResolutionSummary] = useState('');

  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key !== 'Escape' || event.defaultPrevented || pending) {
        return;
      }

      event.preventDefault();
      onCancel();
    }

    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onCancel, pending]);

  const resolving = targetStatus === 'resolved';
  const normalizedSummary = resolutionSummary.trim();
  const confirmationDisabled = pending || (resolving && normalizedSummary.length === 0);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (confirmationDisabled) return;

    onConfirm(resolving ? normalizedSummary : null);
  }

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
      <form
        className="operations-confirmation-card ticket-transition-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="ticket-transition-title"
        onSubmit={submit}
      >
        <span className="operations-confirmation-card__icon">
          {targetStatus === 'reopened' ? (
            <RotateCcw size={27} aria-hidden="true" />
          ) : (
            <CheckCircle2 size={27} aria-hidden="true" />
          )}
        </span>

        <p className="operations-kicker">Confirm ticket transition</p>

        <h2 id="ticket-transition-title">Mark as {statusLabels[targetStatus].toLowerCase()}?</h2>

        <p>
          The latest ticket version will be used. If another operator changed it first, this update
          will be rejected and refreshed safely.
        </p>

        {resolving ? (
          <label className="ticket-resolution-field">
            <span>Resolution summary</span>

            <textarea
              autoFocus
              required
              maxLength={5_000}
              rows={4}
              value={resolutionSummary}
              placeholder="Describe how the customer’s issue was resolved."
              onChange={(event) => {
                setResolutionSummary(event.target.value);
              }}
            />

            <small>
              Required · {resolutionSummary.length.toLocaleString()}
              /5,000
            </small>
          </label>
        ) : null}

        {error ? (
          <p className="operations-dialog-error" role="alert">
            {updateErrorMessage(error)}
          </p>
        ) : null}

        <div className="operations-confirmation-card__actions">
          <button
            type="button"
            className="operations-button operations-button--secondary"
            disabled={pending}
            onClick={onCancel}
          >
            Keep current status
          </button>

          <button
            type="submit"
            className="operations-button operations-button--primary"
            aria-busy={pending}
            disabled={confirmationDisabled}
          >
            {pending ? 'Updating…' : `Confirm ${statusLabels[targetStatus].toLowerCase()}`}
          </button>
        </div>
      </form>
    </div>
  );
}

export function TicketActions({
  ticket,
  currentOperatorId,
}: {
  readonly ticket: Ticket;
  readonly currentOperatorId: string;
}) {
  const updateTicket = useUpdateTicket();
  const [targetStatus, setTargetStatus] = useState<TicketStatus | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const closed = ticket.status === 'closed';
  const assignedToCurrentOperator = ticket.assigned_agent_id === currentOperatorId;

  async function submitUpdate(update: TicketUpdateInput, successMessage: string): Promise<boolean> {
    setNotice(null);
    updateTicket.reset();

    try {
      const result = await updateTicket.mutateAsync({
        ticketId: ticket.ticket_id,
        update,
      });

      setNotice(result.changed ? successMessage : 'The ticket already had the requested values.');

      return true;
    } catch {
      return false;
    }
  }

  async function assignToMe() {
    await submitUpdate(
      {
        expectedRowVersion: ticket.row_version,
        assignedAgentId: currentOperatorId,
      },
      'The ticket is now assigned to you.',
    );
  }

  async function unassign() {
    await submitUpdate(
      {
        expectedRowVersion: ticket.row_version,
        unassign: true,
      },
      'The ticket is now unassigned.',
    );
  }

  async function saveClassification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const formData = new FormData(event.currentTarget);

    const parsedPriority = ticketPrioritySchema.safeParse(formData.get('priority'));

    const parsedCategory = ticketCategorySchema.safeParse(formData.get('category'));

    if (!parsedPriority.success || !parsedCategory.success) {
      return;
    }

    const update: TicketUpdateInput = {
      expectedRowVersion: ticket.row_version,
      ...(parsedPriority.data !== ticket.priority ? { priority: parsedPriority.data } : {}),
      ...(parsedCategory.data !== ticket.category ? { category: parsedCategory.data } : {}),
    };

    if (parsedPriority.data === ticket.priority && parsedCategory.data === ticket.category) {
      setNotice('No classification changes were selected.');
      return;
    }

    await submitUpdate(update, 'Ticket classification updated.');
  }

  async function confirmTransition(resolutionSummary: string | null) {
    if (targetStatus === null) return;

    const succeeded = await submitUpdate(
      {
        expectedRowVersion: ticket.row_version,
        targetStatus,
        ...(resolutionSummary === null ? {} : { resolutionSummary }),
      },
      `Ticket moved to ${statusLabels[targetStatus].toLowerCase()}.`,
    );

    if (succeeded) {
      setTargetStatus(null);
    }
  }

  return (
    <section className="ticket-action-panel" aria-labelledby="ticket-actions-title">
      <div className="ticket-action-panel__heading">
        <div>
          <p className="operations-kicker">Workflow</p>
          <h3 id="ticket-actions-title">Manage ticket</h3>
        </div>

        <span>v{ticket.row_version}</span>
      </div>

      {notice ? (
        <div className="ticket-action-notice" role="status">
          <CheckCircle2 size={17} aria-hidden="true" />
          <span>{notice}</span>

          <button
            type="button"
            aria-label="Dismiss notification"
            onClick={() => {
              setNotice(null);
            }}
          >
            <X size={15} aria-hidden="true" />
          </button>
        </div>
      ) : null}

      {updateTicket.error && targetStatus === null ? (
        <div className="ticket-action-error" role="alert">
          <CircleAlert size={18} aria-hidden="true" />
          <span>{updateErrorMessage(updateTicket.error)}</span>
        </div>
      ) : null}

      <div className="ticket-assignment-actions">
        <div>
          <strong>Assignment</strong>
          <small>
            {ticket.assigned_agent_id === null
              ? 'No operator owns this ticket.'
              : assignedToCurrentOperator
                ? 'This ticket belongs to your queue.'
                : 'Another operator currently owns this ticket.'}
          </small>
        </div>

        <div>
          {!assignedToCurrentOperator ? (
            <button
              type="button"
              className="operations-button operations-button--primary"
              disabled={closed || updateTicket.isPending}
              onClick={() => {
                void assignToMe();
              }}
            >
              <UserRoundCheck size={17} aria-hidden="true" />
              {ticket.assigned_agent_id === null ? 'Assign to me' : 'Take ownership'}
            </button>
          ) : null}

          {ticket.assigned_agent_id !== null ? (
            <button
              type="button"
              className="operations-button operations-button--secondary"
              disabled={closed || updateTicket.isPending}
              onClick={() => {
                void unassign();
              }}
            >
              <UserMinus size={17} aria-hidden="true" />
              Unassign
            </button>
          ) : null}
        </div>
      </div>

      <form
        className="ticket-classification-form"
        key={`classification-${ticket.row_version}`}
        onSubmit={(event) => {
          void saveClassification(event);
        }}
      >
        <fieldset disabled={closed || updateTicket.isPending}>
          <legend>Classification</legend>

          <label>
            <span>Priority</span>

            <select name="priority" defaultValue={ticket.priority}>
              <option value="urgent">Urgent</option>
              <option value="high">High</option>
              <option value="normal">Normal</option>
              <option value="low">Low</option>
            </select>
          </label>

          <label>
            <span>Category</span>

            <select name="category" defaultValue={ticket.category}>
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

          <button type="submit" className="operations-button operations-button--secondary">
            Apply changes
          </button>
        </fieldset>
      </form>

      <div className="ticket-lifecycle-actions">
        <strong>Lifecycle</strong>

        <div>
          {availableStatusActions(ticket.status).map((action) => (
            <button
              type="button"
              className={`operations-button operations-button--${action.tone}`}
              disabled={updateTicket.isPending}
              key={action.status}
              onClick={() => {
                updateTicket.reset();
                setNotice(null);
                setTargetStatus(action.status);
              }}
            >
              {action.label}
            </button>
          ))}
        </div>
      </div>

      {closed ? (
        <p className="ticket-closed-notice">
          Closed tickets must be reopened before their assignment or classification can be changed.
        </p>
      ) : null}

      {targetStatus ? (
        <TicketTransitionDialog
          targetStatus={targetStatus}
          pending={updateTicket.isPending}
          error={updateTicket.error}
          onCancel={() => {
            setTargetStatus(null);
            updateTicket.reset();
          }}
          onConfirm={(resolutionSummary) => {
            void confirmTransition(resolutionSummary);
          }}
        />
      ) : null}
    </section>
  );
}
