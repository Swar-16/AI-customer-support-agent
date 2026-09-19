// apps/web/src/features/operations/operations-conversation-contract.ts
import { z } from 'zod';

import { SafeApiError } from '../../shared/api/safe-error';

export const operationsConversationIdSchema = z.uuid();

export const operationsConversationStatusSchema = z.enum([
  'open',
  'waiting_for_customer',
  'waiting_for_agent',
  'escalated',
  'resolved',
  'closed',
]);

export const operationsConversationChannelSchema = z.enum(['web', 'mobile', 'email', 'api']);

export const operationsMessageRoleSchema = z.enum(['customer', 'assistant', 'support_agent']);

const timestampSchema = z.iso.datetime({
  offset: true,
});

export const operationsConversationSchema = z
  .object({
    conversation_id: operationsConversationIdSchema,
    customer_id: z.uuid(),
    status: operationsConversationStatusSchema,
    channel: operationsConversationChannelSchema,
    title: z.string().nullable().default(null),
    created_at: timestampSchema,
    updated_at: timestampSchema,
    resolved_at: timestampSchema.nullable().default(null),
    closed_at: timestampSchema.nullable().default(null),
  })
  .strict();

export const operationsMessageFeedbackSchema = z
  .object({
    feedback_id: z.uuid(),
    rating: z.number().int().min(1).max(5),
    helpful: z.boolean().nullable().default(null),
    created_at: timestampSchema,
  })
  .strict();

export const operationsConversationMessageSchema = z
  .object({
    message_id: z.uuid(),
    conversation_id: operationsConversationIdSchema,
    role: operationsMessageRoleSchema,
    content: z.string(),
    sequence_number: z.number().int().min(1),
    created_at: timestampSchema,

    ai_run_id: z.uuid().nullable().default(null),
    feedback: operationsMessageFeedbackSchema.nullable().default(null),
    feedback_eligible: z.boolean().default(false),
  })
  .strict();

export const operationsConversationPageSchema = z
  .object({
    items: z.array(operationsConversationSchema),
    total: z.number().int().nonnegative(),
    count: z.number().int().nonnegative(),
    limit: z.number().int().min(1).max(200),
    offset: z.number().int().nonnegative(),
    has_more: z.boolean(),
    next_offset: z.number().int().nonnegative().nullable().default(null),
  })
  .strict();

export const operationsMessagePageSchema = z
  .object({
    items: z.array(operationsConversationMessageSchema),
    total: z.number().int().nonnegative(),
    count: z.number().int().nonnegative(),
    limit: z.number().int().min(1).max(200),
    offset: z.number().int().nonnegative(),
    has_more: z.boolean(),
    next_offset: z.number().int().nonnegative().nullable(),
  })
  .strict();

export type OperationsConversationStatus = z.infer<typeof operationsConversationStatusSchema>;

export type OperationsConversationChannel = z.infer<typeof operationsConversationChannelSchema>;

export type OperationsMessageRole = z.infer<typeof operationsMessageRoleSchema>;

export type OperationsConversation = z.infer<typeof operationsConversationSchema>;

export type OperationsConversationMessage = z.infer<typeof operationsConversationMessageSchema>;

export type OperationsConversationPage = z.infer<typeof operationsConversationPageSchema>;

export type OperationsMessagePage = z.infer<typeof operationsMessagePageSchema>;

function decode<T>(schema: z.ZodType<T>, value: unknown): T {
  const result = schema.safeParse(value);

  if (!result.success) {
    throw SafeApiError.fromLocal('invalid-response');
  }

  return result.data;
}

function checkPagination(page: {
  readonly items: readonly unknown[];
  readonly total: number;
  readonly count: number;
  readonly limit: number;
  readonly offset: number;
  readonly has_more: boolean;
  readonly next_offset: number | null;
}) {
  const expectedNextOffset = page.offset + page.count;

  if (
    page.count !== page.items.length ||
    page.count > page.limit ||
    page.total < expectedNextOffset ||
    (page.has_more &&
      (page.count === 0 || page.next_offset === null || page.next_offset !== expectedNextOffset)) ||
    (!page.has_more && page.next_offset !== null)
  ) {
    throw SafeApiError.fromLocal('invalid-response');
  }
}

export function decodeOperationsConversation(value: unknown): OperationsConversation {
  return decode(operationsConversationSchema, value);
}

export function decodeOperationsConversationPage(value: unknown): OperationsConversationPage {
  const page = decode(operationsConversationPageSchema, value);

  checkPagination(page);
  return page;
}

export function decodeOperationsMessagePage(value: unknown): OperationsMessagePage {
  const page = decode(operationsMessagePageSchema, value);

  checkPagination(page);
  return page;
}
