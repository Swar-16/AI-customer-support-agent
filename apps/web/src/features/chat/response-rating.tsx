// apps/web/src/features/chat/response-rating.tsx
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { skipToken, useQuery, useQueryClient } from '@tanstack/react-query';
import { Controller, useForm } from 'react-hook-form';

import { useApiTransport } from '../../shared/api/transport-context';
import { useSession, useSessionController } from '../../shared/auth/session-context';
import { createResponseFeedbackApi, feedbackRatingSchema } from './response-feedback-api';
import { createResponseFeedbackReadback } from './response-feedback-readback';
import { RatingStars } from './rating-stars';
import type { components } from '../../shared/api/generated/schema';
import { chatKeys } from './chat-queries';
import { SavedResponseRating } from './saved-response-rating';
import './response-rating.css';

interface ResponseRatingProps {
  readonly conversationId: string;
  readonly responseMessageId: string;
  readonly message?: components['schemas']['ConversationMessageResponse'];
}

interface RatingTarget {
  readonly conversationId: string;
  readonly responseMessageId: string;
  readonly aiRunId: string;
}

interface RatingFormValues {
  readonly rating: number | null;
}

type RatingSubmission =
  | { readonly phase: 'pending' }
  | {
      readonly phase: 'confirmed';
      readonly rating: number;
      readonly created: boolean;
    }
  | { readonly phase: 'conflict' }
  | { readonly phase: 'unconfirmed' }
  | { readonly phase: 'rejected' };

