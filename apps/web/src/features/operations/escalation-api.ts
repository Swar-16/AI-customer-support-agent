// apps/web/src/features/operations/escalation-api.ts
import { z } from 'zod';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult, createTransport } from '../../shared/api/transport';
import {
  decodeEscalation,
  decodeEscalationPage,
  decodeEscalationUpdate,
  escalationIdSchema,
  escalationPrioritySchema,
  escalationStatusSchema,
  type Escalation,
  type EscalationPage,
  type EscalationPriority,
  type EscalationStatus,
  type EscalationUpdate,
} from './escalation-contract';

type Transport = ReturnType<typeof createTransport>;

export interface EscalationFilters {
  readonly activeOnly: boolean;
  readonly status: EscalationStatus | null;
  readonly priority: EscalationPriority | null;
  readonly reasonCode: string | null;
  readonly limit: number;
  readonly offset: number;
}

const filtersSchema = z
  .object({
    activeOnly: z.boolean(),
    status: escalationStatusSchema.nullable(),
    priority: escalationPrioritySchema.nullable(),
    reasonCode: z.string().trim().min(1).max(100).nullable(),
    limit: z.number().int().min(1).max(200),
    offset: z.number().int().nonnegative(),
  })
  .strict()
  .superRefine((filters, context) => {
    if (filters.activeOnly && (filters.status !== null || filters.reasonCode !== null)) {
      context.addIssue({
        code: 'custom',
        path: ['activeOnly'],
        message: 'Active-only queries cannot include status or reason-code filters.',
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

export function createEscalationApi(request: Transport) {
  return {
    list(
      filters: EscalationFilters,
      signal?: AbortSignal,
    ): Promise<TransportResult<EscalationPage>> {
      const parsed = filtersSchema.safeParse(filters);

      if (!parsed.success) {
        return invalidRequest<EscalationPage>();
      }

      const query = new URLSearchParams({
        active_only: String(parsed.data.activeOnly),
        limit: String(parsed.data.limit),
        offset: String(parsed.data.offset),
      });

      if (parsed.data.status !== null) {
        query.set('status', parsed.data.status);
      }

      if (parsed.data.priority !== null) {
        query.set('priority', parsed.data.priority);
      }

      if (parsed.data.reasonCode !== null) {
        query.set('reason_code', parsed.data.reasonCode);
      }

      return request({
        path: '/v1/escalations',
        method: 'GET',
        authentication: 'bearer',
        query,
        decode: decodeEscalationPage,
        ...requestSignal(signal),
      });
    },

    get(escalationId: string, signal?: AbortSignal): Promise<TransportResult<Escalation>> {
      const parsedId = escalationIdSchema.safeParse(escalationId);

      if (!parsedId.success) {
        return invalidRequest<Escalation>();
      }

      return request({
        path: `/v1/escalations/${parsedId.data}`,
        method: 'GET',
        authentication: 'bearer',
        decode: decodeEscalation,
        ...requestSignal(signal),
      });
    },

    updateStatus(
      escalationId: string,
      status: EscalationStatus,
      signal?: AbortSignal,
    ): Promise<TransportResult<EscalationUpdate>> {
      const parsedId = escalationIdSchema.safeParse(escalationId);
      const parsedStatus = escalationStatusSchema.safeParse(status);

      if (!parsedId.success || !parsedStatus.success) {
        return invalidRequest<EscalationUpdate>();
      }

      return request({
        path: `/v1/escalations/${parsedId.data}`,
        method: 'PATCH',
        authentication: 'bearer',
        body: {
          kind: 'json',
          value: {
            status: parsedStatus.data,
          },
        },
        decode: decodeEscalationUpdate,
        ...requestSignal(signal),
      });
    },
  };
}
