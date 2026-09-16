// apps/web/src/features/chat/customer-escalation-api.ts
import { z } from 'zod';

import type { components } from '../../shared/api/generated/schema';
import { SafeApiError } from '../../shared/api/safe-error';
import type { createTransport, TransportResult } from '../../shared/api/transport';
import { conversationIdSchema } from './chat-contract';

export type CustomerEscalation = components['schemas']['CustomerEscalationStatusResponse'];

type Transport = ReturnType<typeof createTransport>;

const timestamp = z.iso.datetime({ offset: true });

const customerEscalationSchema = z.object({
  escalation_id: conversationIdSchema,
  conversation_id: conversationIdSchema,
  status: z.enum(['open', 'in_review', 'resolved', 'dismissed']),
  priority: z.enum(['low', 'normal', 'high', 'urgent']),
  created_at: timestamp,
  updated_at: timestamp,
  resolved_at: timestamp.nullable().default(null),
}) satisfies z.ZodType<CustomerEscalation>;

function decodeCustomerEscalation(
  value: unknown,
  expectedConversationId: string,
): CustomerEscalation {
  const parsed = customerEscalationSchema.safeParse(value);

  if (!parsed.success || parsed.data.conversation_id !== expectedConversationId) {
    throw SafeApiError.fromLocal('invalid-response');
  }

  // The schema strips any properties outside the customer allowlist.
  return parsed.data;
}

export function createCustomerEscalationApi(request: Transport) {
  return {
    async get(
      conversationId: string,
      signal?: AbortSignal,
    ): Promise<TransportResult<CustomerEscalation>> {
      const id = conversationIdSchema.safeParse(conversationId);

      if (!id.success) {
        return {
          ok: false,
          error: SafeApiError.fromLocal('invalid-response'),
          retryAfterMs: null,
        };
      }

      return request({
        path: `/v1/conversations/${id.data}/escalation-status`,
        method: 'GET',
        authentication: 'bearer',
        decode: (value) => decodeCustomerEscalation(value, id.data),
        ...(signal === undefined ? {} : { signal }),
      });
    },
  };
}
