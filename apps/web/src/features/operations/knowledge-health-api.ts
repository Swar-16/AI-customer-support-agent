// apps/web/src/features/operations/knowledge-health-api.ts
import { z } from 'zod';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult, createTransport } from '../../shared/api/transport';
import { analyticsBucketSchema, type AnalyticsBucket } from './ai-activity-contract';
import { decodeKnowledgeHealth, type KnowledgeHealth } from './knowledge-health-contract';

type Transport = ReturnType<typeof createTransport>;

export interface KnowledgeHealthWindow {
  readonly startedAt: string;
  readonly endedAt: string;
  readonly bucket: AnalyticsBucket;
}

const knowledgeHealthWindowSchema = z
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
        message: 'Knowledge health window end must be later than its start.',
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

export function createKnowledgeHealthApi(request: Transport) {
  return {
    get(
      window: KnowledgeHealthWindow,
      signal?: AbortSignal,
    ): Promise<TransportResult<KnowledgeHealth>> {
      const parsed = knowledgeHealthWindowSchema.safeParse(window);

      if (!parsed.success) {
        return invalidRequest<KnowledgeHealth>();
      }

      const query = new URLSearchParams({
        started_at: parsed.data.startedAt,
        ended_at: parsed.data.endedAt,
        bucket: parsed.data.bucket,
      });

      return request({
        path: '/v1/dashboard/knowledge-health',
        method: 'GET',
        authentication: 'bearer',
        query,
        decode: decodeKnowledgeHealth,
        ...requestSignal(signal),
      });
    },
  };
}
