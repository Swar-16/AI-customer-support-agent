// apps/web/src/features/chat/chat-api.ts

import { z } from 'zod';

import type { components, paths } from '../../shared/api/generated/schema';
import { SafeApiError } from '../../shared/api/safe-error';
import type { createTransport } from '../../shared/api/transport';
import {
  conversationChannelSchema,
  conversationIdSchema,
  conversationStatusSchema,
  decodeConversation,
  decodeConversationPage,
  decodeCreatedConversation,
  decodeMessagePage,
  customerMessageSchema,
  decodeSendMessage,
  decodeClosedConversation,
} from './chat-contract';

type Transport = ReturnType<typeof createTransport>;

type ListQuery = NonNullable<paths['/v1/conversations']['get']['parameters']['query']>;

export type ConversationFilters = Pick<ListQuery, 'limit' | 'offset' | 'status' | 'channel'>;

export interface HistoryPagination {
  readonly limit?: number;
  readonly offset?: number;
}

const paginationSchema = z.object({
  limit: z.number().int().min(1).max(200).default(50),
  offset: z.number().int().nonnegative().default(0),
});

const filtersSchema = paginationSchema.extend({
  status: conversationStatusSchema.nullable().optional(),
  channel: conversationChannelSchema.nullable().optional(),
});

function invalidRequest() {
  return Promise.resolve({
    ok: false as const,
    error: SafeApiError.fromLocal('invalid-response'),
    retryAfterMs: null,
  });
}

function requestSignal(signal: AbortSignal | undefined) {
  return signal === undefined ? {} : { signal };
}

export function createChatApi(request: Transport) {
  return {
    create(title?: string | null, signal?: AbortSignal) {
      const parsed = z.string().max(500).nullable().optional().safeParse(title);
      if (!parsed.success) return invalidRequest();

      const body = {
        channel: 'web',
        ...(parsed.data === undefined ? {} : { title: parsed.data }),
      } satisfies components['schemas']['CreateConversationRequest'];

      return request({
        path: '/v1/conversations',
        method: 'POST',
        authentication: 'bearer',
        body: { kind: 'json', value: body },
        decode: decodeCreatedConversation,
        ...requestSignal(signal),
      });
    },

    list(filters: ConversationFilters = {}, signal?: AbortSignal) {
      const parsed = filtersSchema.safeParse(filters);
      if (!parsed.success) return invalidRequest();

      const query = new URLSearchParams({
        limit: String(parsed.data.limit),
        offset: String(parsed.data.offset),
      });

      if (parsed.data.status != null) {
        query.set('status', parsed.data.status);
      }
      if (parsed.data.channel != null) {
        query.set('channel', parsed.data.channel);
      }

      return request({
        path: '/v1/conversations',
        method: 'GET',
        authentication: 'bearer',
        query,
        decode: decodeConversationPage,
        ...requestSignal(signal),
      });
    },

    get(conversationId: string, signal?: AbortSignal) {
      const parsed = conversationIdSchema.safeParse(conversationId);
      if (!parsed.success) return invalidRequest();

      return request({
        path: `/v1/conversations/${parsed.data}`,
        method: 'GET',
        authentication: 'bearer',
        decode(value) {
          const conversation = decodeConversation(value);

          if (conversation.conversation_id !== parsed.data) {
            throw SafeApiError.fromLocal('invalid-response');
          }

          return conversation;
        },
        ...requestSignal(signal),
      });
    },

    close(conversationId: string, signal?: AbortSignal) {
      const id = conversationIdSchema.safeParse(conversationId);
      if (!id.success) return invalidRequest();

      return request({
        path: `/v1/conversations/${id.data}/close`,
        method: 'POST',
        authentication: 'bearer',
        decode(value) {
          const result = decodeClosedConversation(value);

          if (result.conversation_id !== id.data) {
            throw SafeApiError.fromLocal('invalid-response');
          }

          return result;
        },
        ...requestSignal(signal),
      });
    },

    send(conversationId: string, message: string, signal?: AbortSignal) {
      const id = conversationIdSchema.safeParse(conversationId);
      const parsedMessage = customerMessageSchema.safeParse(message);

      if (!id.success || !parsedMessage.success) {
        return invalidRequest();
      }

      const body = {
        message: parsedMessage.data,
      } satisfies components['schemas']['SendMessageRequest'];

      return request({
        path: `/v1/conversations/${id.data}/messages`,
        method: 'POST',
        authentication: 'bearer',
        body: { kind: 'json', value: body },
        decode(value) {
          const result = decodeSendMessage(value);

          if (result.conversation_id !== id.data) {
            throw SafeApiError.fromLocal('invalid-response');
          }

          return result;
        },
        ...requestSignal(signal),
      });
    },

    history(conversationId: string, pagination: HistoryPagination = {}, signal?: AbortSignal) {
      const id = conversationIdSchema.safeParse(conversationId);
      const page = paginationSchema.safeParse(pagination);

      if (!id.success || !page.success) return invalidRequest();

      return request({
        path: `/v1/conversations/${id.data}/messages`,
        method: 'GET',
        authentication: 'bearer',
        query: new URLSearchParams({
          limit: String(page.data.limit),
          offset: String(page.data.offset),
        }),
        decode(value) {
          const result = decodeMessagePage(value);

          if (result.items.some((message) => message.conversation_id !== id.data)) {
            throw SafeApiError.fromLocal('invalid-response');
          }

          return result;
        },
        ...requestSignal(signal),
      });
    },
  };
}
