// apps/web/src/features/operations/ai-activity-api.ts
import { z } from 'zod';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult, createTransport } from '../../shared/api/transport';
import {
  analyticsBucketSchema,
  decodeAIAnalytics,
  type AIAnalytics,
  type AnalyticsBucket,
} from './ai-activity-contract';

type Transport = ReturnType<typeof createTransport>;

export interface AIAnalyticsWindow {
  readonly startedAt: string;
  readonly endedAt: string;
  readonly bucket: AnalyticsBucket;
}

const analyticsWindowRequestSchema = z
  .object({
    startedAt: z.iso.datetime({
      offset: true,
    }),
    endedAt: z.iso.datetime({
      offset: true,
    }),
    bucket: analyticsBucketSchema,
  })
  .strict()
  .superRefine((window, context) => {
    if (Date.parse(window.startedAt) >= Date.parse(window.endedAt)) {
      context.addIssue({
        code: 'custom',
        path: ['endedAt'],
        message: 'Analytics window end must be later than its start.',
      });
    }
  });

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

export function createAIActivityApi(request: Transport) {
  return {
    analytics(
      window: AIAnalyticsWindow,
      signal?: AbortSignal,
    ): Promise<TransportResult<AIAnalytics>> {
      const parsed = analyticsWindowRequestSchema.safeParse(window);

      if (!parsed.success) {
        return invalidRequest<AIAnalytics>();
      }

      const query = new URLSearchParams({
        started_at: parsed.data.startedAt,
        ended_at: parsed.data.endedAt,
        bucket: parsed.data.bucket,
      });

      return request({
        path: '/v1/dashboard/ai-analytics',
        method: 'GET',
        authentication: 'bearer',
        query,
        decode: decodeAIAnalytics,
        ...requestSignal(signal),
      });
    },
  };
}
