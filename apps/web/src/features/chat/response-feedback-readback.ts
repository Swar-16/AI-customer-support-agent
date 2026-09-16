// apps/web/src/features/chat/response-feedback-readback.ts
import { z } from 'zod';

import type { components } from '../../shared/api/generated/schema';
import { SafeApiError } from '../../shared/api/safe-error';
import type { createTransport } from '../../shared/api/transport';
import { conversationIdSchema } from './chat-contract';

type Transport = ReturnType<typeof createTransport>;

type StoredRating = Pick<
  components['schemas']['FeedbackResponse'],
  'feedback_id' | 'conversation_id' | 'customer_id' | 'response_message_id' | 'rating'
>;

type RatingPage = Omit<components['schemas']['FeedbackListResponse'], 'items'> & {
  readonly items: StoredRating[];
};

export type FeedbackReadback =
  | {
      readonly kind: 'found';
      readonly feedbackId: string;
      readonly rating: number;
    }
  | { readonly kind: 'not-observed' }
  | { readonly kind: 'incomplete' };

const PAGE_SIZE = 100;
const MAX_PAGES = 5;

const storedRatingSchema = z.object({
  feedback_id: conversationIdSchema,
  conversation_id: conversationIdSchema,
  customer_id: conversationIdSchema,
  response_message_id: conversationIdSchema,
  rating: z.number().int().min(1).max(5),
}) satisfies z.ZodType<StoredRating>;

const pageSchema = z.object({
  items: z.array(storedRatingSchema).max(PAGE_SIZE),
  count: z.number().int().min(0).max(PAGE_SIZE),
  limit: z.literal(PAGE_SIZE),
  offset: z.number().int().nonnegative(),
  has_more: z.boolean(),
}) satisfies z.ZodType<RatingPage>;

function requireId(value: string): string {
  const parsed = conversationIdSchema.safeParse(value);

  if (!parsed.success) {
    throw SafeApiError.fromLocal('invalid-response');
  }

  return parsed.data;
}

export function createResponseFeedbackReadback(request: Transport) {
  return {
    async findRating(
      customerId: string,
      conversationId: string,
      responseMessageId: string,
      signal?: AbortSignal,
    ): Promise<FeedbackReadback> {
      const ownerId = requireId(customerId);
      const conversation = requireId(conversationId);
      const message = requireId(responseMessageId);

      for (let pageIndex = 0; pageIndex < MAX_PAGES; pageIndex += 1) {
        if (signal?.aborted) {
          throw SafeApiError.fromLocal('aborted');
        }

        const offset = pageIndex * PAGE_SIZE;

        const result = await request<RatingPage>({
          path: '/v1/feedback',
          method: 'GET',
          authentication: 'bearer',
          query: new URLSearchParams({
            conversation_id: conversation,
            limit: String(PAGE_SIZE),
            offset: String(offset),
          }),
          decode: (value) => {
            const parsed = pageSchema.safeParse(value);

            if (!parsed.success) {
              throw SafeApiError.fromLocal('invalid-response');
            }

            const page = parsed.data;

            if (
              page.offset !== offset ||
              page.count !== page.items.length ||
              (page.has_more && page.count !== PAGE_SIZE) ||
              page.items.some(
                (item) => item.customer_id !== ownerId || item.conversation_id !== conversation,
              )
            ) {
              throw SafeApiError.fromLocal('invalid-response');
            }

            return page;
          },
          ...(signal ? { signal } : {}),
        });

        if (!result.ok) throw result.error;

        if (signal?.aborted) {
          throw SafeApiError.fromLocal('aborted');
        }

        const matches = result.data.items.filter((item) => item.response_message_id === message);

        if (matches.length > 1) {
          throw SafeApiError.fromLocal('invalid-response');
        }

        const match = matches[0];

        if (match) {
          return {
            kind: 'found',
            feedbackId: match.feedback_id,
            rating: match.rating,
          };
        }

        if (!result.data.has_more) {
          // Offset pagination is not a snapshot. This does not prove that
          // an earlier mutation failed or that resubmission is safe.
          return { kind: 'not-observed' };
        }
      }

      return { kind: 'incomplete' };
    },
  };
}
