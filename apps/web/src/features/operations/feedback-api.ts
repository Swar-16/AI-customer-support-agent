// apps/web/src/features/operations/feedback-api.ts
import { z } from 'zod';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult, createTransport } from '../../shared/api/transport';
import {
  decodeFeedback,
  decodeFeedbackPage,
  decodeFeedbackReviewResponse,
  feedbackIdSchema,
  feedbackReasonCodeSchema,
  feedbackReviewRequestSchema,
  feedbackStatusSchema,
  type Feedback,
  type FeedbackPage,
  type FeedbackReasonCode,
  type FeedbackReviewRequest,
  type FeedbackReviewResponse,
  type FeedbackStatus,
} from './feedback-contract';

type Transport = ReturnType<typeof createTransport>;

export interface FeedbackFilters {
  readonly status: FeedbackStatus | null;
  readonly rating: number | null;
  readonly helpful: boolean | null;
  readonly reasonCode: FeedbackReasonCode | null;
  readonly customerId: string | null;
  readonly conversationId: string | null;
  readonly createdFrom: string | null;
  readonly createdTo: string | null;
  readonly limit: number;
  readonly offset: number;
}

const nullableUuidSchema = z.uuid().nullable();
const nullableTimestampSchema = z.iso.datetime({ offset: true }).nullable();

const feedbackFiltersSchema = z
  .object({
    status: feedbackStatusSchema.nullable(),
    rating: z.number().int().min(1).max(5).nullable(),
    helpful: z.boolean().nullable(),
    reasonCode: feedbackReasonCodeSchema.nullable(),
    customerId: nullableUuidSchema,
    conversationId: nullableUuidSchema,
    createdFrom: nullableTimestampSchema,
    createdTo: nullableTimestampSchema,
    limit: z.number().int().min(1).max(200),
    offset: z.number().int().nonnegative(),
  })
  .strict()
  .superRefine((filters, context) => {
    if (
      filters.createdFrom !== null &&
      filters.createdTo !== null &&
      Date.parse(filters.createdFrom) > Date.parse(filters.createdTo)
    ) {
      context.addIssue({
        code: 'custom',
        path: ['createdTo'],
        message: 'The end date must not be earlier than the start date.',
      });
    }
  });

function requestSignal(signal: AbortSignal | undefined) {
  return signal === undefined ? {} : { signal };
}

function invalidRequest<T>(): Promise<TransportResult<T>> {
  return Promise.resolve({
    ok: false,
    error: SafeApiError.fromLocal('invalid-response'),
    retryAfterMs: null,
  });
}

export function createFeedbackApi(request: Transport) {
  return {
    list(filters: FeedbackFilters, signal?: AbortSignal): Promise<TransportResult<FeedbackPage>> {
      const parsed = feedbackFiltersSchema.safeParse(filters);

      if (!parsed.success) {
        return invalidRequest<FeedbackPage>();
      }

      const query = new URLSearchParams({
        limit: String(parsed.data.limit),
        offset: String(parsed.data.offset),
      });

      if (parsed.data.status !== null) {
        query.set('status', parsed.data.status);
      }

      if (parsed.data.rating !== null) {
        query.set('rating', String(parsed.data.rating));
      }

      if (parsed.data.helpful !== null) {
        query.set('helpful', String(parsed.data.helpful));
      }

      if (parsed.data.reasonCode !== null) {
        query.set('reason_code', parsed.data.reasonCode);
      }

      if (parsed.data.customerId !== null) {
        query.set('customer_id', parsed.data.customerId);
      }

      if (parsed.data.conversationId !== null) {
        query.set('conversation_id', parsed.data.conversationId);
      }

      if (parsed.data.createdFrom !== null) {
        query.set('created_from', parsed.data.createdFrom);
      }

      if (parsed.data.createdTo !== null) {
        query.set('created_to', parsed.data.createdTo);
      }

      return request({
        path: '/v1/feedback',
        method: 'GET',
        authentication: 'bearer',
        query,
        decode: decodeFeedbackPage,
        ...requestSignal(signal),
      });
    },

    get(feedbackId: string, signal?: AbortSignal): Promise<TransportResult<Feedback>> {
      const parsedId = feedbackIdSchema.safeParse(feedbackId);

      if (!parsedId.success) {
        return invalidRequest<Feedback>();
      }

      return request({
        path: `/v1/feedback/${parsedId.data}`,
        method: 'GET',
        authentication: 'bearer',
        decode: decodeFeedback,
        ...requestSignal(signal),
      });
    },

    review(
      feedbackId: string,
      input: FeedbackReviewRequest,
      signal?: AbortSignal,
    ): Promise<TransportResult<FeedbackReviewResponse>> {
      const parsedId = feedbackIdSchema.safeParse(feedbackId);
      const parsedInput = feedbackReviewRequestSchema.safeParse(input);

      if (!parsedId.success || !parsedInput.success) {
        return invalidRequest<FeedbackReviewResponse>();
      }

      return request({
        path: `/v1/feedback/${parsedId.data}/review`,
        method: 'PATCH',
        authentication: 'bearer',
        body: {
          kind: 'json',
          value: parsedInput.data,
        },
        decode: decodeFeedbackReviewResponse,
        ...requestSignal(signal),
      });
    },
  };
}
