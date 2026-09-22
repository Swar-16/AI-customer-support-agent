// apps/web/src/features/chat/customer-escalation-api.ts
import { z } from 'zod';

import type { components } from '../../shared/api/generated/schema';
import { SafeApiError } from '../../shared/api/safe-error';
import type { createTransport, TransportResult } from '../../shared/api/transport';
import { conversationIdSchema } from './chat-contract';

export type CustomerEscalation = components['schemas']['CustomerEscalationStatusResponse'];

export type CustomerLinkedTicket = components['schemas']['CustomerLinkedTicketResponse'];

type Transport = ReturnType<typeof createTransport>;

const timestampSchema = z.iso.datetime({
  offset: true,
});

export const customerTicketStatusSchema = z.enum([
  'open',
  'in_progress',
  'waiting_for_customer',
  'resolved',
  'closed',
  'reopened',
]);

const customerLinkedTicketSchema = z.object({
  ticket_id: conversationIdSchema,
  ticket_reference: z.string().min(1).max(32),
  status: customerTicketStatusSchema,
}) satisfies z.ZodType<CustomerLinkedTicket>;

const customerEscalationSchema = z.object({
  escalation_id: conversationIdSchema,
  conversation_id: conversationIdSchema,

  status: z.enum(['open', 'in_review', 'resolved', 'dismissed']),

  priority: z.enum(['low', 'normal', 'high', 'urgent']),

  created_at: timestampSchema,
  updated_at: timestampSchema,
  resolved_at: timestampSchema.nullable().default(null),

  /*
   * A ticket exists only after an agent explicitly converts the
   * escalation. Null is therefore a normal and expected state.
   */
  linked_ticket: customerLinkedTicketSchema.nullable().default(null),
}) satisfies z.ZodType<CustomerEscalation>;

function invalidRequest(): Promise<TransportResult<CustomerEscalation>> {
  return Promise.resolve({
    ok: false,
    error: SafeApiError.fromLocal('invalid-response'),
    retryAfterMs: null,
  });
}

function decodeCustomerEscalation(
  value: unknown,
  expectedConversationId: string,
): CustomerEscalation {
  const parsed = customerEscalationSchema.safeParse(value);

  if (!parsed.success || parsed.data.conversation_id !== expectedConversationId) {
    throw SafeApiError.fromLocal('invalid-response');
  }

  /*
   * Zod strips properties outside the customer-authorized response.
   * This prevents operational metadata or internal ticket data from
   * accidentally reaching the customer interface.
   */
  return parsed.data;
}

export function createCustomerEscalationApi(request: Transport) {
  return {
    get(
      conversationId: string,
      signal?: AbortSignal,
    ): Promise<TransportResult<CustomerEscalation>> {
      const parsedConversationId = conversationIdSchema.safeParse(conversationId);

      if (!parsedConversationId.success) {
        return invalidRequest();
      }

      return request({
        path: `/v1/conversations/${parsedConversationId.data}/escalation-status`,
        method: 'GET',
        authentication: 'bearer',
        decode: (value) => decodeCustomerEscalation(value, parsedConversationId.data),
        ...(signal === undefined ? {} : { signal }),
      });
    },
  };
}
