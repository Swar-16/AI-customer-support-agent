// apps/web/src/features/operations/feedback-queue.tsx
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import {
  ArrowLeft,
  ArrowRight,
  CircleAlert,
  Clock3,
  Eye,
  RefreshCw,
  Star,
  ThumbsDown,
  ThumbsUp,
  X,
} from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import type { FeedbackFilters } from './feedback-api';
import {
  feedbackIdSchema,
  feedbackReasonCodeSchema,
  type Feedback,
  type FeedbackReasonCode,
  type FeedbackStatus,
} from './feedback-contract';
import { FeedbackDetailDrawer } from './feedback-detail-drawer';
import { useFeedbackList } from './feedback-queries';
import { DashboardJellySwitch } from './dashboard-jelly-switch';

import './feedback-queue.css';

const PAGE_LIMIT = 20;

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

function dateBoundary(value: string, endOfDay: boolean): string | null {
  if (value.length === 0) {
    return null;
  }

  const time = endOfDay ? '23:59:59.999' : '00:00:00.000';

  return new Date(`${value}T${time}`).toISOString();
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

function FeedbackCard({
  feedback,
  selected,
  onSelect,
}: {
  readonly feedback: Feedback;
  readonly selected: boolean;
  readonly onSelect: () => void;
}) {
  const comment =
    feedback.comment ?? 'The customer submitted a rating without an additional comment.';

  return (
    <button
      type="button"
      className={`feedback-card${feedback.rating <= 2 ? ' is-low-rating' : ''}${selected ? ' is-selected' : ''}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="feedback-card__topline">
        <RatingStars rating={feedback.rating} />

        <span className={`feedback-status feedback-status--${feedback.status}`}>
          {statusLabels[feedback.status]}
        </span>
      </span>

      <strong>{comment}</strong>

      <span className="feedback-card__signals">
        {feedback.helpful === true ? (
          <span className="is-helpful">
            <ThumbsUp size={14} aria-hidden="true" />
            Helpful
          </span>
        ) : feedback.helpful === false ? (
          <span className="is-unhelpful">
            <ThumbsDown size={14} aria-hidden="true" />
            Not helpful
          </span>
        ) : (
          <span>No helpfulness selection</span>
        )}

        {feedback.reason_codes.length > 0 ? (
          <span>
            {feedback.reason_codes.length}{' '}
            {feedback.reason_codes.length === 1 ? 'reason' : 'reasons'}
          </span>
        ) : null}
      </span>

      <span className="feedback-card__footer">
        <span>
          <Clock3 size={14} aria-hidden="true" />
          {formatTimestamp(feedback.created_at)}
        </span>

        <span title={feedback.conversation_id}>
          Conversation {shortIdentifier(feedback.conversation_id)}
        </span>
      </span>
    </button>
  );
}

function FeedbackListSkeleton() {
  return (
    <div
      className="feedback-list feedback-list--loading"
      aria-label="Loading feedback"
      aria-busy="true"
    >
      {Array.from({ length: 5 }, (_, index) => (
        <div className="operations-skeleton feedback-card-skeleton" key={index} />
      ))}
    </div>
  );
}

type FeedbackQueueTab = 'pending' | 'reviewed';

type ReviewedFeedbackStatus = Exclude<FeedbackStatus, 'pending'>;

export function FeedbackQueue() {
  const [searchParams, setSearchParams] = useSearchParams();

  const requestedFeedbackId = searchParams.get('feedback');

  const parsedFeedbackId = feedbackIdSchema.safeParse(requestedFeedbackId);

  const selectedId = parsedFeedbackId.success ? parsedFeedbackId.data : null;

  const invalidFeedbackLink = requestedFeedbackId !== null && !parsedFeedbackId.success;

  const [tab, setTab] = useState<FeedbackQueueTab>('pending');
  const [reviewedStatus, setReviewedStatus] = useState<ReviewedFeedbackStatus>('reviewed');
  const [rating, setRating] = useState<number | null>(null);
  const [helpful, setHelpful] = useState<boolean | null>(null);
  const [reasonCode, setReasonCode] = useState<FeedbackReasonCode | null>(null);
  const [createdFrom, setCreatedFrom] = useState('');
  const [createdTo, setCreatedTo] = useState('');
  const [offset, setOffset] = useState(0);

  function setFeedbackInUrl(feedbackId: string | null, replace = true) {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);

        if (feedbackId === null) {
          next.delete('feedback');
        } else {
          next.set('feedback', feedbackId);
        }

        return next;
      },
      { replace },
    );
  }

  function resetPageAndSelection() {
    setOffset(0);
    setFeedbackInUrl(null);
  }

  const filters = useMemo<FeedbackFilters>(
    () => ({
      status: tab === 'pending' ? 'pending' : reviewedStatus,
      rating,
      helpful,
      reasonCode,
      customerId: null,
      conversationId: null,
      createdFrom: dateBoundary(createdFrom, false),
      createdTo: dateBoundary(createdTo, true),
      limit: PAGE_LIMIT,
      offset,
    }),
    [createdFrom, createdTo, helpful, offset, rating, reasonCode, reviewedStatus, tab],
  );

  const queue = useFeedbackList(filters);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (
        event.key === 'Escape' &&
        document.querySelector('[role="dialog"][aria-modal="true"]') === null
      ) {
        setFeedbackInUrl(null);
      }
    }

    window.addEventListener('keydown', handleKeyDown);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  });

  const visibleSummary = useMemo(() => {
    const items = queue.data?.items ?? [];

    const average =
      items.length === 0
        ? null
        : items.reduce((total, item) => total + item.rating, 0) / items.length;

    return {
      count: items.length,
      average,
      pending: items.filter((item) => item.status === 'pending').length,
      lowRatings: items.filter((item) => item.rating <= 2).length,
    };
  }, [queue.data?.items]);

  const startNumber = queue.data ? queue.data.offset + 1 : 0;

  const endNumber = queue.data ? queue.data.offset + queue.data.count : 0;

  return (
    <div className="feedback-workspace">
      <section className="feedback-queue-panel">
        <div className="feedback-queue-toolbar">
          <div>
            <p className="operations-kicker">Quality review queue</p>

            <h2>Customer feedback</h2>

            <p>Review low-confidence experiences and record the action taken.</p>
          </div>

          <button
            type="button"
            className="operations-icon-button feedback-refresh"
            aria-label="Refresh feedback"
            title="Refresh feedback"
            disabled={queue.isFetching}
            onClick={() => {
              void queue.refetch();
            }}
          >
            <RefreshCw
              size={19}
              aria-hidden="true"
              className={queue.isFetching ? 'is-spinning' : undefined}
            />
          </button>
        </div>

        <DashboardJellySwitch
          label="Feedback queue view"
          value={tab}
          tone="accent"
          options={[
            {
              value: 'pending',
              label: 'Pending',
            },
            {
              value: 'reviewed',
              label: 'Reviewed',
            },
          ]}
          onChange={(nextTab) => {
            setTab(nextTab);
            resetPageAndSelection();
          }}
        />
        <div className="feedback-stat-grid" aria-label="Visible feedback summary">
          <article>
            <span>Visible</span>
            <strong>{visibleSummary.count}</strong>
            <small>Current page</small>
          </article>

          <article>
            <span>Average rating</span>
            <strong>
              {visibleSummary.average === null ? '—' : visibleSummary.average.toFixed(1)}
            </strong>
            <small>Current page</small>
          </article>

          <article>
            <span>Pending</span>
            <strong>{visibleSummary.pending}</strong>
            <small>Needs review</small>
          </article>

          <article>
            <span>Low ratings</span>
            <strong>{visibleSummary.lowRatings}</strong>
            <small>1–2 stars</small>
          </article>
        </div>

        <div className="feedback-filter-bar">
          {tab === 'reviewed' ? (
            <label>
              <span>Review outcome</span>

              <select
                value={reviewedStatus}
                onChange={(event) => {
                  const value = event.target.value;

                  if (value === 'reviewed' || value === 'actioned' || value === 'dismissed') {
                    setReviewedStatus(value);
                    resetPageAndSelection();
                  }
                }}
              >
                <option value="reviewed">Reviewed</option>
                <option value="actioned">Actioned</option>
                <option value="dismissed">Dismissed</option>
              </select>
            </label>
          ) : null}

          <label>
            <span>Rating</span>

            <select
              value={rating ?? ''}
              onChange={(event) => {
                const next = event.target.value === '' ? null : Number(event.target.value);

                setRating(next);
                resetPageAndSelection();
              }}
            >
              <option value="">All ratings</option>
              <option value="1">1 star</option>
              <option value="2">2 stars</option>
              <option value="3">3 stars</option>
              <option value="4">4 stars</option>
              <option value="5">5 stars</option>
            </select>
          </label>

          <label>
            <span>Helpfulness</span>

            <select
              value={helpful === null ? '' : String(helpful)}
              onChange={(event) => {
                setHelpful(event.target.value === '' ? null : event.target.value === 'true');
                resetPageAndSelection();
              }}
            >
              <option value="">All responses</option>
              <option value="true">Helpful</option>
              <option value="false">Not helpful</option>
            </select>
          </label>

          <label>
            <span>Reason</span>

            <select
              value={reasonCode ?? ''}
              onChange={(event) => {
                const parsed = feedbackReasonCodeSchema.safeParse(event.target.value);

                setReasonCode(parsed.success ? parsed.data : null);
                resetPageAndSelection();
              }}
            >
              <option value="">All reasons</option>

              {Object.entries(reasonLabels).map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>From</span>

            <input
              type="date"
              value={createdFrom}
              max={createdTo || undefined}
              onChange={(event) => {
                setCreatedFrom(event.target.value);
                resetPageAndSelection();
              }}
            />
          </label>

          <label>
            <span>To</span>

            <input
              type="date"
              value={createdTo}
              min={createdFrom || undefined}
              onChange={(event) => {
                setCreatedTo(event.target.value);
                resetPageAndSelection();
              }}
            />
          </label>
        </div>

        {invalidFeedbackLink ? (
          <div className="feedback-link-warning" role="alert">
            <CircleAlert size={19} aria-hidden="true" />

            <div>
              <strong>Invalid feedback link</strong>
              <p>
                The requested feedback identifier is invalid. You can continue browsing the review
                queue.
              </p>
            </div>

            <button
              type="button"
              aria-label="Dismiss invalid feedback link"
              onClick={() => {
                setFeedbackInUrl(null);
              }}
            >
              <X size={17} aria-hidden="true" />
            </button>
          </div>
        ) : null}

        {queue.isPending && queue.data === undefined ? <FeedbackListSkeleton /> : null}

        {queue.isError && queue.data === undefined ? (
          <div className="feedback-empty-state" role="alert">
            <span>
              <CircleAlert size={27} aria-hidden="true" />
            </span>

            <h2>Feedback unavailable</h2>

            <p>{safeErrorMessage(queue.error, 'The feedback queue could not be loaded.')}</p>

            <button
              type="button"
              className="operations-button operations-button--primary"
              onClick={() => {
                void queue.refetch();
              }}
            >
              Try again
            </button>
          </div>
        ) : null}

        {queue.data?.items.length === 0 ? (
          <div className="feedback-empty-state">
            <span>
              <Star size={27} aria-hidden="true" />
            </span>

            <h2>No feedback matched</h2>

            <p>Adjust the status, rating, helpfulness, reason, or date filters.</p>
          </div>
        ) : null}

        {queue.data && queue.data.items.length > 0 ? (
          <>
            <div className="feedback-list-summary">
              <span>
                Showing {startNumber}–{endNumber}
              </span>

              {queue.isFetching ? <span role="status">Refreshing…</span> : null}
            </div>

            <div className="feedback-list">
              {queue.data.items.map((feedback) => (
                <FeedbackCard
                  feedback={feedback}
                  selected={selectedId === feedback.feedback_id}
                  key={feedback.feedback_id}
                  onSelect={() => {
                    if (selectedId !== feedback.feedback_id) {
                      setFeedbackInUrl(feedback.feedback_id, false);
                    }
                  }}
                />
              ))}
            </div>

            <nav className="feedback-pagination" aria-label="Feedback pages">
              <div>
                {queue.data.offset > 0 ? (
                  <button
                    type="button"
                    className="operations-button operations-button--secondary"
                    onClick={() => {
                      setOffset(Math.max(0, queue.data.offset - queue.data.limit));
                      setFeedbackInUrl(null);
                    }}
                  >
                    <ArrowLeft size={17} aria-hidden="true" />
                    Previous
                  </button>
                ) : null}
              </div>

              <span>Page {Math.floor(queue.data.offset / queue.data.limit) + 1}</span>

              <div>
                {queue.data.has_more ? (
                  <button
                    type="button"
                    className="operations-button operations-button--secondary"
                    onClick={() => {
                      setOffset(queue.data.offset + queue.data.limit);
                      setFeedbackInUrl(null);
                    }}
                  >
                    Next
                    <ArrowRight size={17} aria-hidden="true" />
                  </button>
                ) : null}
              </div>
            </nav>
          </>
        ) : null}
      </section>

      {selectedId ? (
        <FeedbackDetailDrawer
          key={selectedId}
          feedbackId={selectedId}
          onClose={() => {
            setFeedbackInUrl(null);
          }}
        />
      ) : (
        <aside className="feedback-detail-placeholder" aria-label="Feedback selection">
          <span>
            <Eye size={25} aria-hidden="true" />
          </span>

          <h2>Inspect feedback</h2>

          <p>
            Select a feedback card to inspect its rating, customer context, related records, and
            review lifecycle.
          </p>
        </aside>
      )}
    </div>
  );
}
