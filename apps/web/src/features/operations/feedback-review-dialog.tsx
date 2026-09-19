// apps/web/src/features/operations/feedback-review-dialog.tsx
import { type FormEvent, useEffect, useRef, useState } from 'react';
import { RefreshCw, ShieldCheck, X } from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import type { Feedback, FeedbackReviewTargetStatus, FeedbackStatus } from './feedback-contract';
import { useReviewFeedback } from './feedback-queries';

const statusLabels: Record<FeedbackStatus, string> = {
  pending: 'Pending review',
  reviewed: 'Reviewed',
  actioned: 'Actioned',
  dismissed: 'Dismissed',
};

const reviewLabels: Record<FeedbackReviewTargetStatus, string> = {
  reviewed: 'Mark reviewed',
  actioned: 'Mark actioned',
  dismissed: 'Dismiss feedback',
};

function safeErrorMessage(error: unknown, fallback: string): string {
  return error instanceof SafeApiError ? error.message : fallback;
}

export function FeedbackReviewDialog({
  feedback,
  targetStatus,
  onClose,
  onRefresh,
}: {
  readonly feedback: Feedback;
  readonly targetStatus: FeedbackReviewTargetStatus;
  readonly onClose: () => void;
  readonly onRefresh: () => Promise<void>;
}) {
  const review = useReviewFeedback();
  const submittingRef = useRef(false);
  const [notes, setNotes] = useState('');

  const normalizedNotes = notes.trim();

  const notesRequired = targetStatus === 'actioned' || targetStatus === 'dismissed';

  const invalid = notesRequired && normalizedNotes.length === 0;

  const stale = review.error instanceof SafeApiError && review.error.status === 409;

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !review.isPending) {
        onClose();
      }
    }

    window.addEventListener('keydown', handleKeyDown);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [onClose, review.isPending]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (invalid || review.isPending || submittingRef.current) {
      return;
    }

    submittingRef.current = true;

    try {
      await review.mutateAsync({
        feedbackId: feedback.feedback_id,
        expectedRowVersion: feedback.row_version,
        targetStatus,
        reviewNotes: normalizedNotes.length > 0 ? normalizedNotes : null,
      });

      onClose();
    } catch {
      // A safe mutation error is rendered below.
    } finally {
      submittingRef.current = false;
    }
  }

  async function refreshStaleFeedback() {
    if (review.isPending) {
      return;
    }

    review.reset();
    await onRefresh();
    onClose();
  }

  const danger = targetStatus === 'dismissed';

  return (
    <div className="operations-dialog-backdrop" role="presentation">
      <form
        className="feedback-review-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="feedback-review-title"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <span className={`feedback-review-dialog__icon${danger ? ' is-danger' : ''}`}>
          {danger ? (
            <X size={25} aria-hidden="true" />
          ) : (
            <ShieldCheck size={25} aria-hidden="true" />
          )}
        </span>

        <p className="operations-kicker">Confirm feedback review</p>

        <h2 id="feedback-review-title">{reviewLabels[targetStatus]}?</h2>

        <p>
          This will move the feedback from <strong>{statusLabels[feedback.status]}</strong> to{' '}
          <strong>{statusLabels[targetStatus]}</strong>.
        </p>

        <label className="feedback-review-dialog__field">
          <span>
            Review notes
            {notesRequired ? ' *' : ' (optional)'}
          </span>

          <textarea
            rows={5}
            maxLength={5_000}
            value={notes}
            disabled={review.isPending || stale}
            placeholder={
              notesRequired
                ? 'Explain the action taken or why this feedback is being dismissed.'
                : 'Add useful context for other operators.'
            }
            onChange={(event) => {
              setNotes(event.target.value);
            }}
          />
        </label>

        <div className="feedback-review-dialog__count">
          <span>
            {invalid
              ? 'Review notes are required for this transition.'
              : 'Internal note visible to support staff.'}
          </span>

          <span>{notes.length}/5,000</span>
        </div>

        {review.isError ? (
          <div className={`feedback-review-error${stale ? ' is-stale' : ''}`} role="alert">
            <CircleErrorIcon stale={stale} />

            <div>
              <strong>{stale ? 'Feedback changed elsewhere' : 'Review could not be saved'}</strong>

              <p>
                {stale
                  ? 'Another operator updated this feedback. Refresh its current state before making another decision.'
                  : safeErrorMessage(review.error, 'The feedback status could not be updated.')}
              </p>
            </div>
          </div>
        ) : null}

        <div className="feedback-review-dialog__actions">
          <button
            type="button"
            className="operations-button operations-button--secondary"
            disabled={review.isPending}
            onClick={onClose}
          >
            Keep current status
          </button>

          {stale ? (
            <button
              type="button"
              className="operations-button operations-button--primary"
              onClick={() => {
                void refreshStaleFeedback();
              }}
            >
              <RefreshCw size={17} aria-hidden="true" />
              Refresh feedback
            </button>
          ) : (
            <button
              type="submit"
              className={
                danger
                  ? 'operations-button operations-button--danger-solid'
                  : 'operations-button operations-button--primary'
              }
              disabled={invalid || review.isPending}
            >
              {review.isPending ? 'Updating…' : reviewLabels[targetStatus]}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

function CircleErrorIcon({ stale }: { readonly stale: boolean }) {
  return stale ? <RefreshCw size={20} aria-hidden="true" /> : <X size={20} aria-hidden="true" />;
}
