// apps/web/src/features/operations/ai-activity-queries.ts
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult } from '../../shared/api/transport';
import { useApiTransport } from '../../shared/api/transport-context';
import { useSession } from '../../shared/auth/session-context';
import { createAIActivityApi, type AIAnalyticsWindow } from './ai-activity-api';

export const aiActivityKeys = {
  all: (adminId: string | null) => ['operations', adminId, 'ai-activity'] as const,

  analytics: (adminId: string | null, window: AIAnalyticsWindow) =>
    [
      ...aiActivityKeys.all(adminId),
      'analytics',
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

export function useAIActivityApi() {
  const transport = useApiTransport();

  return useMemo(() => createAIActivityApi(transport), [transport]);
}

export function useAIAnalytics(window: AIAnalyticsWindow) {
  const api = useAIActivityApi();
  const adminId = useAdminId();

  return useQuery({
    queryKey: aiActivityKeys.analytics(adminId, window),
    enabled: adminId !== null,
    retry: false,
    staleTime: 30_000,

    queryFn: async ({ signal }) => {
      if (adminId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.analytics(window, signal));
    },
  });
}
