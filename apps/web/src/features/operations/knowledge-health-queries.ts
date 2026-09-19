// apps/web/src/features/operations/knowledge-health-queries.ts
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult } from '../../shared/api/transport';
import { useApiTransport } from '../../shared/api/transport-context';
import { useSession } from '../../shared/auth/session-context';
import { createKnowledgeHealthApi, type KnowledgeHealthWindow } from './knowledge-health-api';

export const knowledgeHealthKeys = {
  all: (adminId: string | null) => ['operations', adminId, 'knowledge-health'] as const,

  report: (adminId: string | null, window: KnowledgeHealthWindow) =>
    [
      ...knowledgeHealthKeys.all(adminId),
      'report',
      {
        startedAt: window.startedAt,
        endedAt: window.endedAt,
        bucket: window.bucket,
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

export function useKnowledgeHealthApi() {
  const transport = useApiTransport();

  return useMemo(() => createKnowledgeHealthApi(transport), [transport]);
}

export function useKnowledgeHealth(window: KnowledgeHealthWindow) {
  const api = useKnowledgeHealthApi();
  const adminId = useAdminId();

  return useQuery({
    queryKey: knowledgeHealthKeys.report(adminId, window),
    enabled: adminId !== null,
    retry: false,
    staleTime: 30_000,

    queryFn: async ({ signal }) => {
      if (adminId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.get(window, signal));
    },
  });
}
