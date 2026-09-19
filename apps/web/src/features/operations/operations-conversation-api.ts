// apps/web/src/features/operations/operations-conversation-api.ts
import { z } from 'zod';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult, createTransport } from '../../shared/api/transport';
import {
  decodeOperationsConversation,
  decodeOperationsConversationPage,
  decodeOperationsMessagePage,
  operationsConversationChannelSchema,
  operationsConversationIdSchema,
  operationsConversationStatusSchema,
  type OperationsConversation,
  type OperationsConversationChannel,
  type OperationsConversationPage,
  type OperationsConversationStatus,
  type OperationsMessagePage,
} from './operations-conversation-contract';

type Transport = ReturnType<typeof createTransport>;

export interface OperationsConversationFilters {
  readonly status: OperationsConversationStatus | null;
  readonly channel: OperationsConversationChannel | null;
  readonly customerId: string | null;
  readonly limit: number;
  readonly offset: number;
}

export interface OperationsMessageFilters {
  readonly conversationId: string;
  readonly limit: number;
  readonly offset: number;
}

const conversationFiltersSchema = z
  .object({
    status: operationsConversationStatusSchema.nullable(),
    channel: operationsConversationChannelSchema.nullable(),
    customerId: z.uuid().nullable(),
    limit: z.number().int().min(1).max(200),
    offset: z.number().int().nonnegative(),
  })
  .strict();

const messageFiltersSchema = z
  .object({
    conversationId: operationsConversationIdSchema,
    limit: z.number().int().min(1).max(200),
    offset: z.number().int().nonnegative(),
  })
  .strict();

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

export function createOperationsConversationApi(request: Transport) {
  return {
    list(
      filters: OperationsConversationFilters,
      signal?: AbortSignal,
    ): Promise<TransportResult<OperationsConversationPage>> {
      const parsed = conversationFiltersSchema.safeParse(filters);

      if (!parsed.success) {
        return invalidRequest<OperationsConversationPage>();
      }

      const query = new URLSearchParams({
        limit: String(parsed.data.limit),
        offset: String(parsed.data.offset),
      });

      if (parsed.data.status !== null) {
        query.set('status', parsed.data.status);
      }

      if (parsed.data.channel !== null) {
        query.set('channel', parsed.data.channel);
      }

      if (parsed.data.customerId !== null) {
        query.set('customer_id', parsed.data.customerId);
      }

      return request({
        path: '/v1/conversations',
        method: 'GET',
        authentication: 'bearer',
        query,
        decode: decodeOperationsConversationPage,
        ...requestSignal(signal),
      });
    },

    get(
      conversationId: string,
      signal?: AbortSignal,
    ): Promise<TransportResult<OperationsConversation>> {
      const parsedId = operationsConversationIdSchema.safeParse(conversationId);

      if (!parsedId.success) {
        return invalidRequest<OperationsConversation>();
      }

      return request({
        path: `/v1/conversations/${parsedId.data}`,
        method: 'GET',
        authentication: 'bearer',
        decode: decodeOperationsConversation,
        ...requestSignal(signal),
      });
    },

    listMessages(
      filters: OperationsMessageFilters,
      signal?: AbortSignal,
    ): Promise<TransportResult<OperationsMessagePage>> {
      const parsed = messageFiltersSchema.safeParse(filters);

      if (!parsed.success) {
        return invalidRequest<OperationsMessagePage>();
      }

      const query = new URLSearchParams({
        limit: String(parsed.data.limit),
        offset: String(parsed.data.offset),
      });

      return request({
        path: `/v1/conversations/${parsed.data.conversationId}/messages`,
        method: 'GET',
        authentication: 'bearer',
        query,
        decode: decodeOperationsMessagePage,
        ...requestSignal(signal),
      });
    },
  };
}
