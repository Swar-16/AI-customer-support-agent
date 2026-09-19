// apps/web/src/features/operations/ai-trace-api.ts
import { z } from 'zod';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult, createTransport } from '../../shared/api/transport';
import {
  decodeTraceDetail,
  decodeTracePage,
  traceIdSchema,
  traceStatusSchema,
  type TraceDetail,
  type TracePage,
  type TraceStatus,
} from './ai-trace-contract';

type Transport = ReturnType<typeof createTransport>;

export interface TraceFilters {
  readonly startedAt: string;
  readonly endedAt: string;
  readonly traceId: string | null;
  readonly conversationId: string | null;
  readonly aiRunId: string | null;
  readonly status: TraceStatus | null;
  readonly limit: number;
  readonly offset: number;
}

const traceFiltersSchema = z
  .object({
    startedAt: z.iso.datetime({
      offset: true,
    }),
    endedAt: z.iso.datetime({
      offset: true,
    }),
    traceId: z.uuid().nullable(),
    conversationId: z.uuid().nullable(),
    aiRunId: z.uuid().nullable(),
    status: traceStatusSchema.nullable(),
    limit: z.number().int().min(1).max(500),
    offset: z.number().int().nonnegative(),
  })
  .strict()
  .superRefine((filters, context) => {
    if (Date.parse(filters.startedAt) >= Date.parse(filters.endedAt)) {
      context.addIssue({
        code: 'custom',
        path: ['endedAt'],
        message: 'Trace window end must be later than its start.',
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

export function createAITraceApi(request: Transport) {
  return {
    list(filters: TraceFilters, signal?: AbortSignal): Promise<TransportResult<TracePage>> {
      const parsed = traceFiltersSchema.safeParse(filters);

      if (!parsed.success) {
        return invalidRequest<TracePage>();
      }

      const query = new URLSearchParams({
        started_at: parsed.data.startedAt,
        ended_at: parsed.data.endedAt,
        limit: String(parsed.data.limit),
        offset: String(parsed.data.offset),
      });

      if (parsed.data.traceId !== null) {
        query.set('trace_id', parsed.data.traceId);
      }

      if (parsed.data.conversationId !== null) {
        query.set('conversation_id', parsed.data.conversationId);
      }

      if (parsed.data.aiRunId !== null) {
        query.set('ai_run_id', parsed.data.aiRunId);
      }

      if (parsed.data.status !== null) {
        query.set('status', parsed.data.status);
      }

      return request({
        path: '/v1/dashboard/traces',
        method: 'GET',
        authentication: 'bearer',
        query,
        decode: decodeTracePage,
        ...requestSignal(signal),
      });
    },

    get(traceId: string, signal?: AbortSignal): Promise<TransportResult<TraceDetail>> {
      const parsedId = traceIdSchema.safeParse(traceId);

      if (!parsedId.success) {
        return invalidRequest<TraceDetail>();
      }

      return request({
        path: `/v1/dashboard/traces/${parsedId.data}`,
        method: 'GET',
        authentication: 'bearer',
        decode: decodeTraceDetail,
        ...requestSignal(signal),
      });
    },
  };
}
