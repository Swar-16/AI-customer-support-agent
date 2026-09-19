// apps/web/src/features/operations/operations-api.ts
import type { createTransport } from '../../shared/api/transport';
import { decodeDashboardOverview } from './operations-contract';

type Transport = ReturnType<typeof createTransport>;

export const overviewWindows = ['24h', '7d', '30d'] as const;

export type OverviewWindow = (typeof overviewWindows)[number];

const windowDurations: Record<OverviewWindow, number> = {
  '24h': 24 * 60 * 60 * 1_000,
  '7d': 7 * 24 * 60 * 60 * 1_000,
  '30d': 30 * 24 * 60 * 60 * 1_000,
};

function requestSignal(signal: AbortSignal | undefined) {
  return signal === undefined ? {} : { signal };
}

export function createOperationsApi(request: Transport, now: () => Date = () => new Date()) {
  return {
    overview(window: OverviewWindow, signal?: AbortSignal) {
      const endedAt = now();
      const startedAt = new Date(endedAt.getTime() - windowDurations[window]);

      const query = new URLSearchParams({
        started_at: startedAt.toISOString(),
        ended_at: endedAt.toISOString(),
      });

      return request({
        path: '/v1/dashboard/overview',
        method: 'GET',
        authentication: 'bearer',
        query,
        decode: decodeDashboardOverview,
        ...requestSignal(signal),
      });
    },
  };
}
