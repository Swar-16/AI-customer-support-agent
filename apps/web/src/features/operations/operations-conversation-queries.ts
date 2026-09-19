// apps/web/src/features/operations/operations-conversation-queries.ts
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult } from '../../shared/api/transport';
import { useApiTransport } from '../../shared/api/transport-context';
import { useSession } from '../../shared/auth/session-context';
import {
  createOperationsConversationApi,
  type OperationsConversationFilters,
  type OperationsMessageFilters,
} from './operations-conversation-api';

export const operationsConversationKeys = {
  all: (operatorId: string | null) => ['operations', operatorId, 'conversations'] as const,

  lists: (operatorId: string | null) =>
    [...operationsConversationKeys.all(operatorId), 'list'] as const,

  list: (operatorId: string | null, filters: OperationsConversationFilters) =>
    [
      ...operationsConversationKeys.lists(operatorId),
      {
        status: filters.status,
        channel: filters.channel,
        customerId: filters.customerId,
        limit: filters.limit,
        offset: filters.offset,
      },
    ] as const,

  details: (operatorId: string | null) =>
    [...operationsConversationKeys.all(operatorId), 'detail'] as const,

  detail: (operatorId: string | null, conversationId: string | null) =>
    [...operationsConversationKeys.details(operatorId), conversationId] as const,

  messages: (operatorId: string | null, filters: OperationsMessageFilters | null) =>
    [
      ...operationsConversationKeys.all(operatorId),
      'messages',
      filters === null
        ? null
        : {
            conversationId: filters.conversationId,
            limit: filters.limit,
            offset: filters.offset,
          },
    ] as const,
};

function unwrap<T>(result: TransportResult<T>): T {
  if (!result.ok) {
    throw result.error;
  }

  return result.data;
}

function useAdminId(): string | null {
  const session = useSession();

  if (
    session.phase !== 'authenticated' ||
    session.user?.status !== 'active' ||
    session.user.role !== 'admin'
  ) {
    return null;
  }

  return session.user.id;
}

export function useOperationsConversationApi() {
  const transport = useApiTransport();

  return useMemo(() => createOperationsConversationApi(transport), [transport]);
}

export function useOperationsConversationList(filters: OperationsConversationFilters) {
  const api = useOperationsConversationApi();
  const operatorId = useAdminId();

  return useQuery({
    queryKey: operationsConversationKeys.list(operatorId, filters),
    enabled: operatorId !== null,
    retry: false,
    staleTime: 15_000,

    queryFn: async ({ signal }) => {
      if (operatorId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.list(filters, signal));
    },
  });
}

export function useOperationsConversationDetail(conversationId: string | null) {
  const api = useOperationsConversationApi();
  const operatorId = useAdminId();

  return useQuery({
    queryKey: operationsConversationKeys.detail(operatorId, conversationId),
    enabled: operatorId !== null && conversationId !== null,
    retry: false,
    staleTime: 15_000,

    queryFn: async ({ signal }) => {
      if (operatorId === null || conversationId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.get(conversationId, signal));
    },
  });
}

export function useOperationsConversationMessages(filters: OperationsMessageFilters | null) {
  const api = useOperationsConversationApi();
  const operatorId = useAdminId();

  return useQuery({
    queryKey: operationsConversationKeys.messages(operatorId, filters),
    enabled: operatorId !== null && filters !== null,
    retry: false,
    staleTime: 10_000,

    queryFn: async ({ signal }) => {
      if (operatorId === null || filters === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.listMessages(filters, signal));
    },
  });
}
