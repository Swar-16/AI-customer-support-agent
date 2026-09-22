// apps/web/src/features/chat/chat-contract.ts
import { z } from 'zod';

import type { components } from '../../shared/api/generated/schema';
import { SafeApiError } from '../../shared/api/safe-error';

export type CreatedConversation = components['schemas']['CreateConversationResponse'];

export type Conversation = components['schemas']['ConversationResponse'];

export type ConversationPage = components['schemas']['ConversationListResponse'];

export type ConversationMessage = components['schemas']['ConversationMessageResponse'];

export type MessagePage = components['schemas']['ConversationMessageListResponse'];

export type SendMessageResult = components['schemas']['SendMessageResponse'];

export type CloseConversationResult = components['schemas']['CloseConversationResponse'];

export const conversationIdSchema = z
  .string()
  .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu)
  .transform((value) => value.toLowerCase());

export const conversationStatusSchema = z.enum([
  'open',
  'waiting_for_customer',
  'waiting_for_agent',
  'escalated',
  'resolved',
  'closed',
]);

export const conversationChannelSchema = z.enum(['web', 'mobile', 'email', 'api']);

const timestampSchema = z.iso.datetime({
  offset: true,
});

const createdConversationSchema = z.object({
  conversation_id: conversationIdSchema,
  customer_id: conversationIdSchema,
  status: conversationStatusSchema,
  channel: conversationChannelSchema,
  title: z.string().nullable().default(null),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}) satisfies z.ZodType<CreatedConversation>;

const conversationSchema = createdConversationSchema.extend({
  resolved_at: timestampSchema.nullable().default(null),
  closed_at: timestampSchema.nullable().default(null),
}) satisfies z.ZodType<Conversation>;

const conversationMessageFeedbackSchema = z.object({
  feedback_id: conversationIdSchema,
  rating: z.number().int().min(1).max(5),
  helpful: z.boolean().nullable().default(null),
  created_at: timestampSchema,
}) satisfies z.ZodType<components['schemas']['ConversationMessageFeedbackResponse']>;

const messageSchema = z.object({
  message_id: conversationIdSchema,
  conversation_id: conversationIdSchema,
  role: z.enum(['customer', 'assistant', 'support_agent']),
  content: z.string(),
  sequence_number: z.number().int().min(1),
  created_at: timestampSchema,

  /*
   * Lifecycle messages and other deterministic assistant messages may not
   * have a completed AI-run association.
   */
  ai_run_id: conversationIdSchema.nullable().default(null),

  /*
   * Feedback eligibility is decided exclusively by the backend.
   * Missing legacy values safely decode as false.
   */
  feedback_eligible: z.boolean().default(false),

  /*
   * Only the customer-safe historical feedback summary is returned here.
   */
  feedback: conversationMessageFeedbackSchema.nullable().default(null),
}) satisfies z.ZodType<ConversationMessage>;

const paginationFields = {
  total: z.number().int().nonnegative(),
  count: z.number().int().nonnegative(),
  limit: z.number().int().min(1).max(200),
  offset: z.number().int().nonnegative(),
  has_more: z.boolean(),
};

const conversationPageSchema = z.object({
  ...paginationFields,
  items: z.array(conversationSchema),
  next_offset: z.number().int().nonnegative().nullable().default(null),
}) satisfies z.ZodType<ConversationPage>;

const messagePageSchema = z.object({
  ...paginationFields,
  items: z.array(messageSchema),
  next_offset: z.number().int().nonnegative().nullable().default(null),
}) satisfies z.ZodType<MessagePage>;

/*
 * Count Unicode code points rather than UTF-16 code units.
 */
export const customerMessageSchema = z
  .string()
  .trim()
  .refine((value) => value.length > 0, {
    message: 'Enter a message.',
  })
  .refine((value) => Array.from(value).length <= 20_000, {
    message: 'Use 20,000 characters or fewer.',
  });

export const sendMessageSchema = z.object({
  conversation_id: conversationIdSchema,
  customer_message_id: conversationIdSchema,
  ai_run_id: conversationIdSchema,
  trace_id: conversationIdSchema,

  /*
   * OpenAPI intentionally exposes pipeline_stage as a string rather than
   * a frontend-owned enum.
   */
  pipeline_stage: z.string().min(1).max(100),

  intent: z.string().max(100).nullable().default(null),

  decision: z.string().max(100).nullable().default(null),

  assistant_message_id: conversationIdSchema.nullable().default(null),

  escalation_id: conversationIdSchema.nullable().default(null),

  response: z
    .string()
    .refine((value) => Array.from(value).length <= 30_000)
    .nullable()
    .default(null),

  succeeded: z.boolean(),
}) satisfies z.ZodType<SendMessageResult>;

const closeConversationSchema = z.object({
  conversation_id: conversationIdSchema,
  customer_id: conversationIdSchema,
  status: z.literal('closed'),
  resolved_at: timestampSchema.nullable(),
  closed_at: timestampSchema,
  updated_at: timestampSchema,
  changed: z.boolean(),
}) satisfies z.ZodType<CloseConversationResult>;

function decode<T>(schema: z.ZodType<T>, value: unknown): T {
  const result = schema.safeParse(value);

  if (!result.success) {
    /*
     * Never propagate Zod errors that might include customer or assistant
     * message content.
     */
    throw SafeApiError.fromLocal('invalid-response');
  }

  return result.data;
}

function checkPagination(page: {
  readonly items: readonly unknown[];
  readonly count: number;
  readonly limit: number;
  readonly offset: number;
  readonly has_more: boolean;
  readonly next_offset?: number | null;
}) {
  const nextOffset = page.next_offset ?? null;

  if (
    page.count !== page.items.length ||
    page.count > page.limit ||
    (page.has_more && (nextOffset === null || nextOffset <= page.offset || page.count === 0)) ||
    (!page.has_more && nextOffset !== null)
  ) {
    throw SafeApiError.fromLocal('invalid-response');
  }
}

export function decodeCreatedConversation(value: unknown): CreatedConversation {
  return decode(createdConversationSchema, value);
}

export function decodeConversation(value: unknown): Conversation {
  return decode(conversationSchema, value);
}

export function decodeConversationPage(value: unknown): ConversationPage {
  const page = decode(conversationPageSchema, value);

  checkPagination(page);

  return page;
}

export function decodeMessagePage(value: unknown): MessagePage {
  const page = decode(messagePageSchema, value);

  checkPagination(page);

  return page;
}

export function decodeSendMessage(value: unknown): SendMessageResult {
  const result = decode(sendMessageSchema, value);

  /*
   * The backend persists the response and assistant message together.
   *
   * A successful escalation is allowed to have both fields populated.
   * We intentionally do not branch on pipeline_stage here.
   */
  const hasAssistantMessage = result.assistant_message_id !== null;

  const hasResponse = result.response !== null;

  if (
    hasAssistantMessage !== hasResponse ||
    (result.response !== null && result.response.trim().length === 0)
  ) {
    throw SafeApiError.fromLocal('invalid-response');
  }

  return result;
}

export function decodeClosedConversation(value: unknown): CloseConversationResult {
  return decode(closeConversationSchema, value);
}
