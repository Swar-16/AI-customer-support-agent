// apps/web/src/features/operations/operations-queries.ts
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult } from '../../shared/api/transport';
import { useApiTransport } from '../../shared/api/transport-context';
import { useSession } from '../../shared/auth/session-context';
import { createOperationsApi, type OverviewWindow } from './operations-api';

export const operationsKeys = {
  all: (adminId: string | null) => ['operations', adminId] as const,

  overview: (adminId: string | null, window: OverviewWindow) =>
    ['operations', adminId, 'overview', window] as const,
};

function unwrap<T>(result: TransportResult<T>): T {
  if (!result.ok) throw result.error;
  return result.data;
}

export function useOperationsApi() {
  const transport = useApiTransport();

  return useMemo(() => createOperationsApi(transport), [transport]);
}

function useAdminId(): string | null {
  const session = useSession();

  return session.phase === 'authenticated' &&
    session.user?.role === 'admin' &&
    session.user.status === 'active'
    ? session.user.id
    : null;
}

export function useDashboardOverview(window: OverviewWindow) {
  const api = useOperationsApi();
  const adminId = useAdminId();

  return useQuery({
    queryKey: operationsKeys.overview(adminId, window),
    enabled: adminId !== null,
    retry: false,
    staleTime: 30_000,
    queryFn: async ({ signal }) => {
      if (adminId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.overview(window, signal));
    },
  });
}
