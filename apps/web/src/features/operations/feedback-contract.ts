// apps/web/src/features/operations/feedback-contract.ts
import { z } from 'zod';

import { SafeApiError } from '../../shared/api/safe-error';

export const feedbackIdSchema = z.uuid();

export const feedbackStatusSchema = z.enum(['pending', 'reviewed', 'actioned', 'dismissed']);

export const feedbackReviewTargetStatusSchema = z.enum(['reviewed', 'actioned', 'dismissed']);

export const feedbackReasonCodeSchema = z.enum([
  'INCORRECT_ANSWER',
  'INCOMPLETE_ANSWER',
  'IRRELEVANT_ANSWER',
  'OUTDATED_INFORMATION',
  'UNCLEAR_ANSWER',
  'MISSING_CITATION',
  'UNSAFE_RESPONSE',
  'SLOW_RESPONSE',
  'OTHER',
]);

const timestampSchema = z.iso.datetime({ offset: true });

export const feedbackSchema = z
  .object({
    feedback_id: feedbackIdSchema,
    conversation_id: z.uuid(),
    customer_id: z.uuid(),
    response_message_id: z.uuid(),
    ai_run_id: z.uuid().nullable().default(null),

    rating: z.number().int().min(1).max(5),
    helpful: z.boolean().nullable().default(null),
    comment: z.string().max(5_000).nullable().default(null),
    reason_codes: z.array(feedbackReasonCodeSchema).max(10),

    status: feedbackStatusSchema,
    reviewed_by_user_id: z.uuid().nullable().default(null),
    review_notes: z.string().max(5_000).nullable().default(null),

    metadata: z.record(z.string(), z.unknown()).default({}),
    row_version: z.number().int().min(1),

    created_at: timestampSchema,
    updated_at: timestampSchema,
    reviewed_at: timestampSchema.nullable().default(null),
  })
  .strict();

export const feedbackPageSchema = z
  .object({
    items: z.array(feedbackSchema),
    count: z.number().int().nonnegative(),
    limit: z.number().int().min(1).max(200),
    offset: z.number().int().nonnegative(),
    has_more: z.boolean(),
  })
  .strict()
  .superRefine((page, context) => {
    if (page.count !== page.items.length) {
      context.addIssue({
        code: 'custom',
        path: ['count'],
        message: 'Feedback count must match the number of returned items.',
      });
    }

    if (page.items.length > page.limit) {
      context.addIssue({
        code: 'custom',
        path: ['items'],
        message: 'The feedback page contains more items than its limit.',
      });
    }

    if (page.has_more && page.count === 0) {
      context.addIssue({
        code: 'custom',
        path: ['has_more'],
        message: 'An empty feedback page cannot indicate more results.',
      });
    }

    const feedbackIds = new Set<string>();

    page.items.forEach((feedback, index) => {
      if (feedbackIds.has(feedback.feedback_id)) {
        context.addIssue({
          code: 'custom',
          path: ['items', index, 'feedback_id'],
          message: 'Feedback identifiers must be unique within a page.',
        });
      }

      feedbackIds.add(feedback.feedback_id);
    });
  });

export const feedbackReviewRequestSchema = z
  .object({
    expected_row_version: z.number().int().min(1),
    target_status: feedbackReviewTargetStatusSchema,
    review_notes: z.string().trim().max(5_000).nullable(),
  })
  .strict()
  .superRefine((request, context) => {
    const notes = request.review_notes;

    if (
      (request.target_status === 'actioned' || request.target_status === 'dismissed') &&
      (notes === null || notes.length === 0)
    ) {
      context.addIssue({
        code: 'custom',
        path: ['review_notes'],
        message: `Review notes are required when feedback is ${request.target_status}.`,
      });
    }
  });

export const feedbackReviewResponseSchema = z
  .object({
    feedback_id: feedbackIdSchema,
    conversation_id: z.uuid(),
    customer_id: z.uuid(),
    response_message_id: z.uuid(),
    ai_run_id: z.uuid().nullable().default(null),

    previous_status: feedbackStatusSchema,
    current_status: feedbackStatusSchema,

    reviewed_by_user_id: z.uuid().nullable().default(null),
    review_notes: z.string().max(5_000).nullable().default(null),
    reviewed_at: timestampSchema.nullable().default(null),

    row_version: z.number().int().min(1),
    updated_at: timestampSchema,
    changed: z.boolean(),
  })
  .strict();

export type FeedbackStatus = z.infer<typeof feedbackStatusSchema>;
export type FeedbackReviewTargetStatus = z.infer<typeof feedbackReviewTargetStatusSchema>;
export type FeedbackReasonCode = z.infer<typeof feedbackReasonCodeSchema>;
export type Feedback = z.infer<typeof feedbackSchema>;
export type FeedbackPage = z.infer<typeof feedbackPageSchema>;
export type FeedbackReviewRequest = z.infer<typeof feedbackReviewRequestSchema>;
export type FeedbackReviewResponse = z.infer<typeof feedbackReviewResponseSchema>;

function decode<T>(schema: z.ZodType<T>, value: unknown): T {
  const result = schema.safeParse(value);

  if (!result.success) {
    throw SafeApiError.fromLocal('invalid-response');
  }

  return result.data;
}

export function decodeFeedback(value: unknown): Feedback {
  return decode(feedbackSchema, value);
}

export function decodeFeedbackPage(value: unknown): FeedbackPage {
  return decode(feedbackPageSchema, value);
}

export function decodeFeedbackReviewResponse(value: unknown): FeedbackReviewResponse {
  return decode(feedbackReviewResponseSchema, value);
}
