// apps/web/src/features/operations/escalation-api.ts
import { z } from 'zod';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult, createTransport } from '../../shared/api/transport';
import {
  decodeEscalationDetail,
  decodeEscalationPage,
  decodeEscalationUpdate,
  escalationIdSchema,
  escalationPrioritySchema,
  escalationStatusSchema,
  escalationTransitionRequestSchema,
  type EscalationTransitionRequest,
  type EscalationDetail,
  type EscalationPage,
  type EscalationPriority,
  type EscalationStatus,
  type EscalationUpdate,
} from './escalation-contract';
import type { components } from '../../shared/api/generated/schema';

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

    get(escalationId: string, signal?: AbortSignal): Promise<TransportResult<EscalationDetail>> {
      const parsedId = escalationIdSchema.safeParse(escalationId);

      if (!parsedId.success) {
        return invalidRequest<EscalationDetail>();
      }

      return request({
        path: `/v1/escalations/${parsedId.data}`,
        method: 'GET',
        authentication: 'bearer',
        decode(value) {
          const escalation = decodeEscalationDetail(value);

          if (escalation.escalation_id !== parsedId.data) {
            throw SafeApiError.fromLocal('invalid-response');
          }

          return escalation;
        },
        ...requestSignal(signal),
      });
    },

    updateStatus(
      escalationId: string,
      transition: EscalationTransitionRequest,
      signal?: AbortSignal,
    ): Promise<TransportResult<EscalationUpdate>> {
      const parsedId = escalationIdSchema.safeParse(escalationId);

      const parsedTransition = escalationTransitionRequestSchema.safeParse(transition);

      if (!parsedId.success || !parsedTransition.success) {
        return invalidRequest<EscalationUpdate>();
      }

      const terminal =
        parsedTransition.data.status === 'resolved' || parsedTransition.data.status === 'dismissed';

      const body = terminal
        ? {
            status: parsedTransition.data.status,
            customer_message: parsedTransition.data.customer_message,
          }
        : {
            status: parsedTransition.data.status,
          };

      /*
       * Non-terminal transitions omit customer_message completely.
       * Terminal transitions include the agent-written safe explanation.
       */
      const requestBody = body satisfies components['schemas']['UpdateEscalationRequest'];

      return request({
        path: `/v1/escalations/${parsedId.data}`,
        method: 'PATCH',
        authentication: 'bearer',
        body: {
          kind: 'json',
          value: requestBody,
        },
        decode(value) {
          const result = decodeEscalationUpdate(value);

          if (result.escalation_id !== parsedId.data) {
            throw SafeApiError.fromLocal('invalid-response');
          }

          return result;
        },
        ...requestSignal(signal),
      });
    },
  };
}
