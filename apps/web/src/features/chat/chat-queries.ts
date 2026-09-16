// apps/web/src/features/chat/chat-queries.ts

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult } from '../../shared/api/transport';
import { useApiTransport } from '../../shared/api/transport-context';
import { useSession } from '../../shared/auth/session-context';
import { createChatApi } from './chat-api';

export const chatKeys = {
  all: (customerId: string | null) => ['chat', customerId] as const,

  conversations: (customerId: string | null, offset: number, limit: number) =>
    ['chat', customerId, 'conversations', { limit, offset }] as const,

  conversation: (customerId: string | null, conversationId: string | null) =>
    ['chat', customerId, 'conversation', conversationId] as const,

  history: (customerId: string | null, conversationId: string | null, offset: number) =>
    [
      'chat',
      customerId,
      'conversation',
      conversationId,
      'messages',
      { limit: 50, offset },
    ] as const,
};

function unwrap<T>(result: TransportResult<T>): T {
  if (!result.ok) throw result.error;
  return result.data;
}

export function useChatApi() {
  const transport = useApiTransport();
  return useMemo(() => createChatApi(transport), [transport]);
}

function useCustomerId(): string | null {
  const session = useSession();

  return session.phase === 'authenticated' &&
    session.user?.role === 'customer' &&
    session.user.status === 'active'
    ? session.user.id
    : null;
}

export function useConversations(offset: number, limit: number) {
  const api = useChatApi();
  const customerId = useCustomerId();

  return useQuery({
    queryKey: chatKeys.conversations(customerId, offset, limit),
    enabled: customerId !== null,
    retry: false,
    queryFn: async ({ signal }) => {
      if (customerId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.list({ limit, offset }, signal));
    },
  });
}

export function useConversation(conversationId: string | null) {
  const api = useChatApi();
  const customerId = useCustomerId();

  return useQuery({
    queryKey: chatKeys.conversation(customerId, conversationId),
    enabled: customerId !== null && conversationId !== null,
    retry: false,
    queryFn: async ({ signal }) => {
      if (customerId === null || conversationId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.get(conversationId, signal));
    },
  });
}

export function useConversationHistory(conversationId: string | null, offset: number) {
  const api = useChatApi();
  const customerId = useCustomerId();

  return useQuery({
    queryKey: chatKeys.history(customerId, conversationId, offset),
    enabled: customerId !== null && conversationId !== null,
    retry: false,
    queryFn: async ({ signal }) => {
      if (customerId === null || conversationId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.history(conversationId, { limit: 50, offset }, signal));
    },
  });
}
