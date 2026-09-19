// apps/web/src/features/operations/feedback-detail-drawer.tsx
import { useState } from 'react';
import { Link } from 'react-router';
import {
  CheckCircle2,
  CircleAlert,
  MessageSquareText,
  ShieldCheck,
  Star,
  ThumbsDown,
  ThumbsUp,
  X,
} from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import {
  type FeedbackReasonCode,
  type FeedbackReviewTargetStatus,
  type FeedbackStatus,
} from './feedback-contract';
import { useFeedbackDetail } from './feedback-queries';
import { FeedbackReviewDialog } from './feedback-review-dialog';

const statusLabels: Record<FeedbackStatus, string> = {
  pending: 'Pending review',
  reviewed: 'Reviewed',
  actioned: 'Actioned',
  dismissed: 'Dismissed',
};

const reasonLabels: Record<FeedbackReasonCode, string> = {
  INCORRECT_ANSWER: 'Incorrect answer',
  INCOMPLETE_ANSWER: 'Incomplete answer',
  IRRELEVANT_ANSWER: 'Irrelevant answer',
  OUTDATED_INFORMATION: 'Outdated information',
  UNCLEAR_ANSWER: 'Unclear answer',
  MISSING_CITATION: 'Missing citation',
  UNSAFE_RESPONSE: 'Unsafe response',
  SLOW_RESPONSE: 'Slow response',
  OTHER: 'Other',
};

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function shortIdentifier(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-4)}`;
}

function safeErrorMessage(error: unknown, fallback: string): string {
  return error instanceof SafeApiError ? error.message : fallback;
}

function RatingStars({ rating }: { readonly rating: number }) {
  return (
    <span className="feedback-rating" aria-label={`${rating} out of 5 stars`}>
      {Array.from({ length: 5 }, (_, index) => {
        const active = index < rating;

        return (
          <Star
            size={16}
            key={index}
            aria-hidden="true"
            fill={active ? 'currentColor' : 'none'}
            className={active ? 'is-active' : undefined}
          />
        );
      })}
    </span>
  );
}

export function FeedbackDetailDrawer({
  feedbackId,
  onClose,
}: {
  readonly feedbackId: string;
  readonly onClose: () => void;
}) {
  const detail = useFeedbackDetail(feedbackId);

  const [reviewTarget, setReviewTarget] = useState<FeedbackReviewTargetStatus | null>(null);

  const feedback = detail.data;

  return (
    <aside className="feedback-drawer" aria-label="Feedback details">
      <div className="feedback-drawer__header">
        <div>
          <p className="operations-kicker">Feedback detail</p>

          <h2>Customer response quality</h2>
        </div>

        <button
          type="button"
          className="feedback-drawer__close"
          aria-label="Close feedback details"
          title="Close details"
          onClick={onClose}
        >
          <X size={20} aria-hidden="true" />
        </button>
      </div>

      {detail.isPending ? (
        <div className="feedback-drawer__loading" aria-busy="true">
          <div className="operations-skeleton" />
          <div className="operations-skeleton" />
          <div className="operations-skeleton" />
        </div>
      ) : null}

      {detail.isError ? (
        <div className="feedback-drawer__error" role="alert">
          <CircleAlert size={22} aria-hidden="true" />

          <div>
            <strong>Feedback unavailable</strong>

            <p>{safeErrorMessage(detail.error, 'The feedback details could not be loaded.')}</p>

            <button
              type="button"
              className="operations-button operations-button--secondary"
              onClick={() => {
                void detail.refetch();
              }}
            >
              Try again
            </button>
          </div>
        </div>
      ) : null}

      {feedback ? (
        <>
          <div className="feedback-drawer__summary">
            <RatingStars rating={feedback.rating} />

            <span className={`feedback-status feedback-status--${feedback.status}`}>
              {statusLabels[feedback.status]}
            </span>
          </div>

          <section className="feedback-drawer__section">
            <p className="operations-kicker">Customer feedback</p>

            <blockquote>{feedback.comment ?? 'No written comment was submitted.'}</blockquote>

            <div className="feedback-helpful-state">
              {feedback.helpful === true ? (
                <>
                  <ThumbsUp size={17} aria-hidden="true" />
                  Marked helpful
                </>
              ) : feedback.helpful === false ? (
                <>
                  <ThumbsDown size={17} aria-hidden="true" />
                  Marked not helpful
                </>
              ) : (
                'No helpfulness selection'
              )}
            </div>
          </section>

          <section className="feedback-drawer__section">
            <p className="operations-kicker">Reported reasons</p>

            {feedback.reason_codes.length > 0 ? (
              <div className="feedback-reason-list">
                {feedback.reason_codes.map((reason) => (
                  <span key={reason}>{reasonLabels[reason]}</span>
                ))}
              </div>
            ) : (
              <p>No structured reason was selected.</p>
            )}
          </section>

          {feedback.review_notes ? (
            <section className="feedback-drawer__section feedback-review-note">
              <p className="operations-kicker">Review notes</p>

              <p>{feedback.review_notes}</p>

              {feedback.reviewed_at ? (
                <small>Reviewed {formatTimestamp(feedback.reviewed_at)}</small>
              ) : null}
            </section>
          ) : null}

          <section className="feedback-drawer__section">
            <p className="operations-kicker">Related evidence</p>

            <dl className="feedback-identifiers">
              <div>
                <dt>Feedback</dt>
                <dd title={feedback.feedback_id}>{shortIdentifier(feedback.feedback_id)}</dd>
              </div>

              <div>
                <dt>Conversation</dt>
                <dd title={feedback.conversation_id}>
                  {shortIdentifier(feedback.conversation_id)}
                </dd>
              </div>

              <div>
                <dt>Assistant response</dt>
                <dd title={feedback.response_message_id}>
                  {shortIdentifier(feedback.response_message_id)}
                </dd>
              </div>

              <div>
                <dt>AI run</dt>
                <dd title={feedback.ai_run_id ?? undefined}>
                  {feedback.ai_run_id ? shortIdentifier(feedback.ai_run_id) : 'Unavailable'}
                </dd>
              </div>
            </dl>

            <Link
              className="operations-button operations-button--secondary feedback-conversation-link"
              to={`/operations/conversations?conversation=${feedback.conversation_id}`}
            >
              <MessageSquareText size={17} aria-hidden="true" />
              Open conversation
            </Link>
          </section>

          <section className="feedback-drawer__section">
            <p className="operations-kicker">Timeline</p>

            <dl className="feedback-timeline">
              <div>
                <dt>Submitted</dt>
                <dd>{formatTimestamp(feedback.created_at)}</dd>
              </div>

              <div>
                <dt>Last updated</dt>
                <dd>{formatTimestamp(feedback.updated_at)}</dd>
              </div>

              <div>
                <dt>Row version</dt>
                <dd>{feedback.row_version}</dd>
              </div>
            </dl>
          </section>

          {feedback.status === 'pending' || feedback.status === 'reviewed' ? (
            <section className="feedback-drawer__actions">
              <p className="operations-kicker">Review action</p>

              <div>
                {feedback.status === 'pending' ? (
                  <button
                    type="button"
                    className="operations-button operations-button--primary"
                    onClick={() => {
                      setReviewTarget('reviewed');
                    }}
                  >
                    <CheckCircle2 size={17} aria-hidden="true" />
                    Mark reviewed
                  </button>
                ) : null}

                <button
                  type="button"
                  className="operations-button operations-button--secondary"
                  onClick={() => {
                    setReviewTarget('actioned');
                  }}
                >
                  Mark actioned
                </button>

                <button
                  type="button"
                  className="operations-button operations-button--danger"
                  onClick={() => {
                    setReviewTarget('dismissed');
                  }}
                >
                  Dismiss
                </button>
              </div>
            </section>
          ) : (
            <div className="feedback-terminal-state">
              <ShieldCheck size={19} aria-hidden="true" />

              <span>This feedback review is complete and cannot transition again.</span>
            </div>
          )}

          {reviewTarget ? (
            <FeedbackReviewDialog
              feedback={feedback}
              targetStatus={reviewTarget}
              onClose={() => {
                setReviewTarget(null);
              }}
              onRefresh={async () => {
                await detail.refetch();
              }}
            />
          ) : null}
        </>
      ) : null}
    </aside>
  );
}