export function ResponseRating({
  conversationId,
  responseMessageId,
  message,
}: ResponseRatingProps) {
  const session = useSession();

  if (
    session.phase !== 'authenticated' ||
    session.user?.role !== 'customer' ||
    session.user.status !== 'active'
  ) {
    return null;
  }

  /*
   * Persisted conversation history is the only authority for feedback
   * eligibility. Never fall back to an ID remembered after message
   * submission.
   */
  if (message === undefined) {
    return null;
  }

  if (
    message.role !== 'assistant' ||
    message.conversation_id !== conversationId ||
    message.message_id !== responseMessageId ||
    message.feedback_eligible !== true
  ) {
    return null;
  }

  /*
   * Existing customer-safe feedback returned by conversation history remains
   * visible without making another feedback request.
   */
  if (message.feedback != null) {
    return <SavedResponseRating rating={message.feedback.rating} />;
  }

  /*
   * Eligible feedback requires the backend-provided completed AI-run
   * association. Optional generated properties must be narrowed explicitly.
   */
  if (typeof message.ai_run_id !== 'string') {
    return null;
  }

  const target: RatingTarget = {
    conversationId,
    responseMessageId,
    aiRunId: message.ai_run_id,
  };

  return (
    <RatingForm
      key={`${target.conversationId}:` + `${target.responseMessageId}:` + target.aiRunId}
      target={target}
    />
  );
}
function RatingForm({ target }: { readonly target: RatingTarget }) {
  const id = useId();
  const session = useSession();
  const controller = useSessionController();
  const transport = useApiTransport();
  const queryClient = useQueryClient();
  const api = useMemo(() => createResponseFeedbackApi(transport), [transport]);
  const readbackApi = useMemo(() => createResponseFeedbackReadback(transport), [transport]);

  const readAbortRef = useRef<AbortController | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkNotice, setCheckNotice] = useState('');

  useEffect(() => {
    return () => {
      readAbortRef.current?.abort();
      readAbortRef.current = null;
    };
  }, [session]);

  const customerId =
    session.phase === 'authenticated' &&
    session.user?.role === 'customer' &&
    session.user.status === 'active'
      ? session.user.id
      : null;

  const submissionKey = [
    'chat',
    customerId,
    'conversation',
    target.conversationId,
    'rating-submission',
    target.responseMessageId,
  ] as const;

  const submission = useQuery<RatingSubmission>({
    queryKey: submissionKey,
    queryFn: skipToken,
    staleTime: Infinity,

    // Preserve pending/uncertain outcomes across conversation pagination.
    // The existing session cleanup clears these records on identity changes.
    gcTime: Infinity,
  });

  const { control, handleSubmit } = useForm<RatingFormValues>({
    defaultValues: { rating: null },
  });

  function sessionIsCurrent() {
    return customerId !== null && controller.getSnapshot() === session;
  }

  function refreshSavedFeedback() {
    if (customerId === null || !sessionIsCurrent()) return;

    void queryClient.invalidateQueries({
      queryKey: [...chatKeys.conversation(customerId, target.conversationId), 'messages'],
    });
  }

  async function submit(values: RatingFormValues): Promise<void> {
    const rating = feedbackRatingSchema.safeParse(values.rating);

    if (
      !rating.success ||
      !sessionIsCurrent() ||
      queryClient.getQueryData<RatingSubmission>(submissionKey) !== undefined
    ) {
      return;
    }

    // Synchronous cache write: a second submit handler sees this immediately,
    // even before React renders the disabled controls.
    queryClient.setQueryData<RatingSubmission>(submissionKey, {
      phase: 'pending',
    });

    try {
      const result = await api.submitRating(target.conversationId, {
        response_message_id: target.responseMessageId,
        ai_run_id: target.aiRunId,
        rating: rating.data,
      });

      // Never repopulate a cleared cache using an old session's response.
      if (!sessionIsCurrent()) return;

      let outcome: RatingSubmission;

      if (result.ok) {
        outcome =
          result.data.customer_id === customerId
            ? {
                phase: 'confirmed',
                rating: result.data.rating,
                created: result.data.created,
              }
            : { phase: 'unconfirmed' };
      } else if (result.error.status === 409) {
        outcome = { phase: 'conflict' };
      } else if (
        result.error.kind === 'http' &&
        result.error.status !== null &&
        result.error.status >= 400 &&
        result.error.status < 500 &&
        result.error.status !== 408
      ) {
        outcome = { phase: 'rejected' };
      } else {
        outcome = { phase: 'unconfirmed' };
      }

      queryClient.setQueryData<RatingSubmission>(submissionKey, outcome);
      if (
        outcome.phase === 'confirmed' ||
        outcome.phase === 'conflict' ||
        outcome.phase === 'unconfirmed'
      ) {
        refreshSavedFeedback();
      }
    } catch {
      if (!sessionIsCurrent()) return;

      queryClient.setQueryData<RatingSubmission>(submissionKey, {
        phase: 'unconfirmed',
      });
      refreshSavedFeedback();
    }
  }

  async function checkSavedRating(): Promise<void> {
    if (customerId === null || !sessionIsCurrent() || readAbortRef.current !== null) {
      return;
    }

    const current = queryClient.getQueryData<RatingSubmission>(submissionKey);

    if (current?.phase !== 'conflict' && current?.phase !== 'unconfirmed') {
      return;
    }

    const abortController = new AbortController();
    readAbortRef.current = abortController;
    setChecking(true);
    setCheckNotice('');

    function mayApplyResult() {
      return (
        !abortController.signal.aborted &&
        readAbortRef.current === abortController &&
        sessionIsCurrent()
      );
    }

    try {
      const result = await readbackApi.findRating(
        customerId,
        target.conversationId,
        target.responseMessageId,
        abortController.signal,
      );

      if (!mayApplyResult()) return;

      if (result.kind === 'found') {
        // Show what the server actually stores, even if it differs
        // from the rating selected in this form.
        const confirmed: RatingSubmission = {
          phase: 'confirmed',
          rating: result.rating,
          created: false,
        };
        refreshSavedFeedback();

        queryClient.setQueryData<RatingSubmission>(submissionKey, () => confirmed);

        setCheckNotice('');
      } else if (result.kind === 'incomplete') {
        setCheckNotice(
          'The check reached its page limit without finding this rating. Submission remains paused. You can check again.',
        );
      } else {
        setCheckNotice(
          'No saved rating was found in the records checked. The earlier request may still complete, so submission remains paused. You can check again.',
        );
      }
    } catch {
      if (!mayApplyResult()) return;

      setCheckNotice(
        'The saved rating could not be checked. Submission remains paused. You can check again.',
      );
    } finally {
      if (readAbortRef.current === abortController) {
        readAbortRef.current = null;

        if (sessionIsCurrent() && !abortController.signal.aborted) {
          setChecking(false);
        }
      }
    }
  }

  const outcome = submission.data;
  const locked = customerId === null || outcome !== undefined;
  const canCheck =
    customerId !== null && (outcome?.phase === 'conflict' || outcome?.phase === 'unconfirmed');

  let status = '';
  let error = '';

  if (outcome?.phase === 'pending') {
    status = 'Submitting your rating…';
  } else if (outcome?.phase === 'confirmed') {
    status = outcome.created
      ? `Thank you. Your rating of ${outcome.rating} out of 5 was saved.`
      : `Your rating of ${outcome.rating} out of 5 was already saved.`;
  } else if (outcome?.phase === 'conflict') {
    error =
      'Your rating could not be saved because it conflicts with the current feedback. No replacement was submitted.';
  } else if (outcome?.phase === 'unconfirmed') {
    error =
      'We could not confirm whether your rating was saved. Submission is paused to avoid sending it again.';
  } else if (outcome?.phase === 'rejected') {
    error = 'The server did not accept this rating. No further submission was attempted.';
  }

  return (
    <form
      className="chat-rating"
      aria-label="Rate this response"
      aria-busy={outcome?.phase === 'pending' || checking}
      noValidate
      onSubmit={(event) => {
        void handleSubmit(submit)(event);
      }}
    >
      <fieldset disabled={locked}>
        <legend>How useful was this response?</legend>

        <p id={`${id}-help`} className="chat-rating__help">
          Choose one rating. Submitted feedback cannot be edited here.
        </p>

        <Controller
          name="rating"
          control={control}
          rules={{
            validate: (value) =>
              feedbackRatingSchema.safeParse(value).success || 'Choose a rating from 1 to 5.',
          }}
          render={({ field, fieldState }) => (
            <>
              <RatingStars
                name={`${id}-rating`}
                value={outcome?.phase === 'confirmed' ? outcome.rating : field.value}
                disabled={locked}
                invalid={fieldState.invalid}
                describedBy={fieldState.error ? `${id}-help ${id}-error` : `${id}-help`}
                inputRef={field.ref}
                onChange={field.onChange}
                onBlur={field.onBlur}
              />

              {fieldState.error && (
                <p id={`${id}-error`} role="alert">
                  {fieldState.error.message}
                </p>
              )}

              <button
                className="chat-rating__submit"
                type="submit"
                disabled={locked || !feedbackRatingSchema.safeParse(field.value).success}
              >
                Submit rating
              </button>
            </>
          )}
        />
      </fieldset>

      <p role="status" aria-atomic="true">
        {status}
      </p>
      {error && <p role="alert">{error}</p>}

      {canCheck && (
        <div className="chat-rating__recovery">
          <button
            type="button"
            disabled={checking}
            onClick={() => {
              void checkSavedRating();
            }}
          >
            Check saved rating
          </button>

          <p role="status" aria-atomic="true">
            {checking ? 'Checking saved feedback…' : checkNotice}
          </p>
        </div>
      )}
    </form>
  );
}
