// apps/web/src/features/operations/ai-trace-queries.ts
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult } from '../../shared/api/transport';
import { useApiTransport } from '../../shared/api/transport-context';
import { useSession } from '../../shared/auth/session-context';
import { createAITraceApi, type TraceFilters } from './ai-trace-api';

export const aiTraceKeys = {
  all: (adminId: string | null) => ['operations', adminId, 'ai-traces'] as const,

  lists: (adminId: string | null) => [...aiTraceKeys.all(adminId), 'list'] as const,

  list: (adminId: string | null, filters: TraceFilters) =>
    [
      ...aiTraceKeys.lists(adminId),
      {
        startedAt: filters.startedAt,
        endedAt: filters.endedAt,
        traceId: filters.traceId,
        conversationId: filters.conversationId,
        aiRunId: filters.aiRunId,
        status: filters.status,
        limit: filters.limit,
        offset: filters.offset,
      },
    ] as const,

  details: (adminId: string | null) => [...aiTraceKeys.all(adminId), 'detail'] as const,

  detail: (adminId: string | null, traceId: string | null) =>
    [...aiTraceKeys.details(adminId), traceId] as const,
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

export function useAITraceApi() {
  const transport = useApiTransport();

  return useMemo(() => createAITraceApi(transport), [transport]);
}

export function useAITraceList(filters: TraceFilters) {
  const api = useAITraceApi();
  const adminId = useAdminId();

  return useQuery({
    queryKey: aiTraceKeys.list(adminId, filters),
    enabled: adminId !== null,
    retry: false,
    staleTime: 15_000,

    queryFn: async ({ signal }) => {
      if (adminId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.list(filters, signal));
    },
  });
}

export function useAITraceDetail(traceId: string | null) {
  const api = useAITraceApi();
  const adminId = useAdminId();

  return useQuery({
    queryKey: aiTraceKeys.detail(adminId, traceId),
    enabled: adminId !== null && traceId !== null,
    retry: false,
    staleTime: 15_000,

    queryFn: async ({ signal }) => {
      if (adminId === null || traceId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.get(traceId, signal));
    },
  });
}
