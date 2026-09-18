// apps/web/src/features/chat/response-feedback-api.ts
import { z } from 'zod';

import type { components } from '../../shared/api/generated/schema';
import { SafeApiError } from '../../shared/api/safe-error';
import type { createTransport, TransportResult } from '../../shared/api/transport';
import { conversationIdSchema } from './chat-contract';

type Transport = ReturnType<typeof createTransport>;

export type RatingInput = Pick<
  components['schemas']['SubmitFeedbackRequest'],
  'response_message_id' | 'ai_run_id' | 'rating'
>;

export type RatingReceipt = Pick<
  components['schemas']['SubmitFeedbackResponse'],
  | 'feedback_id'
  | 'conversation_id'
  | 'customer_id'
  | 'response_message_id'
  | 'ai_run_id'
  | 'rating'
  | 'status'
  | 'row_version'
  | 'created'
>;

export const feedbackRatingSchema = z.number().int().min(1).max(5);

const ratingInputSchema = z.object({
  response_message_id: conversationIdSchema,
  ai_run_id: conversationIdSchema,
  rating: feedbackRatingSchema,
}) satisfies z.ZodType<RatingInput>;

const ratingReceiptSchema = z.object({
  feedback_id: conversationIdSchema,
  conversation_id: conversationIdSchema,
  customer_id: conversationIdSchema,
  response_message_id: conversationIdSchema,
  ai_run_id: conversationIdSchema.nullable().default(null),
  rating: feedbackRatingSchema,
  status: z.enum(['pending', 'reviewed', 'actioned', 'dismissed']),
  row_version: z.number().int().min(1),
  created: z.boolean(),
}) satisfies z.ZodType<RatingReceipt>;

export function createResponseFeedbackApi(request: Transport) {
  return {
    async submitRating(
      conversationId: string,
      input: RatingInput,
      signal?: AbortSignal,
    ): Promise<TransportResult<RatingReceipt>> {
      const id = conversationIdSchema.safeParse(conversationId);
      const parsed = ratingInputSchema.safeParse(input);

      if (!id.success || !parsed.success) {
        return {
          ok: false,
          error: SafeApiError.fromLocal('invalid-response'),
          retryAfterMs: null,
        };
      }

      const body = {
        response_message_id: parsed.data.response_message_id,
        ai_run_id: parsed.data.ai_run_id,
        rating: parsed.data.rating,
      } satisfies components['schemas']['SubmitFeedbackRequest'];

      return request({
        path: `/v1/conversations/${id.data}/feedback`,
        method: 'POST',
        authentication: 'bearer',
        body: { kind: 'json', value: body },
        decode(value) {
          const receipt = ratingReceiptSchema.safeParse(value);

          if (
            !receipt.success ||
            receipt.data.conversation_id !== id.data ||
            receipt.data.response_message_id !== body.response_message_id ||
            receipt.data.ai_run_id !== body.ai_run_id ||
            receipt.data.rating !== body.rating
          ) {
            throw SafeApiError.fromLocal('invalid-response');
          }

          return receipt.data;
        },
        ...(signal === undefined ? {} : { signal }),
      });
    },
  };
}
